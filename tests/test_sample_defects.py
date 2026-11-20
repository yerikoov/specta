"""The agents must find most of the defects planted in samples/sample_tz_p2p.md."""
from scripts.check_sample import evaluate


def test_agents_find_planted_defects():
    r = evaluate()
    assert r["recall"] >= 0.8, r["missed"]
    assert not r["false_positives_kept"], r["false_positives_kept"]
