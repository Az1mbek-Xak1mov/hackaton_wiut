"""Owner cash-flow spreadsheet (month | money in | money out [| balance]) → monthly facts. Pure functions, no LLM.

A simple management cash-flow table is not a statutory form or a bank statement, so it gets its own
document type `cash_flow`. Every value becomes a fact `cashflow.inflow.YYYY-MM` / `cashflow.outflow.YYYY-MM`
(/ `cashflow.balance_end.YYYY-MM`) citing its sheet row.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from app.pipeline import classify as cls
from app.pipeline.compute import new_fact_key
from app.pipeline.types import FactDraft, ParsedDoc, XlsxSheet

_MONTH_H = r"(?<![\wа-я])(?:month|period|date|oy|sana|давр|месяц|период|дата|ой)(?![a-z])"
_IN_H = (r"(?:income|inflow|cash in|money in|receipts?|revenue|sales|tushum|kirim|daromad|поступлен|приход|доход|"
         r"выручк)")
_OUT_H = (r"(?:spending|spent|outflow|cash out|money out|expenses?|payments?|costs?|xarajat|chiqim|сарф|расход|"
          r"выплат|платеж|затрат)")
_BAL_H = r"(?:balance|closing|qoldiq|остаток|сальдо)"

_MONTH_WORDS = {
    **{m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)},
    **{m: i for i, m in enumerate(["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"], 1)},
    **{m: i for i, m in enumerate(["yan", "fev", "mar", "apr", "may", "iyun", "iyul", "avg", "sen", "okt", "noy", "dek"], 1)},
    "май": 5,
}
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
               "November", "December"]


def month_human(ym: str) -> str:
    return f"{MONTH_NAMES[int(ym[5:7]) - 1]} {ym[:4]}"


def parse_month(v) -> str | None:
    """A cell that names a month → 'YYYY-MM'."""
    if isinstance(v, (datetime, date)):
        return f"{v.year:04d}-{v.month:02d}"
    if not isinstance(v, str):
        return None
    t = cls.light_norm(v).strip()
    if m := re.fullmatch(r"(\d{4})[-./](\d{1,2})(?:[-./]\d{1,2})?", t):
        y, mo = int(m.group(1)), int(m.group(2))
    elif m := re.fullmatch(r"(?:\d{1,2}[./])?(\d{1,2})[./](\d{4})", t):
        y, mo = int(m.group(2)), int(m.group(1))
    elif m := re.fullmatch(r"([a-zа-я']+)\.?,?\s+(\d{4})(?:\s*(?:г\.?|y\.?|yil))?", t):
        word, y = m.group(1), int(m.group(2))
        mo = next((n for k, n in sorted(_MONTH_WORDS.items(), key=lambda kv: -len(kv[0])) if word.startswith(k)), 0)
    else:
        return None
    if not (1 <= mo <= 12 and 1990 <= y <= 2100):
        return None
    return f"{y:04d}-{mo:02d}"


def _num(v) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        t = v.strip().replace(" ", "").replace(" ", "").replace(" ", "")
        neg = t.startswith("(") and t.endswith(")")
        t = t.strip("()").replace("−", "-")
        if re.fullmatch(r"-?\d+(?:,\d{3})+(?:\.\d+)?", t):
            t = t.replace(",", "")
        elif re.fullmatch(r"-?\d+,\d+", t):
            t = t.replace(",", ".")
        try:
            x = float(t)
        except ValueError:
            return None
        return -x if neg else x
    return None


def _scale(header_text: str) -> float:
    """Multiplier to UZS from the header ('mln', 'тыс', 'ming')."""
    if re.search(r"\b(?:mln|млн|million)\b", header_text):
        return 1_000_000.0
    if re.search(r"(?:тыс|ming|thousand|'000|000s)", header_text):
        return 1000.0
    return 1.0


def find_cashflow_table(sheets: list[XlsxSheet]) -> dict | None:
    """The first sheet whose header row names a month, money-in and money-out column, with ≥ 1 month row."""
    for s in sheets:
        for hi, row in enumerate(s.rows[:20]):
            cols: dict[str, int] = {}
            for ci, v in enumerate(row):
                if not isinstance(v, str):
                    continue
                t = cls.light_norm(v)
                if "month" not in cols and re.search(_MONTH_H, t):
                    cols["month"] = ci
                elif "in" not in cols and re.search(_IN_H, t):
                    cols["in"] = ci
                elif "out" not in cols and re.search(_OUT_H, t):
                    cols["out"] = ci
                elif "bal" not in cols and re.search(_BAL_H, t):
                    cols["bal"] = ci
            if not {"in", "out"} <= set(cols):
                continue
            mc = cols.get("month", 0)
            body = [(hi + 1 + j, r) for j, r in enumerate(s.rows[hi + 1:]) if len(r) > mc and parse_month(r[mc])]
            if body:
                head = cls.light_norm(" ".join(str(v) for r_ in s.rows[:hi + 1] for v in r_ if isinstance(v, str)))
                return {"sheet": s.name, "header_row": hi, "cols": {**cols, "month": mc}, "rows": body,
                        "scale": _scale(head)}
    return None


def extract_cashflow(parsed: ParsedDoc) -> list[FactDraft]:
    table = find_cashflow_table(parsed.sheets)
    if table is None:
        return []
    cols, scale, sheet = table["cols"], table["scale"], table["sheet"]
    seen: set[str] = set()
    out: list[FactDraft] = []
    specs = [("in", "inflow", "Money in (cash-flow file)"), ("out", "outflow", "Money out (cash-flow file)"),
             ("bal", "balance_end", "Cash at end of month (cash-flow file)")]
    for row_i, r in table["rows"]:
        ym = parse_month(r[cols["month"]])
        if ym in seen:
            continue
        seen.add(ym)
        for key, name, label in specs:
            if key not in cols or cols[key] >= len(r):
                continue
            v = _num(r[cols[key]])
            if v is None:
                continue
            if name == "outflow":
                v = abs(v)
            uzs = v * scale
            out.append(FactDraft(field=f"cashflow.{name}.{ym}", label=f"{label}, {month_human(ym)}",
                                 value=round(uzs / 1000.0, 3), unit="kUZS", kind="extracted", period_label=ym,
                                 printed=str(r[cols[key]])[:64], passage=f"row {row_i + 1} of sheet {sheet}",
                                 confidence=0.95, method="table", note="owner's management cash-flow table",
                                 key=new_fact_key()))
    return out
