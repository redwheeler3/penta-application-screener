#!/usr/bin/env bash
# Take a consistent local SQLite snapshot; labels are passed as CLI data.
set -euo pipefail
repo_root="$(cd "$(dirname "$0")" && pwd)"
cd "$repo_root/backend"
uv run python -m app.services.backup backup --tag="${1:-manual}"
