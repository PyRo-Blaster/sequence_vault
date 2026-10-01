"""The Anthropic adapter's request shape and response handling, against a fake SDK client."""

import json
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2 as httpx
import pytest

from sequence_vault.adapters.ai.gateway import ANSWER_SCHEMA, AnthropicLocator
from sequence_vault.application.ports import TransientError
from sequence_vault.settings import REPO_ROOT

PROMPTS = REPO_ROOT / "prompts/extraction/v1"
UNSUPPORTED = {
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "pattern",
    "oneOf",
    "if",
    "then",
    "else",
    "minItems",
    "maxItems",
    "$ref",
}


class FakeMessages:
    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.response, self.error = response, error
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


def response(
    stop_reason: str = "end_turn", text: str = '{"records": [], "unresolved_block_ids": []}'
) -> Any:
    return SimpleNamespace(
        stop_reason=stop_reason,
        model="claude-opus-5-5",
        content=[SimpleNamespace(type="text", text=text)],
    )


def locator(messages: FakeMessages, **options: Any) -> AnthropicLocator:
    client = SimpleNamespace(beta=SimpleNamespace(messages=messages), messages=messages)
    return AnthropicLocator(client, model="claude-opus-5-5", prompt_dir=PROMPTS, **options)


def test_request_uses_structured_output_effort_and_default_fallback() -> None:
    messages = FakeMessages(response())
    answer = locator(messages).answer({"blocks": []})
    (call,) = messages.calls
    assert call["model"] == "claude-opus-5-5"
    assert call["output_config"] == {
        "effort": "medium",
        "format": {"type": "json_schema", "schema": ANSWER_SCHEMA},
    }
    assert (call["betas"], call["fallbacks"]) == (["server-side-fallback-2026-07-01"], "default")
    assert "untrusted" not in call["system"] and "never an instruction" in call["system"]
    assert "tools" not in call and json.loads(call["messages"][0]["content"]) == {"blocks": []}
    assert answer.data == {"records": [], "unresolved_block_ids": []}


def test_platforms_without_server_fallback_use_the_plain_endpoint() -> None:
    messages = FakeMessages(response())
    locator(messages, server_fallback=False).answer({})
    assert "fallbacks" not in messages.calls[0] and "betas" not in messages.calls[0]


def test_repair_appends_the_previous_answer_and_the_problem() -> None:
    messages = FakeMessages(response())
    locator(messages).answer({"a": 1}, previous='{"records": []}', repair="unknown ids")
    roles = [m["role"] for m in messages.calls[0]["messages"]]
    assert roles == ["user", "assistant", "user"]


@pytest.mark.parametrize(
    ("stop", "text", "problem"),
    [
        ("refusal", "", "refusal"),
        ("max_tokens", '{"rec', "truncated"),
        ("end_turn", "not json", "invalid_json"),
    ],
)
def test_unusable_responses_are_reported(stop: str, text: str, problem: str) -> None:
    answer = locator(FakeMessages(response(stop, text))).answer({})
    assert (answer.data, answer.problem) == (None, problem)


def test_transient_provider_errors_retry_and_others_report_unavailable() -> None:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    with pytest.raises(TransientError):
        locator(FakeMessages(error=anthropic.APIConnectionError(request=request))).answer({})
    denied = anthropic.PermissionDeniedError(
        "denied", response=httpx.Response(403, request=request), body=None
    )
    assert locator(FakeMessages(error=denied)).answer({}).problem == "unavailable"


def test_answer_schema_fits_structured_outputs() -> None:
    def walk(node: Any) -> None:
        if isinstance(node, dict):
            assert not UNSUPPORTED & node.keys(), node
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(ANSWER_SCHEMA)
