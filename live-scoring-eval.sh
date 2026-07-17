#!/usr/bin/env bash
set -euo pipefail

# Live scoring eval: golden synthetic inputs -> the REAL scoring prompt+model -> assertions
# + rubric judge. Makes real model calls (costs money, non-deterministic) — run deliberately,
# never in CI. See docs/ai-evals.md.
repo_root="$(cd "$(dirname "$0")" && pwd)"
cd "$repo_root/backend"

uv run python -m app.evals.live_scoring "$@"
