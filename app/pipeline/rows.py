"""Words -> rows, numeric-token merging, text normalisation for matching."""
from __future__ import annotations

import re
import statistics
import unicodedata

from app.pipeline.numbers import NUMERIC_RE, clean_spaces, ocr_digits
from app.pipeline.types import Row, Word

_APOS = str.maketrans({"ʻ": "'", "‘": "'", "’": "'", "ʼ": "'", "`": "'", "´": "'", "‛": "'", "ʹ": "'"})
# Latin look-alikes -> Cyrillic, used only when a word is mostly Cyrillic (OCR mixes scripts)
_LAT2CYR = str.maketrans({"a": "а", "e": "е", "o": "о", "p": "р", "c": "с", "y": "у", "x": "х", "k": "к",
                          "m": "м", "t": "т", "h": "н", "b": "в", "A": "А", "E": "Е", "O": "О", "P": "Р",
                          "C": "С", "Y": "У", "X": "Х", "K": "К", "M": "М", "T": "Т", "H": "Н", "B": "В"})
_CYR2LAT = {v: k for k, v in {"a": "а", "e": "е", "o": "о", "p": "р", "c": "с", "y": "у", "x": "х", "k": "к",
                               "m": "м", "t": "т", "b": "в"}.items()}
_CYR2LAT_T = str.maketrans(_CYR2LAT)

_FORMULA_RE = re.compile(r"\((?:\s*(?:стр|сатр|str|satr|line)\.?)[^)]*\)", re.I)
_ACCOUNTS_RE = re.compile(r"\(\s*\d{4}[^)]*\)")
_FILLER_RE = re.compile(
    r"\b(в том числе|шу жумладан|shu jumladan|из нее|из него|шундан|shundan|including|of which)\b:?", re.I)


def is_cyrillic(ch: str) -> bool:
    return "Ѐ" <= ch <= "ӿ"


def fold_script(word: str) -> str:
    """Homoglyph fold inside a word towards its majority script."""
    cyr = sum(is_cyrillic(c) for c in word)
    lat = sum(("a" <= c.lower() <= "z") for c in word)
    if cyr and lat:
        return word.translate(_LAT2CYR) if cyr >= lat else word.translate(_CYR2LAT_T)
    return word


def norm_text(text: str) -> str:
    """Normalise a label for fuzzy matching: NFKC, lowercase, apostrophes, homoglyphs, formulas removed."""
    t = unicodedata.normalize("NFKC", text or "").translate(_APOS)
    t = t.replace("ё", "е").replace("Ё", "Е")
    t = _FORMULA_RE.sub(" ", t)
    t = _ACCOUNTS_RE.sub(" ", t)
    t = _FILLER_RE.sub(" ", t)
    t = " ".join(fold_script(w) for w in t.split())
    t = t.lower()
    t = re.sub(r"[^\w' ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


_LONE_DIGIT = {"$": "5", "§": "5", "S": "5", "s": "5", "б": "6", "З": "3", "з": "3", "O": "0", "О": "0",
               "o": "0", "о": "0", "l": "1", "I": "1", "|": "1"}


def _height(w: Word) -> float:
    return max(0.1, w.y1 - w.y0)


def merge_numeric_tokens(words: list[Word], *, ocr: bool = False) -> list[Word]:
    """Join '9' '842' '316' (space thousands split by the PDF/OCR word splitter) into '9 842 316'.

    Words must belong to one row. Merges only when the gap is small (≈ one space)."""
    ws = sorted(words, key=lambda w: w.x0)
    out: list[Word] = []
    for w in ws:
        if out:
            prev = out[-1]
            pt = clean_spaces(ocr_digits(prev.text) if ocr else prev.text)
            if ocr and pt in _LONE_DIGIT and re.fullmatch(r"\d{1,3}(?: \d{3})*", clean_spaces(w.text)):
                pt = _LONE_DIGIT[pt]  # "$" "812 400" -> "5 812 400"
            wt = clean_spaces(ocr_digits(w.text) if ocr else w.text)
            char_w = (prev.x1 - prev.x0) / max(1, len(prev.text))
            gap = w.x0 - prev.x1
            head_ok = re.fullmatch(r"\(?[\-−–]?\d{1,3}(?: \d{3})*", pt) is not None
            if not head_ok and ocr:  # OCR may drop one thousands space: "1339" "800"
                head_ok = re.fullmatch(r"\(?[\-−–]?\d{4,6}(?: \d{3})*", pt) is not None
            tail_ok = re.fullmatch(r"\d{3}(?: \d{3})*(?:[.,]\d+)?\)?", wt) is not None
            if head_ok and tail_ok and gap <= max(1.6 * char_w, 0.45 * _height(w)) and gap > -1:
                text = f"{pt} {wt}"
                if ocr:
                    text = _regroup(text)
                out[-1] = Word(text=text, x0=prev.x0, y0=min(prev.y0, w.y0), x1=w.x1,
                               y1=max(prev.y1, w.y1), conf=min(prev.conf, w.conf))
                continue
        out.append(w)
    return out


def _regroup(text: str) -> str:
    """'1339 800' -> '1 339 800' (keeps sign/parentheses and decimals)."""
    m = re.fullmatch(r"(\(?[\-−–]?)([\d ]+?)((?:[.,]\d+)?\)?)", text)
    if not m or not m.group(2).replace(" ", "").isdigit():
        return text
    grouped = f"{int(m.group(2).replace(' ', '')):,}".replace(",", " ")
    return f"{m.group(1)}{grouped}{m.group(3)}"


def cluster_rows(words: list[Word], page_n: int, *, ocr: bool = False) -> list[Row]:
    """Cluster words into rows by y-centre (tolerance 0.45 x median word height)."""
    if not words:
        return []
    med_h = statistics.median(_height(w) for w in words)
    tol = 0.45 * med_h
    rows: list[list[Word]] = []
    centres: list[float] = []
    for w in sorted(words, key=lambda w: ((w.y0 + w.y1) / 2, w.x0)):
        c = (w.y0 + w.y1) / 2
        if rows and abs(c - centres[-1]) <= tol:
            rows[-1].append(w)
            n = len(rows[-1])
            centres[-1] = centres[-1] + (c - centres[-1]) / n
        else:
            rows.append([w])
            centres.append(c)
    out = []
    for ws, c in zip(rows, centres):
        ws = merge_numeric_tokens(ws, ocr=ocr)
        out.append(Row(page_n=page_n, y=c, words=sorted(ws, key=lambda w: w.x0)))
    return out


def is_number_word(w: Word, *, ocr: bool = False) -> bool:
    t = clean_spaces(ocr_digits(w.text) if ocr else w.text)
    return bool(NUMERIC_RE.match(t)) or t in {"-", "–", "—", "−"}


def union_bbox(words: list[Word]) -> list[float] | None:
    if not words:
        return None
    return [min(w.x0 for w in words), min(w.y0 for w in words), max(w.x1 for w in words), max(w.y1 for w in words)]


def row_text(row: Row) -> str:
    return " ".join(w.text for w in row.words)
