"""Text and value normalisation for bank statements (RU / UZ-Latin / UZ-Cyrillic / EN)."""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta

_APOS = str.maketrans({"ʻ": "'", "ʼ": "'", "‘": "'", "’": "'", "`": "'", "´": "'", "ё": "е", "Ё": "Е"})
_SPACES = re.compile(r"\s+")

# VAT mentions inside ordinary payment purposes ("в т.ч. НДС 12% 107 142,86") are not tax payments.
_VAT_INCLUDED = re.compile(
    r"(в\s*т\.?\s*ч\.?|в\s+том\s+числе|включая|с\s+уч[её]том|shu\s+jumladan|jumladan|including|incl\.?)\s*"
    r"(ндс|qqs|vat)\b[^;,)]*",
    re.IGNORECASE,
)
_VAT_NONE = re.compile(
    r"((без|кроме)\s+ндс|ндс\s+не\s+облага\w*|qqs\s*siz|qqssiz|qqs\s+solinmaydi|without\s+vat|vat\s+exempt)",
    re.IGNORECASE,
)
_VAT_RATE = re.compile(r"\b(ндс|qqs|vat)\s*[-:]?\s*\d+\s*%[^;,)]*", re.IGNORECASE)

STIR_RE = re.compile(r"(?<!\d)([2-7]\d{8})(?!\d)")
STIR_LABELLED_RE = re.compile(r"(?:инн|стир|stir|inn|tin)\s*[:№#]?\s*([2-7]\d{8})(?!\d)", re.IGNORECASE)
ACCOUNT_RE = re.compile(r"(?<!\d)(\d{20})(?!\d)")
MFO_RE = re.compile(r"(?:мфо|mfo)\s*[:№#]?\s*(\d{5})(?!\d)", re.IGNORECASE)
CONTRACT_RES = [
    re.compile(r"(?:кредитн\w*\s+)?(?:договор\w*|дог\.?|контракт\w*|shartnoma\w*|contract|agreement)\s*"
               r"(?:(?:№|no\.?|n|#|nr\.?)\s*)?((?:[A-ZА-Я]{1,3}-)?[0-9][0-9A-Za-zА-Яа-я\-/]{0,24}[0-9A-Za-zА-Яа-я])(?![.,]\d)",
               re.IGNORECASE),
    re.compile(r"№\s*([0-9][0-9\-/]{0,24}[0-9])"),
    re.compile(r"(?<![\d\-/])(\d{2,4}[\-/]\d{1,6}(?:[\-/]\d{1,6})?)-?\s*son", re.IGNORECASE),
]
CONTRACT_DATE_RE = re.compile(r"(?:от|dan|from|dated)?\s*(\d{2}\.\d{2}\.\d{4})", re.IGNORECASE)


def norm(text: object) -> str:
    """Lower-case, NFKC, unified apostrophes, ё→е, single spaces."""
    if text is None:
        return ""
    s = unicodedata.normalize("NFKC", str(text)).translate(_APOS).lower()
    return _SPACES.sub(" ", s).strip()


_UZ_CYR = {
    "а": "a", "б": "b", "в": "v", "г": "g", "ғ": "g'", "д": "d", "е": "e", "ё": "yo", "ж": "j", "з": "z", "и": "i",
    "й": "y", "к": "k", "қ": "q", "л": "l", "м": "m", "н": "n", "о": "o", "ў": "o'", "п": "p", "р": "r", "с": "s",
    "т": "t", "у": "u", "ф": "f", "х": "x", "ҳ": "h", "ц": "ts", "ч": "ch", "ш": "sh", "ъ": "'", "ь": "", "э": "e",
    "ю": "yu", "я": "ya", "ы": "i", "щ": "sh",
}
_UZ_MARKERS = re.compile(r"[ўқғҳ]")


def uz_cyr_to_lat(text: str) -> str:
    """Uzbek Cyrillic → Latin (normalised, lower-case input). Russian text passes through unchanged unless it
    contains Uzbek-only letters, so Russian rules keep matching the original."""
    if not _UZ_MARKERS.search(text) and not re.search(r"\b(учун|бўйича|шартнома|тўлов|солиқ)\b", text):
        return text
    return "".join(_UZ_CYR.get(ch, ch) for ch in text)


def strip_vat_mentions(text: str) -> str:
    s = _VAT_INCLUDED.sub(" ", text)
    s = _VAT_NONE.sub(" ", s)
    s = _VAT_RATE.sub(" ", s)
    return _SPACES.sub(" ", s).strip()


def find_stir(*texts: object) -> str | None:
    for t in texts:
        if not t:
            continue
        m = STIR_LABELLED_RE.search(str(t))
        if m:
            return m.group(1)
    return None


def find_contract(text: str) -> tuple[str | None, str | None]:
    """('2024-1177', '14.11.2024') from 'погашение по кредитному договору № 2024-1177 от 14.11.2024'."""
    if not text:
        return None, None
    for rx in CONTRACT_RES:
        m = rx.search(text)
        if m:
            no = m.group(1).strip("-/ .")
            # a date is not a contract number
            if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", no):
                continue
            d = None
            tail = text[m.end(): m.end() + 40]
            md = CONTRACT_DATE_RE.search(tail)
            if md:
                d = md.group(1)
            return no, d
    return None, None


def parse_amount(v: object) -> float | None:
    """Numbers from xlsx cells: 1234.5, '1 234 567,89', '1,234,567.89', '(1 234)', '-', ''."""
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = unicodedata.normalize("NFKC", str(v)).strip()
    if s in {"", "-", "—", "–"}:
        return None
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    s = s.replace("−", "-").replace("–", "-")
    if s.startswith("-"):
        neg, s = True, s[1:]
    s = re.sub(r"[^\d.,]", "", s)
    if not s or not any(ch.isdigit() for ch in s):
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) in (1, 2):
            s = parts[0] + "." + parts[1]
        else:
            s = s.replace(",", "")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    try:
        val = float(s)
    except ValueError:
        return None
    return -val if neg else val


_DATE_FORMATS = ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y.%m.%d", "%d.%m.%Y %H:%M:%S",
                 "%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S")


def parse_date(v: object) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if 30000 <= float(v) <= 60000:  # Excel serial date
            return date(1899, 12, 30) + timedelta(days=int(v))
        return None
    s = str(v).strip()
    if not s or not any(ch.isdigit() for ch in s):
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    m = re.match(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{4})", s)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def cell_text(v: object) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()
