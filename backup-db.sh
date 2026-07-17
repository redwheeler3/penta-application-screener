#!/usr/bin/env bash
# Take a consistent snapshot of the local SQLite DB into backend/data/backups/.
# Safe to run while the backend is up (uses SQLite VACUUM INTO, not a raw copy).
# Usage: ./backup-db.sh [tag]   (tag defaults to "manual", e.g. ./backup-db.sh rank-7)
set -euo pipefail

repo_root="$(cd "$(dirname "$0")" && pwd)"
tag="${1:-manual}"

cd "$repo_root/backend"
uv run python -c "from app.services.backup import create_and_prune, list_backups, backups_dir; \
p=create_and_prune(tag='$tag'); \
print(f'Backup written: {p} ({p.stat().st_size/1_000_000:.1f} MB)'); \
print(f'{len(list_backups())} backup(s) retained in {backups_dir()}')"
