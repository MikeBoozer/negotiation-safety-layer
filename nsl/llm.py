"""The LLM seam.

Every component talks to the model through `LLMClient.complete_json`, which
returns a dict matching the supplied JSON schema. Two implementations:

  - AnthropicLLM : real calls via the Anthropic SDK + structured outputs.
  - MockLLM      : a deterministic stand-in so the layer runs (and tests pass)
                   with no API key. The mock's "brain" is a handler you pass in.

`anthropic` is imported lazily inside AnthropicLLM so the rest of the package
(and the test suite) imports fine without the dependency or a key.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict


class AnthropicLLM:
    """Real client. Uses the Messages API with `output_config.format` to force
    schema-valid JSON (see the claude-api skill)."""

    def __init__(self, client: Any = None, max_tokens: int = 1024) -> None:
        if client is None:
            import os

            try:  # best-effort: pick up ANTHROPIC_API_KEY from the project .env
                from dotenv import load_dotenv

                root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                load_dotenv(os.path.join(root, ".env"))
            except Exception:
                pass

            import anthropic  # lazy: keeps the package importable without the dep

            client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
        self._client = client
        self._max_tokens = max_tokens

    def complete_json(self, *, model: str, system: str, user: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        resp = self._client.messages.create(
            model=model,
            max_tokens=self._max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        text = next((b.text for b in resp.content if b.type == "text"), None)
        if text is None:
            # e.g. a safety refusal returns an empty content list — give an
            # actionable error instead of a bare StopIteration mid-negotiation.
            raise RuntimeError(
                "Anthropic response contained no text block to parse "
                f"(stop_reason={getattr(resp, 'stop_reason', None)})."
            )
        return json.loads(text)


class MockLLM:
    """Deterministic stand-in. `handler(model, system, user, schema) -> dict`."""

    def __init__(self, handler: Callable[[str, str, str, Dict[str, Any]], Dict[str, Any]]) -> None:
        self._handler = handler

    def complete_json(self, *, model: str, system: str, user: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        return self._handler(model, system, user, schema)
