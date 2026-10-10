"""'What I could read' summary for any document (docs/plan/09-API.md `readable` shape).

Always true, never interpreted: numbers with the label printed on their row and their page/bbox,
dates, STIRs, a text excerpt, the language and the OCR confidence.

Not numbers: identifiers (account numbers, MFO+account, card numbers, IDs — 13 or more digits), years, and
form line codes (010, 020 … or a short integer in the code column at the start of a row).
"""
from __future__ import annotations

import re

from app.pipeline.classify import find_dates, find_stirs
from app.pipeline.numbers import parse_number
from app.pipeline.rows import cluster_rows, is_number_word, row_text
from app.pipeline.types import ParsedDoc

MAX_NUMBERS = 30
MAX_EXCERPT = 1500
MIN_ID_DIGITS = 13            # 20-digit accounts, 16-digit cards, 14-digit PINFL: identifiers, not amounts
MAX_ABS_VALUE = 1e15          # facts.value is Numeric(20, 4): anything near 1e16 cannot be stored


def is_identifier(text: str) -> bool:
    """A long digit run is an account / card / ID number, never an amount."""
    return sum(c.isdigit() for c in str(text)) >= MIN_ID_DIGITS and not re.search(r"[.,]\d{1,2}\)?$", str(text).strip())


def storable_value(v: float | None) -> bool:
    return v is not None and v == v and abs(v) < MAX_ABS_VALUE


def _is_line_code(raw: str, index_in_row: int, numeric_index: int, numbers_after: int) -> bool:
    """'010', '040', or a 2-3 digit integer that opens the row / the number columns (the code column)."""
    if not re.fullmatch(r"\d{2,3}", raw):
        return False
    if raw.startswith("0"):
        return True
    return index_in_row == 0 or (numeric_index == 0 and numbers_after > 0)


def readable_summary(doc: ParsedDoc) -> dict:
    lines: list[str] = []
    numbers: list[dict] = []
    for p in doc.pages:
        for r in cluster_rows(p.words, p.n, ocr=p.ocr_used):
            lines.append(row_text(r))
            nums = [w for w in r.words if is_number_word(w, ocr=p.ocr_used)]
            label = " ".join(w.text for w in r.words if w not in nums).strip()
            for k, w in enumerate(nums):
                raw = w.text.replace(" ", "")
                if is_identifier(raw) or (not p.ocr_used and re.fullmatch(r"[2-7]\d{8}", raw)):
                    continue   # account / card / ID numbers; a bare 9-digit STIR (amounts carry separators)
                if _is_line_code(raw, r.words.index(w), k, len(nums) - k - 1):
                    continue
                v = parse_number(w.text, ocr=p.ocr_used)
                # skip page numbers and other tiny integers without a label
                if v is None or (abs(v) < 1000 and not label) or len(raw) < 3 or not storable_value(v):
                    continue
                if re.fullmatch(r"(19|20)\d{2}", raw):  # a year, not an amount
                    continue
                if len(numbers) < MAX_NUMBERS:
                    numbers.append({"text": w.text, "value": v, "label": label[:160], "page_n": p.n,
                                    "bbox": [round(w.x0, 2), round(w.y0, 2), round(w.x1, 2), round(w.y1, 2)]})
    # sheets: spreadsheets, or the transaction table rebuilt from a PDF statement (its numbers are already
    # listed with their page above)
    for s in (doc.sheets if not doc.pages else []):
        for i, row in enumerate(s.rows[:200]):
            vals = [v for v in row if v is not None]
            if not vals:
                continue
            lines.append(" | ".join(str(v) for v in vals))
            label = " ".join(str(v) for v in vals if isinstance(v, str))[:160]
            for v in vals:
                if not isinstance(v, (int, float)) or isinstance(v, bool) or not storable_value(float(v)):
                    continue
                if isinstance(v, int) and is_identifier(str(v)):
                    continue
                if abs(v) >= 1000 and len(numbers) < MAX_NUMBERS:
                    numbers.append({"text": f"{v:,}".replace(",", " "), "value": float(v), "label": label,
                                    "page_n": None, "sheet": s.name, "row": i + 1, "bbox": None})
    text = "\n".join(lines)
    confs = [p.ocr_mean_conf for p in doc.pages if p.ocr_used and p.ocr_mean_conf is not None]
    return {
        "pages": len(doc.pages) or len(doc.sheets),
        "language": doc.language,
        "ocr_mean_conf": round(sum(confs) / len(confs), 1) if confs else None,
        "numbers": numbers,
        "dates": list(dict.fromkeys(d.isoformat() for _, d in find_dates(text)))[:20],
        "stirs": find_stirs(text)[:10],
        "text_excerpt": text[:MAX_EXCERPT],
    }
