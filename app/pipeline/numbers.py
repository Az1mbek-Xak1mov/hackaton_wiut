"""Number parsing and formatting for Uzbek financial documents.

parse_number("9 842 316") -> 9842316.0      parse_number("(1 234)") -> -1234.0
parse_number("9.842.316") -> 9842316.0      parse_number("1 234,5") -> 1234.5
parse_number("1,234.50")  -> 1234.5         parse_number("-")       -> 0.0 (dash cell = zero)
"""
from __future__ import annotations

import re

_SPACES = "     "
_MINUS = "-−–—"
_DASH_ONLY = re.compile(r"^[\-−–—]+$")
_NA_ONLY = re.compile(r"^[xхXХ]$")  # "х" = cell not applicable on the official forms
# a numeric cell: optional (, optional minus, digits with optional space/./, groups, optional decimals, optional )
NUMERIC_RE = re.compile(
    r"^\(?[\-−–]?\d{1,3}(?:[    .,]\d{3})*(?:[.,]\d+)?\)?$|^\(?[\-−–]?\d+(?:[.,]\d+)?\)?$"
)
_OCR_FIX = str.maketrans({"O": "0", "o": "0", "О": "0", "о": "0", "l": "1", "I": "1", "|": "1", "З": "3", "S": "5", "B": "8"})


def clean_spaces(text: str) -> str:
    for ch in _SPACES:
        text = text.replace(ch, " ")
    return text.strip()


def ocr_digits(token: str) -> str:
    """Fix common OCR confusions inside a mostly-numeric token."""
    digits = sum(c.isdigit() for c in token)
    if digits and digits >= len(re.sub(r"[\s().,\-]", "", token)) - 1:
        return token.translate(_OCR_FIX)
    return token


def is_numeric_token(text: str, *, ocr: bool = False) -> bool:
    t = clean_spaces(text)
    if ocr:
        t = ocr_digits(t)
    return bool(NUMERIC_RE.match(t)) or bool(_DASH_ONLY.match(t))


def is_dash(text: str) -> bool:
    return bool(_DASH_ONLY.match(clean_spaces(text)))


def parse_number(text: str | None, *, prefer_integer: bool = True, ocr: bool = False) -> float | None:
    """Parse a printed amount. Returns None if the text is not a number.

    prefer_integer: a single '.' or ',' followed by exactly three digits is read as a thousands
    separator (statutory forms are printed in whole thousands of so'm).
    """
    if text is None:
        return None
    t = clean_spaces(str(text))
    if not t:
        return None
    if ocr:
        t = ocr_digits(t)
    if _DASH_ONLY.match(t):
        return 0.0
    if _NA_ONLY.match(t):
        return None
    neg = False
    if t.startswith("(") and t.endswith(")"):
        neg, t = True, t[1:-1].strip()
    if t and t[0] in _MINUS:
        neg, t = (not neg), t[1:].strip()
    if t.endswith("-"):  # trailing minus (some accounting exports)
        neg, t = (not neg), t[:-1].strip()
    if " " in t and not re.fullmatch(r"\d{1,3}(?: \d{3})+(?:[.,]\d+)?", t):
        return None  # "12 34" is two numbers, not one
    t = t.replace(" ", "")
    if not t or not re.fullmatch(r"[\d.,]+", t) or not re.search(r"\d", t):
        return None
    dots, commas = t.count("."), t.count(",")
    if dots and commas:
        dec = "." if t.rfind(".") > t.rfind(",") else ","
        thou = "," if dec == "." else "."
        t = t.replace(thou, "").replace(dec, ".")
    elif dots > 1 or commas > 1:
        sep = "." if dots > 1 else ","
        parts = t.split(sep)
        if all(len(p) == 3 for p in parts[1:]):
            t = "".join(parts)
        else:
            return None
    elif dots == 1 or commas == 1:
        sep = "." if dots else ","
        head, tail = t.split(sep)
        if len(tail) == 3 and prefer_integer and head:
            t = head + tail
        else:
            t = head + "." + tail
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def fmt_thousands(v: float, decimals: int = 0) -> str:
    """9842316 -> '9 842 316' (space thousands, true minus sign)."""
    s = f"{abs(v):,.{decimals}f}".replace(",", " ")
    return ("−" if v < 0 else "") + s


def fmt_mln_from_k(v_kuzs: float, decimals: int = 1) -> str:
    """kUZS -> mln UZS display: 9842316 -> '9 842.3'."""
    return fmt_thousands(v_kuzs / 1000.0, decimals)


def amount_to_kuzs(value: float, unit_text: str) -> float:
    """Convert an amount printed with a unit word to kUZS."""
    u = unit_text.lower()
    if re.search(r"mlrd|млрд|billion|bn", u):
        return value * 1_000_000
    if re.search(r"mln|млн|million", u):
        return value * 1000
    if re.search(r"ming|минг|тыс|thousand|\bk\b", u):
        return value
    return value / 1000.0  # so'm / сум / UZS
