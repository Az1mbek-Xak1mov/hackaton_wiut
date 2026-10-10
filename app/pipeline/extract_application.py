"""Loan-application form → facts (requested amount, term, rate, declared revenue/debts, purpose…).

The form is a list of "label / label / label: value" lines in UZ/RU/EN (labels in
dictionary/application.yaml). Amounts are converted to kUZS from so'm, thousand or mln so'm.
"""
from __future__ import annotations

import re

from rapidfuzz import fuzz

from app.pipeline.classify import light_norm
from app.pipeline.dictionary import application_fields
from app.pipeline.numbers import amount_to_kuzs, parse_number
from app.pipeline.rows import cluster_rows, norm_text, row_text, union_bbox
from app.pipeline.types import FactDraft, ParsedDoc, Row, Word

ORDER = ["requested_amount", "term_months", "rate_pct", "declared_revenue_fy", "declared_debts_total",
         "purpose", "collateral", "applicant_name", "stir"]
LABELS_EN = {"requested_amount": "Requested loan amount", "term_months": "Requested term", "rate_pct": "Interest rate",
             "declared_revenue_fy": "Revenue declared in the application", "declared_debts_total": "Existing debts declared in the application",
             "purpose": "Loan purpose", "collateral": "Collateral offered", "applicant_name": "Applicant", "stir": "Applicant STIR"}
_NUM = re.compile(r"\(?-?\d[\d \u00a0.,]*\d\)?|\d")


def _match_field(label: str) -> str | None:
    nl = norm_text(label)
    if not nl:
        return None
    fields = application_fields()["fields"]
    best, best_s = None, 0.0
    for key in ORDER:
        for labs in fields[key]["labels"].values():
            for lab in labs:
                nlab = norm_text(lab)
                if not nlab:
                    continue
                if re.search(rf"(?:^|\b){re.escape(nlab)}(?:\b|$)", nl):
                    s = 100.0 + len(nlab) / 100.0     # exact containment, longer label wins
                else:
                    s = fuzz.partial_ratio(nlab, nl) if len(nlab) >= 6 else 0.0
                if s > best_s:
                    best, best_s = key, s
    return best if best_s >= 92 else None


def _split(row: Row) -> tuple[list[Word], list[Word]] | None:
    for i, w in enumerate(row.words):
        if w.text.endswith(":") or (w.text == ":" and i > 0):
            return row.words[: i + 1], row.words[i + 1:]
        if ":" in w.text[:-1] and not re.search(r"\d:\d", w.text):
            return row.words[: i + 1], row.words[i + 1:]
    return None


def _first_amount(text: str) -> tuple[float, str] | None:
    for m in _NUM.finditer(text):
        raw = m.group(0).strip()
        v = parse_number(raw, prefer_integer=True)
        if v is not None:
            return v, raw
    return None


def _year(text: str) -> int | None:
    m = re.search(r"\b(20\d{2})\b", text)
    return int(m.group(1)) if m else None


def extract_application(doc: ParsedDoc) -> list[FactDraft]:
    fields = application_fields()["fields"]
    none_words = [light_norm(w) for w in fields["declared_debts_total"].get("none_words", [])]
    facts: list[FactDraft] = []
    seen: set[str] = set()
    for page in doc.pages:
        rows = cluster_rows(page.words, page.n, ocr=page.ocr_used)
        for i, row in enumerate(rows):
            sp = _split(row)
            if not sp:
                continue
            lab_words, val_words = sp
            label = " ".join(w.text for w in lab_words).rstrip(":")
            key = _match_field(label)
            if not key or key in seen:
                continue
            wrapped = False
            if not val_words and i + 1 < len(rows):  # value wrapped to the next line
                val_words, wrapped = rows[i + 1].words, True
            # free-text values that wrap: continuation rows start at the left margin and carry no label
            if key in ("purpose", "collateral", "applicant_name") and not wrapped:
                for nxt in rows[i + 1:i + 3]:
                    nt = row_text(nxt)
                    if _split(nxt) or re.match(r"^\s*(?:\d+-bo'lim|\d+-бўлим|раздел|section)\b", light_norm(nt)) \
                            or abs(nxt.words[0].x0 - row.words[0].x0) > 6:
                        break
                    val_words = val_words + nxt.words
                    wrapped = True
            value_text = " ".join(w.text for w in val_words).strip()
            if not value_text:
                continue
            conf = 0.97
            if page.ocr_used:
                cs = [w.conf for w in val_words] or [0.5]
                conf = min(0.97, sum(cs) / len(cs) + 0.1)
            base = dict(page_n=page.n, bbox=_r(union_bbox(val_words)), label_bbox=_r(union_bbox(lab_words)),
                        passage=row_text(row) + ("\n" + row_text(rows[i + 1]) if wrapped else ""),
                        confidence=round(conf, 3), method="rule", kind="extracted", printed=value_text)
            f = _make(key, label, value_text, none_words, doc, base)
            if f is not None:
                facts.append(f)
                seen.add(key)
    return facts


def _r(b):
    return [round(x, 2) for x in b] if b else None


def _make(key: str, label: str, value_text: str, none_words: list[str], doc: ParsedDoc, base: dict) -> FactDraft | None:
    field = f"application.{key}"
    lab = LABELS_EN[key]
    lv = light_norm(value_text)
    if key in ("requested_amount", "declared_revenue_fy", "declared_debts_total"):
        if key == "declared_debts_total" and any(re.search(rf"(?:^|\b){re.escape(nw)}(?:\b|$)", lv) for nw in none_words) \
                and not re.search(r"\d", lv):
            return FactDraft(field=field, label=lab, value=0.0, unit="kUZS", note="declared: none", **base)
        amt = _first_amount(value_text)
        if amt is None:
            return None
        v, raw = amt
        unit_ctx = value_text + " " + label
        kuzs = amount_to_kuzs(v, unit_ctx)
        period = ""
        if key == "declared_revenue_fy":
            y = _year(label) or _year(value_text) or ((doc.period_end.year - 1) if doc.period_end else None)
            period = f"FY{y}" if y else ""
        return FactDraft(field=field, label=lab, value=round(kuzs, 4), unit="kUZS", period_label=period,
                         note=f"converted to thousand UZS from '{raw}'" if kuzs != v else "", **base)
    if key == "term_months":
        m = re.search(r"(\d+)\s*(мес|oy|ой|month|m\b)", lv)
        y = re.search(r"(\d+)\s*(год|лет|yil|йил|year)", lv)
        if m:
            n = int(m.group(1))
        elif y:
            n = int(y.group(1)) * 12
        else:
            a = _first_amount(value_text)
            if a is None:
                return None
            n = int(a[0])
        return FactDraft(field=field, label=lab, value=float(n), unit="count", note="months", **base)
    if key == "rate_pct":
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*%", value_text)
        if not m:
            return None
        return FactDraft(field=field, label=lab, value=float(m.group(1).replace(",", ".")), unit="pct", **base)
    if key == "stir":
        m = re.search(r"\b([2-7]\d{2}) ?(\d{3}) ?(\d{3})\b", value_text)
        if not m:
            return None
        return FactDraft(field=field, label=lab, value=0.0, unit="text", note="".join(m.groups()), **base)
    # free text: purpose, collateral, applicant_name
    return FactDraft(field=field, label=lab, value=0.0, unit="text", note=value_text, **base)
