"""Recurring-payment detection over categorised outflows (loans, salaries, taxes, rent…).

A group is recurring when it has payments in ≥ 3 distinct months, the payment day of month varies by
≤ 3 days (std) and the monthly total varies by ≤ 15% (coefficient of variation). Principal and interest
paid as two transactions in the same month are summed per month first.
"""
from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict
from datetime import date

from app.pipeline.rules.periods import add_months
from app.pipeline.statements.categorise import CATEGORY_LABELS
from app.pipeline.statements.text import find_contract, norm
from app.pipeline.types import TxnDraft

RECURRING_CATEGORIES = {"loan_repayment", "salary", "payroll_tax", "tax", "rent_utilities", "supplier_payment"}
MIN_MONTHS = 3
MAX_DAY_STD = 3.0
MAX_CV = 0.15


def counterparty_key(t: TxnDraft) -> str:
    if t.counterparty_stir:
        return t.counterparty_stir
    name = norm(t.counterparty)
    name = re.sub(r"\b(mchj|ooo|ооо|мчж|xk|ao|ат|aj|ltd|llc|чп|ип)\b", " ", name)
    name = re.sub(r"[^\w]+", " ", name).strip()
    return name[:40] or "unknown"


_SUBTYPES: dict[str, list[tuple[str, re.Pattern]]] = {
    "payroll_tax": [
        ("payroll:pit", re.compile(r"(ндфл|подоходн|доход\w*\s+физ|jshds|daromad\s+soli|jismoniy\s+shaxs|income\s+tax|pit\b)")),
        ("payroll:social", re.compile(r"(социальн|соц\.?\s*налог|инпс|ijtimoiy|social|пенсион|pension)")),
    ],
    "tax": [
        ("tax:vat", re.compile(r"(ндс|qqs|vat|добавленн|qo.shilgan\s+qiymat)")),
        ("tax:profit", re.compile(r"(прибыл|foyda|profit)")),
        ("tax:property", re.compile(r"(имуществ|mol-mulk|property|земельн|yer\s+soli)")),
    ],
    "rent_utilities": [
        ("rent", re.compile(r"(аренд|ijara|ижара|\brent)")),
        ("util:electricity", re.compile(r"(электр|elektr|electric)")),
        ("util:gas", re.compile(r"(газ|gaz|\bgas\b)")),
        ("util:water", re.compile(r"(вод|suv|water|канализ|oqova)")),
        ("util:heat", re.compile(r"(тепл|issiqlik|heat)")),
        ("util:telecom", re.compile(r"(связ|internet|интернет|telefon|aloqa)")),
    ],
}
_INTEREST = re.compile(r"(процент|foiz|interest)")
_PRINCIPAL = re.compile(r"(основн|asosiy|principal|кредит[ау]?\s+по\s+договор|kreditni\s+qaytar|погашение\s+кредита)")


def _group_key(t: TxnDraft) -> tuple[str, str | None]:
    """Group names follow the generator's truth labels: salary, payroll:social|pit, rent, util:<kind>, tax:<kind>,
    loan:<contract>[:interest], <category>:<counterparty>."""
    text = norm(t.purpose)
    if t.category == "loan_repayment":
        no, _ = find_contract(t.purpose)
        base = f"loan:{no}" if no else f"loan:{counterparty_key(t)}"
        if _INTEREST.search(text) and not _PRINCIPAL.search(text):
            return base + ":interest", no
        return base, no
    if t.category == "salary":
        return "salary", None
    for key, rx in _SUBTYPES.get(t.category, []):
        if rx.search(text):
            return key, None
    if t.category == "payroll_tax":
        return "payroll:other", None
    if t.category == "rent_utilities":
        return f"util:{counterparty_key(t)}", None
    if t.category == "supplier_payment":
        return f"supplier:{counterparty_key(t)}", None
    return f"{t.category}:{counterparty_key(t)}", None


def _label(category: str, contract_no: str | None, counterparty: str) -> str:
    if category == "loan_repayment":
        base = f"Loan repayments, contract {contract_no}" if contract_no else "Loan repayments"
        return f"{base} ({counterparty})" if counterparty else base
    if category in ("salary", "payroll_tax"):
        return CATEGORY_LABELS[category]
    return f"{CATEGORY_LABELS.get(category, category)}: {counterparty}" if counterparty else CATEGORY_LABELS.get(category, category)


_KEY_LABELS = {
    "payroll:pit": "Personal income tax withheld", "payroll:social": "Social tax", "payroll:other": "Payroll taxes",
    "tax:vat": "VAT", "tax:profit": "Profit tax", "tax:property": "Property and land tax", "rent": "Rent",
    "util:electricity": "Electricity", "util:gas": "Gas", "util:water": "Water", "util:heat": "Heating",
    "util:telecom": "Telecom and internet",
}


def _key_label(key: str, category: str, contract_no: str | None, counterparty: str) -> str:
    if key in _KEY_LABELS:
        base = _KEY_LABELS[key]
        return f"{base}: {counterparty}" if counterparty and key in ("rent",) or key.startswith("util:") and counterparty \
            else base
    return _label(category, contract_no, counterparty)


def _month(t: TxnDraft) -> str:
    return f"{t.booked_on.year:04d}-{t.booked_on.month:02d}"


