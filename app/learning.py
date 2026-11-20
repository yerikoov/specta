"""The team learns from past checks — no model training, just memory that goes into prompts and cards.

1. **Choices** — which answer analysts pick for a typical problem (rule key, e.g. «размытое "быстро"»).
   Only rule-based findings are counted: their key is stable across documents and carries no client text.
   The question card then shows «Чаще выбирают: …».
2. **Lessons** — findings the team rejected (the Critic's ruling in the debate, a failed quote check).
   They are added to that agent's prompt next time: «такие замечания отклоняли — не повторяй».
   Lessons are kept per account (they quote the client's TZ, so they never leak to other users),
   at most LESSONS_PER_AGENT per agent, and expire after LESSON_DAYS.

Lessons are not part of the cache key (see llm.run_agent `learned`): an identical TZ reuses its already debated
answer, a new or edited TZ misses the cache and is checked with the experience.
"""
from __future__ import annotations

import os
import time

from . import cache
from .models import Finding

LESSONS_PER_AGENT = 5
LESSON_DAYS = 90


def enabled() -> bool:
    return cache.enabled() and os.getenv("LEARNING", "1").lower() not in ("0", "false", "no", "off")


def _sig(f: Finding) -> str | None:
    if not f.key or f.key.startswith("llm:"):
        return None
    return f"{f.agent}|{f.key}"


def record_choice(f: Finding, label: str) -> None:
    sig = _sig(f)
    if not sig or not enabled():
        return
    with cache._lock:
        cache.conn().execute("insert into choices (sig, label, n, ts) values (?, ?, 1, ?) "
                             "on conflict (sig, label) do update set n = n + 1, ts = excluded.ts", (sig, label, time.time()))


def popular(f: Finding, labels: list[str]) -> dict | None:
    """{"label", "n", "total"} when analysts chose one of these options at least twice before."""
    sig = _sig(f)
    if not sig or not enabled():
        return None
    with cache._lock:
        rows = cache.conn().execute("select label, n from choices where sig=? order by n desc", (sig,)).fetchall()
    total = sum(n for _, n in rows)
    top = next(((lab, n) for lab, n in rows if lab in labels), None)
    if not top or top[1] < 2:
        return None
    return {"label": top[0], "n": top[1], "total": total}


def record_rejected(scope: str, f: Finding, reason: str) -> None:
    """A finding the team rejected → a lesson for that agent (only Claude-found ones: rules don't need it)."""
    if not enabled() or not f.key.startswith("llm:"):
        return
    text = " ".join(f.text.split())[:200]
    with cache._lock:
        c = cache.conn()
        c.execute("insert into lessons (scope, agent, text, reason, n, ts) values (?, ?, ?, ?, 1, ?) "
                  "on conflict (scope, agent, text) do update set n = n + 1, reason = excluded.reason, ts = excluded.ts",
                  (scope, f.agent, text, " ".join(reason.split())[:200], time.time()))


def lessons(scope: str, agent: str) -> list[dict]:
    if not enabled():
        return []
    with cache._lock:
        rows = cache.conn().execute(
            "select text, reason, n from lessons where scope=? and agent=? and ts > ? order by n desc, ts desc limit ?",
            (scope, agent, time.time() - LESSON_DAYS * 86400, LESSONS_PER_AGENT)).fetchall()
    return [{"text": t, "reason": r, "n": n} for t, r, n in rows]


def lessons_prompt(scope: str, agent: str) -> str:
    items = lessons(scope, agent)
    if not items:
        return ""
    lines = "\n".join(f"- «{x['text']}» — отклонено: {x['reason']}" for x in items)
    return ("\n\nОпыт прошлых проверок этой команды: такие замечания отклоняли — не повторяй похожие, "
            "если в этом ТЗ нет новых фактов:\n" + lines)
