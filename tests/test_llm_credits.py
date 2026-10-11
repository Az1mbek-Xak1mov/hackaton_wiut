"""The API key has no credits left (or is invalid): everything is still processed, no AI text is produced, and every
place a summary would appear says plainly why."""
import httpx
import pytest

from app.modules.llm import provider as prov
from app.modules.llm.provider import AnthropicProvider, LLMBadKey, LLMNoCredits, classify_failure
from tests.conftest import demo_auth
from tests.test_llm import _owner_books, _review, llm  # noqa: F401  (fixture re-export)
from tests.test_review import _make_application


class NoCreditsProvider:
    name, model = "fake", "fake-1"

    def __init__(self):
        self.calls = 0

    def complete(self, messages, tools=None, json_schema=None):
        self.calls += 1
        raise LLMNoCredits("openai: Error code: 429 - {'error': {'code': 'insufficient_quota'}}")


def test_no_credits_still_analyses_and_says_why(client, session_factory, llm):  # noqa: F811
    p = llm(NoCreditsProvider())
    officer = _make_application(client)
    v = _review(client, session_factory, officer)
    # figures, findings and ratios are computed without the LLM
    assert any(f["label"] == "Net revenue" for f in v["figures"])
    assert v["issues"] and v["ratios"]
    n = v["narrative"]
    assert n["mode"] != "llm"
    assert n["llm_status"] == "no_credits"
    assert "no credits left" in n["llm_status_text"]
    assert "still computed from the documents" in n["llm_status_text"]
    assert p.calls == 1          # remembered: no further calls while the quota is used up
    ver = client.get("/api/v1/version").json()
    assert ver["llm_status"] == "no_credits" and "no credits left" in ver["llm_status_text"]


def test_no_credits_cfo_answer_has_reason(client, db, llm):  # noqa: F811
    owner = demo_auth(client, "owner")
    _owner_books(db)
    llm(NoCreditsProvider())
    out = client.post("/api/v1/cfo/messages", json={"question": "account balance September"}, headers=owner).json()
    assert out["mode"] == "facts_only"
    assert out["answer"]["llm_status"] == "no_credits"
    assert out["answer"]["table"]


def test_version_reports_no_key_and_off(client, monkeypatch):
    from app.core.config import settings
    assert client.get("/api/v1/version").json()["llm_status"] == "no_key"   # tests run without OPENAI_API_KEY
    monkeypatch.setattr(settings, "LLM_PROVIDER", "none")
    v = client.get("/api/v1/version").json()
    assert v["llm_status"] == "off" and v["llm_status_text"].startswith("AI summary is switched off")


def test_status_expires(monkeypatch):
    prov._remember("no_credits", "x")
    assert prov._blocked() is not None
    monkeypatch.setattr(prov, "FAILURE_TTL_S", -1)
    assert prov._blocked() is None


@pytest.mark.parametrize("status,code,body,kind", [
    (429, "insufficient_quota", "You exceeded your current quota", LLMNoCredits),
    (429, None, "Rate limit reached for requests", None),
    (401, "invalid_api_key", "Incorrect API key provided", LLMBadKey),
    (400, None, '{"error":{"message":"Your credit balance is too low to access the Anthropic API."}}', LLMNoCredits),
    (500, None, "server error", None),
])
def test_classify_failure(status, code, body, kind):
    assert classify_failure(status, code, body) is kind


def test_anthropic_no_credits_and_bad_key():
    def make(status, msg):
        return AnthropicProvider("m", "k", transport=httpx.MockTransport(
            lambda r: httpx.Response(status, json={"type": "error", "error": {"message": msg}})))
    with pytest.raises(LLMNoCredits):
        make(400, "Your credit balance is too low to access the Anthropic API.").complete(
            [{"role": "user", "content": "q"}])
    with pytest.raises(LLMBadKey):
        make(401, "invalid x-api-key").complete([{"role": "user", "content": "q"}])
