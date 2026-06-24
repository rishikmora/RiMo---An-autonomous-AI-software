"""RiMo API application factory.

Wires together configuration, structured logging, CORS, Prometheus metrics,
exception handling, and the versioned API router. The ASGI app is exposed as
``app`` for `uvicorn app.main:app`.
"""
from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text

from app.api import api_router
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.core.ratelimit import limiter
from app.core.trace import bind_trace_id, clear_trace_id
from app.db.session import engine
from app.orchestration.event_bus import get_event_bus

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup/shutdown: verify dependencies, then dispose cleanly."""
    configure_logging()
    logger.info("api_starting", env=settings.app_env, version=app.version)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("database_connection_ok")
    except Exception as exc:  # pragma: no cover - surfaced at boot only
        logger.error("database_connection_failed", error=str(exc))
    yield
    await engine.dispose()
    await get_event_bus().close()
    logger.info("api_stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="RiMo — Autonomous Software Engineering Platform",
        description=(
            "RiMo (Rishik Mora AI) is an autonomous, multi-agent software "
            "engineering platform. Ten specialist agents plan, build, review, "
            "test, secure, ship, and deploy software around the clock."
        ),
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url=f"{settings.api_v1_prefix}/openapi.json",
    )

    # --- Rate limiting ------------------------------------------------------
    # The limiter is attached to app state; sensitive routes opt in via the
    # @limiter.limit decorator (see app/api/auth.py). Exceeding a limit returns
    # HTTP 429 with Retry-After.
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # --- CORS ---------------------------------------------------------------
    # Explicit allow-list from config — one source of truth for every
    # environment. Never "*" with credentials (the spec forbids it and browsers
    # reject it), so origins are always enumerated.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Process-Time-Ms", "X-Request-Id"],
    )

    # --- Request timing + trace correlation ---------------------------------
    @app.middleware("http")
    async def add_process_time_header(request: Request, call_next):  # type: ignore[no-untyped-def]
        # Honor an inbound trace id (e.g. from a gateway) or mint a fresh one,
        # and bind it so every downstream log line shares the id.
        incoming = request.headers.get("X-Request-Id")
        trace_id = bind_trace_id(incoming)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            clear_trace_id()
        elapsed_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Process-Time-Ms"] = f"{elapsed_ms:.1f}"
        response.headers["X-Request-Id"] = trace_id
        if settings.prometheus_enabled:
            _record_request(request.method, request.url.path, response.status_code, elapsed_ms)
        return response

    # --- Exception handlers -------------------------------------------------
    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": exc.errors(), "body": "validation_error"},
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled_exception", path=request.url.path, error=str(exc))
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"},
        )

    # --- Health & metrics ---------------------------------------------------
    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": settings.app_name, "env": settings.app_env}

    @app.get("/ready", tags=["system"])
    async def ready() -> Response:
        """Readiness: a pod that can't reach Postgres *or* Redis is not ready."""
        checks: dict[str, str] = {}
        ok = True

        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            checks["postgres"] = "ok"
        except Exception:
            checks["postgres"] = "unreachable"
            ok = False

        try:
            import redis.asyncio as aioredis

            client = aioredis.from_url(str(settings.redis_url))
            try:
                await client.ping()
                checks["redis"] = "ok"
            finally:
                await client.aclose()
        except Exception:
            checks["redis"] = "unreachable"
            ok = False

        # Agents can't run at all without an Anthropic key; surface it (not fatal
        # for readiness so the dashboard stays reachable, but visible).
        checks["anthropic_key"] = "present" if settings.anthropic_api_key else "missing"

        status_code = 200 if ok else 503
        return JSONResponse(
            {"status": "ready" if ok else "not_ready", "checks": checks},
            status_code=status_code,
        )

    if settings.prometheus_enabled:
        _install_metrics(app)

    app.include_router(api_router)
    return app


# --- Prometheus ------------------------------------------------------------
try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        Counter,
        Histogram,
        generate_latest,
    )

    _REQUESTS = Counter(
        "rimo_http_requests_total",
        "Total HTTP requests",
        ["method", "path", "status"],
    )
    _LATENCY = Histogram(
        "rimo_http_request_duration_ms",
        "HTTP request duration in milliseconds",
        ["method", "path"],
        buckets=(5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000),
    )
    _METRICS_AVAILABLE = True
except Exception:  # pragma: no cover - prometheus optional
    _METRICS_AVAILABLE = False


def _record_request(method: str, path: str, status_code: int, elapsed_ms: float) -> None:
    if not _METRICS_AVAILABLE:
        return
    # Collapse high-cardinality ids so the metric stays bounded.
    label_path = _normalise_path(path)
    _REQUESTS.labels(method=method, path=label_path, status=str(status_code)).inc()
    _LATENCY.labels(method=method, path=label_path).observe(elapsed_ms)


def _normalise_path(path: str) -> str:
    parts = []
    for seg in path.split("/"):
        if len(seg) >= 32 and "-" in seg:
            parts.append("{id}")
        else:
            parts.append(seg)
    return "/".join(parts) or "/"


def _install_metrics(app: FastAPI) -> None:
    if not _METRICS_AVAILABLE:
        logger.info("prometheus_unavailable_skipping_metrics")
        return

    @app.get("/metrics", tags=["system"], include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


app = create_app()
