"""Local / on-prem model behind any OpenAI-compatible server (vLLM, Ollama, LM Studio, KazLLM deployments).

The ТЗ never leaves the bank's network. The adapter exposes the same `messages.parse(...)` surface the agent
loop already uses with Claude (system blocks, tool use, structured output), so every agent, tool, cache and
trace works unchanged — only the transport differs.

    LLM_PROVIDER=local
    LOCAL_LLM_URL=http://localhost:11434/v1      # Ollama; vLLM: http://host:8000/v1
    LOCAL_LLM_MODEL=qwen2.5:14b-instruct          # or LOCAL_MODEL_FAST / _STRONG / _LEAD per tier
    LOCAL_LLM_KEY=                                # if the server needs a bearer token
"""
from __future__ import annotations

import json
import os
import re
from types import SimpleNamespace as NS

import httpx
from pydantic import ValidationError

TIMEOUT = float(os.getenv("LOCAL_LLM_TIMEOUT", "180"))


def models() -> dict[str, str]:
    base = os.getenv("LOCAL_LLM_MODEL", "qwen2.5:14b-instruct")
    return {"fast": os.getenv("LOCAL_MODEL_FAST", base), "strong": os.getenv("LOCAL_MODEL_STRONG", base),
            "lead": os.getenv("LOCAL_MODEL_LEAD", base)}


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
    def __init__(self, url: str, key: str):
        self.url = url.rstrip("/") + "/chat/completions"
        self.headers = {"Authorization": f"Bearer {key}"} if key else {}

    async def _post(self, body: dict) -> dict:
        from .llm import LLMError
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as c:
                r = await c.post(self.url, json=body, headers=self.headers)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as e:
            raise LLMError(f"локальная модель: HTTP {e.response.status_code}") from e
        except httpx.HTTPError as e:
            raise LLMError(f"локальная модель недоступна ({type(e).__name__})") from e

    async def parse(self, *, model, max_tokens, system, messages, output_format, tools=None, output_config=None, **_):
        msgs = _messages(system, messages)
        schema = output_format.model_json_schema()
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
        # the answer, constrained to the JSON schema (vLLM / Ollama / LM Studio support json_schema)
        msgs.append({"role": "user", "content": "Верни итоговый ответ строго в JSON по схеме, без пояснений."})
        d = await self._post({"model": model, "max_tokens": max_tokens, "messages": msgs, "temperature": 0,
                              "response_format": {"type": "json_schema",
                                                  "json_schema": {"name": output_format.__name__, "schema": schema}}})
        count(d)
        text = d["choices"][0]["message"].get("content") or ""
        return NS(stop_reason="end_turn", content=[], usage=usage,
                  parsed_output=output_format.model_validate_json(_json(text)))   # ValidationError → loop retries


def client() -> NS:
    return NS(messages=_Messages(os.getenv("LOCAL_LLM_URL", "http://localhost:11434/v1"), os.getenv("LOCAL_LLM_KEY", "")))
