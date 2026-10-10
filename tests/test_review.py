from tests import fakes
from tests.conftest import demo_auth

FY = b"%PDF-1.4\n" + b"y" * 50 + b"\n%%EOF FY2025 form2 file"
H1 = b"%PDF-1.4\n" + b"z" * 50 + b"\n%%EOF H1 2026 form2 file"
STATEMENT = b"%PDF-1.4\n" + b"s" * 50 + b"\n%%EOF STATEMENT 2026 file"


def _make_application(client):
    officer = demo_auth(client, "officer")
    r = client.post("/api/v1/applications", headers=officer, json={
        "borrower": {"name": "Farovon Savdo MChJ", "stir": "302447118", "industry": "Food distribution",
                     "region": "Tashkent", "employees": 42, "since": 2018},
        "number": "APP-2026-0931", "requested_amount": 850000, "term_months": 24, "rate_pct": 24,
        "purpose": "Working capital", "received_on": "2026-10-06"})
    assert r.status_code == 201, r.text
    for name, content in (("Forma2_2025.pdf", FY), ("Forma2_1H2026.pdf", H1), ("vypiska.pdf", STATEMENT)):
        up = client.post("/api/v1/applications/APP-2026-0931/documents", headers=officer,
                         files={"file": (name, content, "application/pdf")})
        assert up.status_code == 201, up.text
    return officer


def test_review_view_model(client, session_factory, monkeypatch):
    fakes.install(monkeypatch)
    officer = _make_application(client)
    fakes.run_all_jobs(session_factory)    # 3 document jobs, then the auto-enqueued application analysis
    r = client.get("/api/v1/applications/APP-2026-0931/review", headers=officer)
    assert r.status_code == 200, r.text
    v = r.json()
    assert set(v) >= {"application", "applicant", "request", "issues", "figures", "ratios", "indicator", "narrative",
                      "documents", "review_trail", "facts", "columns"}
    assert v["application"]["status"] == "in_review" and v["application"]["sla_days"] == 5
    assert v["applicant"]["stir"] == "302 447 118"
    assert v["request"]["amount_display"] == "850.0"
    assert [c["key"] for c in v["columns"]] == ["fy2025", "h1_2026"]
    rev = next(f for f in v["figures"] if f["label"] == "Net revenue")
    assert v["facts"][rev["cells"]["fy2025"]]["display"] == "9 842.3"
    assert v["facts"][rev["cells"]["h1_2026"]]["display"] == "5 316.4"
    inflow = next(f for f in v["figures"] if "inflows" in f["label"])
    assert inflow["cells"]["fy2025"] is None and inflow["cells"]["h1_2026"]
    labels = [i["label"] for i in v["issues"]]
    assert labels[0] == "Undeclared obligation" and "Missing document" in labels
    loan_evidence = v["issues"][0]["evidence"][0]
    assert loan_evidence in v["facts"]                        # cited fact is shipped with the view
    dscr = next(b for b in v["ratios"] if b["label"] == "Est. debt service coverage")
    assert dscr["value_display"] == "1.47 → 1.04" and dscr["flag"] is True
    assert any(b["value_display"] == "6.0%" for b in v["ratios"])
    assert v["indicator"]["label"] == "Adequate, with one unresolved issue"
    assert "Not a validated credit score" in v["indicator"]["disclaimer"]
    assert v["narrative"]["mode"] == "template" and v["narrative"]["verified"] is True
    assert "[f_" in v["narrative"]["markdown"]
    missing = [d for d in v["documents"] if d["status"] == "missing"]
    assert any("Tax declaration" in d["title"] for d in missing)
    assert any("Analysis completed" in t["text"] for t in v["review_trail"])

    items = client.get("/api/v1/applications", headers=officer).json()["items"]
    assert items[0]["number"] == "APP-2026-0931" and items[0]["issues_count"] == 2


def test_fact_review_and_decision(client, session_factory, monkeypatch):
    fakes.install(monkeypatch)
    officer = _make_application(client)
    fakes.run_all_jobs(session_factory)
    v = client.get("/api/v1/applications/APP-2026-0931/review", headers=officer).json()
    fact = v["facts"][next(f for f in v["figures"] if f["label"] == "Net revenue")["cells"]["fy2025"]]
    r = client.post(f"/api/v1/facts/{fact['uuid']}/review", json={"action": "verify"}, headers=officer)
    assert r.status_code == 200 and r.json()["status"] == "verified"
    bad = client.post(f"/api/v1/facts/{fact['uuid']}/review", json={"action": "correct"}, headers=officer)
    assert bad.status_code == 422
    short = client.post("/api/v1/applications/APP-2026-0931/decision", headers=officer,
                        json={"outcome": "recommend", "reasoning": "ok"})
    assert short.status_code == 422
    d = client.post("/api/v1/applications/APP-2026-0931/decision", headers=officer,
                    json={"outcome": "request_info", "reasoning": "Need the Q2 tax declaration and the 2024-1177 "
                                                                  "loan contract before committee.",
                          "evidence_reviewed": [fact["key"]]})
    assert d.status_code == 201
    trail = client.get("/api/v1/applications/APP-2026-0931/review", headers=officer).json()["review_trail"]
    assert any("verified Net revenue" in t["text"] for t in trail)
    assert any("recorded the decision" in t["text"] for t in trail)
