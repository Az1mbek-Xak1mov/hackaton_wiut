"""Uzbek Latin -> Uzbek Cyrillic transliteration (generator use only)."""
from __future__ import annotations

import re

_APOS = "'ʻʼ‘’`"

_MULTI = [
    ("o'", "ў"), ("g'", "ғ"), ("sh", "ш"), ("ch", "ч"),
    ("ya", "я"), ("yo", "ё"), ("yu", "ю"), ("ye", "е"),
]
_SINGLE = {
    "a": "а", "b": "б", "d": "д", "e": "е", "f": "ф", "g": "г", "h": "ҳ", "i": "и",
    "j": "ж", "k": "к", "l": "л", "m": "м", "n": "н", "o": "о", "p": "п", "q": "қ",
    "r": "р", "s": "с", "t": "т", "u": "у", "v": "в", "x": "х", "y": "й", "z": "з",
    "c": "с", "w": "в",
}
# words kept as-is or with a fixed spelling
_FIXED = {
    "MChJ": "МЧЖ", "XK": "ХК", "AJ": "АЖ", "QK": "ҚК", "ATB": "АТБ", "STIR": "СТИР",
    "MFO": "МФО", "QQS": "ҚҚС",
}


def _word(w: str) -> str:
    if w in _FIXED:
        return _FIXED[w]
    if re.fullmatch(r"[IVX]+", w):  # roman numerals stay Latin
        return w
    if not re.search(r"[A-Za-z]", w):
        return w
    s = w
    for a in _APOS:
        s = s.replace(a, "'")
    out = []
    i = 0
    lower = s.lower()
    while i < len(s):
        ch = s[i]
        # word-initial e -> э
        if lower[i] == "e" and (i == 0 or not lower[i - 1].isalpha()):
            rep = "э"
            out.append(rep.upper() if ch.isupper() else rep)
            i += 1
            continue
        matched = False
        for lat, cyr in _MULTI:
            if lower.startswith(lat, i):
                seg = s[i:i + len(lat)]
                out.append(cyr.upper() if seg[0].isupper() else cyr)
                i += len(lat)
                matched = True
                break
        if matched:
            continue
        if ch == "'":
            out.append("ъ")
        elif lower[i] in _SINGLE:
            cyr = _SINGLE[lower[i]]
            out.append(cyr.upper() if ch.isupper() else cyr)
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def to_cyrillic(text: str) -> str:
    return re.sub(r"[A-Za-z'ʻʼ‘’`]+", lambda m: _word(m.group(0)), text)
