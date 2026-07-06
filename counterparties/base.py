"""Counterparty interface. A counterparty produces a single-turn offer (message +
price) and may accept ground rules. v0 uses scripted, deterministic ones so the
harness is reproducible; an LLM adversary is an easy drop-in behind this ABC."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class CounterpartyTurn:
    message: str
    offered_price: float
    offered_size: float
    is_threat: bool


class CounterpartyAgent(ABC):
    name: str = "counterparty"

    @abstractmethod
    def turn(self) -> CounterpartyTurn: ...

    def consider_ground_rules(self, rules: List[str]) -> bool:
        return True

    def observe_commitment(self, framing: Optional[str]) -> None:
        """Pre-play brief: the commitment text (with its credibility framing)
        our side transmits BEFORE the counterparty moves. None = nothing was
        transmitted. Default: ignore — scripted counterparties are non-reactive."""
        return None
