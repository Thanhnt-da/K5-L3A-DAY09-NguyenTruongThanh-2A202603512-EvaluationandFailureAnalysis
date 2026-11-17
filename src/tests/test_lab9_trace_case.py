"""Regression test for docs/trace_case.md: C-002, FM-03 ticket_trust.

The ticket claims a 5-day delay; the DB says 2 days (below SHIP-LATE-03's 3-day minimum), so the
correct outcome is `denied` with no refund. The first wrong step is a `model_override` event that
replaces the DB fact with the ticket's number. Runs the shapes on a temp store (lab9.trace_case).
"""
import pytest

pytestmark = pytest.mark.student
# Lab 8's cross-platform CI installs only Lab 8 deps and runs `-m student -k swarm`, which selects
# the swarm case below; skip there instead of failing. The eval-gate job installs pydantic-evals.
pytest.importorskip("pydantic_evals")


def _ctx(case):
    from pydantic_evals.evaluators import EvaluatorContext

    return EvaluatorContext(name="trace_case", inputs={}, metadata=None, expected_output=case["label"],
                            output=case["trial"], duration=0.0, _span_tree=None, attributes={}, metrics={})


def _first_override(events):
    return next((i for i, e in enumerate(events, 1) if e.get("kind") == "model_override"), None)


@pytest.mark.parametrize("shape,seed", [("seeded_regression", 11), ("swarm", 55)])
def test_ticket_trust_is_caught(shape, seed):
    from lab9.graders import DbFactKept, RefundAmountCorrect
    from lab9.trace_case import investigate

    case = investigate(shape, "C-002", seed)
    events = case["trial"]["events"]
    assert _first_override(events) == 3, "first wrong step should be event 3 (after handoff, investigator)"
    assert events[_first_override(events) - 1]["payload"] == {"delay_days": 5}
    assert DbFactKept().evaluate(_ctx(case)).value is False
    assert RefundAmountCorrect().evaluate(_ctx(case)).value is False      # ledger 20000, label 0
    assert case["trial"]["lab8_pass"] is False


def test_fixed_keeps_the_db_fact():
    from lab9.graders import DbFactKept, RefundAmountCorrect
    from lab9.trace_case import investigate

    case = investigate("fixed", "C-002", 11)
    assert _first_override(case["trial"]["events"]) is None
    assert DbFactKept().evaluate(_ctx(case)).value is True
    assert RefundAmountCorrect().evaluate(_ctx(case)).value is True
    assert case["trial"]["result"]["status"] == "denied"
    assert case["trial"]["lab8_pass"] is True
