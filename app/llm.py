"""Claude API adapter (official Anthropic SDK).

Three tiers, three Claude models, picked per role to keep spend low:
  fast   — specialists' extra pass, rebuttals in the debate  → Claude Haiku 5.5  (effort low)
  strong — Critic / moderator of the debate                  → Claude Sonnet 5.5 (effort medium)
  lead   — the client-facing executive summary (one call)    → Claude Opus 5.5   (effort low)

Cost controls:
  * rule-based detectors run first, for free; Claude only refines and argues about what they found;
  * the document goes into the system prompt as one cached block (prompt caching), so every agent that
    uses the same model re-reads it at ~10% of the input price;
  * structured outputs (validated Pydantic) — no retries on broken JSON;
  * a hard per-check call budget (LLM_MAX_CALLS) and a spend meter per check.
Providers (LLM_PROVIDER): anthropic (Claude, default when ANTHROPIC_API_KEY is set) · local (any
OpenAI-compatible on-prem server, see app.local_llm — the TZ never leaves the bank) · rules (no model at all).
Without a key and without a local server the app runs on the rule engine only (no network).
Personal data (ИИН, phones, cards, IBAN, e-mail) is masked before anything is sent to a cloud model (app.pii).
"""
from __future__ import annotations

import contextvars
import inspect
import json
import logging
import os
import random
import time
from typing import Callable, Literal, Optional, Type, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

log = logging.getLogger("llm")
T = TypeVar("T", bound=BaseModel)
Tier = Literal["fast", "strong", "lead"]

MODELS = {
    "fast": os.getenv("LLM_MODEL_FAST", "claude-haiku-5-5"),
    "strong": os.getenv("LLM_MODEL_STRONG", "claude-sonnet-5-5"),
    "lead": os.getenv("LLM_MODEL_LEAD", "claude-opus-5-5"),
}
EFFORT = {"fast": "low", "strong": "medium", "lead": "low"}
# $ per 1M tokens: input, output (cache read = 10% of input, cache write = 125%)
PRICES = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.0, 10.0), "claude-opus-5-5": (4.0, 20.0)}
SHARED = ("Ты — участник команды ИИ-агентов, которая проверяет техническое задание (ТЗ) финтех-проекта банка "
          "перед передачей в разработку. Отвечай по-русски, коротко и по существу. Цитаты бери дословно из ТЗ.\n\n")

# the spend meter and the trace of the check being processed (set by the orchestrator)
meter: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar("llm_meter", default=None)
trace: contextvars.ContextVar[Optional[list]] = contextvars.ContextVar("llm_trace", default=None)


def record(kind: str, agent: str, **kw) -> None:
    """One line in the check's trace: an LLM call, a tool call or a rule-engine pass."""
    t = trace.get()
    if t is not None:
        t.append({"ts": time.time(), "kind": kind, "agent": agent, **kw})


class LLMError(RuntimeError):
    pass


CACHE_TTL = float(os.getenv("CACHE_TTL_DAYS", "30")) * 86400


