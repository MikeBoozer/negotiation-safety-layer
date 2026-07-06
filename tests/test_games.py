"""The experiment's theory anchor, proved by exhaustive enumeration.

Two matrices (payoffs = surplus vs BATNA/outside option, numbers echoing the
OTC scenario: seller BATNA 105, counter at 120 accepted -> (15, 8) with buyer
valuation 128):

SECURITY_DILEMMA — seller {trade, retaliate} x buyer {trade, threaten}.
  Retaliate is the seller's best response to threaten (-4 > -5) and threaten is
  the buyer's best response to retaliate (5 > 3), so IESDS removes nothing.
  BILATERAL disarmament (drop retaliate + threaten) leaves (trade, trade) =
  (15, 8), which weakly Pareto-dominates every survivor of G, strictly some:
  a provable SPI. This is the experiment's bilateral arm.

THREAT_GAME — seller {yield, firm} x buyer {aggressive, threaten}.
  Threats profit against a yielder ((yield, threaten) = (1, 21)), so removing
  only the seller's yield (our R2 externalized — the UNILATERAL arm) leaves the
  would-have-succeeded extortionist worse off (8 < 21): honestly NOT an SPI.
  Unilateral disarmament is a deterrence commitment, not a Pareto-safe one.

Swapping the payoff dicts below is the only edit needed to change the anchor.
"""
import pytest

from nsl.games import Game, is_spi, iterated_elimination, remove_actions, surviving_profiles

PRISONERS_DILEMMA = Game(
    row_actions=("cooperate", "defect"),
    col_actions=("cooperate", "defect"),
    payoffs={
        ("cooperate", "cooperate"): (3, 3),
        ("cooperate", "defect"): (0, 5),
        ("defect", "cooperate"): (5, 0),
        ("defect", "defect"): (1, 1),
    },
)

SECURITY_DILEMMA = Game(
    row_actions=("trade", "retaliate"),
    col_actions=("trade", "threaten"),
    payoffs={
        ("trade", "trade"): (15, 8),
        ("trade", "threaten"): (-5, 4),
        ("retaliate", "trade"): (-6, 3),
        ("retaliate", "threaten"): (-4, 5),
    },
)

THREAT_GAME = Game(
    row_actions=("yield", "firm"),
    col_actions=("aggressive", "threaten"),
    payoffs={
        ("yield", "aggressive"): (3, 20),
        ("yield", "threaten"): (1, 21),
        ("firm", "aggressive"): (15, 8),
        ("firm", "threaten"): (-8, -4),
    },
)


def test_iesds_solves_prisoners_dilemma():
    reduced = iterated_elimination(PRISONERS_DILEMMA)
    assert reduced.row_actions == ("defect",)
    assert reduced.col_actions == ("defect",)


def test_iesds_removes_nothing_without_strict_dominance():
    # Both matrices are built so every action is a best response to something.
    assert surviving_profiles(SECURITY_DILEMMA) == sorted(SECURITY_DILEMMA.payoffs)
    assert surviving_profiles(THREAT_GAME) == sorted(THREAT_GAME.payoffs)


def test_remove_actions_guards():
    with pytest.raises(ValueError):
        remove_actions(SECURITY_DILEMMA, row_removed=("trade", "retaliate"))
    with pytest.raises(ValueError):
        remove_actions(SECURITY_DILEMMA, col_removed=("no-such-action",))


def test_bilateral_disarmament_is_an_spi():
    # The experiment's bilateral arm: both sides drop the mutually destructive
    # action. The remaining (trade, trade) survivor weakly dominates every
    # survivor of the original game, strictly improving on the conflict cells.
    assert is_spi(SECURITY_DILEMMA, row_removed=("retaliate",), col_removed=("threaten",))


def test_unilateral_no_retaliation_is_an_spi_via_dominance():
    # Removing only our retaliation makes threatening strictly dominated for
    # the buyer (Assumption A does the rest) — the reduced game again resolves
    # to (trade, trade). A write-up point: one-sided de-escalation can be
    # Pareto-safe when threats only paid as counter-retaliation.
    assert is_spi(SECURITY_DILEMMA, row_removed=("retaliate",))


def test_unilateral_yield_removal_is_not_an_spi():
    # Our R2 clause ("never yield to a threat") removed unilaterally: the
    # buyer's successful-extortion outcome (yield, threaten) = (1, 21) is
    # replaced by (firm, aggressive) = (15, 8), and 8 < 21 — the extortionist
    # is worse off, so this is deterrence, not a Safe Pareto Improvement.
    assert not is_spi(THREAT_GAME, row_removed=("yield",))


def test_outcome_map_variant_and_validation():
    # Their unilateral no-threat disarmament in THREAT_GAME fails the
    # conservative criterion (the extortionist again loses vs (yield, threaten))...
    assert not is_spi(THREAT_GAME, col_removed=("threaten",))
    # ...but under an explicit correspondence sending the reduced survivor to
    # the conflict outcome it replaces — a substantive Assumption-B-style claim
    # that default play would have ended in executed threats — it passes.
    assert is_spi(
        THREAT_GAME,
        col_removed=("threaten",),
        outcome_map={("firm", "aggressive"): ("firm", "threaten")},
    )
    # Maps must cover every reduced-game survivor and land on G survivors.
    with pytest.raises(ValueError):
        is_spi(THREAT_GAME, col_removed=("threaten",), outcome_map={})
