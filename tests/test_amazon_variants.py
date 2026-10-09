"""Tests for Amazon multi-variant (Twister) & cross-color stock and price tracking."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bs4 import BeautifulSoup

from database import Database, Product
from notifier import Notifier
from tracker import Tracker
from scrapers.amazon import AmazonScraper


MOCK_AMAZON_TWISTER_HTML = """
<!DOCTYPE html>
<html>
<head><title>8Bitdo Ultimate 2C Wireless Controller</title></head>
<body>
  <span id="productTitle">8Bitdo Ultimate 2C Wireless Controller for Windows PC & Android</span>
  <div id="corePriceDisplay_desktop_feature_div">
    <span class="a-price priceToPay"><span class="a-offscreen">₹2,999</span></span>
    <span class="a-price a-text-price"><span class="a-offscreen">₹3,999</span></span>
  </div>
  <div id="availability">
    <span class="a-size-medium a-color-success">In stock</span>
  </div>

  <script type="text/javascript">
    P.register('twister-js-init-dpx-data', function() {
      var dataToReturn = {
        "dimensionValuesDisplayData": {
          "B0FX3TJ5RX": ["Transparent Black"],
          "B0D739FJLG": ["Green"],
          "B0D73398R9": ["Peach"]
        }
      };
      return dataToReturn;
    });
  </script>
</body>
</html>
"""

MOCK_PEACH_OOS_HTML = """
<!DOCTYPE html>
<html>
<head><title>8Bitdo Ultimate 2C - Peach</title></head>
<body>
  <span id="productTitle">8Bitdo Ultimate 2C Wireless Controller (Peach)</span>
  <div id="availability">
    <span class="a-color-price">Currently unavailable.</span>
  </div>
</body>
</html>
"""

MOCK_GREEN_DEAL_HTML = """
<!DOCTYPE html>
<html>
<head><title>8Bitdo Ultimate 2C - Green</title></head>
<body>
  <span id="productTitle">8Bitdo Ultimate 2C Wireless Controller (Green)</span>
  <div id="corePriceDisplay_desktop_feature_div">
    <span class="a-price priceToPay"><span class="a-offscreen">₹2,499</span></span>
    <span class="a-price a-text-price"><span class="a-offscreen">₹3,999</span></span>
  </div>
  <div id="availability">
    <span class="a-color-success">In stock</span>
  </div>
