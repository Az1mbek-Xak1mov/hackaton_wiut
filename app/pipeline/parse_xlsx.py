"""XLSX → XlsxSheet rows (values, not formulas)."""
from __future__ import annotations

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
