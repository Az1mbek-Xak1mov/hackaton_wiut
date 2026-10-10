import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.pipeline import dictionary as dic  # noqa: E402

from test_extract_fixtures import balanced_form1, form2_values  # noqa: E402


def test_loads_both_forms_with_unique_codes_and_slugs():
    f1, f2 = dic.entries("form1"), dic.entries("form2")
    assert len(f1) >= 26 and len(f2) >= 19
    assert len({e.code for e in f1}) == len(f1)
    assert len({e.slug for e in f2}) == len(f2)
    for e in f1 + f2:
        assert set(e.labels) >= {"uz_latn", "uz_cyrl", "ru", "en"}, e.code
        assert e.field == f"{e.form}.{e.code}.{e.slug}"


def test_design_codes_present_with_official_meaning():
    for code in ("140", "390", "400", "490", "600", "770", "780", "450", "480", "210", "320", "610"):
        assert dic.by_code("form1", code) is not None, code
    for code in ("010", "020", "030", "040", "170", "240", "250", "270"):
        assert dic.by_code("form2", code) is not None, code
    assert dic.code_for("form2", "finance_costs_total") == "170"
    assert dic.code_for("form2", "profit_tax") == "250"
    assert dic.code_for("form2", "pre_tax_profit") == "240"
    assert dic.code_for("form1", "total_liabilities_equity") == "780"
    assert dic.code_for("form1", "long_term_liabilities_total") == "490"
    assert dic.by_code("form2", "080") is None  # removed in the 2019 edition


def test_sum_relations_reference_known_codes_and_resolve():
    for form in ("form1", "form2"):
        for e in dic.entries(form):
            for t in list(e.sum_of) + list(e.parts):
                assert dic.by_code(form, t.lstrip("-")) is not None, (form, e.code, t)


def test_balanced_values_pass_all_checks():
    v1 = balanced_form1(3)
    assert all(c["ok"] for c in dic.check_sums("form1", v1))
    assert abs(v1["400"] - v1["780"]) < 0.5
    v2 = form2_values(4)
    assert all(c["ok"] for c in dic.check_sums("form2", v2))


def test_application_fields_loaded():
    f = dic.application_fields()["fields"]
    assert {"requested_amount", "term_months", "declared_revenue_fy", "declared_debts_total"} <= set(f)
