"""Filesystem locations of the eval DATASET — the versioned corpus, kept OUT of the code
package.

The eval cases and the invariant baseline are a git-tracked, human-edited dataset (see the
"dataset is a versioned artifact" decision in docs/ai-evals.md), not Python. They live in
``backend/eval-data/`` — a sibling of ``app/`` — so the code/data split is legible in the
tree and the corpus isn't intermixed with modules. Every module that reads or writes a
dataset file imports its path from here (one definition, one place to move them).
"""

from __future__ import annotations

from pathlib import Path

# backend/ — this file is app/evals/paths.py, so three parents up is the backend root.
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
EVAL_DATA_DIR = _BACKEND_ROOT / "eval-data"

# Judge cases (semantic verdicts) and the invariant baseline.
JUDGE_CASES_PATH = EVAL_DATA_DIR / "judge_cases.json"
FIXTURE_PATH = EVAL_DATA_DIR / "rank_baseline.json"

# Live per-pass golden inputs: each `<pass>_golden.json` holds cases run through that pass's
# REAL production prompt (see app/evals/live_*.py and docs/eval-case-schema.md).
GOLDEN_PATH = EVAL_DATA_DIR / "scoring_golden.json"  # scoring (the first live eval)
CONSOLIDATION_GOLDEN_PATH = EVAL_DATA_DIR / "consolidation_golden.json"
