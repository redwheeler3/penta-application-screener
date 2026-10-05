"""Rekey only caches whose consumed submitted evidence can be proved unchanged.

Revision ID: a47e5c19b203
Revises: c83d5f917a2b
"""

import hashlib
import json
from collections import defaultdict

import sqlalchemy as sa

from alembic import op
from app.ai.model_catalog import MODEL_IDENTITIES, model_identity

revision = "a47e5c19b203"
down_revision = "c83d5f917a2b"
branch_labels = None
depends_on = None

# Freeze the input projections used by this data migration.
SCREENING_KEYS = ("applicant_name", "co_applicant_name", "child_details", "pets_text",
                  "applicant_email", "co_applicant_email", "co_applicant_phone")
RANK_KEYS = ("adult_count", "child_count", "applicant_age", "co_applicant_age", "child_details",
             "household_income", "applicant_income", "co_applicant_income",
             "applicant_employment_start", "co_applicant_employment_start", "pets_text")


def _key(row, raw_hash, normalized=None, *, neutral_model=None):
    identity = {"kind": row["kind"], "model_id": neutral_model or model_identity(row["model_id"]),
                "prompt_version": row["prompt_version"]}
    if row["reasoning_effort"] is not None:
        identity["reasoning_effort"] = row["reasoning_effort"]
    if normalized is None:
        identity["raw_hash"] = raw_hash
    else:
        facts = ({key: normalized.get(key) for key in SCREENING_KEYS} if row["kind"] == "screening"
                 else {key: normalized[key] for key in RANK_KEYS if key in normalized})
        basis = json.dumps({"raw_hash": raw_hash, "facts": facts}, sort_keys=True, default=str)
        identity["input_hash"] = hashlib.sha256(basis.encode("utf-8")).hexdigest()
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode("utf-8")).hexdigest()


def _rekey(*, reverse=False):
    connection = op.get_bind()
    metadata = sa.MetaData()
    results = sa.Table("application_ai_results", metadata, autoload_with=connection)
    applications = sa.Table("applications", metadata, autoload_with=connection)
    versions = sa.Table("application_versions", metadata, autoload_with=connection)
    snapshots = defaultdict(list)
    for version in connection.execute(sa.select(versions)).mappings():
        snapshots[version["application_id"]].append((version["content_hash"], version["normalized"] or {}))
    for application in connection.execute(sa.select(applications)).mappings():
        # Native publications have immutable versions. Imported records carry fixed
        # form-supplied ages and can use their matching current projection.
        if snapshots[application["id"]] or not isinstance((application["raw_row"] or {}).get("applicant"), dict):
            snapshots[application["id"]].append((application["raw_row_hash"], application["normalized"] or {}))
    rows = connection.execute(sa.select(results)).mappings().all()
    occupied = {row["cache_key"] for row in rows}
    for row in rows:
        try:
            models = {model_identity(row["model_id"])}
        except ValueError:
            # A retired provider route can still have a valid neutral-model cache.
            # The stored digest proves the identity; never guess it from route text.
            models = set(MODEL_IDENTITIES.values())
        candidates = set()
        for raw_hash, normalized in snapshots[row["application_id"]]:
            for neutral_model in models:
                old = _key(row, raw_hash, neutral_model=neutral_model)
                new = _key(row, raw_hash, normalized, neutral_model=neutral_model)
                source, target = (new, old) if reverse else (old, new)
                if source == row["cache_key"]:
                    candidates.add(target)
        # Multiple age projections for identical answers cannot prove what an
        # in-flight historical call consumed. Keep its output and cost as history.
        if len(candidates) != 1:
            continue
        target = candidates.pop()
        if target in occupied:
            continue
        connection.execute(results.update().where(results.c.id == row["id"]).values(cache_key=target))
        occupied.add(target)


def upgrade():
    _rekey()


def downgrade():
    _rekey(reverse=True)
