"""Statutory line codes used by rules, ratios and monitoring (matched on form + code, never on slug).

Arithmetic relations (R02/R03) come from `app/pipeline/dictionary/forms.yaml` (`sum_of`) when it exists;
the built-in fallback below covers only relations that hold on the official Form 1 / Form 2 templates.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

# Form 1 — balance sheet
F1_INVENTORY = "140"
F1_RECEIVABLES = "210"
F1_TRADE_RECEIVABLES = "220"
F1_CASH = "320"
F1_LT_ASSETS_TOTAL = "130"
F1_CURRENT_ASSETS = "390"
F1_TOTAL_ASSETS = "400"
F1_RETAINED_EARNINGS = "450"
F1_EQUITY_TOTAL = "480"
F1_LT_LIABILITIES = "490"
F1_LT_BANK_LOANS = "570"
F1_CURRENT_LIABILITIES = "600"
F1_PAYABLES_SUPPLIERS = "610"
F1_ST_BANK_LOANS = "730"
F1_LIABILITIES_TOTAL = "770"
F1_TOTAL_PASSIVE = "780"

# Form 2 — financial results
F2_REVENUE = "010"
F2_COGS = "020"
F2_GROSS_PROFIT = "030"
F2_PERIOD_EXPENSES = "040"
F2_FINANCE_COSTS = "170"      # finance costs total (the design's "line 120" is dividend income on the official form)
F2_INTEREST_EXPENSE = "180"
F2_PRE_TAX_PROFIT = "240"
F2_PROFIT_TAX = "250"
F2_NET_PROFIT = "270"

DICTIONARY_PATH = Path(__file__).resolve().parents[1] / "dictionary" / "forms.yaml"

# (form, parent, [(child, sign)])  — official-template relations only
_FALLBACK_RELATIONS: list[tuple[str, str, list[tuple[str, int]]]] = [
    ("form1", "400", [("130", 1), ("390", 1)]),
    ("form1", "780", [("480", 1), ("770", 1)]),
    ("form1", "770", [("490", 1), ("600", 1)]),
    ("form2", "030", [("010", 1), ("020", -1)]),
    ("form2", "270", [("240", 1), ("250", -1), ("260", -1)]),
]


def _child(c) -> tuple[str, int]:
    s = str(c).strip()
    sign = 1
    if s.startswith("-") or s.startswith("−"):
        sign, s = -1, s[1:].strip()
    elif s.startswith("+"):
        s = s[1:].strip()
    return s.zfill(3) if s.isdigit() else s, sign


@lru_cache(maxsize=4)
def _load_dictionary(path: str, mtime: float) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if isinstance(data, dict):
        for k in ("lines", "entries", "items"):
            if isinstance(data.get(k), list):
                return data[k]
        out: list[dict] = []
        for form, rows in data.items():
            if isinstance(rows, list):
                for r in rows:
                    if isinstance(r, dict):
                        out.append({"form": r.get("form", form), **r})
        return out
    return data if isinstance(data, list) else []


def dictionary_entries() -> list[dict]:
    p = DICTIONARY_PATH
    if not p.exists():
        return []
    try:
        return _load_dictionary(str(p), p.stat().st_mtime)
    except Exception:  # a broken dictionary must not break reconciliation
        return []


def sum_relations() -> list[tuple[str, str, list[tuple[str, int]]]]:
    """[(form, parent_code, [(child_code, sign)])]. A child's own `sign: -1` in the dictionary means it is
    subtracted in its parent (e.g. accumulated depreciation, treasury shares, cost of sales)."""
    entries = dictionary_entries()
    if not entries:
        return list(_FALLBACK_RELATIONS)
    signs: dict[tuple[str, str], int] = {}
    for e in entries:
        form, code = str(e.get("form", "")), str(e.get("code", "")).zfill(3)
        try:
            signs[(form, code)] = -1 if int(e.get("sign", 1)) < 0 else 1
        except (TypeError, ValueError):
            signs[(form, code)] = 1
    rels = []
    for e in entries:
        kids = e.get("sum_of")
        if not kids or not isinstance(kids, list):
            continue
        form, parent = str(e.get("form", "")), str(e.get("code", "")).zfill(3)
        children = []
        for c in kids:
            code, sign = _child(c)
            if sign == 1:
                sign = signs.get((form, code), 1)
            children.append((code, sign))
        if children:
            rels.append((form, parent, children))
    return rels or list(_FALLBACK_RELATIONS)


def label_for(form: str, code: str) -> str | None:
    """English label from the dictionary (UI wording), if available."""
    for e in dictionary_entries():
        if str(e.get("form")) == form and str(e.get("code", "")).zfill(3) == code:
            labels = e.get("labels") or {}
            en = labels.get("en")
            if isinstance(en, list) and en:
                return str(en[0])
            if isinstance(en, str):
                return en
            return e.get("label") or e.get("field")
    return None
