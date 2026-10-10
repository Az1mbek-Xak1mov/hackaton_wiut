"""LLM paths with a fake provider: verified narrative (accepted / rejected-then-accepted / all rejected → template),
the CFO tool loop, the unmapped-line fallback and the Anthropic wire format."""
import json
import sys
from datetime import date

import httpx
import pytest

import app.pipeline.verify as real_verify
from app.modules.llm.provider import AnthropicProvider, LLMResult, ToolCall, set_provider_override
from app.pipeline.types import FactDraft
from tests import fakes
from tests.conftest import demo_auth
from tests.test_review import _make_application


class FakeProvider:
    name, model = "fake", "fake-1"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def complete(self, messages, tools=None, json_schema=None):
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools, "json_schema": json_schema})
        reply = self.replies.pop(0)
        if callable(reply):
            reply = reply(messages)
        if isinstance(reply, str):
            reply = LLMResult(text=reply, usage={"prompt_tokens": 100, "completion_tokens": 20})
        reply.message = reply.message or {"role": "assistant", "content": reply.text}
        return reply


@pytest.fixture()
def llm(monkeypatch):
    """Fake pipeline stages + the REAL verifier + a fake narrative fact set; yields an injector."""
    fakes.install(monkeypatch)
    monkeypatch.setitem(sys.modules, "app.pipeline.verify", real_verify)
    narrative = sys.modules["app.pipeline.narrative"]
    narrative.narrative_fact_set = lambda ctx, findings, ratio_facts, limit=60: {
        f.key: f for f in list(ctx.facts) + list(ratio_facts) if f.key}

    def install(provider):
        set_provider_override(provider)
        return provider
    yield install
    set_provider_override(None)


def _revenue_key(messages) -> str:
    payload = json.loads(messages[1]["content"])
    return next(f["id"] for f in payload["facts"] if f["label"] == "Net revenue" and f["period"] == "FY2025")


def _good(messages):
    return f"Net revenue was 9 842.3 mln UZS in the last financial year [{_revenue_key(messages)}]."


def _bad(messages):
    return f"Net revenue was 9 999.9 mln UZS [{_revenue_key(messages)}]."


def _review(client, session_factory, officer):
    fakes.run_all_jobs(session_factory)
    return client.get("/api/v1/applications/APP-2026-0931/review", headers=officer).json()


def test_narrative_accepted_first_time(client, session_factory, llm):
    p = llm(FakeProvider([_good]))
    officer = _make_application(client)
    v = _review(client, session_factory, officer)
    n = v["narrative"]
    assert n["mode"] == "llm" and n["verified"] is True and n["attempts"] == 1 and n["rejected"] == []
    assert "9 842.3 mln UZS" in n["markdown"]
    sent = json.loads(p.calls[0]["messages"][1]["content"])
    assert "Farovon" not in json.dumps(sent) and "302447118" not in json.dumps(sent)   # LLM_REDACT
    assert any("AI draft accepted" in t["text"] for t in v["review_trail"])


def test_narrative_rejected_then_accepted(client, session_factory, llm):
    p = llm(FakeProvider([_bad, _good]))
    officer = _make_application(client)
    n = _review(client, session_factory, officer)["narrative"]
    assert n["mode"] == "llm" and n["verified"] and n["attempts"] == 2
    assert len(n["rejected"]) == 1 and n["rejected"][0]["unmatched"][0]["text"].startswith("9 999.9")
    feedback = p.calls[1]["messages"][-1]["content"]
    assert "rejected by the citation verifier" in feedback and "9 999.9" in feedback


def test_all_drafts_rejected_falls_back_to_template(client, session_factory, llm):
    llm(FakeProvider([_bad, _bad, _bad]))
    officer = _make_application(client)
    v = _review(client, session_factory, officer)
    n = v["narrative"]
    assert n["mode"] == "template" and n["verified"] is True and len(n["rejected"]) == 3
    trail = [t["text"] for t in v["review_trail"]]
    assert sum("rejected by the verifier" in t for t in trail) == 3