def _stats(items: list[TxnDraft]) -> dict | None:
    by_month: dict[str, list[TxnDraft]] = defaultdict(list)
    for t in items:
        by_month[_month(t)].append(t)
    if len(by_month) < MIN_MONTHS:
        return None
    months = sorted(by_month)
    sums = [sum(-t.amount for t in by_month[m]) for m in months]
    days = [max(by_month[m], key=lambda t: -t.amount).booked_on.day for m in months]
    mean = statistics.fmean(sums)
    if mean <= 0:
        return None
    cv = statistics.pstdev(sums) / mean if len(sums) > 1 else 0.0
    day_std = statistics.pstdev(days) if len(days) > 1 else 0.0
    if cv > MAX_CV or day_std > MAX_DAY_STD:
        return None
    return {"months": months, "sums": dict(zip(months, sums)), "days": days, "cv": cv, "day_std": day_std}


def _entry(key: str, items: list[TxnDraft], sums: dict[str, float], days: list[int], cv: float, day_std: float,
           contract_no: str | None) -> dict:
    category = items[0].category
    months = sorted(sums)
    contract_date = None
    if contract_no:
        for t in items:
            no, d = find_contract(t.purpose)
            if no == contract_no and d:
                contract_date = d
                break
    cp_names = Counter(t.counterparty.strip() for t in items if t.counterparty and t.counterparty.strip())
    counterparty = cp_names.most_common(1)[0][0] if cp_names else ""
    stirs = Counter(t.counterparty_stir for t in items if t.counterparty_stir)
    day = int(round(statistics.median(days)))
    last = max(t.booked_on for t in items)
    first = min(t.booked_on for t in items)
    nxt = add_months(date(last.year, last.month, 1), 1)
    try:
        next_due = date(nxt.year, nxt.month, day)
    except ValueError:
        next_due = add_months(date(last.year, last.month, min(day, 28)), 1)
    monthly = statistics.median(sums[m] for m in months)
    return {
        "group": key,
        "label": _key_label(key, category, contract_no, counterparty),
        "category": category,
        "count": len(months),                      # months with a payment
        "payments": len(items),                    # individual transactions
        "amount": round(monthly / 1000.0, 3),      # typical monthly total, kUZS
        "amount_uzs": round(monthly, 2),
        "total": round(sum(sums.values()) / 1000.0, 3),
        "day_of_month": day,
        "first_date": first,
        "last_date": last,
        "next_due": next_due,
        "months": months,
        "contract_no": contract_no,
        "contract_date": contract_date,
        "counterparty": counterparty,
        "counterparty_stir": stirs.most_common(1)[0][0] if stirs else None,
        "row_ns": sorted(t.row_n for t in items),
        "cv": round(cv, 4),
        "day_std": round(day_std, 2),
    }


def detect_recurring(txns: list[TxnDraft]) -> list[dict]:
    """Recurring groups. `t.recurring_group` gets the fine-grained key (e.g. loan:2024-1177:interest); the returned
    list merges a loan's principal and interest groups into one entry per contract (key loan:<contract>)."""
    groups: dict[str, list[TxnDraft]] = defaultdict(list)
    contracts: dict[str, Counter] = defaultdict(Counter)
    for t in txns:
        if t.amount >= 0 or t.category not in RECURRING_CATEGORIES:
            continue
        key, contract = _group_key(t)
        groups[key].append(t)
        if contract:
            contracts[key][contract] += 1

    # loan rows without a contract number join the contract group of the same lender, if there is one
    for key in [k for k in groups if k.startswith("loan:") and not contracts.get(k)]:
        lender = counterparty_key(groups[key][0])
        suffix = ":interest" if key.endswith(":interest") else ""
        for other, items in groups.items():
            if other != key and other.startswith("loan:") and contracts.get(other) and other.endswith(suffix) \
                    and (suffix or not other.endswith(":interest")) and counterparty_key(items[0]) == lender:
                groups[other].extend(groups[key])
                groups[key] = []
                break

    recurring: dict[str, dict] = {}
    for key, items in groups.items():
        if not items:
            continue
        st = _stats(items)
        if st is None:
            continue
        for t in items:
            t.recurring_group = key
        recurring[key] = st

    out: list[dict] = []
    loans: dict[str, list[str]] = defaultdict(list)
    for key in recurring:
        if key.startswith("loan:"):
            loans[key[: -len(":interest")] if key.endswith(":interest") else key].append(key)
            continue
        st = recurring[key]
        contract = contracts[key].most_common(1)[0][0] if contracts.get(key) else None
        out.append(_entry(key, groups[key], st["sums"], st["days"], st["cv"], st["day_std"], contract))
    for base, keys in loans.items():
        items = [t for k in keys for t in groups[k]]
        sums: dict[str, float] = defaultdict(float)
        for k in keys:
            for m, v in recurring[k]["sums"].items():
                sums[m] += v
        main = base if base in recurring else keys[0]
        cnt = Counter()
        for k in keys:
            cnt.update(contracts.get(k, Counter()))
        contract = cnt.most_common(1)[0][0] if cnt else None
        e = _entry(base, items, dict(sums), recurring[main]["days"], recurring[main]["cv"], recurring[main]["day_std"],
                   contract)
        e["subgroups"] = sorted(keys)
        out.append(e)
    out.sort(key=lambda g: (g["category"] != "loan_repayment", -g["amount"]))
    return out
