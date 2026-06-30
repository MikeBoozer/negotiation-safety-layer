"""Data carriers passed between the layer's components. Plain dataclasses, no deps."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Optional


@dataclass
class EncounterState:
    """What the detector concluded about the current turn, plus the facts the
    harness/host supplies (the counterparty's offer and the pre-coercion baseline)."""

    is_strategic: bool
    stakes: str = ""
    counterparty: Optional[str] = None
    coercion_present: bool = False
    coercion_description: Optional[str] = None
    demand: Optional[str] = None
    incoming_message: str = ""
    # Facts supplied by the host, not inferred by the detector:
    offered_price: Optional[float] = None
    offered_size: Optional[float] = None
    baseline_price: Optional[float] = None  # best terms on the table BEFORE any coercion


@dataclass
class Action:
    """A proposed outbound move, produced by the negotiator (and vetted by the verifier)."""

    action: Literal["accept", "counter", "walk"]
    message: str
    price: float = 0.0
    size: float = 0.0
    responding_to_coercion: bool = False
    value_vs_batna: float = 0.0
    rationale: str = ""


@dataclass
class Verdict:
    allowed: bool
    reasons: List[str] = field(default_factory=list)


@dataclass
class Commitment:
    statement: str
    signature: str
    algorithm: str


@dataclass
class TurnResult:
    """What the orchestrator returns for one turn."""

    passthrough: bool
    state: Optional[EncounterState] = None
    action: Optional[Action] = None
    verdict: Optional[Verdict] = None
    commitment: Optional[Commitment] = None
    used_safe_default: bool = False
