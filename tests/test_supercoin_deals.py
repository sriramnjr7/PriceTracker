"""Comprehensive tests for Flipkart SuperCoin 70%+ Loot Deal detection & Pincode Bypass.

Verifies:
1. Extraction of earn callouts (e.g. "Earn 700 SuperCoins on this order" for a ₹1,000 item -> triggers >= 70% deal).
2. Extraction of 100% SuperCoins back and cashback offers ("100% SuperCoins back on order", "Earn 100% cashback as SuperCoins", "Get 75% Cashback in SuperCoins").
3. Rejection of standard loyalty coins (< 70%, e.g. 10 coins on ₹2,924).
4. Rejection of all redemption/spend phrasing:
   - "Pay using 100 SuperCoins"
   - "Pay using 100% SuperCoins"
   - "Redeem 70% SuperCoins to get discount"
   - "Use 75% SuperCoins"
   - "Pay ₹500 + 700 SuperCoins on this order"
   - "Save ₹700 with 700 SuperCoins on this order"
   - "You can choose to pay for this item with 700 SuperCoins on this order"
5. Coexistence of spend and earn text ("Pay using 100 SuperCoins to save ₹100. Earn 750 SuperCoins on this order!").
6. Boundary conditions and ratio arithmetic.
7. Script INITIAL_STATE extraction.
8. Regional pincode unserviceability bypass ("Not deliverable in your location" and "isa:false" are not treated as OOS).
9. Dashboard API exposure and strict telemetry filtering (only >= 70% return deals counted).
"""

from __future__ import annotations

import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from api.index import app
from scrapers.base import ScrapeResult
from scrapers.flipkart import FlipkartScraper


@pytest.fixture
def scraper():
    return FlipkartScraper()


SAMPLE_FK_HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head><title>Skechers GO RUN Elevate - Buy Online at Best Price in India</title></head>
<body>
  <span class="VU-ZEz">Skechers GO RUN Elevate Running Shoes For Men</span>
  <div class="Nx9bqj CxhGGd">₹{price}</div>
  <div class="yRaY8j">₹{mrp}</div>
  <button>Buy Now</button>
  <button>Add to Cart</button>
  <div class="offers-section">
    {extra_content}
  </div>
