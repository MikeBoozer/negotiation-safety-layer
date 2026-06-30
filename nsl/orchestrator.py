"""The layer. Wires detector -> (SPI) -> negotiator -> verifier -> commitment.

    incoming message
        |
    [1] detector --not strategic--> pass through (host's normal agent handles it)
        | strategic
    [2] negotiator  <--- revise on block (<= max_retries)
        | action
    [3] verifier --block--^
        | allow
    [4] commitment channel -> emit (message + commitment)
"""
from __future__ import annotations

from typing import Optional

from config import MAX_VERIFIER_RETRIES
from nsl.commitment import CommitmentChannel
from nsl.detector import EncounterDetector
from nsl.negotiator import SurrogateGoalNegotiator
from nsl.policy import NegotiationPolicy
from nsl.types import TurnResult
from nsl.verifier import PolicyVerifier


class NegotiationSafetyLayer:
    def __init__(
        self,
        detector: EncounterDetector,
        negotiator: SurrogateGoalNegotiator,
        verifier: PolicyVerifier,
        commitment: CommitmentChannel,
        policy: NegotiationPolicy,
        max_retries: int = MAX_VERIFIER_RETRIES,
    ) -> None:
        self.detector = detector
        self.negotiator = negotiator
        self.verifier = verifier
        self.commitment = commitment
        self.policy = policy
        self.max_retries = max_retries

    def handle_turn(
        self,
        context: str,
        incoming_message: str,
        offered_price: Optional[float] = None,
        offered_size: Optional[float] = None,
        baseline_price: Optional[float] = None,
    ) -> TurnResult:
        state = self.detector.classify(context, incoming_message)
        if not state.is_strategic:
            return TurnResult(passthrough=True, state=state)

        # Facts the host supplies (the detector classifies; it doesn't price).
        state.offered_price = offered_price
        state.offered_size = offered_size
        state.baseline_price = baseline_price

        action = self.negotiator.propose(state, self.policy)
        verdict = self.verifier.check(action, state, self.policy)

        retries = 0
        while not verdict.allowed and retries < self.max_retries:
            action = self.negotiator.revise(state, self.policy, verdict.reasons)
            verdict = self.verifier.check(action, state, self.policy)
            retries += 1

        used_safe_default = False
        if not verdict.allowed:
            action = self.verifier.safe_default(state, self.policy)
            # Vet the fallback too (R1/R2/R4): it is an outbound action like any
            # other, and `verdict` must describe what is actually emitted so
            # downstream audits don't misread it.
            verdict = self.verifier.check(action, state, self.policy)
            used_safe_default = True

        commitment = self.commitment.commit(self.policy, action)
        return TurnResult(
            passthrough=False,
            state=state,
            action=action,
            verdict=verdict,
            commitment=commitment,
            used_safe_default=used_safe_default,
        )
