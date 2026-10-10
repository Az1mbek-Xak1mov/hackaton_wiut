"""Citation verifier (docs/plan/02-PIPELINE.md §7) — deterministic, no LLM.

Every number in generated text must (a) sit in a sentence that cites at least one fact id `[f_xxxxxx]`
and (b) equal the value of a fact cited in that sentence, at any display scale (kUZS / mln / bn / UZS,
percent, ratio), within half a unit of the last printed digit. Years, dates, contract numbers and line codes
are accepted only when they appear in the facts' periods or labels. Unknown ids and approval/score language
are rejected.
"""
from __future__ import annotations

import re
from datetime import date

from app.pipeline.compute import fact_display
from app.pipeline.rules.periods import parse_period
from app.pipeline.types import FactDraft

CITE_TOKEN = re.compile(r"\bf_[A-Za-z0-9]{2,24}\b")
FINDING_TOKEN = re.compile(r"\[\s*([RM]\d{2}(?:-\d+)?)\s*\]")
_BRACKETS = re.compile(r"\[\s*(?:f_[A-Za-z0-9]{2,24}|[RM]\d{2}(?:-\d+)?)(?:\s*[,;]\s*(?:f_[A-Za-z0-9]{2,24}|[RM]\d{2}(?:-\d+)?))*\s*\]")

_MONTHS = {
    **{m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)},
    **{m: i for i, m in enumerate(["январ", "феврал", "март", "апрел", "ма", "июн", "июл", "август", "сентябр", "октябр",
                                   "ноябр", "декабр"], 1)},
    **{m: i for i, m in enumerate(["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust", "sentyabr",
                                   "oktyabr", "noyabr", "dekabr"], 1)},
}
_MONTH_ALT = ("jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|"
              "oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|январ\\w*|феврал\\w*|март\\w*|апрел\\w*|ма[йя]\\w*|июн\\w*|"
              "июл\\w*|август\\w*|сентябр\\w*|октябр\\w*|ноябр\\w*|декабр\\w*|yanvar\\w*|fevral\\w*|mart\\w*|"
              "aprel\\w*|iyun\\w*|iyul\\w*|avgust\\w*|sentyabr\\w*|oktyabr\\w*|noyabr\\w*|dekabr\\w*")
_DATE_DMY_WORD = re.compile(rf"(?<![\w.,])(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_ALT})\.?(?:,?\s+(\d{{4}}))?(?![\w])",
                            re.IGNORECASE)
_DATE_MDY_WORD = re.compile(rf"(?<![\w])({_MONTH_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,\s+(\d{{4}})(?![\w])", re.IGNORECASE)
_DATE_ISO = re.compile(r"(?<![\w.-])(\d{4})-(\d{2})-(\d{2})(?![\w-])")
_DATE_DMY = re.compile(r"(?<![\w.])(\d{1,2})\.(\d{1,2})\.(\d{4})(?![\w])")
_YM = re.compile(r"(?<![\w.-])(\d{4})-(\d{2})(?![\w-])")
_REF = re.compile(r"(?<![\w-])[A-Za-zА-Яа-я]{1,5}-\d+(?:-\d+)*(?![\w-])")
_IDENT = re.compile(r"(?<![\w.,/-])\d+(?:[/-]\d+)+(?![\w/-])")
_TIME = re.compile(r"(?<![\w:])\d{1,2}:\d{2}(?![\w:])")
_ORDINAL = re.compile(r"^(\s*(?:[-*]\s*)?)(\d{1,2})[.)](?=\s)")
_LINE_CODES = re.compile(r"\b(lines?|codes?|строк[аи]?|стр\.|qator|satr|код)\s+(\d{3}(?:\s*(?:,|and|и|va|\+|−|-|/|or)\s*\d{3})*)",
                         re.IGNORECASE)
