import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from app import orchestrator as o
from app.models import Event
from app.parsing import parse_bytes
from app.store import create_session

SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "sample_tz_p2p.md"
KEYS = {"id", "agent", "type", "severity", "section_ref", "text", "quote", "options", "allow_custom", "emotion"}


def test_event_schema_rejects_unknown_type():
    with pytest.raises(ValidationError):
        Event(agent="critic", type="banana", text="x")
    with pytest.raises(ValidationError):
        Event(agent="critic", type="status", emotion="furious")


def run(coro):
    return asyncio.run(coro)


def test_full_flow_events_follow_one_schema():
    async def flow():
        s = create_session(parse_bytes("tz.md", SAMPLE.read_bytes()))
        await o.run_analysis(s)
        assert s.analyze_log.items[-1]["type"] == "done"
        await o.run_chat_intro(s)
        assert not any(q.status == "open" for q in s.questions)   # summary first, questions on request
        await o.handle_command(s, "start")
        q = next(q for q in s.questions if q.status == "open")
        before = s.score["total"]
        await o.answer(s, q.id, q.options[0].key, None)
        assert s.score["total"] > before
        await o.undo_answer(s, q.id)
        assert s.question(q.id).status == "open"
        await o.handle_command(s, "improve")
        return s

    s = run(flow())
    types = {e["type"] for e in s.chat_log.items}
    assert {"status", "finding", "question", "score", "applied", "done"} <= types
    for e in s.chat_log.items:
        assert KEYS <= set(e)
        Event.model_validate(e)
        if e["type"] == "question":
            assert e["options"] and e["allow_custom"] is True
    assert s.reported and s.score["total"] > s.score_before["total"]
    assert s.tests


def test_custom_answer_changes_document():
    async def flow():
        s = create_session(parse_bytes("tz.md", SAMPLE.read_bytes()))
        await o.run_analysis(s)
        await o.run_chat_intro(s)
        await o.handle_command(s, "start")
        q = next(q for q in s.questions if q.status == "open" and s.finding(q.finding_id).quote)
        await o.answer(s, q.id, None, "Лимит на одну операцию — 250 000 ₸.")
        return s

    s = run(flow())
    assert "250 000 ₸" in s.doc.full_text()


def test_summary_and_skip():
    async def flow():
        s = create_session(parse_bytes("tz.md", SAMPLE.read_bytes()))
        await o.run_analysis(s)
        await o.run_chat_intro(s)
        summary = next(e for e in s.chat_log.items if e["type"] == "score")["data"]["summary"]
        assert summary["top"] and summary["actions"][0]["cmd"] == "start"
        await o.handle_command(s, "start")
        first = next(q for q in s.questions if q.status == "open")
        await o.handle_message(s, first.id, "skip")
        nxt = next(q for q in s.questions if q.status == "open")
        assert nxt.id != first.id and s.question(first.id).skipped
        return s

    run(flow())


def test_mention_routes_to_that_agent():
    async def flow():
        s = create_session(parse_bytes("tz.md", SAMPLE.read_bytes()))
        await o.run_analysis(s)
        await o.run_chat_intro(s)
        await o.handle_message(s, "@Комплаенс что с KYC?", None)
        return s

    s = run(flow())
    last = s.chat_log.items[-1]
    assert last["agent"] == "regulatory" and last["data"].get("reply_to")
    assert o.mentioned_agent("вопрос к @нфт") == "nfr" and o.mentioned_agent("без упоминаний") is None


def test_several_mentions_start_a_discussion():
    async def flow():
        s = create_session(parse_bytes("tz.md", SAMPLE.read_bytes()))
        await o.run_analysis(s)
        await o.run_chat_intro(s)
        n = len(s.chat_log.items)
        await o.handle_message(s, "@Ясность спроси у @Комплаенс, что с KYC", None)
        return s, n

    s, n = run(flow())
    new = s.chat_log.items[n:]
    speakers = [e["agent"] for e in new]
    assert {"ambiguity", "regulatory"} <= set(speakers) and len(new) >= 3
    assert new[0]["data"]["to"] == "regulatory"
    assert new[0]["data"]["working"] and not new[-1]["data"].get("working")


def test_cancelled_message_is_forgotten():
    async def flow():
        s = create_session(parse_bytes("tz.md", SAMPLE.read_bytes()))
        await o.run_analysis(s)
        before, n = s.context, len(s.notes)
        real = o.pause

        async def hang(*_a, **_k):
            await asyncio.sleep(30)

        o.pause = hang
        try:
            task = asyncio.create_task(o.handle_message(s, "@Комплаенс случайно", None))
            for _ in range(50):
                if len(s.notes) > n:
                    break
                await asyncio.sleep(0.01)
            assert len(s.notes) == n + 1 and s.pending_agent == "regulatory"
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert s.context == before and len(s.notes) == n
        finally:
            o.pause = real

    run(flow())


def test_cancel_says_who_stopped():
    from app.main import _safe

    async def flow():
        s = create_session(parse_bytes("tz.md", SAMPLE.read_bytes()))
        s.pending_agent = "reporter"
        s.cancel_token = 1

        async def hang():
            await asyncio.sleep(30)

        task = asyncio.create_task(_safe(s, hang()))
        await asyncio.sleep(0.05)
        task.cancel()
        await task
        last = s.chat_log.items[-1]
        assert last["agent"] == "reporter" and last["text"] == "Остановил."

    run(flow())