def test_llm_switch_off_uses_template_without_calls(client, session_factory, llm):
    p = llm(FakeProvider([]))
    officer = _make_application(client)
    client.put("/api/v1/settings/llm", json={"enabled": False}, headers=officer)
    n = _review(client, session_factory, officer)["narrative"]
    assert n["mode"] == "template" and p.calls == []


# ------------------------------------------------------------------------------------------------ CFO

def _owner_books(db, owner_email="owner@converza.uz"):
    from app.modules.borrowers.models import Borrower
    from app.modules.documents.models import Document
    from app.modules.extraction.service import persist_facts
    from app.modules.statements.models import Transaction
    from app.modules.users.models import User
    owner = db.query(User).filter(User.email == owner_email).one()
    b = Borrower(name="Navro'z Tekstil MChJ", stir="305118742", industry="Textile", region="Namangan",
                 owner_user_id=owner.id)
    db.add(b)
    db.flush()
    doc = Document(filename="bank_vypiska.xlsx", sha256="x" * 64, mime="xlsx", owner_kind="owner", borrower_id=b.id,
                   doc_type="bank_statement", status="analyzed", summary={})
    db.add(doc)
    db.flush()
    db.add_all([Transaction(document_id=doc.id, row_n=10, booked_on=date(2026, 9, 5), amount=-298_400_000,
                            counterparty="Payroll", category="salary"),
                Transaction(document_id=doc.id, row_n=11, booked_on=date(2026, 9, 12), amount=1_075_600_000,
                            counterparty="Toshkent Mato Bozori", category="sales_receipt")])
    persist_facts(db, [
        FactDraft(field="statement.balance_end.2026-08", label="Account balance, end of Aug 2026", value=436100,
                  kind="aggregate", period_label="2026-08-31", method="aggregate"),
        FactDraft(field="statement.balance_end.2026-09", label="Account balance, end of Sep 2026", value=318200,
                  kind="aggregate", period_label="2026-09-30", method="aggregate"),
    ], document=doc)
    db.commit()
    return b


def test_cfo_tool_loop_with_verified_answer(client, db, llm):
    owner = demo_auth(client, "owner")
    _owner_books(db)

    def search(messages):
        return LLMResult(text="", tool_calls=[ToolCall("c1", "search_facts", {"query": "account balance"})])

    def diff(messages):
        found = json.loads(messages[-1]["content"])["facts"]
        aug = next(f["id"] for f in found if "Aug" in f["label"])
        sep = next(f["id"] for f in found if "Sep" in f["label"])
        return LLMResult(text="", tool_calls=[ToolCall("c2", "compute", {"expression": f"{sep} - {aug}",
                                                                         "label": "Change in cash, September"})])

    def final(messages):
        fact = json.loads(messages[-1]["content"])["fact"]
        return json.dumps({"direct_answer": f"Cash fell by {fact['display'].split()[0]} mln UZS in September "
                                            f"[{fact['id']}].",
                           "table": [{"label": "Change in cash", "fact_id": fact["id"]}],
                           "cant_see": "Receivables by customer are not in the bank statement.",
                           "next_steps": ["Upload the sales ledger."]})
    p = llm(FakeProvider([search, diff, final]))
    r = client.post("/api/v1/cfo/messages", json={"question": "Why is my cash falling?"}, headers=owner)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["mode"] == "llm"
    assert out["answer"]["direct_answer"].startswith("Cash fell by −117.9 mln UZS")
    key = out["answer"]["table"][0]["fact_key"]
    assert " - " in out["facts"][key]["formula"] and out["facts"][key]["kind"] == "computed"
    assert [t["tool"] for t in out["tool_trace"]] == ["search_facts", "compute"]
    assert out["tool_trace"][1]["result_key"] == key
    assert p.calls[0]["tools"] and "Navro" not in p.calls[0]["messages"][1]["content"]
    hist = client.get("/api/v1/cfo/messages", headers=owner).json()["messages"]
    assert [m["role"] for m in hist] == ["user", "assistant"]


