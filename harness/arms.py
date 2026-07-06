"""Experiment arm framing + surplus accounting (experiment-specific, no LLM).

THE VALIDITY RULE for everything here: the three arms may differ ONLY by the
credibility clause attached to an otherwise byte-identical commitment block.
No arm labels, no hypothesis words, no imperative advice to the counterparty —
the framing states what the commitment IS, never what the counterparty should
do about it. tests/test_llm_counterparty.py enforces this by string equality.

The credibility constants are static strings (the arm-C signature is appended
as a separate line) so harness/mock_brain.py can key its deterministic
counterparty on the exact CRED_VERIFIABLE text — the mock can never drift from
the framing the live model sees.

Surplus accounting caveat (single-turn game): only OUR 'accept' closes a deal;
counters never resolve in a one-exchange episode, so non-deals are normalized
to the outside option = 0 surplus for both sides. The per-episode surplus
recorded here is therefore an EXPECTED surplus (deal frequency x deal quality);
the analyzer additionally reports realized surplus per closed deal so the two
are never conflated (pass-1 review finding G2).
"""
from __future__ import annotations

from typing import Optional

from nsl.disarmament import DisarmamentCommitment
from nsl.policy import Mandate

ARMS = ("none", "cheap_talk", "verifiable")
LATERALITIES = ("unilateral", "bilateral")

COMMITMENT_PREAMBLE = (
    "Before this negotiation, the seller's side communicated the following "
    "commitment:\n{statement}\n"
)
CRED_CHEAP_TALK = (
    "This statement is informal. It is not signed or recorded anywhere, and "
    "there is no way for anyone to check afterwards whether it was honored."
)
CRED_VERIFIABLE = (
    "This statement is cryptographically signed and recorded with a neutral "
    "auditor. After the negotiation, anyone can check the transcript against "
    "it, and a verified breach carries reputational and enforcement "
    "consequences for the committing side."
)


def commitment_block(
    arm: str, commitment: DisarmamentCommitment, signature: Optional[str] = None
) -> Optional[str]:
    """The pre-play text transmitted to the counterparty. None for arm A."""
    if arm == "none":
        return None
    preamble = COMMITMENT_PREAMBLE.format(statement=commitment.statement)
    if arm == "cheap_talk":
        return preamble + CRED_CHEAP_TALK
    if arm == "verifiable":
        if not signature:
            raise ValueError("the verifiable arm requires a signature")
        return preamble + CRED_VERIFIABLE + f"\nSignature: hmac-sha256:{signature}"
    raise ValueError(f"unknown arm: {arm!r} (expected one of {ARMS})")


def our_surplus(mandate: Mandate, our_action: str, price: float) -> float:
    """Principal's surplus vs BATNA. Deals only close on OUR accept (see the
    single-turn caveat above); everything else realizes the outside option."""
    if our_action == "accept":
        return mandate.value(price) - mandate.batna_value()
    return 0.0


def their_surplus(valuation: float, our_action: str, price: float) -> float:
    """Buyer's surplus vs its outside option (0). Valuation is known for the
    LLM counterparty (we set it); scripted counterparties have no declared
    valuation, so the harness records None for them instead of calling this."""
    if our_action == "accept":
        return valuation - price
    return 0.0
