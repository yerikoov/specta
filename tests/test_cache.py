"""Persistent cache: saves tokens, but answers never outlive the knowledge or the web pages they used."""
import asyncio
import json
import time
from types import SimpleNamespace as NS

from app import cache, learning, research
from app.agents.base import LLMFindings
from app.llm import llm, meter, trace
from app.models import Finding


class OneShot:
    """A fake Claude: optionally reads a web page first, then answers."""
    def __init__(self, url=None):
        self.calls, self.url = 0, url

    async def parse(self, **kw):
        self.calls += 1
        usage = NS(input_tokens=1000, output_tokens=200, cache_read_input_tokens=0, cache_creation_input_tokens=0)
        if self.url and self.calls % 2 == 1:
            block = NS(type="tool_use", id=f"tu{self.calls}", name="read_page", input={"url": self.url, "focus": "x"})
            return NS(stop_reason="tool_use", content=[block], usage=usage, parsed_output=None)
        out = LLMFindings(findings=[{"text": f"ответ {self.calls}", "severity": "important"}])
        return NS(stop_reason="end_turn", content=[], usage=usage, parsed_output=out)


def ask(prompt, tools=None, run_tool=None):
    m, t = {"calls": 0, "input": 0, "output": 0, "cached": 0, "usd": 0.0}, []

    async def go():
        meter.set(m); trace.set(t)
        return await llm.run_agent(prompt, "проверь", LLMFindings, doc="ТЗ", tools=tools, run_tool=run_tool,
                                   agent="regulatory", purpose="поиск проблем")
    return asyncio.run(go()), m, t


def test_second_identical_call_comes_from_the_file(monkeypatch):
    fake = OneShot()
    monkeypatch.setattr(llm, "client", NS(messages=fake))
    r1, m1, _ = ask("кеш-тест 1")
    r2, m2, t2 = ask("кеш-тест 1")
    assert fake.calls == 1 and r1 == r2
    assert m2["calls"] == 0 and m2["saved_usd"] > 0 and t2[-1]["kind"] == "cache"
    ask("кеш-тест 1 — другой промпт")
    assert fake.calls == 2


def test_knowledge_change_invalidates(monkeypatch):
    fake = OneShot()
    monkeypatch.setattr(llm, "client", NS(messages=fake))
    ask("кеш-тест 2")
    monkeypatch.setattr(cache, "fingerprint", lambda: "new-kb-version")   # KB / rules / prompts edited
    ask("кеш-тест 2")
    assert fake.calls == 2


def test_changed_web_page_drops_answers_built_on_it(monkeypatch):
    url = "https://old.adilet.zan.kz/rus/docs/TEST"
    edition = {"text": "редакция 1", "n": 0}

    async def fetch(u, meta=None):
        edition["n"] += 1
        h = cache.key_of(edition["text"])[:16]
        if meta and meta.get("hash") == h:
            return 304, "", {}
        return 200, edition["text"], {"url": u, "title": "закон", "hash": h, "checked": time.time()}

    monkeypatch.setattr(research, "_fetch", fetch)
    monkeypatch.setattr(research, "_public", lambda u: True)
    from app.agents.tools import TOOLS, run_tool
    tools = [TOOLS["read_page"]]
    fake = OneShot(url)
    monkeypatch.setattr(llm, "client", NS(messages=fake))
    rt = lambda n, a: run_tool(n, a, None)

    ask("кеш-тест 3", tools, rt)
    assert fake.calls == 2
    ask("кеш-тест 3", tools, rt)                     # page still fresh → whole answer from cache
    assert fake.calls == 2

    def expire():
        with cache._lock:
            cache.conn().execute("update entries set expires=0 where ns='web_page'")

    expire()                                         # page due for revalidation, unchanged → re-run, page 304
    ask("кеш-тест 3", tools, rt)
    assert fake.calls == 4
    assert cache.get("web_page", research.page_dep(url)) is not None   # revalidated (304) → kept for another TTL

    expire()
    edition["text"] = "редакция 2"                   # the law was amended
    out = json.loads(asyncio.run(research.read(url, "x")))
    assert "изменилась" in out["note"] and "редакция 2" in out["text"]
    calls = fake.calls
    ask("кеш-тест 3", tools, rt)                     # the old answer was dropped → agent runs again
    assert fake.calls > calls


def test_learning_choices_and_lessons():
    f = Finding(agent="ambiguity", criterion="clarity", severity="important", key="vague:bystro", text="«быстро»")
    for _ in range(2):
        learning.record_choice(f, "Не более 2 с для 95% запросов")
    learning.record_choice(f, "Не более 1 с")
    p = learning.popular(f, ["Не более 1 с", "Не более 2 с для 95% запросов"])
    assert p == {"label": "Не более 2 с для 95% запросов", "n": 2, "total": 3}

    bad = Finding(agent="nfr", criterion="clarity", severity="minor", key="llm:rto", text="Нет RTO/RPO")
    learning.record_rejected("user-a", bad, "для MVP не требуется")
    assert "Нет RTO/RPO" in learning.lessons_prompt("user-a", "nfr")
    assert learning.lessons_prompt("user-b", "nfr") == ""           # never leaks to another account
