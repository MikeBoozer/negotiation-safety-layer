"""The LLM seam.

Every component talks to the model through `LLMClient.complete_json`, which
returns a dict matching the supplied JSON schema. Two implementations:

  - AnthropicLLM : real calls via the Anthropic SDK + structured outputs.
  - MockLLM      : a deterministic stand-in so the layer runs (and tests pass)
                   with no API key. The mock's "brain" is a handler you pass in.

Both accumulate one record per call in `call_log`, which the harness drains
once per episode via `take_calls()`. The point is to capture what cannot be
re-derived after the fact: the model snapshot that actually SERVED the call,
the exact prompts, the raw response text, the stop reason, and the request id.
`anthropic` is imported lazily inside AnthropicLLM so the rest of the package
(and the test suite) imports fine without the dependency or a key.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional


def _schema_props(schema: Dict[str, Any]) -> List[str]:
    """Sorted property names of the output schema — enough to identify which
    component made the call (harness.mock_brain.component_of dispatches on the
    same keys) without nsl having to import from harness."""
    return sorted(schema.get("properties", {}))


class _CallRecorder:
    """Per-call transcript buffer, drained by the harness once per episode.

    Deliberately separate from harness.budget.MeteredLLM: the meter's
    `last_usage` identity check keys off the *requested* model id and only
    trusts exact token counts when it matches what it asked for. The served
    snapshot can be a more specific id than the alias you requested, so
    conflating the two would silently drop the meter back to its chars//4
    estimate. Requested id stays in `last_usage`; served id goes in the record.
    """

    def __init__(self) -> None:
        self.call_log: List[Dict[str, Any]] = []

    def take_calls(self) -> List[Dict[str, Any]]:
        """Return the calls recorded since the last drain, and reset."""
        calls, self.call_log = self.call_log, []
        return calls


class AnthropicLLM(_CallRecorder):
    """Real client. Uses the Messages API with `output_config.format` to force
    schema-valid JSON (see the claude-api skill)."""

    def __init__(self, client: Any = None, max_tokens: int = 1024) -> None:
        super().__init__()
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
        usage = getattr(resp, "usage", None)
        self.last_usage = (  # exact token counts, consumed by harness.budget.MeteredLLM
            {"model": model, "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens}
            if usage is not None
            else None
        )
        text = next((b.text for b in resp.content if b.type == "text"), None)
        # Record BEFORE the refusal check: an episode that died on an empty
        # content list is exactly the one whose stop_reason we want on disk.
        self._record(model, resp, usage, system, user, schema, text)
        if text is None:
            # e.g. a safety refusal returns an empty content list — give an
            # actionable error instead of a bare StopIteration mid-negotiation.
            raise RuntimeError(
                "Anthropic response contained no text block to parse "
                f"(stop_reason={getattr(resp, 'stop_reason', None)})."
            )
        return json.loads(text)

    def _record(
        self,
        model: str,
        resp: Any,
        usage: Any,
        system: str,
        user: str,
        schema: Dict[str, Any],
        text: Optional[str],
    ) -> None:
        self.call_log.append(
            {
                "model_requested": model,
                # resp.model is the snapshot that actually served this call.
                # Requesting an alias can return a more specific id, and that
                # resolution is not recoverable later — the alias will point
                # somewhere else by the time anyone re-reads these results.
                "model_served": getattr(resp, "model", None),
                "stop_reason": getattr(resp, "stop_reason", None),
                # The one id that lets Anthropic trace this exact call.
                "request_id": getattr(resp, "_request_id", None),
                "schema_props": _schema_props(schema),
                "system": system,
                "user": user,
                "response_text": text,
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
                # Recorded to VERIFY the standing claim that prompt caching
                # never fires here (prompts are ~400-500 tokens; the minimum
                # cacheable prefix is 1024 on Sonnet/Opus and 4096 on Haiku)
                # rather than to keep asserting it.
                "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", None),
                "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None),
            }
        )


class MockLLM(_CallRecorder):
    """Deterministic stand-in. `handler(model, system, user, schema) -> dict`."""

    def __init__(self, handler: Callable[[str, str, str, Dict[str, Any]], Dict[str, Any]]) -> None:
        super().__init__()
        self._handler = handler

    def complete_json(self, *, model: str, system: str, user: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        resp = self._handler(model, system, user, schema)
        # Same record shape as the live client (nulls where only a real
        # response has the field) so the mock exercises the recording path.
        self.call_log.append(
            {
                "model_requested": model,
                "model_served": None,
                "stop_reason": None,
                "request_id": None,
                "schema_props": _schema_props(schema),
                "system": system,
                "user": user,
                "response_text": json.dumps(resp),
                "input_tokens": None,
                "output_tokens": None,
                "cache_creation_input_tokens": None,
                "cache_read_input_tokens": None,
            }
        )
        return resp
