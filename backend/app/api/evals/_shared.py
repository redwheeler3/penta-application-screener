"""Shared plumbing for the eval-cockpit endpoints (the /evals package).

The streaming scaffold, the concurrency helpers, the per-case fan-out, the EvalRun persister,
and the small display/version helpers — used by ``runs`` (the streaming pass endpoints) and
``catalog`` (last-run rehydration). Split out so each endpoint module stays about its own
routes, not the machinery under them.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Iterator
from typing import Any

from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.problems import Problem
from app.db.models import EvalRun
from app.evals.case_store import UnknownEvalError, list_cases
from app.schemas.base import ResponseModel
from app.schemas.evals import StabilityRun
from app.schemas.events import EvalSummaryEvent, ThinkingEvent, emit

# Default K for a stability run when the UI doesn't override it (K≥5 to trust a "stable"
# verdict, per the CLI habit), bounded so the default run's cost is predictable.
DEFAULT_STABILITY_K = 5


def persist(db: Session, eval_key: str, prompt_version: str, result: ResponseModel, thinking: str) -> None:
    """Record one run as an EvalRun row. Best-effort — a persistence failure must not fail
    the run (the result already streamed to the user)."""
    try:
        db.add(EvalRun(
            eval_key=eval_key,
            prompt_version=prompt_version,
            result=result.model_dump(by_alias=True),
            thinking=thinking or None,
        ))
        db.commit()
    except Exception:  # telemetry write; never propagate
        db.rollback()


def runs_out(report) -> list[StabilityRun]:
    """The per-run outcome+reasoning of a stability report, as wire shapes. Shared by every
    live pass so a flip carries the model's own 'why' for each of the K runs."""
    return [StabilityRun(outcome=r.outcome, detail=r.detail) for r in report.runs]


def stream(db: Session, eval_key: str, prompt_version: str, work) -> StreamingResponse:
    """Shared streaming scaffold (mirrors the Rank job): run ``work(on_delta)`` on a worker
    thread, drain its reasoning deltas to NDJSON ``thinking`` lines, then emit the terminal
    ``EvalSummaryEvent`` with the structured result, persisting the run to an EvalRun row.

    ``work`` receives ``on_delta`` (append a reasoning delta) and must return a
    ``ResponseModel``. Model calls block, so they run off-thread; a generator can't yield
    from the provider's ``on_delta`` callback, hence the queue. The request-scoped ``db``
    lives for the whole stream (as the Rank job's does), so persistence uses it directly."""
    def gen() -> Iterator[str]:
        q: queue.Queue[str | None] = queue.Queue()
        thinking_parts: list[str] = []
        outcome: dict[str, Any] = {}

        def on_delta(text: str) -> None:
            q.put(text)

        def do_work() -> None:
            try:
                outcome["result"] = work(on_delta)
            except Exception as exc:  # surfaced as a stream error below
                outcome["error"] = exc
            finally:
                q.put(None)

        worker = threading.Thread(target=do_work, daemon=True)
        worker.start()
        while True:
            item = q.get()
            if item is None:
                break
            thinking_parts.append(item)
            yield emit(ThinkingEvent(phase=eval_key, text=item))
        worker.join()

        if "error" in outcome:
            from app.schemas.events import ErrorEvent
            yield emit(ErrorEvent(phase=eval_key, message=f"{type(outcome['error']).__name__}: {outcome['error']}"))
            return
        result: ResponseModel = outcome["result"]
        persist(db, eval_key, prompt_version, result, "".join(thinking_parts))
        yield emit(EvalSummaryEvent(eval=eval_key, result=result.model_dump(by_alias=True)))

    return StreamingResponse(gen(), media_type="application/x-ndjson")


def select(items: list, case: str | None, key):
    """Filter a case list to a single ``case`` key when given (for a per-row run), or return
    all. 404 if the key is unknown — a stray key shouldn't silently run the whole set."""
    if case is None:
        return items
    picked = [it for it in items if key(it) == case]
    if not picked:
        raise Problem("not_found", detail=f"No case with key {case!r}.")
    return picked


