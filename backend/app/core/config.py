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
    # Short-lived access token + longer-lived, revocable refresh token.
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 14
    # Explicit CORS allow-list — one source of truth for every environment.
    # Never combine "*" with credentials; this is an explicit list by design.
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    # Per-IP auth throttling (requests / minute).
    rate_limit_login_per_minute: int = 5
    rate_limit_register_per_minute: int = 10
    # Rate-limit storage backend; empty = use redis_url. Tests set memory://.
    ratelimit_storage_uri: str = ""

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
    openai_api_key: str = Field(default="", description="OpenAI API key (optional)")
    google_api_key: str = Field(default="", description="Google AI API key (optional)")
    default_model: str = "claude-opus-4-8"
    fast_model: str = "claude-haiku-4-5-20251001"
    max_agent_iterations: int = 25
    agent_temperature: float = 0.2

    # --- Multi-model routing -------------------------------------------------
    # Enable cost-aware routing: cheap models for trivial work, frontier for
    # design. Falls back to Anthropic-only when other providers aren't keyed.
    routing_enabled: bool = True
    # Per-tier model assignment (provider:model). Routing degrades gracefully:
    # if a provider has no key, the router substitutes the best available
    # Anthropic model so the system never blocks.
    model_trivial: str = "anthropic:claude-haiku-4-5-20251001"
    model_simple: str = "anthropic:claude-haiku-4-5-20251001"
    model_standard: str = "anthropic:claude-sonnet-4-6"
    model_complex: str = "anthropic:claude-opus-4-8"
    # USD per 1M tokens, (input, output). Used by the economic ledger.
    model_prices: dict[str, tuple[float, float]] = {
        "claude-opus-4-8": (15.0, 75.0),
        "claude-sonnet-4-6": (3.0, 15.0),
        "claude-haiku-4-5-20251001": (0.80, 4.0),
        "gpt-4o": (2.50, 10.0),
        "gpt-4o-mini": (0.15, 0.60),
        "gemini-1.5-pro": (1.25, 5.0),
        "gemini-1.5-flash": (0.075, 0.30),
    }

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
    # How often (in main-loop cycles) the slow maintenance pass runs: autonomous
    # research, knowledge-graph rebuilds, and refactor scans.
    maintenance_cycle_interval: int = 20

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
    # Hard financial stop: when a project's cumulative model spend reaches this,
    # the orchestrator pauses it (a real kill-switch, not a soft target). 0 = off.
    max_cost_usd_per_project: float = 25.0

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
