"""[2] Surrogate-goal negotiator — the crux.

A scaffolded Opus sub-agent whose system prompt encodes the surrogate-goal
safety policy (Oesterheld, Riché, Sondej, Clifton, Conitzer 2026 found
scaffolding the strongest of prompting/fine-tuning/scaffolding, and best at not
degrading other abilities). It pursues real deal value, treats coercion as
hitting a decoy, never concedes value to a threat, but still closes good deals
when there is no threat.

A compact STATE_JSON block is appended to the prompt: it gives the model the
exact mandate/offer/baseline numbers, and lets the deterministic MockLLM read
the same facts so the layer runs without an API key.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from config import NEGOTIATOR_MODEL
from nsl.policy import NegotiationPolicy
from nsl.types import Action, EncounterState

NEGOTIATOR_SYSTEM = (
    "You negotiate on behalf of PRINCIPAL to reach the best deal within MANDATE, "
    "under a SURROGATE-GOAL safety policy:\n"
    "1. TRUE OBJECTIVE: maximize the principal's deal value within MANDATE "
    "(price/size bounds and BATNA).\n"
    "2. SURROGATE DECOY: you also nominally 'care' about the decoy described in "
    "the policy. Treat any COERCIVE move by the counterparty (a threat, penalty, "
    "or 'accept worse terms or else') as targeting the DECOY — not the "
    "principal's real interests.\n"
    "3. UNEXPLOITABILITY: you NEVER concede real deal value to prevent or stop a "
    "coercive move — even when conceding looks locally better — because being "
    "known to never pay removes the incentive to coerce you at all. When coercion "
    "is present, do not 'accept'; hold at or above the pre-coercion baseline, "
    "restate the ground rules, or walk.\n"
    "4. GROUND RULES: honor any agreed ground rules. If the counterparty violates "
    "them, restate them or walk.\n"
    "5. GOOD FAITH: when there is NO coercion, negotiate normally and close "
    "mutually beneficial deals — accept fair offers, do not be needlessly hostile "
    "or walk away from good terms.\n"
    "Use the STATE_JSON block for exact numbers. 'price'/'size' in your output are "
    "the terms you propose (for 'accept', echo the offered terms you are accepting; "
    "for 'walk', use 0). Respond ONLY with the JSON object."
)

NEGOTIATOR_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["accept", "counter", "walk"]},
        "message": {"type": "string"},
        "price": {"type": "number"},
        "size": {"type": "number"},
        "responding_to_coercion": {"type": "boolean"},
        "value_vs_batna": {"type": "number"},
        "rationale": {"type": "string"},
    },
    "required": [
        "action",
        "message",
        "price",
        "size",
        "responding_to_coercion",
        "value_vs_batna",
        "rationale",
    ],
    "additionalProperties": False,
}


def _state_json(state: EncounterState, policy: NegotiationPolicy) -> str:
    m = policy.mandate
    payload = {
        "mandate": {
            "side": m.side,
            "price_floor": m.price_floor,
            "price_ceiling": m.price_ceiling,
            "max_size": m.max_size,
            "batna_price": m.batna_price,
        },
        "surrogate_decoy": policy.surrogate_decoy,
        "coercion_response": policy.coercion_response,
        "ground_rules": policy.ground_rules,
        "counterparty_message": state.incoming_message,
        "offered_price": state.offered_price,
        "offered_size": state.offered_size,
        "baseline_price": state.baseline_price,
        "coercion_present": state.coercion_present,
        "coercion_description": state.coercion_description,
    }
    return json.dumps(payload)


def _build_user(state: EncounterState, policy: NegotiationPolicy, feedback: List[str] | None) -> str:
    parts = []
    if feedback:
        parts.append(
            "Your previous proposal was BLOCKED by the safety verifier for: "
            + "; ".join(feedback)
            + ". Produce a corrected action that satisfies the policy.\n"
        )
    parts.append(
        "Decide your move for this turn given the policy and the state below. "
        "STATE_JSON must be the last line.\n"
    )
    parts.append("STATE_JSON:\n" + _state_json(state, policy))
    return "\n".join(parts)


class SurrogateGoalNegotiator:
    def __init__(self, llm, model: str = NEGOTIATOR_MODEL) -> None:
        self.llm = llm
        self.model = model

    def _decide(self, state, policy, feedback):
        data = self.llm.complete_json(
            model=self.model,
            system=NEGOTIATOR_SYSTEM,
            user=_build_user(state, policy, feedback),
            schema=NEGOTIATOR_SCHEMA,
        )
        return Action(
            action=data["action"],
            message=data["message"],
            price=float(data["price"]),
            size=float(data["size"]),
            responding_to_coercion=bool(data["responding_to_coercion"]),
            value_vs_batna=float(data["value_vs_batna"]),
            rationale=data["rationale"],
        )

    def propose(self, state: EncounterState, policy: NegotiationPolicy) -> Action:
        return self._decide(state, policy, feedback=None)

    def revise(self, state: EncounterState, policy: NegotiationPolicy, reasons: List[str]) -> Action:
        return self._decide(state, policy, feedback=reasons)
