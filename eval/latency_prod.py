"""Production latency from the server's own job timings (read-only), merged into the newest eval results JSON.

    uv run python -m eval.latency_prod              # query production, write + merge
    uv run python -m eval.latency_prod --dry-run    # query and print only
    uv run python -m eval.latency_prod --merge-only # re-merge eval/results/latency_production.json into the newest results

Source: jobs.stage_timings["total"] (ms spent in pipeline stages, written by app/modules/jobs/runner.py) joined
with documents.doc_type for finished `analyse_document` jobs. The SQL runs in a read-only session over
`ssh deploy@159.195.213.245 docker compose ... exec -T db psql`. For public uploads (the jury path),
end-to-end time (created -> finished, including queue wait) is reported too.
"""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.metrics import percentile  # noqa: E402

HOST = "deploy@159.195.213.245"
COMPOSE = ["docker", "compose", "-p", "converza", "--env-file", "/srv/converza/.env",
           "-f", "/srv/converza/repo/compose.prod.yml"]
RESULTS = ROOT / "eval" / "results"
STANDALONE = RESULTS / "latency_production.json"
SERVER = "4 vCPU, no GPU, 7.8 GiB RAM shared with other services; worker concurrency per WORKER_CONCURRENCY"

SQL = """
SELECT coalesce(json_agg(row_to_json(t)), '[]'::json) FROM (
  SELECT d.doc_type,
         CASE WHEN d.filename ILIKE '%.xlsx' OR d.mime LIKE '%spreadsheet%' THEN 'XLSX'
              WHEN d.mime LIKE 'image/%' THEN 'OCR (photo/image)'
              WHEN d.text_layer THEN 'PDF text layer'
              ELSE 'OCR (scanned PDF)' END AS path,
         d.owner_kind,
         (j.stage_timings->>'total')::numeric AS total_ms,
         round(extract(epoch FROM (j.finished_at - j.created_at)) * 1000) AS end_to_end_ms,
         j.finished_at
  FROM jobs j
  JOIN documents d ON j.ref = 'document:' || d.uuid::text
  WHERE j.kind = 'analyse_document' AND j.status = 'done'
    AND (j.stage_timings->>'total') IS NOT NULL
) t
"""


def query_production(host: str = HOST) -> list[dict]:
    remote = shlex.join(COMPOSE + ["exec", "-T", "db", "psql", "-U", "app", "app", "-qAt", "-v", "ON_ERROR_STOP=1",
                                   "-c", "SET default_transaction_read_only = on", "-c", " ".join(SQL.split())])
    out = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", host, remote],
                         capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise SystemExit(f"production query failed ({out.returncode}): {out.stderr.strip()[:500]}")
    line = next((ln for ln in out.stdout.splitlines() if ln.strip().startswith("[")), "[]")
    return json.loads(line)


def _row(label: dict, ms: list[float]) -> dict:
    return {**label, "documents": len(ms), "p50_ms": round(percentile(ms, 50)), "p95_ms": round(percentile(ms, 95)),
            "max_ms": round(max(ms))}


def summarise(rows: list[dict]) -> dict:
    by: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r in rows:
        by[(r["doc_type"], r["path"])].append(float(r["total_ms"]))
    table = [_row({"doc_type": dt, "path": p}, v) for (dt, p), v in sorted(by.items())]
    allv = [float(r["total_ms"]) for r in rows]
    if allv:
        table.append(_row({"doc_type": "all documents", "path": "all"}, allv))
    pub = [r for r in rows if r["owner_kind"] == "public"]
    public = []
    if pub:
        byp: dict[str, list[float]] = defaultdict(list)
        for r in pub:
            byp[r["path"]].append(float(r["end_to_end_ms"]))
        public = [_row({"path": p, "measure": "end-to-end (upload accepted -> result ready)"}, v) for p, v in sorted(byp.items())]
        public.append(_row({"path": "all", "measure": "end-to-end (upload accepted -> result ready)"},
                           [float(r["end_to_end_ms"]) for r in pub]))
    finished = [r["finished_at"] for r in rows if r.get("finished_at")]
    return {
        "server": "4 vCPU, no GPU",
        "server_detail": SERVER,
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "production jobs.stage_timings.total (ms in pipeline stages) for finished analyse_document jobs; "
                  "read-only SQL over ssh",
        "jobs_finished_between": [min(finished), max(finished)] if finished else None,
        "n_jobs": len(rows),
        "by_doc_type": table,
        "public_uploads_end_to_end": public,
        "jobs_by_owner_kind": {k: sum(1 for r in rows if r["owner_kind"] == k) for k in sorted({r["owner_kind"] for r in rows})},
        "note": "by_doc_type = processing time inside the pipeline stages for every finished document job (seeded "
                "bundles are processed in bulk, so their queue wait is not meaningful); public_uploads_end_to_end = "
                "uploads to /analyse, including queue wait.",
    }


def newest_results() -> Path | None:
    files = [p for p in RESULTS.glob("*.json") if p.name != STANDALONE.name]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def merge(lat: dict) -> Path | None:
    target = newest_results()
    if target is None:
        return None
    data = json.loads(target.read_text(encoding="utf-8"))
    data["latency_production"] = lat
    nm = data.get("not_measured")
    if isinstance(nm, list):
        data["not_measured"] = [x for x in nm if not str(x).lower().startswith("production latency")]
    target.write_text(json.dumps(data, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    return target


def main() -> None:
    ap = argparse.ArgumentParser(prog="eval.latency_prod")
    ap.add_argument("--dry-run", action="store_true", help="query and print; write nothing")
    ap.add_argument("--merge-only", action="store_true", help=f"merge {STANDALONE.relative_to(ROOT)} without querying")
    ap.add_argument("--host", default=HOST)
    a = ap.parse_args()
    if a.merge_only:
        lat = json.loads(STANDALONE.read_text(encoding="utf-8"))
    else:
        lat = summarise(query_production(a.host))
    print(json.dumps(lat, indent=1, ensure_ascii=False, default=str))
    if a.dry_run:
        return
    RESULTS.mkdir(parents=True, exist_ok=True)
    if not a.merge_only:
        STANDALONE.write_text(json.dumps(lat, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    target = merge(lat)
    if target:
        print(f"merged into {target.relative_to(ROOT)} under 'latency_production'")
    else:
        print(f"no eval results JSON yet; wrote {STANDALONE.relative_to(ROOT)} — run with --merge-only after eval.run")


if __name__ == "__main__":
    main()
