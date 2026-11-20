"""Supabase: accounts (GoTrue Auth) and persistence of TZ checks.

The secret key never leaves the server. Persistence uses Postgres tables (supabase/migrations/*.sql) when
they exist; until the migration is applied it falls back to a private Storage bucket with JSON objects,
so the product works the moment the keys are set. Without SUPABASE_* env vars everything stays in memory
(tests, local hacking) and a single local user is used.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Optional

import httpx

log = logging.getLogger("db")
BUCKET = "specta"


class AuthError(Exception):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


class Supa:
    def __init__(self) -> None:
        self.url = os.getenv("SUPABASE_URL", "").rstrip("/")
        self.key = os.getenv("SUPABASE_SECRET_KEY", "")
        self.enabled = bool(self.url and self.key)
        self.backend: Optional[str] = None          # "tables" | "storage" | "memory"
        self._mem: dict[str, dict] = {}              # memory backend: sid -> row
        self._users: dict[str, tuple[float, dict]] = {}  # token -> (expires, user)

    # ------------------------------------------------------------------ http
    def _h(self, bearer: Optional[str] = None, **extra) -> dict:
        h = {"apikey": self.key, "Authorization": f"Bearer {bearer or self.key}"}
        h.update(extra)
        return h

    async def _req(self, method: str, path: str, **kw) -> httpx.Response:
        async with httpx.AsyncClient(timeout=20) as c:
            return await c.request(method, self.url + path, **kw)

    # ------------------------------------------------------------------ auth
    async def signup(self, email: str, password: str, name: str) -> dict:
        if not self.enabled:
            return self._local_session(email, name)
        r = await self._req("POST", "/auth/v1/admin/users", headers=self._h(),
                            json={"email": email, "password": password, "email_confirm": True,
                                  "user_metadata": {"name": name}})
        if r.status_code in (400, 422):
            msg = r.json().get("msg") or r.json().get("message") or r.text
            if "already" in msg.lower() or "exists" in msg.lower():
                raise AuthError("Аккаунт с таким email уже есть — войдите", 409)
            raise AuthError(_ru_auth(msg))
        r.raise_for_status()
        user = r.json()
        await self._upsert_profile(user["id"], name)
        return await self.login(email, password)

    async def login(self, email: str, password: str) -> dict:
        if not self.enabled:
            return self._local_session(email, "")
        r = await self._req("POST", "/auth/v1/token?grant_type=password", headers={"apikey": self.key},
                            json={"email": email, "password": password})
        if r.status_code >= 400:
            raise AuthError("Неверный email или пароль", 401)
        return _session(r.json())

    async def refresh(self, refresh_token: str) -> dict:
        if not self.enabled:
            return self._local_session("local@specta", "")
        r = await self._req("POST", "/auth/v1/token?grant_type=refresh_token", headers={"apikey": self.key},
                            json={"refresh_token": refresh_token})
        if r.status_code >= 400:
            raise AuthError("Сессия истекла — войдите снова", 401)
        return _session(r.json())

    async def user(self, token: str) -> dict:
        """Validate an access token with Supabase Auth (cached for 60 s)."""
        if not self.enabled:
            return {"id": "local", "email": "local@specta", "name": "Вы"}
        hit = self._users.get(token)
        if hit and hit[0] > time.time():
            return hit[1]
        r = await self._req("GET", "/auth/v1/user", headers={"apikey": self.key, "Authorization": f"Bearer {token}"})
        if r.status_code >= 400:
            raise AuthError("Нужно войти", 401)
        u = r.json()
        user = {"id": u["id"], "email": u.get("email", ""), "name": (u.get("user_metadata") or {}).get("name", "")}
        self._users[token] = (time.time() + 60, user)
        return user

    def _local_session(self, email: str, name: str) -> dict:
        return {"access_token": "local", "refresh_token": "local", "expires_in": 10 ** 9,
                "user": {"id": "local", "email": email, "name": name or "Вы"}}

    async def _upsert_profile(self, uid: str, name: str) -> None:
        if await self._detect() != "tables":
            return
        await self._req("POST", "/rest/v1/profiles", headers=self._h(**{"Prefer": "resolution=merge-duplicates"}),
                        json={"id": uid, "name": name})

    # ------------------------------------------------------------------ backend detection
    async def _detect(self) -> str:
        if self.backend:
            return self.backend
        if not self.enabled:
            self.backend = "memory"
            return self.backend
        try:
            r = await self._req("GET", "/rest/v1/tz_sessions?select=id&limit=1", headers=self._h())
            if r.status_code == 200:
                self.backend = "tables"
            else:
                await self._req("POST", "/storage/v1/bucket", headers=self._h(),
                                json={"id": BUCKET, "name": BUCKET, "public": False})
                self.backend = "storage"
                log.warning("Supabase tables not found — apply supabase/migrations/*.sql; using Storage meanwhile")
        except httpx.HTTPError as e:
            log.error("Supabase unreachable (%s) — keeping data in memory", e)
            self.backend = "memory"
        return self.backend

    # ------------------------------------------------------------------ storage helpers
    async def _put(self, path: str, data: Any) -> None:
        r = await self._req("POST", f"/storage/v1/object/{BUCKET}/{path}",
                            headers=self._h(**{"x-upsert": "true", "Content-Type": "application/json"}),
                            content=_dumps(data))
        r.raise_for_status()

    async def _get(self, path: str) -> Optional[Any]:
        r = await self._req("GET", f"/storage/v1/object/authenticated/{BUCKET}/{path}", headers=self._h())
        if r.status_code in (400, 404):
            return None
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------------ sessions
    async def save(self, row: dict) -> None:
        """row: id, user_id, title, filename, score_before, score, status, share_token, state, events, cost_usd."""
        b = await self._detect()
        row = {**row, "updated_at": _iso(time.time())}
        if b == "memory":
            self._mem[row["id"]] = row
        elif b == "tables":
            r = await self._req("POST", "/rest/v1/tz_sessions?on_conflict=id",
                                headers=self._h(**{"Prefer": "resolution=merge-duplicates,return=minimal",
                                                   "Content-Type": "application/json"}),
                                content=_dumps(row))
            r.raise_for_status()
        else:
            await self._put(f"sessions/{row['id']}.json", row)
            idx = await self._get(f"users/{row['user_id']}/index.json") or []
            meta = _meta(row)
            idx = [m for m in idx if m["id"] != row["id"]] + [meta]
            await self._put(f"users/{row['user_id']}/index.json", idx)
            if row.get("share_token"):
                await self._put(f"shares/{row['share_token']}.json", {"id": row["id"]})

    async def load(self, sid: str) -> Optional[dict]:
        b = await self._detect()
        if b == "memory":
            return self._mem.get(sid)
        if b == "tables":
            r = await self._req("GET", f"/rest/v1/tz_sessions?id=eq.{sid}&select=*", headers=self._h())
            r.raise_for_status()
            rows = r.json()
            return rows[0] if rows else None
        return await self._get(f"sessions/{sid}.json")

    async def list(self, uid: str) -> list[dict]:
        b = await self._detect()
        if b == "memory":
            rows = [_meta(r) for r in self._mem.values() if r["user_id"] == uid]
        elif b == "tables":
            r = await self._req("GET", "/rest/v1/tz_sessions?select=id,user_id,title,filename,score_before,score,"
                                       f"status,share_token,cost_usd,created_at,updated_at&user_id=eq.{uid}"
                                       "&order=updated_at.desc&limit=100", headers=self._h())
            r.raise_for_status()
            rows = r.json()
        else:
            rows = await self._get(f"users/{uid}/index.json") or []
        return sorted(rows, key=lambda m: m.get("updated_at", ""), reverse=True)

    async def by_share(self, token: str) -> Optional[dict]:
        b = await self._detect()
        if b == "memory":
            return next((r for r in self._mem.values() if r.get("share_token") == token), None)
        if b == "tables":
            r = await self._req("GET", f"/rest/v1/tz_sessions?share_token=eq.{token}&select=*", headers=self._h())
            r.raise_for_status()
            rows = r.json()
            return rows[0] if rows else None
        ref = await self._get(f"shares/{token}.json")
        return await self.load(ref["id"]) if ref else None

    async def delete(self, sid: str, uid: str) -> None:
        b = await self._detect()
        if b == "memory":
            self._mem.pop(sid, None)
        elif b == "tables":
            await self._req("DELETE", f"/rest/v1/tz_sessions?id=eq.{sid}&user_id=eq.{uid}", headers=self._h())
        else:
            await self._req("DELETE", f"/storage/v1/object/{BUCKET}", headers=self._h(),
                            json={"prefixes": [f"sessions/{sid}.json"]})
            idx = await self._get(f"users/{uid}/index.json") or []
            await self._put(f"users/{uid}/index.json", [m for m in idx if m["id"] != sid])


def _session(tok: dict) -> dict:
    u = tok.get("user") or {}
    return {"access_token": tok["access_token"], "refresh_token": tok.get("refresh_token"),
            "expires_in": tok.get("expires_in", 3600),
            "user": {"id": u.get("id"), "email": u.get("email", ""), "name": (u.get("user_metadata") or {}).get("name", "")}}


def _meta(row: dict) -> dict:
    keys = ("id", "user_id", "title", "filename", "score_before", "score", "status", "share_token", "cost_usd",
            "created_at", "updated_at")
    return {k: row.get(k) for k in keys}


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _dumps(data: Any) -> bytes:
    import json
    return json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")


def _ru_auth(msg: str) -> str:
    m = msg.lower()
    if "password" in m:
        return "Пароль слишком простой — минимум 6 символов"
    if "email" in m:
        return "Проверьте email"
    return msg


supa = Supa()


# ---------------------------------------------------------------------- debounced persistence
_pending: dict[str, asyncio.Task] = {}


def schedule_save(session, delay: float = 1.5) -> None:
    """Coalesce bursts of chat events into one write per session."""
    if not getattr(session, "user_id", None):
        return
    t = _pending.get(session.id)
    if t and not t.done():
        return

    async def run():
        await asyncio.sleep(delay)
        _pending.pop(session.id, None)
        try:
            from .store import snapshot
            await supa.save(snapshot(session))
        except Exception:  # persistence must never break the chat
            log.exception("save failed for %s", session.id)

    try:
        _pending[session.id] = asyncio.get_running_loop().create_task(run())
    except RuntimeError:
        pass


async def save_now(session) -> None:
    if getattr(session, "user_id", None):
        from .store import snapshot
        await supa.save(snapshot(session))
