"""Tests for Flipkart multi-variant & cross-color stock and price tracking."""

import pytest
from unittest.mock import AsyncMock, patch
from bs4 import BeautifulSoup

from database import Database, Product
from notifier import Notifier
from tracker import Tracker
from scrapers.flipkart import FlipkartScraper


MOCK_ALL_OOS_HTML = """
<!DOCTYPE html>
<html>
<head><title>CROCS Unisex LiteRide 360 Clog</title></head>
<body>
  <h1><span>CROCS Unisex LiteRide 360 Clog</span></h1>
  <div class="Nx9bqj">₹6,495</div>
  <div class="yRaY8j">₹6,495</div>
  <div class="z3htrc">Currently Unavailable</div>
  
  <div>
    <div>Selected Color: Taffy Pink</div>
    <div class="swatches-container">
      <a href="/crocs-literide-360-unisex-clogs/p/itm1?pid=SNDG1">Out of stock</a>
      <a href="/crocs-literide-360-clog-blk-sgy/p/itm2?pid=SNDG2">Out of stock</a>
      <a href="/crocs-literide-360-clog-tpk/p/itm3?pid=SNDG3">Out of stock</a>
    </div>
  </div>

  <div>
    <div>Select Size</div>
    <a href="/crocs-literide?pid=SNDG3A&swatchAttr=size">
      <div style="height:1px;"></div><div>7</div>
    </a>
    <a href="/crocs-literide?pid=SNDG3B&swatchAttr=size">
      <div style="height:1px;"></div><div>8</div>
    </a>
  </div>
</body>
</html>
"""

MOCK_IN_STOCK_COLOR_HTML = """
<!DOCTYPE html>
<html>
<head><title>CROCS Unisex LiteRide 360 Clog Blk/SGy</title></head>
<body>
  <h1><span>CROCS Unisex LiteRide 360 Clog Blk/SGy</span></h1>
  <div class="Nx9bqj">₹2,299</div>
  <div class="yRaY8j">₹5,995</div>
  
  <div>
    <div>Selected Color: Black / Slate Grey</div>
  </div>

  <div>
    <div>Select Size</div>
    <a href="/crocs-literide?pid=SNDG2A&swatchAttr=size">
      <div>7</div>
    </a>
    <a href="/crocs-literide?pid=SNDG2B&swatchAttr=size">
      <div>8</div>
    </a>
    <a href="/crocs-literide?pid=SNDG2C&swatchAttr=size">
      <div style="height:1px;"></div><div>9</div>
    </a>
  </div>
</body>
</html>
"""


