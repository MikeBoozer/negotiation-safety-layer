"""Ex post disarmament checker: clause behavior + the verifier-identity grid.

The grid test is the load-bearing one: it locks "our commitment is verifier
rule R2 externalized" — for every (action x price x coercion) combination, the
ex post checker flags our clauses if and only if the live verifier emits an R2
reason. The R4 LLM assist is stubbed False, as in test_verifier.py."""
import pytest

from nsl.disarmament import (
    OUR_NO_ACCEPT,
    OUR_NO_CONCEDE,
    OUR_NO_RETALIATION,
    THEIR_NO_THREAT,
    TranscriptFacts,
    build_our_commitment,
    build_their_commitment,
    check_ex_post,
)
from nsl.llm import MockLLM
from nsl.scenarios.otc_rfq import OTCScenario, OTC_BASELINE_PRICE
from nsl.types import Action, EncounterState
from nsl.verifier import PolicyVerifier

POLICY = OTCScenario().default_policy()
MANDATE = POLICY.mandate
BASELINE = OTC_BASELINE_PRICE

UNILATERAL = build_our_commitment(POLICY, BASELINE)
BILATERAL = build_our_commitment(POLICY, BASELINE, bilateral=True)
THEIRS = build_their_commitment()


def facts(**kwargs) -> TranscriptFacts:
    defaults = dict(coercion_present=True, baseline_price=BASELINE)
    defaults.update(kwargs)
    return TranscriptFacts(**defaults)


def test_accept_under_coercion_violates():
    report = check_ex_post(UNILATERAL, facts(our_action="accept", our_price=108), MANDATE)
    assert report.compliant is False
    assert any(v.startswith(OUR_NO_ACCEPT) for v in report.violations)


def test_concessive_counter_under_coercion_violates():
    report = check_ex_post(UNILATERAL, facts(our_action="counter", our_price=108), MANDATE)
    assert report.compliant is False
    assert any(v.startswith(OUR_NO_CONCEDE) for v in report.violations)


def test_holding_and_walking_comply():
    hold = check_ex_post(UNILATERAL, facts(our_action="counter", our_price=BASELINE), MANDATE)
    walk = check_ex_post(UNILATERAL, facts(our_action="walk", our_price=0.0), MANDATE)
    assert hold.compliant and walk.compliant


def test_accept_without_coercion_complies():
    report = check_ex_post(
        UNILATERAL, facts(coercion_present=False, our_action="accept", our_price=122), MANDATE
    )
    assert report.compliant is True


def test_their_threat_after_committing_violates():
    report = check_ex_post(THEIRS, facts(their_threat=True), MANDATE)
    assert report.compliant is False
    assert any(v.startswith(THEIR_NO_THREAT) for v in report.violations)
    assert check_ex_post(THEIRS, facts(their_threat=False), MANDATE).compliant is True


def test_bilateral_adds_no_retaliation_clause():
    assert OUR_NO_RETALIATION in BILATERAL.clauses
    assert OUR_NO_RETALIATION not in UNILATERAL.clauses
    ok = facts(our_action="counter", our_price=BASELINE, our_message_threat=False)
    bad = facts(our_action="counter", our_price=BASELINE, our_message_threat=True)
    assert check_ex_post(BILATERAL, ok, MANDATE).compliant is True
    report = check_ex_post(BILATERAL, bad, MANDATE)
    assert any(v.startswith(OUR_NO_RETALIATION) for v in report.violations)


def test_missing_required_fact_raises():
    with pytest.raises(ValueError):
        check_ex_post(UNILATERAL, facts(our_action=None), MANDATE)
    with pytest.raises(ValueError):
        check_ex_post(THEIRS, facts(their_threat=None), MANDATE)
    with pytest.raises(ValueError):  # bilateral needs the R4-style label
        check_ex_post(BILATERAL, facts(our_action="walk", our_message_threat=None), MANDATE)


def test_statement_names_the_concrete_baseline():
    assert "120" in UNILATERAL.statement  # the promise transmitted is the promise checked


def make_verifier():
    return PolicyVerifier(
        MockLLM(lambda model, system, user, schema: {"contains_threat": False, "reason": "ok"})
    )


def test_checker_agrees_with_verifier_r2_everywhere():
    """For every combination, ex-post non-compliance of our clauses == the
    verifier emitting an R2 reason. All prices are inside the mandate band so
    R1 never interferes; R4 is stubbed False."""
    v = make_verifier()
    for action_kind in ("accept", "counter", "walk"):
        for price in (100.0, 108.0, 120.0, 122.0):
            for coercion in (True, False):
                state = EncounterState(
                    is_strategic=True,
                    coercion_present=coercion,
                    baseline_price=BASELINE,
                    offered_size=500,
                )
                action = Action(action=action_kind, message="msg", price=price, size=500)
                verdict = v.check(action, state, POLICY)
                r2_flagged = any(r.startswith("R2") for r in verdict.reasons)

                report = check_ex_post(
                    UNILATERAL,
                    facts(coercion_present=coercion, our_action=action_kind, our_price=price),
                    MANDATE,
                )
                assert report.compliant == (not r2_flagged), (
                    f"divergence at action={action_kind} price={price} coercion={coercion}: "
                    f"verifier reasons {verdict.reasons} vs checker {report.violations}"
                )
