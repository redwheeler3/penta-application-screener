"""AI token pricing for cost estimates and spending-cap enforcement.

Prices are USD per 1,000,000 tokens. The direct-provider and Bedrock on-demand
prices for the supported models were equivalent when last checked 2026-08-22.
Update by hand when provider pricing changes.

Why hardcoded: the AWS Price List API (boto3 "pricing", ServiceCode
"AmazonBedrock") carries recent competitor models (Llama 4, Nova 2.0, Qwen3,
etc.) but, as of 2026-06, lists no Anthropic Claude model past v3 — so it
cannot price Haiku 4.5 / Sonnet 4.6, the models we actually use. A live lookup
would always fall back, so the table is the source of truth. Revisit if AWS
adds Claude 4.x to the Price List API.

The lookup matches on a stable model-family substring so direct and Bedrock IDs
share one price entry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.ai.provider import Usage


class Tally(Protocol):
    """The running totals a per-application pass accumulates as it processes results
    (screening's ``RunTally``, ranking's ``ScoreTally``). ``PassCost.from_tally`` reads
    these to shape the pass's spend once, so the two tallies can't drift on how a tally
    becomes a cost."""

    analyzed: int
    cached: int
    failed: int
    cost_usd: float
    input_tokens: int
    output_tokens: int
    cached_saved_usd: float


@dataclass(frozen=True)
class ModelPrice:
    input_per_mtok: float
    output_per_mtok: float


# Keyed by a stable substring of the model ID. More specific keys must precede
# the broader ones they share a prefix with (e.g. "sonnet-4-6" before
# "sonnet-4"), since lookup returns the first matching substring.
_PRICES: dict[str, ModelPrice] = {
    "gpt-5.6-luna": ModelPrice(input_per_mtok=0.20, output_per_mtok=1.20),
    "gpt-5.6-terra": ModelPrice(input_per_mtok=2.00, output_per_mtok=12.00),
    "haiku-4-5": ModelPrice(input_per_mtok=1.00, output_per_mtok=5.00),
    "sonnet-4-6": ModelPrice(input_per_mtok=3.00, output_per_mtok=15.00),
    "sonnet-4-5": ModelPrice(input_per_mtok=3.00, output_per_mtok=15.00),
    "sonnet-4": ModelPrice(input_per_mtok=3.00, output_per_mtok=15.00),
    "opus-4": ModelPrice(input_per_mtok=15.00, output_per_mtok=75.00),
}

# Used when a model ID is not in the table, so a missing entry never silently
# under-estimates cost: fall back to the most expensive known rate (Opus-tier).
_FALLBACK = _PRICES["opus-4"]


def price_for_model(model_id: str) -> ModelPrice:
    for key, price in _PRICES.items():
        if key in model_id:
            return price
    return _FALLBACK


def cost_usd(model_id: str, usage: Usage) -> float:
    price = price_for_model(model_id)
    return (
        usage.input_tokens / 1_000_000 * price.input_per_mtok
        + usage.output_tokens / 1_000_000 * price.output_per_mtok
    )


@dataclass(frozen=True)
class PassCost:
    """What one AI pass spent, in one shape every pass speaks (pool-level and
    per-application alike). Built once from a model call's ``Usage`` so tokens are never
    discarded (every pass funnels through this one shape rather than hand-writing
    ``cost_usd(...)`` and returning a bare float, which would drop the token counts).
    Carries the fresh spend
    (``calls`` model calls, ``input_tokens``/``output_tokens``, ``cost_usd``) plus the
    cache side (``cached_count`` reused units and ``cached_saved_usd``, their original
    cost — an estimate of what caching saved). A pass that never caches leaves those 0.

    Additive so a fan-out (K discovery calls) or a per-candidate loop can fold each
    call's cost into one pass total with ``+``/``sum``.
    """

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    cached_count: int = 0
    cached_saved_usd: float = 0.0
    # Model calls that errored out. Meaningful for the per-application passes (screening,
    # scoring), where a failure is non-fatal and per-item — the run continues, this counts
    # the casualties. ~Always 0 for the pool passes (discovery/decompose/match/consolidate),
    # where a failure is fatal: the run aborts before recording, so there's no partial
    # count to keep. Latency is NOT here — it's wall-clock per pass, measured at the pass
    # level and recorded separately (summing it across a fan-out's parallel calls would
    # give CPU time, not wall-clock).
    failed_calls: int = 0
    # The model the pass ran on. "" when it made no call this run (a skipped match on a
    # first run, a consolidation that nominated nothing). On a fan-out all K calls share
    # one model, so summing keeps it.
    model_id: str = ""

    @classmethod
    def from_usage(cls, model_id: str, usage: Usage) -> PassCost:
        """One fresh model call, priced from its token usage."""
        return cls(
            calls=1,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=cost_usd(model_id, usage),
            model_id=model_id,
        )

    @classmethod
    def from_tally(cls, tally: Tally, model_id: str) -> PassCost:
        """A per-application pass's accumulated ``tally`` as one ``PassCost`` (fresh tokens +
        cost, cache side). ``model_id`` is blank when the pass made no fresh call this run
        (an all-cached run), so a skipped pass doesn't claim a model."""
        return cls(
            calls=tally.analyzed,
            input_tokens=tally.input_tokens,
            output_tokens=tally.output_tokens,
            cost_usd=tally.cost_usd,
            cached_count=tally.cached,
            cached_saved_usd=tally.cached_saved_usd,
            failed_calls=tally.failed,
            model_id=model_id if tally.analyzed else "",
        )

    def __add__(self, other: PassCost) -> PassCost:
        return PassCost(
            calls=self.calls + other.calls,
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cost_usd=self.cost_usd + other.cost_usd,
            cached_count=self.cached_count + other.cached_count,
            cached_saved_usd=self.cached_saved_usd + other.cached_saved_usd,
            failed_calls=self.failed_calls + other.failed_calls,
            model_id=self.model_id or other.model_id,
        )

    def __radd__(self, other: PassCost | int) -> PassCost:
        # so sum([...]) works: its start value is int 0, everything else is a PassCost.
        if other == 0:
            return self
        return self.__add__(other)  # type: ignore[arg-type]
