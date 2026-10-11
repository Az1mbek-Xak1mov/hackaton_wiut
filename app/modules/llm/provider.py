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


class LLMNoCredits(LLMUnavailable):
    """The provider refused the call because the API key has no credits / quota left (OpenAI 429
    `insufficient_quota`, Anthropic "credit balance is too low"). Callers fall back like for LLMUnavailable."""


class LLMBadKey(LLMUnavailable):
    """The provider rejected the API key (HTTP 401 `invalid_api_key` / authentication_error)."""


# ---- plain status of the AI service ---------------------------------------------------------------------------
# A no-credits / bad-key answer is remembered for FAILURE_TTL_S so the pipeline does not call a provider that will
# refuse every request; any other failure is remembered (for the status line) but does not block further calls.
FAILURE_TTL_S = 300
_TAIL = " All figures, checks and ratios above are still computed from the documents."
STATUS_TEXT = {
    "ok": "",
    "off": "AI summary is switched off." + _TAIL,
    "no_key": "AI summary is off: no AI key is configured." + _TAIL,
    "bad_key": "AI summary is off: the AI service rejected the API key." + _TAIL,
    "no_credits": "AI summary is off: the AI service has no credits left (API key quota used up)." + _TAIL,
    "error": "AI summary is unavailable: the AI service did not answer." + _TAIL,
}
_failure: dict | None = None    # {"code": "no_credits"|"no_key"|"error", "text": str, "at": monotonic seconds}


def _remember(code: str, detail: str = "", text_key: str | None = None) -> None:
    global _failure
    _failure = {"code": code, "text": STATUS_TEXT[text_key or code], "detail": detail[:300], "at": time.monotonic()}


def reset_status() -> None:
    """Forget a remembered provider failure (tests; a key/credit top-up is picked up after FAILURE_TTL_S anyway)."""
    global _failure
    _failure = None


def _recent_failure() -> dict | None:
    if _failure is None or time.monotonic() - _failure["at"] > FAILURE_TTL_S:
        return None
    return _failure


def _blocked() -> dict | None:
    f = _recent_failure()
    return f if f and f["code"] in ("no_credits", "no_key") else None


def classify_failure(status_code: int | None, code: str | None, body: str) -> type[LLMUnavailable] | None:
    """Map a provider refusal to LLMNoCredits / LLMBadKey; None = an ordinary error."""
    low = (body or "").lower()
    code = (code or "").lower()
    if code == "insufficient_quota" or "insufficient_quota" in low or "credit balance is too low" in low \
            or "exceeded your current quota" in low or "billing" in low and status_code in (400, 402, 403, 429):
        return LLMNoCredits
    if status_code == 402:
        return LLMNoCredits
    if status_code == 401 or code in ("invalid_api_key", "authentication_error") or "invalid_api_key" in low \
            or "authentication_error" in low or "invalid x-api-key" in low:
        return LLMBadKey
    return None


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
            kind = classify_failure(getattr(exc, "status_code", None), getattr(exc, "code", None), str(exc))
            if kind is not None:
                raise kind(f"{self.name}: {str(exc)[:300]}") from exc
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
            kind = classify_failure(resp.status_code, None, resp.text)
            if kind is not None:
                raise kind(f"anthropic: HTTP {resp.status_code}: {resp.text[:300]}")
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
    reset_status()


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
    """The runtime switch is on AND a provider is configured (or injected) AND the provider has not just refused
    the key (no credits / invalid key) within FAILURE_TTL_S."""
    return configured() and llm_enabled(db) and _blocked() is None


def status(db: Session | None = None) -> dict:
    """{code: ok|off|no_key|no_credits|error, text}: the plain reason an AI summary is (not) shown."""
    def out(code: str, text_key: str | None = None) -> dict:
        return {"code": code, "text": STATUS_TEXT[text_key or code]}
    if _override is None and settings.LLM_PROVIDER == "none":
        return out("off")
    if db is not None:
        try:
            if not llm_enabled(db):
                return out("off")
        except Exception:   # DB not migrated yet
            pass
    if not configured():
        return out("no_key")
    f = _recent_failure()
    if f is not None:
        return {"code": f["code"], "text": f["text"]}
    return out("ok")


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
    blocked = _blocked()
    if blocked is not None and configured() and llm_enabled(db):
        raise (LLMNoCredits if blocked["code"] == "no_credits" else LLMBadKey)(blocked["detail"] or blocked["text"])
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
        if isinstance(exc, LLMNoCredits):
            _remember("no_credits", str(exc))
            logger.warning("LLM provider has no credits left; AI text is off for %ss: %s", FAILURE_TTL_S, exc)
        elif isinstance(exc, LLMBadKey):
            _remember("no_key", str(exc), text_key="bad_key")
            logger.warning("LLM provider rejected the API key; AI text is off for %ss: %s", FAILURE_TTL_S, exc)
        elif not isinstance(exc, LLMUnavailable):
            _remember("error", str(exc))
        if isinstance(exc, (LLMError, LLMUnavailable)):
            raise
        raise LLMError(f"{provider.name}: {exc.__class__.__name__}: {exc}") from exc
    row.ok = True
    reset_status()
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
