"""Bank statement (xlsx) → transactions, aggregate facts and recurring payment groups."""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from app.pipeline.compute import new_fact_key
from app.pipeline.rules.periods import month_end, months_between, parse_period
from app.pipeline.statements.categorise import CATEGORY_LABELS, Categoriser
from app.pipeline.statements.recurring import detect_recurring
from app.pipeline.statements.text import (
    ACCOUNT_RE, MFO_RE, STIR_LABELLED_RE, STIR_RE, cell_text, norm, parse_amount, parse_date,
)
from app.pipeline.types import FactDraft, ParsedDoc, TxnDraft, XlsxSheet

HEADER_SCAN_ROWS = 30

# role → header pattern (normalised text); checked in this order
_ROLE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("stir", re.compile(r"(^|[^\w])(инн|стир|stir|inn|tin)([^\w]|$)")),
    ("mfo", re.compile(r"(^|[^\w])(мфо|mfo)([^\w]|$)")),
    ("debit", re.compile(r"(дебет|debet|debit|расход|chiqim|списан|outflow|withdraw)")),
    ("credit", re.compile(r"(кредит|kredit|credit|приход|kirim|поступлен|зачислен|inflow|deposit)")),
    ("balance", re.compile(r"(остаток|qoldiq|қолдиқ|balance|сальдо)")),
    ("date", re.compile(r"(дата|sana|сана|date)")),
    ("purpose", re.compile(r"(назначени|maqsad|mazmun|мақсад|мазмун|purpose|description|details|детали|основани|содержани)")),
    ("counterparty", re.compile(r"(контрагент|корреспондент|наименовани|получател|плательщик|kontragent|"
                                r"korrespondent|to.lovchi|oluvchi|nomi|номи|тўловчи|олувчи|counterparty|payee|payer|beneficiar|name)")),
    ("account", re.compile(r"(сч[её]т|р/с|hisob\s*raqam|hisobvaraq|ҳисоб\s*рақам|ҳисобварақ|account)")),
    ("currency", re.compile(r"(валют|valyuta|currency)")),
    ("doc_no", re.compile(r"(№|номер|hujjat|ҳужжат|doc)")),
    ("amount", re.compile(r"(сумма|summa|amount)")),
]
_ROLE_RX = dict(_ROLE_PATTERNS)
_NAME_HINT = re.compile(r"(наимен|nomi|номи|name)")

_OPENING = re.compile(r"(входящ\w*\s+остат|остат\w*\s+на\s+начал|сальдо\s+на\s+начал|начальн\w*\s+остат|"
                      r"kirish\s+qoldi|davr\s+boshi\w*\s+qoldi|boshlang.ich\s+qoldi|opening\s+balance|balance\s+at\s+start)")
_CLOSING = re.compile(r"(исходящ\w*\s+остат|остат\w*\s+на\s+конец|сальдо\s+на\s+конец|конечн\w*\s+остат|"
                      r"chiqish\s+qoldi|davr\s+oxiri\w*\s+qoldi|yakuniy\s+qoldi|closing\s+balance|balance\s+at\s+end)")
_TOTALS = re.compile(r"(итого|jami|всего|total|оборот|обороты)")


@dataclass
class HeaderMatch:
    sheet: XlsxSheet
    row: int                    # 0-based index of the (first) header row
    rows_used: int              # 1 or 2
    columns: dict[str, int] = field(default_factory=dict)
    score: int = 0


def _role(cell: str) -> str | None:
    t = norm(cell)
    if not t:
        return None
    for role, rx in _ROLE_PATTERNS:
        if rx.search(t):
            if role in ("counterparty", "account"):
                has_cp = _ROLE_RX["counterparty"].search(t)
                has_acc = _ROLE_RX["account"].search(t)
                if has_cp and has_acc:
                    return "counterparty" if _NAME_HINT.search(t) else "account"
            return role
    return None


