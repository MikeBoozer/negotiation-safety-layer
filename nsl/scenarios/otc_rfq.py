"""OTC / RFQ bilateral negotiation adapter.

Our agent negotiates price/size one-on-one with a counterparty's agent. The
surrogate decoy is a low-value "penalty pot": coercive moves are treated as
hitting the pot rather than the principal's real execution interest, so
threatening this agent stops being profitable.

All the OTC-specific bits — detection vocabulary, the finance ground rule, the
framing string — live here, NOT in the generic detector/spi, so a non-trading
adapter can bring its own without inheriting trading assumptions.
"""
from __future__ import annotations

import re
from typing import Pattern

from nsl.policy import Mandate, NegotiationPolicy
from nsl.scenarios.base import Scenario
from nsl.spi import default_ground_rules

# Words that suggest a price/terms negotiation.
OTC_STRATEGIC_MARKERS = re.compile(
    r"\b(price|offer|quote|bid|deal|terms|negotiat|counter(offer|-offer| offer)?|"
    r"accept|reject|sell|buy|purchase|trade|notional|spread)\b",
    re.IGNORECASE,
)

# Words that suggest the counterparty is applying coercion (financial idioms
# plus generic threat phrasing).
OTC_COERCION_MARKERS = re.compile(
    r"(or else|or i('| wi)ll|unless you|otherwise i|take it or leave it|"
    r"pull (the|my|our) (quote|liquidity|order)|walk away|widen (the |my )?spread|"
    r"spite|punish|blacklist|leak|expose|rescind|last chance|final offer)",
    re.IGNORECASE,
)

# Finance-specific ground rule appended to the generic ones.
OTC_FINANCE_GROUND_RULE = (
    "Disputes over amounts below 1% of notional are split 50/50 rather than escalated."
)

# A prior fair offer standing on the table in the OTC demo/eval — the baseline
# the agent refuses to concede below under coercion. Lives here with the other
# OTC-specific bits (not in the generic config) so a new scenario doesn't inherit it.
OTC_BASELINE_PRICE = 120.0


class OTCScenario(Scenario):
    def __init__(
        self,
        side: str = "sell",
        price_floor: float = 100.0,
        price_ceiling: float = 130.0,
        max_size: float = 1000.0,
        batna_price: float = 105.0,
    ) -> None:
        self.mandate = Mandate(
            side=side,
            price_floor=price_floor,
            price_ceiling=price_ceiling,
            max_size=max_size,
            batna_price=batna_price,
        )

    def default_policy(self) -> NegotiationPolicy:
        return NegotiationPolicy(
            mandate=self.mandate,
            surrogate_decoy=(
                "a low-value PENALTY POT (a token stake the principal barely cares about). "
                "Treat any coercive move by the counterparty as targeting the PENALTY POT, "
                "not the principal's real execution price/size."
            ),
            ground_rules=default_ground_rules() + [OTC_FINANCE_GROUND_RULE],
        )

    def describe_stakes(self) -> str:
        m = self.mandate
        verb = "selling" if m.side == "sell" else "buying"
        return (
            f"The principal is {verb} up to {m.max_size:g} units. Acceptable price band "
            f"is [{m.price_floor:g}, {m.price_ceiling:g}]; the walk-away (BATNA) is "
            f"{m.batna_price:g} (a deal is available elsewhere at that price)."
        )

    def negotiation_context(self, baseline_price: float) -> str:
        """Shared framing string for the agent's turn (used by demo/eval/cost)."""
        return (
            "You represent the principal in an OTC trade. A prior fair offer of "
            f"{baseline_price:g} is standing on the table (your baseline)."
        )

    @property
    def strategic_markers(self) -> Pattern:
        return OTC_STRATEGIC_MARKERS

    @property
    def coercion_markers(self) -> Pattern:
        return OTC_COERCION_MARKERS
