"""Cost metering + a HARD budget guard for live experiment runs.

PRICES is the single source of truth for $/1M token rates — count_cost.py
imports it from here. MeteredLLM wraps any LLMClient and accumulates estimated
spend: exact token counts when the wrapped client reports usage (AnthropicLLM
records `last_usage`), else a conservative chars//4 heuristic with the schema
billed as input (matching count_cost's '+schema' upper bound). BudgetGuard
refuses to START an episode that would project past the cap; in-flight
episodes always finish, so the cap can be overshot by at most ~one episode.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from config import DETECTOR_MODEL, NEGOTIATOR_MODEL, VERIFIER_MODEL

# (input $/1M, output $/1M), keyed off the config constants so a model-id bump
# in config.py moves the pricing with it instead of silently falling through
# to the unknown-model fallback. (COUNTERPARTY_MODEL == VERIFIER_MODEL today.)
PRICES = {
    NEGOTIATOR_MODEL: (5.0, 25.0),
    VERIFIER_MODEL: (3.0, 15.0),
    DETECTOR_MODEL: (1.0, 5.0),
}
_UNKNOWN_MODEL_PRICE = PRICES[NEGOTIATOR_MODEL]  # price unknown models like Opus: conservative


class BudgetExceeded(RuntimeError):
    pass


class MeteredLLM:
    """Wraps any LLMClient; accumulates estimated $ across calls."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.total_usd = 0.0
        self.calls = 0
        self._last_take = 0.0

    def complete_json(self, *, model: str, system: str, user: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        resp = self.inner.complete_json(model=model, system=system, user=user, schema=schema)
        pin, pout = PRICES.get(model, _UNKNOWN_MODEL_PRICE)
        usage = getattr(self.inner, "last_usage", None)
        if usage and usage.get("model") == model:
            in_tok, out_tok = usage["input_tokens"], usage["output_tokens"]
        else:
            in_tok = (len(system) + len(user) + len(json.dumps(schema))) // 4
            out_tok = len(json.dumps(resp)) // 4
        self.total_usd += in_tok / 1e6 * pin + out_tok / 1e6 * pout
        self.calls += 1
        return resp

    def take_delta(self) -> float:
        """Cost since the last take_delta() — brackets one episode for attribution."""
        delta = self.total_usd - self._last_take
        self._last_take = self.total_usd
        return delta


class BudgetGuard:
    """HARD cap on cumulative estimated spend (resume-aware via already_spent)."""

    def __init__(self, cap_usd: float, already_spent: float = 0.0) -> None:
        self.cap_usd = cap_usd
        self.spent = already_spent
        self._recent: List[float] = []  # last 10 episode costs

    def projected_next(self) -> float:
        if self._recent:
            return max(sum(self._recent) / len(self._recent), 0.05)
        return 0.05

    def check_or_raise(self) -> None:
        projected = self.projected_next()
        if self.spent + projected > self.cap_usd:
            raise BudgetExceeded(
                f"estimated spend ${self.spent:.2f} + projected next episode "
                f"${projected:.2f} would exceed the ${self.cap_usd:.2f} cap"
            )

    def record(self, episode_cost: float) -> None:
        self.spent += episode_cost
        self._recent.append(episode_cost)
        if len(self._recent) > 10:
            self._recent.pop(0)
