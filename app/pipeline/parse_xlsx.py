"""XLSX → XlsxSheet rows (values, not formulas)."""
from __future__ import annotations

import io
import re
from datetime import date, datetime

import openpyxl

from app.pipeline.types import XlsxSheet

MAX_ROWS = 20000


def read_xlsx(path: str, max_rows: int = MAX_ROWS) -> list[XlsxSheet]:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheets = []
    try:
        for ws in wb.worksheets:
            rows = []
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i >= max_rows:
                    break
                vals = [(_cell(v)) for v in row]
                while vals and vals[-1] is None:
                    vals.pop()
                rows.append(vals)
            while rows and not rows[-1]:
                rows.pop()
            sheets.append(XlsxSheet(name=ws.title, rows=rows))
    finally:
        wb.close()
    return sheets


def _cell(v):
    if isinstance(v, datetime):
        return v.date() if (v.hour, v.minute, v.second) == (0, 0, 0) else v
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


def sheet_text(sheets: list[XlsxSheet], max_rows: int = 30) -> str:
    """Text of the first rows of every sheet, for classification."""
    parts = []
    for s in sheets:
        for row in s.rows[:max_rows]:
            parts.append(" ".join(str(v) for v in row if v is not None and not isinstance(v, (int, float, date))))
    return "\n".join(p for p in parts if p)


# ---------------------------------------------------------------- other spreadsheet formats → the same sheets

_NUM_CELL = re.compile(r"^[\-−(]?\d{1,3}(?:[  ,]\d{3})*(?:[.,]\d+)?\)?$|^[\-−(]?\d+(?:[.,]\d+)?\)?$")


def _text_cell(v: str):
    """CSV / HTML cell text → number when it is clearly one; identifiers (leading zero, ≥ 13 digits) stay text."""
    v = (v or "").strip()
    if not v:
        return None
    digits = sum(c.isdigit() for c in v)
    if _NUM_CELL.match(v) and digits < 13 and not (v[0] == "0" and digits > 1 and not v.startswith(("0.", "0,"))):
        from app.pipeline.statements.text import parse_amount
        n = parse_amount(v)
        if n is not None:
            return int(n) if n.is_integer() and not re.search(r"[.,]\d{1,2}$", v) else n
    return v


def read_xls(path: str, max_rows: int = MAX_ROWS) -> list[XlsxSheet]:
    """Legacy Excel 97-2003 (.xls) via xlrd; dates become dates like in read_xlsx."""
    import xlrd
    book = xlrd.open_workbook(path, on_demand=True)
    sheets = []
    try:
        for sh in book.sheets():
            rows = []
            for i in range(min(sh.nrows, max_rows)):
                vals = []
                for c in sh.row(i):
                    if c.ctype == xlrd.XL_CELL_DATE:
                        try:
                            v = _cell(xlrd.xldate.xldate_as_datetime(c.value, book.datemode))
                        except Exception:
                            v = c.value
                    elif c.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK, xlrd.XL_CELL_ERROR):
                        v = None
                    elif c.ctype == xlrd.XL_CELL_NUMBER:
                        v = int(c.value) if float(c.value).is_integer() else c.value
                    elif c.ctype == xlrd.XL_CELL_BOOLEAN:
                        v = bool(c.value)
                    else:
                        v = _cell(c.value)
                    vals.append(v)
                while vals and vals[-1] is None:
                    vals.pop()
                rows.append(vals)
            while rows and not rows[-1]:
                rows.pop()
            sheets.append(XlsxSheet(name=sh.name, rows=rows))
    finally:
        book.release_resources()
    return sheets


def decode_text(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _delimiter(text: str) -> str:
    """The delimiter that splits the most lines into the same number of columns (decimal commas do not)."""
    from collections import Counter
    lines = [ln for ln in text.splitlines()[:50] if ln.strip()]
    best, best_score = ",", -1
    for d in (";", "\t", ",", "|"):
        counts = Counter(ln.count(d) for ln in lines if ln.count(d))
        if counts:
            n, k = counts.most_common(1)[0]
            if n * k > best_score:
                best, best_score = d, n * k
    return best


def read_csv(path: str, max_rows: int = MAX_ROWS) -> list[XlsxSheet]:
    import csv
    text = decode_text(open(path, "rb").read())
    rows = []
    for i, row in enumerate(csv.reader(io.StringIO(text), delimiter=_delimiter(text))):
        if i >= max_rows:
            break
        vals = [_text_cell(v) for v in row]
        while vals and vals[-1] is None:
            vals.pop()
        rows.append(vals)
    while rows and not rows[-1]:
        rows.pop()
    return [XlsxSheet(name="CSV", rows=rows)]


def read_html_table(path: str, max_rows: int = MAX_ROWS) -> list[XlsxSheet]:
    """Many bank-clients save 'Excel' exports as an HTML table (or Excel 2003 XML) with an .xls name."""
    from html.parser import HTMLParser

    class _P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.rows: list[list] = []
            self.row: list | None = None
            self.cell: list[str] | None = None

        def handle_starttag(self, tag, attrs):
            if tag in ("tr", "row"):   # HTML table, or Excel 2003 XML (<Row><Cell><Data>)
                self.row = []
            elif tag in ("td", "th", "cell") and self.row is not None:
                self.cell = []
            elif tag == "br" and self.cell is not None:
                self.cell.append(" ")

        def handle_endtag(self, tag):
            if tag in ("td", "th", "cell") and self.row is not None and self.cell is not None:
                self.row.append(_text_cell(re.sub(r"\s+", " ", "".join(self.cell))))
                self.cell = None
            elif tag in ("tr", "row") and self.row is not None:
                if len(self.rows) < max_rows:
                    self.rows.append(self.row)
                self.row = None

        def handle_data(self, data):
            if self.cell is not None:
                self.cell.append(data)

    p = _P()
    p.feed(decode_text(open(path, "rb").read()))
    rows = p.rows
    for r in rows:
        while r and r[-1] is None:
            r.pop()
    return [XlsxSheet(name="Table", rows=rows)]
