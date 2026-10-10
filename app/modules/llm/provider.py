"""One LLM interface for every provider: complete(messages, tools=None, json_schema=None) -> LLMResult.

Messages use the OpenAI chat shape ({role: system|user|assistant|tool, content, tool_calls?, tool_call_id?});
tools are {name, description, parameters (JSON schema)}. Providers: openai (SDK), anthropic (Messages API over
httpx), ollama (OpenAI-compatible base_url), none. The LLM is used only for the narrative, CFO Q&A, the
unmapped-line fallback and the unknown-document description; every call is logged in `llm_calls`.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Protocol

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.llm.models import LlmCall
from app.modules.settings.service import llm_enabled

logger = logging.getLogger(__name__)

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MAX_TOKENS = 1500


class LLMUnavailable(RuntimeError):
    """LLM switched off, provider `none`, or no key/base URL: callers fall back to the deterministic path."""


class LLMError(RuntimeError):
    """The provider call failed (network, HTTP error, malformed reply)."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class LLMResult:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict = field(default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0})
    message: dict = field(default_factory=dict)   # assistant turn in the shared message shape, for the next round
    call_id: int | None = None                    # llm_calls.id


class Provider(Protocol):
    name: str
    model: str

    def complete(self, messages: list[dict], tools: list[dict] | None = None,
                 json_schema: dict | None = None) -> LLMResult: ...


def _assistant_message(text: str, calls: list[ToolCall]) -> dict:
    msg: dict = {"role": "assistant", "content": text or ""}
    if calls:
        msg["tool_calls"] = [{"id": c.id, "type": "function",
                              "function": {"name": c.name, "arguments": json.dumps(c.arguments, ensure_ascii=False)}}
                             for c in calls]
    return msg


class OpenAICompatibleProvider:
    """OpenAI, and Ollama through its OpenAI-compatible endpoint (same prompts, same tool shape)."""

    def __init__(self, name: str, model: str, api_key: str, base_url: str | None = None) -> None:
        from openai import OpenAI
        self.name, self.model = name, model
        self._client = OpenAI(api_key=api_key, base_url=base_url or None, timeout=settings.LLM_TIMEOUT_S, max_retries=1)

    def complete(self, messages, tools=None, json_schema=None) -> LLMResult:
        kwargs: dict = {"model": self.model, "messages": messages, "temperature": 0.1, "max_tokens": MAX_TOKENS}
        if tools:
            kwargs["tools"] = [{"type": "function", "function": t} for t in tools]
            kwargs["tool_choice"] = "auto"
        if json_schema:
            kwargs["response_format"] = {"type": "json_schema",
                                         "json_schema": {"name": json_schema.get("title", "answer"),
                                                         "schema": json_schema, "strict": False}}
        try:
            resp = self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            raise LLMError(f"{self.name}: {exc.__class__.__name__}: {str(exc)[:300]}") from exc
        msg = resp.choices[0].message
        calls = []
        for tc in msg.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except ValueError:
                args = {"_raw": tc.function.arguments}
            calls.append(ToolCall(tc.id, tc.function.name, args))
        usage = {"prompt_tokens": getattr(resp.usage, "prompt_tokens", 0) or 0,
                 "completion_tokens": getattr(resp.usage, "completion_tokens", 0) or 0}
        return LLMResult(text=msg.content or "", tool_calls=calls, usage=usage,
                         message=_assistant_message(msg.content or "", calls))


