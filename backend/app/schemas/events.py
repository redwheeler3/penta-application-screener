"""The one NDJSON event vocabulary shared by both streaming jobs (Screen, Rank).

NDJSON responses bypass ``response_model``, so these typed models are the single
source of truth for event shapes. Generators emit
``event.model_dump_json(by_alias=True) + "\\n"`` — camelCase for free, greppable,
and mirrored by the frontend's discriminated union in ``types.ts``.

Grammar (every event carries ``phase`` so the client's stream switch is identical
across jobs; screening uses the single phase ``"screen"``):

    phase      — a pass began (``total`` known for per-item passes)
    progress   — one item finished within a phase
    thinking   — streamed model reasoning (rank's criteria phase only)
    notice     — a mid-stream structured update (rank's criteria_done)
    warning    — the run degraded but is continuing (a yellow, non-fatal toast)
    item_error — one item failed, NON-fatal; the stream continues
    error      — a fatal phase failure; the stream ends
    summary    — final totals (job-specific fields + shared cost)

``item_error`` vs ``error`` is deliberate: a per-item failure (one applicant) must
not be shown as a run-fatal toast, which is what a single merged ``error`` type
would cause. ``warning`` is a third severity between them: run-level (not per-item)
but non-fatal — e.g. some (not all) fan-out discovery workers timed out and the run
proceeded on the survivors. The client shows it amber and keeps going.
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


class StageEvent(ResponseModel):
    """A sub-stage transition within a phase, for phases that run several sequential
    steps under one phase banner (the criteria phase: discovery → decompose → match).
    Lets the UI update its label ("Running discoveries…" → "Settling the set…")
    without a per-item progress fraction — the steps are opaque model calls.
    """

    type: Literal["stage"] = "stage"
    phase: str
    stage: str


class NoticeEvent(ResponseModel):
    """A structured mid-stream update (e.g. criteria discovered + carried forward)."""

    type: Literal["notice"] = "notice"
    phase: str
    dimensions: int
    carried_forward: int
    new_dimensions: int


class WarningEvent(ResponseModel):
    """The run degraded but is continuing — a run-level, non-fatal notice shown as an
    amber toast (between the green summary and a fatal red error). E.g. a minority of
    fan-out discovery workers timed out; the run proceeded on the survivors."""

    type: Literal["warning"] = "warning"
    phase: str
    message: str


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


class ScreeningSummary(ResponseModel):
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


class EvalSummaryEvent(ResponseModel):
    """Terminal event of a streaming eval run — carries the full structured result as
    ``result`` (one of the eval response models in schemas/evals.py) plus where the run
    was persisted. The frontend renders ``result`` into the eval's results panel once the
    live "thinking" stream has finished. ``eval`` names which eval produced it so the
    client routes the payload to the right renderer."""

    type: Literal["summary"] = "summary"
    eval: str  # "scoring" | "judge" | "stability"
    saved_path: str | None = None  # server-side path the run was recorded to
    result: dict  # the eval's response model, already camelCase-serialized


def emit(event: ResponseModel) -> str:
    """Serialize one event to a camelCase NDJSON line."""
    return event.model_dump_json(by_alias=True) + "\n"
