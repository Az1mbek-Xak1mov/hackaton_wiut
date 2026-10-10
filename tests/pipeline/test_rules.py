import copy

from test_rules_fixtures import F1, F2, FAROVON_APP, FAROVON_DOCS, fact, farovon_ctx

from app.pipeline.rules import run_application_rules, run_application_rules_with_facts
from app.pipeline.rules.context import AppContext


def _ids(findings):
    return [(f.rule_id, f.severity) for f in findings]


def _keys(ctx):
    return set(ctx.index.by_key)


def test_hero_farovon_exactly_three_issues():
    ctx = farovon_ctx()
    findings, derived = run_application_rules_with_facts(ctx)
    assert _ids(findings) == [("R06", "attn"), ("R07", "watch"), ("R10", "neutral")]
    r06, r07, r10 = findings
    assert r06.label == "Undeclared obligation"
    assert r06.title == "Bank statement shows loan repayments not listed in the application"
    assert r06.params["contract_no"] == "2024-1177" and r06.params["day_of_month"] == 20
    assert "18.5 mln UZS" in r06.detail and "8 monthly repayments" in r06.detail
    assert r07.title == "2025 revenue differs between the application form and the income statement"
    assert "557.7 mln UZS" in r07.detail and "5.7%" in r07.detail
    assert r10.title == "Tax declaration for Q2 2026 not provided"
    # every evidence key resolves to a fact (extracted, aggregate or derived)
    keys = _keys(ctx)
    for f in findings:
        assert all(k in keys for k in f.evidence)
    assert all(d.key in keys for d in derived)


def test_r06_lt_liabilities_in_evidence_and_declared_contract_suppresses():
    ctx = farovon_ctx()
    r06 = [f for f in run_application_rules(ctx) if f.rule_id == "R06"][0]
    lt = ctx.index.stat("form1", "490", "2026-06-30")
    assert lt.key in r06.evidence
    app = dict(FAROVON_APP, declared_debts=[{"lender": "Hamkorbank", "contract_no": "2024/1177", "monthly": 18_500}],
               declared_debts_total=120_000)
    assert not [f for f in run_application_rules(farovon_ctx(app=app)) if f.rule_id == "R06"]


def test_r06_without_application_uses_form1_zero_liabilities():
    app = {k: v for k, v in FAROVON_APP.items() if not k.startswith("declared_debts")}
    f = [f for f in run_application_rules(farovon_ctx(app=app)) if f.rule_id == "R06"]
    assert f and f[0].title.endswith("no long-term liabilities on Form 1")


def test_r06_not_fired_without_loan_payments():
    assert not [f for f in run_application_rules(farovon_ctx(statement_kw={"loan": False})) if f.rule_id == "R06"]


def test_r07_within_tolerance():
    app = dict(FAROVON_APP, declared_revenue_fy=9_900_000.0)
    assert not [f for f in run_application_rules(farovon_ctx(app=app)) if f.rule_id == "R07"]


def test_r01_balance_mismatch():
    f1 = copy.deepcopy(F1)
    f1["2026-06-30"]["780"] = 4_200_000
    f1["2026-06-30"]["480"] = 2_259_800
    fs = run_application_rules(farovon_ctx(f1=f1))
    r01 = [f for f in fs if f.rule_id == "R01"]
    assert len(r01) == 1 and r01[0].severity == "attn" and "10.6 mln UZS" in r01[0].detail
    assert not [f for f in fs if f.rule_id == "R02"]


def test_r02_section_sum():
    f1 = copy.deepcopy(F1)
    f1["2025-12-31"]["770"] = 1_900_000
    f1["2025-12-31"]["780"] = 4_022_200
    fs = run_application_rules(farovon_ctx(f1=f1))
    r02 = [f for f in fs if f.rule_id == "R02"]
    assert r02 and r02[0].params["parent"] == "770"


def test_r03_income_statement_chain():
    f2 = copy.deepcopy(F2)
    f2["FY2025"]["030"] = 1_300_000
    fs = run_application_rules(farovon_ctx(f2=f2))
    r03 = [f for f in fs if f.rule_id == "R03"]
    assert len(r03) == 1 and r03[0].params["parent"] == "030" and r03[0].severity == "watch"


