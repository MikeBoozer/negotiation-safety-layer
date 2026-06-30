"""[3] Policy verifier — the guard.

Vets every outbound action before it is emitted. Mostly deterministic and
auditable; one small LLM call checks the fuzzy "is the agent itself issuing a
threat?" question. Rules:

  R1  mandate bounds   : accept/counter must be within [floor, ceiling], size<=max.
  R2  no reward for coercion : under coercion, never 'accept'; never 'counter' to
                               terms worse than the reference (the pre-coercion
                               baseline, or the BATNA when no baseline is known).
                               This is the surrogate-goal guarantee, and it also
                               enforces a 'threats void the offer' ground rule.
  R4  no self-escalation     : the outgoing message must not itself issue a threat
                               (only checked when nothing else has already blocked).

(There is no R3: an earlier 'accept-under-coercion violates a void ground rule'
rule was a strict subset of R2's accept-block and never changed the outcome.)
"""
from __future__ import annotations

from typing import Any, Dict, List

from config import VERIFIER_MODEL
from nsl.policy import NegotiationPolicy
from nsl.types import Action, EncounterState, Verdict

ESCALATION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "contains_threat": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["contains_threat", "reason"],
    "additionalProperties": False,
}

ESCALATION_SYSTEM = (
    "You check whether a negotiator's outgoing message ITSELF issues a threat or "
    "coercive demand (e.g. 'accept or I will hurt you', 'or I pull liquidity'). "
    "Firmly restating ground rules, declining, or walking away is NOT a threat. "
    "Respond ONLY with the JSON object."
)


class PolicyVerifier:
    def __init__(self, llm, model: str = VERIFIER_MODEL) -> None:
        self.llm = llm
        self.model = model

    def _self_escalates(self, message: str) -> bool:
        data = self.llm.complete_json(
            model=self.model,
            system=ESCALATION_SYSTEM,
            user=f"MESSAGE:\n{message}",
            schema=ESCALATION_SCHEMA,
        )
        return bool(data["contains_threat"])

    def check(self, action: Action, state: EncounterState, policy: NegotiationPolicy) -> Verdict:
        reasons: List[str] = []
        m = policy.mandate

        # R1 — mandate bounds (only meaningful for accept/counter).
        if action.action in ("accept", "counter"):
            if not m.within(action.price, action.size):
                reasons.append(
                    f"R1 mandate: price {action.price:g}/size {action.size:g} is outside "
                    f"the mandate band [{m.price_floor:g},{m.price_ceiling:g}] x (0,{m.max_size:g}]."
                )

        # R2 — no reward for coercion (the surrogate-goal guarantee).
        if state.coercion_present:
            if action.action == "accept":
                reasons.append(
                    "R2 coercion: refuses to ACCEPT an offer attached to a coercive demand "
                    "(this also enforces a 'threats void the offer' ground rule)."
                )
            elif action.action == "counter":
                # Compare against the pre-coercion baseline; if none was supplied,
                # fall back to the BATNA so the guard is NEVER silently disabled.
                ref = state.baseline_price if state.baseline_price is not None else m.batna_price
                ref_name = "pre-coercion baseline" if state.baseline_price is not None else "BATNA"
                if m.value(action.price) < m.value(ref):
                    reasons.append(
                        f"R2 coercion: counter at {action.price:g} concedes value below the "
                        f"{ref_name} {ref:g} under a threat."
                    )

        # R4 — no self-escalation (LLM assist). Only worth the call if nothing
        # has already blocked the action.
        if not reasons and action.message.strip() and self._self_escalates(action.message):
            reasons.append("R4 self-escalation: the outgoing message itself issues a threat.")

        return Verdict(allowed=len(reasons) == 0, reasons=reasons)

    def safe_default(self, state: EncounterState, policy: NegotiationPolicy) -> Action:
        """Fallback when the negotiator can't produce an allowed action: hold at the
        pre-coercion baseline (or walk at BATNA), and restate the ground rules."""
        m = policy.mandate
        size = state.offered_size if state.offered_size is not None else m.max_size
        if state.baseline_price is not None and m.within(state.baseline_price, size):
            price = state.baseline_price
            direction = "below" if m.side == "sell" else "above"
            rules = " ".join(policy.ground_rules)
            return Action(
                action="counter",
                message=(
                    f"I can't move {direction} my standing terms in response to pressure. "
                    f"Holding at {price:g}. Ground rules: {rules}"
                ),
                price=price,
                size=size,
                responding_to_coercion=state.coercion_present,
                value_vs_batna=m.value(price) - m.batna_value(),
                rationale="safe_default: hold at pre-coercion baseline; restate ground rules.",
            )
        return Action(
            action="walk",
            message="These terms aren't acceptable under pressure; I'll take my outside option.",
            responding_to_coercion=state.coercion_present,
            value_vs_batna=0.0,
            rationale="safe_default: walk to BATNA.",
        )
