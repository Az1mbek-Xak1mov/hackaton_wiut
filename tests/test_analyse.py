from tests import fakes
from tests.conftest import demo_auth

PDF_FY = b"%PDF-1.4\n" + b"x" * 100 + b"\n%%EOF FY2025 form2"
PDF_UNKNOWN = b"%PDF-1.4\n" + b"x" * 100 + b"\n%%EOF UNKNOWN letter"


def test_public_analyse_end_to_end(client, session_factory, monkeypatch):
    fakes.install(monkeypatch)
    r = client.post("/api/v1/analyse", files={"file": ("Forma2_2025.pdf", PDF_FY, "application/pdf")})
    assert r.status_code == 201, r.text
    uuid = r.json()["uuid"]
    assert r.json()["job"]["status"] == "queued"
    pending = client.get(f"/api/v1/analyse/{uuid}").json()
    assert pending["document"]["status"] == "queued" and pending["facts"] == []

    assert fakes.run_all_jobs(session_factory) == 1
    res = client.get(f"/api/v1/analyse/{uuid}").json()
    doc = res["document"]
    assert doc["doc_type"] == "form2" and doc["page_count"] == 1
    assert doc["status"] == "clarification"            # one figure below 80% confidence
    assert res["job"]["status"] == "done" and "parse" in res["job"]["stage_timings"]
    rev = next(f for f in res["facts"] if f["line_code"] == "010")
    assert rev["display"] == "9 842.3" and rev["display_unit"] == "mln UZS"
    assert rev["period_label"] == "FY2025"              # "cur" resolved from the document period
    assert rev["page_image_url"] == f"/api/v1/documents/{uuid}/pages/1.png"
    assert rev["page_width"] == 595 and rev["document"]["filename"] == "Forma2_2025.pdf"
    assert res["unmapped"][0]["text"] == "Unofficial line"
    assert res["readable"]["pages"] == 1
    img = client.get(rev["page_image_url"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    # anonymous evidence-store fetch works for public documents
    keys = ",".join(f["key"] for f in res["facts"])
    assert len(client.get(f"/api/v1/facts?keys={keys}").json()["facts"]) == len(res["facts"])


def test_unknown_document_still_answers(client, session_factory, monkeypatch):
    fakes.install(monkeypatch)
    uuid = client.post("/api/v1/analyse", files={"file": ("letter.pdf", PDF_UNKNOWN, "application/pdf")}).json()["uuid"]
    fakes.run_all_jobs(session_factory)
    res = client.get(f"/api/v1/analyse/{uuid}").json()
    assert res["document"]["doc_type"] == "unknown"
    assert res["document"]["type_reason"] == "no statutory line codes found"
    assert res["readable"] is not None and res["facts"] == []


def test_unsupported_format_is_answered_immediately(client):
    r = client.post("/api/v1/analyse", files={"file": ("notes.txt", b"hello world", "text/plain")})
    assert r.status_code == 201
    res = client.get(f"/api/v1/analyse/{r.json()['uuid']}").json()
    assert res["document"]["status"] == "failed"
    assert "Unsupported file type" in res["document"]["failure_cause"]
    assert res["job"]["status"] == "done"


def test_missing_pipeline_fails_truthfully(client, session_factory):
    uuid = client.post("/api/v1/analyse", files={"file": ("a.pdf", PDF_FY, "application/pdf")}).json()["uuid"]
    import app.modules.jobs.runner as runner
    original = runner.pipeline_fn

    def missing(module, name):
        raise runner.PipelineMissing(f"{module} missing")
    runner.pipeline_fn = missing
    try:
        fakes.run_all_jobs(session_factory)
    finally:
        runner.pipeline_fn = original
    doc = client.get(f"/api/v1/analyse/{uuid}").json()["document"]
    assert doc["status"] == "failed" and "not available in this build" in doc["failure_cause"]


def test_bank_document_requires_auth(client, session_factory, monkeypatch):
    fakes.install(monkeypatch)
    officer = demo_auth(client, "officer")
    r = client.post("/api/v1/documents", files={"file": ("f.pdf", PDF_FY, "application/pdf")}, headers=officer)
    assert r.status_code == 201
    uuid = r.json()["uuid"]
    assert client.get(f"/api/v1/documents/{uuid}").status_code == 401
    assert client.get(f"/api/v1/documents/{uuid}", headers=officer).status_code == 200
    assert client.get(f"/api/v1/analyse/{uuid}").status_code == 404   # not a public upload
    fakes.run_all_jobs(session_factory)
    token = officer["Authorization"].split()[1]
    assert client.get(f"/api/v1/documents/{uuid}/pages/1.png?token={token}").status_code == 200


def test_upload_too_large(client, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "PUBLIC_MAX_UPLOAD_MB", 0)
    r = client.post("/api/v1/analyse", files={"file": ("a.pdf", PDF_FY, "application/pdf")})
    assert r.status_code == 413 and r.json()["code"] == "file_too_large"
