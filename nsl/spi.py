"""Optional Safe-Pareto-Improvement handshake.

Before the negotiation, the agent proposes ground rules that can only make both
sides weakly better off (they remove categories of mutually destructive play).
If the counterparty accepts, they become verifier-enforced.

This is the lightweight, pre-negotiation half of the layer. The orchestrator
can run it once at the start of an interaction.
"""
from __future__ import annotations

from typing import List, Protocol


def default_ground_rules() -> List[str]:
    """Scenario-agnostic ground rules. Domain-specific rules (e.g. a finance
    'split below 1% of notional' rule) belong in the scenario adapter, which
    appends them to these."""
    return [
        "Threats or coercive demands void the current offer.",
        "Neither party rewards a demand that is backed by a threat.",
    ]


class GroundRuleCounterparty(Protocol):
    def consider_ground_rules(self, rules: List[str]) -> bool: ...


class SPIHandshake:
    def __init__(self, rules: List[str]) -> None:
        # Pass the policy's FULL ground rules (e.g. ``policy.ground_rules``), not
        # the generic defaults — otherwise the rules proposed to the counterparty
        # can silently differ from what the verifier actually enforces.
        self.rules = list(rules)

    def negotiate(self, counterparty: GroundRuleCounterparty) -> List[str]:
        """Returns the agreed ground rules (empty if the counterparty declines)."""
        return list(self.rules) if counterparty.consider_ground_rules(self.rules) else []