class LLM:
    def __init__(self) -> None:
        key = os.getenv("ANTHROPIC_API_KEY", "")
        want = os.getenv("LLM_PROVIDER", "auto").lower()
        if want in ("rules", "mock", "off", "none"):
            want = "rules"
        elif want == "auto":
            want = "anthropic" if key else ("local" if os.getenv("LOCAL_LLM_URL") else "rules")
        self.models = dict(MODELS)
        self.client = None
        if want == "anthropic" and key:
            self.client = anthropic.AsyncAnthropic(api_key=key, timeout=float(os.getenv("LLM_TIMEOUT", "90")), max_retries=2)
        elif want == "local":
            from . import local_llm
            self.client = local_llm.client()
            self.models = local_llm.models()
        self.provider = want if self.client else "rules"
        self.max_calls = int(os.getenv("LLM_MAX_CALLS", "24"))
        self.delay_scale = float(os.getenv("DEMO_DELAY_SCALE", os.getenv("MOCK_DELAY_SCALE", "1.0")))

    @property
    def engine(self) -> str:
        """claude | local | rules — what the UI and the trace show."""
        if self.client is None:
            return "rules"
        return "local" if self.provider == "local" else "claude"

    @property
    def mock(self) -> bool:
        """True when no API key is configured: the rule engine does the work alone."""
        return self.client is None

    def mock_delay(self, lo: float = 0.3, hi: float = 0.9) -> float:
        """Pacing for the rule engine so the team's progress is readable (seconds)."""
        return random.uniform(lo, hi) * self.delay_scale

    async def complete_json(self, system: str, user: str, schema: Type[T], tier: Tier = "fast",
                            mock: Optional[Callable[[], dict]] = None, doc: Optional[str] = None,
                            max_tokens: int = 6000, agent: str = "", purpose: str = "") -> T:
        """One structured call. `doc` (the TZ text) is sent as a cached system block shared by all agents."""
        if self.mock:
            return schema.model_validate(mock() if mock else {})
        return await self.run_agent(system, user, schema, tier=tier, doc=doc, max_tokens=max_tokens,
                                    agent=agent, purpose=purpose)

    async def run_agent(self, system: str, user: str, schema: Type[T], tier: Tier = "fast", doc: Optional[str] = None,
                        tools: Optional[list] = None, run_tool: Optional[Callable[[str, dict], str]] = None,
                        max_steps: int = 4, max_tokens: int = 6000, agent: str = "", purpose: str = "",
                        learned: str = "") -> T:
        """An agent turn: Claude may call our tools (search the KB, read the facts table, look up a clause)
        for up to `max_steps` rounds, then returns a structured, schema-validated answer."""
        from . import cache
        model = self.models[tier]
        ckey = cache.key_of(model, EFFORT[tier], system, user, doc, schema.__name__, schema.model_json_schema(),
                            sorted(t["name"] for t in tools or []))
        hit = self._cached(ckey, schema, agent, purpose)
        if hit is not None:
            return hit
        # lessons from past checks go into the prompt but not into the cache key: the same TZ gives the same
        # (already debated) answer, while a new or edited TZ misses the cache and is checked with the experience
        system = system + learned
        m = meter.get()
        if m is not None and m["calls"] >= self.max_calls:
            raise LLMError("лимит вызовов модели для этой проверки исчерпан")
        spent = {"usd": 0.0, "input": 0, "output": 0}
        read_urls: list[str] = []
        # personal data is replaced by tokens before anything goes to a cloud model, and restored in the answer
        from .pii import Masker, enabled as pii_on
        pm = Masker() if self.provider == "anthropic" and pii_on() else None
        if pm:
            system, user, doc = pm.mask(system), pm.mask(user), pm.mask(doc)
        sys_blocks = []
        if doc:
            sys_blocks.append({"type": "text", "text": SHARED + "ТЗ:\n" + doc, "cache_control": {"type": "ephemeral"}})
        sys_blocks.append({"type": "text", "text": system + (
            "\n\nУ тебя есть инструменты — вызывай их, когда нужны данные вне текста ТЗ; затем дай итоговый ответ." if tools else "")})
        from .agents.tools import definitions
        tool_defs = definitions(tools) if tools else None
        messages: list = [{"role": "user", "content": user}]
        for step in range(max_steps + 1):
            if m is not None and m["calls"] >= self.max_calls:
                raise LLMError("лимит вызовов модели для этой проверки исчерпан")
            kw = dict(model=model, max_tokens=max_tokens, system=sys_blocks, messages=messages,
                      output_format=schema, output_config={"effort": EFFORT[tier]})
            if tool_defs and step < max_steps:      # last round: answer only
                kw["tools"] = tool_defs
            t0 = time.perf_counter()
            try:
                resp = await self.client.messages.parse(**kw)
            except ValidationError as e:   # e.g. the answer was cut by max_tokens: retry once with more room
                if kw["max_tokens"] < 16000 and step < max_steps:
                    max_tokens = min(16000, kw["max_tokens"] * 2)
                    log.warning("%s: truncated structured answer, retrying with max_tokens=%s", agent, max_tokens)
                    continue
                raise LLMError("ответ модели не прошёл проверку схемы") from e
            except anthropic.RateLimitError as e:
                raise LLMError("Claude API: превышен лимит запросов") from e
            except anthropic.APIStatusError as e:
                raise LLMError(f"Claude API {e.status_code}: {e.message}") from e
            except anthropic.APIConnectionError as e:
                raise LLMError("Claude API недоступен") from e
            self._account(model, resp.usage, agent=agent, purpose=purpose or "ответ", ms=(time.perf_counter() - t0) * 1000,
                          spent=spent)
            if resp.stop_reason == "refusal":
                raise LLMError("модель отказалась отвечать")
            calls = [b for b in resp.content if b.type == "tool_use"]
            if resp.stop_reason == "tool_use" and calls and run_tool:
                messages.append({"role": "assistant", "content": resp.content})
                results = []
                for c in calls:
                    args = pm.unmask_obj(c.input or {}) if pm else (c.input or {})
                    if c.name == "read_page" and args.get("url"):
                        read_urls.append(args["url"])
                    t1 = time.perf_counter()
                    out = run_tool(c.name, args)
                    if inspect.isawaitable(out):
                        out = await out
                    record("tool", agent, tool=c.name, args=args, ms=round((time.perf_counter() - t1) * 1000, 1),
                           result=out[:240])
                    results.append({"type": "tool_result", "tool_use_id": c.id, "content": pm.mask(out) if pm else out})
                messages.append({"role": "user", "content": results})   # all results in one message
                continue
            if resp.parsed_output is None:
                raise LLMError(f"модель не вернула результат ({resp.stop_reason})")
            out = resp.parsed_output
            if pm and pm.count:
                out = schema.model_validate(pm.unmask_obj(out.model_dump()))
            if pm and m is not None:   # the same TZ is masked in every call: keep the number of distinct values
                m["pii_masked"] = max(m.get("pii_masked", 0), pm.count)
            from .research import page_dep
            cache.put("llm", ckey, out.model_dump_json(), ttl=CACHE_TTL,
                      meta={**spent, "model": model, "agent": agent, "purpose": purpose},
                      deps=[page_dep(u) for u in read_urls])
            return out
        raise LLMError("агент не закончил за отведённое число шагов")

    def _cached(self, ckey: str, schema: Type[T], agent: str, purpose: str) -> Optional[T]:
        """A saved answer for exactly this prompt + TZ + knowledge version — unless a web page it relied on is due
        for revalidation (then the agent runs again and the page is re-checked)."""
        from . import cache
        hit = cache.get("llm", ckey)
        if not hit:
            return None
        value, meta = hit
        if any(cache.get("web_page", d) is None for d in cache.deps_of("llm", ckey)):
            return None
        try:
            out = schema.model_validate_json(value)
        except ValidationError:
            return None
        m = meter.get()
        if m is not None:
            m["saved_usd"] = m.get("saved_usd", 0) + meta.get("usd", 0)
            m["cache_hits"] = m.get("cache_hits", 0) + 1
        record("cache", agent, model=meta.get("model", ""), purpose=purpose or meta.get("purpose", ""),
               saved_usd=round(meta.get("usd", 0), 6), saved_tokens=meta.get("input", 0) + meta.get("output", 0), ms=0)
        return out

    def _account(self, model: str, usage, agent: str = "", purpose: str = "", ms: float = 0, spent: dict | None = None) -> None:
        if usage is None:
            return
        pin, pout = PRICES.get(model, (0.0, 0.0) if self.provider == "local" else (4.0, 20.0))   # on-prem: free
        inp = usage.input_tokens or 0
        read = getattr(usage, "cache_read_input_tokens", 0) or 0
        write = getattr(usage, "cache_creation_input_tokens", 0) or 0
        out = usage.output_tokens or 0
        usd = (inp * pin + read * pin * 0.1 + write * pin * 1.25 + out * pout) / 1e6
        if spent is not None:
            spent["usd"] += usd; spent["input"] += inp + read + write; spent["output"] += out
        m = meter.get()
        if m is None:
            return
        m["calls"] += 1
        m["input"] += inp + read + write
        m["cached"] += read
        m["output"] += out
        m["usd"] += usd
        record("llm", agent, model=model, purpose=purpose, input=inp + read + write, cached=read, output=out,
               usd=round(usd, 6), ms=round(ms))
        log.info("%s %s: in=%s cached=%s out=%s → $%.5f total", agent, model, inp, read, out, m["usd"])


llm = LLM()
