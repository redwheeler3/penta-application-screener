import ast
import json
import runpy
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from alembic import command
from app.core.config import get_settings
from app.schemas.settings import AppSettings


def test_migrations_do_not_import_mutable_application_code():
    for path in (Path(__file__).parents[1] / "alembic/versions").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            modules = ([node.module or ""] if isinstance(node, ast.ImportFrom)
                       else [item.name for item in node.names] if isinstance(node, ast.Import) else [])
            assert not any(name == "app" or name.startswith("app.") for name in modules), path.name


@pytest.mark.parametrize("opening_count", [1, 2])
@pytest.mark.parametrize("restore", [False, True])
def test_populated_historical_openings_preserve_paid_history(tmp_path, opening_count, restore):
    from app.services.backup import create_backup, restore_backup

    engine = create_engine(f"sqlite:///{(tmp_path / 'historical.db').as_posix()}")
    backend = Path(__file__).parents[1]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "f0a1b2c3d4e5")
            for identity in range(1, opening_count + 1):
                connection.exec_driver_sql("INSERT INTO openings (id, unit_size_bedrooms, housing_charge_cents, application_open_date, application_close_date, move_in_date, intake_mode, published_at) VALUES (?, 2, 125000, '2026-01-01', '2099-10-31', '2099-11-30', 'applications', CURRENT_TIMESTAMP)", (identity,))
            connection.exec_driver_sql("INSERT INTO applications (id, primary_email, raw_row, raw_row_hash, normalized, submitted_at) VALUES (1, 'synthetic@example.test', '{}', 'synthetic', '{}', CURRENT_TIMESTAMP)")
            connection.exec_driver_sql("INSERT INTO application_participations (application_id, opening_id, applied_at) VALUES (1, 1, CURRENT_TIMESTAMP)")
            connection.exec_driver_sql("INSERT INTO analyses (id, dimension_report, rank_inputs_fingerprint) VALUES (1, '{\"dimensions\": []}', 'historical-fingerprint')")
            connection.exec_driver_sql("INSERT INTO analysis_audit (analysis_id, discovery_narrative) VALUES (1, 'Synthetic paid history')")
            connection.exec_driver_sql("INSERT INTO run_cost_ledger (kind, estimated_usd) VALUES ('rank', 0.25)")
        if restore:
            restore_backup(create_backup(engine=engine), engine=engine)
        else:
            with engine.begin() as connection:
                config.attributes["connection"] = connection
                command.upgrade(config, "head")
        with engine.connect() as connection:
            expected_owner = 1 if opening_count == 1 else None
            assert connection.exec_driver_sql("SELECT opening_id, rank_inputs_fingerprint FROM analyses").one() == (expected_owner, "historical-fingerprint")
            assert connection.exec_driver_sql("SELECT discovery_narrative FROM analysis_audit").scalar_one() == "Synthetic paid history"
            assert connection.exec_driver_sql("SELECT opening_id, estimated_usd FROM run_cost_ledger").one() == (expected_owner, 0.25)
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    finally:
        engine.dispose()


