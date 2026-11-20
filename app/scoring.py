"""Scoring 0–100 by criteria. Pure Python, recomputed after every applied answer."""
from __future__ import annotations

import math

from .models import Finding

CRITERIA = {
    "completeness": "Полнота",
    "clarity": "Ясность",
    "testability": "Тестируемость",
    "consistency": "Согласованность",
    "compliance": "Комплаенс",
}
PENALTY = {"critical": 18, "important": 10, "minor": 4}
DECAY = 80.0   # score = 100 * exp(-penalty / DECAY): diminishing, never negative


NOT_TZ_CAP = 40   # a document that is not a TZ never looks «ready», whatever was patched into it


def compute(findings: list[Finding], cap: int | None = None) -> dict:
    pen = {c: 0 for c in CRITERIA}
    open_count = {c: 0 for c in CRITERIA}
    for f in findings:
        if f.status == "open":
            pen[f.criterion] += PENALTY[f.severity]
            open_count[f.criterion] += 1
    crit = {c: round(100 * math.exp(-p / DECAY)) for c, p in pen.items()}
    total = round(sum(crit.values()) / len(crit))
    if cap is not None:
        total = min(total, cap)
    return {
        "total": total,
        "ten": round(total / 10, 1),
        "capped": cap is not None and total == cap,
        "criteria": [{"key": c, "label": CRITERIA[c], "value": crit[c], "open": open_count[c]} for c in CRITERIA],
    }
