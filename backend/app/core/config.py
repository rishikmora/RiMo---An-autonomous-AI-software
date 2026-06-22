"""Application configuration.

All settings are loaded from environment variables via Pydantic. No secret is
ever hard-coded; in production these are injected through Kubernetes secrets or
a `.env` file that is excluded from version control.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---------------------------------------------------------
    app_name: str = "RiMo"
    app_env: Literal["development", "staging", "production"] = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    secret_key: str = Field(..., min_length=32, description="JWT signing secret")
    access_token_expire_minutes: int = 60 * 24

    # --- Database ------------------------------------------------------------
    database_url: PostgresDsn = Field(
        default="postgresql+asyncpg://rimo:rimo@localhost:5432/rimo",
    )
    db_pool_size: int = 20
    db_max_overflow: int = 10
    db_echo: bool = False

    # --- Redis ---------------------------------------------------------------
    redis_url: RedisDsn = Field(default="redis://localhost:6379/0")

    # --- AI Layer ------------------------------------------------------------
    anthropic_api_key: str = Field(default="", description="Anthropic API key")
    default_model: str = "claude-opus-4-8"
    fast_model: str = "claude-haiku-4-5-20251001"
    max_agent_iterations: int = 25
    agent_temperature: float = 0.2

    # --- Vector store --------------------------------------------------------
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    memory_top_k: int = 8

    # --- GitHub --------------------------------------------------------------
    github_app_id: str = ""
    github_private_key: str = ""
    github_webhook_secret: str = ""
    workspace_root: str = "/data/workspaces"

    # --- Orchestration -------------------------------------------------------
    max_concurrent_projects: int = 10
    max_concurrent_agents_per_project: int = 4
    heartbeat_interval_seconds: int = 15
    task_lease_seconds: int = 900

    # --- Observability -------------------------------------------------------
    log_level: str = "INFO"
    log_json: bool = True
    prometheus_enabled: bool = True
    otel_endpoint: str = ""

    # --- Safety --------------------------------------------------------------
    require_human_approval_for_merge: bool = True
    require_human_approval_for_deploy: bool = True
    allow_repo_deletion: bool = False
    max_files_changed_per_pr: int = 50

    @field_validator("agent_temperature")
    @classmethod
    def _validate_temperature(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("agent_temperature must be between 0 and 1")
        return v

    @property
    def sync_database_url(self) -> str:
        """Synchronous DSN used by Alembic migrations."""
        return str(self.database_url).replace("+asyncpg", "+psycopg")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