_FORM_NO = re.compile(r"\b(forms?|forma|форма|shakl)\s*(?:№|no\.?)?\s*([12])(?![\d.,])", re.IGNORECASE)
_NUM = re.compile(
    r"(?<![\w.,])(?P<sign>[−\-–+])?"
    r"(?P<num>\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?|\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:[.,]\d+)?)"
    r"(?P<suffix>\s*(?:%|×|x(?![a-zа-я])|mln|million|млн|bn|billion|млрд|mlrd|thousand|тыс|ming|kuzs|"
    r"days?|kun|дн\w*|months?|oy(?![a-z])|мес\w*)(?![a-zа-я]))?",
    re.IGNORECASE,
)
_YEAR = re.compile(r"^(19[9]\d|20[0-3]\d)$")

FORBIDDEN = [
    r"\bapprov(?:e|ed|es|al|ing)\b", r"\breject(?:s|ed|ion|ing)?\b", r"\bdeclin(?:e|ed)\s+(?:the\s+)?(?:loan|application|credit)",
    r"\bcredit\s*scor", r"\bscor(?:e|es|ing)\b", r"\brating\b", r"\bcreditworth",
    r"одобр", r"отказ", r"скоринг", r"рейтинг", r"кредитоспособн", r"\bбалл",
    r"tasdiqla", r"\brad\s+(?:et|qil)", r"reyting", r"skoring",
]
_FORBIDDEN = [re.compile(p, re.IGNORECASE) for p in FORBIDDEN]


# ------------------------------------------------------------------ helpers

def _num_value(text: str) -> tuple[float, int]:
    t = text.replace(" ", " ").replace(" ", " ")
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", t):
        t = t.replace(",", "")
    else:
        t = t.replace(" ", "").replace(",", ".")
    decimals = len(t.split(".", 1)[1]) if "." in t else 0
    return float(t), decimals


def _unit(suffix: str | None) -> str:
    s = (suffix or "").strip().lower()
    if not s:
        return "none"
    if s == "%":
        return "pct"
    if s in ("×", "x"):
        return "times"
    if s in ("mln", "million", "млн"):
        return "mln"
    if s in ("bn", "billion", "млрд", "mlrd"):
        return "bn"
    if s in ("thousand", "тыс", "ming", "kuzs"):
        return "k"
    if s.startswith(("day", "kun", "дн")):
        return "days"
    if s.startswith(("month", "oy", "мес")):
        return "months"
    return "none"


def _candidates(f: FactDraft, unit: str) -> list[float]:
    v = f.value
    money_scales: dict[str, float] = {}
    if f.unit == "kUZS":
        money_scales = {"k": v, "mln": v / 1e3, "bn": v / 1e6, "uzs": v * 1e3}
    elif f.unit == "UZS":
        money_scales = {"uzs": v, "k": v / 1e3, "mln": v / 1e6, "bn": v / 1e9}
    if unit in ("mln", "bn", "k"):
        return [money_scales[unit]] if unit in money_scales else []
    if unit == "pct":
        if f.unit == "pct":
            return [v]
        if f.unit == "ratio":
            return [v * 100.0]
        return []
    if unit == "times":
        return [v] if f.unit in ("ratio", "count") else []
    if unit in ("days", "months"):
        return [v] if f.unit in ("days", "count") else []
    out = list(money_scales.values()) if money_scales else [v]
    if f.unit == "ratio":
        out.append(v * 100.0)
    return out


def _metadata_text(f: FactDraft) -> str:
    return " ".join(str(x) for x in (f.label, f.period_label, f.printed, f.line_code or "") if x)


def _numbers_in(text: str) -> set[float]:
    out = set()
    for m in _NUM.finditer(text):
        try:
            out.add(abs(_num_value(m.group("num"))[0]))
        except ValueError:
            continue
    return out


