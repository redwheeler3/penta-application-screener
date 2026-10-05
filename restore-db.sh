#!/usr/bin/env bash
# Stop the backend first. The shared CLI selects a backup and confirms the restore.
set -euo pipefail
repo_root="$(cd "$(dirname "$0")" && pwd)"
cd "$repo_root/backend"
if [[ "${1:-}" == "--latest" ]]; then
  [[ $# -eq 1 ]] || { echo "Usage: $0 [--latest | backup]" >&2; exit 1; }
  uv run python -m app.services.backup restore --latest
elif [[ $# -eq 0 ]]; then
  uv run python -m app.services.backup restore
else
  [[ $# -eq 1 ]] || { echo "Usage: $0 [--latest | backup]" >&2; exit 1; }
  uv run python -m app.services.backup restore -- "$1"
fi
