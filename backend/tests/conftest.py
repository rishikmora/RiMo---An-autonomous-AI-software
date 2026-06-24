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
# In-memory rate-limit storage so tests don't require a running Redis.
os.environ.setdefault("RATELIMIT_STORAGE_URI", "memory://")
# Generous auth limits in tests (the suite logs in many times from one IP).
os.environ.setdefault("RATE_LIMIT_LOGIN_PER_MINUTE", "1000")
os.environ.setdefault("RATE_LIMIT_REGISTER_PER_MINUTE", "1000")
# NullPool: each test runs on its own event loop, so pooled asyncpg connections
# can't be shared across loops (see app/db/session.py).
os.environ.setdefault("DB_POOL_SIZE", "0")


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"
