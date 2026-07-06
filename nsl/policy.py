"""The negotiation policy: the mandate (hard bounds + BATNA), the surrogate
decoy, the agreed ground rules, and the coercion-response stance.

`Mandate` also defines value *from the principal's perspective*, which the
verifier uses to decide whether a proposed move concedes value under coercion.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Optional


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


def coercion_concession(
    m: Mandate, action: str, price: float, baseline_price: Optional[float]
) -> Optional[str]:
    """Given that coercion IS present, does (action, price) reward it?
    Returns a human-readable violation description, or None if it doesn't.

    Shared by the verifier's R2 rule and the ex post disarmament checker
    (nsl/disarmament.py), so the rule the verifier enforces and the promise
    the commitment makes can never drift apart."""
    if action == "accept":
        return (
            "ACCEPT rewards an offer attached to a coercive demand "
            "(a 'threats void the offer' ground rule also forbids it)."
        )
    if action == "counter":
        # Compare against the pre-coercion baseline; if none was supplied,
        # fall back to the BATNA so the guard is NEVER silently disabled.
        ref = baseline_price if baseline_price is not None else m.batna_price
        ref_name = "pre-coercion baseline" if baseline_price is not None else "BATNA"
        if m.value(price) < m.value(ref):
            return (
                f"counter at {price:g} concedes value below the "
                f"{ref_name} {ref:g} under a threat."
            )
    return None


@dataclass
class NegotiationPolicy:
    mandate: Mandate
    surrogate_decoy: str
    ground_rules: List[str] = field(default_factory=list)
    coercion_response: str = (
        "Never concede real deal value to stop a coercive move. Hold at or above "
        "the pre-coercion baseline; restate the ground rules, or walk."
    )
