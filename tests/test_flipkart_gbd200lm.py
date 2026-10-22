"""Tests for Flipkart GBD-200LM tracking and bank offer effective price calculations."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from config import Settings
from database import Product
from scrapers.base import ScrapeResult
from scrapers.flipkart import FlipkartScraper
from tracker import Tracker
from run_247_radar import probe_vip_watches


def test_flipkart_extract_offers_and_effective_price():
    scraper = FlipkartScraper()

    # 1. Test INITIAL_STATE bank offer parsing
    html_with_state = """
    <html>
      <head>
        <script>
          window.__INITIAL_STATE__ = {
            "pageDataV4": {
              "page": {
                "data": {
                  "10002": [
                    {
                      "widget": {
                        "data": {
                          "offers": [
                            {"value": {"title": "10% Instant Discount on HDFC Bank Credit Card EMI up to ₹1,250"}},
                            {"value": {"title": "Flat ₹750 off on Axis Bank Credit Cards"}}
                          ]
                        }
                      }
                    }
                  ]
                }
              }
            }
          };
        </script>
      </head>
      <body>
        <script>
          var x = {"contentValue": "Flat ₹750 off on Axis Bank Credit Cards"};
        </script>
        <div>Product Page</div>
      </body>
    </html>
    """
    eff_price, offers = scraper._extract_offers_and_effective_price(html_with_state, base_price=8208.0)
    assert len(offers) >= 1
    assert "₹750" in offers[0]
    # base 8208 - 750 = 7458
    assert eff_price == 7458.0


def test_flipkart_extract_offers_direct_text_callout():
    scraper = FlipkartScraper()

    html_direct = """
    <html>
      <body>
        <div>₹6,881 with Bank offer</div>
      </body>
    </html>
    """
    eff_price, offers = scraper._extract_offers_and_effective_price(html_direct, base_price=8208.0)
    assert eff_price == 6881.0


def test_tracker_should_notify_gbd200lm_rules():
    p = Product(
        id=117,
        url="https://www.flipkart.com/casio-gbd-200lm-1dr-g-shock-dial-luminescent-camouflage-resin-strap-digital-watch-men/p/itme88c68d4590ae?pid=WATGUGJRFGGGEKGR",
        platform="flipkart",
        title="CASIO GBD-200LM-1DR G-SHOCK",
        initial_price=8208.0,
        current_price=None,
        target_price=7500.0,
        percentage_drop_target=None,
        last_checked=None,
        is_active=True,
        last_notified_price=None,
    )

    # 1. Base price <= 7500 without offers -> should notify
    should, _ = Tracker._should_notify(p, old_price=None, new_price=7400.0, effective_price=None)
    assert should is True

    # 2. Base price 8208 (> 7500), but bank offer effective price 6881 (< 7000) -> should notify
    should, _ = Tracker._should_notify(p, old_price=None, new_price=8208.0, effective_price=6881.0)
    assert should is True

    # 3. Base price 8208 (> 7500), bank offer effective price 7200 (> 7000) -> should NOT notify
    should, _ = Tracker._should_notify(p, old_price=None, new_price=8208.0, effective_price=7200.0)
    assert should is False

    # 4. Base price 8208 (> 7500), no offers computed -> should NOT notify
    should, _ = Tracker._should_notify(p, old_price=None, new_price=8208.0, effective_price=None)
    assert should is False


@pytest.mark.asyncio
async def test_probe_vip_watches_gbd200lm_offer_trigger():
    mock_tracker = MagicMock()
    mock_tracker.config = Settings()
    mock_tracker.notifier = MagicMock()
    mock_tracker.notifier.send_telegram = AsyncMock(return_value=True)
    mock_tracker.db = MagicMock()
    mock_tracker.db.get_products = AsyncMock(return_value=[])
    mock_tracker.db.update_price = AsyncMock()
    mock_tracker.db.log_deal_alert = AsyncMock()

    gbd200_vip = [
        {
            "id": 117,
            "name": "CASIO GBD-200LM-1DR",
            "url": "https://www.flipkart.com/casio-gbd-200lm-1dr-g-shock-dial-luminescent-camouflage-resin-strap-digital-watch-men/p/itme88c68d4590ae?pid=WATGUGJRFGGGEKGR",
            "target_price": 7500.0,
            "offer_target_price": 7000.0,
            "default_price": 8208.0,
            "mrp": 12995,
            "tag": "watgugjrfgggekgr",
            "platform": "flipkart",
            "is_active": True,
        }
    ]

    mock_scraper = MagicMock()
    # In stock at base 8208, but effective_price is 6881 (target < 7000 met!)
    mock_scraper.scrape = AsyncMock(return_value=ScrapeResult(
        url="https://www.flipkart.com/casio-gbd-200lm-1dr-g-shock-dial-luminescent-camouflage-resin-strap-digital-watch-men/p/itme88c68d4590ae?pid=WATGUGJRFGGGEKGR",
        platform="flipkart",
        price=8208.0,
        in_stock=True,
        title="CASIO GBD-200LM-1DR",
        effective_price=6881.0,
        offers=["Flat ₹1327 off on Axis Bank Cards"],
    ))

    with patch("run_247_radar.ship_vip_log_to_supabase", new_callable=AsyncMock), \
         patch("run_247_radar.VIP_WATCHES", gbd200_vip), \
         patch("scrapers.get_scraper", return_value=mock_scraper):
        alerts_sent = await probe_vip_watches(mock_tracker)
        assert alerts_sent == 1
        mock_tracker.notifier.send_telegram.assert_awaited_once()
        sent_text = mock_tracker.notifier.send_telegram.await_args[0][0]
        assert "6881" in sent_text
        assert "Target Met!" in sent_text
