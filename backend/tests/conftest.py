"""Shared pytest fixtures.

Tests run against a real Postgres (with pgvector) in CI; locally they fall back
to the deterministic embedding provider and never call external APIs. The
SECRET_KEY / DATABASE_URL come from the environment (see ci.yml).
"""
from __future__ import annotations

import os

import pytest

# Ensure required settings exist before app modules import.
os.environ.setdefault("SECRET_KEY", "test_secret_key_at_least_32_characters_long_xx")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-placeholder")
os.environ.pop("OPENAI_API_KEY", None)  # force deterministic embeddings in tests


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"
