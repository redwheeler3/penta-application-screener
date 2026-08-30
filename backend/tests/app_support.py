"""Shared FastAPI wiring for sequential integration tests."""

from fastapi import FastAPI

from app.main import create_app

_app = create_app()


def shared_test_app() -> FastAPI:
    """Return the shared route graph with no dependency overrides from the prior test."""
    _app.dependency_overrides.clear()
    return _app
