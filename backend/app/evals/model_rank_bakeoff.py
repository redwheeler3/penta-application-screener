"""Run one full synthetic Rank on an isolated copy of the local database for M20."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from app.ai.strands_provider import StrandsProvider
from app.api.ranking.run import rank_run
from app.core.config import get_settings
from app.db.models import Application, RunCostLedger, User, UserRole
from app.evals.fixture import _to_json, build_fixture, load
from app.evals.invariants import run_invariants
from app.evals.model_bakeoff import HAIKU, LUNA, SONNET, TERRA
from app.services.analysis import get_current_analysis
from app.services.settings import get_app_settings, save_app_settings

CONFIGURATIONS = {
    "control": {
        "models": {
            "discovery_model": SONNET,
            "decompose_model": SONNET,
            "match_model": SONNET,
            "dimension_scoring_model": HAIKU,
            "consolidate_model": SONNET,
        },
        "reasoning": {},
    },
    "candidate": {
        "models": {
            "discovery_model": TERRA,
            "decompose_model": TERRA,
            "match_model": TERRA,
            "dimension_scoring_model": LUNA,
            "consolidate_model": TERRA,
        },
        "reasoning": {LUNA: "low", TERRA: "low"},
    },
}


def _reasoning_for(config: dict[str, Any], override: str | None) -> dict[str, str]:
    if override is None:
        return config["reasoning"]
    return {
        model: override
        for model in set(config["models"].values())
        if model.startswith("openai.")
    }


async def _consume(response: Any) -> list[dict[str, Any]]:
    events = []
    async for chunk in response.body_iterator:
        text = chunk.decode() if isinstance(chunk, bytes) else chunk
        for line in text.splitlines():
            if line.strip():
                events.append(json.loads(line))
    return events


def run_rank_copy(
    *,
    source_db: Path,
    work_db: Path,
    configuration: str,
    region: str,
    openai_reasoning_effort: str | None = None,
) -> dict[str, Any]:
    """Copy the synthetic DB, run Rank against the copy, and return a PII-free artifact."""
    work_db.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_db, work_db)
    engine = create_engine(f"sqlite:///{work_db}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    config = CONFIGURATIONS[configuration]
    reasoning = _reasoning_for(config, openai_reasoning_effort)
    with Session(engine) as db:
        settings = get_app_settings(db)
        ai = settings.ai.model_copy(update=config["models"] | {"spending_cap_usd": 100.0})
        settings = settings.model_copy(update={"ai": ai})
        save_app_settings(db, settings)

        user = db.scalar(
            select(User).where(User.role == UserRole.ADMIN, User.is_active.is_(True)).limit(1)
        )
        if user is None:
            raise RuntimeError("The synthetic database has no active admin to attribute Rank.")
        before_ledger_id = db.scalar(select(func.max(RunCostLedger.id))) or 0
        provider = StrandsProvider(
            region=region,
            max_pool_connections=ai.max_workers,
            openai_reasoning_efforts=reasoning,
        )
        # The endpoint's post-Rank safety copy should follow the isolated DB, but adds no
        # value here because this file is already the disposable copy.
        runtime_settings = get_settings()
        old_backup_setting = runtime_settings.local_db_backups
        runtime_settings.local_db_backups = False
        started = time.perf_counter()
        try:
            events = asyncio.run(_consume(rank_run(user=user, db=db, provider=provider)))
        finally:
            runtime_settings.local_db_backups = old_backup_setting
        wall_clock_seconds = time.perf_counter() - started

        errors = [event for event in events if event.get("type") == "error"]
        ledger = db.scalar(
            select(RunCostLedger)
            .where(RunCostLedger.id > before_ledger_id, RunCostLedger.kind == "rank")
            .order_by(RunCostLedger.id.desc())
            .limit(1)
        )
        if ledger is None:
            raise RuntimeError(f"Rank produced no cost ledger; stream errors: {errors}")
        analysis = get_current_analysis(db)
        if analysis is None:
            raise RuntimeError("Rank completed without a current analysis.")
        fixture = build_fixture(db, analysis)
        baseline = load()
        violations = run_invariants(fixture)
        summary_event = next(
            (event for event in reversed(events) if event.get("type") == "summary"), None
        )
        return {
            "experiment": "M20 production-shaped synthetic Rank",
            "created_at": datetime.now(UTC).isoformat(),
            "configuration": configuration,
            "region": region,
            "models": config["models"],
            "reasoning": reasoning,
            "source_application_count": db.scalar(select(func.count()).select_from(Application)),
            "wall_clock_seconds": wall_clock_seconds,
            "stream_summary": summary_event,
            "stream_errors": errors,
            "passes": [
                {
                    "label": row.label,
                    "model": row.model_id,
                    "calls": row.calls,
                    "input_tokens": row.input_tokens,
                    "output_tokens": row.output_tokens,
                    "cost_usd": row.cost_usd,
                    "cached_count": row.cached_count,
                    "failed_calls": row.failed_calls,
                    "duration_ms": row.duration_ms,
                }
                for row in ledger.passes
            ],
            "invariant_violations": [violation.__dict__ for violation in violations],
            "comparison": {
                "dimensions": len(fixture.dimensions),
                "baseline_dimensions": len(baseline.dimensions),
                "shared_dimension_keys": len(
                    {d["key"] for d in fixture.dimensions}
                    & {d["key"] for d in baseline.dimensions}
                ),
                "score_vectors": len(fixture.score_vectors),
                "baseline_score_vectors": len(baseline.score_vectors),
            },
            "fixture": _to_json(fixture),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", type=Path, default=Path("data/penta_screener.db"))
    parser.add_argument("--work-db", type=Path, required=True)
    parser.add_argument("--configuration", choices=tuple(CONFIGURATIONS), required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument(
        "--openai-reasoning-effort",
        choices=("none", "low", "medium", "high", "xhigh", "max"),
        help="Override reasoning for every OpenAI model in this isolated run.",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_rank_copy(
        source_db=args.source_db,
        work_db=args.work_db,
        configuration=args.configuration,
        region=args.region,
        openai_reasoning_effort=args.openai_reasoning_effort,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "configuration", "wall_clock_seconds", "stream_summary", "passes",
        "invariant_violations", "comparison",
    )}, indent=2))


if __name__ == "__main__":
    main()