def _allowed_years_dates(facts: dict[str, FactDraft]) -> tuple[set[int], set[date], set[str]]:
    years: set[int] = set()
    dates: set[date] = set()
    idents: set[str] = set()
    for f in facts.values():
        p = parse_period(f.period_label)
        for d in (p.start, p.end):
            if d:
                dates.add(d)
                years.add(d.year)
        if p.kind == "point" and p.end:
            from datetime import timedelta
            dates.add(p.end + timedelta(days=1))  # "balance at 1 Jan 2026"
        blob = " ".join(str(x) for x in (f.label, f.period_label, f.printed, f.note, f.passage) if x)
        for y in re.findall(r"(?<!\d)(19[9]\d|20[0-3]\d)(?!\d)", blob):
            years.add(int(y))
        for m in _DATE_ISO.finditer(blob):
            try:
                dates.add(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
            except ValueError:
                pass
        for m in _DATE_DMY.finditer(blob):
            try:
                dates.add(date(int(m.group(3)), int(m.group(2)), int(m.group(1))))
            except ValueError:
                pass
        for m in _DATE_DMY_WORD.finditer(blob):
            mon = _month_no(m.group(2))
            if mon and m.group(3):
                try:
                    dates.add(date(int(m.group(3)), mon, int(m.group(1))))
                except ValueError:
                    pass
        for m in _IDENT.finditer(blob):
            idents.add(m.group(0))
    return years, dates, idents


def _month_no(word: str) -> int | None:
    w = word.lower().rstrip(".")
    for k in sorted(_MONTHS, key=len, reverse=True):
        if w.startswith(k):
            return _MONTHS[k]
    return None


def _split_sentences(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        lead_ord = re.match(r"^\s*(?:[-*]\s*)?\d{1,2}[.)]\s+", line)
        prefix = lead_ord.group(0) if lead_ord else ""
        parts = re.split(r"(?<=[.!?])\s+(?=\S)", line[len(prefix):])
        if parts:
            parts[0] = prefix + parts[0]
        for part in parts:
            lead = re.match(r"^((?:\s*\[[^\]]*\])+)(.*)$", part)
            if lead and out and CITE_TOKEN.search(lead.group(1)):
                out[-1] = out[-1] + " " + lead.group(1).strip()
                part = lead.group(2)
            stripped = _BRACKETS.sub("", part)
            if not re.search(r"[A-Za-zА-Яа-яЎўҚқҒғҲҳ0-9]", stripped):
                if out:
                    out[-1] = out[-1] + " " + part.strip()
                continue
            out.append(part.strip())
    return out


# ------------------------------------------------------------------ public API

def verify(text: str, facts: dict[str, FactDraft], finding_ids: set[str] | None = None,
           check_forbidden: bool = True) -> dict:
    """Returns {ok, numbers, unmatched, uncited_sentences, unknown_ids, forbidden, cited}."""
    finding_ids = finding_ids or set()
    years, allowed_dates, idents = _allowed_years_dates(facts)
    all_codes = {f.line_code for f in facts.values() if f.line_code}
    report = {"ok": True, "numbers": [], "unmatched": [], "uncited_sentences": [], "unknown_ids": [],
              "forbidden": [], "cited": []}

    for tok in CITE_TOKEN.findall(text):
        if tok not in facts and tok not in report["unknown_ids"]:
            report["unknown_ids"].append(tok)
    for m in FINDING_TOKEN.finditer(text):
        if m.group(1) not in finding_ids and m.group(1) not in report["unknown_ids"]:
            report["unknown_ids"].append(m.group(1))
    if check_forbidden:
        for rx in _FORBIDDEN:
            for m in rx.finditer(text):
                report["forbidden"].append(m.group(0))

    for sent in _split_sentences(text):
        cited = [c for c in dict.fromkeys(CITE_TOKEN.findall(sent)) if c in facts]
        for c in cited:
            if c not in report["cited"]:
                report["cited"].append(c)
        work = _BRACKETS.sub(" ", sent)
        work = CITE_TOKEN.sub(" ", work)
        issues: list[dict] = []
        meta_nums: set[float] = set()
        meta_idents: set[str] = set()
        for c in cited:
            meta_nums |= _numbers_in(_metadata_text(facts[c]))
            meta_idents |= {m.group(0) for m in _IDENT.finditer(_metadata_text(facts[c]))}

        def blank(m: re.Match) -> str:
            return " " * len(m.group(0))

        # references (APP-2026-0931), times, ordinals, form numbers
        work = _REF.sub(blank, work)
        work = _TIME.sub(blank, work)
        work = _ORDINAL.sub(lambda m: m.group(1) + " " * (len(m.group(0)) - len(m.group(1))), work)
        work = _FORM_NO.sub(lambda m: m.group(1) + " " * (len(m.group(0)) - len(m.group(1))), work)

        # dates
        def check_date(raw: str, d: date | None, day_month: tuple[int, int] | None = None) -> None:
            ok = False
            if d is not None:
                ok = d in allowed_dates
            elif day_month is not None:
                ok = any((x.day, x.month) == day_month for x in allowed_dates)
            report["numbers"].append({"text": raw, "kind": "date", "matched_fact": "date" if ok else None})
            if not ok:
                issues.append({"text": raw, "sentence": sent, "hint": "date not found in the facts"})

        for rx in (_DATE_ISO, _DATE_DMY):
            for m in list(rx.finditer(work)):
                g = m.groups()
                try:
                    d = date(int(g[0]), int(g[1]), int(g[2])) if rx is _DATE_ISO else date(int(g[2]), int(g[1]), int(g[0]))
                except ValueError:
                    d = None
                check_date(m.group(0), d)
            work = rx.sub(blank, work)
        for m in list(_DATE_MDY_WORD.finditer(work)):
            mon = _month_no(m.group(1))
            try:
                d = date(int(m.group(3)), mon, int(m.group(2))) if mon else None
            except ValueError:
                d = None
            check_date(m.group(0), d)
        work = _DATE_MDY_WORD.sub(blank, work)
        for m in list(_DATE_DMY_WORD.finditer(work)):
            mon = _month_no(m.group(2))
            if m.group(3) and mon:
                try:
                    check_date(m.group(0), date(int(m.group(3)), mon, int(m.group(1))))
                except ValueError:
                    check_date(m.group(0), None, None)
            elif mon:
                check_date(m.group(0), None, (int(m.group(1)), mon))
        work = _DATE_DMY_WORD.sub(lambda m: " " * len(m.group(0)), work)
        for m in list(_YM.finditer(work)):
            y = int(m.group(1))
            ok = y in years
            report["numbers"].append({"text": m.group(0), "kind": "period", "matched_fact": "period" if ok else None})
            if not ok:
                issues.append({"text": m.group(0), "sentence": sent, "hint": "period not found in the facts"})
        work = _YM.sub(blank, work)

        # identifiers (contract numbers) and line codes
        for m in list(_IDENT.finditer(work)):
            ok = m.group(0) in idents or m.group(0) in meta_idents
            report["numbers"].append({"text": m.group(0), "kind": "identifier", "matched_fact": "identifier" if ok else None})
            if not ok:
                issues.append({"text": m.group(0), "sentence": sent, "hint": "identifier not found in the facts"})
        work = _IDENT.sub(blank, work)
        for m in list(_LINE_CODES.finditer(work)):
            for code in re.findall(r"\d{3}", m.group(2)):
                ok = code in all_codes
                report["numbers"].append({"text": code, "kind": "line_code", "matched_fact": "line_code" if ok else None})
                if not ok:
                    issues.append({"text": code, "sentence": sent, "hint": "line code not among the facts"})
            work = work[: m.start(2)] + " " * (m.end(2) - m.start(2)) + work[m.end(2):]

        # quantities
        for m in _NUM.finditer(work):
            raw = m.group(0).strip()
            try:
                value, decimals = _num_value(m.group("num"))
            except ValueError:
                continue
            unit = _unit(m.group("suffix"))
            if unit == "none" and decimals == 0 and _YEAR.match(m.group("num")):
                ok = int(m.group("num")) in years
                report["numbers"].append({"text": raw, "kind": "year", "matched_fact": "year" if ok else None})
                if not ok:
                    issues.append({"text": raw, "sentence": sent, "hint": "year not found in the facts"})
                continue
            if not cited:
                report["numbers"].append({"text": raw, "kind": "number", "value": value, "matched_fact": None})
                issues.append({"text": raw, "sentence": sent, "hint": "sentence has no citation"})
                continue
            tol = 0.5 * 10 ** (-decimals) + 1e-9
            match = None
            for c in cited:
                if any(abs(abs(value) - abs(cand)) <= tol for cand in _candidates(facts[c], unit)):
                    match = c
                    break
            if match is None and unit in ("none", "days", "months", "times") and abs(value) in meta_nums:
                match = "label"
            if match is None:
                hint = "not the value of any cited fact"
                other = next((k for k, f in facts.items() if k not in cited and
                              any(abs(abs(value) - abs(cand)) <= tol for cand in _candidates(f, unit))), None)
                if other:
                    hint = f"matches {other}, which is not cited in this sentence"
                issues.append({"text": raw, "sentence": sent, "hint": hint})
            report["numbers"].append({"text": raw, "kind": "number", "value": value, "unit": unit, "matched_fact": match})

        if issues:
            report["unmatched"].extend(issues)
            if not cited and any(i["hint"] == "sentence has no citation" for i in issues):
                report["uncited_sentences"].append(sent)

    report["ok"] = not (report["unmatched"] or report["uncited_sentences"] or report["unknown_ids"] or report["forbidden"])
    return report


def feedback_message(report: dict) -> str:
    """Feedback appended to the prompt when a draft is rejected."""
    lines = ["Your previous draft was rejected by the citation verifier. Fix exactly these problems:"]
    for u in report.get("unmatched", [])[:12]:
        lines.append(f"- \"{u['text']}\" ({u['hint']}) in: {u['sentence'][:160]}")
    if report.get("unknown_ids"):
        lines.append(f"- Unknown citation ids (use only ids from the facts): {', '.join(report['unknown_ids'])}")
    if report.get("forbidden"):
        lines.append(f"- Forbidden wording (no approval/rejection/score language): {', '.join(report['forbidden'])}")
    lines.append("Use only numbers that appear as `display` or `value` of the facts you cite in the same sentence.")
    return "\n".join(lines)


def facts_for_prompt(facts: dict[str, FactDraft]) -> list[dict]:
    """The fact set sent to the LLM: ids, labels, values and the display strings it should copy."""
    out = []
    for k, f in facts.items():
        d, u = fact_display(f)
        out.append({"id": k, "label": f.label, "value": round(f.value, 4), "unit": f.unit,
                    "display": f"{d} {u}".strip(), "period": f.period_label})
    return out


def verify_cfo_answer(answer: dict, facts: dict[str, FactDraft]) -> dict:
    """Verify the CFO answer JSON {direct_answer, table:[{label, fact_id}], cant_see, next_steps:[…]}."""
    parts = [str(answer.get("direct_answer") or "")]
    if answer.get("cant_see"):
        parts.append(str(answer["cant_see"]))
    parts.extend(str(s) for s in answer.get("next_steps") or [])
    rep = verify("\n".join(p for p in parts if p.strip()), facts)
    for row in answer.get("table") or []:
        fid = row.get("fact_id") or row.get("fact_key")
        if fid and fid not in facts and fid not in rep["unknown_ids"]:
            rep["unknown_ids"].append(fid)
        label_rep = verify(str(row.get("label") or ""), facts, check_forbidden=False)
        # a table label may restate its own fact's value when the row cites it
        if fid in facts and label_rep["unmatched"]:
            label_rep = verify(f"{row.get('label')} [{fid}]", facts, check_forbidden=False)
        rep["unmatched"].extend(label_rep["unmatched"])
    rep["ok"] = not (rep["unmatched"] or rep["uncited_sentences"] or rep["unknown_ids"] or rep["forbidden"])
    return rep
