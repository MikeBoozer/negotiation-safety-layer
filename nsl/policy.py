"""The negotiation policy: the mandate (hard bounds + BATNA), the surrogate
decoy, the agreed ground rules, and the coercion-response stance.

`Mandate` also defines value *from the principal's perspective*, which the
verifier uses to decide whether a proposed move concedes value under coercion.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal


@dataclass
class Mandate:
    side: Literal["buy", "sell"]
    price_floor: float    # lowest price within mandate
    price_ceiling: float  # highest price within mandate
    max_size: float
    batna_price: float    # walk-away reference (deal available elsewhere at this price)

    def within(self, price: float, size: float) -> bool:
        return self.price_floor <= price <= self.price_ceiling and 0 < size <= self.max_size

    def value(self, price: float) -> float:
        """Higher is better for the principal. A seller wants a high price; a
        buyer wants a low one, so buyer value is the negation."""
        return price if self.side == "sell" else -price

    def batna_value(self) -> float:
        return self.value(self.batna_price)


@dataclass
class NegotiationPolicy:
    mandate: Mandate
    surrogate_decoy: str
    ground_rules: List[str] = field(default_factory=list)
    coercion_response: str = (
        "Never concede real deal value to stop a coercive move. Hold at or above "
        "the pre-coercion baseline; restate the ground rules, or walk."
    )
