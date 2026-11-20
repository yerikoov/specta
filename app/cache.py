"""Persistent cache (one SQLite file) that saves tokens but never serves stale knowledge.

Namespaces:
* ``llm``  — structured agent answers. The key hashes the model, prompts, the TZ text, the schema and the tools,
  and every row is stamped with the *knowledge fingerprint* (KB files, rules, template, agent/prompt code).
  Change any of these and old answers stop matching; they are purged on start.
* ``web_search`` / ``web_page`` — free web research. Pages are revalidated after their TTL with
  ETag / Last-Modified / content hash; when a page really changed, every ``llm`` row that read it is dropped.
* the learning tables live in the same file (see app.learning).

Disable with CACHE=0; the file is CACHE_DB (default data/cache.sqlite).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
from functools import lru_cache
from pathlib import Path

log = logging.getLogger("specta.cache")
ROOT = Path(__file__).resolve().parent.parent
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
_conn_path: str | None = None

# what the cached answers depend on: when any of these files changes, the fingerprint changes
KNOWLEDGE = ["kb/*.md", "config/*.yaml", "app/agents/*.py", "app/llm.py"]


def enabled() -> bool:
    return os.getenv("CACHE", "1").lower() not in ("0", "false", "no", "off")


def db_path() -> str:
    return os.getenv("CACHE_DB") or str(ROOT / "data" / "cache.sqlite")


def conn() -> sqlite3.Connection:
    global _conn, _conn_path
    path = db_path()
    if _conn is None or _conn_path != path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        _conn_path = path
        _conn.execute("pragma journal_mode=wal")
        _conn.executescript("""
            create table if not exists entries (ns text, key text, value text, meta text, version text,
                created real, expires real, hits integer default 0, primary key (ns, key));
            create table if not exists deps (ns text, key text, dep text);
            create index if not exists deps_dep on deps (dep);
            create table if not exists choices (sig text, label text, n integer, ts real, primary key (sig, label));
            create table if not exists lessons (scope text, agent text, text text, reason text, n integer, ts real,
                primary key (scope, agent, text));
        """)
        purge()
    return _conn


@lru_cache(maxsize=1)
def _fingerprint_cached(stamp: str) -> str:
    h = hashlib.sha256()
    for pattern in KNOWLEDGE:
        for p in sorted(ROOT.glob(pattern)):
            h.update(p.name.encode())
            h.update(p.read_bytes())
    return h.hexdigest()[:16]


def fingerprint() -> str:
    """Hash of everything the agents' answers depend on (recomputed only when a file's mtime changes)."""
    stamp = "|".join(f"{p}:{p.stat().st_mtime_ns}" for pattern in KNOWLEDGE for p in sorted(ROOT.glob(pattern)))
    return _fingerprint_cached(stamp)


def key_of(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def get(ns: str, key: str, allow_expired: bool = False) -> tuple[str, dict] | None:
    """(value, meta) or None. ``llm`` rows from an older knowledge fingerprint never match."""
    if not enabled():
        return None
    with _lock:
        row = conn().execute("select value, meta, version, expires from entries where ns=? and key=?", (ns, key)).fetchone()
        if not row:
            return None
        value, meta, version, expires = row
        if ns == "llm" and version != fingerprint():
            return None
        if expires < time.time() and not allow_expired:
            return None
        conn().execute("update entries set hits = hits + 1 where ns=? and key=?", (ns, key))
    return value, json.loads(meta or "{}")


def put(ns: str, key: str, value: str, ttl: float, meta: dict | None = None, deps: list[str] | None = None) -> None:
    if not enabled():
        return
    now = time.time()
    with _lock:
        c = conn()
        c.execute("insert or replace into entries (ns, key, value, meta, version, created, expires, hits) "
                  "values (?, ?, ?, ?, ?, ?, ?, coalesce((select hits from entries where ns=? and key=?), 0))",
                  (ns, key, value, json.dumps(meta or {}, ensure_ascii=False), fingerprint(), now, now + ttl, ns, key))
        c.execute("delete from deps where ns=? and key=?", (ns, key))
        c.executemany("insert into deps (ns, key, dep) values (?, ?, ?)", [(ns, key, d) for d in set(deps or [])])


def extend(ns: str, key: str, ttl: float) -> None:
    """The source was revalidated and did not change: keep the row for another TTL."""
    with _lock:
        conn().execute("update entries set expires=? where ns=? and key=?", (time.time() + ttl, ns, key))


def deps_of(ns: str, key: str) -> list[str]:
    with _lock:
        return [r[0] for r in conn().execute("select dep from deps where ns=? and key=?", (ns, key))]


def invalidate_dep(dep: str) -> int:
    """A source (e.g. a law page) changed: drop every cached answer that was built on it."""
    with _lock:
        c = conn()
        rows = c.execute("select ns, key from deps where dep=?", (dep,)).fetchall()
        for ns, key in rows:
            c.execute("delete from entries where ns=? and key=?", (ns, key))
            c.execute("delete from deps where ns=? and key=?", (ns, key))
    if rows:
        log.info("source changed, dropped %s cached answers: %s", len(rows), dep)
    return len(rows)


def purge() -> None:
    """Drop expired rows and answers from older knowledge (called on open)."""
    now = time.time()
    c = _conn
    stale = c.execute("select ns, key from entries where (ns='llm' and version != ?) or expires < ?",
                      (fingerprint(), now - 30 * 86400)).fetchall()
    for ns, key in stale:
        c.execute("delete from entries where ns=? and key=?", (ns, key))
        c.execute("delete from deps where ns=? and key=?", (ns, key))
    if stale:
        log.info("cache: purged %s stale rows", len(stale))


def stats() -> dict:
    if not enabled():
        return {"enabled": False}
    with _lock:
        c = conn()
        by_ns = {ns: {"rows": n, "hits": h or 0} for ns, n, h in
                 c.execute("select ns, count(*), sum(hits) from entries group by ns")}
        saved = c.execute("select coalesce(sum(json_extract(meta, '$.usd') * hits), 0) from entries where ns='llm'").fetchone()[0]
        lessons = c.execute("select count(*) from lessons").fetchone()[0]
        choices = c.execute("select coalesce(sum(n), 0) from choices").fetchone()[0]
    return {"enabled": True, "fingerprint": fingerprint(), "namespaces": by_ns, "saved_usd": round(saved, 4),
            "lessons": lessons, "answers_learned": choices}
