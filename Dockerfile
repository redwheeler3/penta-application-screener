# Single-origin production image (M17, ADR 0012): build the frontend, then serve it and
# the API from one FastAPI process. Two stages so Node never ships in the runtime image.

# ---- Stage 1: build the Vite bundle -----------------------------------------------------
FROM node:22-slim AS frontend
WORKDIR /frontend
# Install deps against the lockfile first (cached until package*.json changes), then build.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# Vite bakes VITE_* vars into the bundle AT BUILD TIME, so the Google Picker config must be
# present here (not just at runtime). These come from fly.toml [build.args] (see there). They
# are NOT secrets — the Picker API key is a browser key (safe to expose; restricted by referrer
# + Picker-API in Google Cloud), and the client id / project number are public identifiers.
# Passing them as ENV before the build makes import.meta.env.VITE_* resolve; absent, the Picker
# shows "not configured" and sheet-linking is unavailable (M18).
ARG VITE_GOOGLE_PICKER_API_KEY=""
ARG VITE_GOOGLE_CLIENT_ID=""
ARG VITE_GOOGLE_PROJECT_NUMBER=""
ENV VITE_GOOGLE_PICKER_API_KEY=$VITE_GOOGLE_PICKER_API_KEY \
    VITE_GOOGLE_CLIENT_ID=$VITE_GOOGLE_CLIENT_ID \
    VITE_GOOGLE_PROJECT_NUMBER=$VITE_GOOGLE_PROJECT_NUMBER
RUN npm run build   # emits /frontend/dist

# ---- Stage 2: the Python runtime --------------------------------------------------------
# uv ships as a static binary in this image; it manages the venv and the locked install.
FROM python:3.13-slim AS runtime
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Backend lives at /app/backend so the app's relative paths (./data, alembic ./data) and
# the repo layout (parents[2] → repo root) resolve exactly as they do in development.
WORKDIR /app/backend

# Install locked dependencies first, without the app code, so the layer caches across code
# edits. --frozen fails loudly if uv.lock is stale rather than silently resolving.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/backend/.venv \
    PATH="/app/backend/.venv/bin:$PATH"
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# App code: backend, plus the built frontend copied to where StaticFiles looks
# (repo_root/frontend/dist → /app/frontend/dist, since backend is /app/backend).
COPY backend/ /app/backend/
COPY --from=frontend /frontend/dist /app/frontend/dist
# Deps are already installed above; --no-install-project means we never build the app as a
# package (it has no build-system and runs from source, exactly like dev). uvicorn adds the
# working dir to sys.path, so `app.main:app` resolves from /app/backend.
RUN uv sync --frozen --no-dev --no-install-project

# The SQLite DB lives here; the Fly volume mounts over it (see fly.toml [mounts]). Created
# so a first boot without a mounted volume still works (e.g. a local `docker run` smoke test).
RUN mkdir -p /app/backend/data

# Migrate to head, then serve on Fly's injected $PORT (8080). Migrations run on every boot
# and are idempotent (alembic no-ops when already at head), so a redeploy is safe.
EXPOSE 8080
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
