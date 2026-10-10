"""A failing 'describe' stage (e.g. a value the facts table cannot hold) must not fail the whole job."""
from tests import fakes
from tests.test_analyse import PDF_UNKNOWN


def _broken_describe(db, doc):
    from app.modules.extraction.models import Fact
    db.add(Fact(key="f_broken", field="readable.number.1", value=None, document_id=doc.id))   # NOT NULL violation
    db.flush()


def test_describe_failure_degrades_to_no_description(client, session_factory, monkeypatch):
    import app.modules.jobs.runner as runner
    fakes.install(monkeypatch)
    extra = {("app.modules.llm.describe", "describe_document"): _broken_describe}
    monkeypatch.setattr(runner, "optional_fn", lambda m, n: extra.get((m, n)) or fakes.FAKES.get((m, n)))

    uuid = client.post("/api/v1/analyse", files={"file": ("letter.pdf", PDF_UNKNOWN, "application/pdf")}).json()["uuid"]
    fakes.run_all_jobs(session_factory)
    res = client.get(f"/api/v1/analyse/{uuid}").json()
    assert res["job"]["status"] == "done", res["job"]
    assert res["document"]["status"] != "failed"
    assert "describe" in res["job"]["stage_timings"]
    assert res["readable"] is not None                      # what was read is still shown