def _score(cells: list[str]) -> tuple[int, dict[str, int]]:
    cols: dict[str, int] = {}
    for i, c in enumerate(cells):
        r = _role(c)
        if r and r not in cols:
            cols[r] = i
    has_money = any(k in cols for k in ("debit", "credit", "amount"))
    score = len(cols) if ("date" in cols and has_money) else 0
    return score, cols


def detect_header(sheet: XlsxSheet) -> HeaderMatch | None:
    best: HeaderMatch | None = None
    rows = sheet.rows
    for i in range(min(HEADER_SCAN_ROWS, len(rows))):
        a = [cell_text(c) for c in rows[i]]
        if not any(a):
            continue
        s1, c1 = _score(a)
        cand = HeaderMatch(sheet, i, 1, c1, s1)
        if i + 1 < len(rows):
            b = [cell_text(c) for c in rows[i + 1]]
            width = max(len(a), len(b))
            comb = [((a[j] if j < len(a) else "") + " " + (b[j] if j < len(b) else "")).strip() for j in range(width)]
            s2, c2 = _score(comb)
            # a second header row adds roles without looking like data (no dates, few numbers)
            nonempty = [c for c in rows[i + 1] if c not in (None, "")]
            b_is_data = any(parse_date(c) for c in nonempty) or \
                sum(1 for c in nonempty if isinstance(c, (int, float)) or parse_amount(c) is not None) >= 2
            if s2 > s1 and not b_is_data:
                cand = HeaderMatch(sheet, i, 2, c2, s2)
        if cand.score >= 3 and (best is None or cand.score > best.score):
            best = cand
    return best


def _row_text(row: list) -> str:
    return " ".join(cell_text(c) for c in row if c not in (None, ""))


def _last_number(row: list) -> float | None:
    for c in reversed(row):
        v = parse_amount(c) if not isinstance(c, (date,)) else None
        if v is not None and not (isinstance(c, str) and parse_date(c)):
            return v
    return None


def _scan_balances(rows: list[list]) -> tuple[float | None, float | None]:
    opening = closing = None
    for r in rows:
        t = norm(_row_text(r))
        if not t:
            continue
        if opening is None and _OPENING.search(t):
            opening = _last_number(r)
        elif _CLOSING.search(t):
            closing = _last_number(r)
    return opening, closing


def _header_stir(rows: list[list], header_row: int) -> str | None:
    for r in rows[:header_row]:
        m = STIR_LABELLED_RE.search(_row_text(r))
        if m:
            return m.group(1)
    return None


def _cell(row: list, cols: dict[str, int], role: str):
    i = cols.get(role)
    if i is None or i >= len(row):
        return None
    return row[i]


