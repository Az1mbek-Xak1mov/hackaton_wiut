"""Owner dashboard: only stored facts from the owner's own documents, each with its source document."""
from app.modules.borrowers.models import Borrower
from app.modules.documents.models import Document
from app.modules.extraction.models import Fact

SIGNUP = {"email": "dash@example.uz", "password": "secret-pass-1", "full_name": "Dash Owner",
          "company_name": "Dash Textile MChJ", "stir": "305 118 743", "industry": "Textile", "region": "Namangan"}


def test_owner_dashboard_empty_then_from_facts(client, db):
    tok = client.post("/api/v1/auth/register", json=SIGNUP).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    empty = client.get("/api/v1/owner/dashboard", headers=h).json()
    assert empty["months"] == [] and empty["periods"] == [] and empty["cash_on_hand"] is None
    assert empty["has"] == {"bank_statement": False, "form2": False, "ratios": False}
    assert "score" not in str(empty).lower()

    b = db.query(Borrower).filter(Borrower.name == "Dash Textile MChJ").one()
    st = Document(filename="vypiska.xlsx", sha256="a" * 64, owner_kind="owner", borrower_id=b.id,
                  doc_type="bank_statement", status="analyzed")
    f2 = Document(filename="Forma2_2025.pdf", sha256="b" * 64, owner_kind="owner", borrower_id=b.id,
                  doc_type="form2", status="analyzed")
    db.add_all([st, f2])
    db.flush()
    rows = [("statement.inflow.total.2026-03", 900.0, None, "2026-03", st),
            ("statement.outflow.total.2026-03", 700.0, None, "2026-03", st),
            ("statement.balance_end.2026-03", 1500.0, None, "2026-03", st),
            ("statement.inflow.total.2026-04", 950.0, None, "2026-04", st),
            ("form2.010.net_revenue", 12000.0, "010", "FY2025", f2),
            ("form2.270.net_profit", 800.0, "270", "FY2025", f2)]
    for i, (field, v, code, p, d) in enumerate(rows):
        db.add(Fact(key=f"f_dash{i:04d}", field=field, label=field, value=v, line_code=code, period_label=p,
                    document_id=d.id, kind="aggregate" if d is st else "extracted"))
    db.commit()

    r = client.get("/api/v1/owner/dashboard", headers=h).json()
    assert [m["month"] for m in r["months"]] == ["2026-03", "2026-04"]
    assert r["months"][1]["money_out"] is None                       # absent stays absent, never invented
    assert r["cash_on_hand"] == "f_dash0002"
    assert r["periods"][0]["revenue"] == "f_dash0004" and r["periods"][0]["net_profit"] == "f_dash0005"
    assert r["facts"]["f_dash0004"]["document"]["filename"] == "Forma2_2025.pdf"
    assert r["has"]["bank_statement"] and r["has"]["form2"] and not r["has"]["ratios"]
