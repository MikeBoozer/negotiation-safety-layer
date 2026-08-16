"""Tests for the SPI ground-rules handshake.

`nsl/spi.py` had no test importing it, despite being the module behind the
experiment's bilateral arm — the 60/60 refusal and the 39/40 uptake flip, which
is the published write-up's strongest result. It is only 38 lines, which caps
the risk, but "small" is not "verified".

The property that actually matters is the one its own docstring warns about:
the rules PROPOSED to the counterparty must be the rules the verifier ENFORCES.
If those two silently diverge, the experiment asks the counterparty to agree to
one thing and then scores it against another, and every uptake number becomes
uninterpretable. That is `test_asked_rules_cover_everything_the_verifier_enforces`
below, which runs a real mock episode rather than asserting on spi.py alone.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from nsl.spi import SPIHandshake, default_ground_rules  # noqa: E402


class Spy:
    """Counterparty that records what it was asked and answers as instructed."""

    def __init__(self, accepts: bool) -> None:
        self.accepts = accepts
        self.asked: List[List[str]] = []

    def consider_ground_rules(self, rules: List[str]) -> bool:
        self.asked.append(list(rules))
        return self.accepts


# --------------------------------------------------------------------------
# default_ground_rules
# --------------------------------------------------------------------------

def test_default_rules_are_both_present() -> None:
    rules = default_ground_rules()
    assert len(rules) == 2
    assert any("void" in r.lower() for r in rules)
    assert any("rewards a demand" in r.lower() for r in rules)


def test_default_rules_are_a_fresh_list_each_call() -> None:
    """A future refactor to a module-level constant would make one caller's
    edit leak into every later negotiation."""
    first = default_ground_rules()
    first.append("Injected rule that no one agreed to.")
    assert "Injected rule that no one agreed to." not in default_ground_rules()


# --------------------------------------------------------------------------
# SPIHandshake
# --------------------------------------------------------------------------

def test_proposes_exactly_the_rules_it_was_constructed_with() -> None:
    rules = ["Rule A.", "Rule B."]
    spy = Spy(accepts=True)
    SPIHandshake(rules).negotiate(spy)
    assert spy.asked == [["Rule A.", "Rule B."]]


def test_accepting_returns_the_rules() -> None:
    rules = ["Rule A.", "Rule B."]
    assert SPIHandshake(rules).negotiate(Spy(accepts=True)) == rules


def test_declining_returns_empty() -> None:
    assert SPIHandshake(["Rule A."]).negotiate(Spy(accepts=False)) == []


def test_counterparty_is_asked_exactly_once_even_when_it_declines() -> None:
    spy = Spy(accepts=False)
    SPIHandshake(["Rule A."]).negotiate(spy)
    assert len(spy.asked) == 1


def test_construction_copies_the_caller_s_list() -> None:
    """Otherwise a later edit to the caller's list changes what gets proposed,
    after the design was supposedly fixed."""
    rules = ["Rule A."]
    handshake = SPIHandshake(rules)
    rules.append("Snuck in after construction.")
    spy = Spy(accepts=True)
    handshake.negotiate(spy)
    assert spy.asked == [["Rule A."]]


def test_returned_list_is_a_copy() -> None:
    """Mutating one episode's agreed rules must not change the next episode's."""
    handshake = SPIHandshake(["Rule A."])
    agreed = handshake.negotiate(Spy(accepts=True))
    agreed.append("Added downstream.")
    assert handshake.negotiate(Spy(accepts=True)) == ["Rule A."]


def test_empty_rule_set_makes_acceptance_indistinguishable_from_refusal() -> None:
    """DOCUMENTS A LATENT TRAP rather than asserting desired behaviour.

    `negotiate` signals acceptance by returning a non-empty list, and
    `harness/run_experiment.py` records the outcome as `bool(handshake.
    negotiate(cp))`. So with an empty rule set, a counterparty that ACCEPTS is
    recorded as having refused.

    Not currently reachable: the caller always passes
    `policy.ground_rules + [THEIR_NO_THREAT]`, which is never empty. It is
    recorded because the uptake result is the paper's strongest finding and this
    is the one way it could be silently mis-recorded — if a future scenario ever
    supplies no ground rules, the handshake needs a separate accepted flag.
    """
    spy = Spy(accepts=True)
    assert SPIHandshake([]).negotiate(spy) == []
    assert spy.accepts is True  # it said yes
    assert bool(SPIHandshake([]).negotiate(Spy(accepts=True))) is False  # recorded as no


# --------------------------------------------------------------------------
# The wiring test — the one the docstring's warning is about
# --------------------------------------------------------------------------

def test_asked_rules_cover_everything_the_verifier_enforces(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run a real bilateral mock episode and capture what the counterparty was
    actually asked, then assert it contains every rule the verifier enforces.

    `nsl/verifier.py` builds its prompt from `policy.ground_rules`, and
    `run_experiment.py` proposes `policy.ground_rules + [THEIR_NO_THREAT]`. The
    extra clause is what we ask OF them, so a superset is correct and equality
    is not. What must never happen is a rule being enforced that was never put
    to the counterparty.
    """
    from harness import run_experiment as rx

    captured: List[List[str]] = []
    real_make = rx.make_counterparty

    def spying_make(kind: str, llm):  # type: ignore[no-untyped-def]
        cp = real_make(kind, llm)
        inner = cp.consider_ground_rules

        def wrapped(rules: List[str]) -> bool:
            captured.append(list(rules))
            return inner(rules)

        cp.consider_ground_rules = wrapped  # type: ignore[method-assign]
        return cp

    monkeypatch.setattr(rx, "make_counterparty", spying_make)

    from harness.mock_brain import mock_handler  # noqa: E402
    from nsl.factory import build_layer  # noqa: E402
    from nsl.llm import MockLLM  # noqa: E402
    from nsl.scenarios.otc_rfq import OTCScenario  # noqa: E402

    llm = MockLLM(mock_handler)
    scenario = OTCScenario()
    layer = build_layer(llm, scenario)
    cell = next(
        c for c in rx.default_grid(episodes=1, calibration_episodes=1)
        if c.laterality == "bilateral" and c.counterparty == "llm"
    )
    rx.run_episode(cell, 0, layer, scenario, llm)

    assert captured, "the bilateral arm must ask the counterparty about ground rules"
    asked = captured[0]
    for rule in layer.policy.ground_rules:
        assert rule in asked, (
            "the verifier enforces a rule the counterparty was never asked to agree to: "
            f"{rule!r}"
        )
    assert len(asked) > len(layer.policy.ground_rules), (
        "the bilateral ask should add the counterparty's own no-threat clause"
    )
