"""Bugs found on a real upload: a non-TZ got 92/100, P2P wording leaked into other products,
placeholders counted as filled sections, markdown tables were glued, the change log was truncated."""
import asyncio
from pathlib import Path

from app import export
from app import orchestrator as o
from app.doccheck import tz_likeness
from app.parsing import parse_bytes
from app.store import create_session

S = Path(__file__).resolve().parent.parent / "samples"


def doc(name):
    return parse_bytes(name, (S / name).read_bytes())


def analysed(name):
    s = create_session(doc(name))
    asyncio.run(o.run_analysis(s))
    return s


def test_a_checklist_is_not_a_tz():
    assert tz_likeness(doc("sample_tz_p2p.md"))["ok"]
    assert tz_likeness(doc("test_tz_bnpl.md"))["ok"]
    bad = tz_likeness(doc("test_tz_bnpl_expected.md"))
    assert not bad["ok"] and bad["reason"]
    s = analysed("test_tz_bnpl_expected.md")
    assert s.warning and "не похож" in o.summary_data(s)["verdict"]
    assert not analysed("test_tz_bnpl.md").warning


def test_markdown_tables_and_bullets_become_clauses():
    d = doc("test_tz_bnpl_expected.md")
    sec2 = [x for x in d.sections if x.ref.startswith("2.")]
    assert len(sec2) == 5 and sec2[0].text.startswith("C1 — Сумма одной покупки")
    assert not any("|---" in x.text for x in d.sections)
    sec3 = [x for x in d.sections if x.ref.startswith("3.")]
    assert sec3[0].ref == "3.1" and sec3[0].text.startswith("п. 3.8")   # a reference, not the clause number


def test_fixes_for_a_credit_product_do_not_talk_about_transfers():
    s = analysed("test_tz_bnpl.md")
    texts = [op.text.lower() for f in s.findings for opt in f.options for op in opt.ops]
    leaked = [t for t in texts if "перевод" in t or "получател" in t or "енп" in t]
    assert not leaked, leaked[:3]


def test_placeholder_sections_stay_open_and_keep_the_score_honest():
    async def flow():
        s = create_session(doc("test_tz_bnpl.md"))
        await o.run_analysis(s)
        await o.handle_command(s, "improve")
        return s
    s = asyncio.run(flow())
    stubs = [f for f in s.findings if f.key.endswith(":stub") and f.status == "open"]
    assert stubs, "added «goals/terms/schedule/risks» placeholders must remain open"
    assert s.score["total"] < 95
    md = export.improved_md(s)
    assert "…" not in md.split("## Журнал изменений")[1]        # change log is written in full
