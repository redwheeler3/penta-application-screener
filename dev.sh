#!/usr/bin/env bash
set -e

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"

cleanup() {
  kill 0 2>/dev/null
}
trap cleanup EXIT

echo "Running migrations..."
(cd "$REPO_ROOT/backend" && uv run alembic upgrade head)

echo "To use the API docs (http://localhost:8000/docs), first sign in here:"
echo "  http://localhost:8000/auth/google/login"
echo ""

echo "Starting backend on http://localhost:8000 ..."
(cd "$REPO_ROOT/backend" && uv run fastapi dev --host localhost app/main.py) &

echo "Starting frontend on http://localhost:5173 ..."
(cd "$REPO_ROOT/frontend" && npm run dev) &

wait
