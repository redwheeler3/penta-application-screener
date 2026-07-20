"""The in-UI eval cockpit endpoints (/evals).

Catalog + invariants are free (no model calls) and return plain JSON. The three run
endpoints stream NDJSON — reasoning `thinking` lines then a terminal `summary` carrying
the structured result — and persist an EvalRun row. A MockProvider stands in for Bedrock,
routing by output schema (scoring vs. judge), so these exercise the real router + runner
wiring without spend.
"""

import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.mock_provider import MockProvider
from app.ai.schemas import (
    DimensionScore,
    DimensionScoringReport,
    JudgeReport,
    JudgeVerdict,
    ScoreConfidence,
)
from app.api.dependencies import get_ai_provider, require_current_user
from app.db.models import Base, EvalRun, User, UserRole
from app.db.session import get_db
from app.main import create_app

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def setup_app():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    user = User(email="m@x.com", display_name="M", role=UserRole.MEMBER, is_active=True)
    db.add(user)
    db.commit()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_current_user] = lambda: user
    provider = MockProvider()
    app.dependency_overrides[get_ai_provider] = lambda: provider
    return app, db, provider


async def _stream_events(client: AsyncClient, url: str) -> list[dict]:
    events: list[dict] = []
    async with client.stream("POST", url) as resp:
        assert resp.status_code == 200
        async for line in resp.aiter_lines():
            if line.strip():
                events.append(json.loads(line))
    return events


def test_seed_str_renders_any_of_fires_group() -> None:
    """_seed_str feeds the judge-stability `seed` field for every case. A screening `fires`
    entry can be a nested 'at least one of' list (e.g. [["pet_policy", "other"]]) — joining it
    as a bare str used to throw 'expected str instance, list found' when Run Stability hit the
    velociraptor case. It must render the group as 'a | b'."""
    from app.api.evals import _seed_str

    assert _seed_str({"fires": [["pet_policy", "other"]], "absent": []}) == "fires: pet_policy | other"
    assert _seed_str({"fires": ["pet_policy"], "absent": ["fake_contact"]}) == (
        "fires: pet_policy · absent: fake_contact"
    )
    assert _seed_str({"fires": [], "absent": []}) == "clean"
    assert _seed_str("merge") == "merge"  # categorical label passes through


async def test_catalog_lists_evals_with_spend_flags() -> None:
    app, _db, _p = setup_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        body = (await client.get("/evals/catalog")).json()
    by_key = {e["key"]: e for e in body["evals"]}
    assert by_key["invariants"]["spends"] is False
    assert by_key["invariants"]["estimatedCalls"] == 0
    # Spending evals report a positive call estimate for the UI's confirm dialog.
    assert by_key["scoring"]["spends"] is True
    assert by_key["scoring"]["estimatedCalls"] > 0
    assert by_key["stability"]["estimatedCalls"] > by_key["judge"]["estimatedCalls"]


async def test_invariants_run_free_over_the_fixture() -> None:
    app, _db, _p = setup_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        body = (await client.get("/evals/invariants")).json()
    # The committed baseline fixture is green, so every invariant passes.
    assert body["hasFixture"] is True
    assert body["invariants"], "no invariants reported"
    assert all(inv["passed"] for inv in body["invariants"])