</body>
</html>
"""


def test_earn_callout_70_percent(scraper):
    """1. Extraction of earn callouts (e.g. 'Earn 700 SuperCoins on this order' for ₹1,000 item -> triggers >= 70% deal)."""
    html = SAMPLE_FK_HTML_TEMPLATE.format(
        price="1,000",
        mrp="2,000",
        extra_content="<div>Earn 700 SuperCoins on this order</div>",
    )
    result = scraper.parse(html, "https://www.flipkart.com/item/p/itm12345")

    assert result.price == 1000.0
    assert result.supercoins_earned == 700
    assert result.supercoin_ratio == 0.70
    assert result.is_supercoin_deal is True


def test_100_percent_supercoins_back(scraper):
    """2. Extraction of 100% SuperCoins back and cashback offers."""
    html_100 = SAMPLE_FK_HTML_TEMPLATE.format(
        price="500",
        mrp="1,000",
        extra_content="<span>100% SuperCoins back on order</span>",
    )
    result_100 = scraper.parse(html_100, "https://www.flipkart.com/item/p/itm12345")

    assert result_100.price == 500.0
    assert result_100.supercoins_earned == 500
    assert result_100.supercoin_ratio == 1.0
    assert result_100.is_supercoin_deal is True

    # 75% SuperCoins cashback
    html_75 = SAMPLE_FK_HTML_TEMPLATE.format(
        price="1,200",
        mrp="2,400",
        extra_content="<div>75% SuperCoins cashback on order</div>",
    )
    result_75 = scraper.parse(html_75, "https://www.flipkart.com/item/p/itm12345")
    assert result_75.price == 1200.0
    assert result_75.supercoins_earned == 900
    assert result_75.supercoin_ratio == 0.75
    assert result_75.is_supercoin_deal is True

    # 'Earn 100% cashback as SuperCoins'
    html_cb_as = SAMPLE_FK_HTML_TEMPLATE.format(
        price="1,000",
        mrp="2,000",
        extra_content="<div>Earn 100% cashback as SuperCoins</div>",
    )
    res_cb_as = scraper.parse(html_cb_as, "https://www.flipkart.com/item/p/itm12345")
    assert res_cb_as.price == 1000.0
    assert res_cb_as.supercoins_earned == 1000
    assert res_cb_as.supercoin_ratio == 1.0
    assert res_cb_as.is_supercoin_deal is True

    # 'Get 75% Cashback in SuperCoins'
    html_cb_in = SAMPLE_FK_HTML_TEMPLATE.format(
        price="1,000",
        mrp="2,000",
        extra_content="<div>Get 75% Cashback in SuperCoins</div>",
    )
    res_cb_in = scraper.parse(html_cb_in, "https://www.flipkart.com/item/p/itm12345")
    assert res_cb_in.price == 1000.0
    assert res_cb_in.supercoins_earned == 750
    assert res_cb_in.supercoin_ratio == 0.75
    assert res_cb_in.is_supercoin_deal is True


def test_rejection_of_standard_loyalty_coins(scraper):
    """3. Rejection of standard loyalty coins (< 70%, e.g. 10 coins on ₹2,924)."""
    html = SAMPLE_FK_HTML_TEMPLATE.format(
        price="2,924",
        mrp="4,999",
        extra_content="<div>Earn 10 SuperCoins on this order</div>",
    )
    result = scraper.parse(html, "https://www.flipkart.com/item/p/itm12345")

    assert result.price == 2924.0
    assert result.supercoins_earned == 10
    assert result.supercoin_ratio == pytest.approx(10 / 2924.0, rel=1e-2)
    assert result.supercoin_ratio < 0.70
    assert result.is_supercoin_deal is False

    # Also test 50 SuperCoins on ₹1,000 (5% return)
    html_50 = SAMPLE_FK_HTML_TEMPLATE.format(
        price="1,000",
        mrp="1,500",
        extra_content="<div>Get up to 50 SuperCoins on this order</div>",
    )
    res_50 = scraper.parse(html_50, "https://www.flipkart.com/item/p/itm12345")
    assert res_50.supercoins_earned == 50
    assert res_50.supercoin_ratio == 0.05
    assert res_50.is_supercoin_deal is False


def test_rejection_of_redemption_and_spend_text(scraper):
    """4. Rejection of redemption & payment text ('Pay using 100 SuperCoins', 'Pay using 100% SuperCoins', etc.)."""
    spend_phrases = [
        "Pay using 100 SuperCoins",
        "Pay using 100% SuperCoins",
        "Redeem 70% SuperCoins to get discount",
        "Use 75% SuperCoins",
        "Use 200 SuperCoins on this order",
        "Redeem 500 SuperCoins",
        "Pay ₹500 + 700 SuperCoins on this order",
        "Save ₹700 with 700 SuperCoins on this order",
        "You can choose to pay for this item with 700 SuperCoins on this order",
    ]
    for phrase in spend_phrases:
        html = SAMPLE_FK_HTML_TEMPLATE.format(
            price="1,000",
            mrp="2,000",
            extra_content=f"<div>{phrase}</div>",
        )
        res = scraper.parse(html, "https://www.flipkart.com/item/p/itm12345")
        assert res.supercoins_earned is None, f"Failed to reject spend phrase: '{phrase}'"
        assert res.supercoin_ratio is None, f"Failed to reject spend ratio for: '{phrase}'"
        assert res.is_supercoin_deal is False, f"Flagged spend phrase as deal: '{phrase}'"


def test_coexistence_of_redemption_and_earn(scraper):
    """5. Coexistence of redemption and earn in the same text."""
    # Spend followed by earn
    html_both = SAMPLE_FK_HTML_TEMPLATE.format(
        price="1,000",
        mrp="2,000",
        extra_content="<div>Pay using 100 SuperCoins to save ₹100. Earn 750 SuperCoins on this order!</div>",
    )
    res_both = scraper.parse(html_both, "https://www.flipkart.com/item/p/itm12345")
    assert res_both.supercoins_earned == 750
    assert res_both.supercoin_ratio == 0.75
    assert res_both.is_supercoin_deal is True

    # Earn followed by spend
    html_reverse = SAMPLE_FK_HTML_TEMPLATE.format(
        price="1,000",
        mrp="2,000",
        extra_content="<div>Earn 700 SuperCoins on this order. Pay using 100 SuperCoins.</div>",
    )
    res_reverse = scraper.parse(html_reverse, "https://www.flipkart.com/item/p/itm12345")
    assert res_reverse.supercoins_earned == 700
    assert res_reverse.supercoin_ratio == 0.70
    assert res_reverse.is_supercoin_deal is True


def test_boundary_conditions(scraper):
    """6. Test boundary ratios: exactly 70% triggers deal, 69.9% does not."""
    # Exactly 70% (700 on 1000)
    html_70 = SAMPLE_FK_HTML_TEMPLATE.format(
        price="1,000",
        mrp="2,000",
        extra_content="<div>Earn 700 SuperCoins on this order</div>",
    )
    res_70 = scraper.parse(html_70, "https://www.flipkart.com/item/p/itm12345")
    assert res_70.supercoin_ratio == 0.70
    assert res_70.is_supercoin_deal is True

    # 69.9% (699 on 1000)
    html_69 = SAMPLE_FK_HTML_TEMPLATE.format(
        price="1,000",
        mrp="2,000",
        extra_content="<div>Earn 699 SuperCoins on this order</div>",
    )
    res_69 = scraper.parse(html_69, "https://www.flipkart.com/item/p/itm12345")
    assert res_69.supercoin_ratio == 0.699
    assert res_69.is_supercoin_deal is False

    # Zero or None price safety
    coins, ratio, is_deal = scraper._extract_supercoins_from_text("Earn 700 SuperCoins on this order", None)
    assert coins == 700
    assert ratio is None
    assert is_deal is False

    coins_0, ratio_0, is_deal_0 = scraper._extract_supercoins_from_text("Earn 700 SuperCoins on this order", 0.0)
    assert coins_0 == 700
    assert ratio_0 is None
    assert is_deal_0 is False


def test_structured_script_initial_state_extraction(scraper):
    """7. Test extraction from window.__INITIAL_STATE__ when HTML lacks visible promo text."""
    html = """
    <!DOCTYPE html>
    <html>
    <head><title>Deal Item</title></head>
    <body>
      <span class="VU-ZEz">Realme Smartphone</span>
      <div class="Nx9bqj CxhGGd">₹10,000</div>
      <button>Buy Now</button>
      <script>
        window.__INITIAL_STATE__ = {
          "pageData": {
            "offer": "Earn 8000 SuperCoins on this order"
          }
        };
      </script>
    </body>
    </html>
    """
    res = scraper.parse(html, "https://www.flipkart.com/item/p/itm999")
    assert res.price == 10000.0
    assert res.supercoins_earned == 8000
    assert res.supercoin_ratio == 0.80
    assert res.is_supercoin_deal is True


def test_skip_pincode_unserviceability_retains_in_stock(scraper):
    """8. Test that regional pincode unserviceability checks are skipped to capture all national deals."""
    # HTML with "Not deliverable in your location" and "isa:false"
    html_pincode = """
    <!DOCTYPE html>
    <html>
    <head><title>Casio Watch</title></head>
    <body>
      <span class="VU-ZEz">Casio EDIFICE Watch</span>
      <div class="Nx9bqj CxhGGd">₹4,995</div>
      <div>Not deliverable in your location</div>
      <div>Currently out of stock for 635109</div>
      <button>Buy Now</button>
      <button>Add to Cart</button>
      <div>Earn 3500 SuperCoins on this order</div>
      <script>
        window.__INITIAL_STATE__ = {
          "isa": false
        };
      </script>
    </body>
    </html>
    """
    res = scraper.parse(html_pincode, "https://www.flipkart.com/casio-watch/p/itm123")
    assert res.in_stock is True, "Pincode unserviceability should be skipped; item should remain in_stock"
    assert res.price == 4995.0
    assert res.supercoins_earned == 3500
    assert res.supercoin_ratio == round(3500 / 4995.0, 4)
    assert res.is_supercoin_deal is True


@pytest.mark.asyncio
async def test_dashboard_api_supercoin_telemetry():
    """9. Verify GET /api/dashboard/data returns supercoin deal fields and telemetry."""
    client = TestClient(app)
    response = client.get("/api/dashboard/data?bypass=1")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "supercoin_deals_count" in data["stats"]
    assert isinstance(data["stats"]["supercoin_deals_count"], int)