def case_workers(settings, *, fan_out: int = 1) -> int:
    """How many cases to run concurrently. Governed by the SAME ``settings.max_workers`` knob
    Rank already runs at (default 50) — the system's proven ceiling — so there's one concurrency
    dial, not a second. ``fan_out`` is the per-case inner concurrency: a STABILITY case fans out
    K model calls of its own, so we divide by K to keep TOTAL in-flight calls (cases × K) under
    the ceiling; a plain run (one call per case) passes fan_out=1 and gets the full width."""
    return max(1, settings.ai.max_workers // max(1, fan_out))


def over_cases(cases: list, run_case_fn, *, on_delta, max_workers: int) -> list:
    """Run ``run_case_fn(case, case_on_delta)`` for each case CONCURRENTLY (bounded by
    ``max_workers`` — see ``case_workers``), returning results in the ORIGINAL case order. Each
    case gets its own buffered ``case_on_delta``; when a case finishes, its whole buffer is
    flushed to the real ``on_delta`` as ONE block, so cases never interleave in the thinking box
    even though they run in parallel (and only this thread ever writes the stream — the per-case
    fns write to their own buffers). For a stability case, within-case K-parallelism still applies
    inside ``run_case_fn`` (run_stability's own pool).

    Flushing is AS-COMPLETED: each case's block streams the instant that case finishes, so the
    thinking box fills as fast as work lands — a fast case never waits behind a slow predecessor.
    Block order is therefore completion order, not case order; that's fine because nothing
    downstream depends on narration order (each block is self-labelled with its case key) and the
    returned RESULTS are still re-sorted to case order below (the frontend keys per-case output by
    ``key``, and agreement is an order-independent aggregate — so results order is only tidiness)."""
    from app.ai.analysis import run_in_pool

    def work(indexed):
        i, c = indexed
        buf: list[str] = []
        result = run_case_fn(c, buf.append)
        return i, result, buf

    slots: dict[int, object] = {}
    for _item, packed, err in run_in_pool(
        list(enumerate(cases)), call=work, max_workers=min(max_workers, len(cases) or 1)
    ):
        if err is not None:
            raise err
        i, result, buf = packed
        slots[i] = result
        for line in buf:  # flush this case's block immediately, the moment it completes
            on_delta(line)

    return [slots[i] for i in range(len(cases))]


def current_prompt_version(eval_key: str, db: Session) -> str:
    """The prompt version a fresh run of ``eval_key`` would exercise right now — so a
    rehydrated last run can be flagged stale when the prompt has since changed. Judge and
    stability share the judge prompt; scoring uses the scoring prompt."""
    from app.services.settings import get_app_settings

    if eval_key in ("scoring", "scoring_stability"):
        from app.ai.dimension_scoring import PROMPT_VERSION as SCORING_PROMPT_VERSION

        return SCORING_PROMPT_VERSION
    if eval_key in ("consolidation", "consolidation_stability"):
        from app.ai.dimension_consolidate import (
            PROMPT_VERSION as CONSOLIDATE_PROMPT_VERSION,
        )

        return CONSOLIDATE_PROMPT_VERSION
    if eval_key in ("matching", "matching_stability"):
        from app.ai.dimension_matching import PROMPT_VERSION as MATCH_PROMPT_VERSION

        return MATCH_PROMPT_VERSION
    if eval_key in ("decomposition", "decomposition_stability"):
        from app.ai.dimension_decompose import (
            PROMPT_VERSION as DECOMPOSE_PROMPT_VERSION,
        )

        return DECOMPOSE_PROMPT_VERSION
    if eval_key in ("screening", "screening_stability"):
        from app.ai.screening import screening_prompt_version

        return screening_prompt_version(get_app_settings(db))
    if eval_key in ("judge", "stability"):
        from app.evals.judge import prompt_version as judge_prompt_version

        return judge_prompt_version()
    return ""


def live_case_keys(run_key: str) -> set[str] | None:
    """The case keys that CURRENTLY exist for a run key's pass, for filtering a merged
    historical last-run (so a renamed/removed case can't resurrect). ``run_key`` may be a live
    eval or its ``_stability`` sibling (same golden set), or judge/stability (the aggregated
    set). None ⇒ no editable case set for this key (don't filter)."""
    base = run_key.removesuffix("_stability")
    case_key = "judge" if base in ("judge", "stability") else base
    try:
        return {c["key"] for c in list_cases(case_key) if "key" in c}
    except UnknownEvalError:
        return None


def seed_str(expected: object) -> str:
    """A compact display token for a case's human label, for the stability ``seed`` field.
    Categorical labels are strings; scoring/screening labels are dicts (a band or fires/absent),
    which we render as a short key summary."""
    from app.evals.screening import fire_label as screening_fire_label

    if isinstance(expected, str):
        return expected
    if isinstance(expected, dict):
        if "fires" in expected or "absent" in expected:
            # A fire entry may be a nested list — an "at least one of" group (e.g.
            # ["pet_policy", "other"]) — which screening_fire_label renders as "a | b". Joining
            # it as a bare str would throw (the judge-stability seed bug for the velociraptor case).
            parts = []
            if expected.get("fires"):
                parts.append("fires: " + ", ".join(screening_fire_label(f) for f in expected["fires"]))
            if expected.get("absent"):
                parts.append("absent: " + ", ".join(expected["absent"]))
            return " · ".join(parts) or "clean"
        lo, hi = expected.get("score_min", "-1"), expected.get("score_max", "1")
        conf = f" {expected['confidence']}" if "confidence" in expected else ""
        return f"[{lo}, {hi}]{conf}"
    return str(expected)
