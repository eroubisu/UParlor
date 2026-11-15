"""Quality baseline ratchet tests."""

from tools.quality_audit import assess


BASELINE = {
    "coverage_floor": 59.0,
    "duplicate_group_ceiling": 3,
    "severe_complexity": {"module.py:Example.run": 24},
    "vulture_allowlist": [
        {"path": "module.py", "name": "callback_arg", "reason": "framework"},
    ],
}


def test_quality_ratchet_accepts_equal_or_improved_metrics():
    metrics = {
        "coverage_percent": 60.0,
        "duplicate_groups": 2,
        "severe_complexity": {"module.py:Example.run": 23},
        "vulture_findings": [
            {"path": "module.py", "name": "callback_arg"},
        ],
    }

    assert assess(metrics, BASELINE) == []


def test_quality_ratchet_reports_each_regression_class():
    metrics = {
        "coverage_percent": 58.0,
        "duplicate_groups": 4,
        "severe_complexity": {
            "module.py:Example.run": 25,
            "module.py:Example.new": 21,
        },
        "vulture_findings": [
            {"path": "module.py", "name": "unused_value"},
        ],
    }

    errors = assess(metrics, BASELINE)

    assert len(errors) == 5
    assert any("coverage" in error for error in errors)
    assert any("duplicate groups" in error for error in errors)
    assert any("complexity worsened" in error for error in errors)
    assert any("new severe complexity" in error for error in errors)
    assert any("new dead-code candidate" in error for error in errors)