def test_monotonic_identity_migration_preserves_every_row_and_detaches_comparison(tmp_path, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from app.db.models import (
        RECORD_ID_FLOOR,
        ApplicantDraft,
        ApplicantDraftIntent,
        Application,
        ApplicationAISelection,
        BrowserSession,
        PasswordlessIdentityKind,
        User,
        UserRole,
    )

    backend = Path(__file__).parents[1]
    url = f"sqlite:///{(tmp_path / 'record-identity.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    engine = create_engine(url)
    try:
        config = Config(str(backend / "alembic.ini"))
        config.set_main_option("script_location", str(backend / "alembic"))
        command.upgrade(config, "9f0a1b2c3d4e")
        now = datetime.now(UTC)
        with Session(engine) as db:
            db.add_all([
                User(id=1, email="synthetic@example.com", display_name="Synthetic", role=UserRole.ADMIN),
                Application(id=2, primary_email="applicant@example.com", raw_row={}, raw_row_hash="synthetic", normalized={}),
            ])
            db.flush()
            db.add(ApplicantDraft(id=3, email="applicant@example.com", intent=ApplicantDraftIntent.SAVE,
                application_id=2, draft_token_hash="synthetic-draft", created_at=now, saved_at=now, expires_on=now.date() + timedelta(days=1)))
            db.flush()
            db.add_all([
                BrowserSession(id=4, identity_kind=PasswordlessIdentityKind.APPLICANT, application_id=2,
                    reconciliation_draft_id=3, token_hash="synthetic-session", created_at=now, last_activity_at=now,
                    idle_expires_at=now + timedelta(days=1), absolute_expires_at=now + timedelta(days=2)),
            ])
            db.flush()
            db.execute(text("INSERT INTO application_committee_notes (id, application_id, author_user_id, body) VALUES (5, 2, 1, 'Synthetic note')"))
            db.execute(text("INSERT INTO application_ai_results (id, application_id, kind, cache_key, model_id, prompt_version, output, input_tokens, output_tokens, cost_usd) VALUES (6, 2, 'screening', 'synthetic-result', 'synthetic', 'synthetic', '{\"flags\": []}', 100, 50, 0.1)"))
            db.add(ApplicationAISelection(application_id=2, kind="screening", result_id=6))
            db.commit()
        with engine.connect() as connection:
            tables = connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version'").scalars().all()
            columns = {name: ", ".join(f'"{row[1]}"' for row in connection.exec_driver_sql(f'PRAGMA table_info("{name}")')) for name in tables}
            before = {name: connection.exec_driver_sql(f'SELECT * FROM "{name}" ORDER BY rowid').all() for name in tables}
        command.upgrade(config, "head")
        with engine.begin() as connection:
            for name in tables:
                assert connection.exec_driver_sql(f'SELECT {columns[name] if name == "application_committee_notes" else "*"} FROM "{name}" ORDER BY rowid').all() == before[name]
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.exec_driver_sql("DELETE FROM applicant_drafts WHERE id=3")
            assert connection.exec_driver_sql("SELECT reconciliation_draft_id FROM browser_sessions WHERE id=4").scalar_one() is None
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        with Session(engine) as db:
            created = Application(primary_email="new@example.com", raw_row={}, raw_row_hash="new", normalized={})
            db.add(created)
            db.commit()
            first_id = created.id
            assert RECORD_ID_FLOOR < first_id < 2**53
            db.delete(created)
            db.commit()
            next_record = Application(primary_email="next@example.com", raw_row={}, raw_row_hash="next", normalized={})
            db.add(next_record)
            db.commit()
            assert next_record.id > first_id
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_failed_run_metadata_migration_preserves_existing_costs_and_unknown_units(tmp_path, monkeypatch) -> None:
    backend = Path(__file__).parents[1]
    url = f"sqlite:///{(tmp_path / 'failed-run-metadata.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    try:
        config = Config(str(backend / "alembic.ini"))
        config.set_main_option("script_location", str(backend / "alembic"))
        command.upgrade(config, "8e9f0a1b2c3d")
        engine = create_engine(url)
        with engine.begin() as connection:
            connection.exec_driver_sql("INSERT INTO run_cost_ledger (id, kind, estimated_usd, dimension_count, created_at, updated_at) "
                "VALUES (1, 'rank', 0.25, 2, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
            connection.exec_driver_sql("INSERT INTO run_pass_cost "
                "(run_id, label, model_id, calls, input_tokens, output_tokens, cost_usd, cached_count, cached_saved_usd, duration_ms, failed_calls, created_at, updated_at) "
                "VALUES (1, 'Dimension scoring', 'synthetic', 2, 100, 50, 0.1, 2, 0.05, 500, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
        engine.dispose()
        command.upgrade(config, "head")
        engine = create_engine(url)
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT status, failed_pass, dimension_count FROM run_cost_ledger").one() == ("completed", None, 2)
            assert connection.exec_driver_sql("SELECT calls, fresh_units, cost_usd, cached_count FROM run_pass_cost").one() == (2, None, 0.1, 2)
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        engine.dispose()
    finally:
        get_settings.cache_clear()


def test_run_renewal_migration_preserves_an_active_acquisition(tmp_path, monkeypatch) -> None:
    backend = Path(__file__).parents[1]
    url = f"sqlite:///{(tmp_path / 'run-renewal.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    try:
        config = Config(str(backend / "alembic.ini"))
        config.set_main_option("script_location", str(backend / "alembic"))
        command.upgrade(config, "7d8e9f0a1b2c")
        engine = create_engine(url)
        with engine.begin() as connection:
            connection.exec_driver_sql("INSERT INTO users (id, email, display_name, role, is_active, created_at, updated_at) "
                "VALUES (1, 'synthetic@example.com', 'Synthetic', 'member', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
            connection.exec_driver_sql("UPDATE run_lock SET holder_user_id = 1, kind = 'rank', held_since = '2026-10-03 12:00:00'")
        engine.dispose()
        command.upgrade(config, "head")
        engine = create_engine(url)
        with engine.connect() as connection:
            row = connection.exec_driver_sql("SELECT holder_user_id, kind, held_since, renewed_at FROM run_lock").one()
            assert row == (1, "rank", "2026-10-03 12:00:00", "2026-10-03 12:00:00")
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        engine.dispose()
    finally:
        get_settings.cache_clear()


def test_result_selection_migration_preserves_history_and_previous_display(tmp_path, monkeypatch) -> None:
    backend = Path(__file__).parents[1]
    url = f"sqlite:///{(tmp_path / 'selected-results.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    try:
        config = Config(str(backend / "alembic.ini"))
        config.set_main_option("script_location", str(backend / "alembic"))
        command.upgrade(config, "6c7d8e9f0a1b")
        engine = create_engine(url)
        with engine.begin() as connection:
            connection.exec_driver_sql("INSERT INTO applications "
                "(id, primary_email, raw_row, raw_row_hash, normalized, working_revision, synthetic_data, created_at, updated_at) "
                "VALUES (1, 'synthetic@example.com', '{}', 'synthetic', '{}', 1, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
            for result_id, kind, created_at in [
                (1, "screening", "2026-10-01"), (2, "screening", "2026-10-02"),
                (3, "screening", "2026-10-02"), (4, "dimension_scoring:criterion", "2026-10-01"),
            ]:
                connection.exec_driver_sql("INSERT INTO application_ai_results "
                    "(id, application_id, kind, cache_key, model_id, prompt_version, output, input_tokens, output_tokens, cost_usd, created_at, updated_at) "
                    "VALUES (?, 1, ?, ?, 'synthetic', 'test', '{}', 0, 0, 0, ?, ?)",
                    (result_id, kind, str(result_id), created_at, created_at))
        engine.dispose()
        command.upgrade(config, "head")
        engine = create_engine(url)
        with engine.begin() as connection:
            assert connection.exec_driver_sql("SELECT application_id, kind, result_id FROM application_ai_selections ORDER BY kind").all() == [
                (1, "dimension_scoring:criterion", 4), (1, "screening", 3),
            ]
            assert connection.exec_driver_sql("SELECT COUNT(*) FROM application_ai_results").scalar_one() == 4
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.exec_driver_sql("DELETE FROM applications WHERE id = 1")
            assert connection.exec_driver_sql("SELECT COUNT(*) FROM application_ai_selections").scalar_one() == 0
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        engine.dispose()
    finally:
        get_settings.cache_clear()


def test_publication_migration_preserves_openings_and_enforces_request_identity(tmp_path, monkeypatch) -> None:
    from sqlalchemy.exc import IntegrityError

    backend = Path(__file__).parents[1]
    url = f"sqlite:///{(tmp_path / 'publication.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    try:
        config = Config(str(backend / "alembic.ini"))
        config.set_main_option("script_location", str(backend / "alembic"))
        command.upgrade(config, "9e0f1a2b3c4d")
        engine = create_engine(url)
        with engine.begin() as connection:
            connection.exec_driver_sql("INSERT INTO openings (unit_size_bedrooms, housing_charge_cents, "
                "application_open_date, application_close_date, move_in_date, intake_mode, created_at, updated_at) "
                "VALUES (2, 125000, '2026-10-01', '2026-10-31', '2026-11-30', 'applications', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
        engine.dispose()
        command.upgrade(config, "head")
        engine = create_engine(url)
        with engine.begin() as connection:
            row = connection.exec_driver_sql("SELECT housing_charge_cents, publication_request_id, publication_request FROM openings").one()
            assert row == (125000, None, None)
            connection.exec_driver_sql("UPDATE openings SET publication_request_id = 'synthetic-publication'")
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.exec_driver_sql("INSERT INTO openings (unit_size_bedrooms, housing_charge_cents, "
                "application_open_date, application_close_date, move_in_date, intake_mode, publication_request_id, created_at, updated_at) "
                "VALUES (2, 125000, '2026-10-01', '2026-10-31', '2026-11-30', 'applications', 'synthetic-publication', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
        engine.dispose()
    finally:
        get_settings.cache_clear()


def test_run_dimension_count_migration_preserves_unmeasured_history(tmp_path, monkeypatch) -> None:
    backend = Path(__file__).parents[1]
    url = f"sqlite:///{(tmp_path / 'run-dimensions.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    try:
        config = Config(str(backend / "alembic.ini"))
        config.set_main_option("script_location", str(backend / "alembic"))
        command.upgrade(config, "5b6c7d8e9f0a")
        engine = create_engine(url)
        with engine.begin() as connection:
            connection.exec_driver_sql("INSERT INTO run_cost_ledger (kind, estimated_usd, created_at, updated_at) "
                "VALUES ('rank', 0.25, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
        engine.dispose()
        command.upgrade(config, "head")
        engine = create_engine(url)
        with engine.connect() as connection:
            row = connection.exec_driver_sql("SELECT kind, estimated_usd, dimension_count FROM run_cost_ledger").one()
            assert row == ("rank", 0.25, None)
        engine.dispose()
    finally:
        get_settings.cache_clear()


def test_global_profile_migration_updates_only_saved_us_claude_routes() -> None:
    migration_path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "3e4f5a6b7c8d_use_global_claude_profiles.py"
    )
    migration = runpy.run_path(str(migration_path))
    settings = {
        "ai": {
            "screening_model": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
            "discovery_model": "us.anthropic.claude-sonnet-4-6",
            "decompose_model": "claude-sonnet-4-6",
            "spending_cap_usd": 2.0,
        },
        "unrelated": "preserved",
    }

    changed = migration["_replace_profile_ids"](settings, migration["_US_TO_GLOBAL"])

    assert changed is True
    assert settings == {
        "ai": {
            "screening_model": "global.anthropic.claude-haiku-4-5-20251001-v1:0",
            "discovery_model": "global.anthropic.claude-sonnet-4-6",
            "decompose_model": "claude-sonnet-4-6",
            "spending_cap_usd": 2.0,
        },
        "unrelated": "preserved",
    }


def test_global_profile_migration_updates_an_existing_database(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database = tmp_path / "global-profiles.db"
    backend = Path(__file__).parents[1]
    database_url = f"sqlite:///{database.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    try:
        config = Config(str(backend / "alembic.ini"))
        config.set_main_option("script_location", str(backend / "alembic"))
        command.upgrade(config, "2d3e4f5a6b7c")

        engine = create_engine(database_url)
        settings = {
            "ai": {
                "screening_model": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
                "discovery_model": "us.anthropic.claude-sonnet-4-6",
                "match_model": "claude-sonnet-4-6",
            }
        }
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO admin_settings (key, value, created_at, updated_at) "
                "VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                ("app_settings", json.dumps(settings)),
            )
        engine.dispose()

        command.upgrade(config, "head")

        engine = create_engine(database_url)
        with engine.connect() as connection:
            stored = json.loads(
                connection.exec_driver_sql(
                    "SELECT value FROM admin_settings WHERE key = 'app_settings'"
                ).scalar_one()
            )
        engine.dispose()

        assert stored["ai"] == {
            "screening_model": "global.anthropic.claude-haiku-4-5-20251001-v1:0",
            "discovery_model": "global.anthropic.claude-sonnet-4-6",
            "match_model": "claude-sonnet-4-6",
        }
    finally:
        get_settings.cache_clear()


def test_global_openai_migration_updates_only_saved_mantle_routes() -> None:
    migration_path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "4f5a6b7c8d9e_use_global_openai_profiles.py"
    )
    migration = runpy.run_path(str(migration_path))
    settings = {
        "ai": {
            "screening_model": "openai.gpt-5.6-luna",
            "discovery_model": "openai.gpt-5.6-terra",
            "decompose_model": "gpt-5.6-terra",
            "spending_cap_usd": 2.0,
        },
        "unrelated": "preserved",
    }

    changed = migration["_replace_route_ids"](settings, migration["_MANTLE_TO_GLOBAL"])

    assert changed is True
    assert settings == {
        "ai": {
            "screening_model": "global.openai.gpt-5.6-luna",
            "discovery_model": "global.openai.gpt-5.6-terra",
            "decompose_model": "gpt-5.6-terra",
            "spending_cap_usd": 2.0,
        },
        "unrelated": "preserved",
    }


def test_global_openai_migration_updates_an_existing_database(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database = tmp_path / "global-openai-profiles.db"
    backend = Path(__file__).parents[1]
    database_url = f"sqlite:///{database.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    try:
        config = Config(str(backend / "alembic.ini"))
        config.set_main_option("script_location", str(backend / "alembic"))
        command.upgrade(config, "3e4f5a6b7c8d")

        engine = create_engine(database_url)
        settings = {
            "ai": {
                "screening_model": "openai.gpt-5.6-luna",
                "discovery_model": "openai.gpt-5.6-terra",
                "match_model": "gpt-5.6-terra",
            }
        }
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO admin_settings (key, value, created_at, updated_at) "
                "VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                ("app_settings", json.dumps(settings)),
            )
        engine.dispose()

        command.upgrade(config, "head")

        engine = create_engine(database_url)
        with engine.connect() as connection:
            stored = json.loads(
                connection.exec_driver_sql(
                    "SELECT value FROM admin_settings WHERE key = 'app_settings'"
                ).scalar_one()
            )
        engine.dispose()

        assert stored["ai"] == {
            "screening_model": "global.openai.gpt-5.6-luna",
            "discovery_model": "global.openai.gpt-5.6-terra",
            "match_model": "gpt-5.6-terra",
        }
    finally:
        get_settings.cache_clear()


def test_vacancy_privacy_migrations_update_an_existing_database(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database = tmp_path / "vacancy-hash-removal.db"
    backend = Path(__file__).parents[1]
    database_url = f"sqlite:///{database.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    try:
        config = Config(str(backend / "alembic.ini"))
        config.set_main_option("script_location", str(backend / "alembic"))
        command.upgrade(config, "4f5a6b7c8d9e")

        engine = create_engine(database_url)
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO vacancy_consent_receipts "
                "(subscription_id, email_hash, unit_sizes, consented_at, consent_version, "
                "source, fulfilled_at, retain_until, email_delivery_id) "
                "VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?, ?, CURRENT_TIMESTAMP, ?, ?)",
                (
                    1,
                    "legacy-hash",
                    "[1]",
                    "2026-08-27",
                    "public website",
                    "2027-09-01",
                    42,
                ),
            )
        engine.dispose()

        command.upgrade(config, "5a6b7c8d9e0f")

        engine = create_engine(database_url)
        with engine.begin() as connection:
            receipt_columns = {
                row[1]
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(vacancy_consent_receipts)"
                )
            }
            audit_columns = {
                row[1]
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(vacancy_subscription_audits)"
                )
            }
            source = connection.exec_driver_sql(
                "SELECT source FROM vacancy_consent_receipts"
            ).scalar_one()
            connection.exec_driver_sql(
                "INSERT INTO vacancy_subscriptions "
                "(email, wants_one_bedroom, wants_two_bedroom, wants_three_bedroom, "
                "first_consented_at, consented_at, consent_version, source, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?, ?, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                ("active@example.com", 1, 0, 0, "2026-08-27", "public website"),
            )
            connection.exec_driver_sql(
                "INSERT INTO email_deliveries "
                "(idempotency_key, message_kind, recipient_kind, recipient_email, state, "
                "quota_blocked, attempt_count, last_attempt_at, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, "
                "CURRENT_TIMESTAMP)",
                (
                    "opening:1:subscription:1",
                    "vacancy_opening",
                    "applicant",
                    None,
                    "accepted",
                    0,
                    1,
                ),
            )
        engine.dispose()

        assert "email_hash" not in receipt_columns
        assert "email_hash" not in audit_columns
        assert source == "public website"

        command.upgrade(config, "head")

        engine = create_engine(database_url)
        with engine.connect() as connection:
            tables = {
                row[0]
                for row in connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            subscription_columns = {
                row[1]
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(vacancy_subscriptions)"
                )
            }
            active = connection.exec_driver_sql(
                "SELECT email, source FROM vacancy_subscriptions"
            ).one()
            accepted_vacancy_deliveries = connection.exec_driver_sql(
                "SELECT COUNT(*) FROM email_deliveries "
                "WHERE message_kind = 'vacancy_opening' AND state = 'accepted'"
            ).scalar_one()
        engine.dispose()

        assert "vacancy_consent_receipts" not in tables
        assert "vacancy_subscription_audits" not in tables
        assert "consent_version" not in subscription_columns
        assert "managed_by_user_id" not in subscription_columns
        assert active == ("active@example.com", "public website")
        assert accepted_vacancy_deliveries == 0
    finally:
        get_settings.cache_clear()


def test_terms_version_removal_preserves_application_versions(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database = tmp_path / "terms-version-removal.db"
    backend = Path(__file__).parents[1]
    database_url = f"sqlite:///{database.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    try:
        config = Config(str(backend / "alembic.ini"))
        config.set_main_option("script_location", str(backend / "alembic"))
        command.upgrade(config, "6b7c8d9e0f1a")

        engine = create_engine(database_url)
        with engine.begin() as connection:
            inserted = connection.exec_driver_sql(
                "INSERT INTO applications "
                "(primary_email, raw_row, raw_row_hash, normalized, working_revision, "
                "synthetic_data, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                ("applicant@example.com", "{}", "content-hash", "{}", 1, 0),
            )
            connection.exec_driver_sql(
                "INSERT INTO application_versions "
                "(application_id, answers, normalized, selected_opening_ids, content_hash, "
                "submitted_at, terms_version) "
                "VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)",
                (inserted.lastrowid, "{}", "{}", "[]", "content-hash", "2026-08-27"),
            )
        engine.dispose()

        command.upgrade(config, "head")

        engine = create_engine(database_url)
        with engine.connect() as connection:
            columns = {
                row[1]
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(application_versions)"
                )
            }
            content_hash = connection.exec_driver_sql(
                "SELECT content_hash FROM application_versions"
            ).scalar_one()
        engine.dispose()

        assert "terms_version" not in columns
        assert content_hash == "content-hash"
    finally:
        get_settings.cache_clear()


def test_fresh_schema_keeps_timestamp_defaults_on_opening_scoped_tables(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database = tmp_path / "m24-fresh.db"
    backend = Path(__file__).parents[1]
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database.as_posix()}")
    get_settings.cache_clear()
    try:
        config = Config(str(backend / "alembic.ini"))
        config.set_main_option("script_location", str(backend / "alembic"))
        command.upgrade(config, "head")

        engine = create_engine(f"sqlite:///{database.as_posix()}")
        with engine.connect() as connection:
            for table in (
                "member_rules",
                "member_eligibility",
                "application_shortlist",
                "application_committee_notes",
            ):
                columns = {
                    row[1]: row[4]
                    for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")
                }
                assert columns["created_at"] is not None
                assert columns["updated_at"] is not None
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("ambiguous", [False, True])
@pytest.mark.parametrize("retired_route", [False, True])
def test_cache_evidence_migration_preserves_proven_hits_and_uncertain_history(monkeypatch, ambiguous, retired_route):
    from datetime import UTC, datetime

    from app.ai.analysis import cache_key
    from app.db.models import Application, ApplicationAIResult, ApplicationVersion
    from tests.db_support import memory_session

    migration = runpy.run_path(str(Path(__file__).parents[1] / "alembic/versions/a47e5c19b203_capture_consumed_cache_evidence.py"))
    db = memory_session()
    application = Application(primary_email="evidence@example.test", raw_row={"applicant": {}},
                              raw_row_hash="unchanged", normalized={"child_details": [{"age": 11}]})
    db.add(application)
    db.flush()
    for age in ([10, 11] if ambiguous else [11, 11]):
        db.add(ApplicationVersion(application_id=application.id, answers=application.raw_row,
            normalized={"child_details": [{"age": age}]}, content_hash="unchanged",
            selected_opening_ids=[], submitted_at=datetime.now(UTC)))
    row = {"kind": "screening", "model_id": AppSettings().ai.screening_model, "reasoning_effort": None, "prompt_version": "v"}
    old_key = migration["_key"](row, "unchanged", neutral_model="anthropic:claude-haiku-4-5-20251001")
    if retired_route:
        row["model_id"] = "retired-provider-route"
    result = ApplicationAIResult(producer_application_id=application.id, cache_key=old_key, output={"flags": []},
                                 cost_usd=0.123, input_tokens=100, output_tokens=50, **row)
    db.add(result)
    db.commit()
    with db.bind.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE application_ai_results RENAME COLUMN producer_application_id TO application_id")
        monkeypatch.setattr(migration["op"], "get_bind", lambda: connection)
        migration["upgrade"]()
        connection.exec_driver_sql("ALTER TABLE application_ai_results RENAME COLUMN application_id TO producer_application_id")
    db.expire_all()
    # This migration freezes its own historical input schema. Current projections
    # can change without rewriting the meaning of already migrated evidence.
    migrated_key = "e84360248cc9f3fa6afe0e41751636c07971780cbc7e1ff7c9d087c0e6b674ce"
    assert result.cache_key == (old_key if ambiguous else migrated_key)
    assert result.cache_key != cache_key(application=application,
        kind="screening", model_id=AppSettings().ai.screening_model, prompt_version="v")
    assert result.output == {"flags": []}
    assert result.cost_usd == 0.123
    assert result.input_tokens == 100
