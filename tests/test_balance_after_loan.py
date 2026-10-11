"""Balance after the loan: latest month-end balance fact + requested amount, added in Python, with its source."""
from datetime import date

from app.modules.applications.models import Application, Decision
from app.modules.borrowers.models import Borrower
from app.modules.documents.models import Document
from app.modules.extraction.models import Fact
from app.modules.owner.service import balance_after_loan
from tests.conftest import make_user

SIGNUP = {"email": "loan@example.uz", "password": "secret-pass-1", "full_name": "Loan Owner",
          "company_name": "Loan Textile MChJ", "stir": "305 118 744", "industry": "Textile", "region": "Namangan"}


def test_balance_after_loan_pure():
    assert balance_after_loan(None, 300000.0, None) == {"available": False, "reason": "no_bank_statement"}
    f = Fact(key="f_x", field="statement.balance_end.2026-04", value=1500.0, unit="kUZS")
    r = balance_after_loan(f, 300000.0, {"key": "f_x"})
    assert r["available"] and r["cash_now_kuzs"] == 1500.0 and r["loan_kuzs"] == 300000.0
    assert r["cash_after_kuzs"] == 301500.0 and r["as_of_month"] == "2026-04"
    assert r["cash_after_display"] == "301.5" and r["cash_fact"] == {"key": "f_x"}
    u = Fact(key="f_y", field="statement.balance_end.2026-04", value=2_000_000.0, unit="UZS")
    assert balance_after_loan(u, 1000.0, None)["cash_after_kuzs"] == 3000.0


def test_owner_items_balance_after(client, db):
    tok = client.post("/api/v1/auth/register", json=SIGNUP).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    b = db.query(Borrower).filter(Borrower.name == "Loan Textile MChJ").one()
    officer = make_user(db, "officer2@bank.uz", "officer")
    app = Application(number="A-LOAN-1", borrower_id=b.id, requested_amount=300000, term_months=12,
                      purpose="Working capital", status="in_review", received_on=date(2026, 5, 1))
    db.add(app)
    db.commit()
    item = client.get("/api/v1/owner/applications", headers=h).json()["items"][0]
    assert item["balance_after"] == {"available": False, "reason": "no_bank_statement"}

    st = Document(filename="vypiska.xlsx", sha256="c" * 64, owner_kind="owner", borrower_id=b.id,
                  doc_type="bank_statement", status="analyzed")
    db.add(st)
    db.flush()
    for i, (ym, v) in enumerate((("2026-03", 1500.0), ("2026-04", 2500.0))):
        db.add(Fact(key=f"f_loan{i:04d}", kind="aggregate", field=f"statement.balance_end.{ym}", label="Balance",
                    value=v, period_label=ym, document_id=st.id))
    db.commit()
    ba = client.get("/api/v1/owner/applications", headers=h).json()["items"][0]["balance_after"]
    assert ba["available"] and ba["as_of_month"] == "2026-04"
    assert ba["cash_now_kuzs"] == 2500.0 and ba["cash_after_kuzs"] == 302500.0
    assert ba["cash_fact"]["key"] == "f_loan0001" and ba["cash_fact"]["document"]["filename"] == "vypiska.xlsx"

    db.add(Decision(application_id=app.id, officer_id=officer.id, outcome="decline", reasoning="Not enough history."))
    app.status = "decided"
    db.commit()
    item = client.get("/api/v1/owner/applications", headers=h).json()["items"][0]
    assert item["balance_after"] is None and item["decision"]["outcome"] == "decline" and item["step"] == 4
