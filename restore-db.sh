#!/usr/bin/env bash
# Restore the local SQLite DB from a backup in backend/data/backups/.
# The current DB is snapshotted first (tag "pre-restore"), so a restore is itself
# reversible. Stop the backend before restoring so nothing is mid-write.
#
# Usage:
#   ./restore-db.sh                 # list backups, prompt for one
#   ./restore-db.sh --latest        # restore the most recent backup
#   ./restore-db.sh <path|filename> # restore a specific backup
set -euo pipefail

repo_root="$(cd "$(dirname "$0")" && pwd)"
backend_dir="$repo_root/backend"
backups_dir="$backend_dir/data/backups"

list_py="from app.services.backup import list_backups
for i, p in enumerate(list_backups()):
    print(f'{i}\t{p.name}')"

choice="${1:-}"
cd "$backend_dir"

if [[ "$choice" == "--latest" ]]; then
  target="$(uv run python -c "from app.services.backup import list_backups; bs=list_backups(); print(bs[0] if bs else '')")"
elif [[ -n "$choice" ]]; then
  # accept a bare filename (resolve against backups dir) or a full path
  if [[ -f "$choice" ]]; then target="$choice"; else target="$backups_dir/$choice"; fi
else
  echo "Available backups (newest first):"
  uv run python -c "$list_py"
  echo ""
  read -r -p "Enter a backup filename to restore (or blank to cancel): " picked
  [[ -z "$picked" ]] && { echo "Restore cancelled."; exit 0; }
  if [[ -f "$picked" ]]; then target="$picked"; else target="$backups_dir/$picked"; fi
fi

if [[ -z "$target" || ! -f "$target" ]]; then
  echo "No such backup: ${target:-<none>}" >&2
  exit 1
fi

echo "This will REPLACE the live DB with:"
echo "  $target"
echo "The current DB is snapshotted first (tag pre-restore) and can be restored back."
read -r -p "Type RESTORE to continue: " confirmation
[[ "$confirmation" != "RESTORE" ]] && { echo "Restore cancelled."; exit 0; }

uv run python -c "from pathlib import Path; from app.services.backup import restore_backup; \
p=restore_backup(Path('$target')); print(f'Restored {p} from $target')"