class AnthropicProvider:
    """Claude Messages API over httpx (no SDK dependency). JSON output = a forced `answer` tool."""

    name = "anthropic"

    def __init__(self, model: str, api_key: str, transport: httpx.BaseTransport | None = None) -> None:
        self.model = model
        self._http = httpx.Client(timeout=settings.LLM_TIMEOUT_S, transport=transport,
                                  headers={"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION,
                                           "content-type": "application/json"})

    @staticmethod
    def _convert(messages: list[dict]) -> tuple[str, list[dict]]:
        system, out = [], []
        for m in messages:
            role = m["role"]
            if role == "system":
                system.append(m.get("content") or "")
            elif role == "user":
                out.append({"role": "user", "content": m.get("content") or ""})
            elif role == "assistant":
                blocks = [{"type": "text", "text": m["content"]}] if m.get("content") else []
                for tc in m.get("tool_calls") or []:
                    blocks.append({"type": "tool_use", "id": tc["id"], "name": tc["function"]["name"],
                                   "input": json.loads(tc["function"]["arguments"] or "{}")})
                out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": ""}]})
            elif role == "tool":
                block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m.get("content") or ""}
                if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list) and \
                        all(b.get("type") == "tool_result" for b in out[-1]["content"]):
                    out[-1]["content"].append(block)     # consecutive tool results share one user turn
                else:
                    out.append({"role": "user", "content": [block]})
        return "\n\n".join(system), out

    def complete(self, messages, tools=None, json_schema=None) -> LLMResult:
        system, msgs = self._convert(messages)
        body: dict = {"model": self.model, "max_tokens": MAX_TOKENS, "temperature": 0.1, "messages": msgs}
        if system:
            body["system"] = system
        api_tools = [{"name": t["name"], "description": t.get("description", ""), "input_schema": t["parameters"]}
                     for t in tools or []]
        if json_schema and not tools:
            api_tools = [{"name": "answer", "description": "Return the final answer.", "input_schema": json_schema}]
            body["tool_choice"] = {"type": "tool", "name": "answer"}
        if api_tools:
            body["tools"] = api_tools
        try:
            resp = self._http.post(ANTHROPIC_URL, json=body)
        except httpx.HTTPError as exc:
            raise LLMError(f"anthropic: unreachable ({exc.__class__.__name__})") from exc
        if resp.status_code >= 400:
            raise LLMError(f"anthropic: HTTP {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        text_parts, calls = [], []
        for block in data.get("content") or []:
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                calls.append(ToolCall(block["id"], block["name"], block.get("input") or {}))
        if json_schema and not tools and calls and calls[0].name == "answer":
            text_parts, calls = [json.dumps(calls[0].arguments, ensure_ascii=False)], []
        usage = data.get("usage") or {}
        text = "".join(text_parts)
        return LLMResult(text=text, tool_calls=calls,
                         usage={"prompt_tokens": usage.get("input_tokens", 0),
                                "completion_tokens": usage.get("output_tokens", 0)},
                         message=_assistant_message(text, calls))


_override: Provider | None = None


def set_provider_override(provider: Provider | None) -> None:
    """Tests (and scripts) inject a provider; production resolves it from settings."""
    global _override
    _override = provider


def configured() -> bool:
    if _override is not None:
        return True
    p = settings.LLM_PROVIDER
    if p == "openai":
        return bool(settings.OPENAI_API_KEY)
    if p == "anthropic":
        return bool(settings.ANTHROPIC_API_KEY)
    if p == "ollama":
        return bool(settings.LLM_BASE_URL)
    return False


def available(db: Session) -> bool:
    """The runtime switch is on AND a provider is configured (or injected)."""
    return configured() and llm_enabled(db)


def get_provider() -> Provider:
    if _override is not None:
        return _override
    p = settings.LLM_PROVIDER
    if p == "openai" and settings.OPENAI_API_KEY:
        return OpenAICompatibleProvider("openai", settings.LLM_MODEL, settings.OPENAI_API_KEY)
    if p == "ollama" and settings.LLM_BASE_URL:
        return OpenAICompatibleProvider("ollama", settings.LLM_MODEL, "ollama", settings.LLM_BASE_URL)
    if p == "anthropic" and settings.ANTHROPIC_API_KEY:
        return AnthropicProvider(settings.LLM_MODEL, settings.ANTHROPIC_API_KEY)
    raise LLMUnavailable(f"LLM provider '{p}' is not configured")


def complete(db: Session, purpose: str, messages: list[dict], tools: list[dict] | None = None,
             json_schema: dict | None = None, *, application_id: int | None = None,
             document_id: int | None = None) -> LLMResult:
    """Calls the configured provider and logs the call (tokens, latency, ok) in the caller's session."""
    if not available(db):
        raise LLMUnavailable("LLM is off or not configured")
    provider = get_provider()
    t0 = time.perf_counter()
    row = LlmCall(provider=provider.name, model=provider.model, purpose=purpose[:24], application_id=application_id,
                  document_id=document_id)
    try:
        result = provider.complete(messages, tools=tools, json_schema=json_schema)
    except Exception as exc:
        row.ok, row.error = False, str(exc)[:1000]
        row.latency_ms = int((time.perf_counter() - t0) * 1000)
        db.add(row)
        db.flush()
        if isinstance(exc, (LLMError, LLMUnavailable)):
            raise
        raise LLMError(f"{provider.name}: {exc.__class__.__name__}: {exc}") from exc
    row.ok = True
    row.latency_ms = int((time.perf_counter() - t0) * 1000)
    row.prompt_tokens = int(result.usage.get("prompt_tokens") or 0)
    row.completion_tokens = int(result.usage.get("completion_tokens") or 0)
    db.add(row)
    db.flush()
    result.call_id = row.id
    return result


def parse_json(text: str) -> dict | None:
    """First JSON object in a reply (models sometimes wrap it in a code fence)."""
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = t[t.find("{"):] if "{" in t else t
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(t[start:end + 1])
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None
