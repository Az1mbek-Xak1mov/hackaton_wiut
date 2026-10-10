from test_rules_fixtures import farovon_ctx

from app.pipeline.narrative import (
    CLOSING_LINE, narrative_fact_set, repayment_indicator, template_narrative,
)
from app.pipeline.ratios import compute_ratios
from app.pipeline.rules import run_application_rules
from app.pipeline.verify import CITE_TOKEN, verify


def _hero():
    ctx = farovon_ctx()
    findings = run_application_rules(ctx)
    ratios = compute_ratios(ctx)
    return ctx, findings, ratios


def test_template_narrative_passes_verifier_and_cites():
    ctx, findings, ratios = _hero()
    md = template_narrative(ctx, findings, ratios)
    facts = {**ctx.index.by_key, **{f.key: f for f in ratios}}
    r = verify(md, facts)
    assert r["ok"], r
    assert "9 842.3 mln UZS" in md and "1.47" in md and "1.04" in md
    assert "Undeclared obligation" in md and "Contradiction" in md and "Missing document" in md
    assert md.strip().endswith(CLOSING_LINE)
    assert len(set(CITE_TOKEN.findall(md))) >= 8
    assert all(k in facts for k in CITE_TOKEN.findall(md))


def test_template_without_findings_or_ratios_is_still_true():
    ctx = farovon_ctx(f1={}, f2={}, statement_kw={"loan": False}, app={})
    md = template_narrative(ctx, [], [])
    assert verify(md, ctx.index.by_key)["ok"]
    assert "Not enough figures" in md


def test_repayment_indicator_matches_design_wording():
    ctx, findings, ratios = _hero()
    ind = repayment_indicator(ctx, findings, ratios)
    assert ind["label"] == "Adequate, with two unresolved issues"
    assert any("1.47" in s for s in ind["supports"])
    assert any("1.04" in s for s in ind["weighs_against"])
    assert "Not a validated credit score" in ind["disclaimer"]


def test_narrative_fact_set_contains_evidence_and_ratios():
    ctx, findings, ratios = _hero()
    fs = narrative_fact_set(ctx, findings, ratios)
    for f in findings:
        assert all(k in fs for k in f.evidence)
    fields = {f.field for f in fs.values()}
    assert {"ratio.dscr_new_loan", "ratio.dscr_incl_undeclared", "ratio.current_ratio"} <= fields
