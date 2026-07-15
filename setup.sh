#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")" && pwd)"

echo "Installing backend dependencies..."
(cd "$repo_root/backend" && uv sync)

echo "Installing frontend dependencies..."
(cd "$repo_root/frontend" && npm install)

echo "Running database migrations..."
(cd "$repo_root/backend" && uv run alembic upgrade head)

echo "Setup complete. Configure Google OAuth before signing in."
