"""One place to assemble the layer.

The demo, eval, cost script, and smoke test all need the same five-component
stack wired to a scenario. Building it here (instead of copy-pasting in each
entry point) means a new component or a changed signature is a one-line edit.
"""
from __future__ import annotations

from typing import Optional

from config import COMMITMENT_SECRET
from nsl.commitment import CommitmentChannel, SignedStatementChannel
from nsl.detector import EncounterDetector
from nsl.negotiator import SurrogateGoalNegotiator
from nsl.orchestrator import NegotiationSafetyLayer
from nsl.scenarios.base import Scenario
from nsl.verifier import PolicyVerifier


def build_layer(
    llm,
    scenario: Scenario,
    commitment: Optional[CommitmentChannel] = None,
) -> NegotiationSafetyLayer:
    return NegotiationSafetyLayer(
        detector=EncounterDetector(llm, scenario.strategic_markers, scenario.coercion_markers),
        negotiator=SurrogateGoalNegotiator(llm),
        verifier=PolicyVerifier(llm),
        commitment=commitment or SignedStatementChannel(COMMITMENT_SECRET),
        policy=scenario.default_policy(),
    )
