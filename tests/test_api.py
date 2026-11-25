import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from app import orchestrator
from app.main import app
from app.store import get_session

client = TestClient(app)


def test_upload_analyze_report_export():
    r = client.post("/api/upload", data={"sample": "true", "context": "P2P, запуск 2027"})
    assert r.status_code == 200
    sid, k = r.json()["session_id"], r.json()["stream_key"]
    # the analyze SSE stream closes when analysis is done
    with client.stream("GET", f"/api/analyze/{sid}/stream?k={k}") as resp:
        body = "".join(resp.iter_text())
    assert '"type": "done"' in body and "event: end" in body
    s = get_session(sid)
    asyncio.run(orchestrator.run_chat_intro(s))
    assert client.get(f"/api/doc/{sid}").json()["highlights"]
    rep = client.get(f"/api/report/{sid}").json()
    assert rep["score"]["total"] == rep["score_before"]["total"]
    md = client.get(f"/api/report/{sid}/export?format=md&k={k}")
    assert md.status_code == 200 and "# Техническое задание" in md.text
    dx = client.get(f"/api/report/{sid}/export?format=docx&k={k}")
    assert dx.status_code == 200 and dx.content[:2] == b"PK"


def test_bad_uploads():
    assert client.post("/api/upload", files={"file": ("x.exe", b"MZ", "application/octet-stream")}).status_code == 400
    assert client.get("/api/doc/nope").status_code == 404
    assert client.post("/api/chat/nope/answer", json={"question_id": "q1", "choice_key": "A"}).status_code == 404


def test_history_share_and_stream_key():
    r = client.post("/api/upload", data={"sample": "true"})
    sid, k = r.json()["session_id"], r.json()["stream_key"]
    assert client.get(f"/api/chat/{sid}/stream?k=wrong").status_code == 404
    s = get_session(sid)
    asyncio.run(orchestrator.run_analysis(s))
    asyncio.run(orchestrator.run_chat_intro(s))
    asyncio.run(orchestrator.handle_command(s, "improve"))
    from app.db import save_now
    asyncio.run(save_now(s))
    assert any(m["id"] == sid for m in client.get("/api/sessions").json())
    tok = client.post(f"/api/sessions/{sid}/share").json()["token"]
    pub = client.get(f"/api/share/{tok}").json()
    assert pub["summary"]["headline"] and pub["score"]["total"] > pub["score_before"]["total"]
    assert client.get(f"/api/share/{tok}/export").content[:2] == b"PK"
    assert s.debate, "agents must discuss doubtful findings"


def test_upload_with_appendices():
    from app.agents.base import doc_for_prompt
    tz = (Path(__file__).resolve().parent.parent / "samples" / "test_tz_bnpl.md").read_bytes()
    api_spec = "# Спецификация API\n1. POST /installments — создать рассрочку, таймаут 5 с.\n".encode()
    r = client.post("/api/upload", files=[("file", ("tz.md", tz, "text/markdown")),
                                          ("extra", ("api.md", api_spec, "text/markdown"))])
    assert r.status_code == 200 and r.json()["appendix"] == 1
    s = get_session(r.json()["session_id"])
    assert s.doc.appendix[0].startswith("[api.md]") and "POST /installments" in doc_for_prompt(s.doc)
    assert not any("installments" in (x.text or "") for x in s.doc.sections)     # appendix is not part of the TZ
    bad = client.post("/api/upload", files=[("file", ("tz.md", tz, "text/markdown")), ("extra", ("x.exe", b"MZ", "application/x"))])
    assert bad.status_code == 400 and "x.exe" in bad.json()["detail"]
