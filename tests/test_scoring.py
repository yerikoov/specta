from app import scoring
from app.models import Finding


def f(criterion, sev, status="open"):
    return Finding(agent="x", criterion=criterion, severity=sev, text="t", status=status)


def test_perfect_score_without_findings():
    s = scoring.compute([])
    assert s["total"] == 100 and len(s["criteria"]) == 5


def test_penalties_and_resolution_raise_score():
    items = [f("clarity", "critical"), f("consistency", "important"), f("compliance", "minor")]
    before = scoring.compute(items)["total"]
    items[0].status = "resolved"
    after = scoring.compute(items)["total"]
    assert 0 < before < after <= 100


def test_dropped_findings_do_not_count():
    assert scoring.compute([f("clarity", "critical", "dropped")])["total"] == 100


def test_score_never_negative():
    s = scoring.compute([f("compliance", "critical") for _ in range(50)])
    assert all(c["value"] >= 0 for c in s["criteria"])
