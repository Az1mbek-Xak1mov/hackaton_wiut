"""Run the real pipeline over generated bundles and hard cases, compare with truth.json, write a results JSON.

    uv run python -m eval.run --split test [--limit N] [--workers N] [--no-hard] [--out PATH]
    uv run python -m eval.run --split hard

Pipeline functions are called directly (no database): parse_document → extract_forms / extract_application /
normalise_statement → run_application_rules → compute_ratios → template narrative + verifier.
Inputs the bank already knows are given as such: the borrower STIR and the application date.
The output file (eval/results/<date>_<time>_<git-sha7>.json) is what /metrics renders; every number on the
metrics page and slides comes from it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
import traceback
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval import metrics as M  # noqa: E402

CAVEAT = ("Measured on our synthetic generator's test split and hand-made hard cases; overstates real-document "
          "accuracy; real-document evaluation is pilot month 1.")
RULE_IDS = [f"R{i:02d}" for i in range(1, 13)]
FORM_TYPES = ("form1", "form2")


# ------------------------------------------------------------------ helpers

def _git_sha() -> tuple[str, bool]:
    try:
        sha = subprocess.run(["git", "rev-parse", "--short=7", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                             timeout=10).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT,
                                    capture_output=True, text=True, timeout=10).stdout.strip())
        return sha or "nogit", dirty
    except Exception:
        return "nogit", True


def _to_date(v) -> date | None:
    if not v:
        return None
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _truth_period(d: dict) -> tuple[date | None, date | None]:
    p = d.get("period")
    if isinstance(p, dict):
        return _to_date(p.get("start")), _to_date(p.get("end"))
    return None, None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _rel(p: Path) -> str:
    try:
        return str(p.resolve().relative_to(ROOT))
    except ValueError:
        return str(p)


def _statement_truth(truth: dict, filename: str) -> dict | None:
    tr = truth.get("transactions")
    trs = tr if isinstance(tr, list) else ([tr] if isinstance(tr, dict) else [])
    for t in trs:
        if t.get("file") == filename:
            return t
    return None


# ------------------------------------------------------------------ one bundle (runs in a worker process)

def run_bundle(bundle_dir: str, kind: str) -> dict:
    """kind = synth | hard. Returns a JSON-safe dict of per-document results and bundle-level outcomes."""
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")
    from app.pipeline.classify import period_labels
    from app.pipeline.extract_application import extract_application
    from app.pipeline.extract_forms import extract_forms
    from app.pipeline.narrative import template_narrative
    from app.pipeline.parse import parse_document
    from app.pipeline.ratios import compute_ratios
    from app.pipeline.rules import AppContext, run_application_rules
    from app.pipeline.statements import normalise_statement
    from app.pipeline.statements.categorise import Categoriser, MODEL_MIN_PROB, rule_category
    from app.pipeline.verify import verify

    bdir = Path(bundle_dir)
    truth = json.loads((bdir / "truth.json").read_text(encoding="utf-8"))
    company = truth.get("company") or {}
    stir = company.get("stir")
    out: dict = {"bundle": bdir.name, "kind": kind, "dir": _rel(bdir), "docs": [], "fired": [], "planted": [],
                 "cat": {}, "rec": None, "bal": None, "crash": None, "narrative_ok": None, "findings": []}
    out["planted"] = sorted({p["rule"] for p in truth.get("planted") or [] if p.get("rule")})
    cat = Categoriser()
    all_facts, all_txns, all_rec, docs_ctx, fact_doc = [], [], [], [], {}
    tol = float(truth.get("tolerance_kuzs") or M.TOL_KUZS)
    with tempfile.TemporaryDirectory(prefix="eval-") as tmp:
        for i, d in enumerate(truth.get("documents") or []):
            path = bdir / d["file"]
            rec: dict = {"file": d["file"], "path_rel": _rel(path), "truth_type": d.get("doc_type"),
                         "variant": M.variant_of(d), "language": d.get("language")}
            if not path.exists():
                rec["missing_file"] = True
                out["docs"].append(rec)
                continue
            t0 = time.perf_counter()
            facts, txns, recurring = [], [], []
            try:
                parsed = parse_document(str(path), out_dir=f"{tmp}/{i}", filename=d["file"])
                if parsed.doc_type in FORM_TYPES:
                    facts, _unmapped = extract_forms(parsed)
                elif parsed.doc_type == "loan_application":
                    facts = extract_application(parsed)
                elif parsed.doc_type == "bank_statement":
                    txns, facts, recurring = normalise_statement(parsed, stir, cat)
            except Exception as exc:  # a crash is a result, not a reason to stop the run
                rec["crash"] = f"{exc.__class__.__name__}: {exc}"[:300]
                rec["traceback"] = traceback.format_exc(limit=3)[-800:]
                rec["ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
                out["docs"].append(rec)
                continue
            rec["ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
            rec.update(pred_type=parsed.doc_type, kind=parsed.kind, pages=len(parsed.pages),
                       failure_cause=parsed.failure_cause, partial=parsed.partial, n_facts=len(facts),
                       pred_period=[str(parsed.period_start) if parsed.period_start else None,
                                    str(parsed.period_end) if parsed.period_end else None])
            ts, te = _truth_period(d)
            if te is not None:
                if d.get("doc_type") == "bank_statement":   # statements: the months covered
                    ps, pe = parsed.period_start, parsed.period_end
                    rec["period_ok"] = bool(ps and pe and ts and (ps.year, ps.month) == (ts.year, ts.month)
                                            and (pe.year, pe.month) == (te.year, te.month))
                else:
                    rec["period_ok"] = (parsed.period_end == te) and (ts is None or d.get("doc_type") == "form1"
                                                                       or parsed.period_start == ts)
            tt = d.get("doc_type")
            if tt in FORM_TYPES and d.get("fields") is not None:
                form_facts = facts if parsed.doc_type == tt else []
                cur, prev = period_labels(tt, parsed.period_start, parsed.period_end)
                sc = M.score_form(d, form_facts, cur, prev, tol)
                rec["fields"] = {k: v for k, v in sc.items() if k != "errors"}
                rec["errors"] = sc["errors"][:40]
            elif tt == "loan_application" and d.get("fields"):
                sc = M.score_application(d, facts if parsed.doc_type == tt else [])
                rec["fields"] = {k: v for k, v in sc.items() if k != "errors"}
                rec["errors"] = sc["errors"]
            if parsed.doc_type == "bank_statement" or tt == "bank_statement":
                st = _statement_truth(truth, d["file"])
                rec["transactions"] = len(txns)
                if st and st.get("rows"):
                    rows = st["rows"]
                    prod = {t.row_n: t.category for t in txns}
                    rules = {}
                    model = {}
                    for t in txns:
                        if stir and t.counterparty_stir and t.counterparty_stir == stir:
                            rules[t.row_n] = "own_transfer"
                        else:
                            rules[t.row_n] = rule_category(t.purpose, t.counterparty, t.amount) or "other"
                        if cat.has_model:
                            c, p = cat.model_predict(t.purpose, t.counterparty, t.amount)
                            model[t.row_n] = c if p >= MODEL_MIN_PROB else "other"
                    preds = {"rules then model (production)": prod, "rules only": rules}
                    if model:
                        preds["model only"] = model
                    scored = M.score_categories(rows, txns, preds)
                    out["cat"] = {mode: [list(yt), list(yp)] for mode, (yt, yp) in scored.items()}
                    out["rec"] = M.score_recurring(rows, txns)
                    out["bal"] = M.score_balances(st, facts)
                    truth_rows = {r["row"] for r in rows}
                    rec["rows_parsed"] = len(txns)
                    rec["rows_truth"] = len(truth_rows)
                    rec["rows_missing"] = len(truth_rows - {t.row_n for t in txns})
                    by_row = {t.row_n: t for t in txns}
                    rec["category_errors"] = [
                        {"row": r["row"], "truth": r["category"], "got": by_row[r["row"]].category,
                         "purpose": by_row[r["row"]].purpose[:90]}
                        for r in rows if r["row"] in by_row and by_row[r["row"]].category != r["category"]][:20]
                if isinstance(d.get("rows"), list):   # hard case H11: currency per row
                    uzs = {r["row"] for r in d["rows"] if str(r.get("currency", "UZS")).upper() == "UZS"}
                    usd = {r["row"] for r in d["rows"] if str(r.get("currency", "UZS")).upper() != "UZS"}
                    kept = {t.row_n for t in txns}
                    rec["currency_check"] = {"uzs_rows": len(uzs), "uzs_kept": len(uzs & kept),
                                             "foreign_rows": len(usd), "foreign_kept": len(usd & kept)}
            if isinstance(d.get("rows"), dict):   # hard case H15: English statement keyed by label
                printed = [float(v[c]) for v in d["rows"].values() for c in ("cur", "prev") if v.get(c) is not None]
                vals = [float(f.value) for f in facts]
                rec["label_check"] = {"facts": len(vals),
                                      "match_printed": sum(1 for v in vals if any(abs(v - p) <= 1 for p in printed)),
                                      "not_printed": sum(1 for v in vals if not any(abs(v - p) <= 1 for p in printed)
                                                         and abs(v) > 0.5),
                                      "max_conf": max([float(f.confidence or 0) for f in facts], default=None)}
            out["docs"].append(rec)
            all_facts.extend(facts)
            all_txns.extend(txns)
            all_rec.extend(recurring)
            for f in facts:
                if f.key:
                    fact_doc[f.key] = d["file"]
            docs_ctx.append({"uuid": d["file"], "filename": d["file"], "doc_type": parsed.doc_type,
                             "period_start": parsed.period_start, "period_end": parsed.period_end,
                             "stir": parsed.stir, "sha256": _sha256(path)})

        run_rules = kind == "synth" or bool(truth.get("planted")) or "application_declares_debts" in truth
        if run_rules:
            app = {"received_on": truth.get("received"), "borrower_stir": stir}
            if "application_declares_debts" in truth:
                app["declared_debts"] = list(truth["application_declares_debts"])
            try:
                t0 = time.perf_counter()
                ctx = AppContext(facts=all_facts, transactions=all_txns, documents=docs_ctx, application=app,
                                 recurring=all_rec, fact_document=fact_doc)
                findings = run_application_rules(ctx)
                ratios = compute_ratios(ctx)
                out["rules_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
                out["fired"] = sorted({f.rule_id for f in findings})
                out["findings"] = [{"rule": f.rule_id, "title": f.title, "detail": f.detail[:240]} for f in findings]
                md = template_narrative(ctx, findings, ratios)
                facts_all = {**ctx.index.by_key, **{f.key: f for f in ratios}}
                out["narrative_ok"] = bool(verify(md, facts_all)["ok"])
            except Exception as exc:
                out["crash"] = f"rules: {exc.__class__.__name__}: {exc}"[:300]
    return out


# ------------------------------------------------------------------ hard-case checks

def _doc(res: dict, i: int = 0) -> dict:
    docs = res.get("docs") or []
    return docs[i] if len(docs) > i else {}


def _f1(doc: dict) -> float | None:
    return (doc.get("fields") or {}).get("f1")


def hard_check(case: dict, res: dict) -> tuple[bool, str]:
    cid = case["id"]
    d = _doc(res)
    flds = d.get("fields") or {}
    if d.get("crash"):
        return False, f"crashed: {d['crash']}"
    if cid in ("H01", "H04", "H05", "H08", "H09", "H10"):
        ok = (_f1(d) or 0) >= 0.95 and flds.get("silent_errors", 0) == 0
        return ok, f"type {d.get('pred_type')}; field F1 {_f1(d)}; silent errors {flds.get('silent_errors')}"
    if cid == "H02":
        ok = flds.get("silent_errors", 1) == 0
        return ok, f"field F1 {_f1(d)}; wrong values without a low-confidence flag: {flds.get('silent_errors')}"
    if cid == "H03":
        signs = sum(1 for e in d.get("errors") or [] if e["kind"] == "sign lost or inverted")
        return signs == 0 and (_f1(d) or 0) >= 0.95, f"sign errors {signs}; field F1 {_f1(d)}"
    if cid == "H06":
        prev_spurious = sum(1 for e in d.get("errors") or [] if e["kind"].startswith("value for a blank") and
                            e["col"] == "prev")
        return prev_spurious == 0 and (flds.get("recall") or 0) >= 0.95, \
            f"values invented for the blank prior-year column: {prev_spurious}; recall {flds.get('recall')}"
    if cid == "H07":
        return (_f1(d) or 0) >= 0.95 and flds.get("spurious", 1) == 0, \
            f"field F1 {_f1(d)}; values for absent cells {flds.get('spurious')}"
    if cid == "H11":
        c = d.get("currency_check") or {}
        ok = bool(c) and c["foreign_kept"] == 0 and c["uzs_kept"] == c["uzs_rows"]
        return ok, (f"UZS rows kept {c.get('uzs_kept')} of {c.get('uzs_rows')}; foreign-currency rows kept in UZS "
                    f"aggregates {c.get('foreign_kept')} of {c.get('foreign_rows')}") if c else "no currency check"
    if cid in ("H12", "H14"):
        yt, yp = (res.get("cat") or {}).get("rules then model (production)", [[], []])
        if cid == "H14":
            pairs = [(a, b) for a, b in zip(yt, yp) if a == "salary"]
            ok = bool(pairs) and all(a == b for a, b in pairs)
            return ok, f"salary rows categorised as salary: {sum(a == b for a, b in pairs)} of {len(pairs)}"
        sc = M.classification_scores(yt, yp)
        return (sc["accuracy"] or 0) >= 0.9, f"categoriser accuracy {sc['accuracy']} on {sc['rows']} rows"
    if cid == "H13":
        return "R06" in res.get("fired", []), f"rules fired: {', '.join(res.get('fired') or []) or 'none'}"
    if cid == "H15":
        c = d.get("label_check") or {}
        ok = c.get("not_printed", 1) == 0 and (d.get("pred_type") not in FORM_TYPES or (c.get("max_conf") or 0) < 0.95)
        return ok, (f"classified as {d.get('pred_type')}; {c.get('facts')} values reported, {c.get('match_printed')} "
                    f"match a printed value, {c.get('not_printed')} do not; highest confidence {c.get('max_conf')}")
    if cid == "H16":
        cause = (d.get("failure_cause") or "")
        return "encrypt" in cause.lower(), f"failure cause: {cause or 'none'}"
    if cid == "H17":
        nonzero = sum(1 for e in d.get("errors") or [] if e["kind"].startswith("value for a blank") and e["got"])
        return nonzero == 0, f"non-zero values reported on an all-zero form: {nonzero}"
    if cid == "H18":
        return "R12" in res.get("fired", []), f"rules fired: {', '.join(res.get('fired') or []) or 'none'}"
    if cid == "H19":
        cause = d.get("failure_cause") or ""
        return bool(cause), f"failure cause: {cause or 'none'}; facts {d.get('n_facts')}"
    if cid == "H20":
        ok = d.get("pred_type") == "unknown" and not d.get("n_facts")
        return ok, f"classified as {d.get('pred_type')}; facts {d.get('n_facts')}"
    return False, "no automated check for this case"


# ------------------------------------------------------------------ aggregation

def _field_rows(docs: list[dict], by_variant: bool = True) -> list[dict]:
    acc: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0, 0, 0, 0, 0])  # docs tp fp fn cells silent
    for d in docs:
        f = d.get("fields")
        if not f:
            continue
        keys = [(d["truth_type"], "all")]
        if by_variant:
            keys.append((d["truth_type"], d.get("variant") or "text layer"))
        for k in keys:
            a = acc[k]
            a[0] += 1
            a[1] += f["tp"]
            a[2] += f["fp"]
            a[3] += f["fn"]
            a[4] += f.get("cells", 0)
            a[5] += f.get("silent_errors", 0)
    order = {"all": 0, "text layer": 1, "scan 300 dpi": 2, "scan 150 dpi": 3, "phone photo": 4}
    rows = []
    for (dt, var), a in sorted(acc.items(), key=lambda kv: (kv[0][0], order.get(kv[0][1], 9), kv[0][1])):
        rows.append({"doc_type": dt, "variant": var, "documents": a[0], "cells": a[4],
                     **{k: v for k, v in M.prf(a[1], a[2], a[3]).items()}, "silent_errors": a[5]})
    return rows


def _language_rows(docs: list[dict]) -> list[dict]:
    acc: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    for d in docs:
        f = d.get("fields")
        if not f or d["truth_type"] not in FORM_TYPES:
            continue
        a = acc[(d["truth_type"], d.get("language") or "?")]
        a[0] += 1
        a[1] += f["tp"]
        a[2] += f["fp"]
        a[3] += f["fn"]
    return [{"doc_type": dt, "label_language": lang, "documents": a[0], **M.prf(a[1], a[2], a[3])}
            for (dt, lang), a in sorted(acc.items())]


def _doctype_rows(docs: list[dict]) -> list[dict]:
    by: dict[str, list] = defaultdict(list)
    for d in docs:
        if d.get("truth_type") and "pred_type" in d:
            by[d["truth_type"]].append(d["pred_type"])
    rows = []
    for tt, preds in sorted(by.items()):
        wrong = Counter(p for p in preds if p != tt)
        rows.append({"truth_type": tt, "documents": len(preds), "correct": sum(p == tt for p in preds),
                     "accuracy": round(sum(p == tt for p in preds) / len(preds), 4),
                     "most_common_error": (f"{wrong.most_common(1)[0][0]} ×{wrong.most_common(1)[0][1]}"
                                           if wrong else "—")})
    return rows


def _period_rows(docs: list[dict]) -> list[dict]:
    by: dict[str, list[bool]] = defaultdict(list)
    for d in docs:
        if "period_ok" in d:
            by[d["truth_type"]].append(bool(d["period_ok"]))
    return [{"doc_type": k, "documents": len(v), "correct": sum(v), "accuracy": round(sum(v) / len(v), 4)}
            for k, v in sorted(by.items())]


def _latency_rows(docs: list[dict]) -> list[dict]:
    by: dict[tuple[str, str], list[float]] = defaultdict(list)
    for d in docs:
        if d.get("ms") is None or not d.get("kind"):
            continue
        path = {"pdf_text": "PDF text layer", "pdf_scan": "OCR (scanned PDF)", "image": "OCR (photo/image)",
                "xlsx": "XLSX"}.get(d["kind"], d["kind"])
        by[(d.get("truth_type") or "?", path)].append(d["ms"])
    rows = []
    for (dt, path), v in sorted(by.items()):
        rows.append({"doc_type": dt, "path": path, "documents": len(v), "p50_ms": round(M.percentile(v, 50)),
                     "p95_ms": round(M.percentile(v, 95)), "max_ms": round(max(v))})
    allv = [d["ms"] for d in docs if d.get("ms") is not None and d.get("kind")]
    if allv:
        rows.append({"doc_type": "all documents", "path": "all", "documents": len(allv),
                     "p50_ms": round(M.percentile(allv, 50)), "p95_ms": round(M.percentile(allv, 95)),
                     "max_ms": round(max(allv))})
    return rows


def _known_failures(results: list[dict], hard: list[dict]) -> list[dict]:
    classes: dict[str, dict] = {}

    def add(key: str, example: str, detail: str, area: str) -> None:
        c = classes.setdefault(key, {"area": area, "failure": key, "count": 0, "example": example, "detail": detail})
        c["count"] += 1

    for r in results:
        for d in r["docs"]:
            ex = d.get("path_rel", d.get("file"))
            if d.get("crash"):
                add(f"pipeline crash ({d['crash'].split(':')[0]})", ex, d["crash"][:160], "pipeline")
            if d.get("pred_type") and d.get("truth_type") and d["pred_type"] != d["truth_type"] and \
                    d["truth_type"] not in ("unknown_or_non_statutory",):
                add(f"document type {d['truth_type']} classified as {d['pred_type']}", ex,
                    f"variant: {d.get('variant')}; reason: {(d.get('failure_cause') or '')[:120]}", "classification")
            if d.get("period_ok") is False:
                add(f"{d['truth_type']}: reporting period not detected correctly", ex,
                    f"detected {d.get('pred_period')}", "classification")
            for e in d.get("errors") or []:
                add(f"{d['truth_type']}: {e['kind']}", ex,
                    f"line {e.get('code')} {e.get('col', '')}: truth {e.get('truth')}, extracted {e.get('got')} "
                    f"(confidence {e.get('conf')}); variant {d.get('variant')}", "extraction")
            for e in d.get("category_errors") or []:
                add(f"statement category {e['truth']} → {e['got']}", ex, f"row {e['row']}: {e['purpose']}",
                    "categoriser")
        planted, fired = set(r.get("planted") or []), set(r.get("fired") or [])
        for rule in fired - planted:
            if r["kind"] == "synth":
                det = next((f"{f['title']}: {f['detail']}" for f in r.get("findings") or [] if f["rule"] == rule), "")
                add(f"rule {rule} fired without a planted contradiction (false positive)", r["dir"], det[:200],
                    "reconciliation")
        for rule in planted - fired:
            add(f"rule {rule} missed a planted contradiction (false negative)", r["dir"], "", "reconciliation")
        if r.get("rec") and r["rec"].get("missed"):
            for g in r["rec"]["missed"]:
                add(f"recurring group not detected: {g.split(':')[0]}", r["dir"], g, "statements")
    for h in hard:
        if h["result"] != "pass":
            add(f"hard case {h['id']} ({h['case']})", h["example"], h["observed"], "hard case")
    rows = sorted(classes.values(), key=lambda c: (-c["count"], c["failure"]))
    return rows


def aggregate(results: list[dict], hard_results: list[dict], hard_index: list[dict], split: str, workers: int,
              wall_s: float) -> dict:
    synth = [r for r in results if r["kind"] == "synth"]
    sdocs = [d for r in synth for d in r["docs"]]
    hdocs = [d for r in hard_results for d in r["docs"]]
    sha, dirty = _git_sha()

    cat_modes: dict[str, list[list[str]]] = defaultdict(lambda: [[], []])
    rec_tot = [0, 0, 0]
    bal = [0, 0]
    for r in synth:
        for mode, (yt, yp) in (r.get("cat") or {}).items():
            cat_modes[mode][0].extend(yt)
            cat_modes[mode][1].extend(yp)
        if r.get("rec"):
            rec_tot[0] += r["rec"]["tp"]
            rec_tot[1] += r["rec"]["fp"]
            rec_tot[2] += r["rec"]["fn"]
        if r.get("bal"):
            bal[0] += r["bal"]["months"]
            bal[1] += r["bal"]["exact"]
    categoriser = [{"mode": m, **M.classification_scores(*v)} for m, v in
                   sorted(cat_modes.items(), key=lambda kv: kv[0] != "rules then model (production)")]
    prod = cat_modes.get("rules then model (production)", [[], []])
    confusions = [{"truth": a, "predicted": b, "rows": n} for (a, b), n in M.confusion_pairs(prod[0], prod[1])]
    rules = M.score_rules([(set(r["fired"]), set(r["planted"])) for r in synth], RULE_IDS)
    micro = rules[-1]

    by_id = {c["id"]: c for c in hard_index}
    hard_rows = []
    for r in sorted(hard_results, key=lambda x: x["bundle"]):
        case = by_id.get(r["bundle"], {"id": r["bundle"], "case": "", "expected": ""})
        ok, observed = hard_check(case, r)
        hard_rows.append({"id": case["id"], "case": case.get("case", ""), "expected": case.get("expected", ""),
                          "result": "pass" if ok else "fail", "observed": observed,
                          "example": (r["docs"][0].get("path_rel") if r.get("docs") else r["dir"])})

    fields = _field_rows(sdocs)
    lat = _latency_rows(sdocs)

    def f1_of(dt: str) -> float | None:
        return next((x["f1"] for x in fields if x["doc_type"] == dt and x["variant"] == "all"), None)

    dt_rows = _doctype_rows(sdocs)
    dt_all = (sum(x["correct"] for x in dt_rows) / sum(x["documents"] for x in dt_rows)) if dt_rows else None
    narr = [r["narrative_ok"] for r in synth if r.get("narrative_ok") is not None]
    headline = {
        "Form 1 field F1": f1_of("form1"),
        "Form 2 field F1": f1_of("form2"),
        "Loan application field F1": f1_of("loan_application"),
        "Wrong values shown without a low-confidence flag": sum(x["silent_errors"] for x in fields if x["variant"] == "all"),
        "Document type accuracy": round(dt_all, 4) if dt_all is not None else None,
        "Contradiction detection precision (micro)": micro["precision"],
        "Contradiction detection recall (micro)": micro["recall"],
        "Categoriser accuracy (production: rules then model)": categoriser[0]["accuracy"] if categoriser else None,
        "Categoriser macro-F1 (production)": categoriser[0]["macro_f1"] if categoriser else None,
        "Recurring payment detection precision": M.prf(*rec_tot)["precision"],
        "Recurring payment detection recall": M.prf(*rec_tot)["recall"],
        "Template narratives passing the citation verifier": f"{sum(narr)} of {len(narr)}",
        "Hard cases passed": f"{sum(1 for h in hard_rows if h['result'] == 'pass')} of {len(hard_rows)}",
        "Latency p50 per document, laptop (ms)": next((x["p50_ms"] for x in lat if x["doc_type"] == "all documents"), None),
        "Latency p95 per document, laptop (ms)": next((x["p95_ms"] for x in lat if x["doc_type"] == "all documents"), None),
    }
    bundles = sorted(r["bundle"] for r in synth)
    dataset = (f"synthetic {split} split: {len(synth)} bundles ({bundles[0]}–{bundles[-1]}), {len(sdocs)} documents"
               if synth else "no synthetic bundles") + (f"; hard cases: {len(hard_rows)}" if hard_rows else "")
    out = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "git_sha": sha + ("-dirty" if dirty else ""),
        "split": split,
        "dataset": dataset,
        "n_bundles": len(synth),
        "n_documents": len(sdocs),
        "caveat": CAVEAT,
        "note": ("Pipeline functions called directly (no database, LLM off). Borrower STIR and application date "
                 "are given as known to the bank. Definitions: eval/metrics.py and docs/EVAL.md."),
        "headline": headline,
        "field_extraction": fields,
        "field_extraction_by_label_language": _language_rows(sdocs),
        "document_type": dt_rows,
        "period_detection": _period_rows(sdocs),
        "contradiction_detection": rules,
        "categoriser": categoriser,
        "categoriser_confusions": confusions,
        "recurring_detection": {**M.prf(*rec_tot)},
        "statement_month_end_balances": {"months": bal[0], "exact": bal[1],
                                         "accuracy": round(bal[1] / bal[0], 4) if bal[0] else None},
        "latency_laptop": lat,
        "latency_environment": {"machine": f"{platform.system()} {platform.machine()}", "cpu_threads": os.cpu_count(),
                                "parallel_workers": workers, "omp_thread_limit": os.environ.get("OMP_THREAD_LIMIT", "1"),
                                "wall_clock_s": round(wall_s, 1),
                                "note": "laptop, documents processed in parallel; production latency comes from server job timings"},
        "hard_cases": [{k: v for k, v in h.items() if k != "example"} for h in hard_rows],
        "hard_case_field_extraction": _field_rows(hdocs, by_variant=False),
        "known_failures": _known_failures(synth, hard_rows),
        "not_measured": [
            "LLM narrative acceptance and token cost: this run uses the LLM off (template narrative); cost per "
            "application in UZS comes from production llm_calls",
            "Production latency: added from server job timings",
            "Real-document accuracy: pilot month 1 on anonymised bank files",
        ],
        "crashes": [{"bundle": r["bundle"], "file": d.get("file"), "error": d.get("crash")}
                    for r in results + hard_results for d in r["docs"] if d.get("crash")]
                   + [{"bundle": r["bundle"], "file": "", "error": r["crash"]} for r in results + hard_results
                      if r.get("crash")],
    }
    return out


# ------------------------------------------------------------------ main

def discover(split: str, limit: int | None, with_hard: bool) -> tuple[list[tuple[str, str]], list[dict]]:
    jobs: list[tuple[str, str]] = []
    if split != "hard":
        dirs = sorted(p.parent for p in (ROOT / "data" / "synth" / split).glob("*/truth.json"))
        if limit:
            dirs = dirs[:limit]
        jobs += [(str(d), "synth") for d in dirs]
    hard_index: list[dict] = []
    if split == "hard" or with_hard:
        idx = ROOT / "data" / "hard" / "index.json"
        hard_index = json.loads(idx.read_text(encoding="utf-8")) if idx.exists() else []
        jobs += [(str(p.parent), "hard") for p in sorted((ROOT / "data" / "hard").glob("H*/truth.json"))]
    return jobs, hard_index


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Evaluate the pipeline against generated truth")
    ap.add_argument("--split", default="test", choices=["test", "dev", "hard", "train"])
    ap.add_argument("--limit", type=int, default=None, help="first N synthetic bundles only")
    ap.add_argument("--workers", type=int, default=max(1, min(6, (os.cpu_count() or 2) // 2)))
    ap.add_argument("--no-hard", action="store_true", help="skip data/hard")
    ap.add_argument("--out", default=None, help="results JSON path (default eval/results/<date>_<time>_<sha>.json)")
    ap.add_argument("--raw", default=None, help="also write per-document raw results to this path")
    args = ap.parse_args(argv)
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")

    jobs, hard_index = discover(args.split, args.limit, not args.no_hard)
    if not jobs:
        print(f"no bundles found for split {args.split}", file=sys.stderr)
        return 1
    t0 = time.perf_counter()
    results: list[dict] = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(run_bundle, d, k): (d, k) for d, k in jobs}
        for i, fut in enumerate(as_completed(futs), 1):
            d, k = futs[fut]
            try:
                results.append(fut.result())
            except Exception as exc:
                results.append({"bundle": Path(d).name, "kind": k, "dir": _rel(Path(d)), "docs": [], "fired": [],
                                "planted": [], "crash": f"{exc.__class__.__name__}: {exc}"[:300]})
            if i % 10 == 0 or i == len(jobs):
                print(f"{i}/{len(jobs)} bundles  {time.perf_counter() - t0:.0f}s", file=sys.stderr)
    wall = time.perf_counter() - t0
    synth = [r for r in results if r["kind"] == "synth"]
    hard = [r for r in results if r["kind"] == "hard"]
    data = aggregate(synth, hard, hard_index, args.split, args.workers, wall)

    sha, _ = _git_sha()
    out = Path(args.out) if args.out else ROOT / "eval" / "results" / \
        f"{datetime.now():%Y-%m-%d_%H%M}_{sha}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    if args.raw:
        Path(args.raw).write_text(json.dumps(results, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps(data["headline"], indent=1, ensure_ascii=False))
    print(f"wrote {_rel(out)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
