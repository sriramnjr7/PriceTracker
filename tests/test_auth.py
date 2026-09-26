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


@pytest.mark.asyncio
async def test_auth_login_vercel_rewrites():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Via _vercel_path query param
        resp = await client.post(
            "/api/index.py?_vercel_path=api/auth/login",
            json={"email": "custom@example.com", "password": settings.dashboard_password}
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["email"] == "custom@example.com"

        # 2. Via x-vercel-matched-path header
        resp2 = await client.post(
            "/api/index.py",
            headers={"x-vercel-matched-path": "/api/auth/login"},
            json={"email": "custom@example.com", "password": settings.dashboard_password}
        )
        assert resp2.status_code == 200
        assert resp2.json()["ok"] is True



@pytest.mark.asyncio
async def test_product_price_history_endpoint():
    from unittest.mock import patch, AsyncMock, MagicMock
    from database import Product

    mock_db = MagicMock()
    mock_db.initialize = AsyncMock()
    mock_db.close = AsyncMock()
    mock_db.get_product = AsyncMock(return_value=Product(
        id=1,
        url="https://amazon.in/dp/B001",
        platform="amazon",
        title="Casio Watch",
        initial_price=2000.0,
        current_price=1800.0,
        target_price=1500.0,
        percentage_drop_target=None,
        last_checked=None,
        is_active=True,
        last_notified_price=None,
    ))
    from datetime import datetime, timezone, timedelta
    now_utc = datetime.now(timezone.utc)
    mock_db.price_history = AsyncMock(return_value=[
        (1800.0, (now_utc - timedelta(days=1)).isoformat()),
        (1900.0, (now_utc - timedelta(days=2)).isoformat()),
        (2000.0, (now_utc - timedelta(days=3)).isoformat()),
    ])

    with patch("api.index.get_database", return_value=mock_db):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/products/1/history?range=weekly")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "success"
            assert data["product_id"] == 1
            assert data["range"] == "weekly"
            assert data["min_price"] == 1800.0
            assert data["max_price"] == 2000.0
            assert len(data["points"]) >= 2