async def test_scoring_streams_thinking_then_summary_and_persists() -> None:
    app, db, provider = setup_app()
    # Every scoring call returns a neutral (0) score for the dimension it was asked about;
    # route by schema so scoring and judge calls are disambiguated.
    provider.route(
        "<dimensions>",
        DimensionScoringReport(scores=[]),  # empty -> "model returned no score" failure path
    )
    provider.route(
        "cited_evidence",
        JudgeReport(verdict=JudgeVerdict.SUPPORTED, reason="ok"),
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        events = await _stream_events(client, "/evals/scoring")
    kinds = [e["type"] for e in events]
    assert "thinking" in kinds  # reasoning streamed
    summary = next(e for e in events if e["type"] == "summary")
    assert summary["eval"] == "scoring"
    assert summary["result"]["total"] >= 1
    # Persisted exactly one EvalRun row for this run.
    rows = list(db.scalars(select(EvalRun).where(EvalRun.eval_key == "scoring")))
    assert len(rows) == 1
    assert rows[0].result["total"] == summary["result"]["total"]


async def test_scoring_grades_a_real_score() -> None:
    app, _db, provider = setup_app()
    # A dimension gets a concrete neutral score; the harness's assertions then grade it.
    def scored(_schema=None):
        return DimensionScoringReport(scores=[
            DimensionScore(dimension_key=k, score=0.0, rationale="r",
                           evidence="not addressed", confidence=ScoreConfidence.LOW)
            for k in [
                "licensed_trade_skills", "available_time_for_coop_work",
                "governance_board_experience",
            ]
        ])
    # Route both dimensions' scoring calls to a neutral score, judge calls to supported.
    provider.route("<dimensions>", scored())
    provider.route("cited_evidence", JudgeReport(verdict=JudgeVerdict.SUPPORTED, reason="ok"))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        events = await _stream_events(client, "/evals/scoring")
    summary = next(e for e in events if e["type"] == "summary")
    # An absence case scored 0.0 should pass its assertion; the result carries per-case rows.
    assert summary["result"]["cases"], "no cases in result"
    assert all("score" in c for c in summary["result"]["cases"])


async def test_scoring_runs_a_single_case() -> None:
    app, _db, provider = setup_app()
    provider.route("<dimensions>", DimensionScoringReport(scores=[]))
    provider.route("cited_evidence", JudgeReport(verdict=JudgeVerdict.SUPPORTED, reason="ok"))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        events = await _stream_events(client, "/evals/scoring?case=absence_scores_neutral")
    summary = next(e for e in events if e["type"] == "summary")
    # Only the requested case ran.
    assert summary["result"]["total"] == 1
    assert summary["result"]["cases"][0]["key"] == "absence_scores_neutral"


async def test_run_unknown_case_is_404() -> None:
    app, _db, _p = setup_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.post("/evals/scoring?case=does_not_exist")
    assert resp.status_code == 404


async def test_harvest_unknown_family_is_404() -> None:
    app, _db, _p = setup_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.get("/evals/harvest/nonsense")
    assert resp.status_code == 404


async def test_harvest_requires_a_current_run() -> None:
    # Harvest proposes cases from the CURRENT run; with none in the DB it's a 409, never a
    # silent empty list (and it never reaches the synthetic-pool guard without a run).
    app, _db, _p = setup_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.get("/evals/harvest/scoring")
    assert resp.status_code == 409


async def test_rebaseline_requires_a_current_run() -> None:
    # Re-baseline records the CURRENT Rank's fixture; with no run in the DB it's a 409
    # (run_required), never a silent empty write.
    app, _db, _p = setup_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.post("/evals/baseline")
    assert resp.status_code == 409


async def test_run_requires_login() -> None:
    app, _db, _p = setup_app()
    app.dependency_overrides.pop(require_current_user)  # simulate logged-out
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.post("/evals/scoring")
    assert resp.status_code == 401


async def test_last_run_is_empty_before_any_run() -> None:
    app, _db, _p = setup_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        body = (await client.get("/evals/last-run?keys=judge,stability")).json()
    assert body["runs"] == []


async def test_last_run_returns_newest_PER_KEY_not_one_across_keys() -> None:
    app, db, _p = setup_app()
    # Two keys, two runs each (the second of each is newer by insertion order). The tab must
    # restore BOTH keys' newest — not just whichever ran last overall — so live + stability
    # results coexist rather than clobbering each other.
    for ek, n in [("judge", 1), ("stability", 2), ("judge", 3), ("stability", 4)]:
        db.add(EvalRun(eval_key=ek, prompt_version="v", result={"n": n}, thinking="t"))
        db.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        body = (await client.get("/evals/last-run?keys=judge,stability")).json()
    by_key = {r["evalKey"]: r for r in body["runs"]}
    assert set(by_key) == {"judge", "stability"}
    assert by_key["judge"]["result"] == {"n": 3}  # newest judge, not overwritten by stability
    assert by_key["stability"]["result"] == {"n": 4}
    assert all(r["ranAt"] for r in body["runs"])


async def test_last_run_omits_a_key_with_no_run() -> None:
    app, db, _p = setup_app()
    db.add(EvalRun(eval_key="judge", prompt_version="v", result={}, thinking=None))
    db.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        body = (await client.get("/evals/last-run?keys=judge,stability")).json()
    assert [r["evalKey"] for r in body["runs"]] == ["judge"]  # stability has no run → omitted


async def test_last_run_flags_a_stale_prompt() -> None:
    # A run whose stored prompt no longer matches the current judge prompt is flagged stale,
    # so a rehydrated result can't be mistaken for one produced by the prompt in effect now.
    app, db, _p = setup_app()
    db.add(EvalRun(eval_key="judge", prompt_version="stale-version", result={}, thinking=None))
    db.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        body = (await client.get("/evals/last-run?keys=judge")).json()
    run = body["runs"][0]
    assert run["stale"] is True
    assert run["currentPromptVersion"]  # the real judge prompt version


async def test_get_cases_reads_the_fixture() -> None:
    app, _db, _p = setup_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        body = (await client.get("/evals/cases/scoring")).json()
    assert body["evalKey"] == "scoring"
    assert body["cases"]
    assert all("key" in c for c in body["cases"])


async def test_get_cases_404_for_non_editable_eval() -> None:
    app, _db, _p = setup_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.get("/evals/cases/invariants")
    assert resp.status_code == 404


async def test_put_case_rejects_invalid_payload_without_writing() -> None:
    # A payload missing required fields is refused (422) — the store validates before any
    # write, so the committed fixture is never touched by a bad request.
    app, _db, _p = setup_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.put("/evals/cases/scoring", json={"case": {"key": "x"}})
    assert resp.status_code == 422
