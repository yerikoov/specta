"""Runs the agent pipeline on the sample ТЗ and checks the planted defects are found.

    python -m scripts.check_sample
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("MOCK_DELAY_SCALE", "0")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from app import orchestrator  # noqa: E402
from app.parsing import parse_bytes  # noqa: E402
from app.store import create_session  # noqa: E402


def _match(f, d) -> bool:
    if f.agent != d["agent"]:
        return False
    if d.get("ref") and not (f.section_ref or "").startswith(str(d["ref"])):
        return False
    if d.get("key") and d["key"] not in f.key:
        return False
    return True


def evaluate() -> dict:
    exp = yaml.safe_load((ROOT / "samples" / "expected_defects.yaml").read_text(encoding="utf-8"))
    s = create_session(parse_bytes("sample_tz_p2p.md", (ROOT / "samples" / "sample_tz_p2p.md").read_bytes()))
    asyncio.run(orchestrator.run_analysis(s))
    kept = [f for f in s.findings if f.status == "open"]
    found, missed = [], []
    for d in exp["defects"]:
        (found if any(_match(f, d) for f in kept) else missed).append(d)
    fps = [d for d in exp.get("false_positives", []) if any(_match(f, d) for f in kept)]
    return {"total": len(exp["defects"]), "found": found, "missed": missed,
            "recall": len(found) / len(exp["defects"]), "false_positives_kept": fps,
            "kept": len(kept), "dropped": sum(1 for f in s.findings if f.status == "dropped"),
            "score": s.score_before["total"]}


if __name__ == "__main__":
    r = evaluate()
    for d in r["found"]:
        print(f"  ✓ {d['id']} {d['kind']:<16} {d['note']}")
    for d in r["missed"]:
        print(f"  ✗ {d['id']} {d['kind']:<16} {d['note']}")
    print(f"\nНайдено {len(r['found'])}/{r['total']} заложенных дефектов (recall {r['recall']:.0%}); "
          f"замечаний после Критика: {r['kept']}, отклонено: {r['dropped']}; стартовая оценка {r['score']}/100")
    if r["false_positives_kept"]:
        print("Ложные срабатывания не удалены:", r["false_positives_kept"])
    sys.exit(0 if r["recall"] >= 0.8 and not r["false_positives_kept"] else 1)
