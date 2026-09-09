"""Unit tests for Quick Commerce Radar (qcommerce_radar.py)."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from config import Settings
from qcommerce_radar import QuickCommerceRadar


@pytest.mark.asyncio
async def test_qcommerce_radar_scan_bigbasket():
    radar = QuickCommerceRadar(Settings())

    mock_deals = [
        {
            "title": "Fresho Apple - Royal Gala 1kg",
            "price": 99.0,
            "mrp": 240.0,
            "discount_percent": 58.7,
            "platform": "bigbasket",
            "url": "https://www.bigbasket.com/pd/123",
            "in_stock": True,
        }
    ]

    mock_scraper = MagicMock()
    mock_scraper.scan_deals = AsyncMock(return_value=mock_deals)

    with patch("scrapers.bigbasket.BigBasketScraper.scan_deals", new_callable=AsyncMock) as mock_scan:
        mock_scan.return_value = mock_deals
        found = await radar.scan_bigbasket_deals(min_discount=50.0)
        assert len(found) >= 1
        assert found[0]["title"] == "Fresho Apple - Royal Gala 1kg"
        assert found[0]["price"] == 99.0


@pytest.mark.asyncio
async def test_qcommerce_radar_scan_all_aggregates():
    radar = QuickCommerceRadar(Settings())

    with patch.object(radar, "scan_bigbasket_deals", new_callable=AsyncMock) as mock_bb, \
         patch.object(radar, "scan_blinkit_deals", new_callable=AsyncMock) as mock_bl:
        mock_bb.return_value = [{"title": "Item BB", "price": 50, "mrp": 200, "discount_percent": 75, "platform": "bigbasket", "url": "https://bb/1"}]
        mock_bl.return_value = [{"title": "Item Blinkit", "price": 40, "mrp": 200, "discount_percent": 80, "platform": "blinkit", "url": "https://blinkit/1"}]

        res = await radar.scan_all_qcommerce(min_discount=70.0)
        assert len(res["bigbasket"]) == 1
        assert len(res["blinkit"]) == 1
