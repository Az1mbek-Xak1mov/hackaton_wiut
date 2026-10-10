"""Two apps, two sign-in surfaces: owner self sign-up on converza.uz, officers on app.converza.uz."""
from app.modules.applications.models import Application
from tests import fakes
from tests.conftest import auth, make_user

PDF = b"%PDF-1.4\n" + b"q" * 60 + b"\n%%EOF FY2025 form2 owner"
SIGNUP = {"email": "Dilnoza@Example.uz", "password": "secret-pass-1", "full_name": "Dilnoza Karimova",
          "company_name": "Karimova Textile MChJ", "stir": "305 118 742", "industry": "Textile", "region": "Namangan"}


def _register(client, **over):
    return client.post("/api/v1/auth/register", json={**SIGNUP, **over})


def test_register_creates_owner_and_business(client):
    r = _register(client)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["user"]["role"] == "owner" and body["user"]["email"] == "dilnoza@example.uz"
    assert body["surface"] == "owner" and "application:read" not in body["scopes"]
    h = {"Authorization": f"Bearer {body['access_token']}"}
    me = client.get("/api/v1/owner/me", headers=h).json()
    assert me["business"]["name"] == "Karimova Textile MChJ" and me["business"]["stir"] == "305118742"
    assert _register(client).json()["code"] == "email_taken"
    assert _register(client, email="other@example.uz").json()["code"] == "stir_taken"
    no_stir = _register(client, email="third@example.uz", stir="", company_name="No STIR LLC")
    assert no_stir.status_code == 201
    assert _register(client, email="x@example.uz", password="short").status_code == 422
    assert _register(client, email="y@example.uz", stir="123").status_code == 422


def test_login_surface_mismatch(client, db):
    make_user(db, "officer@bank.uz", "officer")
    _register(client)
    wrong = client.post("/api/v1/auth/login?surface=owner",
                        data={"username": "officer@bank.uz", "password": "password123"})
    assert wrong.status_code == 403 and wrong.json()["code"] == "wrong_surface"
    assert "app.converza.uz" in wrong.json()["message"]
    wrong = client.post("/api/v1/auth/login?surface=bank",
                        data={"username": "dilnoza@example.uz", "password": "secret-pass-1"})
    assert wrong.status_code == 403 and "converza.uz" in wrong.json()["message"]
    owner = client.post("/api/v1/auth/login", data={"username": "dilnoza@example.uz", "password": "secret-pass-1"})
    assert owner.status_code == 200 and owner.json()["surface"] == "owner"
    h = {"Authorization": f"Bearer {owner.json()['access_token']}"}
    for path in ("/api/v1/applications", "/api/v1/borrowers", "/api/v1/portfolio/summary"):
        assert client.get(path, headers=h).status_code == 403     # owner tokens never pass bank scopes
    bank = auth(client, "officer@bank.uz")
    assert client.get("/api/v1/owner/me", headers=bank).status_code == 403


def test_demo_login_is_404_when_disabled(client, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "DEMO_LOGIN_ENABLED", False)
    assert client.post("/api/v1/auth/demo", json={"role": "officer"}).status_code == 404


