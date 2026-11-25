"""LLM APIs that speak the OpenAI Chat Completions protocol: Google Gemini, OpenAI, DeepSeek — and any other
compatible API (OpenRouter, Groq, Mistral, Together…) via LLM_BASE_URL.

The adapter exposes the same `messages.parse(...)` surface the agent loop uses with the Claude SDK (system blocks,
tool use, structured output), so every agent, tool, cache and trace works unchanged — only the transport differs.
Claude itself goes through the official Anthropic SDK (app.llm).

    provider   key                 model (default)          base URL
    gemini     GEMINI_API_KEY      GEMINI_MODEL   gemini-2.5-flash   Google AI Studio (free tier)
    openai     OPENAI_API_KEY      OPENAI_MODEL   gpt-4o-mini        api.openai.com
    deepseek   DEEPSEEK_API_KEY    DEEPSEEK_MODEL deepseek-chat      api.deepseek.com
    custom     LLM_API_KEY         LLM_MODEL      (required)         LLM_BASE_URL (required)
"""
from __future__ import annotations

import json
import os
import re
from types import SimpleNamespace as NS

import httpx
from pydantic import ValidationError

TIMEOUT = float(os.getenv("LLM_TIMEOUT", "120"))


def _flat(schema: dict) -> dict:
    """Inline $ref/$defs and drop keywords some OpenAI-compatible servers (Gemini) reject."""
    defs = schema.get("$defs", {})

    def walk(x):
        if isinstance(x, dict):
            if "$ref" in x:
                return walk(defs[x["$ref"].split("/")[-1]])
            return {k: walk(v) for k, v in x.items() if k not in ("$defs", "additionalProperties", "title", "default")}
        if isinstance(x, list):
            return [walk(v) for v in x]
        return x
    return walk(schema)


def _text(blocks) -> str:
    if isinstance(blocks, str):
        return blocks
    return "\n\n".join(b["text"] if isinstance(b, dict) else getattr(b, "text", "") for b in blocks)


def _messages(system, messages) -> list[dict]:
    """Anthropic-style conversation → OpenAI chat messages."""
    out = [{"role": "system", "content": _text(system)}] if system else []
    for m in messages:
        c = m["content"]
        if m["role"] == "assistant" and not isinstance(c, str):
            text = "".join(getattr(b, "text", "") for b in c if getattr(b, "type", "") == "text")
            calls = [{"id": b.id, "type": "function", "function": {"name": b.name, "arguments": json.dumps(b.input, ensure_ascii=False)}}
                     for b in c if getattr(b, "type", "") == "tool_use"]
            out.append({"role": "assistant", "content": text or None, **({"tool_calls": calls} if calls else {})})
        elif isinstance(c, list) and c and isinstance(c[0], dict) and c[0].get("type") == "tool_result":
            out += [{"role": "tool", "tool_call_id": r["tool_use_id"], "content": r["content"]} for r in c]
        else:
            out.append({"role": m["role"], "content": _text(c)})
    return out


def _json(text: str) -> str:
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=0)
    return text[start:]


