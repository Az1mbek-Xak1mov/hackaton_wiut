"""Period labels used on facts.

Flows (Form 2, statement aggregates): FY2025, H1-2026, Q3-2026, 9M-2026, 2026-09, 2026-01..2026-08
Points (Form 1 balance dates):        2025-12-31 (a balance "at 1 Jan 2026" is normalised to 2025-12-31)
Unknown column markers:                cur, prev
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta


@dataclass(frozen=True)
class Period:
    raw: str
    kind: str                 # flow | point | unknown
    start: date | None = None
    end: date | None = None
    months: int = 0           # flows only

    @property
    def key(self) -> str:
        if self.kind == "point" and self.end:
            return self.end.isoformat()
        return self.raw

    @property
    def days(self) -> int:
        if self.start and self.end:
            return (self.end - self.start).days + 1
        return 0

    def sort_key(self) -> tuple:
        rank = {"cur": 2, "prev": 1}.get(self.raw, 0)
        return (self.end or date.min, self.months, rank)

    def human(self) -> str:
        """FY2025 -> 'FY 2025', H1-2026 -> 'H1 2026', 2025-12-31 -> '31 Dec 2025', 2026-09 -> 'Sep 2026'."""
        m = re.fullmatch(r"FY(\d{4})", self.raw)
        if m:
            return f"FY {m.group(1)}"
        m = re.fullmatch(r"([HQ]\d|\d{1,2}M)-(\d{4})", self.raw)
        if m:
            return f"{m.group(1)} {m.group(2)}"
        if self.kind == "point" and self.end:
            return f"{self.end.day} {calendar.month_abbr[self.end.month]} {self.end.year}"
        m = re.fullmatch(r"(\d{4})-(\d{2})", self.raw)
        if m:
            return f"{calendar.month_abbr[int(m.group(2))]} {m.group(1)}"
        return self.raw


def month_end(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def add_months(d: date, n: int) -> date:
    y, m = d.year, d.month + n
    while m > 12:
        y, m = y + 1, m - 12
    while m < 1:
        y, m = y - 1, m + 12
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def months_between(a: date, b: date) -> list[str]:
    """Inclusive list of YYYY-MM from the month of a to the month of b."""
    out, y, m = [], a.year, a.month
    while (y, m) <= (b.year, b.month):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def normalise_point(d: date) -> date:
    """A balance at the start of a day equals the balance at the end of the previous day."""
    if d.day == 1:
        return d - timedelta(days=1)
    return d


def to_date(v) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s[: len(datetime(2000, 1, 1).strftime(fmt))], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        return None


_PATTERNS = [
    (re.compile(r"^FY(\d{4})$"), "fy"),
    (re.compile(r"^(\d{4})$"), "fy"),
    (re.compile(r"^H([12])-(\d{4})$"), "h"),
    (re.compile(r"^Q([1-4])-(\d{4})$"), "q"),
    (re.compile(r"^(\d{1,2})M-(\d{4})$"), "nm"),
    (re.compile(r"^(\d{4})-(\d{2})$"), "month"),
    (re.compile(r"^(\d{4})-(\d{2})-(\d{2})$"), "point"),
    (re.compile(r"^(\d{4})-(\d{2})\.\.(\d{4})-(\d{2})$"), "range"),
    (re.compile(r"^(\d{4})-(\d{2})-(\d{2})\.\.(\d{4})-(\d{2})-(\d{2})$"), "drange"),
]


def parse_period(label: str | None) -> Period:
    raw = (label or "").strip()
    for rx, kind in _PATTERNS:
        m = rx.match(raw)
        if not m:
            continue
        g = m.groups()
        try:
            if kind == "fy":
                y = int(g[0])
                return Period(f"FY{y}", "flow", date(y, 1, 1), date(y, 12, 31), 12)
            if kind == "h":
                h, y = int(g[0]), int(g[1])
                s = date(y, 1 if h == 1 else 7, 1)
                return Period(raw, "flow", s, month_end(y, 6 if h == 1 else 12), 6)
            if kind == "q":
                q, y = int(g[0]), int(g[1])
                return Period(raw, "flow", date(y, 3 * q - 2, 1), month_end(y, 3 * q), 3)
            if kind == "nm":
                n, y = int(g[0]), int(g[1])
                if 1 <= n <= 12:
                    return Period(raw, "flow", date(y, 1, 1), month_end(y, n), n)
            if kind == "month":
                y, mo = int(g[0]), int(g[1])
                return Period(raw, "flow", date(y, mo, 1), month_end(y, mo), 1)
            if kind == "point":
                d = normalise_point(date(int(g[0]), int(g[1]), int(g[2])))
                return Period(d.isoformat(), "point", None, d, 0)
            if kind == "drange":
                s = date(int(g[0]), int(g[1]), int(g[2]))
                e = date(int(g[3]), int(g[4]), int(g[5]))
                return Period(raw, "flow", s, e, len(months_between(s, e)))
            if kind == "range":
                s = date(int(g[0]), int(g[1]), 1)
                e = month_end(int(g[2]), int(g[3]))
                return Period(raw, "flow", s, e, len(months_between(s, e)))
        except ValueError:
            break
    return Period(raw, "unknown")


def previous_flow(p: Period) -> str | None:
    """Label of the consecutive previous period of the same length."""
    if p.kind != "flow" or not p.start:
        return None
    m = re.fullmatch(r"FY(\d{4})", p.raw)
    if m:
        return f"FY{int(m.group(1)) - 1}"
    m = re.fullmatch(r"H([12])-(\d{4})", p.raw)
    if m:
        h, y = int(m.group(1)), int(m.group(2))
        return f"H2-{y - 1}" if h == 1 else f"H1-{y}"
    m = re.fullmatch(r"Q([1-4])-(\d{4})", p.raw)
    if m:
        q, y = int(m.group(1)), int(m.group(2))
        return f"Q4-{y - 1}" if q == 1 else f"Q{q - 1}-{y}"
    m = re.fullmatch(r"(\d{4})-(\d{2})", p.raw)
    if m:
        d = add_months(date(int(m.group(1)), int(m.group(2)), 1), -1)
        return f"{d.year:04d}-{d.month:02d}"
    return None


def same_period_last_year(p: Period) -> str | None:
    m = re.fullmatch(r"(FY|H[12]-|Q[1-4]-|\d{1,2}M-)?(\d{4})", p.raw)
    if p.kind == "flow" and m:
        prefix, y = m.group(1) or "FY", int(m.group(2))
        return f"{prefix}{y - 1}"
    m = re.fullmatch(r"(\d{4})-(\d{2})", p.raw)
    if m:
        return f"{int(m.group(1)) - 1}-{m.group(2)}"
    return None
