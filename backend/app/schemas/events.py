"""The one NDJSON event vocabulary shared by both streaming jobs (Screen, Rank).

NDJSON responses bypass ``response_model``, so these typed models are the single
source of truth for event shapes. Generators emit
``event.model_dump_json(by_alias=True) + "\\n"`` — camelCase for free, greppable,
and mirrored by the frontend's discriminated union in ``types.ts``.

Grammar (every event carries ``phase`` so the client's stream switch is identical
across jobs; quality-flags uses the single phase ``"screen"``):

    phase      — a pass began (``total`` known for per-item passes)
    progress   — one item finished within a phase
    thinking   — streamed model reasoning (rank's criteria phase only)
    notice     — a mid-stream structured update (rank's criteria_done)
    item_error — one item failed, NON-fatal; the stream continues
    error      — a fatal phase failure; the stream ends
    summary    — final totals (job-specific fields + shared cost)

``item_error`` vs ``error`` is deliberate: a per-item failure (one applicant) must
not be shown as a run-fatal toast, which is what a single merged ``error`` type
would cause.
"""

from typing import Literal

from app.schemas.base import ResponseModel


class PhaseEvent(ResponseModel):
    type: Literal["phase"] = "phase"
    phase: str
    total: int | None = None


class ProgressEvent(ResponseModel):
    type: Literal["progress"] = "progress"
    phase: str
    processed: int
    total: int


class ThinkingEvent(ResponseModel):
    type: Literal["thinking"] = "thinking"
    phase: str
    text: str


class NoticeEvent(ResponseModel):
    """A structured mid-stream update (e.g. criteria discovered + carried forward)."""

    type: Literal["notice"] = "notice"
    phase: str
    dimensions: int
    carried_forward: int
    new_dimensions: int


class ItemErrorEvent(ResponseModel):
    """One item failed but the stream continues (non-fatal)."""

    type: Literal["item_error"] = "item_error"
    phase: str
    message: str
    application_id: int | None = None


class ErrorEvent(ResponseModel):
    """A fatal phase failure; the stream ends after this."""

    type: Literal["error"] = "error"
    phase: str
    message: str


class QualityFlagSummary(ResponseModel):
    type: Literal["summary"] = "summary"
    analyzed: int
    cached: int
    flagged: int
    failed: int
    total_cost_usd: float


class RankSummary(ResponseModel):
    type: Literal["summary"] = "summary"
    dimensions: int
    scored: int
    failed: int
    total_cost_usd: float


def emit(event: ResponseModel) -> str:
    """Serialize one event to a camelCase NDJSON line."""
    return event.model_dump_json(by_alias=True) + "\n"
