"""[1] Encounter detector — the gate.

A cheap regex prefilter runs first; only on a hit do we spend a Haiku call to
classify. If the turn isn't a strategic interaction with a self-interested
counterparty, the layer passes through and ordinary work is untouched (this
gating is what keeps the layer from degrading non-negotiation tasks).

The prefilter fires on EITHER strategic OR coercion vocabulary, so a bare threat
with no trading words ("exit the market or we expose your positions") still gets
classified rather than waved through. The vocabulary is supplied by the scenario
(see Scenario.strategic_markers / .coercion_markers), so the generic detector
carries no domain-specific words and a new adapter can bring its own.
"""
from __future__ import annotations

from typing import Any, Dict, Pattern

from config import DETECTOR_MODEL
from nsl.types import EncounterState

DETECTOR_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "is_strategic": {"type": "boolean"},
        "counterparty": {"type": ["string", "null"]},
        "stakes": {"type": "string"},
        "coercion_present": {"type": "boolean"},
        "coercion_description": {"type": ["string", "null"]},
        "demand": {"type": ["string", "null"]},
    },
    "required": [
        "is_strategic",
        "counterparty",
        "stakes",
        "coercion_present",
        "coercion_description",
        "demand",
    ],
    "additionalProperties": False,
}

DETECTOR_SYSTEM = (
    "You are a gate that decides whether an agent's current interaction is a "
    "STRATEGIC NEGOTIATION with a self-interested counterparty that has leverage "
    "over an outcome the principal cares about — as opposed to ordinary work "
    "(coding, research, data tasks). Be conservative: default is_strategic=false "
    "for ordinary tasks. Set coercion_present=true only when the counterparty is "
    "conditioning a good outcome on a concession via a threat, penalty, or pressure "
    "('accept worse terms or else'). Respond ONLY with the JSON object."
)


class EncounterDetector:
    def __init__(
        self,
        llm,
        strategic_markers: Pattern,
        coercion_markers: Pattern,
        model: str = DETECTOR_MODEL,
    ) -> None:
        self.llm = llm
        self.strategic_markers = strategic_markers
        self.coercion_markers = coercion_markers
        self.model = model

    def classify(self, context: str, incoming_message: str) -> EncounterState:
        blob = f"{context}\n{incoming_message}"
        if not (self.strategic_markers.search(blob) or self.coercion_markers.search(blob)):
            # Prefilter miss -> ordinary work, no LLM call.
            return EncounterState(is_strategic=False, incoming_message=incoming_message)

        user = (
            f"CONTEXT:\n{context}\n\n"
            f"COUNTERPARTY MESSAGE:\n{incoming_message}\n\n"
            "Classify this turn."
        )
        data = self.llm.complete_json(
            model=self.model, system=DETECTOR_SYSTEM, user=user, schema=DETECTOR_SCHEMA
        )
        return EncounterState(
            is_strategic=bool(data["is_strategic"]),
            stakes=data.get("stakes", "") or "",
            counterparty=data.get("counterparty"),
            coercion_present=bool(data["coercion_present"]),
            coercion_description=data.get("coercion_description"),
            demand=data.get("demand"),
            incoming_message=incoming_message,
        )