</body>
</html>
"""


def test_extract_twister_variants_json():
    scraper = AmazonScraper()
    soup = BeautifulSoup(MOCK_AMAZON_TWISTER_HTML, "html.parser")
    variants = scraper._extract_twister_variants(soup, MOCK_AMAZON_TWISTER_HTML)
    assert len(variants) == 3
    assert variants["B0FX3TJ5RX"] == "Transparent Black"
    assert variants["B0D739FJLG"] == "Green"
    assert variants["B0D73398R9"] == "Peach"


def test_extract_twister_variants_dom():
    scraper = AmazonScraper()
    dom_html = """
    <ul>
      <li data-defaultasin="B0FX3TJ5RX" title="Click to select Transparent Black">
        <img alt="Transparent Black" />
      </li>
      <li data-defaultasin="B0D739FJLG" title="Green">
        <img alt="Green" />
      </li>
    </ul>
    """
    soup = BeautifulSoup(dom_html, "html.parser")
    variants = scraper._extract_twister_variants(soup, dom_html)
    assert len(variants) == 2
    assert variants["B0FX3TJ5RX"] == "Transparent Black"
    assert variants["B0D739FJLG"] == "Green"


@pytest.mark.asyncio
async def test_check_product_variants_amazon():
    scraper = AmazonScraper()

    async def mock_fetch(url):
        if "B0D739FJLG" in url:
            return MOCK_GREEN_DEAL_HTML
        if "B0D73398R9" in url:
            return MOCK_PEACH_OOS_HTML
        return MOCK_AMAZON_TWISTER_HTML

    with patch.object(scraper, "_static_fetch", side_effect=mock_fetch):
        res = await scraper.check_product_variants("https://www.amazon.in/dp/B0FX3TJ5RX/ref=twister_B0DJJDQK94")

    assert res["in_stock"] is True
    assert res["lowest_price"] == 2499.0
    assert len(res["in_stock_variants"]) == 2
    # Transparent Black (2999) and Green (2499) are in stock; Peach is OOS
    colors = [v["color"] for v in res["in_stock_variants"]]
    assert "Transparent Black" in colors
    assert "Green" in colors
    assert "Peach" not in colors


@pytest.mark.asyncio
async def test_tracker_amazon_variants_triggers_alert():
    mock_db = AsyncMock(spec=Database)
    mock_db.update_price = AsyncMock()
    mock_db.set_last_notified = AsyncMock()
    mock_db.log_deal_alert = AsyncMock()
    mock_db.is_deal_recently_notified = AsyncMock(return_value=False)

    mock_notifier = AsyncMock(spec=Notifier)
    mock_notifier.send_message = AsyncMock(return_value=True)

    tracker = Tracker(mock_db, mock_notifier)

    product = Product(
        id=20,
        url="https://www.amazon.in/dp/B0FX3TJ5RX/ref=twister_B0DJJDQK94",
        platform="amazon",
        title="8Bitdo Ultimate 2C Wireless Controller (All Colors / Joystick - Variants)",
        initial_price=2999.0,
        current_price=2999.0,
        target_price=2600.0,
        percentage_drop_target=None,
        last_checked="2026-09-10T12:00:00",
        is_active=True,
        last_notified_price=None,
    )

    # 1. When all variants are out of stock -> No notification
    with patch("scrapers.amazon.AmazonScraper.check_product_variants", new_callable=AsyncMock) as mock_variants:
        mock_variants.return_value = {
            "model_title": "8Bitdo Ultimate 2C Wireless Controller",
            "in_stock": False,
            "lowest_price": None,
            "in_stock_variants": [],
            "total_variants_checked": 5,
        }
        alerted = await tracker.check_product(product)
        assert alerted is False
        assert mock_notifier.send_message.call_count == 0

    # 2. When variants are in stock but price > target (e.g. 2999 > 2600) -> No notification
    with patch("scrapers.amazon.AmazonScraper.check_product_variants", new_callable=AsyncMock) as mock_variants:
        mock_variants.return_value = {
            "model_title": "8Bitdo Ultimate 2C Wireless Controller",
            "in_stock": True,
            "lowest_price": 2999.0,
            "in_stock_variants": [
                {
                    "color": "Transparent Black",
                    "asin": "B0FX3TJ5RX",
                    "price": 2999.0,
                    "mrp": 3999.0,
                    "url": "https://www.amazon.in/dp/B0FX3TJ5RX",
                }
            ],
            "total_variants_checked": 5,
        }
        alerted = await tracker.check_product(product)
        assert alerted is False
        assert mock_notifier.send_message.call_count == 0

    # 3. When any variant drops below target (e.g. Green at 2499 <= 2600) -> TRIGGERS ALERT!
    with patch("scrapers.amazon.AmazonScraper.check_product_variants", new_callable=AsyncMock) as mock_variants:
        mock_variants.return_value = {
            "model_title": "8Bitdo Ultimate 2C Wireless Controller",
            "in_stock": True,
            "lowest_price": 2499.0,
            "in_stock_variants": [
                {
                    "color": "Green",
                    "asin": "B0D739FJLG",
                    "price": 2499.0,
                    "mrp": 3999.0,
                    "url": "https://www.amazon.in/dp/B0D739FJLG",
                }
            ],
            "total_variants_checked": 5,
        }
        alerted = await tracker.check_product(product)
        assert alerted is True
        assert mock_notifier.send_message.call_count == 1
        sent_msg = mock_notifier.send_message.call_args[0][0]
        assert "8BITDO JOYSTICK IN-STOCK DEAL" in sent_msg
        assert "Green" in sent_msg
        assert "₹2,499" in sent_msg
        assert "Below ₹2,600" in sent_msg
        mock_db.log_deal_alert.assert_called_once()
