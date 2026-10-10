"""LLM fallback for unmapped Form 1/2 rows (docs/plan/02-PIPELINE.md §3, step d).

For a row the dictionary could not map, the model chooses among the top-5 candidate codes (JSON-schema
constrained). The choice is accepted only if the code is not used yet in that column and every sum relation
involving it still holds; accepted rows become facts with confidence 0.75 and method `llm_fallback`."""
import logging
import time

from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from app.modules.llm import prompts
from app.modules.llm.provider import LLMError, LLMUnavailable, available, complete, parse_json

logger = logging.getLogger(__name__)

TOP_K = 5
MIN_SCORE = 40
CONFIDENCE = 0.75


def _norm(text: str) -> str:
    try:
        from app.pipeline.rows import norm_text
        return norm_text(text)
    except Exception:
        return " ".join((text or "").lower().split())


def candidates(form: str, label: str, used: set[str]) -> list:
    from app.pipeline import dictionary as dic
    nl = _norm(label)
    scored = []
    for e in dic.entries(form):
        if e.code in used:
            continue
        best = max((fuzz.token_set_ratio(nl, _norm(lab)) for lab in e.all_labels()), default=0)
        if best >= MIN_SCORE:
            scored.append((best, e))
    scored.sort(key=lambda x: -x[0])
    return [e for _, e in scored[:TOP_K]]


def _column_of(row: dict, facts: list) -> tuple[str, float | None]:
    """Period label and kUZS multiplier from the extracted fact nearest to this value on the same page."""
    from app.pipeline.numbers import parse_number
    same_page = [f for f in facts if f.page_n == row.get("page_n") and f.bbox]
    bbox = row.get("bbox")
    if not same_page or not bbox:
        return "cur", None
    near = min(same_page, key=lambda f: abs(f.bbox[2] - bbox[2]))
    raw = parse_number(near.printed) if near.printed else None
    mult = (near.value / raw) if raw else None
    return near.period_label or "cur", mult


def _sums_hold(form: str, values: dict[str, float], code: str) -> bool:
    from app.pipeline import dictionary as dic
    for chk in dic.check_sums(form, values):
        involved = chk["code"] == code or any(t.lstrip("+-") == code for t in chk["terms"])
        if involved and not chk["ok"]:
            return False
    return True


def resolve_unmapped(db: Session, form: str, facts: list, unmapped: list[dict], *, max_rows: int = 12,
                     deadline: float | None = None, document_id: int | None = None) -> tuple[list, list[dict]]:
    """Returns (new FactDrafts, rows still unmapped). Nothing happens when the LLM is off."""
    from app.pipeline.numbers import parse_number
    from app.pipeline.types import FactDraft

    if not unmapped or not available(db) or form not in ("form1", "form2"):
        return [], unmapped
    new, remaining, tried = [], [], 0
    for row in unmapped:
        label = (row.get("label") or "").strip()
        value = parse_number(row.get("value_printed") or "")
        if tried >= max_rows or value is None or sum(ch.isalpha() for ch in label) < 3 or \
                (deadline is not None and time.time() > deadline):
            remaining.append(row)
            continue
        period, mult = _column_of(row, facts)
        used = {f.line_code for f in facts + new if f.period_label == period and f.line_code}
        cands = candidates(form, label, used)
        if not cands:
            remaining.append(row)
            continue
        tried += 1
        schema = {"title": "line_choice", "type": "object",
                  "properties": {"code": {"type": ["string", "null"], "enum": [e.code for e in cands] + [None]},
                                 "reason": {"type": "string"}},
                  "required": ["code", "reason"]}
        payload = {"form": form, "row_text": row.get("text") or label, "amount": row.get("value_printed"),
                   "candidates": [{"code": e.code, "labels": e.all_labels()[:6]} for e in cands]}
        try:
            res = complete(db, "unmapped_line", [{"role": "system", "content": prompts.load("unmapped_line")},
                                                 {"role": "user", "content": str(payload)}],
                           json_schema=schema, document_id=document_id)
        except (LLMUnavailable, LLMError) as exc:
            logger.warning("unmapped-line fallback stopped: %s", exc)
            remaining.append(row)
            remaining.extend(unmapped[unmapped.index(row) + 1:])
            break
        choice = parse_json(res.text) or {}
        code = choice.get("code")
        entry = next((e for e in cands if e.code == code), None)
        kuzs = value * mult if mult else value
        values = {f.line_code: f.value for f in facts + new if f.period_label == period and f.line_code}
        if entry is None or code in used or not _sums_hold(form, {**values, code: kuzs}, code):
            remaining.append({**row, "llm": {"code": code, "accepted": False,
                                             "reason": "not a free candidate or breaks a sum check" if entry else
                                             (choice.get("reason") or "no candidate matched")}})
            continue
        new.append(FactDraft(field=entry.field, label=entry.label_en, value=kuzs, line_code=code,
                             period_label=period, printed=row.get("value_printed") or "", page_n=row.get("page_n"),
                             bbox=row.get("bbox"), passage=row.get("text") or label, confidence=CONFIDENCE,
                             method="llm_fallback",
                             note=f"mapped by the language model among {len(cands)} dictionary candidates: "
                                  f"{(choice.get('reason') or '')[:160]}"))
    return new, remaining
