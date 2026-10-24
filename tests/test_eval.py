import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))

from answer_eval import args_match  # noqa: E402


def test_days_equal_dates():
    want = {"price": 70000, "due_date": "2026-03-01", "actual_date": "2026-03-11", "kind": "prepaid_delivery"}
    assert args_match(want, {"price": 70000, "days": 10, "kind": "prepaid_delivery"})
    assert args_match(want, {"price": 70000, "due_date": "2026-03-01", "actual_date": "2026-03-11", "kind": "prepaid_delivery"})
    assert not args_match(want, {"price": 70000, "due_date": "2026-03-02", "actual_date": "2026-03-11", "kind": "prepaid_delivery"})


def test_custom_kind_may_be_omitted():
    want = {"event_date": "2026-07-10", "days": 30}
    assert args_match(want, {"event_date": "2026-07-10", "days": 30})
    assert not args_match(want, {"event_date": "2026-07-11", "days": 30})


def test_out_of_scope_split():
    from answer_eval import metrics

    def run(expect, refused):
        return {"case": {"expected": [], "expect": expect}, "refused": refused, "sources": [], "tool_calls": [],
                "cited": 0, "invalid": 0, "seconds": 1, "tokens_per_sec": None}

    m = metrics([run("refuse", True), run("refuse", False), run("web_ok", False)], [])
    assert m["refusal_on_out_of_scope"] == 0.5
    assert m["web_ok_answered"] == 1.0
