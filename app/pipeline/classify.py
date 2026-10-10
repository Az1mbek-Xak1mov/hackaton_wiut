"""Document type, language, period and STIR detection from page text."""
from __future__ import annotations

import calendar
import re
import unicodedata
from datetime import date, timedelta

TYPE_LABELS = {
    "form1": "Form 1 (balance sheet)",
    "form2": "Form 2 (income statement)",
    "bank_statement": "bank statement",
    "loan_application": "loan application form",
    "tax_declaration": "tax declaration",
    "invoice": "invoice",
    "sales_ledger": "sales ledger",
    "unknown": "unknown document",
}

# (pattern on lightly normalised text, weight, human hint)
KEYWORDS: dict[str, list[tuple[str, float]]] = {
    "form1": [
        (r"бухгалтерский баланс", 4), (r"buxgalteriya balansi", 4), (r"бухгалтерия баланси", 4),
        (r"balance sheet", 3), (r"statement of financial position", 3),
        (r"всего по активу", 2), (r"balans aktivi", 2), (r"баланс активи", 2), (r"всего по пассиву", 2),
        (r"balans passivi", 2), (r"баланс пассиви", 2), (r"форма\s*(?:№|n|no)?\s*1\b", 2), (r"1-son shakl", 2),
        (r"1-сон шакл", 2), (r"total assets", 1.5), (r"total equity and liabilities", 1.5),
    ],
    "form2": [
        (r"отчет о финансовых результатах", 4), (r"moliyaviy natijalar to'g'risida", 4),
        (r"молиявий натижалар тўғрисида", 4), (r"income statement", 3), (r"statement of profit or loss", 3),
        (r"profit and loss", 2), (r"чистая выручка", 1.5), (r"sof tushum", 1.5), (r"соф тушум", 1.5),
        (r"форма\s*(?:№|n|no)?\s*2\b", 2), (r"2-son shakl", 2), (r"2-сон шакл", 2), (r"net profit", 1),
        (r"чистая прибыль", 1), (r"sof foyda", 1), (r"соф фойда", 1),
    ],
    "bank_statement": [
        (r"выписка", 3), (r"ko'chirma", 3), (r"кўчирма", 3), (r"bank statement", 3), (r"account statement", 3),
        (r"назначение платежа", 2), (r"to'lov maqsadi", 2), (r"тўлов мақсади", 2), (r"остаток на", 1),
        (r"входящий остаток", 1.5), (r"исходящий остаток", 1.5), (r"\bмфо\b", 1), (r"\bmfo\b", 1),
        (r"debit", 0.5), (r"дебет", 0.5), (r"обороты", 1),
    ],
    "loan_application": [
        (r"заявка на (?:получение )?кредит", 4), (r"заявление на (?:получение )?кредит", 4),
        (r"kredit olish uchun ariza", 4), (r"кредит олиш учун ариза", 4), (r"loan application", 4),
        (r"so'ralayotgan summa", 2), (r"запрашиваемая сумма", 2), (r"requested amount", 2),
        (r"сўралаётган сумма", 2),
    ],
    "tax_declaration": [
        (r"налоговая декларация", 4), (r"soliq deklaratsiyasi", 4), (r"солиқ декларацияси", 4),
        (r"tax declaration", 3), (r"tax return", 3), (r"расчет налога", 2), (r"hisob-kitob", 0.5),
    ],
    "invoice": [
        (r"сч[её]т-фактура", 4), (r"hisob-faktura", 4), (r"ҳисоб-фактура", 4), (r"\binvoice\b", 3),
        (r"накладная", 2), (r"yuk xati", 2),
    ],
    "sales_ledger": [
        (r"реестр реализации", 3), (r"книга продаж", 3), (r"sotuv(?:lar)? reestri", 3), (r"sales ledger", 3),
        (r"реестр сч[её]тов-фактур", 3), (r"sotuvlar", 1.5),
    ],
}

_APOS = str.maketrans({"ʻ": "'", "‘": "'", "’": "'", "ʼ": "'", "`": "'", "´": "'"})


def light_norm(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "").translate(_APOS).lower().replace("ё", "е")
    return re.sub(r"\s+", " ", t)


