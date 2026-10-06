"""Fixture scope/provenance and complete-file publication, using synthetic data only."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest
from sqlalchemy import select

from app.db.models import (
    Application,
    ApplicationAIResult,
    ApplicationAISelection,
    RunCostLedger,
    RunPassCost,
    User,
    UserRole,
)
from app.evals import fixture, fixture_files
from app.services.ranking.analysis import create_analysis
from tests.application_support import current_opening_id
from tests.db_support import add_selected_result
from tests.ranking_support import a_pattern_report, add_eligible, setup_app


def analysis(db, *, configuration=None):
    return create_analysis(db, user=db.scalar(select(User)), opening_id=current_opening_id(db),
        report=a_pattern_report(), narrative=None, inputs_fingerprint="synthetic", configuration=configuration)


def score(db, application, key, value, *, model="synthetic-model", version="synthetic-version"):
    return add_selected_result(db, ApplicationAIResult(producer_application_id=application.id,
        kind=f"dimension_scoring:{key}", cache_key=f"{application.id}:{key}", model_id=model,
        prompt_version=version, output={"score": value}))


def test_fixture_vectors_and_producer_metadata_use_only_scoped_consumer_selections():
    _app, db, _provider = setup_app(UserRole.ADMIN)
    consumer = add_eligible(db, email="consumer@example.com", raw_hash="consumer")
    current = analysis(db)
    key = a_pattern_report().dimensions[0].key
    outsider = Application(primary_email="outsider@example.com", raw_row={}, raw_row_hash="outside", normalized={})
    db.add(outsider)
    db.flush()
    shared = score(db, outsider, key, 0.75, model="selected-producer", version="selected-prompt")
    db.add(ApplicationAISelection(application_id=consumer.id, kind=shared.kind, result_id=shared.id))
    score(db, consumer, "unrelated", -0.4)
    db.commit()

    output = fixture.build_fixture(db, current)
    assert output.score_vectors == {key: [0.75]}
    assert output.provenance.pass_models == {"Dimension scoring": "selected-producer"}
    assert output.provenance.pass_prompt_versions == {"Dimension scoring": "selected-prompt"}


def test_captured_configuration_cannot_be_shifted_by_a_failed_ledger_or_current_prompt(monkeypatch):
    _app, db, _provider = setup_app(UserRole.ADMIN)
    add_eligible(db, email="synthetic@example.com", raw_hash="synthetic")
    db.add(RunCostLedger(kind="rank", status="failed", passes=[RunPassCost(
        label="Pattern discovery", model_id="failed-model", cost_usd=0, input_tokens=0,
        output_tokens=0, cached_count=0, duration_ms=0)]))
    db.commit()
    current = analysis(db, configuration={"passes": {"discovery": {
        "model": "captured-model", "prompt_version": "captured-prompt",
    }}})
    monkeypatch.setattr("app.ai.dimension_discovery.PROMPT_VERSION", "edited-prompt")
    output = fixture.build_fixture(db, current)
    assert output.provenance.pass_models == {"Pattern discovery": "captured-model"}
    assert output.provenance.pass_prompt_versions == {"Pattern discovery": "captured-prompt"}


def test_missing_historical_provenance_is_unknown_not_reconstructed():
    _app, db, _provider = setup_app(UserRole.ADMIN)
    add_eligible(db, email="synthetic@example.com", raw_hash="synthetic")
    output = fixture.build_fixture(db, analysis(db))
    assert output.provenance == fixture.Provenance()


def test_mixed_selected_score_sources_do_not_get_one_fabricated_model_or_prompt():
    _app, db, _provider = setup_app(UserRole.ADMIN)
    first = add_eligible(db, email="first@example.com", raw_hash="first")
    second = add_eligible(db, email="second@example.com", raw_hash="second")
    current = analysis(db)
    key = a_pattern_report().dimensions[0].key
    score(db, first, key, 0.2, model="first-model", version="first-prompt")
    score(db, second, key, 0.3, model="second-model", version="second-prompt")
    db.commit()
    output = fixture.build_fixture(db, current)
    assert output.score_vectors == {key: [0.2, 0.3]}
    assert "Dimension scoring" not in output.provenance.pass_models
    assert "Dimension scoring" not in output.provenance.pass_prompt_versions


def test_failed_baseline_publication_preserves_complete_previous_file(tmp_path, monkeypatch):
    _app, db, _provider = setup_app(UserRole.ADMIN)
    add_eligible(db, email="synthetic@example.com", raw_hash="synthetic")
    analysis(db)
    path = tmp_path / "rank_baseline.json"
    fixture.record(db, path)
    original = path.read_bytes()

    def fail_replace(_source, _target):
        # A reader sees the complete prior fixture while publication is pending.
        assert fixture.load(path).dimensions
        raise OSError("Synthetic publication failure")

    monkeypatch.setattr(fixture_files.os, "replace", fail_replace)
    with pytest.raises(OSError, match="Synthetic publication failure"):
        fixture.record(db, path)
    assert path.read_bytes() == original
    assert not list(tmp_path.glob("*.tmp"))
    json.loads(original)


def test_fixture_reader_closes_its_handle_before_replacement(tmp_path, monkeypatch):
    path = tmp_path / "shared.json"
    fixture_files.write_json(path, {"version": 1})
    held, release, waiting = Event(), Event(), Event()
    lock = fixture_files._file_lock(path)
    read_text = Path.read_text

    class ReportWaiting:
        def __enter__(self):
            if held.is_set() and not release.is_set():
                waiting.set()
            return lock.__enter__()

        def __exit__(self, *args):
            return lock.__exit__(*args)

    def hold_reader(target, *args, **kwargs):
        if target == path and not held.is_set():
            with target.open(encoding="utf-8") as handle:
                held.set()
                assert release.wait(5)
                return handle.read()
        return read_text(target, *args, **kwargs)

    monkeypatch.setattr(fixture_files, "_file_lock", lambda _path: ReportWaiting())
    monkeypatch.setattr(Path, "read_text", hold_reader)
    with ThreadPoolExecutor(max_workers=2) as pool:
        reader = pool.submit(fixture_files.read_json, path)
        try:
            assert held.wait(5)
            writer = pool.submit(fixture_files.write_json, path, {"version": 2})
            assert waiting.wait(5)
            assert not writer.done()
        finally:
            release.set()
        assert reader.result(timeout=5) == {"version": 1}
        writer.result(timeout=5)
    assert fixture_files.read_json(path) == {"version": 2}