def test_cfo_unverifiable_answer_is_not_shown(client, db, llm):
    owner = demo_auth(client, "owner")
    _owner_books(db)
    made_up = json.dumps({"direct_answer": "Cash fell by 500.0 mln UZS.", "table": [], "cant_see": "",
                          "next_steps": []})
    llm(FakeProvider([made_up, made_up]))
    out = client.post("/api/v1/cfo/messages", json={"question": "How much cash do I have?"}, headers=owner).json()
    assert "can't answer that from the records" in out["answer"]["direct_answer"]
    assert any(t["tool"] == "verifier" for t in out["tool_trace"])
    assert "500.0" not in json.dumps(out["answer"])


def test_cfo_llm_off_returns_matching_facts(client, db, llm):
    owner = demo_auth(client, "owner")
    officer = demo_auth(client, "officer")
    _owner_books(db)
    p = llm(FakeProvider([]))
    client.put("/api/v1/settings/llm", json={"enabled": False}, headers=officer)
    out = client.post("/api/v1/cfo/messages", json={"question": "account balance September"}, headers=owner).json()
    assert out["mode"] == "facts_only" and "language model is off" in out["answer"]["direct_answer"]
    assert out["answer"]["table"] and all(r["fact_key"] in out["facts"] for r in out["answer"]["table"])
    assert p.calls == []


# ------------------------------------------------------------------------------------------------ unmapped lines

def test_unmapped_line_fallback_respects_sum_checks(db, llm):
    from app.modules.llm.unmapped import resolve_unmapped
    facts = [FactDraft(field="form2.010.net_revenue", label="Net revenue", value=9842316, line_code="010",
                       period_label="FY2025", printed="9 842 316", page_n=1, bbox=[500, 100, 550, 110]),
             FactDraft(field="form2.020.cost_of_sales", label="Cost of sales", value=8614900, line_code="020",
                       period_label="FY2025", printed="8 614 900", page_n=1, bbox=[500, 120, 550, 130])]
    good = {"page_n": 1, "text": "Yalpi foyda (zarar) 1 227 416", "label": "Yalpi foyda (zarar)",
            "value_printed": "1 227 416", "bbox": [500, 140, 550, 150]}
    wrong = {**good, "value_printed": "1 000 000"}
    llm(FakeProvider(['{"code": "030", "reason": "gross profit"}']))
    new, rest = resolve_unmapped(db, "form2", facts, [good])
    assert len(new) == 1 and new[0].line_code == "030" and new[0].method == "llm_fallback"
    assert new[0].confidence == 0.75 and new[0].value == 1227416 and rest == []
    llm(FakeProvider(['{"code": "030", "reason": "gross profit"}']))
    new, rest = resolve_unmapped(db, "form2", facts, [wrong])      # 010 − 020 ≠ 1 000 000 → refused
    assert new == [] and rest[0]["llm"]["accepted"] is False


# ------------------------------------------------------------------------------------------------ providers

def test_anthropic_wire_format():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.update(body)
        return httpx.Response(200, json={"content": [{"type": "tool_use", "id": "t1", "name": "search_facts",
                                                      "input": {"query": "cash"}}],
                                         "usage": {"input_tokens": 11, "output_tokens": 5}})
    p = AnthropicProvider("claude-test", "key", transport=httpx.MockTransport(handler))
    res = p.complete([{"role": "system", "content": "sys"}, {"role": "user", "content": "q"},
                      {"role": "assistant", "content": "", "tool_calls": [
                          {"id": "t0", "type": "function", "function": {"name": "x", "arguments": "{}"}}]},
                      {"role": "tool", "tool_call_id": "t0", "content": "{}"}],
                     tools=[{"name": "search_facts", "description": "d", "parameters": {"type": "object"}}])
    assert seen["system"] == "sys" and seen["messages"][-1]["content"][0]["type"] == "tool_result"
    assert res.tool_calls[0].name == "search_facts" and res.usage == {"prompt_tokens": 11, "completion_tokens": 5}


def test_llm_calls_are_logged(client, session_factory, llm):
    llm(FakeProvider([_good]))
    officer = _make_application(client)
    fakes.run_all_jobs(session_factory)
    from app.modules.llm.models import LlmCall
    s = session_factory()
    calls = s.query(LlmCall).all()
    s.close()
    assert len(calls) == 1 and calls[0].purpose == "narrative" and calls[0].prompt_tokens == 100 and calls[0].ok
    assert officer