def classify_text(text: str, *, codes_found: set[str] | None = None, xlsx_header_score: float = 0.0,
                  kind: str = "pdf_text") -> tuple[str, float, str]:
    """(doc_type, confidence 0-1, reason sentence)."""
    t = light_norm(text)
    scores: dict[str, float] = {}
    hits: dict[str, list[str]] = {}
    for typ, kws in KEYWORDS.items():
        s = 0.0
        for pat, w in kws:
            m = re.search(pat, t)
            if m:
                s += w
                hits.setdefault(typ, []).append(m.group(0))
        scores[typ] = s
    codes_found = codes_found or set()
    if {"400", "780"} <= codes_found or {"400", "770"} <= codes_found or {"390", "600"} <= codes_found:
        scores["form1"] += 2.5
        hits.setdefault("form1", []).append("line codes " + ", ".join(sorted(codes_found & {"390", "400", "600", "780"})))
    if {"010", "270"} <= codes_found or {"010", "020", "030"} <= codes_found:
        scores["form2"] += 2.5
        hits.setdefault("form2", []).append("line codes " + ", ".join(sorted(codes_found & {"010", "020", "030", "270"})))
    if xlsx_header_score:
        scores["bank_statement"] += xlsx_header_score
        hits.setdefault("bank_statement", []).append("transaction table header (date, debit, credit, purpose)")
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    (top, s1), (second, s2) = ranked[0], ranked[1]
    if s1 >= 3.0 and (s2 == 0 or s1 >= 1.5 * s2):
        conf = min(0.99, 0.6 + 0.06 * s1)
        found = "; ".join(dict.fromkeys(hits.get(top, [])))
        return top, round(conf, 2), f"Recognised as {TYPE_LABELS[top]}: found {found}."
    if s1 > 0:
        reason = (f"Not a recognised statutory form or statement: best match {TYPE_LABELS[top]} "
                  f"(keyword score {s1:.1f}, needs 3.0"
                  + (f"; runner-up {TYPE_LABELS[second]} {s2:.1f}" if s2 else "") + ").")
    else:
        reason = ("Not a recognised statutory form or statement: no form title, line codes or "
                  "statement columns were found.")
    if kind in ("pdf_scan", "image") and len(t) < 80:
        reason += " Very little text could be read from the image."
    return "unknown", round(min(0.5, 0.1 * s1), 2), reason


def detect_language(text: str) -> str:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return ""
    cyr = sum("Ѐ" <= c <= "ӿ" for c in letters)
    lat = len(letters) - cyr
    uz_cyr_letters = sum(c in "ўқғҳЎҚҒҲ" for c in letters)
    t = light_norm(text)
    uz_lat_markers = len(re.findall(r"\b(?:va|bo'yicha|jami|yil|summa|qarz|xarajat\w*|daromad\w*|foyda\w*|hisobot\w*|"
                                    r"mablag'\w*|majburiyat\w*|to'lov\w*|uchun|so'm)\b", t))
    en_markers = len(re.findall(r"\b(?:the|and|of|total|assets|revenue|profit|for|statement|liabilities)\b", t))
    if cyr and lat and min(cyr, lat) / len(letters) > 0.3:
        return "mixed"
    if cyr >= lat:
        return "uz_cyrl" if uz_cyr_letters >= max(3, 0.004 * cyr) else "ru"
    return "en" if en_markers > uz_lat_markers else "uz_latn"


_MONTHS = {
    1: ["январ", "yanvar", "january", "jan"], 2: ["феврал", "fevral", "february", "feb"],
    3: ["март", "mart", "march", "mar"], 4: ["апрел", "aprel", "april", "apr"],
    5: ["мая", "май", "may"], 6: ["июн", "iyun", "june", "jun"], 7: ["июл", "iyul", "july", "jul"],
    8: ["август", "avgust", "august", "aug"], 9: ["сентябр", "sentyabr", "september", "sep"],
    10: ["октябр", "oktyabr", "october", "oct"], 11: ["ноябр", "noyabr", "november", "nov"],
    12: ["декабр", "dekabr", "december", "dec"],
}
_MONTH_RE = "|".join(sorted({s for v in _MONTHS.values() for s in v}, key=len, reverse=True))


def _month_of(word: str) -> int | None:
    w = word.lower()
    for m, stems in _MONTHS.items():
        if any(w.startswith(s) for s in stems):
            return m
    return None


