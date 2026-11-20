"""Bundled questions: fewer clicks, the same final TZ."""
import asyncio
from pathlib import Path

from app import orchestrator as o
from app.agents import clarifier
from app.parsing import parse_bytes
from app.store import create_session

SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "sample_tz_p2p.md"


def run(coro):
    return asyncio.run(coro)


async def analysed():
    s = create_session(parse_bytes("tz.md", SAMPLE.read_bytes()))
    await o.run_analysis(s)
    return s


def test_bundles_reduce_questions_and_keep_critical_single():
    s = run(analysed())
    singles = clarifier.build_questions(s.findings, [])
    assert len(s.questions) < len(singles) * 0.7
    for q in s.questions:
        if q.members:
            assert all(s.finding(fid).severity != "critical" for fid in q.members)
            assert q.options[-1].key == clarifier.SPLIT and len(q.items) == len(q.members)
    assert all(not q.members for q in s.questions if q.priority == "critical")


def test_bundle_gives_the_same_tz_as_answering_one_by_one():
    async def flow():
        a, b = await analysed(), await analysed()
        await o.handle_command(a, "improve")                # bundles, option A
        b.questions = clarifier.ordered(clarifier.build_questions(b.findings, []))  # no bundles
        await o.handle_command(b, "improve")
        return a, b
    a, b = run(flow())
    content = lambda s: sorted((x.title, x.text) for x in s.doc.sections)   # only new-section numbering may differ
    assert content(a) == content(b)
    assert a.score["total"] == b.score["total"]


def test_split_and_undo_bundle():
    async def flow():
        s = await analysed()
        bq = next(q for q in s.questions if q.members)
        members = list(bq.members)
        bq.status = "open"
        await o.answer(s, bq.id, "A", None)
        assert all(s.finding(f).status == "resolved" for f in members)
        await o.undo_answer(s, bq.id)
        assert all(s.finding(f).status == "open" for f in members)
        await o.answer(s, bq.id, clarifier.SPLIT, None)
        assert bq not in s.questions
        assert {q.finding_id for q in s.questions if not q.members} >= set(members)
        assert sum(q.status == "open" for q in s.questions) == 1
    run(flow())


def test_duplicates_from_other_agents_close_with_one_answer():
    async def flow():
        s = await analysed()
        singles = clarifier.ordered(clarifier.build_questions(s.findings, []))
        i, j = 0, next(k for k, q in enumerate(singles) if q.agent != singles[0].agent)
        qs, _ = clarifier.make_questions(s.findings, [[i, j]])
        s.questions = qs
        keep = next(q for q in qs if q.also)
        assert singles[j].finding_id in keep.also and all(q.finding_id != singles[j].finding_id for q in qs)
        keep.status = "open"
        await o.answer(s, keep.id, keep.options[0].key, None)
        assert s.finding(singles[j].finding_id).status == "resolved"
        await o.undo_answer(s, keep.id)
        assert s.finding(singles[j].finding_id).status == "open"
    run(flow())
