#!/usr/bin/env bash
set -euo pipefail

force=false
if [[ "${1:-}" == "--force" ]]; then
  force=true
elif [[ $# -gt 0 ]]; then
  echo "Usage: ./reset-db.sh [--force]" >&2
  exit 1
fi

repo_root="$(cd "$(dirname "$0")" && pwd)"
backend_dir="$repo_root/backend"
database_path="$backend_dir/data/penta_screener.db"

echo "This will delete the local SQLite database and recreate an empty schema."
echo "Database: $database_path"
echo "This clears local users, Google credentials, settings, sync runs, and imported applications."

if [[ "$force" != true ]]; then
  read -r -p "Type RESET to continue: " confirmation
  if [[ "$confirmation" != "RESET" ]]; then
    echo "Database reset cancelled."
    exit 0
  fi
fi

if [[ -f "$database_path" ]]; then
  if rm "$database_path"; then
    echo "Deleted existing database."
  else
    echo "Could not delete the database. Stop the backend/dev script first, then run this again." >&2
    exit 1
  fi
else
  echo "No existing database found."
fi

echo "Running migrations..."
(cd "$backend_dir" && uv run alembic upgrade head)

echo "Database reset complete."
