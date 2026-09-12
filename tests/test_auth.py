import pytest
from httpx import ASGITransport, AsyncClient
from api.index import app
from config import settings


@pytest.mark.asyncio
async def test_auth_login_success():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/auth/login",
            json={"email": "custom@example.com", "password": settings.dashboard_password}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["email"] == "custom@example.com"


@pytest.mark.asyncio
async def test_auth_login_invalid_password():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/auth/login",
            json={"email": "custom@example.com", "password": "wrong-password-xyz"}
        )
        assert resp.status_code == 401
        assert "Invalid credentials" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_auth_login_default_email_fallback():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/auth/login",
            json={"password": settings.dashboard_password}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "@" in data["email"]
