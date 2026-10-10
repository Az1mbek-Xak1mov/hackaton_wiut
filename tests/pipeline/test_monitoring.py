from datetime import date

from test_rules_fixtures import fact

from app.pipeline.compute import new_fact_key
from app.pipeline.monitoring import MonitoringContext, evaluate_borrower, threshold_disclosure
from app.pipeline.types import FactDraft, TxnDraft


def _zilola_facts(q3_revenue=1_289_000, rec_q3=403_000, cash_sep=65_500):
    return [
        fact("form2.010.net_revenue", 1_790_000, "Q2-2026"),
        fact("form2.010.net_revenue", q3_revenue, "Q3-2026"),
        fact("form1.210.receivables_total", 286_000, "2026-06-30"),
        fact("form1.210.receivables_total", rec_q3, "2026-09-30"),
        fact("form1.610.trade_payables", 200_000, "2026-03-31"),
        fact("form1.610.trade_payables", 205_000, "2026-06-30"),
        fact("form1.610.trade_payables", 210_000, "2026-09-30"),
        FactDraft(field="statement.balance_end.2026-09", label="Account balance, end of Sep 2026", value=cash_sep,
                  unit="kUZS", kind="aggregate", period_label="2026-09-30", key=new_fact_key()),
    ]


def _loan(late_last=True):
    dues = [date(2025, 11, 15), date(2025, 12, 15)] + [date(2026, m, 15) for m in range(1, 10)]
    out = [{"n": i + 1, "due_on": d, "paid_on": d} for i, d in enumerate(dues)]
    if late_last:
        out[-1]["paid_on"] = date(2026, 9, 17)
    return {"installment": 46_800.0, "due_day": 15, "repayments": out, "contract_no": "L-2025-0417"}


STATEMENT_DOC = [{"doc_type": "bank_statement", "period_start": "2026-07-01", "period_end": "2026-09-30"}]


def test_zilola_attention_with_four_indicators():
    loan = _loan()
    assert loan["repayments"][-1]["due_on"] == date(2026, 9, 15)
    res = evaluate_borrower(MonitoringContext(facts=_zilola_facts(), loan=loan, documents=STATEMENT_DOC,
                                              as_of=date(2026, 10, 10)))
    ind = res["indicators"]
    assert res["status"] == "attn"
    assert ind["M01"]["triggered"] and ind["M01"]["display"] == "−28.0%" and ind["M01"]["basis"] == "vs Q2 2026"
    assert ind["M02"]["triggered"] and ind["M02"]["display"] == "+40.9%"
    assert not ind["M03"]["triggered"]
    assert ind["M04"]["triggered"] and ind["M04"]["display"] == "1.4×"
    assert ind["M05"]["triggered"] and ind["M05"]["value"] == 2
    assert not ind["M06"]["triggered"]
    assert [f.rule_id for f in res["findings"]] == ["M01", "M02", "M04", "M05"]
    assert res["reason"].startswith("Revenue −28.0% vs Q2 2026; Receivables +40.9% while revenue fell")
    keys = {f.key for f in res["facts"]} | {f.key for f in _zilola_facts()}
    for f in res["findings"]:
        assert f.evidence
    assert res["trend_pct"] == -27.99 and round(res["coverage"], 2) == 1.4
    del keys


def test_stable_borrower():
    res = evaluate_borrower(MonitoringContext(facts=_zilola_facts(q3_revenue=1_800_000, rec_q3=290_000,
                                                                  cash_sep=150_000),
                                              loan=_loan(late_last=False), documents=STATEMENT_DOC,
                                              as_of=date(2026, 10, 10)))
    assert res["status"] == "stable" and res["reason"] == "All indicators within range" and not res["findings"]


def test_watch_on_single_indicator_and_late_statement():
    res = evaluate_borrower(MonitoringContext(facts=_zilola_facts(q3_revenue=1_800_000, rec_q3=290_000),
                                              loan=_loan(late_last=False), documents=STATEMENT_DOC,
                                              as_of=date(2026, 10, 10)))
    assert res["status"] == "watch" and [f.rule_id for f in res["findings"]] == ["M04"]
    late_docs = [{"doc_type": "bank_statement", "period_start": "2026-06-01", "period_end": "2026-08-31"}]
    res2 = evaluate_borrower(MonitoringContext(facts=_zilola_facts(q3_revenue=1_800_000, rec_q3=290_000,
                                                                   cash_sep=150_000),
                                               loan=_loan(late_last=False), documents=late_docs,
                                               as_of=date(2026, 10, 25)))
    assert res2["indicators"]["M06"]["triggered"] and res2["status"] == "watch"
    assert "Sep 2026 statement not uploaded, 15 days past covenant date" == res2["reason"]


def test_punctuality_inferred_from_statement():
    txns = [TxnDraft(row_n=10 + m, booked_on=date(2026, m, 15 if m < 9 else 17), amount=-46_800_000.0,
                     category="loan_repayment", purpose="Kredit to'lovi") for m in (7, 8, 9)]
    res = evaluate_borrower(MonitoringContext(facts=_zilola_facts(q3_revenue=1_800_000, rec_q3=290_000,
                                                                  cash_sep=150_000),
                                              transactions=txns, loan={"installment": 46_800.0, "due_day": 15},
                                              documents=STATEMENT_DOC, as_of=date(2026, 10, 10)))
    assert res["indicators"]["M05"]["triggered"] and res["status"] == "attn"
    lf = [f for f in res["facts"] if f.field == "monitoring.days_late"][0]
    assert lf.passage == "row 19 of the bank statement"


def test_threshold_disclosure_lists_all_indicators():
    d = threshold_disclosure()
    assert [x["id"] for x in d] == ["M01", "M02", "M03", "M04", "M05", "M06"]