@pytest.mark.asyncio
async def test_check_product_variants_all_oos():
    scraper = FlipkartScraper()
    with patch.object(scraper, "_static_fetch", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = MOCK_ALL_OOS_HTML
        res = await scraper.check_product_variants("https://www.flipkart.com/crocs-literide-360-clog-tpk/p/itm3?pid=SNDG3")

    assert res["in_stock"] is False
    assert res["lowest_price"] is None
    assert len(res["in_stock_variants"]) == 0
    assert res["total_colors_checked"] >= 3
    # Verifies only 1 request was made because all swatches were marked 'Out of stock'
    assert mock_fetch.call_count == 1


@pytest.mark.asyncio
async def test_check_product_variants_with_in_stock_swatch():
    scraper = FlipkartScraper()

    # Primary page has one in-stock swatch (SNDG2 - Black/Slate Grey)
    mock_primary_with_one_instock = MOCK_ALL_OOS_HTML.replace(
        '<a href="/crocs-literide-360-clog-blk-sgy/p/itm2?pid=SNDG2">Out of stock</a>',
        '<a href="/crocs-literide-360-clog-blk-sgy/p/itm2?pid=SNDG2">Black / Slate Grey</a>',
    )

    async def side_effect_fetch(url):
        if "pid=SNDG2" in url:
            return MOCK_IN_STOCK_COLOR_HTML
        return mock_primary_with_one_instock

    with patch.object(scraper, "_static_fetch", side_effect=side_effect_fetch) as mock_fetch:
        res = await scraper.check_product_variants("https://www.flipkart.com/crocs-literide-360-clog-tpk/p/itm3?pid=SNDG3")

    assert res["in_stock"] is True
    assert res["lowest_price"] == 2299.0
    assert len(res["in_stock_variants"]) == 1
    variant = res["in_stock_variants"][0]
    assert variant["price"] == 2299.0
    assert variant["mrp"] == 5995.0
    assert "7" in variant["sizes"]
    assert "8" in variant["sizes"]
    assert "9" not in variant["sizes"]  # Size 9 has strike-through


@pytest.mark.asyncio
async def test_tracker_flipkart_variants_triggers_alert():
    mock_db = AsyncMock(spec=Database)
    mock_db.update_price = AsyncMock()
    mock_db.set_last_notified = AsyncMock()
    mock_db.log_deal_alert = AsyncMock()
    mock_db.is_deal_recently_notified = AsyncMock(return_value=False)

    mock_notifier = AsyncMock(spec=Notifier)
    mock_notifier.send_message = AsyncMock(return_value=True)

    tracker = Tracker(mock_db, mock_notifier)

    product = Product(
        id=18,
        url="https://www.flipkart.com/crocs-literide-360-clog-tpk/p/itm3?pid=SNDG3",
        platform="flipkart",
        title="CROCS Unisex LiteRide 360 Clog (All Colors & Sizes)",
        initial_price=6495.0,
        current_price=None,
        target_price=2500.0,
        percentage_drop_target=None,
        last_checked="2026-09-10T12:00:00",
        is_active=True,
        last_notified_price=None,
    )

    # 1. When all variants are out of stock -> No notification
    with patch("scrapers.flipkart.FlipkartScraper.check_product_variants", new_callable=AsyncMock) as mock_variants:
        mock_variants.return_value = {
            "model_title": "CROCS Unisex LiteRide 360 Clog",
            "in_stock": False,
            "lowest_price": None,
            "in_stock_variants": [],
            "total_colors_checked": 13,
        }
        alerted = await tracker.check_product(product)
        assert alerted is False
        assert mock_notifier.send_message.call_count == 0

    # 2. When an in-stock variant exists but price > target (e.g. 3840 > 2500) -> No notification
    with patch("scrapers.flipkart.FlipkartScraper.check_product_variants", new_callable=AsyncMock) as mock_variants:
        mock_variants.return_value = {
            "model_title": "CROCS Unisex LiteRide 360 Clog",
            "in_stock": True,
            "lowest_price": 3840.0,
            "in_stock_variants": [
                {
                    "color": "Black / Slate Grey",
                    "sizes": ["7", "8"],
                    "price": 3840.0,
                    "mrp": 5995.0,
                    "url": "https://www.flipkart.com/crocs-literide-360-clog-blk-sgy/p/itm2?pid=SNDG2",
                }
            ],
            "total_colors_checked": 13,
        }
        alerted = await tracker.check_product(product)
        assert alerted is False
        assert mock_notifier.send_message.call_count == 0

    # 3. When an in-stock variant drops to 2299 <= 2500 -> TRIGGERS NOTIFICATION!
    with patch("scrapers.flipkart.FlipkartScraper.check_product_variants", new_callable=AsyncMock) as mock_variants:
        mock_variants.return_value = {
            "model_title": "CROCS Unisex LiteRide 360 Clog",
            "in_stock": True,
            "lowest_price": 2299.0,
            "in_stock_variants": [
                {
                    "color": "Navy / Blue",
                    "sizes": ["8", "9"],
                    "price": 2299.0,
                    "mrp": 5995.0,
                    "url": "https://www.flipkart.com/crocs-literide-360-clog-nvy/p/itm4?pid=SNDG4",
                }
            ],
            "total_colors_checked": 13,
        }
        alerted = await tracker.check_product(product)
        assert alerted is True
        assert mock_notifier.send_message.call_count == 1
        sent_msg = mock_notifier.send_message.call_args[0][0]
        assert "CROCS LITERIDE 360 IN-STOCK DEAL" in sent_msg
        assert "Navy / Blue" in sent_msg
        assert "8, 9" in sent_msg
        assert "₹2,299" in sent_msg
        mock_db.log_deal_alert.assert_called_once()
