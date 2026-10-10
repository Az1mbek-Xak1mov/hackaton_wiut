"""Metric definitions (docs/plan/03-DATA.md §Metrics). Pure functions over truth.json and pipeline outputs.

Field extraction — unit = (document, line code, column):
    TP  extracted with |value − truth| ≤ tolerance (1 kUZS; a hard case may set `tolerance_kuzs`)
    FP  a wrong value (also counted as FN: the true value was not delivered), or a value for a cell that is
        blank or absent in the truth (an extracted 0 for a blank cell is not counted)
    FN  a truth cell that was not extracted correctly
    silent error = wrong value shown with confidence ≥ 0.80 (no "needs clarification" flag)
Contradiction detection — unit = (bundle, rule id): planted ∧ fired = TP, fired only = FP, planted only = FN.
Recurring detection — unit = recurring group; a detected group matches a truth group when their statement
    rows overlap with IoU ≥ 0.5 (names are not compared).
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict

TOL_KUZS = 1.0
SILENT_CONF = 0.80
APP_NUMERIC = {"requested_amount": 1.0, "term_months": 0.5, "rate_pct": 0.05, "declared_revenue_fy": 1.0,
               "declared_debts_total": 1.0}


def prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f1 = 2 * p * r / (p + r) if p and r else (0.0 if p is not None and r is not None else None)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": _r(p), "recall": _r(r), "f1": _r(f1)}


def _r(x: float | None, nd: int = 4) -> float | None:
    return None if x is None else round(float(x), nd)


def percentile(values: list[float], q: float) -> float | None:
    """Nearest-rank percentile (q in 0..100)."""
    v = sorted(values)
    if not v:
        return None
    k = max(1, math.ceil(q / 100.0 * len(v)))
    return v[k - 1]


# ---------------------------------------------------------------- statutory forms

def truth_cells(doc: dict) -> tuple[dict[tuple[str, str], float], set[tuple[str, str]]]:
    """{(code, col): value} for printed cells, and the set of blank cells."""
    cells: dict[tuple[str, str], float] = {}
    blank: set[tuple[str, str]] = set()
    for code, v in (doc.get("fields") or {}).items():
        for col in ("cur", "prev"):
            if v.get(col) is None:
                blank.add((str(code).zfill(3), col))
            else:
                cells[(str(code).zfill(3), col)] = float(v[col])
    for b in doc.get("blank_cells") or []:
        code, _, col = str(b).partition(".")
        blank.add((code.zfill(3), col))
    return cells, blank


def predicted_cells(facts: list, cur_label: str, prev_label: str) -> dict[tuple[str, str], object]:
    """{(code, col): fact} from extracted statutory facts; the column is read from the period label."""
    out: dict[tuple[str, str], object] = {}
    for f in facts:
        parts = (f.field or "").split(".")
        if len(parts) < 2 or parts[0] not in ("form1", "form2") or not parts[1].isdigit():
            continue
        lab = f.period_label or ""
        if lab in (cur_label, "cur"):
            col = "cur"
        elif lab in (prev_label, "prev"):
            col = "prev"
        else:
            col = "other"
        key = (parts[1].zfill(3), col)
        if key not in out or (f.confidence or 0) > (out[key].confidence or 0):
            out[key] = f
    return out


def score_form(doc: dict, facts: list, cur_label: str, prev_label: str, tol: float = TOL_KUZS) -> dict:
    cells, blank = truth_cells(doc)
    pred = predicted_cells(facts, cur_label, prev_label)
    tp = fp = fn = 0
    wrong = spurious = missing = silent = 0
    errors: list[dict] = []
    for key, f in pred.items():
        v = float(f.value)
        if key in cells:
            t = cells[key]
            if abs(v - t) <= tol:
                tp += 1
            else:
                fp += 1
                fn += 1
                wrong += 1
                conf = float(f.confidence or 0)
                if conf >= SILENT_CONF:
                    silent += 1
                other = cells.get((key[0], "prev" if key[1] == "cur" else "cur"))
                errors.append({"kind": classify_value_error(v, t, other), "code": key[0], "col": key[1],
                               "truth": t, "got": v, "conf": round(conf, 3)})
        elif key in blank and abs(v) < 0.5:
            continue
        else:
            fp += 1
            spurious += 1
            errors.append({"kind": "value for a blank or absent cell" if key[1] != "other" else
                           "unrecognised period label", "code": key[0], "col": key[1], "truth": None, "got": v,
                           "conf": round(float(f.confidence or 0), 3)})
    for key, t in cells.items():
        if key not in pred:
            fn += 1
            missing += 1
            errors.append({"kind": "line not extracted", "code": key[0], "col": key[1], "truth": t, "got": None,
                           "conf": None})
    return {**prf(tp, fp, fn), "cells": len(cells), "wrong": wrong, "spurious": spurious, "missing": missing,
            "silent_errors": silent, "errors": errors}


def classify_value_error(got: float, truth: float, other_col: float | None) -> str:
    if other_col is not None and abs(got - other_col) <= TOL_KUZS:
        return "current and prior-year columns swapped"
    if truth and abs(got + truth) <= TOL_KUZS:
        return "sign lost or inverted"
    if truth and got and (abs(got / truth - 1000) < 1 or abs(got / truth - 0.001) < 1e-6):
        return "unit scale error (x1000)"
    a, b = str(int(round(abs(got)))), str(int(round(abs(truth))))
    if len(a) == len(b) and sum(x != y for x, y in zip(a, b)) <= 2:
        return "OCR digit misread"
    if len(a) != len(b) and (a in b or b in a):
        return "digits dropped or merged"
    return "wrong value"


# ---------------------------------------------------------------- loan application

def score_application(doc: dict, facts: list) -> dict:
    by = {}
    for f in facts:
        if f.field.startswith("application."):
            by[f.field.split(".", 1)[1]] = f
    tp = fp = fn = 0
    errors = []
    for name, tol in APP_NUMERIC.items():
        tv = (doc.get("fields") or {}).get(name)
        if tv is None or tv.get("value") is None:
            if name in by and abs(float(by[name].value)) > tol:
                fp += 1
                errors.append({"kind": "application field not in the form", "code": name, "truth": None,
                               "got": float(by[name].value)})
            continue
        t = float(tv["value"])
        f = by.get(name)
        if f is None:
            fn += 1
            errors.append({"kind": "application field not extracted", "code": name, "truth": t, "got": None})
        elif abs(float(f.value) - t) <= tol:
            tp += 1
        else:
            fp += 1
            fn += 1
            errors.append({"kind": "application field wrong value", "code": name, "truth": t, "got": float(f.value)})
    return {**prf(tp, fp, fn), "cells": sum(1 for n in APP_NUMERIC if ((doc.get("fields") or {}).get(n) or {})
                                            .get("value") is not None), "errors": errors}


# ---------------------------------------------------------------- statements

def score_categories(truth_rows: list[dict], txns: list, predictions: dict[str, dict[int, str]]) -> dict:
    """predictions: mode -> {row_n: category}. Returns per-mode (y_true, y_pred) lists for later pooling."""
    labels = {r["row"]: r["category"] for r in truth_rows if r.get("category")}
    out = {}
    for mode, pred in predictions.items():
        yt, yp = [], []
        for row, cat in pred.items():
            if row in labels:
                yt.append(labels[row])
                yp.append(cat)
        out[mode] = (yt, yp)
    return out


def classification_scores(y_true: list[str], y_pred: list[str]) -> dict:
    if not y_true:
        return {"rows": 0, "accuracy": None, "macro_f1": None}
    acc = sum(a == b for a, b in zip(y_true, y_pred)) / len(y_true)
    labels = sorted(set(y_true))
    f1s = []
    for lab in labels:
        tp = sum(1 for a, b in zip(y_true, y_pred) if a == lab and b == lab)
        fp = sum(1 for a, b in zip(y_true, y_pred) if a != lab and b == lab)
        fn = sum(1 for a, b in zip(y_true, y_pred) if a == lab and b != lab)
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        f1s.append(2 * p * r / (p + r) if p + r else 0.0)
    return {"rows": len(y_true), "accuracy": _r(acc), "macro_f1": _r(sum(f1s) / len(f1s))}


def confusion_pairs(y_true: list[str], y_pred: list[str], top: int = 8) -> list[tuple[tuple[str, str], int]]:
    return Counter((a, b) for a, b in zip(y_true, y_pred) if a != b).most_common(top)


def score_recurring(truth_rows: list[dict], txns: list) -> dict:
    truth_g: dict[str, set[int]] = defaultdict(set)
    for r in truth_rows:
        if r.get("recurring_group"):
            truth_g[r["recurring_group"]].add(r["row"])
    pred_g: dict[str, set[int]] = defaultdict(set)
    for t in txns:
        if t.recurring_group:
            pred_g[t.recurring_group].add(t.row_n)
    matched_truth: set[str] = set()
    tp = fp = 0
    for g, rows in pred_g.items():
        best = max(((len(rows & tr) / len(rows | tr), tg) for tg, tr in truth_g.items()), default=(0.0, None))
        if best[0] >= 0.5 and best[1] not in matched_truth:
            tp += 1
            matched_truth.add(best[1])
        else:
            fp += 1
    fn = len(truth_g) - len(matched_truth)
    return {"tp": tp, "fp": fp, "fn": fn, "truth_groups": len(truth_g), "detected_groups": len(pred_g),
            "missed": sorted(set(truth_g) - matched_truth)}


def score_balances(truth_tr: dict, facts: list) -> dict:
    exp = truth_tr.get("month_end_balances") or {}
    by = {f.field.rsplit(".", 1)[1]: f for f in facts if f.field.startswith("statement.balance_end.")}
    exact = sum(1 for ym, v in exp.items() if ym in by and abs(by[ym].value - v / 1000.0) <= 0.5)
    return {"months": len(exp), "exact": exact}


# ---------------------------------------------------------------- rules

def score_rules(bundles: list[tuple[set[str], set[str]]], rule_ids: list[str]) -> list[dict]:
    per = {r: [0, 0, 0, 0, 0] for r in rule_ids}   # planted, fired, tp, fp, fn
    for fired, planted in bundles:
        for r in set(fired) | set(planted):
            row = per.setdefault(r, [0, 0, 0, 0, 0])
            row[0] += r in planted
            row[1] += r in fired
            if r in fired and r in planted:
                row[2] += 1
            elif r in fired:
                row[3] += 1
            else:
                row[4] += 1
    out = []
    for r in sorted(per):
        planted, fired, tp, fp, fn = per[r]
        out.append({"rule": r, "planted": planted, "fired": fired, **prf(tp, fp, fn)})
    tp = sum(x["tp"] for x in out)
    fp = sum(x["fp"] for x in out)
    fn = sum(x["fn"] for x in out)
    out.append({"rule": "micro (all rules)", "planted": sum(x["planted"] for x in out),
                "fired": sum(x["fired"] for x in out), **prf(tp, fp, fn)})
    return out


def variant_of(doc: dict) -> str:
    v = doc.get("variant") or {}
    if v.get("photo"):
        return "phone photo"
    if v.get("scan"):
        return f"scan {v.get('dpi')} dpi"
    return "text layer"