def parse_transactions(doc: ParsedDoc, own_stir: str | None, categoriser: Categoriser | None = None
                       ) -> tuple[list[TxnDraft], dict]:
    """Returns (transactions, meta) where meta has sheet, header row, opening/closing balance, balances by row."""
    best: HeaderMatch | None = None
    for sh in doc.sheets:
        h = detect_header(sh)
        if h and (best is None or h.score > best.score):
            best = h
    meta: dict = {"sheet": None, "header_row": None, "opening": None, "closing": None, "balance_by_row": {},
                  "skipped_rows": 0, "foreign_currency_rows": 0}
    if best is None:
        return [], meta
    cat = categoriser or Categoriser()
    rows, cols = best.sheet.rows, best.columns
    meta.update(sheet=best.sheet.name, header_row=best.row + 1)
    opening, closing = _scan_balances(rows)
    meta.update(opening=opening, closing=closing)
    own = own_stir or doc.stir or _header_stir(rows, best.row)
    meta["own_stir"] = own
    if own and not doc.stir:
        doc.stir = own
    txns: list[TxnDraft] = []
    for i in range(best.row + best.rows_used, len(rows)):
        row = rows[i]
        d = parse_date(_cell(row, cols, "date"))
        if d is None:
            continue
        text_all = norm(_row_text(row))
        if _TOTALS.search(text_all) and not cell_text(_cell(row, cols, "purpose")):
            continue
        cur = norm(cell_text(_cell(row, cols, "currency"))) if "currency" in cols else ""
        money_text = " ".join(norm(cell_text(_cell(row, cols, r))) for r in ("debit", "credit", "amount") if r in cols)
        if (cur and not re.search(r"(uzs|сум|so.m|860|^$)", cur)) or re.search(r"(usd|eur|rub|\$|€)", money_text):
            meta["foreign_currency_rows"] += 1
            continue
        debit = parse_amount(_cell(row, cols, "debit")) if "debit" in cols else None
        credit = parse_amount(_cell(row, cols, "credit")) if "credit" in cols else None
        if debit is None and credit is None and "amount" in cols:
            amt = parse_amount(_cell(row, cols, "amount"))
        else:
            amt = (credit or 0.0) - abs(debit or 0.0)
        if amt is None or abs(amt) < 0.005:
            meta["skipped_rows"] += 1
            continue
        cp_raw = cell_text(_cell(row, cols, "counterparty"))
        purpose = cell_text(_cell(row, cols, "purpose"))
        stir_cell = cell_text(_cell(row, cols, "stir"))
        stir = None
        m = STIR_RE.search(stir_cell) if stir_cell else None
        if m:
            stir = m.group(1)
        if stir is None:
            m = STIR_LABELLED_RE.search(cp_raw) or STIR_LABELLED_RE.search(purpose)
            if m:
                stir = m.group(1)
        if stir is None and cp_raw:
            m = STIR_RE.search(cp_raw)
            if m:
                stir = m.group(1)
        acc_cell = cell_text(_cell(row, cols, "account"))
        m = ACCOUNT_RE.search(acc_cell) or ACCOUNT_RE.search(cp_raw)
        account = m.group(1) if m else None
        counterparty = cp_raw
        if counterparty:
            counterparty = STIR_LABELLED_RE.sub(" ", counterparty)
            counterparty = ACCOUNT_RE.sub(" ", counterparty)
            counterparty = MFO_RE.sub(" ", counterparty)
            counterparty = re.sub(r"\s+", " ", counterparty.replace("\n", " ")).strip(" ,;")
        category, source, conf = cat.categorise(purpose, counterparty, amt, stir, own)
        txns.append(TxnDraft(row_n=i + 1, booked_on=d, amount=round(amt, 2), counterparty=counterparty,
                             counterparty_stir=stir, account=account, purpose=purpose, category=category,
                             category_source=source, category_conf=conf))
        if "balance" in cols:
            b = parse_amount(_cell(row, cols, "balance"))
            if b is not None:
                meta["balance_by_row"][i + 1] = b
    return txns, meta


# ---------------------------------------------------------------- aggregates

