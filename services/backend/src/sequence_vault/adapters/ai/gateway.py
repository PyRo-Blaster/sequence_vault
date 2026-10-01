"""Model gateway: the only code that talks to a model provider (ADR 0003, ADR 0007).

The model receives document text and candidate ids and returns JSON constrained to
ANSWER_SCHEMA. It has no tools, no database and no network access of its own.
"""

import json
from pathlib import Path
from typing import Any

import anthropic

from sequence_vault.application.model_assist import ModelAnswer
from sequence_vault.application.ports import TransientError

Json = dict[str, Any]

# Structured outputs accept a subset of JSON Schema: every object closed and fully required,
# no string or number constraints. Validation of ids happens in model_assist.resolve.
ANSWER_SCHEMA: Json = {
    "type": "object",
    "additionalProperties": False,
    "required": ["records", "unresolved_block_ids"],
    "properties": {
        "records": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "span_ids",
                    "name_ids",
                    "molecule_type",
                    "association_status",
                    "observations",
                ],
                "properties": {
                    "span_ids": {"type": "array", "items": {"type": "string"}},
                    "name_ids": {"type": "array", "items": {"type": "string"}},
                    "molecule_type": {
                        "type": "string",
                        "enum": ["protein", "nucleic_acid", "uncertain"],
                    },
                    "association_status": {
                        "type": "string",
                        "enum": ["unambiguous", "ambiguous", "conflicting"],
                    },
                    "observations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["kind", "message", "block_ids"],
                            "properties": {
                                "kind": {
                                    "type": "string",
                                    "enum": [
                                        "name_conflict",
                                        "unclear_mapping",
                                        "possible_truncation",
                                        "possible_nucleic_acid",
                                        "cross_block_join",
                                        "unsupported_content",
                                    ],
                                },
                                "message": {"type": "string"},
                                "block_ids": {"type": "array", "items": {"type": "string"}},
                            },
                        },
                    },
                },
            },
        },
        "unresolved_block_ids": {"type": "array", "items": {"type": "string"}},
    },
}

TRANSIENT = (
    anthropic.RateLimitError,
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
    anthropic.InternalServerError,
)


class ModelUnavailable(Exception):
    """A non-transient provider error (credentials, permissions, bad request)."""


class AnthropicLocator:
    """Claude via the Anthropic SDK. The client decides the platform (Claude API, Bedrock,
    Vertex AI); server-side refusal fallback is only requested where it is supported."""

    def __init__(
        self,
        client: Any,
        *,
        model: str,
        prompt_dir: Path,
        effort: str = "medium",
        server_fallback: bool = True,
        max_tokens: int = 16_000,
    ) -> None:
        self.client = client
        self.model = model
        self.prompt_version = f"extraction-{prompt_dir.name}"
        self.system = (prompt_dir / "system.md").read_text(encoding="utf-8")
        self.effort = effort
        self.server_fallback = server_fallback
        self.max_tokens = max_tokens

    def answer(
        self, payload: Json, *, previous: str | None = None, repair: str | None = None
    ) -> ModelAnswer:
        messages: list[Json] = [
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}
        ]
        if previous is not None and repair is not None:
            messages += [
                {"role": "assistant", "content": previous},
                {"role": "user", "content": repair},
            ]
        options: Json = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": self.system,
            "messages": messages,
            "output_config": {
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": ANSWER_SCHEMA},
            },
        }
        try:
            if self.server_fallback:
                response = self.client.beta.messages.create(
                    **options, betas=["server-side-fallback-2026-07-01"], fallbacks="default"
                )
            else:
                response = self.client.messages.create(**options)
        except TRANSIENT as error:
            raise TransientError(f"model provider: {type(error).__name__}") from error
        except anthropic.APIError as error:
            return ModelAnswer(None, "unavailable", self.model, str(error)[:200])
        served = getattr(response, "model", self.model)
        if response.stop_reason == "refusal":
            return ModelAnswer(None, "refusal", served)
        if response.stop_reason == "max_tokens":
            return ModelAnswer(None, "truncated", served)
        text = "".join(block.text for block in response.content if block.type == "text")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return ModelAnswer(None, "invalid_json", served, text)
        if not isinstance(data, dict):
            return ModelAnswer(None, "invalid_json", served, text)
        return ModelAnswer(data, None, served, text)


def build_client(
    provider: str,
    *,
    region: str | None,
    project: str | None,
    base_url: str | None,
    api_key: str | None,
) -> Any:
    """SDK client for the organization-approved platform."""
    if provider == "anthropic":
        options: Json = {}
        if base_url:
            options["base_url"] = base_url
        if api_key:
            options["api_key"] = api_key
        return anthropic.Anthropic(**options)
    if provider == "bedrock":
        return anthropic.AnthropicBedrockMantle(aws_region=region)
    if provider == "vertex":
        if not project:
            raise ValueError("SEQUENCE_VAULT_AI_PROJECT is required for Vertex AI.")
        return anthropic.AnthropicVertex(project_id=project, region=region or "global")
    raise ValueError(f"Unknown model provider {provider!r}")
