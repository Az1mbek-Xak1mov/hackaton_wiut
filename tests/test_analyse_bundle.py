import io
import zipfile
from datetime import timedelta

from tests import fakes
from tests.conftest import demo_auth

FY = b"%PDF-1.4\n" + b"y" * 50 + b"\n%%EOF FY2025 form2 file"
H1 = b"%PDF-1.4\n" + b"z" * 50 + b"\n%%EOF H1 2026 form2 file"
STATEMENT = b"%PDF-1.4\n" + b"s" * 50 + b"\n%%EOF STATEMENT 2026 file"


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_zip_loan_file_end_to_end(client, session_factory, monkeypatch):
    fakes.install(monkeypatch)
    z = _zip({"loan/Forma2_2025.pdf": FY, "loan/Forma2_1H2026.pdf": H1, "../../etc/vypiska.pdf": STATEMENT,
              "notes.txt": b"hello", "__MACOSX/._x.pdf": b"junk", "loan/": b""})
    r = client.post("/api/v1/analyse/bundle", files=[("files", ("farovon.zip", z, "application/zip"))])
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["kind"] == "bundle"
    names = sorted(d["filename"] for d in body["documents"])
    assert names == ["Forma2_1H2026.pdf", "Forma2_2025.pdf", "vypiska.pdf"]   # base names only, no traversal
    assert [s["filename"] for s in body["skipped"]] == ["notes.txt"]
    uuid = body["uuid"]

    pending = client.get(f"/api/v1/analyse/bundle/{uuid}").json()
    assert pending["status"] == "reading" and pending["review"] is None
    assert all(d["job"]["status"] == "queued" for d in pending["documents"])

    fakes.run_all_jobs(session_factory)
    res = client.get(f"/api/v1/analyse/bundle/{uuid}").json()
    assert res["status"] == "done", res
    assert {d["doc_type"] for d in res["documents"]} == {"form2", "bank_statement"}
    missing = {m["key"] for m in res["missing"]}
    assert "loan_application" in missing and "form1_fy" in missing and "form2_fy" not in missing
    rv = res["review"]
    assert rv["issues"], "cross-document rules ran"
    assert any(f["rule_id"] == "R06" for f in rv["findings"])
    for f in rv["issues"]:
        assert all(k in rv["facts"] for k in f["evidence"])   # every cited fact travels with the result
    assert rv["narrative"]["markdown"]
    # documents of the loan file are public: anyone holding the uuid can open the evidence
    doc_uuid = res["documents"][0]["uuid"]
    assert client.get(f"/api/v1/analyse/{doc_uuid}").status_code == 200

    # never in the bank's queue, portfolio or borrower list
    officer = demo_auth(client, "officer")
    items = client.get("/api/v1/applications", headers=officer).json()["items"]
    assert all(not i["number"].startswith("PUB-") for i in items)
    borrowers = client.get("/api/v1/borrowers", headers=officer).json()["items"]
    assert all(b["name"] != "Uploaded loan file" for b in borrowers)
    queue = client.get("/api/v1/portfolio/summary", headers=officer).json()
    assert "PUB-" not in str(queue)


def test_multiple_files_and_single_zip_on_analyse(client, session_factory, monkeypatch):
    fakes.install(monkeypatch)
    r = client.post("/api/v1/analyse/bundle", files=[("files", ("a.pdf", FY, "application/pdf")),
                                                    ("files", ("b.pdf", H1, "application/pdf")),
                                                    ("files", ("c.txt", b"text", "text/plain"))])
    assert r.status_code == 201, r.text
    assert len(r.json()["documents"]) == 2 and r.json()["skipped"][0]["filename"] == "c.txt"
    # a ZIP sent to the single-document endpoint is answered as a loan file instead of "unsupported"
    r2 = client.post("/api/v1/analyse", files={"file": ("bundle.zip", _zip({"a.pdf": FY}), "application/zip")})
    assert r2.status_code == 201 and r2.json()["kind"] == "bundle"
    assert client.get(f"/api/v1/analyse/bundle/{r2.json()['uuid']}").status_code == 200


def test_caps(client, monkeypatch):
    import app.modules.analyse.bundle as bundle
    # file count: extras are skipped and listed
    z = _zip({f"f{i}.pdf": FY + str(i).encode() for i in range(14)})
    body = client.post("/api/v1/analyse/bundle", files=[("files", ("many.zip", z, "application/zip"))]).json()
    assert len(body["documents"]) == 12 and len(body["skipped"]) == 2
    assert "limit of 12" in body["skipped"][0]["reason"]
    # zip bomb: uncompressed size is checked (header and actual read), not the compressed size
    monkeypatch.setattr(bundle, "MAX_FILE_MB", 1)
    bomb = _zip({"bomb.pdf": b"%PDF-1.4\n" + b"\0" * (3 * 1024 * 1024)})
    assert len(bomb) < 100_000
    r = client.post("/api/v1/analyse/bundle", files=[("files", ("bomb.zip", bomb, "application/zip"))])
    assert r.status_code == 422 and r.json()["code"] == "no_supported_files"
    # total cap
    monkeypatch.setattr(bundle, "MAX_FILE_MB", 20)
    monkeypatch.setattr(bundle, "MAX_TOTAL_MB", 0)
    r = client.post("/api/v1/analyse/bundle", files=[("files", ("a.pdf", FY, "application/pdf"))])
    assert r.status_code == 413
    # nothing readable
    monkeypatch.setattr(bundle, "MAX_TOTAL_MB", 40)
    r = client.post("/api/v1/analyse/bundle", files=[("files", ("x.txt", b"hello", "text/plain"))])
    assert r.status_code == 422 and r.json()["code"] == "no_supported_files"


def test_expired_loan_file_is_gone(client, session_factory, monkeypatch):
    fakes.install(monkeypatch)
    uuid = client.post("/api/v1/analyse/bundle", files=[("files", ("a.pdf", FY, "application/pdf"))]).json()["uuid"]
    from app.core.timeutil import utcnow
    from app.modules.analyse.bundle import BundleService
    from app.modules.applications.models import Application
    from app.modules.borrowers.models import Borrower
    s = session_factory()
    app = s.query(Application).filter(Application.is_public.is_(True)).one()
    app.expires_at = utcnow() - timedelta(minutes=1)
    s.commit()
    assert client.get(f"/api/v1/analyse/bundle/{uuid}").status_code == 404
    assert BundleService(s).purge_expired() == 1
    assert s.query(Application).count() == 0 and s.query(Borrower).filter(Borrower.is_public.is_(True)).count() == 0
    s.close()
