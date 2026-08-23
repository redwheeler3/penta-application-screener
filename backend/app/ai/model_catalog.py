"""The AI models the application knows how to invoke.

Model IDs stay provider-native and are treated as opaque everywhere outside this
catalog. Each route also maps to the provider-neutral model identity whose
judgment it represents. Settings, traces, and cost rows retain the actual route ID;
caches and freshness use the shared model identity so moving the same model between
certified-equivalent transports does not discard valid work.
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


MODEL_IDS_BY_ROUTE = {
    "bedrock": {
        "haiku": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        "sonnet": "us.anthropic.claude-sonnet-4-6",
        "luna": "openai.gpt-5.6-luna",
        "terra": "openai.gpt-5.6-terra",
    },
    "direct": {
        "haiku": "claude-haiku-4-5-20251001",
        "sonnet": "claude-sonnet-4-6",
        "luna": "gpt-5.6-luna",
        "terra": "gpt-5.6-terra",
    },
}

# Provider-neutral identities for the pinned model behind each route. These values are
# never sent to a provider; cache keys and freshness fingerprints use them solely to
# recognize equivalent Bedrock and direct routes.
MODEL_IDENTITIES = {
    "haiku": "anthropic:claude-haiku-4-5-20251001",
    "sonnet": "anthropic:claude-sonnet-4-6",
    "luna": "openai:gpt-5.6-luna",
    "terra": "openai:gpt-5.6-terra",
}


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    model_identity: str
    label: str
    provider: ModelProvider
    vendor: ModelVendor
    supports_reasoning_effort: bool = False


MODEL_CATALOG: tuple[ModelSpec, ...] = (
    ModelSpec(
        model_id=MODEL_IDS_BY_ROUTE["bedrock"]["haiku"],
        model_identity=MODEL_IDENTITIES["haiku"],
        label="Claude Haiku 4.5",
        provider=ModelProvider.BEDROCK,
        vendor=ModelVendor.ANTHROPIC,
    ),
    ModelSpec(
        model_id=MODEL_IDS_BY_ROUTE["direct"]["haiku"],
        model_identity=MODEL_IDENTITIES["haiku"],
        label="Claude Haiku 4.5",
        provider=ModelProvider.ANTHROPIC,
        vendor=ModelVendor.ANTHROPIC,
    ),
    ModelSpec(
        model_id=MODEL_IDS_BY_ROUTE["bedrock"]["sonnet"],
        model_identity=MODEL_IDENTITIES["sonnet"],
        label="Claude Sonnet 4.6",
        provider=ModelProvider.BEDROCK,
        vendor=ModelVendor.ANTHROPIC,
    ),
    ModelSpec(
        model_id=MODEL_IDS_BY_ROUTE["direct"]["sonnet"],
        model_identity=MODEL_IDENTITIES["sonnet"],
        label="Claude Sonnet 4.6",
        provider=ModelProvider.ANTHROPIC,
        vendor=ModelVendor.ANTHROPIC,
    ),
    ModelSpec(
        model_id=MODEL_IDS_BY_ROUTE["bedrock"]["luna"],
        model_identity=MODEL_IDENTITIES["luna"],
        label="GPT-5.6 Luna",
        provider=ModelProvider.BEDROCK,
        vendor=ModelVendor.OPENAI,
        supports_reasoning_effort=True,
    ),
    ModelSpec(
        model_id=MODEL_IDS_BY_ROUTE["direct"]["luna"],
        model_identity=MODEL_IDENTITIES["luna"],
        label="GPT-5.6 Luna",
        provider=ModelProvider.OPENAI,
        vendor=ModelVendor.OPENAI,
        supports_reasoning_effort=True,
    ),
    ModelSpec(
        model_id=MODEL_IDS_BY_ROUTE["bedrock"]["terra"],
        model_identity=MODEL_IDENTITIES["terra"],
        label="GPT-5.6 Terra",
        provider=ModelProvider.BEDROCK,
        vendor=ModelVendor.OPENAI,
        supports_reasoning_effort=True,
    ),
    ModelSpec(
        model_id=MODEL_IDS_BY_ROUTE["direct"]["terra"],
        model_identity=MODEL_IDENTITIES["terra"],
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


def model_identity(model_id: str) -> str:
    """Return the provider-neutral identity shared by equivalent model routes."""
    return model_spec(model_id).model_identity


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
