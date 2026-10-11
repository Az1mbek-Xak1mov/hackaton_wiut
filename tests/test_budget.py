"""Owner budget (plan vs actual) and advice rules, LLM off; cash-flow spreadsheet → facts."""
from datetime import date

from openpyxl import Workbook

from app.modules.borrowers.models import Borrower
from app.modules.documents.models import Document
from app.modules.extraction.models import Fact
from app.pipeline.cashflow import extract_cashflow, parse_month
from app.pipeline.parse import parse_document
from app.pipeline.types import ParsedDoc, XlsxSheet
from app.pipeline.verify import verify
from app.modules.extraction.service import fact_to_draft
from tests.test_surfaces import _register

_n = [0]


def _fact(db, doc, field, label, kuzs, period):
    _n[0] += 1
    f = Fact(key=f"f_t{_n[0]:05d}", kind="aggregate", document_id=doc.id, field=field, label=label,
             period_label=period, value=kuzs, unit="kUZS", method="aggregate", passage="rows 1–9")
    db.add(f)
    return f


def _owner_with_statement(client, db):
    h = {"Authorization": f"Bearer {_register(client).json()['access_token']}"}
    b = db.query(Borrower).filter(Borrower.owner_user_id.is_not(None)).first()
    doc = Document(filename="vypiska_2026.xlsx", sha256="x" * 64, owner_kind="owner", borrower_id=b.id,
                   doc_type="bank_statement", status="done")
    db.add(doc)
    db.flush()
    # four months: cash falling every month, spending above income in the last one
    data = {"2026-06": (900_000, 700_000, 500_000), "2026-07": (800_000, 750_000, 450_000),
            "2026-08": (700_000, 760_000, 390_000), "2026-09": (600_000, 820_000, 170_000)}
    for ym, (inc, out, bal) in data.items():
        _fact(db, doc, f"statement.inflow.total.{ym}", f"Total inflows, {ym}", inc, ym)
        _fact(db, doc, f"statement.outflow.total.{ym}", f"Total outflows, {ym}", out, ym)
        _fact(db, doc, f"statement.balance_end.{ym}", f"Account balance, end of {ym}", bal, ym)
        _fact(db, doc, f"statement.outflow.loan_repayment.{ym}", f"Loan repayments paid, {ym}", 200_000, ym)
        _fact(db, doc, f"statement.outflow.salary.{ym}", f"Salaries paid, {ym}", 300_000, ym)
        _fact(db, doc, f"statement.inflow.sales_receipt.{ym}", f"Customer receipts, {ym}", inc, ym)
    f2 = Document(filename="forma2_2026.pdf", sha256="y" * 64, owner_kind="owner", borrower_id=b.id,
                  doc_type="form2", status="done")
    db.add(f2)
    db.flush()
    _fact(db, f2, "form2.010.net_revenue", "Net revenue", 9_000_000, "FY2026")
    db.commit()
    return h


def test_budget_plan_vs_actual(client, db):
    h = _owner_with_statement(client, db)
    empty = client.get("/api/v1/owner/budget", headers=h).json()
    assert empty["has_actuals"] and empty["months"][-1]["planned_spending"] is None
    r = client.put("/api/v1/owner/budget", headers=h, json={"lines": [
        {"month": "2026-09", "planned_income": 700_000_000, "planned_spending": 650_000_000},
        {"month": "2026-09", "category": "salary", "planned_spending": 250_000_000},
    ]})
    assert r.status_code == 200, r.text
    sep = next(m for m in r.json()["months"] if m["month"] == "2026-09")
    assert sep["source"] == "statement"
    assert sep["actual_spending"] == 820_000_000 and sep["spending_difference"] == 170_000_000
    assert sep["income_difference"] == -100_000_000
    assert sep["spending_ref"]["filename"] == "vypiska_2026.xlsx"
    sal = next(c for c in sep["categories"] if c["category"] == "salary")
    assert sal["difference"] == 50_000_000
    bad = client.put("/api/v1/owner/budget", headers=h, json={"lines": [{"month": "2026-13", "planned_income": 1}]})
    assert bad.status_code == 422


def test_advice_rules_llm_off(client, db):
    h = _owner_with_statement(client, db)
    assert client.get("/api/v1/owner/advice", headers=h).json()["items"] == []
    client.put("/api/v1/owner/budget", headers=h, json={"lines": [
        {"month": "2026-09", "planned_income": 700_000_000, "planned_spending": 650_000_000}]})
    out = client.post("/api/v1/owner/advice", headers=h).json()
    assert out["mode"] == "rules"
    ids = {it["id"] for it in out["items"]}
    assert {"A1", "A2", "B1", "B2", "C1", "D1"} <= ids
    facts = {k: fact_to_draft(f) for k, f in ((f.key, f) for f in db.query(Fact).all())}
    for it in out["items"]:
        assert it["text"] == it["rule_text"]
        assert verify(it["text"], facts)["ok"], (it["id"], verify(it["text"], facts))   # rule texts cite every number
        assert all(k in out["facts"] for k in it["fact_keys"])
    a1 = next(it for it in out["items"] if it["id"] == "A1")
    assert "170.0 mln UZS" in a1["text"] and a1["sources"][0]["filename"] == "vypiska_2026.xlsx"
    # a second run replaces the plan/difference facts instead of piling them up
    n = db.query(Fact).filter(Fact.field.like("budget.%")).count()
    client.post("/api/v1/owner/advice", headers=h)
    assert db.query(Fact).filter(Fact.field.like("budget.%")).count() == n
    assert client.get("/api/v1/owner/advice", headers=h).json()["items"]


def test_parse_month_variants():
    assert parse_month("2026-03") == "2026-03"
    assert parse_month("Mart 2026") == "2026-03"
    assert parse_month("Январь 2026") == "2026-01"
    assert parse_month("03.2026") == "2026-03"
    assert parse_month(date(2026, 5, 1)) == "2026-05"
    assert parse_month("Salary") is None


def test_cashflow_sheet_becomes_facts(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Cash flow"
    ws.append(["Cash flow 2026, thousand UZS"])
    ws.append(["Month", "Income", "Spending", "Balance"])
    ws.append(["January 2026", 120_000, 95_000, 40_000])
    ws.append(["February 2026", 110_000, 130_000, 20_000])
    p = tmp_path / "cashflow.xlsx"
    wb.save(p)
    parsed = parse_document(str(p), "", str(tmp_path / "out"), filename="cashflow.xlsx")
    assert parsed.doc_type == "cash_flow", parsed.type_reason
    facts = {f.field: f for f in extract_cashflow(parsed)}
    assert facts["cashflow.inflow.2026-01"].value == 120_000          # thousand UZS header → kUZS
    assert facts["cashflow.outflow.2026-02"].value == 130_000
    assert facts["cashflow.balance_end.2026-02"].value == 20_000
    assert "row 4" in facts["cashflow.inflow.2026-02"].passage


def test_cashflow_not_triggered_by_other_tables():
    doc = ParsedDoc(kind="xlsx", sheets=[XlsxSheet("S", [["Name", "Qty"], ["Yarn", 3]])])
    assert extract_cashflow(doc) == []