def _mk(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def find_dates(text: str) -> list[tuple[int, date]]:
    """[(position, date)] for dd.mm.yyyy, yyyy-mm-dd, '31 декабря 2025', '2025 yil 31 dekabr', 'December 31, 2025'."""
    t = light_norm(text)
    out = []
    for m in re.finditer(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b", t):
        d = _mk(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if d:
            out.append((m.start(), d))
    for m in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", t):
        d = _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            out.append((m.start(), d))
    for m in re.finditer(rf"\b(\d{{1,2}})[ -]?(?:{_MONTH_RE})\w*,? (\d{{4}})", t):
        mon = _month_of(re.search(_MONTH_RE, m.group(0)).group(0))
        d = _mk(int(m.group(2)), mon, int(m.group(1))) if mon else None
        if d:
            out.append((m.start(), d))
    for m in re.finditer(rf"\b(\d{{4}})[ -](?:yil|йил|г\.?|года?)?\s*(\d{{1,2}})[ -]?(?:{_MONTH_RE})\w*", t):
        mon = _month_of(re.search(_MONTH_RE, m.group(0)[4:]).group(0))
        d = _mk(int(m.group(1)), mon, int(m.group(2))) if mon else None
        if d:
            out.append((m.start(), d))
    for m in re.finditer(rf"\b(?:{_MONTH_RE})\w* (\d{{1,2}}), (\d{{4}})", t):
        mon = _month_of(m.group(0).split()[0])
        d = _mk(int(m.group(2)), mon, int(m.group(1))) if mon else None
        if d:
            out.append((m.start(), d))
    return sorted(out, key=lambda x: x[0])


def _end_of_month(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


_GEN_RE = re.compile(r"(сформирован\w*|shakllantiril\w*|шакллантирил\w*|generated|printed|дата печати|created|создан\w*)\W{0,4}$")


def _year_near(t: str, a: int, b: int) -> int | None:
    m = re.search(r"(20\d{2})", t[max(0, a - 40): b + 40])
    return int(m.group(1)) if m else None


def detect_period(text: str, doc_type: str = "unknown") -> tuple[date | None, date | None]:
    """(period_start, period_end) from the document header text."""
    t = light_norm(text)[:4000]
    dates = [(p, d) for p, d in find_dates(t) if not _GEN_RE.search(t[max(0, p - 30):p])]
    # tokens like FY2025 / H1-2026 / Q3 2026 (exports, English statements)
    m = re.search(r"\bfy ?-?(20\d{2})\b", t)
    if m:
        y = int(m.group(1))
        return date(y, 1, 1), date(y, 12, 31)
    m = re.search(r"\bh([12]) ?-?(20\d{2})\b", t) or re.search(r"\b(20\d{2}) ?-?h([12])\b", t)
    if m:
        a, b = m.groups()
        h, y = (int(a), int(b)) if len(a) == 1 else (int(b), int(a))
        return (date(y, 1, 1), date(y, 6, 30)) if h == 1 else (date(y, 7, 1), date(y, 12, 31))
    # UZ range without years on both ends: "2026 yil 1 yanvardan 30 iyungacha"
    m = re.search(rf"(\d{{1,2}})[ -]?({_MONTH_RE})\w*?(?:dan|дан)\s+(\d{{1,2}})[ -]?({_MONTH_RE})\w*?(?:gacha|гача)", t)
    if m:
        y = _year_near(t, m.start(), m.end())
        m1, m2 = _month_of(m.group(2)), _month_of(m.group(4))
        if y and m1 and m2:
            d1, d2 = _mk(y, m1, int(m.group(1))), _mk(y, m2, int(m.group(3)))
            if d1 and d2 and d1 < d2:
                return d1, d2
    # RU "с 1 января по 30 июня 2026 г."
    m = re.search(rf"\bс\s+(\d{{1,2}})\s+({_MONTH_RE})\w*\s+(?:(20\d{{2}})\s*(?:г\.?|года)?\s+)?по\s+(\d{{1,2}})\s+({_MONTH_RE})\w*\s+(20\d{{2}})", t)
    if m:
        y2 = int(m.group(6))
        y1 = int(m.group(3)) if m.group(3) else y2
        d1, d2 = _mk(y1, _month_of(m.group(2)), int(m.group(1))), _mk(y2, _month_of(m.group(5)), int(m.group(4)))
        if d1 and d2 and d1 < d2:
            return d1, d2
    # month range "январь-июнь 2026" / "for January-June 2026"
    m = re.search(rf"\b({_MONTH_RE})\w*\s*[-–—]\s*({_MONTH_RE})\w*\s+(20\d{{2}})", t)
    if m:
        m1, m2, y = _month_of(m.group(1)), _month_of(m.group(2)), int(m.group(3))
        if m1 and m2 and m1 <= m2:
            return date(y, m1, 1), _end_of_month(y, m2)
    # explicit dated range: "с 01.01.2026 по 30.06.2026", "01.01.2026 - 30.06.2026"
    for (p1, d1), (p2, d2) in zip(dates, dates[1:]):
        between = t[p1:p2]
        if d1 < d2 and len(between) < 40 and re.search(r"по|-|–|—|to|dan|дан|gacha|гача|до", between):
            return d1, d2
    # half year / 9 months / quarter
    m = re.search(r"(?:\b1|перв\w*|birinchi|биринчи)[- ]?(?:е )?(?:полугоди\w*|yarim yil\w*|ярим йил\w*)", t)
    if m:
        y = _year_near(t, m.start(), m.end())
        if y:
            return date(y, 1, 1), date(y, 6, 30)
    m = re.search(r"\b9[- ]?(?:месяц\w*|oy\w*|ой\w*|months)", t)
    if m:
        y = _year_near(t, m.start(), m.end())
        if y:
            return date(y, 1, 1), date(y, 9, 30)
    m = re.search(r"\b(?:(i{1,3}|iv|[1-4])[- ]?(?:квартал\w*|chorak\w*|чорак\w*)|q([1-4]))\b", t)
    if m:
        q_raw = m.group(1) or m.group(2)
        q = {"i": 1, "ii": 2, "iii": 3, "iv": 4}.get(q_raw) or int(q_raw)
        y = _year_near(t, m.start(), m.end())
        if y:
            return date(y, 3 * q - 2, 1), _end_of_month(y, 3 * q)
    if doc_type == "form1" and dates:
        # balance date: prefer "на 31.12.2025" / "… holatiga" / "as at …"; "1 января 2026" = previous year end
        def anchored(pd):
            p, _ = pd
            return bool(re.search(r"(на|as at|as of|состоянию на)\s*$", t[max(0, p - 18):p])) or \
                bool(re.match(r"\W*\w*\W*(holatiga|ҳолатига|холатига)", t[p:p + 40]))
        pick = next((pd for pd in dates if anchored(pd)), dates[0])
        d = pick[1]
        if (d.month, d.day) == (1, 1):
            d = d - timedelta(days=1)
        return None, d
    m = re.search(r"(?:за|for the year|for)\s*(20\d{2})|(20\d{2})\s*(?:год|yil uchun|йил учун|yil|йил)", t)
    if m:
        yy = int(m.group(1) or m.group(2))
        return date(yy, 1, 1), date(yy, 12, 31)
    if dates:
        return None, dates[0][1]
    m = re.search(r"\b(20\d{2})\b", t)
    if m and doc_type == "form2":
        yy = int(m.group(1))
        return date(yy, 1, 1), date(yy, 12, 31)
    return None, None


def period_labels(doc_type: str, start: date | None, end: date | None) -> tuple[str, str]:
    """(current column label, prior column label)."""
    if end is None:
        return "cur", "prev"
    if doc_type == "form1":
        prev = date(end.year - 1, 12, 31) if (end.month, end.day) != (12, 31) else date(end.year - 1, 12, 31)
        return end.isoformat(), prev.isoformat()
    if start is None:
        return end.isoformat(), "prev"
    months = (end.year - start.year) * 12 + end.month - start.month + 1
    y = end.year
    if months == 12 and start.month == 1:
        return f"FY{y}", f"FY{y - 1}"
    if months == 6 and start.month == 1:
        return f"H1-{y}", f"H1-{y - 1}"
    if months == 9 and start.month == 1:
        return f"9M-{y}", f"9M-{y - 1}"
    if months == 3 and start.month in (1, 4, 7, 10):
        q = (start.month - 1) // 3 + 1
        return f"Q{q}-{y}", f"Q{q}-{y - 1}"
    if months == 1:
        return f"{y}-{end.month:02d}", f"{y - 1}-{end.month:02d}"
    return f"{start.isoformat()}..{end.isoformat()}", "prev"


_STIR_RE = re.compile(r"(?:инн|inn|stir|стир|tin)\D{0,25}?\b([2-7]\d{2}[  ]?\d{3}[  ]?\d{3})\b", re.I)


def detect_stir(text: str) -> str | None:
    m = _STIR_RE.search(light_norm(text))
    return re.sub(r"\D", "", m.group(1)) if m else None


def find_stirs(text: str) -> list[str]:
    return list(dict.fromkeys(re.sub(r"\D", "", m.group(1)) for m in _STIR_RE.finditer(light_norm(text))))
