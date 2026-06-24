"""End-to-end API tests against the real ASGI app and a real database.

Skips automatically if no database is reachable (e.g. a pure unit-test run
without the Postgres service), so the suite stays green everywhere while still
exercising the full request path in CI.
"""
from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.db.session import Base, engine
from app.main import app

pytestmark = pytest.mark.asyncio


async def _db_available() -> bool:
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest.fixture(autouse=True)
async def _schema():
    if not await _db_available():
        pytest.skip("database not available")
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _auth_headers(client: AsyncClient) -> dict[str, str]:
    email = f"user-{uuid.uuid4().hex[:8]}@rimo.example"
    reg = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "supersecret123", "full_name": "Test Operator"},
    )
    assert reg.status_code == 201, reg.text
    # login uses form-encoded OAuth2 password flow
    login = await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": "supersecret123"},
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def test_health(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] in {"ok", "healthy"}


async def test_register_login_me(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["email"].endswith("@rimo.example")


async def test_unauthenticated_dashboard_rejected(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/dashboard/summary")
    assert resp.status_code in {401, 403}


async def test_create_and_list_project(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    create = await client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "Acme API", "mission": "Ship a payments service"},
    )
    assert create.status_code in {200, 201}, create.text
    project = create.json()
    assert project["name"] == "Acme API"
    assert project["slug"]

    listing = await client.get("/api/v1/projects", headers=headers)
    assert listing.status_code == 200
    assert any(p["id"] == project["id"] for p in listing.json())


async def test_project_provisions_ten_agents(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    create = await client.post(
        "/api/v1/projects", headers=headers, json={"name": "Floor Test"}
    )
    pid = create.json()["id"]
    agents = await client.get(f"/api/v1/projects/{pid}/agents", headers=headers)
    assert agents.status_code == 200
    # The company is fully staffed: all ten roles exist for the project.
    roles = {a["role"] for a in agents.json()}
    assert len(roles) == 10


async def test_dashboard_summary_shape(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    resp = await client.get("/api/v1/dashboard/summary", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    for key in (
        "projects_active",
        "agents_running",
        "tasks_queued",
        "prs_open",
        "deployments_today",
        "pending_approvals",
    ):
        assert key in body
