import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.pipeline.extract_forms import extract_forms  # noqa: E402
from app.pipeline.parse import parse_document  # noqa: E402

from test_extract_fixtures import balanced_form1, form2_values, make_form_pdf  # noqa: E402

F2_CUR, F2_PREV = form2_values(2), form2_values(3, revenue=5_812_400)
F1_CUR, F1_PREV = balanced_form1(1), balanced_form1(7)


def _run(tmp_path, form, cur, prev, **kw):
    pdf = make_form_pdf(tmp_path / "f.pdf", form, cur, prev, **kw)
    doc = parse_document(str(pdf), "application/pdf", tmp_path / "out")
    facts, unmapped = extract_forms(doc)
    return doc, facts, unmapped


def _check(facts, cur, prev, cur_label, prev_label, mult=1.0):
    by = {(f.line_code, f.period_label): f for f in facts}
    for code, v in cur.items():
        assert by[(code, cur_label)].value == pytest.approx(v * mult, abs=1), code
    for code, v in prev.items():
        assert by[(code, prev_label)].value == pytest.approx(v * mult, abs=1), code


@pytest.mark.parametrize("lang,period_text,cur_label,prev_label", [
    ("ru", "за 1 полугодие 2026 года", "H1-2026", "H1-2025"),
    ("uz_cyrl", "2025 йил учун", "FY2025", "FY2024"),
])
def test_form2_official_four_columns(tmp_path, lang, period_text, cur_label, prev_label):
    doc, facts, _ = _run(tmp_path, "form2", F2_CUR, F2_PREV, lang=lang, period_text=period_text)
    assert doc.doc_type == "form2" and doc.language == lang
    _check(facts, F2_CUR, F2_PREV, cur_label, prev_label)
    rev = next(f for f in facts if f.line_code == "010" and f.period_label == cur_label)
    assert rev.field == "form2.010.net_revenue" and rev.method == "dictionary" and rev.confidence >= 0.95
    assert rev.printed == "6 349 900" and rev.page_n == 1 and rev.bbox and rev.passage


def test_form1_two_columns_uz_cyrillic_balances(tmp_path):
    doc, facts, _ = _run(tmp_path, "form1", F1_CUR, F1_PREV, lang="uz_cyrl",
                         period_text="2025 йил 31 декабрь ҳолатига", unit_text="минг сўм")
    assert doc.doc_type == "form1"
    _check(facts, F1_CUR, F1_PREV, "2025-12-31", "2024-12-31")
    assert not [f for f in facts if "sum check failed" in f.note]


def test_units_in_mln_converted(tmp_path):
    cur = {k: v for k, v in F2_CUR.items()}
    _, facts, _ = _run(tmp_path, "form2", cur, {}, lang="ru", layout="2col", period_text="за 2025 год",
                       unit_text="млн сум", value_fmt=lambda v: f"{v / 1000:,.1f}".replace(",", " "))
    rev = next(f for f in facts if f.line_code == "010")
    assert rev.value == pytest.approx(6_349_900, abs=100) and "mln" in rev.note


def test_english_layout_without_codes_matched_by_label(tmp_path):
    _, facts, _ = _run(tmp_path, "form2", F2_CUR, F2_PREV, lang="en", layout="2col", codes=False,
                       period_text="for the year 2025", unit_text="UZS '000")
    by = {(f.line_code, f.period_label): f for f in facts}
    assert by[("010", "FY2025")].value == pytest.approx(F2_CUR["010"])
    assert by[("270", "FY2025")].value == pytest.approx(F2_CUR["270"])
    assert all(f.method == "fuzzy" and f.confidence <= 0.85 for f in facts)
    assert "non-statutory" in by[("010", "FY2025")].note


def test_blank_prior_cell_and_sum_check(tmp_path):
    cur = dict(F2_CUR)
    cur["270"] = cur["270"] + 5000  # break 240 - 250 - 260 = 270
    _, facts, _ = _run(tmp_path, "form2", cur, F2_PREV, lang="ru", period_text="за 2025 год", blank_prev={"250"})
    by = {(f.line_code, f.period_label): f for f in facts}
    assert ("250", "FY2024") not in by
    assert "prior-period cell blank" in by[("250", "FY2025")].note
    np_ = by[("270", "FY2025")]
    assert "sum check failed" in np_.note and np_.confidence <= 0.85