def test_owner_application_reaches_the_officer(client, db, session_factory, monkeypatch):
    fakes.install(monkeypatch)
    make_user(db, "officer@bank.uz", "officer")
    owner = {"Authorization": f"Bearer {_register(client).json()['access_token']}"}
    assert client.post("/api/v1/owner/applications", headers=owner,
                       json={"requested_amount_mln": 300, "term_months": 12}).json()["code"] == "no_documents"
    up = client.post("/api/v1/owner/files", headers=owner, files={"file": ("Forma2_2025.pdf", PDF, "application/pdf")})
    assert up.status_code == 201
    fakes.run_all_jobs(session_factory)
    r = client.post("/api/v1/owner/applications", headers=owner,
                    json={"requested_amount_mln": 300, "term_months": 12, "purpose": "Working capital"})
    assert r.status_code == 201, r.text
    number = r.json()["number"]
    assert number.startswith("APP-") and len(number) == 13
    fakes.run_all_jobs(session_factory)
    mine = client.get("/api/v1/owner/applications", headers=owner).json()["items"]
    assert mine[0]["number"] == number and mine[0]["documents"] == 1 and mine[0]["status"] == "in_review"
    assert mine[0]["requested_display"] == "300.0"

    bank = auth(client, "officer@bank.uz")
    items = client.get("/api/v1/applications", headers=bank).json()["items"]
    assert [i["number"] for i in items] == [number] and items[0]["name"] == "Karimova Textile MChJ"
    review = client.get(f"/api/v1/applications/{number}/review", headers=bank)
    assert review.status_code == 200 and review.json()["applicant"]["name"] == "Karimova Textile MChJ"
    borrowers = client.get("/api/v1/borrowers", headers=bank).json()
    row = borrowers["items"][0]
    assert row["status"] == "not_monitored" and row["loan_id"] is None and "no loan" in row["reason"]
    detail = client.get(f"/api/v1/borrowers/{row['uuid']}", headers=bank)
    assert detail.status_code == 200 and detail.json()["loan"] is None
    d = detail.json()
    assert d["status"]["current"] == "not_monitored" and "Monitoring starts" in d["status"]["reason"]
    assert [a["number"] for a in d["applications"]] == [number] and d["applications"][0]["requested_display"] == "300.0"
    assert len(d["documents"]) == 1 and d["documents"][0]["doc_type"]
    assert all(k in d["facts"] for k in d["figure_keys"] + d["ratio_keys"])
    s = session_factory()
    assert s.query(Application).count() == 1
    s.close()


def test_officer_views_work_on_an_empty_database(client, db):
    make_user(db, "officer@bank.uz", "officer")
    bank = auth(client, "officer@bank.uz")
    p = client.get("/api/v1/portfolio/summary", headers=bank)
    assert p.status_code == 200
    body = p.json()
    assert body["monitored"] == 0 and body["warning"]["pct"] == 0.0 and body["queue"] == []
    b = client.get("/api/v1/borrowers", headers=bank).json()
    assert b["counts"]["all"] == 0 and b["items"] == []
    assert client.get("/api/v1/applications", headers=bank).json() == {"items": []}
    assert client.get("/api/v1/monitoring/runs/latest", headers=bank).json() == {"run": None}


def test_seed_creates_the_two_named_accounts(db, session_factory, monkeypatch):
    from app.core.config import settings
    from app.core.seed import seed
    from app.modules.borrowers.models import Borrower
    from app.modules.users.models import User
    monkeypatch.setattr(settings, "SEED_OWNER_PASSWORD", "owner-pass-1")
    monkeypatch.setattr(settings, "SEED_OFFICER_PASSWORD", "officer-pass-1")
    monkeypatch.setattr(settings, "DEMO_LOGIN_ENABLED", False)
    seed()
    seed()   # idempotent
    s = session_factory()
    users = {u.email: u.role for u in s.query(User).all()}
    assert users == {"owner@converza.uz": "owner", "officer@converza.uz": "officer"}
    b = s.query(Borrower).one()
    assert (b.name, b.stir, b.is_synthetic) == ("Farovon Savdo MChJ", "302447118", False)
    s.close()


def test_reset_data_keeps_users(client, db, session_factory, monkeypatch):
    from app.core.config import settings
    from app.modules.borrowers.models import Borrower
    from app.modules.documents.models import Document
    from app.modules.users.models import User
    from app.reset_data import main, reset
    fakes.install(monkeypatch)
    monkeypatch.setattr(settings, "SEED_OWNER_PASSWORD", "owner-pass-1")
    owner = {"Authorization": f"Bearer {_register(client).json()['access_token']}"}
    client.post("/api/v1/owner/files", headers=owner, files={"file": ("f.pdf", PDF, "application/pdf")})
    try:
        main([])
    except SystemExit as exc:
        assert "--yes" in str(exc)
    reset()
    s = session_factory()
    assert s.query(Document).count() == 0
    assert {u.email for u in s.query(User).all()} >= {"dilnoza@example.uz", "owner@converza.uz"}
    assert [b.name for b in s.query(Borrower).all()] == ["Farovon Savdo MChJ"]   # re-seeded owner business
    s.close()


