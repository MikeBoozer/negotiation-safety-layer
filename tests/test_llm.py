"""The LLM seam's per-call recording (N2prep item 1).

The point of these tests is the live path: mock runs can exercise the plumbing
but never produce a served model snapshot, a request id, or usage counts, so
everything that actually matters for a live experiment record is only reachable
through a stubbed SDK response.
"""
import json

import pytest

from harness.budget import MeteredLLM
from nsl.llm import AnthropicLLM, MockLLM

SCHEMA = {"properties": {"is_strategic": {"type": "boolean"}, "stakes": {"type": "string"}}}


class FakeBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class FakeUsage:
    def __init__(self):
        self.input_tokens = 412
        self.output_tokens = 77
        self.cache_creation_input_tokens = 0
        self.cache_read_input_tokens = 0


class FakeResponse:
    """Shaped like a Messages API response: `model` is the SERVED snapshot,
    which is more specific than the alias the caller requested."""

    def __init__(self, text='{"ok": true}', model="claude-haiku-4-5-20251001"):
        self.model = model
        self.stop_reason = "end_turn"
        self._request_id = "req_018EeWyXxfu5pfWkrYcMdjWG"
        self.usage = FakeUsage()
        self.content = [FakeBlock(text)] if text is not None else []


class FakeClient:
    def __init__(self, response=None):
        self.response = response or FakeResponse()
        self.messages = self

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return self.response


def test_records_served_snapshot_separately_from_requested_alias():
    llm = AnthropicLLM(client=FakeClient())
    llm.complete_json(model="claude-haiku-4-5", system="s", user="u", schema=SCHEMA)
    (call,) = llm.take_calls()
    assert call["model_requested"] == "claude-haiku-4-5"
    assert call["model_served"] == "claude-haiku-4-5-20251001"
    assert call["request_id"] == "req_018EeWyXxfu5pfWkrYcMdjWG"
    assert call["stop_reason"] == "end_turn"
    assert (call["input_tokens"], call["output_tokens"]) == (412, 77)
    assert call["cache_read_input_tokens"] == 0
    assert call["schema_props"] == ["is_strategic", "stakes"]
    assert call["system"] == "s" and call["user"] == "u"


def test_metered_still_bills_exact_tokens_when_served_id_differs():
    """The trap this guards: MeteredLLM trusts `last_usage` only when its
    'model' equals the id it requested, and falls back to a chars//4 estimate
    otherwise. Putting the served snapshot in that field would silently disable
    exact token accounting on every live call, because the served id carries a
    date suffix the requested alias does not."""
    metered = MeteredLLM(AnthropicLLM(client=FakeClient()))
    metered.complete_json(model="claude-haiku-4-5", system="s", user="u", schema=SCHEMA)
    # Exact: 412/1e6*1.0 + 77/1e6*5.0. The chars//4 fallback would be ~1e-9,
    # three orders of magnitude off, so this distinguishes the two paths.
    assert metered.total_usd == pytest.approx(412 / 1e6 * 1.0 + 77 / 1e6 * 5.0, abs=0)


def test_take_calls_drains_so_records_attribute_to_one_episode():
    llm = AnthropicLLM(client=FakeClient())
    for _ in range(3):
        llm.complete_json(model="m", system="s", user="u", schema=SCHEMA)
    assert len(llm.take_calls()) == 3
    assert llm.take_calls() == []


def test_refusal_is_recorded_before_it_raises():
    """An episode that died on an empty content list is exactly the one whose
    stop_reason has to survive — recording after the raise would lose it."""
    llm = AnthropicLLM(client=FakeClient(FakeResponse(text=None)))
    with pytest.raises(RuntimeError, match="no text block"):
        llm.complete_json(model="m", system="s", user="u", schema=SCHEMA)
    (call,) = llm.take_calls()
    assert call["response_text"] is None
    assert call["stop_reason"] == "end_turn"
    assert call["request_id"] == "req_018EeWyXxfu5pfWkrYcMdjWG"


def test_mock_records_the_same_shape_so_the_path_is_exercised_offline():
    live = AnthropicLLM(client=FakeClient())
    live.complete_json(model="m", system="s", user="u", schema=SCHEMA)
    mock = MockLLM(lambda model, system, user, schema: {"is_strategic": True})
    mock.complete_json(model="m", system="s", user="u", schema=SCHEMA)
    (live_call,), (mock_call,) = live.take_calls(), mock.take_calls()
    assert set(live_call) == set(mock_call)
    assert json.loads(mock_call["response_text"]) == {"is_strategic": True}
    assert mock_call["model_served"] is None  # no server involved offline
