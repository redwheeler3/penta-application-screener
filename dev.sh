#!/usr/bin/env bash
set -e

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"

cleanup() {
  kill 0 2>/dev/null
}
trap cleanup EXIT

echo "Starting backend on http://127.0.0.1:8000 ..."
(cd "$REPO_ROOT/backend" && uv run fastapi dev app/main.py) &

echo "Starting frontend on http://127.0.0.1:5173 ..."
(cd "$REPO_ROOT/frontend" && npm run dev) &

wait
