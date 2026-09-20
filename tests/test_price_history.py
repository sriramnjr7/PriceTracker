import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta
from api.index import get_product_price_history
from database import Product

@pytest.mark.asyncio
async def test_get_product_price_history_with_logs():
    fake_product = Product(
        id=10,
        url="https://www.flipkart.com/sample-product/p/itm123",
        platform="flipkart",
        title="Sample Headphone",
        initial_price=7999.0,
        current_price=7999.0,
        target_price=4000.0,
        percentage_drop_target=None,
        last_checked=None,
        is_active=True,
        last_notified_price=None,
    )
    now = datetime.now(timezone.utc)
    fake_logs = [
        (7999.0, (now - timedelta(hours=i)).isoformat())
        for i in range(10)
    ]

    mock_db = MagicMock()
    mock_db.initialize = AsyncMock()
    mock_db.close = AsyncMock()
    mock_db.get_product = AsyncMock(return_value=fake_product)
    mock_db.price_history = AsyncMock(return_value=fake_logs)

    with patch("api.index.get_database", return_value=mock_db):
        resp = await get_product_price_history(10, timeframe="weekly")
        assert resp.status_code == 200
        import json
        data = json.loads(resp.body.decode())
        assert data["status"] == "success"
        assert data["product_id"] == 10
        assert data["title"] == "Sample Headphone"
        assert len(data["points"]) == 10
        assert data["min_price"] == 7999.0
        assert data["max_price"] == 7999.0

@pytest.mark.asyncio
async def test_get_product_price_history_fallback_when_no_logs():
    fake_product = Product(
        id=1,
        url="https://casiostore.bhawar.com/products/casio-g-shock",
        platform="casio",
        title="Casio Watch",
        initial_price=12995.0,
        current_price=None,
        target_price=10000.0,
        percentage_drop_target=None,
        last_checked=None,
        is_active=True,
        last_notified_price=None,
    )

    mock_db = MagicMock()
    mock_db.initialize = AsyncMock()
    mock_db.close = AsyncMock()
    mock_db.get_product = AsyncMock(return_value=fake_product)
    mock_db.price_history = AsyncMock(return_value=[])

    with patch("api.index.get_database", return_value=mock_db):
        resp = await get_product_price_history(1, timeframe="weekly")
        assert resp.status_code == 200
        import json
        data = json.loads(resp.body.decode())
        assert data["status"] == "success"
        assert data["product_id"] == 1
        assert len(data["points"]) >= 2
        assert data["points"][0]["price"] == 12995.0
