"""Period labels: FY2025 · H1-2026 · Q3-2026 · 2026-09. Pipelines may emit "cur"/"prev"; we resolve them
from the document period so every consumer sees the same label."""
import calendar
import re
from datetime import date

_FY = re.compile(r"^FY(\d{4})$")
_H = re.compile(r"^H([12])-(\d{4})$")
_Q = re.compile(r"^Q([1-4])-(\d{4})$")
_M = re.compile(r"^(\d{4})-(\d{2})$")
_D = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")   # balance-sheet point, e.g. 2025-12-31


def _label_for(end: date, start: date | None) -> str:
    if end.month == 12 and end.day == 31 and (start is None or (start.month == 1 and start.day == 1)):
        return f"FY{end.year}"
    if end.month == 6 and end.day == 30 and (start is None or (start.month == 1 and start.day == 1)):
        return f"H1-{end.year}"
    if end.day == calendar.monthrange(end.year, end.month)[1] and end.month in (3, 9) and \
            (start is None or (start.month == 1 and start.day == 1) or (end.month - start.month) == 2):
        return f"Q{end.month // 3}-{end.year}"
    if start is not None and start.year == end.year and start.month == end.month:
        return f"{end.year}-{end.month:02d}"
    if start is not None and (end.month - start.month) == 2 and end.day == calendar.monthrange(end.year, end.month)[1]:
        return f"Q{end.month // 3}-{end.year}"
    return f"{end.year}-{end.month:02d}"


def _minus_year(d: date | None) -> date | None:
    if d is None:
        return None
    try:
        return d.replace(year=d.year - 1)
    except ValueError:  # 29 Feb
        return d.replace(year=d.year - 1, day=28)


def resolve_label(label: str, doc_type: str, start: date | None, end: date | None) -> str:
    label = (label or "").strip()
    if label not in ("", "cur", "prev") or end is None:
        return label
    if label in ("", "cur"):
        return _label_for(end, start)
    # prev column
    if doc_type == "form1":   # balance sheet: "at the beginning of the reporting year" = previous 31 Dec
        return f"FY{end.year - 1}"
    return _label_for(_minus_year(end), _minus_year(start))


def label_end(label: str) -> date | None:
    """Period end date for sorting labels (flows FY/H/Q/month and balance points YYYY-MM-DD)."""
    if m := _D.match(label or ""):
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    if m := _FY.match(label):
        return date(int(m.group(1)), 12, 31)
    if m := _H.match(label):
        y = int(m.group(2))
        return date(y, 6, 30) if m.group(1) == "1" else date(y, 12, 31)
    if m := _Q.match(label):
        y, q = int(m.group(2)), int(m.group(1))
        mth = q * 3
        return date(y, mth, calendar.monthrange(y, mth)[1])
    if m := _M.match(label):
        y, mth = int(m.group(1)), int(m.group(2))
        if 1 <= mth <= 12:
            return date(y, mth, calendar.monthrange(y, mth)[1])
    return None


def pretty(label: str) -> str:
    if m := _D.match(label or ""):
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).strftime("%d %b %Y").lstrip("0")
        except ValueError:
            return label
    if m := _FY.match(label):
        return f"FY {m.group(1)}"
    if m := _H.match(label):
        return f"H{m.group(1)} {m.group(2)}"
    if m := _Q.match(label):
        return f"Q{m.group(1)} {m.group(2)}"
    if m := _M.match(label):
        try:
            return f"{calendar.month_abbr[int(m.group(2))]} {m.group(1)}"
        except IndexError:
            return label
    return label