def test_r04_profit_vs_retained_earnings():
    re_ok = [fact("form1.450.retained_earnings", 1_000_000, "2025-12-31"),
             fact("form1.450.retained_earnings", 1_318_000, "2026-06-30")]
    assert not [f for f in run_application_rules(farovon_ctx(extra_facts=re_ok)) if f.rule_id == "R04"]
    re_bad = [fact("form1.450.retained_earnings", 1_000_000, "2025-12-31"),
              fact("form1.450.retained_earnings", 1_100_000, "2026-06-30")]
    r04 = [f for f in run_application_rules(farovon_ctx(extra_facts=re_bad)) if f.rule_id == "R04"]
    assert len(r04) == 1 and r04[0].params["period"] == "H1-2026"


def test_r05_inflows_far_below_revenue():
    ctx = farovon_ctx(statement_kw={"sales_per_receipt": 100_000_000.0})
    r05 = [f for f in run_application_rules(ctx) if f.rule_id == "R05"]
    assert len(r05) == 1 and r05[0].severity == "attn"
    cov = [ctx.index.by_key[k] for k in r05[0].evidence if ctx.index.by_key[k].unit == "pct"][0]
    assert 40 < cov.value < 41


def test_r05_hero_within_band():
    ctx = farovon_ctx()
    assert not [f for f in run_application_rules(ctx) if f.rule_id == "R05"]


def test_r08_statement_gap():
    ctx = farovon_ctx(statement_kw={"months": 3})
    fs = run_application_rules(ctx)
    r08 = [f for f in fs if f.rule_id == "R08"]
    assert r08 and "last 6 months" in r08[0].title


def test_r08_stale_form_period():
    f2 = {"FY2024": dict(F2["FY2025"]), "H1-2026": dict(F2["H1-2026"])}
    docs = [d for d in FAROVON_DOCS]
    docs[3] = dict(docs[3], period_start="2024-01-01", period_end="2024-12-31")
    app = dict(FAROVON_APP, declared_revenue_fy=None)
    fs = run_application_rules(farovon_ctx(f2=f2, docs=docs, app=app))
    r08 = [f for f in fs if f.rule_id == "R08"]
    assert any("FY 2025" in f.title for f in r08)


def test_r09_stir_mismatch():
    docs = [dict(d) for d in FAROVON_DOCS]
    docs[4]["stir"] = "309999999"
    r09 = [f for f in run_application_rules(farovon_ctx(docs=docs)) if f.rule_id == "R09"]
    assert len(r09) == 1 and r09[0].severity == "attn" and "Forma2_1H2026.pdf" in r09[0].detail


def test_r10_missing_form_and_statement():
    docs = [d for d in FAROVON_DOCS if d["uuid"] not in ("d5", "d6")]
    fs = run_application_rules(farovon_ctx(docs=docs, f2={"FY2025": F2["FY2025"]}))
    titles = [f.title for f in fs if f.rule_id == "R10"]
    assert "Income statement (Form 2) for H1 2026 not provided" in titles
    assert "Bank statement not provided" in titles


def test_r11_half_year_pattern():
    f2 = copy.deepcopy(F2)
    f2["H1-2026"].update({"010": 1_500_000, "030": 1_500_000 - 4_672_100})
    fs = run_application_rules(farovon_ctx(f2=f2))
    assert [f for f in fs if f.rule_id == "R11" and f.severity == "info"]


def test_r12_duplicate_and_conflicting_values():
    docs = [dict(d) for d in FAROVON_DOCS]
    docs.append(dict(docs[3], uuid="d7", filename="Forma2_2025_copy.pdf"))
    fs = run_application_rules(farovon_ctx(docs=docs))
    assert [f for f in fs if f.rule_id == "R12" and f.label == "Duplicate document"]

    ctx = farovon_ctx()
    a = ctx.index.stat("form2", "010", "FY2025")
    b = fact("form2.010.net_revenue", 9_900_000, "FY2025")
    ctx2 = AppContext(facts=ctx.facts + [b], transactions=ctx.transactions, documents=ctx.documents,
                      application=ctx.application, recurring=ctx.recurring,
                      fact_document={a.key: "d4", b.key: "d5"})
    conf = [f for f in run_application_rules(ctx2) if f.label == "Conflicting figures"]
    assert len(conf) == 1 and set(conf[0].evidence) == {a.key, b.key}


def test_findings_sorted_by_severity():
    docs = [dict(d) for d in FAROVON_DOCS]
    docs[4]["stir"] = "309999999"
    fs = run_application_rules(farovon_ctx(docs=docs))
    order = {"attn": 0, "watch": 1, "neutral": 2, "info": 3}
    assert [order[f.severity] for f in fs] == sorted(order[f.severity] for f in fs)
