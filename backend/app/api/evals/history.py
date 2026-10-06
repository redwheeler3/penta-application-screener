"""Restore bounded case coverage without loading narration or a row-count window."""

import json

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.evals._shared import result_model, result_reasoning_effort
from app.evals.dataset import case_identity


def latest_case_results(db: Session, key: str, version: str, result: dict,
                        identities: set[str]) -> tuple[list[dict], dict[str, int]]:
    """SQLite chooses the newest result per current family/key in one experiment.

    Only case JSON crosses the DB boundary, even after thousands of per-row runs.
    A non-JSON historical payload supplies no reconstructable cases; it cannot
    break restoration of valid runs. The operational history itself stays intact.
    """
    rows = db.execute(text("""
        WITH valid_runs AS (
            SELECT id, created_at, prompt_version,
                   result
            FROM eval_runs
            WHERE eval_key = :key AND json_valid(result)
              AND coalesce(prompt_version, '') = :version
              AND coalesce(json_extract(result, '$.experimentId'), '') = :experiment
        ), ranked AS (
            SELECT cases.value, valid_runs.id AS source_run_id,
                   row_number() OVER (
                       PARTITION BY json_extract(cases.value, '$.passName'),
                                    json_extract(cases.value, '$.key')
                       ORDER BY valid_runs.created_at DESC, valid_runs.id DESC
                   ) AS position
            FROM valid_runs, json_each(valid_runs.result, '$.cases') AS cases
            WHERE coalesce(json_extract(result, '$.model'), json_extract(result, '$.scoringModel'),
                           json_extract(result, '$.judgeModel'), '') = :model
              AND coalesce(json_extract(result, '$.reasoningEffort'), '') = :reasoning
              AND coalesce(json_extract(result, '$.k'), 1) = :k
              AND CASE WHEN json_extract(cases.value, '$.passName') IS NOT NULL
                       THEN json_array(json_extract(cases.value, '$.passName'), json_extract(cases.value, '$.key'))
                       ELSE json_extract(cases.value, '$.key') END
                  IN (SELECT value FROM json_each(:identities))
        )
        SELECT value, source_run_id FROM ranked WHERE position = 1
    """), {
        "key": key, "version": version, "model": result_model(result),
        "reasoning": result_reasoning_effort(result), "k": result.get("k", 1),
        "experiment": result.get("experimentId", ""), "identities": json.dumps(sorted(identities)),
    })
    cases, sources = [], {}
    for value, run_id in rows:
        case = json.loads(value)
        cases.append(case)
        sources[case_identity(case["key"], case.get("passName", ""))] = run_id
    return cases, sources
