"""Run one full synthetic Rank on an isolated copy of the local database."""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from app.ai.model_catalog import MODEL_IDS_BY_ROUTE, model_spec
from app.ai.pass_catalog import AI_PASS_CATALOG
from app.ai.strands_provider import StrandsProvider
from app.api.ranking.run import rank_run
from app.core.config import get_settings
from app.db.models import Analysis, RunCostLedger, User, UserRole
from app.evals.fixture import _to_json, build_fixture, load
from app.evals.invariants import run_invariants
from app.schemas.settings import AISettings, effective_reasoning_effort
from app.services.applications.scope import opening_ai_applications
from app.services.settings import get_app_settings, save_app_settings

CONFIGURATIONS = {
    "bedrock-control": {
        "models": {
            "discovery_model": MODEL_IDS_BY_ROUTE["bedrock"]["sonnet"],
            "decompose_model": MODEL_IDS_BY_ROUTE["bedrock"]["sonnet"],
            "match_model": MODEL_IDS_BY_ROUTE["bedrock"]["sonnet"],
            "dimension_scoring_model": MODEL_IDS_BY_ROUTE["bedrock"]["haiku"],
            "consolidate_model": MODEL_IDS_BY_ROUTE["bedrock"]["sonnet"],
        },
        "reasoning": {},
    },
    "bedrock-candidate": {
        "models": {
            "discovery_model": MODEL_IDS_BY_ROUTE["bedrock"]["terra"],
            "decompose_model": MODEL_IDS_BY_ROUTE["bedrock"]["terra"],
            "match_model": MODEL_IDS_BY_ROUTE["bedrock"]["terra"],
            "dimension_scoring_model": MODEL_IDS_BY_ROUTE["bedrock"]["luna"],
            "consolidate_model": MODEL_IDS_BY_ROUTE["bedrock"]["terra"],
        },
        "reasoning": {
            MODEL_IDS_BY_ROUTE["bedrock"]["luna"]: "low",
            MODEL_IDS_BY_ROUTE["bedrock"]["terra"]: "low",
        },
    },
    "direct-control": {
        "models": {
            "discovery_model": MODEL_IDS_BY_ROUTE["direct"]["sonnet"],
            "decompose_model": MODEL_IDS_BY_ROUTE["direct"]["sonnet"],
            "match_model": MODEL_IDS_BY_ROUTE["direct"]["sonnet"],
            "dimension_scoring_model": MODEL_IDS_BY_ROUTE["direct"]["haiku"],
            "consolidate_model": MODEL_IDS_BY_ROUTE["direct"]["sonnet"],
        },
        "reasoning": {},
    },
    "direct-candidate": {
        "models": {
            "discovery_model": MODEL_IDS_BY_ROUTE["direct"]["terra"],
            "decompose_model": MODEL_IDS_BY_ROUTE["direct"]["terra"],
            "match_model": MODEL_IDS_BY_ROUTE["direct"]["terra"],
            "dimension_scoring_model": MODEL_IDS_BY_ROUTE["direct"]["luna"],
            "consolidate_model": MODEL_IDS_BY_ROUTE["direct"]["terra"],
        },
        "reasoning": {
            MODEL_IDS_BY_ROUTE["direct"]["luna"]: "low",
            MODEL_IDS_BY_ROUTE["direct"]["terra"]: "low",
        },
    },
}


def _reasoning_for(config: dict[str, Any], override: str | None) -> dict[str, str]:
    if override is None:
        return config["reasoning"]
    return {
        model: override
        for model in set(config["models"].values())
        if model_spec(model).supports_reasoning_effort
    }


async def _consume(response: Any) -> list[dict[str, Any]]:
    events = []
    async for chunk in response.body_iterator:
        text = chunk.decode() if isinstance(chunk, bytes) else chunk
        for line in text.splitlines():
            if line.strip():
                events.append(json.loads(line))
    return events


def snapshot_database(source_db: Path, work_db: Path) -> None:
    """Capture committed SQLite state, including the WAL, without changing the source."""
    source_db = source_db.resolve(strict=True)
    work_db = work_db.resolve()
    if source_db == work_db:
        raise ValueError("The experiment database must be distinct from its source")
    work_db.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents overwriting another experiment or the source via a link.
    with work_db.open("xb"):
        pass
    with closing(sqlite3.connect(f"{source_db.as_uri()}?mode=ro", uri=True)) as source:
        with closing(sqlite3.connect(work_db)) as target:
            source.backup(target)


