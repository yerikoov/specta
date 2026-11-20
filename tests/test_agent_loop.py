"""The Claude tool-use loop, exercised with a fake client (no network, no API key)."""
import asyncio
from pathlib import Path
from types import SimpleNamespace as NS

from app.agents.base import LLMFindings
from app.agents.registry import AGENTS
from app.agents.tools import run_tool, tools_for
from app.llm import llm, meter, trace
from app.parsing import parse_bytes

SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "sample_tz_p2p.md"


class FakeMessages:
    def __init__(self):
        self.calls = []

    async def parse(self, **kw):
        self.calls.append(kw)
        usage = NS(input_tokens=100, output_tokens=40, cache_read_input_tokens=900, cache_creation_input_tokens=0)
        if len(self.calls) == 1:   # first round: the agent looks something up
            block = NS(type="tool_use", id="tu_1", name="search_kb", input={"query": "идентификация клиента"})
            return NS(stop_reason="tool_use", content=[block], usage=usage, parsed_output=None)
        final = LLMFindings(findings=[{"text": "Нет процедуры KYC", "severity": "critical", "section_ref": "3.1"}])
        return NS(stop_reason="end_turn", content=[], usage=usage, parsed_output=final)


def test_agent_calls_tool_then_answers(monkeypatch):
    doc = parse_bytes("tz.md", SAMPLE.read_bytes())
    fake = NS(messages=FakeMessages())
    monkeypatch.setattr(llm, "client", fake)
    m = {"calls": 0, "input": 0, "output": 0, "cached": 0, "usd": 0.0}
    t: list = []

    async def go():
        meter.set(m); trace.set(t)
        return await llm.run_agent("найди пробелы", "проверь", LLMFindings, tier="fast", doc="ТЗ...",
                                   tools=tools_for(AGENTS["regulatory"]), run_tool=lambda n, a: run_tool(n, a, doc),
                                   agent="regulatory", purpose="поиск проблем")

    res = asyncio.run(go())
    assert res.findings[0].text == "Нет процедуры KYC"
    calls = fake.messages.calls
    assert len(calls) == 2 and "tools" in calls[0]
    # the tool result went back in one user message, matched to the tool_use id
    assert calls[1]["messages"][-1]["content"][0]["tool_use_id"] == "tu_1"
    assert [r["kind"] for r in t] == ["llm", "tool", "llm"] and t[1]["tool"] == "search_kb"
    assert m["calls"] == 2 and m["cached"] == 1800 and m["usd"] > 0
    # the TZ prefix is cached
    assert calls[0]["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_web_tools_are_free_guarded_and_budgeted(monkeypatch):
    import json as _json
    from app import research
    from app.agents.registry import AGENTS
    from app.agents.tools import tools_for
    from app.llm import meter

    names = {t["name"] for t in tools_for(AGENTS["regulatory"])}
    assert {"web_search", "read_page"} <= names
    monkeypatch.setenv("WEB_RESEARCH", "0")
    assert "web_search" not in {t["name"] for t in tools_for(AGENTS["regulatory"])}
    # no internal addresses
    out = asyncio.run(research.read("http://127.0.0.1:8000/api/config", "x"))
    assert "error" in _json.loads(out)
    # per-check budget
    async def capped():
        meter.set({"web": research.max_calls()})
        return await research.search("тест лимита", True)
    assert "лимит" in _json.loads(asyncio.run(capped()))["error"]
