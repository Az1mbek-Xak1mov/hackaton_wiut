"""PDF (text layer or OCR) bank statement → one XlsxSheet, so the xlsx statement path categorises it unchanged.

Columns come from the transaction-table header (date, debit, credit, counterparty, purpose …): every word below
it is assigned to the header cell whose span is nearest its centre. A row without a date continues the previous
transaction (wrapped purpose / counterparty text). Rows above the table (account, opening balance) and below it
(closing balance, totals) are kept as label + number cells for the balance scan.
"""
from __future__ import annotations

import re
import statistics

from app.pipeline.numbers import parse_number
from app.pipeline.rows import cluster_rows, is_number_word
from app.pipeline.statements.normalise import _role, _score
from app.pipeline.statements.text import parse_date
from app.pipeline.types import ParsedPage, Row, Word, XlsxSheet

_TEXT_ROLES = ("purpose", "counterparty")
_MONEY_ROLES = ("debit", "credit", "amount", "balance")
_CELL_STARTERS = {"date", "debit", "credit", "amount", "balance", "stir", "mfo"}   # one-word headers


def _cells(words: list[Word], gap_factor: float = 0.9) -> list[list[Word]]:
    """Header words → cells: a gap wider than ~one character height starts a new cell; words of a second header
    line join the cell they overlap horizontally."""
    ws = sorted(words, key=lambda w: w.x0)
    if not ws:
        return []
    h = statistics.median(max(0.1, w.y1 - w.y0) for w in ws)
    cells: list[list[Word]] = []
    for w in ws:
        if cells:
            span_x1 = max(c.x1 for c in cells[-1])
            starts_cell = _role(w.text) in _CELL_STARTERS and w.x0 > span_x1   # 'Hujjat №' | 'Debet'
            if w.x0 - span_x1 <= gap_factor * h and not starts_cell:
                cells[-1].append(w)
                continue
        cells.append([w])
    return cells


def _cell_text(cell: list[Word]) -> str:
    return " ".join(w.text for w in sorted(cell, key=lambda w: (round(w.y0), w.x0)))


def _header_columns(rows: list[Row], i: int) -> tuple[int, list[tuple[float, float, str | None]]] | None:
    """(rows used, [(x0, x1, role)]) when row i (optionally with row i+1) is a transaction-table header."""
    best = None
    for used in (1, 2):
        if i + used > len(rows):
            break
        words = [w for r in rows[i:i + used] for w in r.words]
        if used == 2 and any(parse_date(w.text) for w in rows[i + 1].words):
            break
        cells = _cells(words)
        texts = [_cell_text(c) for c in cells]
        score, cols = _score(texts)
        if score >= 3 and (best is None or score > best[0]):
            roles = {v: k for k, v in cols.items()}
            best = (score, used, [(min(w.x0 for w in c), max(w.x1 for w in c), roles.get(j)) for j, c in enumerate(cells)])
    return (best[1], best[2]) if best else None


def _assign(word: Word, cols: list[tuple[float, float, str | None]]) -> int:
    cx = (word.x0 + word.x1) / 2
    for j, (x0, x1, _) in enumerate(cols):
        if x0 <= cx <= x1:
            return j

    def dist(j: int) -> float:
        x0, x1, _ = cols[j]
        return min(abs(cx - x0), abs(cx - x1))
    return min(range(len(cols)), key=dist)


def _plain_row(r: Row, ocr: bool) -> list:
    """Outside the table: label text, then each number as its own cell."""
    nums = [w for w in r.words if is_number_word(w, ocr=ocr)]
    label = " ".join(w.text for w in r.words if w not in nums).strip()
    out: list = [label] if label else []
    for w in nums:
        v = parse_number(w.text, ocr=ocr)
        if v is not None and sum(c.isdigit() for c in w.text) < 13:
            out.append(v)
        else:
            out.append(w.text)
    return out


def pdf_statement_sheet(pages: list[ParsedPage], name: str = "") -> XlsxSheet | None:
    """The statement table of all pages as one sheet; None when no transaction-table header is found."""
    cols = None
    out: list[list] = []
    last_txn: int | None = None
    pages_used: list[int] = []
    for p in pages:
        rows = cluster_rows(p.words, p.n, ocr=p.ocr_used)
        i = 0
        while i < len(rows):
            r = rows[i]
            hdr = _header_columns(rows, i)
            if hdr is not None:
                used, found = hdr
                if cols is None or len(found) >= len(cols) - 1:
                    cols = found
                if not out or out[-1] != [_cell_text([w]) for w in []]:
                    out.append([role or "" for _, _, role in cols] if out and last_txn is not None else
                               [_cell_text(c) for c in _cells([w for rr in rows[i:i + used] for w in rr.words])])
                pages_used.append(p.n)
                last_txn = None
                i += used
                continue
            if cols is None:
                out.append(_plain_row(r, p.ocr_used))
                i += 1
                continue
            cells: list[list[Word]] = [[] for _ in cols]
            for w in r.words:
                cells[_assign(w, cols)].append(w)
            texts = [_cell_text(c) if c else None for c in cells]
            date_j = next((j for j, (_, _, role) in enumerate(cols) if role == "date"), None)
            has_date = date_j is not None and texts[date_j] and parse_date(texts[date_j].split(" ")[0])
            money_j = [j for j, (_, _, role) in enumerate(cols) if role in _MONEY_ROLES]
            has_money = any(texts[j] for j in money_j)
            if has_date:
                texts[date_j] = texts[date_j].split(" ")[0]
                out.append(texts)
                last_txn = len(out) - 1
                if p.n not in pages_used:
                    pages_used.append(p.n)
            elif last_txn is not None and not has_money:
                prev = out[last_txn]   # wrapped text of the previous transaction
                for j, t in enumerate(texts):
                    if t and cols[j][2] not in _MONEY_ROLES:
                        prev[j] = f"{prev[j]} {t}".strip() if prev[j] else t
            else:
                last_txn = None
                out.append(_plain_row(r, p.ocr_used))
            i += 1
    if cols is None:
        return None
    if not name:
        pp = sorted(set(pages_used)) or [pages[0].n]
        name = f"PDF page {pp[0]}" if len(pp) == 1 else f"PDF pages {pp[0]}–{pp[-1]}"
    return XlsxSheet(name=name, rows=out)


def has_transactions(sheet: XlsxSheet) -> bool:
    return any(isinstance(c, str) and re.match(r"\d", c) and parse_date(c) for row in sheet.rows for c in row)