class _Messages:
    def __init__(self, url: str, key: str, label: str = "LLM API"):
        self.label = label
        self.url = url.rstrip("/") + "/chat/completions"
        self.headers = {"Authorization": f"Bearer {key}"} if key else {}

    async def _post(self, body: dict) -> dict:
        from .llm import LLMError
        for attempt in range(4):
            try:
                async with httpx.AsyncClient(timeout=TIMEOUT) as c:
                    r = await c.post(self.url, json=body, headers=self.headers)
                if r.status_code == 429 and attempt < 3:          # free tiers: back off and retry
                    import asyncio
                    await asyncio.sleep(6 * (attempt + 1))
                    continue
                if r.status_code == 400 and body.get("response_format", {}).get("type") == "json_schema":
                    # the server does not take this schema: plain JSON mode with the schema in the prompt
                    sch = body["response_format"]["json_schema"]["schema"]
                    body = {**body, "response_format": {"type": "json_object"},
                            "messages": body["messages"] + [{"role": "user", "content": "JSON-схема ответа: " + json.dumps(sch, ensure_ascii=False)}]}
                    continue
                r.raise_for_status()
                return r.json()
            except httpx.HTTPStatusError as e:
                raise LLMError(f"{self.label}: HTTP {e.response.status_code} {e.response.text[:160]}") from e
            except httpx.HTTPError as e:
                raise LLMError(f"{self.label} недоступна ({type(e).__name__})") from e
        raise LLMError(f"{self.label}: превышен лимит запросов, попробуйте позже")

    async def parse(self, *, model, max_tokens, system, messages, output_format, tools=None, output_config=None, **_):
        msgs = _messages(system, messages)
        schema = _flat(output_format.model_json_schema())
        usage = NS(input_tokens=0, output_tokens=0, cache_read_input_tokens=0, cache_creation_input_tokens=0)

        def count(d):
            u = d.get("usage") or {}
            usage.input_tokens += u.get("prompt_tokens", 0)
            usage.output_tokens += u.get("completion_tokens", 0)

        if tools:   # a tool round: the model may call tools or already answer
            d = await self._post({"model": model, "max_tokens": max_tokens, "messages": msgs, "temperature": 0,
                                  "tools": [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                                              "parameters": t["input_schema"]}} for t in tools]})
            count(d)
            msg = d["choices"][0]["message"]
            calls = msg.get("tool_calls") or []
            if calls:
                blocks = [NS(type="tool_use", id=c["id"], name=c["function"]["name"],
                             input=json.loads(c["function"].get("arguments") or "{}")) for c in calls]
                if msg.get("content"):
                    blocks.insert(0, NS(type="text", text=msg["content"]))
                return NS(stop_reason="tool_use", content=blocks, usage=usage, parsed_output=None)
            try:
                return NS(stop_reason="end_turn", content=[], usage=usage,
                          parsed_output=output_format.model_validate_json(_json(msg.get("content"))))
            except ValidationError:
                msgs.append({"role": "assistant", "content": msg.get("content") or ""})
        # the answer, constrained to the JSON schema (servers without json_schema fall back to json_object in _post)
        msgs.append({"role": "user", "content": "Верни итоговый ответ строго в JSON по схеме, без пояснений."})
        d = await self._post({"model": model, "max_tokens": max_tokens, "messages": msgs, "temperature": 0,
                              "response_format": {"type": "json_schema",
                                                  "json_schema": {"name": output_format.__name__, "schema": schema}}})
        count(d)
        text = d["choices"][0]["message"].get("content") or ""
        return NS(stop_reason="end_turn", content=[], usage=usage,
                  parsed_output=output_format.model_validate_json(_json(text)))   # ValidationError → loop retries


# provider → (key env, model env, default model, base URL env, default base URL, label)
PROVIDERS = {
    "gemini":   ("GEMINI_API_KEY", "GEMINI_MODEL", "gemini-2.5-flash", "GEMINI_BASE_URL",
                 "https://generativelanguage.googleapis.com/v1beta/openai", "Gemini API"),
    "openai":   ("OPENAI_API_KEY", "OPENAI_MODEL", "gpt-4o-mini", "OPENAI_BASE_URL", "https://api.openai.com/v1", "OpenAI API"),
    "deepseek": ("DEEPSEEK_API_KEY", "DEEPSEEK_MODEL", "deepseek-chat", "DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1", "DeepSeek API"),
    "custom":   ("LLM_API_KEY", "LLM_MODEL", "", "LLM_BASE_URL", "", "LLM API"),
}


def configured(provider: str) -> bool:
    key, model, default, url_env, url, _ = PROVIDERS[provider]
    if provider == "custom":
        return bool(os.getenv(url_env) and os.getenv(model))
    return bool(os.getenv(key))


def models(provider: str) -> dict[str, str]:
    """fast = each requirement / questions, strong = the set and the Critic (`<MODEL>_STRONG` to use a bigger one)."""
    _, env, default, *_ = PROVIDERS[provider]
    base = os.getenv(env, default)
    strong = os.getenv(f"{env}_STRONG", base)
    return {"fast": os.getenv(f"{env}_FAST", base), "strong": strong, "lead": os.getenv(f"{env}_LEAD", strong)}


def client(provider: str) -> NS:
    key, _, _, url_env, url, label = PROVIDERS[provider]
    return NS(messages=_Messages(os.getenv(url_env, url), os.getenv(key, ""), label=label))
