"""Render docs/EVAL.md and docs/KNOWN-FAILURES.md from an eval results JSON (default: the newest one).

    uv run python -m eval.report [--results eval/results/<file>.json] [--note "text"]...

Every number in the two documents is copied from the results file; nothing is computed here except
formatting.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "eval" / "results"


def latest_results() -> Path | None:
    files = sorted(p for p in RESULTS.glob("*.json") if p.is_file())
    return files[-1] if files else None


def _cell(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.4f}".rstrip("0").rstrip(".") if abs(v) < 10 else f"{v:,.1f}".replace(",", " ")
    if isinstance(v, int):
        return f"{v:,}".replace(",", " ")
    return str(v).replace("|", "\\|").replace("\n", " ")


def table(rows: list[dict], cols: list[str] | None = None, headers: dict[str, str] | None = None) -> str:
    if not rows:
        return "_none_\n"
    cols = cols or list(dict.fromkeys(k for r in rows for k in r))
    headers = headers or {}
    out = ["| " + " | ".join(headers.get(c, c.replace("_", " ")) for c in cols) + " |",
           "|" + "|".join("---:" if isinstance(rows[0].get(c), (int, float)) else "---" for c in cols) + "|"]
    for r in rows:
        out.append("| " + " | ".join(_cell(r.get(c)) for c in cols) + " |")
    return "\n".join(out) + "\n"


def kv(d: dict) -> str:
    return table([{"metric": k, "value": v} for k, v in d.items()], ["metric", "value"])


def render_eval(data: dict, src: str, notes: list[str]) -> str:
    h = []
    h.append("# Evaluation results\n")
    h.append(f"> **{data.get('caveat')}**\n")
    h.append(f"Source: `{src}` · generated {data.get('generated_at')} · git `{data.get('git_sha')}`  \n"
             f"Dataset: {data.get('dataset')}  \n{data.get('note', '')}\n")
    h.append("Regenerate: `uv run python -m eval.run --split test` then `uv run python -m eval.report`. "
             "Definitions: `eval/metrics.py`; failure list: [KNOWN-FAILURES.md](KNOWN-FAILURES.md).\n")
    if notes:
        h.append("## Notes on this run\n")
        h.extend(f"- {n}" for n in notes)
        h.append("")
    h.append("## Headline\n")
    h.append(kv(data.get("headline") or {}))
    h.append("## Field extraction (statutory forms and application form)\n")
    h.append("Unit = (document, line code, column). A wrong value counts as one FP and one FN; a *silent error* is a "
             "wrong value shown with confidence ≥ 0.80, i.e. without the \"needs clarification\" flag.\n")
    h.append(table(data.get("field_extraction") or [],
                   ["doc_type", "variant", "documents", "cells", "tp", "fp", "fn", "precision", "recall", "f1",
                    "silent_errors"]))
    h.append("By label language (Form 1 / Form 2):\n")
    h.append(table(data.get("field_extraction_by_label_language") or []))
    h.append("## Document type and period\n")
    h.append(table(data.get("document_type") or []))
    h.append(table(data.get("period_detection") or []))
    h.append("## Contradiction detection (rules R01–R12)\n")
    h.append("Unit = (bundle, rule). Planted = contradictions the generator put into the documents. A rule that "
             "fires on figures that were mis-extracted counts as a false positive.\n")
    h.append(table(data.get("contradiction_detection") or [],
                   ["rule", "planted", "fired", "tp", "fp", "fn", "precision", "recall", "f1"]))
    h.append("## Bank statements\n")
    h.append(table(data.get("categoriser") or []))
    h.append("Most frequent categorisation errors (production mode):\n")
    h.append(table(data.get("categoriser_confusions") or []))
    h.append("Recurring payments (group matched by statement rows, IoU ≥ 0.5):\n")
    h.append(kv(data.get("recurring_detection") or {}))
    h.append("Month-end balances:\n")
    h.append(kv(data.get("statement_month_end_balances") or {}))
    h.append("## Latency per document (laptop)\n")
    h.append(table(data.get("latency_laptop") or []))
    h.append(kv(data.get("latency_environment") or {}))
    h.append("## Hard cases\n")
    h.append(table(data.get("hard_cases") or [], ["id", "case", "expected", "result", "observed"]))
    if data.get("hard_case_field_extraction"):
        h.append("Field extraction on hard-case forms:\n")
        h.append(table(data["hard_case_field_extraction"]))
    h.append("## Not measured in this run\n")
    h.extend(f"- {x}" for x in data.get("not_measured") or [])
    h.append("")
    if data.get("crashes"):
        h.append("## Crashes\n")
        h.append(table(data["crashes"]))
    return "\n".join(h).rstrip() + "\n"


_EXPLAIN = [
    (r"columns swapped", "Current-period and prior-period values exchanged on a scan or photo, usually with high "
     "confidence: the most harmful class (wrong figures without a clarification flag; downstream R01/R02/R04 "
     "findings). Column detection on OCR pages is owned by the extraction stage."),
    (r"line not extracted", "The line is missing from the extracted table (recall loss, mostly 150-dpi scans and "
     "photos). Nothing is invented; the officer sees the gap."),
    (r"digits dropped|digit misread|wrong value|unit scale", "OCR read the number incorrectly. Low-confidence cases "
     "are flagged for clarification; the rest are silent errors counted in the headline."),
    (r"blank or absent cell", "A value was reported for a cell that is blank on the form (OCR noise or a value "
     "attached to the wrong line)."),
    (r"sign lost", "A negative value lost its sign (loss lines)."),
    (r"application field", "A loan-application field was not read (scans/photos) or read wrongly."),
    (r"statement category", "A statement row got another category. Vague purpose texts (\"Mablag' o'tkazish\", "
     "\"Перевод средств\") go to the clarification card as 'other'."),
    (r"recurring group", "A recurring payment group was not detected (too few months or an irregular day/amount)."),
    (r"rule R0?[0-9]+ fired", "Rule fired without a planted contradiction. On the synthetic data this is mostly a "
     "consequence of an upstream extraction error: the extracted figures really do not reconcile."),
    (r"rule R06 missed", "Undeclared-loan check stayed silent. When the application declares other debts but their "
     "contract numbers are not read from the form, R06 does not call any loan undeclared (precision first)."),
    (r"rule R0?[0-9]+ missed", "Planted contradiction not found, usually because an input figure was not extracted."),
    (r"classified as", "Document classified as another type; its figures are not used by that type's checks."),
    (r"period not detected", "Reporting period not detected correctly."),
    (r"hard case", "Hand-made hard case failed its automated check."),
    (r"crash", "Pipeline exception on this document."),
]


def _explain(failure: str) -> str:
    for rx, text in _EXPLAIN:
        if re.search(rx, failure, re.IGNORECASE):
            return text
    return ""


def render_failures(data: dict, src: str) -> str:
    rows = data.get("known_failures") or []
    h = ["# Known failure cases\n",
         f"Every failure class observed in `{src}` ({data.get('dataset')}), with a count and one example file. "
         f"Generated by `eval/report.py`; counts are units of the metric (cells, rows, bundles or documents).\n",
         f"> {data.get('caveat')}\n"]
    by_area: dict[str, list[dict]] = {}
    for r in rows:
        by_area.setdefault(r.get("area", "other"), []).append(r)
    n = 0
    for area in ("extraction", "classification", "statements", "categoriser", "reconciliation", "hard case",
                 "pipeline", "other"):
        items = by_area.get(area)
        if not items:
            continue
        h.append(f"## {area.capitalize()}\n")
        for r in items:
            n += 1
            h.append(f"{n}. **{r['failure']}** — {r['count']} × · example `{r['example']}`  ")
            if r.get("detail"):
                h.append(f"   Example detail: {r['detail']}  ")
            exp = _explain(r["failure"])
            if exp:
                h.append(f"   What it means: {exp}")
            h.append("")
    if not rows:
        h.append("No failures were observed in this run.\n")
    return "\n".join(h).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--results", default=None)
    ap.add_argument("--note", action="append", default=[])
    ap.add_argument("--eval-md", default=str(ROOT / "docs" / "EVAL.md"))
    ap.add_argument("--failures-md", default=str(ROOT / "docs" / "KNOWN-FAILURES.md"))
    args = ap.parse_args(argv)
    src = Path(args.results) if args.results else latest_results()
    if src is None or not src.exists():
        print("no results file; run eval.run first", file=sys.stderr)
        return 1
    data = json.loads(src.read_text(encoding="utf-8"))
    rel = str(src.resolve().relative_to(ROOT)) if src.resolve().is_relative_to(ROOT) else str(src)
    Path(args.eval_md).write_text(render_eval(data, rel, args.note), encoding="utf-8")
    Path(args.failures_md).write_text(render_failures(data, rel), encoding="utf-8")
    print(f"wrote {args.eval_md} and {args.failures_md} from {rel}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