def run_rank_copy(
    *,
    source_db: Path,
    work_db: Path,
    configuration: str,
    opening_id: int,
    region: str,
    max_workers: int | None = None,
    openai_reasoning_effort: str | None = None,
) -> dict[str, Any]:
    """Copy the synthetic DB, run Rank against the copy, and return a PII-free artifact."""
    snapshot_database(source_db, work_db)
    engine = create_engine(f"sqlite:///{work_db}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    try:
        config = CONFIGURATIONS[configuration]
        runtime = get_settings()
        reasoning = _reasoning_for(config, openai_reasoning_effort)
        with Session(engine) as db:
            settings = get_app_settings(db)
            ai_updates = config["models"] | {"spending_cap_usd": 100.0}
            if max_workers is not None:
                ai_updates["max_workers"] = max_workers
            for spec in AI_PASS_CATALOG:
                model = config["models"].get(spec.model_attr)
                if model in reasoning:
                    ai_updates[spec.reasoning_attr] = reasoning[model]
            ai = AISettings.model_validate(settings.ai.model_dump() | ai_updates)
            settings = settings.model_copy(update={"ai": ai})
            save_app_settings(db, settings)

            user = db.scalar(
                select(User).where(User.role == UserRole.ADMIN, User.is_active.is_(True)).limit(1)
            )
            if user is None:
                raise RuntimeError("The synthetic database has no active admin to attribute Rank.")
            before_ledger_id = db.scalar(select(func.max(RunCostLedger.id))) or 0
            before_analysis_id = db.scalar(select(func.max(Analysis.id))) or 0
            accepted_models = {name: getattr(ai, name) for name in config["models"]}
            accepted_reasoning = {
                spec.key: effective_reasoning_effort(getattr(ai, spec.model_attr), getattr(ai, spec.reasoning_attr))
                for spec in AI_PASS_CATALOG if spec.model_attr in accepted_models
            }
            provider = StrandsProvider(
                region=region,
                max_pool_connections=ai.max_workers,
                openai_api_key=runtime.openai_api_key,
                anthropic_api_key=runtime.anthropic_api_key,
                openai_reasoning_efforts=reasoning,
            )
            started = time.perf_counter()
            events = asyncio.run(_consume(rank_run(opening_id=opening_id, user=user, db=db, provider=provider)))
            wall_clock_seconds = time.perf_counter() - started

            errors = [event for event in events if event.get("type") == "error"]
            ledger = db.scalar(
                select(RunCostLedger)
                .where(RunCostLedger.id > before_ledger_id, RunCostLedger.kind == "rank", RunCostLedger.opening_id == opening_id)
                .order_by(RunCostLedger.id.desc())
                .limit(1)
            )
            if ledger is None:
                raise RuntimeError(f"Rank produced no cost ledger; stream errors: {errors}")
            if errors or ledger.status != "completed":
                raise RuntimeError(f"Rank did not complete; stream errors: {errors}")
            analysis = db.scalar(select(Analysis).where(
                Analysis.id > before_analysis_id, Analysis.opening_id == opening_id
            ).order_by(Analysis.id.desc()).limit(1))
            if analysis is None:
                raise RuntimeError("Rank produced no new analysis for the selected opening.")
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
                "opening_id": opening_id,
                "models": accepted_models,
                "reasoning": accepted_reasoning,
                "source_application_count": len(opening_ai_applications(db, opening_id)),
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

    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", type=Path, default=Path("data/penta_screener.db"))
    parser.add_argument("--work-db", type=Path, required=True)
    parser.add_argument("--opening-id", type=int, required=True)
    parser.add_argument("--configuration", choices=tuple(CONFIGURATIONS), required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument(
        "--workers", type=int, choices=range(1, 51),
        help="Override the copied database's AI worker limit for this isolated run.",
    )
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
        opening_id=args.opening_id,
        region=args.region,
        max_workers=args.workers,
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
