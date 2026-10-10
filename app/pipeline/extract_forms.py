"""Statutory-form extraction (Form 1 / Form 2) → FactDraft list + unmapped rows.

Method (docs/plan/02-PIPELINE.md §3): find the line-code column, find the value columns (cur/prev, or the
4-column Form 2: prior income | prior expense | current income | current expense), match each code row to
the dictionary (code exact + fuzzy label), parse values, then cross-check the dictionary sum relations.
Rows without codes are matched by label only (non-statutory / English layouts) with lower confidence.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from app.pipeline import dictionary as dic
from app.pipeline.classify import light_norm, period_labels
from app.pipeline.numbers import clean_spaces, is_dash, ocr_digits, parse_number
from app.pipeline.rows import cluster_rows, is_number_word, norm_text, row_text, union_bbox
from app.pipeline.types import FactDraft, ParsedDoc, Row, Word

LABEL_OK = 70          # code exact + label ≥ 70 → "dictionary" 0.99
LABEL_ONLY_OK = 88     # no code, label ≥ 88 → "fuzzy" 0.85


@dataclass
class _Col:
    x1: float                     # mean right edge, as a fraction of page width
    xs: list[float] = field(default_factory=list)
    lo: float = 1.0
    hi: float = 0.0
    role: str = ""                # cur | prev | cur_inc | cur_exp | prev_inc | prev_exp
    header: str = ""
    x0min: float = 1.0            # leftmost value-token start, fraction of page width


@dataclass
class _Cand:
    row: Row
    page_w: float
    code: str | None
    code_word: Word | None
    label_words: list[Word]
    nums: list[Word]
    ocr: bool
    extra_label: list[tuple[float, str]] = field(default_factory=list)


def _code_text(w: Word, ocr: bool) -> str:
    t = clean_spaces(w.text)
    return ocr_digits(t) if ocr else t


def _unit_multiplier(text: str) -> tuple[float, str]:
    """Statutory forms are printed in thousand so'm; only an explicit 'mln' / 'in so'm' changes that."""
    t = light_norm(text)
    if re.search(r"(?:тыс\w*|ming|минг|thousand|'000)\.?\s*(?:сум|so'm|сўм|som|uzs|soum)|в тысячах|uzs ?'000", t):
        return 1.0, ""
    if re.search(r"(?:млн|mln|million)\.?\s*(?:сум|so'm|сўм|som|uzs|soum)", t):
        return 1000.0, "printed in mln UZS, converted to thousand UZS"
    if re.search(r"в сумах|so'mda|сўмда|in uzs\b", t):
        return 0.001, "printed in UZS, converted to thousand UZS"
    return 1.0, "unit not printed; assumed thousand UZS (statutory default)"


def _cluster_1d(values: list[float], tol: float) -> list[list[float]]:
    out: list[list[float]] = []
    for v in sorted(values):
        if out and v - statistics.mean(out[-1]) <= tol:
            out[-1].append(v)
        else:
            out.append([v])
    return out


def _detect_code_column(rows_by_page: list[tuple[float, list[Row], bool]], form: str) -> float | None:
    """x-centre (fraction of page width) of the line-code column, or None."""
    known = dic.codes(form)
    xs = []
    for pw, rows, ocr in rows_by_page:
        for r in rows:
            for w in r.words:
                if _code_text(w, ocr) in known:
                    xs.append(((w.x0 + w.x1) / 2) / pw)
    if len(xs) < 3:
        return None
    clusters = _cluster_1d(xs, 0.02)
    best = max(clusters, key=len)
    return statistics.mean(best) if len(best) >= 3 else None


_PREV_WORDS = ("начало", "начала", "boshiga", "бошига", "прошлого", "предыдущий", "o'tgan", "ўтган", "oldingi",
               "previous", "prior", "beginning", "opening")
_CUR_WORDS = ("конец", "конца", "oxiriga", "охирига", "current", "closing")


def _fuzzy_period(t: str) -> str | None:
    """OCR-garbled header ('На комец ...'): fuzzy match single words against period keywords."""
    best, role = 0.0, None
    for w in re.findall(r"[\w']{4,}", t):
        for kw in _PREV_WORDS:
            s = fuzz.ratio(w, kw)
            if s > best:
                best, role = s, "prev"
        for kw in _CUR_WORDS:
            s = fuzz.ratio(w, kw)
            if s > best:
                best, role = s, "cur"
    return role if best >= 78 else None


def _header_role(text: str) -> tuple[str | None, str | None, int | None]:
    t = light_norm(text)
    period = None
    if re.search(r"начал|boshi|бошига|бош[иа]|прошл|o'tgan|ўтган|oldingi|prior|previous|beginning|opening", t):
        period = "prev"
    elif re.search(r"конец|конц|oxir|охир|отчетн\w* период|за отчетный|hisobot davrida|ҳисобот даврида|current|closing|end of", t):
        period = "cur"
    else:
        period = _fuzzy_period(t)
    kind = None
    if re.search(r"доход|прибыл|daromad|foyda|даромад|фойда|income|profit", t):
        kind = "inc"
    if re.search(r"расход|убыт|xarajat|zarar|харажат|зарар|expense|loss", t):
        kind = "exp" if kind is None else None   # both words → ambiguous (spanning header)
    years = [int(y) for y in re.findall(r"\b(20\d{2})\b", t)]
    return period, kind, (max(years) if years else None)


def _assign_roles(cols: list[_Col], form: str) -> bool:
    """Assign cur/prev (and income/expense) roles. Returns True when the column order was confirmed by
    header text, False when the statutory default order (prior | current) was assumed."""
    n = len(cols)
    if n == 1:
        cols[0].role = "cur"
        return True
    if form == "form2" and n >= 4:
        use = cols[-4:]
        for c, r in zip(use, ["prev_inc", "prev_exp", "cur_inc", "cur_exp"]):
            c.role = r
        # header says the groups are the other way round
        p0, _, y0 = _header_role(use[0].header + " " + use[1].header)
        p1, _, y1 = _header_role(use[2].header + " " + use[3].header)
        if (p0 == "cur" and p1 == "prev") or (y0 and y1 and y0 > y1):
            for c, r in zip(use, ["cur_inc", "cur_exp", "prev_inc", "prev_exp"]):
                c.role = r
        return bool(p0 or p1 or (y0 and y1))
    left, right = cols[-2], cols[-1]
    left.role, right.role = "prev", "cur"
    pl, _, yl = _header_role(left.header)
    pr, _, yr = _header_role(right.header)
    if (pl == "cur" and pr != "cur") or (pr == "prev" and pl != "prev") or (yl and yr and yl > yr):
        left.role, right.role = "cur", "prev"
    return bool(pl or pr or (yl and yr))


def _fix_income_expense(cols: list[_Col], code_cands: list[_Cand]) -> None:
    """4-column Form 2: the column holding line 010 (revenue) is the income column of its period group,
    the column holding line 020 (cost of sales) is the expense column. Data beats header text."""
    for group in ("prev", "cur"):
        gcols = [c for c in cols if c.role.startswith(group + "_")]
        if len(gcols) != 2:
            continue
        votes = {id(c): 0 for c in gcols}
        for cand in code_cands:
            sign = 1 if cand.code == "010" else (-1 if cand.code in ("020", "040", "170", "250") else 0)
            if not sign:
                continue
            for col in gcols:
                if _nearest(cand.nums, col, cand.page_w) is not None:
                    votes[id(col)] += sign
        a, b = gcols
        if votes[id(a)] > votes[id(b)]:
            a.role, b.role = f"{group}_inc", f"{group}_exp"
        elif votes[id(b)] > votes[id(a)]:
            a.role, b.role = f"{group}_exp", f"{group}_inc"


def _value_columns(cands: list[_Cand], form: str) -> list[_Col]:
    pts = []
    for c in cands:
        for w in c.nums:
            pts.append((w.x1 / c.page_w, w.x0 / c.page_w))
    if not pts:
        return []
    groups = _cluster_1d([p[0] for p in pts], 0.035)
    min_n = max(2, int(0.12 * len(cands))) if len(cands) >= 5 else 1
    cols = []
    for g in groups:
        if len(g) < min_n:
            continue
        lo_x1, hi_x1 = min(g), max(g)
        x0s = [x0 for x1, x0 in pts if lo_x1 <= x1 <= hi_x1]
        cols.append(_Col(x1=statistics.mean(g), xs=g, x0min=min(x0s) if x0s else lo_x1 - 0.08))
    if cols:  # OCR debris inside labels ('1', '22') forms small clusters: keep only real amount columns
        biggest = max(len(c.xs) for c in cols)
        cols = [c for c in cols if len(c.xs) >= 0.4 * biggest]
    return sorted(cols, key=lambda c: c.x1)


def _phrases(words: list[Word], pw: float) -> list[list[Word]]:
    """Split a row into phrases at gaps wider than ~1.5 characters (column boundaries)."""
    out: list[list[Word]] = []
    for w in sorted(words, key=lambda w: w.x0):
        if out:
            prev = out[-1][-1]
            cw = (prev.x1 - prev.x0) / max(1, len(prev.text))
            if w.x0 - prev.x1 <= max(1.5 * cw, 0.006 * pw):
                out[-1].append(w)
                continue
        out.append([w])
    return out


def _attach_headers(cols: list[_Col], rows_by_page, first_code_y: dict[int, float], code_x: float | None) -> None:
    """Header words just above the first code row; each word goes to ONE value column — the nearest one
    by distance from the word centre to the column's [x0, x1] span — and only if it is close enough."""
    for pw, rows, _ in rows_by_page[:1]:
        if not rows or not cols:
            continue
        page_n = rows[0].page_n
        y_lim = first_code_y.get(page_n)
        if y_lim is None:
            continue
        heights = sorted(w.y1 - w.y0 for r in rows for w in r.words) or [10.0]
        lh = heights[len(heights) // 2]
        band = [r for r in rows if y_lim - 12 * lh <= r.y < y_lim]
        left_limit = (code_x + 0.02) if code_x is not None else (min(c.x0min for c in cols) - 0.15)
        texts: dict[int, list[str]] = {id(c): [] for c in cols}
        for r in band:
            for phrase in _phrases(r.words, pw):
                xc = ((phrase[0].x0 + phrase[-1].x1) / 2) / pw
                if xc < left_limit:
                    continue

                def dist(c: _Col) -> float:
                    lo, hi = min(c.x0min, c.x1 - 0.02), c.x1
                    return 0.0 if lo <= xc <= hi else min(abs(xc - lo), abs(xc - hi))
                best = min(cols, key=dist)
                if dist(best) <= 0.15:
                    texts[id(best)].append(" ".join(w.text for w in phrase))
        for c in cols:
            c.header = " ".join(texts[id(c)])


def _nearest(nums: list[Word], col: _Col, pw: float, tol: float = 0.045) -> Word | None:
    best, bd = None, tol
    for w in nums:
        d = abs(w.x1 / pw - col.x1)
        if d <= bd:
            best, bd = w, d
    return best


def _score(label: str, entry: dic.Entry, strict: bool = False) -> float:
    """Label similarity. strict (label-only matching): whole-string comparison, so a short fragment such
    as 'for the year' does not match 'Profit for the year'."""
    nl = norm_text(label)
    if not nl:
        return 0.0
    scorer = fuzz.token_sort_ratio if strict else fuzz.token_set_ratio
    best = 0.0
    for lab in entry.all_labels():
        s = scorer(nl, norm_text(lab))
        if s > best:
            best = s
    return best


def _passage(rows: list[Row], idx: int) -> str:
    lo, hi = max(0, idx - 1), min(len(rows), idx + 2)
    return "\n".join(row_text(r) for r in rows[lo:hi])


def _detect_form_by_labels(rows_by_page) -> str | None:
    hits = {"form1": 0, "form2": 0}
    for form in hits:
        ents = dic.entries(form)
        for pw, rows, _ in rows_by_page:
            for r in rows:
                if not any(is_number_word(w) for w in r.words):
                    continue
                lab = " ".join(w.text for w in r.words if not is_number_word(w))
                if lab and max((_score(lab, e, strict=True) for e in ents), default=0) >= LABEL_ONLY_OK:
                    hits[form] += 1
    form, n = max(hits.items(), key=lambda kv: kv[1])
    return form if n >= 3 else None


def extract_forms(doc: ParsedDoc, form: str | None = None) -> tuple[list[FactDraft], list[dict]]:
    """Extract statutory lines. Returns (facts, unmapped_rows)."""
    if not doc.pages:
        return [], []
    rows_by_page: list[tuple[float, list[Row], bool]] = []
    for p in doc.pages:
        rows_by_page.append((p.width or 1.0, cluster_rows(p.words, p.n, ocr=p.ocr_used), p.ocr_used))
    if form is None:
        form = doc.doc_type if doc.doc_type in ("form1", "form2") else _detect_form_by_labels(rows_by_page)
    if form not in ("form1", "form2"):
        return [], []
    if doc.failure_cause and all(p.ocr_used for p in doc.pages):
        # unreadable scan: report what was read, never numbers we are unsure of
        return [], _unmapped_numbers(rows_by_page)

    all_text = "\n".join(row_text(r) for _, rows, _ in rows_by_page[:1] for r in rows[:40])
    mult, unit_note = _unit_multiplier(all_text)
    cur_label, prev_label = period_labels(form, doc.period_start, doc.period_end)
    code_x = _detect_code_column(rows_by_page, form)
    known = dic.codes(form)

    # ── candidates ────────────────────────────────────────────────────────
    cands: list[_Cand] = []
    orphan_rows: list[tuple[int, Row, float]] = []    # label-only text rows (for wrapped labels)
    first_code_y: dict[int, float] = {}
    side = "asset"
    side_by_row: dict[int, str] = {}
    no_code_rows: list[_Cand] = []
    for pw, rows, ocr in rows_by_page:
        for r in rows:
            t = light_norm(row_text(r))
            if re.search(r"\b(пассив|passiv|equity and liabilities|liabilities and equity)\b", t):
                side = "liability"
            side_by_row[id(r)] = side
            code_word = None
            if code_x is not None:
                for w in r.words:
                    ct = _code_text(w, ocr)
                    if re.fullmatch(r"\d{3}", ct) and abs(((w.x0 + w.x1) / 2) / pw - code_x) <= 0.03:
                        code_word = w
                        break
            nums = [w for w in r.words if w is not code_word and is_number_word(w, ocr=ocr)
                    and (code_word is None or w.x0 >= code_word.x1 - 1)]
            label_words = [w for w in r.words if w is not code_word and w not in nums]
            if code_word is not None:
                code = _code_text(code_word, ocr)
                first_code_y.setdefault(r.page_n, r.y)
                cands.append(_Cand(r, pw, code, code_word, label_words, nums, ocr))
            elif nums and label_words:
                cands.append(_Cand(r, pw, None, None, label_words, nums, ocr))
                no_code_rows.append(cands[-1])
            elif label_words and not nums:
                orphan_rows.append((r.page_n, r, pw))

    code_cands = [c for c in cands if c.code]
    value_cols = _value_columns(code_cands if code_cands else cands, form)
    for col in value_cols:
        col.lo = min(col.xs) - 0.08
        col.hi = max(col.xs)
    _attach_headers(value_cols, rows_by_page, first_code_y, code_x)
    order_confirmed = True
    if value_cols:
        order_confirmed = _assign_roles(value_cols, form)
        _fix_income_expense(value_cols, code_cands)

    # wrapped labels: attach text-only rows to the nearest code row on the same page
    if code_cands:
        heights = [w.y1 - w.y0 for c in code_cands for w in c.row.words] or [10.0]
        lh = statistics.median(heights)
        for page_n, r, pw in orphan_rows:
            if code_x is not None and min(w.x0 for w in r.words) / pw > code_x:
                continue
            same = [c for c in code_cands if c.row.page_n == page_n]
            if not same:
                continue
            near = min(same, key=lambda c: abs(c.row.y - r.y))
            if abs(near.row.y - r.y) <= 2.2 * lh:
                near.extra_label.append((r.y, row_text(r)))

    # ── extraction ───────────────────────────────────────────────────────
    facts: list[FactDraft] = []
    unmapped: list[dict] = []
    taken: set[tuple[str, str]] = set()
    page_rows = {rows[0].page_n: rows for _, rows, _ in rows_by_page if rows}
    page_img = {p.n: p for p in doc.pages}

    for c in cands:
        label_parts = sorted(c.extra_label + [(c.row.y, " ".join(w.text for w in c.label_words))])
        label = " ".join(t for _, t in label_parts).strip()
        entry, method, conf, note = None, "", 0.0, ""
        if c.code:
            if c.code not in known:
                unmapped.append(_unmapped(c, label, f"line code {c.code} is not in the dictionary"))
                continue
            entry = dic.by_code(form, c.code)
            s = _score(label, entry) if label else 0.0
            if s >= LABEL_OK:
                method, conf = "dictionary", 0.99
            else:
                method, conf = "dictionary", 0.90
                note = (f"label differs from the official text (match {s:.0f}%)" if label else "row label not readable")
        else:
            if code_cands:
                # statutory layout: a numbered table — rows without a code are never guessed by label
                ys = [k.row.y for k in code_cands if k.row.page_n == c.row.page_n]
                if ys and min(ys) <= c.row.y <= max(ys):
                    unmapped.append(_unmapped(c, label, "row without a line code inside the statutory table"))
                continue
            side_r = side_by_row.get(id(c.row), "asset")
            pool = [e for e in dic.entries(form) if (e.form, e.code) not in taken
                    and (form != "form1" or (e.side == "asset") == (side_r == "asset"))]
            scored = sorted(((_score(label, e, strict=True), e) for e in pool), key=lambda x: x[0], reverse=True)
            if not scored or scored[0][0] < LABEL_ONLY_OK:
                ys = [k.row.y for k in code_cands if k.row.page_n == c.row.page_n]
                if ys and min(ys) <= c.row.y <= max(ys):  # inside the statutory table: worth showing
                    unmapped.append(_unmapped(c, label, "no line code and no confident label match"))
                continue
            entry = scored[0][1]
            method, conf = "fuzzy", 0.85
            note = "non-statutory layout: matched by label, no line code"
        if (form, entry.code) in taken:
            continue
        if c.ocr:
            method = "ocr+dictionary" if method == "dictionary" else method

        values = _row_values(c, value_cols, entry, page_img.get(c.row.page_n))
        if not values:
            unmapped.append(_unmapped(c, label, "no value in the amount columns"))
            continue
        taken.add((form, entry.code))
        rows = page_rows.get(c.row.page_n, [c.row])
        idx = next((i for i, r in enumerate(rows) if r is c.row), 0)
        passage = _passage(rows, idx)
        label_bbox = union_bbox(c.label_words + ([c.code_word] if c.code_word else []))
        for role, (v, w, wconf) in values.items():
            period = cur_label if role == "cur" else prev_label
            fconf = conf
            if c.ocr:
                fconf = min(conf, wconf + 0.1)
            notes = [n for n in (note, unit_note) if n]
            if not order_confirmed and len(value_cols) >= 2:
                notes.append("column headers unreadable: statutory order (prior | current) assumed")
                if c.ocr:
                    fconf = min(fconf, 0.8)  # never a confident value when cur/prev could be swapped
            if role == "cur" and "prev" not in values and any(col.role.startswith("prev") for col in value_cols):
                notes.append("prior-period cell blank")
            facts.append(FactDraft(
                field=entry.field, label=entry.label_en, value=round(v * mult, 4), unit="kUZS", kind="extracted",
                line_code=entry.code, period_label=period, printed=w.text, page_n=c.row.page_n,
                bbox=[round(w.x0, 2), round(w.y0, 2), round(w.x1, 2), round(w.y1, 2)],
                label_bbox=[round(x, 2) for x in label_bbox] if label_bbox else None,
                passage=passage, confidence=round(max(0.0, min(1.0, fconf)), 3), method=method,
                note="; ".join(notes)))

    _arithmetic(facts, form)
    return facts, unmapped


def _row_values(c: _Cand, cols: list[_Col], entry: dic.Entry, page) -> dict[str, tuple[float, Word, float]]:
    """{'cur': (value, word, conf), 'prev': ...} for one row."""
    got: dict[str, tuple[float, Word, float]] = {}
    if not cols:
        nums = sorted(c.nums, key=lambda w: w.x1)
        roles = ["cur"] if len(nums) == 1 else ["prev", "cur"]
        pairs = list(zip(roles, nums[-len(roles):]))
    else:
        pairs = []
        for col in cols:
            if not col.role:
                continue
            w = _nearest(c.nums, col, c.page_w)
            if w is not None:
                pairs.append((col.role, w))
    raw: dict[str, tuple[float, Word, float]] = {}
    for role, w in pairs:
        text = w.text
        conf = w.conf
        v = parse_number(text, ocr=c.ocr)
        if c.ocr and (v is None or conf < 0.75) and page is not None and page.image_path:
            fixed = _reocr(page, w)
            if fixed is not None:
                v2 = parse_number(fixed[0], ocr=True)
                if v2 is not None and (v is None or fixed[1] > conf):
                    v, conf = v2, fixed[1]
        if v is None:
            continue
        raw[role] = (v, w, conf)
    for period in ("cur", "prev"):
        if period in raw:
            got[period] = raw[period]
            continue
        inc, exp = raw.get(f"{period}_inc"), raw.get(f"{period}_exp")
        if inc and exp and inc[0] and exp[0]:
            got[period] = (inc[0] - exp[0], inc[1], min(inc[2], exp[2]))
        elif exp and (exp[0] or not inc):
            v = -abs(exp[0]) if entry.kind == "result" else abs(exp[0])
            got[period] = (v, exp[1], exp[2])
        elif inc:
            got[period] = inc
    return got


def _join_cell(nums: list[Word], anchor: Word, col: _Col, pw: float) -> Word:
    """OCR splits '1 287 620' into '1287' + '620' with a wide gap: join digit groups inside one column cell."""
    lo = (col.x0min - 0.03) * pw
    inside = sorted((w for w in nums if w.x0 >= lo and w.x1 <= anchor.x1 + 1 and w.x1 <= (col.x1 + 0.03) * pw),
                    key=lambda w: w.x0)
    if len(inside) < 2 or anchor not in inside:
        return anchor
    parts = [w.text.replace(" ", "") for w in inside]
    if not (re.fullmatch(r"\(?-?\d{1,6}", parts[0]) and all(re.fullmatch(r"\d{3}\)?", p) for p in parts[1:])):
        return anchor
    digits = "".join(parts).strip("()-")
    text = f"{int(digits):,}".replace(",", " ")
    if parts[0].startswith("("):
        text = f"({text})"
    return Word(text=text, x0=inside[0].x0, y0=min(w.y0 for w in inside), x1=inside[-1].x1,
                y1=max(w.y1 for w in inside), conf=min(w.conf for w in inside))


def _reocr(page, w: Word):
    try:
        from PIL import Image

        from app.pipeline.ocr import reocr_digits
        img = Image.open(page.image_path)
        s = page.image_scale or 1.0
        big = img.resize((img.width * 2, img.height * 2))
        return reocr_digits(big, [w.x0 * s * 2, w.y0 * s * 2, w.x1 * s * 2, w.y1 * s * 2])
    except Exception:
        return None


def _unmapped(c: _Cand, label: str, reason: str) -> dict:
    vw = max(c.nums, key=lambda w: w.x1) if c.nums else None
    return {"page_n": c.row.page_n, "text": row_text(c.row), "label": label, "code": c.code,
            "value_printed": vw.text if vw else "", "bbox": [vw.x0, vw.y0, vw.x1, vw.y1] if vw else None,
            "reason": reason}


def _unmapped_numbers(rows_by_page) -> list[dict]:
    out = []
    for pw, rows, ocr in rows_by_page:
        for r in rows:
            nums = [w for w in r.words if is_number_word(w, ocr=ocr)]
            if nums:
                vw = max(nums, key=lambda w: w.x1)
                out.append({"page_n": r.page_n, "text": row_text(r), "label": " ".join(w.text for w in r.words if w not in nums),
                            "code": None, "value_printed": vw.text, "bbox": [vw.x0, vw.y0, vw.x1, vw.y1],
                            "reason": "document failed the quality gate; value not extracted"})
    return out[:60]


def _arithmetic(facts: list[FactDraft], form: str) -> None:
    """Sum relations: a failed check lowers confidence by 0.15 on the lines involved; a passed check
    confirms OCR'd values (raised to at least 0.95)."""
    by_period: dict[str, dict[str, FactDraft]] = {}
    for f in facts:
        by_period.setdefault(f.period_label, {})[f.line_code] = f
    for period, fs in by_period.items():
        values = {code: f.value for code, f in fs.items()}
        for e in dic.entries(form):
            if e.code not in fs:
                continue
            if e.sum_of:
                exp = dic.evaluate_sum(e, values)
                if exp is None:
                    continue
                involved = [fs[e.code]] + [fs[c.lstrip("-")] for c in e.sum_of if c.lstrip("-") in fs]
                if abs(exp - values[e.code]) > 1.0:
                    for f in involved:
                        f.confidence = round(max(0.0, f.confidence - 0.15), 3)
                        f.note = _add(f.note, f"sum check failed: line {e.code} = {values[e.code]:,.0f}, "
                                              f"{' '.join(e.sum_of)} gives {exp:,.0f}".replace(",", " "))
                else:
                    for f in involved:
                        if f.confidence < 0.95 and f.method.startswith("ocr"):
                            f.confidence = 0.95
                            f.note = _add(f.note, f"confirmed by sum check of line {e.code}")
            for p in e.parts:
                if p in fs and fs[p].value > values[e.code] + 1.0:
                    fs[p].confidence = round(max(0.0, fs[p].confidence - 0.1), 3)
                    fs[p].note = _add(fs[p].note, f"exceeds its total line {e.code}")
        if form == "form1" and "400" in fs and "780" in fs and abs(fs["400"].value - fs["780"].value) > 1.0:
            for code in ("400", "780"):
                fs[code].note = _add(fs[code].note, "balance does not balance: line 400 ≠ line 780")


def _add(note: str, extra: str) -> str:
    return f"{note}; {extra}" if note else extra
