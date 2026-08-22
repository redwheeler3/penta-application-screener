"""The AI models the application knows how to invoke.

Model IDs stay provider-native and are treated as opaque everywhere outside this
catalog.  The IDs happen to be distinct across the four supported routes, so they
already provide the stable identity used by settings, caches, traces, and cost rows;
there is no second application-specific model identifier to keep in sync.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

ReasoningEffort = Literal["none", "low", "medium", "high", "xhigh", "max"]


class ModelProvider(StrEnum):
    BEDROCK = "bedrock"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


class ModelVendor(StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    label: str
    provider: ModelProvider
    vendor: ModelVendor
    supports_reasoning_effort: bool = False


MODEL_CATALOG: tuple[ModelSpec, ...] = (
    ModelSpec(
        model_id="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        label="Claude Haiku 4.5",
        provider=ModelProvider.BEDROCK,
        vendor=ModelVendor.ANTHROPIC,
    ),
    ModelSpec(
        model_id="claude-haiku-4-5-20251001",
        label="Claude Haiku 4.5",
        provider=ModelProvider.ANTHROPIC,
        vendor=ModelVendor.ANTHROPIC,
    ),
    ModelSpec(
        model_id="us.anthropic.claude-sonnet-4-6",
        label="Claude Sonnet 4.6",
        provider=ModelProvider.BEDROCK,
        vendor=ModelVendor.ANTHROPIC,
    ),
    ModelSpec(
        model_id="claude-sonnet-4-6",
        label="Claude Sonnet 4.6",
        provider=ModelProvider.ANTHROPIC,
        vendor=ModelVendor.ANTHROPIC,
    ),
    ModelSpec(
        model_id="openai.gpt-5.6-luna",
        label="GPT-5.6 Luna",
        provider=ModelProvider.BEDROCK,
        vendor=ModelVendor.OPENAI,
        supports_reasoning_effort=True,
    ),
    ModelSpec(
        model_id="gpt-5.6-luna",
        label="GPT-5.6 Luna",
        provider=ModelProvider.OPENAI,
        vendor=ModelVendor.OPENAI,
        supports_reasoning_effort=True,
    ),
    ModelSpec(
        model_id="openai.gpt-5.6-terra",
        label="GPT-5.6 Terra",
        provider=ModelProvider.BEDROCK,
        vendor=ModelVendor.OPENAI,
        supports_reasoning_effort=True,
    ),
    ModelSpec(
        model_id="gpt-5.6-terra",
        label="GPT-5.6 Terra",
        provider=ModelProvider.OPENAI,
        vendor=ModelVendor.OPENAI,
        supports_reasoning_effort=True,
    ),
)

_BY_ID = {model.model_id: model for model in MODEL_CATALOG}


def model_spec(model_id: str) -> ModelSpec:
    """Return the exact supported route for ``model_id``.

    Routing is deliberately catalog-driven.  Prefix tests spread provider knowledge
    into callers and silently accept invalid combinations; an unknown configured model
    is instead a clear settings error.
    """
    try:
        return _BY_ID[model_id]
    except KeyError as exc:
        raise ValueError(f"Unsupported AI model: {model_id!r}") from exc


def known_model_spec(model_id: str) -> ModelSpec | None:
    """Return catalog metadata when known, including for display-only callers."""
    return _BY_ID.get(model_id)


def supports_reasoning_effort(model_id: str) -> bool:
    """Report a display-safe capability for current or historical model IDs."""
    spec = known_model_spec(model_id)
    return bool(spec and spec.supports_reasoning_effort)


def provider_is_configured(
    provider: ModelProvider, *, openai_api_key: str, anthropic_api_key: str
) -> bool:
    if provider is ModelProvider.OPENAI:
        return bool(openai_api_key)
    if provider is ModelProvider.ANTHROPIC:
        return bool(anthropic_api_key)
    # Bedrock uses boto's credential chain; resolving it during every settings read
    # could contact instance metadata. Invocation remains the authoritative access test.
    return True
