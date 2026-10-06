"""Experiment fidelity and complete, scoped restoration with no real model calls."""

import copy
import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select

from app.ai.schemas import (
    DimensionMatchReport,
    DimensionScoringReport,
    JudgeReport,
    JudgeVerdict,
)
from app.db.models import EvalRun
from app.evals import judge, reproduce
from app.evals.dataset import DatasetSnapshot, case_identity, load_dataset
from app.evals.paths import GOLDEN_FILES
from tests.test_evals_api import _stream_events, setup_app

pytestmark = pytest.mark.anyio


def local_corpus(tmp_path, monkeypatch):
    for family, source in list(GOLDEN_FILES.items()):
        target = tmp_path / source.name
        target.write_bytes(source.read_bytes())
        monkeypatch.setitem(GOLDEN_FILES, family, target)


async def test_catalog_reads_each_family_once(monkeypatch):
    from app.evals import dataset

    reads = []
    original = dataset.read_json

    def counted(path):
        reads.append(path)
        return original(path)

    monkeypatch.setattr(dataset, "read_json", counted)
    app, _db, _provider = setup_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/evals/catalog")).status_code == 200
    assert reads == list(GOLDEN_FILES.values())


async def test_judge_version_uses_captured_briefs_and_actual_guard(tmp_path, monkeypatch):
    local_corpus(tmp_path, monkeypatch)
    captured = load_dataset()
    version = judge.prompt_version(captured)
    cases = judge.load_cases(captured)
    path = GOLDEN_FILES["scoring"]
    changed = json.loads(path.read_text(encoding="utf-8"))
    changed["judge_background"] += " Changed synthetic brief."
    path.write_text(json.dumps(changed), encoding="utf-8")
    assert judge.prompt_version(captured) == version
    assert judge.load_cases(captured) == cases
    assert judge.prompt_version() != version
    monkeypatch.setattr(reproduce, "INJECTION_GUARD_NOTE", "A changed guard")
    assert judge.prompt_version(captured) != version