def _ym(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _month_human(ym: str) -> str:
    return parse_period(ym).human()


def _rows_note(rows: list[int]) -> str:
    rows = sorted(rows)
    shown = ", ".join(str(r) for r in rows[:20])
    return f"rows: {shown}" + (f" … (+{len(rows) - 20})" if len(rows) > 20 else "")


def _agg_fact(field: str, label: str, value_uzs: float, period: str, rows: list[int], sheet: str,
              conf: float = 1.0, note_extra: str = "") -> FactDraft:
    rows = sorted(rows)
    passage = f"rows {rows[0]}–{rows[-1]} of {sheet}" if rows else f"sheet {sheet}"
    note = _rows_note(rows) + (f"; {note_extra}" if note_extra else "")
    return FactDraft(field=field, label=label, value=round(value_uzs / 1000.0, 3), unit="kUZS", kind="aggregate",
                     period_label=period, page_n=None, passage=passage, confidence=round(conf, 3),
                     method="aggregate", note=note, key=new_fact_key())


def _weighted_conf(items: list[TxnDraft]) -> float:
    tot = sum(abs(t.amount) for t in items)
    if tot <= 0:
        return 1.0
    return min(1.0, sum(abs(t.amount) * (t.category_conf or 0.0) for t in items) / tot)


def build_aggregates(txns: list[TxnDraft], meta: dict, recurring: list[dict]) -> list[FactDraft]:
    if not txns:
        return []
    sheet = meta.get("sheet") or "statement"
    facts: list[FactDraft] = []
    first, last = min(t.booked_on for t in txns), max(t.booked_on for t in txns)
    months = months_between(first, last)
    by_month_cat_in: dict[tuple[str, str], list[TxnDraft]] = defaultdict(list)
    by_month_cat_out: dict[tuple[str, str], list[TxnDraft]] = defaultdict(list)
    by_month_in: dict[str, list[TxnDraft]] = defaultdict(list)
    by_month_out: dict[str, list[TxnDraft]] = defaultdict(list)
    for t in txns:
        ym = _ym(t.booked_on)
        if t.amount >= 0:
            by_month_cat_in[(ym, t.category)].append(t)
            by_month_in[ym].append(t)
        else:
            by_month_cat_out[(ym, t.category)].append(t)
            by_month_out[ym].append(t)

    for (ym, c), items in sorted(by_month_cat_in.items()):
        facts.append(_agg_fact(f"statement.inflow.{c}.{ym}", f"{CATEGORY_LABELS.get(c, c)}, {_month_human(ym)}",
                               sum(t.amount for t in items), ym, [t.row_n for t in items], sheet, _weighted_conf(items)))
    for (ym, c), items in sorted(by_month_cat_out.items()):
        facts.append(_agg_fact(f"statement.outflow.{c}.{ym}", f"{CATEGORY_LABELS.get(c, c)} paid, {_month_human(ym)}",
                               -sum(t.amount for t in items), ym, [t.row_n for t in items], sheet, _weighted_conf(items)))
    for ym in months:
        ins, outs = by_month_in.get(ym, []), by_month_out.get(ym, [])
        if ins:
            facts.append(_agg_fact(f"statement.inflow.total.{ym}", f"Total inflows, {_month_human(ym)}",
                                   sum(t.amount for t in ins), ym, [t.row_n for t in ins], sheet))
        if outs:
            facts.append(_agg_fact(f"statement.outflow.total.{ym}", f"Total outflows, {_month_human(ym)}",
                                   -sum(t.amount for t in outs), ym, [t.row_n for t in outs], sheet))

    # month-end balances: balance column, else opening + cumulative, else closing − later movements
    bal_rows: dict[int, float] = meta.get("balance_by_row") or {}
    opening, closing = meta.get("opening"), meta.get("closing")
    ordered = sorted(txns, key=lambda t: (t.booked_on, t.row_n))
    for ym in months:
        in_month = [t for t in ordered if _ym(t.booked_on) == ym]
        if not in_month:
            continue
        last_t = in_month[-1]
        value = None
        how = ""
        if bal_rows:
            cands = [t for t in in_month if t.row_n in bal_rows]
            if cands:
                lt = max(cands, key=lambda t: (t.booked_on, t.row_n))
                value, how = bal_rows[lt.row_n], f"balance column, row {lt.row_n}"
        if value is None and opening is not None:
            upto = [t for t in ordered if _ym(t.booked_on) <= ym]
            value = opening + sum(t.amount for t in upto)
            how = "opening balance + movements"
        if value is None and closing is not None:
            after = [t for t in ordered if _ym(t.booked_on) > ym]
            value = closing - sum(t.amount for t in after)
            how = "closing balance − later movements"
        if value is not None:
            y, m = int(ym[:4]), int(ym[5:])
            f = _agg_fact(f"statement.balance_end.{ym}", f"Account balance, end of {_month_human(ym)}", value, ym,
                          [last_t.row_n], sheet, note_extra=how)
            f.period_label = month_end(y, m).isoformat()
            facts.append(f)

    sales = [t for t in txns if t.amount > 0 and t.category == "sales_receipt"]
    if sales and months:
        span = f"{months[0]}..{months[-1]}"
        f = _agg_fact("statement.avg_monthly_inflow", f"Average monthly customer receipts, {_month_human(months[0])}–"
                      f"{_month_human(months[-1])}", sum(t.amount for t in sales) / len(months), span,
                      [t.row_n for t in sales], sheet, _weighted_conf(sales), note_extra=f"{len(months)} months")
        facts.append(f)
        facts.append(_agg_fact("statement.inflow.sales_receipt.total", f"Customer receipts, {_month_human(months[0])}–"
                               f"{_month_human(months[-1])}", sum(t.amount for t in sales), span,
                               [t.row_n for t in sales], sheet, _weighted_conf(sales)))

    for g in recurring:
        span = f"{g['months'][0]}..{g['months'][-1]}"
        rows = g["row_ns"]
        if g["category"] == "loan_repayment":
            gid = g["group"]
            lbl = f"{g['label']}, monthly (day {g['day_of_month']})"
            fm = _agg_fact(f"statement.loan_repayment.monthly.{gid}", lbl, g["amount_uzs"], span, rows, sheet)
            fc = _agg_fact(f"statement.loan_repayment.count.{gid}", f"{g['label']}: payments", 0, span, rows, sheet)
            fc.value, fc.unit = float(g["count"]), "count"
            ft = _agg_fact(f"statement.loan_repayment.total.{gid}", f"{g['label']}: total paid", g["total"] * 1000.0,
                           span, rows, sheet)
            facts.extend([fm, fc, ft])
            g["fact_keys"] = {"monthly": fm.key, "count": fc.key, "total": ft.key}
            g["evidence"] = [fm.key, fc.key, ft.key]
        else:
            fm = _agg_fact(f"statement.recurring.monthly.{g['group']}", f"{g['label']}, monthly (day {g['day_of_month']})",
                           g["amount_uzs"], span, rows, sheet)
            facts.append(fm)
            g["fact_keys"] = {"monthly": fm.key}
            g["evidence"] = [fm.key]
    return facts


def normalise_statement(doc: ParsedDoc, own_stir: str | None = None, categoriser: Categoriser | None = None
                        ) -> tuple[list[TxnDraft], list[FactDraft], list[dict]]:
    """xlsx statement → (transactions, aggregate facts in kUZS, recurring groups).

    Side effects on `doc`: sets period_start/period_end (first/last transaction date) and stir (account owner)
    when they are not already set. Each recurring group dict gets `fact_keys` pointing at its facts.
    """
    txns, meta = parse_transactions(doc, own_stir, categoriser)
    if not txns:
        return [], [], []
    recurring = detect_recurring(txns)
    facts = build_aggregates(txns, meta, recurring)
    if doc.period_start is None:
        doc.period_start = min(t.booked_on for t in txns)
    if doc.period_end is None:
        doc.period_end = max(t.booked_on for t in txns)
    return txns, facts, recurring


def statement_summary(txns: list[TxnDraft], recurring: list[dict]) -> dict:
    """Small summary for the document row: counts by category, uncategorised, recurring groups."""
    by_cat: dict[str, dict] = {}
    for t in txns:
        c = by_cat.setdefault(t.category, {"category": t.category, "count": 0, "inflow": 0.0, "outflow": 0.0})
        c["count"] += 1
        if t.amount >= 0:
            c["inflow"] += t.amount / 1000.0
        else:
            c["outflow"] += -t.amount / 1000.0
    uncategorised = sum(1 for t in txns if t.category == "other" and (t.category_conf or 0.0) < 0.6)
    return {
        "transactions": len(txns),
        "categories": len([c for c in by_cat if c != "other"]),
        "uncategorised": uncategorised,
        "by_category": sorted(by_cat.values(), key=lambda c: -(c["inflow"] + c["outflow"])),
        "recurring": [{k: g[k] for k in ("group", "label", "category", "count", "amount", "day_of_month", "contract_no")}
                      for g in recurring],
    }