def test_owner_sees_checklist_decision_and_can_answer_a_request(client, db, session_factory, monkeypatch):
    fakes.install(monkeypatch)
    make_user(db, "officer@bank.uz", "officer")
    owner = {"Authorization": f"Bearer {_register(client).json()['access_token']}"}
    empty = client.get("/api/v1/owner/checklist", headers=owner).json()
    assert empty["present"] == 0 and empty["total"] == 7 and [i["key"] for i in empty["items"]][:3] == \
        ["loan_application", "form1_fy", "form1_half"]
    client.post("/api/v1/owner/files", headers=owner, files={"file": ("Forma2_2025.pdf", PDF, "application/pdf")})
    fakes.run_all_jobs(session_factory)
    cl = {i["key"]: i for i in client.get("/api/v1/owner/checklist", headers=owner).json()["items"]}
    assert cl["form2_fy"]["present"] and cl["form2_fy"]["state"] == "ready"
    assert cl["form2_fy"]["document"]["period_end"] == "2025-12-31"
    assert not cl["form2_half"]["present"] and not cl["loan_application"]["present"]

    number = client.post("/api/v1/owner/applications", headers=owner,
                         json={"requested_amount_mln": 300, "term_months": 12, "purpose": "Working capital"}).json()["number"]
    fakes.run_all_jobs(session_factory)
    item = client.get("/api/v1/owner/applications", headers=owner).json()["items"][0]
    assert item["step"] == 3 and item["decision"] is None and not item["action_needed"]
    assert {m["key"] for m in item["missing_documents"]} >= {"loan_application", "form2_half", "bank_statement"}

    bank = auth(client, "officer@bank.uz")
    msg = "Please upload the income statement for the first half of 2026 so we can compare periods."
    r = client.post(f"/api/v1/applications/{number}/decision", headers=bank, json={"outcome": "request_info", "reasoning": msg})
    assert r.status_code == 201
    item = client.get("/api/v1/owner/applications", headers=owner).json()["items"][0]
    assert item["status"] == "waiting_on_applicant" and item["action_needed"] and item["can_add_documents"]
    assert item["decision"]["outcome"] == "request_info" and item["decision"]["message"] == msg
    assert item["decision"]["decided_at"]

    add = f"/api/v1/owner/applications/{item['uuid']}/documents"
    assert client.post(add, headers=owner, json={}).json()["code"] == "no_documents"   # nothing new yet
    h1 = b"%PDF-1.4\n" + b"q" * 60 + b"\n%%EOF Form2 H1 2026 owner upload"
    client.post("/api/v1/owner/files", headers=owner, files={"file": ("Forma2_H1_2026.pdf", h1, "application/pdf")})
    fakes.run_all_jobs(session_factory)
    r = client.post(add, headers=owner, json={})
    assert r.status_code == 200 and r.json()["status"] == "processing"
    fakes.run_all_jobs(session_factory)
    item = client.get("/api/v1/owner/applications", headers=owner).json()["items"][0]
    assert item["status"] == "in_review" and item["documents"] == 2 and not item["action_needed"]
    assert "form2_half" not in {m["key"] for m in item["missing_documents"]}

    client.post(f"/api/v1/applications/{number}/decision", headers=bank,
                json={"outcome": "recommend", "reasoning": "Figures reconcile across both periods; recommended to committee."})
    item = client.get("/api/v1/owner/applications", headers=owner).json()["items"][0]
    assert item["status"] == "decided" and item["step"] == 4 and not item["can_add_documents"]
    assert item["decision"]["outcome"] == "recommend"
    assert client.post(add, headers=owner, json={}).json()["code"] == "application_decided"
