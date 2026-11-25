"""LLM API providers (Claude SDK + OpenAI-compatible presets) and personal-data masking. No network: fake servers."""
import asyncio
import json
from types import SimpleNamespace as NS

import httpx
import pytest

from app import openai_compat, pii
from app.agents.base import LLMFindings
from app.llm import llm, meter, trace


def test_masker_round_trip():
    m = pii.Masker()
    text = "ИИН 900101300123, тел. +7 701 123 45 67, карта 4400 4301 2345 6789, KZ86125KZT5004100100, a.b@bank.kz"
    masked = m.mask(text)
    for v in ("900101300123", "701 123 45 67", "4400 4301 2345 6789", "KZ86125KZT5004100100", "a.b@bank.kz"):
        assert v not in masked
    assert "[ИИН-1]" in masked and m.unmask(masked) == text
    assert m.mask("лимит 1 000 000 ₸ и 300 000 ₸ на 12 месяцев") == "лимит 1 000 000 ₸ и 300 000 ₸ на 12 месяцев"


class FakeClaude:
    def __init__(self):
        self.seen = []

    async def parse(self, **kw):
        self.seen.append(json.dumps(kw["system"], ensure_ascii=False) + kw["messages"][0]["content"])
        usage = NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0)
        out = LLMFindings(findings=[{"text": "Не указано, как проверяется [ИИН-1]", "quote": "ИИН клиента [ИИН-1]",
                                     "severity": "important"}])
        return NS(stop_reason="end_turn", content=[], usage=usage, parsed_output=out)


def test_cloud_never_sees_personal_data_and_quotes_are_restored(monkeypatch):
    fake = FakeClaude()
    monkeypatch.setattr(llm, "client", NS(messages=fake))
    monkeypatch.setattr(llm, "provider", "anthropic")
    m = {"calls": 0, "input": 0, "output": 0, "cached": 0, "usd": 0.0}

    async def go():
        meter.set(m); trace.set([])
        return await llm.run_agent("пиши кратко", "проверь", LLMFindings, doc="3.2 ИИН клиента 900101300123.",
                                   agent="regulatory", purpose="pii-тест")
    res = asyncio.run(go())
    assert "900101300123" not in fake.seen[0] and "[ИИН-1]" in fake.seen[0]
    assert res.findings[0].quote == "ИИН клиента 900101300123"      # matches the document again
    assert m["pii_masked"] == 1


def test_openai_compatible_api_with_tools(monkeypatch):
    calls = []

    def handler(req: httpx.Request):
        body = json.loads(req.content)
        calls.append(body)
        assert req.headers["authorization"] == "Bearer sk-test"
        if len(calls) == 1:      # first round: the model asks for a tool
            msg = {"role": "assistant", "content": None,
                   "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "search_kb", "arguments": '{"query": "KYC"}'}}]}
        else:
            assert body["messages"][-1]["role"] == "tool" or "response_format" in body
            msg = {"role": "assistant", "content": '```json\n{"findings": [{"text": "Нет KYC", "severity": "critical"}]}\n```'}
        return httpx.Response(200, json={"choices": [{"message": msg}], "usage": {"prompt_tokens": 50, "completion_tokens": 9}})

    real = httpx.AsyncClient
    monkeypatch.setattr(openai_compat.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(llm, "client", openai_compat.client("openai"))
    monkeypatch.setattr(llm, "provider", "openai")
    monkeypatch.setattr(llm, "models", openai_compat.models("openai"))
    from app.agents.registry import AGENTS
    from app.agents.tools import run_tool, tools_for
    m, t = {"calls": 0, "input": 0, "output": 0, "cached": 0, "usd": 0.0}, []

    async def go():
        meter.set(m); trace.set(t)
        return await llm.run_agent("тест OpenAI API", "проверь", LLMFindings, doc="ТЗ", tools=tools_for(AGENTS["regulatory"]),
                                   run_tool=lambda n, a: run_tool(n, a, None), agent="regulatory", purpose="openai")
    res = asyncio.run(go())
    assert res.findings[0].text == "Нет KYC"
    assert calls[0]["tools"] and calls[1]["messages"][-1]["role"] == "tool"
    assert m["usd"] == 0 and [r["kind"] for r in t] == ["llm", "tool", "llm"]


@pytest.mark.parametrize("env,provider,model", [
    ({"ANTHROPIC_API_KEY": "a"}, "anthropic", "claude-haiku-5-5"),
    ({"GEMINI_API_KEY": "g"}, "gemini", "gemini-2.5-flash"),
    ({"OPENAI_API_KEY": "o", "OPENAI_MODEL": "gpt-4o-mini"}, "openai", "gpt-4o-mini"),
    ({"DEEPSEEK_API_KEY": "d"}, "deepseek", "deepseek-chat"),
    ({"LLM_BASE_URL": "https://openrouter.ai/api/v1", "LLM_API_KEY": "k", "LLM_MODEL": "meta/llama"}, "custom", "meta/llama"),
    ({}, "rules", None),
])
def test_provider_is_picked_from_the_key_in_env(monkeypatch, env, provider, model):
    from app.llm import LLM
    for k in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "auto")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    m = LLM()
    assert m.provider == provider
    if model:
        assert m.models["fast"] == model and not m.mock
    else:
        assert m.mock
