import test_rules_fixtures  # noqa: F401  (puts the repo root on sys.path)
from app.pipeline.types import FactDraft
from app.pipeline.verify import facts_for_prompt, feedback_message, verify, verify_cfo_answer


def F(key, value, unit="kUZS", label="", period="", line_code=None, field="x"):
    return FactDraft(field=field, label=label or key, value=value, unit=unit, period_label=period, line_code=line_code,
                     key=key)


FACTS = {f.key: f for f in [
    F("f_rev25", 9_842_316, label="Net revenue", period="FY2025", line_code="010", field="form2.010.net_revenue"),
    F("f_revh1", 5_316_400, label="Net revenue", period="H1-2026", line_code="010", field="form2.010.net_revenue"),
    F("f_dscr1", 1.4701, "ratio", label="Est. debt service coverage, requested loan only", period="H1-2026"),
    F("f_dscr2", 1.0357, "ratio", label="Est. debt service coverage incl. undeclared repayments", period="H1-2026"),
    F("f_loanm", 18_500, label="Loan repayments, contract 2024-1177 (ATB Hamkorbank), monthly (day 20)",
      period="2026-01..2026-08"),
    F("f_loanc", 8, "count", label="Loan repayments, contract 2024-1177: payments", period="2026-01..2026-08"),
    F("f_marg", 5.98, "pct", label="Net margin, H1 2026", period="H1-2026"),
    F("f_cash", -117_900, label="Change in cash", period="2026-09"),
    F("f_cr", 1.4795, "ratio", label="Current ratio, 30 Jun 2026", period="2026-06-30"),
]}


def test_accepts_cited_correct_numbers():
    text = ("Net revenue was 9 842.3 mln UZS in FY 2025 [f_rev25] and 5 316.4 mln UZS in H1 2026 [f_revh1]. "
            "Coverage is 1.47 for the requested loan [f_dscr1] and falls to 1.04 [f_dscr2]. "
            "Net margin was 6.0% [f_marg]. Cash fell by −117.9 mln UZS [f_cash].")
    r = verify(text, FACTS)
    assert r["ok"], r
    assert set(r["cited"]) == {"f_rev25", "f_revh1", "f_dscr1", "f_dscr2", "f_marg", "f_cash"}


def test_accepts_printed_thousands_and_other_scales():
    assert verify("Line 010 shows 9 842 316 [f_rev25].", FACTS)["ok"]
    assert verify("Revenue of 9.8 bn UZS [f_rev25].", FACTS)["ok"]
    assert verify("Revenue of 9,842,316 thousand UZS [f_rev25].", FACTS)["ok"]
    assert verify("Current ratio 1.5× at 30 Jun 2026 [f_cr].", FACTS)["ok"]


def test_rejects_invented_number():
    r = verify("Net revenue was 9 900.0 mln UZS in FY 2025 [f_rev25].", FACTS)
    assert not r["ok"] and r["unmatched"][0]["text"].startswith("9 900.0")


def test_rejects_number_cited_to_wrong_fact():
    r = verify("Coverage for the requested loan is 1.47 [f_dscr2].", FACTS)
    assert not r["ok"]
    assert "f_dscr1" in r["unmatched"][0]["hint"]


def test_rejects_uncited_sentence():
    r = verify("Revenue grew to 5 316.4 mln UZS. Coverage is adequate [f_dscr1].", FACTS)
    assert not r["ok"] and r["uncited_sentences"] == ["Revenue grew to 5 316.4 mln UZS."]


def test_rejects_unknown_id_and_forbidden_words():
    assert verify("Revenue was 9 842.3 mln UZS [f_nothere].", FACTS)["unknown_ids"] == ["f_nothere"]
    r = verify("We recommend to approve the loan [f_dscr1].", FACTS)
    assert not r["ok"] and r["forbidden"]
    assert not verify("The credit score is high.", FACTS)["ok"]
    assert not verify("Кредит можно одобрить.", FACTS)["ok"]


def test_whitelists_years_ordinals_identifiers_line_codes_and_label_numbers():
    text = ("1. Ask for contract 2024-1177 [f_loanm].\n"
            "2. The 8 repayments of 18.5 mln UZS were paid on day 20 [f_loanm] [f_loanc].\n"
            "Form 2 line 010 for 2025 shows 9 842.3 mln UZS [f_rev25].")
    r = verify(text, FACTS)
    assert r["ok"], r


def test_rejects_unknown_year_identifier_and_line_code():
    assert not verify("In 2019 revenue was 9 842.3 mln UZS [f_rev25].", FACTS)["ok"]
    assert not verify("Contract 2023-9999 shows 18.5 mln UZS [f_loanm].", FACTS)["ok"]
    assert not verify("Line 999 shows 9 842.3 mln UZS [f_rev25].", FACTS)["ok"]


def test_dates_must_come_from_facts():
    assert verify("At 30 Jun 2026 the current ratio was 1.48 [f_cr].", FACTS)["ok"]
    assert not verify("At 15 Mar 2026 the current ratio was 1.48 [f_cr].", FACTS)["ok"]


def test_cite_after_period_attaches_to_previous_sentence():
    assert verify("Revenue was 9 842.3 mln UZS. [f_rev25] Coverage is 1.47 [f_dscr1].", FACTS)["ok"]


def test_markdown_table_rows():
    text = "| Figure | Value | Record |\n|---|---|---|\n| Net revenue FY 2025 | 9 842.3 | [f_rev25] |"
    assert verify(text, FACTS)["ok"]


def test_feedback_and_prompt_facts():
    r = verify("Revenue was 9 900.0 mln UZS [f_rev25]. We approve.", FACTS)
    msg = feedback_message(r)
    assert "9 900.0" in msg and "approve" in msg
    pf = {p["id"]: p for p in facts_for_prompt(FACTS)}
    assert pf["f_rev25"]["display"] == "9 842.3 mln UZS" and pf["f_marg"]["display"] == "6.0%"


def test_cfo_answer_verification():
    ok = {"direct_answer": "Cash fell by 117.9 mln UZS in September [f_cash].",
          "table": [{"label": "Change in cash", "fact_id": "f_cash"}],
          "cant_see": "What I can't see: receivables by customer.", "next_steps": ["Ask the customer to pay."]}
    assert verify_cfo_answer(ok, FACTS)["ok"]
    bad = dict(ok, table=[{"label": "Change", "fact_id": "f_missing"}])
    assert not verify_cfo_answer(bad, FACTS)["ok"]
    bad2 = dict(ok, direct_answer="Cash fell by 120.0 mln UZS [f_cash].")
    assert not verify_cfo_answer(bad2, FACTS)["ok"]
