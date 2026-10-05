#!/usr/bin/env bash
set -euo pipefail
# Give each service its own process group, including reload workers.
set -m

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"

backend_pid=""
frontend_pid=""
cleanup() {
  for pid in "$backend_pid" "$frontend_pid"; do
    if [[ -n "$pid" ]]; then
      kill -- -"$pid" 2>/dev/null || true
      for attempt in {1..10}; do
        kill -0 -- -"$pid" 2>/dev/null || break
        sleep 0.2
      done
      kill -KILL -- -"$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
    fi
  done
}
trap cleanup EXIT
trap "exit 130" INT
trap "exit 143" TERM

echo "Running migrations..."
(cd "$REPO_ROOT/backend" && uv run alembic upgrade head)

echo "To use the API docs (http://localhost:8000/docs), first sign in here:"
echo "  http://localhost:8000/auth/google/login"
echo ""

echo "Starting backend on http://localhost:8000 ..."
# Watch application code only: saving tests should not restart local development.
(cd "$REPO_ROOT/backend" && exec uv run uvicorn app.main:app --host localhost --port 8000 --reload --reload-dir app) &
backend_pid=$!

echo "Starting frontend on http://localhost:5173 ..."
echo "  Committee screener: http://localhost:5173"
echo "  Application form:   http://localhost:5173/?applicant"
echo "  Access/email review: http://localhost:5173/?preview=access"
(cd "$REPO_ROOT/frontend" && exec npm run dev) &
frontend_pid=$!

wait