async def test_label_changes_expire_coverage_but_editorial_notes_do_not(tmp_path, monkeypatch):
    local_corpus(tmp_path, monkeypatch)
    app, _db, provider = setup_app()
    provider.route("", DimensionScoringReport(scores=[]))
    path = GOLDEN_FILES["scoring"]
    data = json.loads(path.read_text(encoding="utf-8"))
    key = data["cases"][0]["key"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        events = await _stream_events(client, f"/evals/scoring?case={key}")
        result = events[-1]["result"]
        assert result["experimentId"]
        original = result["cases"][0]["inputFingerprint"]
        data["cases"][0]["metadata"]["note"] = "Editorial explanation"
        data["cases"][0]["metadata"]["label_rationale"] = "Editorial rationale"
        path.write_text(json.dumps(data), encoding="utf-8")
        restored = (await client.get("/evals/last-run?keys=scoring")).json()["runs"][0]
        assert not restored["corpusStale"]
        assert restored["currentCaseFingerprints"][key] == original
        data["cases"][0]["metadata"]["expected"] = {"score_min": 0.7, "score_max": 1}
        path.write_text(json.dumps(data), encoding="utf-8")
        restored = (await client.get("/evals/last-run?keys=scoring")).json()["runs"][0]
        assert restored["corpusStale"]
        assert restored["currentCaseFingerprints"][key] != original
        assert restored["result"]["cases"][0]["inputFingerprint"] == original


@pytest.mark.parametrize("mode", ["run", "stability"])
async def test_judge_pair_identity_selects_and_restores_both_families(tmp_path, monkeypatch, mode):
    local_corpus(tmp_path, monkeypatch)
    for family in ("matching", "consolidation"):
        path = GOLDEN_FILES[family]
        data = json.loads(path.read_text(encoding="utf-8"))
        data["cases"][0]["key"] = "same-key"
        path.write_text(json.dumps(data), encoding="utf-8")
    app, _db, provider = setup_app()
    provider.route("", JudgeReport(verdict=JudgeVerdict.KEEP, reason="Synthetic decision"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post("/evals/judge?case=same-key")).status_code == 422
        for family in ("matching", "consolidation"):
            events = await _stream_events(client, f"/evals/judge?mode={mode}&k=2&case=same-key&passName={family}")
            assert [(case["passName"], case["key"]) for case in events[-1]["result"]["cases"]] == [(family, "same-key")]
        key = "stability" if mode == "stability" else "judge"
        restored = (await client.get(f"/evals/last-run?keys={key}")).json()["runs"][0]
        assert {(case["passName"], case["key"]) for case in restored["result"]["cases"]} == {
            ("matching", "same-key"), ("consolidation", "same-key"),
        }


async def test_stability_does_not_merge_different_repetition_counts():
    app, _db, provider = setup_app()
    provider.route("", DimensionMatchReport(matches=[]))
    keys = [case["key"] for case in load_dataset("matching").families["matching"]["cases"][:2]]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await _stream_events(client, f"/evals/matching?mode=stability&k=5&case={keys[0]}")
        await _stream_events(client, f"/evals/matching?mode=stability&k=2&case={keys[1]}")
        run = (await client.get("/evals/last-run?keys=matching_stability")).json()["runs"][0]
    assert run["result"]["k"] == 2
    assert [case["key"] for case in run["result"]["cases"]] == [keys[1]]


async def test_history_restores_all_cases_after_many_partial_runs_without_narration(monkeypatch):
    from app.api.evals import catalog

    app, db, _provider = setup_app()
    snapshot = load_dataset()
    version = judge.prompt_version(snapshot)
    fingerprints = snapshot.case_fingerprints("judge")
    for case in judge.load_cases(snapshot):
        outcome = {"key": case.key, "passName": case.pass_name, "marker": "[ok]",
                   "inputFingerprint": fingerprints[case_identity(case.key, case.pass_name)]}
        db.add(EvalRun(eval_key="judge", prompt_version=version,
                       result={"judgeModel": judge.DEFAULT_MODEL, "experimentId": "synthetic", "cases": [outcome]},
                       thinking="Unused narration" * 1000))
    db.commit()
    latest = db.scalar(select(EvalRun).order_by(EvalRun.id.desc()))
    for _ in range(75):
        db.add(EvalRun(eval_key="judge", prompt_version=version, result=latest.result, thinking="Unused"))
    db.commit()
    queries = []
    coverage_queries = []
    def record(_conn, _cursor, statement, _parameters, _context, _many):
        queries.append(statement)
        if "WITH valid_runs" in statement:
            coverage_queries.append((statement, _parameters))
    event.listen(db.get_bind(), "before_cursor_execute", record)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            run = (await client.get("/evals/last-run?keys=judge")).json()["runs"][0]
            assert len(run["result"]["cases"]) == len(fingerprints) > 30
            assert not run["corpusStale"]
            assert not any("thinking" in query for query in queries)
            changed = copy.deepcopy(snapshot.families)
            changed["scoring"]["cases"].pop(0)
            monkeypatch.setattr(catalog, "load_dataset", lambda: DatasetSnapshot(changed))
            run = (await client.get("/evals/last-run?keys=judge")).json()["runs"][0]
            assert len(run["result"]["cases"]) == len(fingerprints) - 1
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", record)
    statement, parameters = coverage_queries[0]
    plan = db.connection().exec_driver_sql("EXPLAIN QUERY PLAN " + statement, parameters).all()
    assert any("ix_eval_runs_experiment" in row[3] for row in plan)


async def test_judge_stream_stamps_the_brief_it_actually_used(tmp_path, monkeypatch):
    from app.api.evals import runs
    local_corpus(tmp_path, monkeypatch)
    original_version = judge.prompt_version()
    real_version = judge.prompt_version

    def edit_between_capture_and_version(snapshot):
        path = GOLDEN_FILES["matching"]
        data = json.loads(path.read_text(encoding="utf-8"))
        data["judge_background"] += " Edited after request capture."
        path.write_text(json.dumps(data), encoding="utf-8")
        return real_version(snapshot)

    monkeypatch.setattr(runs, "judge_prompt_version", edit_between_capture_and_version)
    key = load_dataset("matching").families["matching"]["cases"][0]["key"]
    app, db, provider = setup_app()
    provider.route("", JudgeReport(verdict=JudgeVerdict.KEEP, reason="Synthetic"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        events = await _stream_events(client, f"/evals/judge?case={key}&passName=matching")
    summary = next(event for event in events if event["type"] == "summary")
    assert summary["result"]["judgePromptVersion"] == original_version
    assert db.scalar(select(EvalRun)).prompt_version == original_version
    assert judge.prompt_version() != original_version


async def test_judge_version_includes_the_output_contract(monkeypatch):
    from pydantic import BaseModel

    from app.evals import matching
    class ChangedSchema(BaseModel):
        decision: str
    captured = load_dataset()
    original_version = judge.prompt_version(captured)
    original_request = matching.judge_request
    monkeypatch.setattr(matching, "judge_request", lambda given: (original_request(given)[0], ChangedSchema))
    assert judge.prompt_version(captured) != original_version


async def test_history_skips_non_json_narration_era_rows():
    from sqlalchemy import text

    from app.ai.dimension_scoring import PROMPT_VERSION
    app, db, provider = setup_app()
    key = load_dataset("scoring").families["scoring"]["cases"][0]["key"]
    db.execute(text("INSERT INTO eval_runs (eval_key, prompt_version, result) VALUES (:key, :version, :result)"),
               {"key": "scoring", "version": PROMPT_VERSION,
                "result": '{"cases": [{"key": "synthetic", "score": NaN}]}'} )
    db.commit()
    provider.route("", DimensionScoringReport(scores=[]))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await _stream_events(client, f"/evals/scoring?case={key}")
        response = await client.get("/evals/last-run?keys=scoring")
    assert response.status_code == 200
    assert [case["key"] for case in response.json()["runs"][0]["result"]["cases"]] == [key]


async def test_whole_run_agreement_survives_history_reordering_and_contested_counts():
    from app.api.evals._shared import current_prompt_version
    app, db, _provider = setup_app()
    snapshot = load_dataset()
    cases = [{"key": case.key, "passName": case.pass_name, "marker": "[ok]"}
             for case in judge.load_cases(snapshot)[:2]]
    agreement = {"kappa": 1, "nScored": 2}
    db.add(EvalRun(eval_key="judge", prompt_version=judge.prompt_version(snapshot),
                   result={"judgeModel": judge.DEFAULT_MODEL, "experimentId": "whole",
                           "cases": list(reversed(cases)), "agreement": agreement}))
    matching_key = snapshot.families["matching"]["cases"][0]["key"]
    db.add(EvalRun(eval_key="matching", prompt_version=current_prompt_version("matching"),
                   result={"model": "synthetic", "experimentId": "contested", "passed": 1, "total": 1,
                           "cases": [{"key": matching_key, "passed": False, "contested": True}]}))
    db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        runs = (await client.get("/evals/last-run?keys=judge,matching")).json()["runs"]
    assert runs[0]["result"]["agreement"] == agreement
    assert runs[1]["result"]["passed"] == 1


@pytest.mark.parametrize("mode", ["run", "stability"])
@pytest.mark.parametrize("key", ["synthetic-café", "synthetic-🙂", 'synthetic-"quoted"\\key'])
async def test_unicode_scoped_identity_round_trips(tmp_path, monkeypatch, mode, key):
    local_corpus(tmp_path, monkeypatch)
    path = GOLDEN_FILES["matching"]
    data = json.loads(path.read_text(encoding="utf-8"))
    data["cases"][0]["key"] = key
    path.write_text(json.dumps(data), encoding="utf-8")
    app, _db, provider = setup_app()
    provider.route("", JudgeReport(verdict=JudgeVerdict.KEEP, reason="Synthetic"))
    from urllib.parse import urlencode
    query = urlencode({"mode": mode, "k": 2, "case": key, "passName": "matching"})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        events = await _stream_events(client, f"/evals/judge?{query}")
        summary = next(item for item in events if item["type"] == "summary")
        family = "stability" if mode == "stability" else "judge"
        run = (await client.get(f"/evals/last-run?keys={family}")).json()["runs"][0]
    assert summary["storedRunId"] == run["runId"]
    assert [case["key"] for case in run["result"]["cases"]] == [key]
    identity = json.dumps(["matching", key], separators=(",", ":"), ensure_ascii=False)
    assert run["result"]["cases"][0]["inputFingerprint"] == run["currentCaseFingerprints"][identity]
