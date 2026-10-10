import pytest
from test_rules_fixtures import FAROVON_APP, farovon_ctx

from app.pipeline.compute import (
    ComputeError, compute, display_with_unit, evaluate, fact_display, format_display, render_formula,
)
from app.pipeline.ratios import annuity, compute_ratios, latest_ratio
from app.pipeline.types import FactDraft


def _disp(facts, field):
    f = latest_ratio(facts, field)
    return fact_display(f)[0] if f else None


def test_hero_ratios_match_design():
    ctx = farovon_ctx()
    rs = compute_ratios(ctx)
    assert _disp(rs, "ratio.current_ratio") == "1.48"
    assert _disp(rs, "ratio.quick_ratio") == "0.75"
    assert _disp(rs, "ratio.net_margin") == "6.0%"
    fy = [f for f in rs if f.field == "ratio.net_margin" and f.period_label == "FY2025"][0]
    assert fact_display(fy)[0] == "6.2%"
    assert _disp(rs, "ratio.debt_to_equity") == "0.85"
    assert _disp(rs, "ratio.receivable_days") == "31"
    assert _disp(rs, "ratio.installment_vs_revenue") == "5.0%"
    assert _disp(rs, "ratio.dscr_new_loan") == "1.47"
    assert _disp(rs, "ratio.dscr_incl_undeclared") == "1.04"
    inst = [f for f in rs if f.field == "loan.installment"][0]
    assert display_with_unit(inst) == "44.1 mln UZS"
    cr = latest_ratio(rs, "ratio.current_ratio")
    assert cr.note == "2 870.4 ÷ 1 940.2" and len(cr.inputs) == 2 and cr.kind == "computed"
    # ratio facts are added to the index (citable) but not duplicated into derived_facts
    assert all(f.key in ctx.index.by_key for f in rs)
    assert not set(f.key for f in rs) & set(f.key for f in ctx.derived_facts)


def test_dscr_without_undeclared_loans_has_no_second_figure():
    rs = compute_ratios(farovon_ctx(statement_kw={"loan": False}))
    assert latest_ratio(rs, "ratio.dscr_incl_undeclared") is None
    assert _disp(rs, "ratio.dscr_new_loan") == "1.47"


def test_installment_from_application_value_when_rate_unknown():
    app = dict(FAROVON_APP, installment=50_000.0, rate_pct=None)
    rs = compute_ratios(farovon_ctx(app=app))
    inst = [f for f in rs if f.field == "loan.installment"][0]
    assert display_with_unit(inst) == "50.0 mln UZS" and inst.formula == "application record"


def test_annuity():
    assert round(annuity(850_000, 22, 24) / 1000, 1) == 44.1
    assert annuity(1200, 0, 12) == 100


def test_compute_safe_and_units():
    a = FactDraft(field="a", label="A", value=2_870_400, unit="kUZS", key="f_aaaaaa")
    b = FactDraft(field="b", label="B", value=1_940_200, unit="kUZS", key="f_bbbbbb")
    facts = {a.key: a, b.key: b}
    r = compute("f_aaaaaa / f_bbbbbb", facts)
    assert r.unit == "ratio" and round(r.value, 2) == 1.48 and r.inputs == ["f_aaaaaa", "f_bbbbbb"]
    assert r.key.startswith("f_") and r.method == "compute"
    assert compute("f_aaaaaa - f_bbbbbb", facts).unit == "kUZS"
    assert compute("(f_aaaaaa - f_bbbbbb) / f_bbbbbb * 100", facts, unit="pct").unit == "pct"
    with pytest.raises(ComputeError):
        compute("f_aaaaaa * f_bbbbbb", facts)  # money squared
    with pytest.raises(ComputeError):
        compute("f_aaaaaa + 1", facts)  # money plus a plain number
    with pytest.raises(ComputeError):
        compute("__import__('os').system('ls')", facts)
    with pytest.raises(ComputeError):
        compute("f_zzzzzz / 2", facts)
    with pytest.raises(ComputeError):
        evaluate("1 / 0", {})
    with pytest.raises(ComputeError):
        compute("f_aaaaaa ** 2", facts)
    assert render_formula("(f_aaaaaa - f_bbbbbb) / f_bbbbbb", facts) == "(2 870.4 − 1 940.2) ÷ 1 940.2"


def test_format_display():
    assert format_display(9_842_316, "kUZS") == ("9 842.3", "mln UZS")
    assert format_display(-117_900, "kUZS") == ("−117.9", "mln UZS")
    assert format_display(86_400_000, "kUZS", money_scale="bn") == ("86.4", "bn UZS")
    assert format_display(1.4795, "ratio") == ("1.48", "")
    assert format_display(-27.0, "pct", signed=True) == ("−27.0%", "")
    assert format_display(6.2, "pct", signed=True) == ("+6.2%", "")
    assert format_display(30.99, "days") == ("31", "days")
    assert format_display(18_500_000, "UZS") == ("18.5", "mln UZS")
