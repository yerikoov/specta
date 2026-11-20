"""Tiny local knowledge base (/kb/*.md with YAML front matter) + keyword retrieval (RAG)."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

KB_DIR = Path(__file__).resolve().parent.parent / "kb"


@lru_cache
def load_kb() -> list[dict]:
    docs = []
    for p in sorted(KB_DIR.glob("*.md")):
        raw = p.read_text(encoding="utf-8")
        meta, body = {}, raw
        if raw.startswith("---"):
            _, fm, body = raw.split("---", 2)
            meta = yaml.safe_load(fm) or {}
        docs.append({"file": p.name, "body": body.strip(), **meta})
    return docs


def checks_for(agent: str) -> list[tuple[dict, dict]]:
    """[(kb_doc, check)] for an agent."""
    return [(d, c) for d in load_kb() if d.get("agent") == agent for c in d.get("checks", [])]


def _tokens(text: str) -> set[str]:
    return {w[:6] for w in re.findall(r"[а-яёa-z]{4,}", text.lower())}


def retrieve(query: str, k: int = 3, agent: str | None = None) -> list[dict]:
    """Keyword-overlap retrieval over KB bodies + check titles (good enough offline RAG)."""
    q = _tokens(query)
    scored = []
    for d in load_kb():
        if agent and d.get("agent") != agent:
            continue
        text = d["body"] + " " + " ".join(c.get("title", "") for c in d.get("checks", []))
        scored.append((len(q & _tokens(text)), d))
    scored.sort(key=lambda x: -x[0])
    return [d for s, d in scored[:k] if s > 0]
