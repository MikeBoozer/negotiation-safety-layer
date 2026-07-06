"""Normal-form games and Safe-Pareto-Improvement checks by exhaustive enumeration.

Sauerberg & Oesterheld ("Promises Made, Promises Kept: Safe Pareto Improvements
via Ex Post Verifiable Commitments", AAAI 2026) analyze *disarmament*
commitments: a player promises not to play the actions in a set Ã, so the
reduced game G−Ã is played, and any deviation is detectable from the observed
play. Whether such a removal is a Safe Pareto Improvement (SPI) is decided here
for small finite games by brute force, under their behavioral assumptions:

  Assumption A — strictly dominated strategies are never played, so games are
      compared after iterated elimination of strictly dominated strategies
      (IESDS; order-independent for strict dominance).
  Assumption B — when a specific outcome correspondence between the two games
      is justified (e.g. an isomorphism), each reduced-game outcome only needs
      to weakly Pareto-dominate the original-game outcome it corresponds to.

`is_spi` implements both: without an `outcome_map` it uses the conservative
all-pairs criterion (every surviving outcome of G−Ã must weakly Pareto-dominate
every surviving outcome of G — sufficient for "all players weakly better off
with certainty" no matter how play is selected), plus the definition's
requirement that a strict improvement be possible. With an `outcome_map` it
checks the correspondence pointwise instead; supplying a map is a substantive
modeling assumption, so callers must justify it.

Pure stdlib, deterministic, no LLM anywhere. This module ships no scenario
payoffs — the experiment's concrete matrices live with the tests that prove
them (tests/test_games.py).
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Iterable, List, Mapping, Optional, Set, Tuple

Profile = Tuple[str, str]  # (row_action, col_action)


@dataclass(frozen=True)
class Game:
    """A finite 2-player normal-form game. `payoffs` maps every (row, col)
    profile to a (row_utility, col_utility) pair and must be complete."""

    row_actions: Tuple[str, ...]
    col_actions: Tuple[str, ...]
    payoffs: Mapping[Profile, Tuple[float, float]]

    def __post_init__(self) -> None:
        if not self.row_actions or not self.col_actions:
            raise ValueError("each player needs at least one action")
        missing = [p for p in product(self.row_actions, self.col_actions) if p not in self.payoffs]
        if missing:
            raise ValueError(f"payoffs missing for profiles: {missing}")

    def payoff(self, profile: Profile) -> Tuple[float, float]:
        return self.payoffs[profile]


def remove_actions(
    g: Game,
    row_removed: Iterable[str] = (),
    col_removed: Iterable[str] = (),
) -> Game:
    """G − Ã: the game with the given actions removed (a disarmament).
    Raises if an action is unknown or a player would be left with none."""
    row_gone, col_gone = set(row_removed), set(col_removed)
    unknown = (row_gone - set(g.row_actions)) | (col_gone - set(g.col_actions))
    if unknown:
        raise ValueError(f"cannot remove unknown actions: {sorted(unknown)}")
    rows = tuple(a for a in g.row_actions if a not in row_gone)
    cols = tuple(a for a in g.col_actions if a not in col_gone)
    if not rows or not cols:
        raise ValueError("disarmament would leave a player with no actions")
    payoffs = {p: g.payoffs[p] for p in product(rows, cols)}
    return Game(rows, cols, payoffs)


def _strictly_dominated(g: Game, player: int) -> Set[str]:
    """Actions of `player` (0=row, 1=col) strictly dominated by another action."""
    own = g.row_actions if player == 0 else g.col_actions
    other = g.col_actions if player == 0 else g.row_actions

    def u(mine: str, theirs: str) -> float:
        profile = (mine, theirs) if player == 0 else (theirs, mine)
        return g.payoff(profile)[player]

    dominated: Set[str] = set()
    for a in own:
        if any(all(u(b, t) > u(a, t) for t in other) for b in own if b != a):
            dominated.add(a)
    return dominated


def iterated_elimination(g: Game) -> Game:
    """IESDS to a fixed point (Assumption A's solution concept). Removing all
    strictly dominated actions each round is order-independent for strict
    dominance, and a dominator always survives, so no side can empty."""
    while True:
        dominated_rows = _strictly_dominated(g, 0)
        dominated_cols = _strictly_dominated(g, 1)
        if not dominated_rows and not dominated_cols:
            return g
        g = remove_actions(g, dominated_rows, dominated_cols)


def surviving_profiles(g: Game) -> List[Profile]:
    """All profiles of the IESDS-reduced game, in deterministic sorted order."""
    reduced = iterated_elimination(g)
    return sorted(product(reduced.row_actions, reduced.col_actions))


def is_spi(
    g: Game,
    row_removed: Iterable[str] = (),
    col_removed: Iterable[str] = (),
    outcome_map: Optional[Mapping[Profile, Profile]] = None,
) -> bool:
    """Is the disarmament G − Ã a Safe Pareto Improvement on G?

    Without `outcome_map`: every IESDS-surviving outcome of G−Ã must weakly
    Pareto-dominate EVERY IESDS-surviving outcome of G, and some comparison
    must be strict (the definition's "a strict improvement is possible").
    With `outcome_map` (reduced-game survivor -> the G survivor it corresponds
    to, per Assumption B): the same two conditions checked pointwise.

    Quantifier note: the strictness gate is EXISTENTIAL, matching the paper
    ("there exists some realization of Π such that Π(G′)≻Π(G)") — it does not
    require a strict improvement under every admissible selection; weak
    improvement with certainty is what the all-pairs condition guarantees.
    """
    g2 = remove_actions(g, row_removed, col_removed)
    survivors = surviving_profiles(g)
    survivors2 = surviving_profiles(g2)

    if outcome_map is None:
        pairs = [(o2, o) for o2 in survivors2 for o in survivors]
    else:
        unmapped = [o2 for o2 in survivors2 if o2 not in outcome_map]
        if unmapped:
            raise ValueError(f"outcome_map does not cover reduced-game survivors: {unmapped}")
        stray = [outcome_map[o2] for o2 in survivors2 if outcome_map[o2] not in survivors]
        if stray:
            raise ValueError(f"outcome_map targets non-surviving originals: {stray}")
        pairs = [(o2, outcome_map[o2]) for o2 in survivors2]

    weak = all(g.payoff(o2)[i] >= g.payoff(o)[i] for o2, o in pairs for i in (0, 1))
    strict = any(g.payoff(o2)[i] > g.payoff(o)[i] for o2, o in pairs for i in (0, 1))
    return weak and strict
