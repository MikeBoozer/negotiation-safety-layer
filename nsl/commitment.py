"""Commitment channel.

For deterrence to bite, the counterparty must be able to *verify* the agent's
commitment to refuse coercion / honor ground rules. The default channel signs a
plain statement with HMAC (stdlib) — a stand-in for a real signature, escrow, or
mediator. Escrow / mediator adapters are interface stubs for later.
"""
from __future__ import annotations

import hashlib
import hmac
from abc import ABC, abstractmethod

from nsl.policy import NegotiationPolicy
from nsl.types import Action, Commitment


def sign_statement(secret: bytes, statement: str) -> str:
    """HMAC-sign a legible commitment statement. Module-level so one-off
    statements (e.g. a disarmament commitment for an experiment arm) can be
    signed with the same scheme the per-turn channel uses."""
    return hmac.new(secret, statement.encode(), hashlib.sha256).hexdigest()


class CommitmentChannel(ABC):
    @abstractmethod
    def commit(self, policy: NegotiationPolicy, action: Action) -> Commitment: ...

    @abstractmethod
    def verify(self, commitment: Commitment) -> bool: ...


class SignedStatementChannel(CommitmentChannel):
    """Signs a legible commitment statement so a counterparty could check it."""

    def __init__(self, secret: bytes) -> None:
        self._secret = secret

    def _statement(self, policy: NegotiationPolicy) -> str:
        rules = "; ".join(policy.ground_rules) if policy.ground_rules else "(none agreed)"
        return (
            "This agent will not concede real deal value to a coercive demand, and "
            f"honors these ground rules: {rules}."
        )

    def _sign(self, statement: str) -> str:
        return sign_statement(self._secret, statement)

    def commit(self, policy: NegotiationPolicy, action: Action) -> Commitment:
        statement = self._statement(policy)
        return Commitment(statement=statement, signature=self._sign(statement), algorithm="hmac-sha256")

    def verify(self, commitment: Commitment) -> bool:
        expected = self._sign(commitment.statement)
        return hmac.compare_digest(expected, commitment.signature)


class EscrowChannel(CommitmentChannel):
    """On-chain escrow stub: the contract is both the credible commitment device
    and the literal surrogate 'burn pile'. Left unimplemented for v0."""

    def commit(self, policy: NegotiationPolicy, action: Action) -> Commitment:  # pragma: no cover
        raise NotImplementedError("EscrowChannel is a stub for the on-chain adapter.")

    def verify(self, commitment: Commitment) -> bool:  # pragma: no cover
        raise NotImplementedError


class MediatorChannel(CommitmentChannel):
    """Neutral third-party mediator stub. Left unimplemented for v0."""

    def commit(self, policy: NegotiationPolicy, action: Action) -> Commitment:  # pragma: no cover
        raise NotImplementedError("MediatorChannel is a stub for the mediator adapter.")

    def verify(self, commitment: Commitment) -> bool:  # pragma: no cover
        raise NotImplementedError
