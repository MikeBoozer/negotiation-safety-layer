"""Scenario adapter interface.

A scenario fixes what changes between use cases:
  - the stakes (what the principal cares about),
  - the surrogate decoy + default policy (mandate + ground rules),
  - the detection vocabulary (which words signal a strategic turn / coercion).

Adding on-chain / auction / procurement later = a new Scenario subclass; the
detector, negotiator, verifier, and orchestrator are untouched.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Pattern

from nsl.policy import NegotiationPolicy


class Scenario(ABC):
    @abstractmethod
    def default_policy(self) -> NegotiationPolicy: ...

    @abstractmethod
    def describe_stakes(self) -> str: ...

    @property
    @abstractmethod
    def strategic_markers(self) -> Pattern:
        """Compiled regex whose hit means 'this might be a strategic turn'."""

    @property
    @abstractmethod
    def coercion_markers(self) -> Pattern:
        """Compiled regex whose hit means 'a threat may be present' — also fires
        the detector even when no strategic words are present."""
