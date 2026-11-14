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

from unittest.mock import AsyncMock, MagicMock, patch
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


def test_user_reported_supercoin_deals_extraction(scraper):
    """10. Verify extraction of all user-reported deal samples (Watches, Brillare Beauty, Perfumes)."""
    samples = [
        (
            "Hilfiger NCTH1791382 Denim Analog Watch - For Men\nPrice: ₹10,960\nSuperCoins back: ₹10,851 (99.01%)\nSeller: RetailNet",
            10960.0,
            10851,
            0.9901,
            True,
        ),
        (
            "BRILLARE 100% Pure Cold Pressed Almond Oil | Organic Oil\n₹595 · SuperCoins ₹590 (99.16%)",
            595.0,
            590,
            0.9916,
            True,
        ),
        (
            "Titan Workwear Workwear Pink Round Dial Women's Watch\nPrice: ₹8,443\nSuperCoins back: ₹6,687 (79.2%)\nSeller: RetailNet",
            8443.0,
            6687,
            0.792,
            True,
        ),
        (
            "EXTRI X6066-C Analog Watch - For Men\nPrice: ₹8,299 → ₹1,869\nSuperCoins back: ₹1,851 (99.04%)\nSeller: HSAtlastradeFashion",
            1869.0,
            1851,
            0.9904,
            True,
        ),
        (
            "DA RAKE Classio Vibes Perfume for 12 Hours Long Lasting\nPrice: ₹986\nSuperCoins back: ₹740 (75.05%)\nSeller: DARAKELUXEZ",
            986.0,
            740,
            0.7505,
            True,
        ),
        (
            "DA RAKE Ascot Oud Perfume for 12 Hours Long Lasting\nPrice: ₹976\nSuperCoins back: ₹732 (75%)\nSeller: DARAKELUXEZ",
            976.0,
            732,
            0.75,
            True,
        ),
        (
            "French Connection Silver Round Dial | FCW12TM Analog Watch\nPrice: ₹1,469\nSuperCoins back: ₹1,455 (99.05%)\nSeller: RetailNet",
            1469.0,
            1455,
            0.9905,
            True,
        ),
        (
            "SLAZENGER SLAZENGER Analog Watch - For Women\nPrice: ₹1,519\nSuperCoins back: ₹1,504 (99.01%)\nSeller: RetailNet",
            1519.0,
            1504,
            0.9901,
            True,
        ),
        (
            "🔥 100% Supercoins offer on Brillare Products\n16 in stock",
            1495.0,
            1495,
            1.0,
            True,
        ),
    ]

    for text, price, exp_coins, exp_ratio, exp_is_deal in samples:
        coins, ratio, is_deal = scraper._extract_supercoins_from_text(text, price)
        assert coins == exp_coins, f"Coins mismatch for '{text[:40]}': got {coins}, expected {exp_coins}"
        assert ratio == exp_ratio, f"Ratio mismatch for '{text[:40]}': got {ratio}, expected {exp_ratio}"
        assert is_deal == exp_is_deal, f"Deal status mismatch for '{text[:40]}'"


def test_flipkart_category_surveillance_rules_integrity():
    """11. Verify SUPERCOIN_CATEGORY_RULES catalog structure, categories, and platform targets."""
    from radar_rules import SUPERCOIN_CATEGORY_RULES

    assert len(SUPERCOIN_CATEGORY_RULES) >= 5
    categories = {r.category for r in SUPERCOIN_CATEGORY_RULES}
    assert "Watches" in categories
    assert "Beauty & Personal Care" in categories
    assert "Fragrances & Perfumes" in categories
    assert "SuperCoins & Clearance" in categories

    for rule in SUPERCOIN_CATEGORY_RULES:
        assert "flipkart" in rule.platforms
        assert rule.min_discount >= 70.0
        assert rule.is_active is True
        assert len(rule.negative_keywords) > 0


@pytest.mark.asyncio
async def test_radar_multi_brand_watch_validation():
    """12. Verify StealRadar handles multi-brand category rules and verifies Hilfiger, Titan, etc."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from config import Settings
    from database import Database
    from notifier import Notifier
    from radar import StealRadar
    from radar_rules import SUPERCOIN_CATEGORY_RULES

    mock_db = MagicMock(spec=Database)
    mock_db.initialize = AsyncMock()
    mock_db.close = AsyncMock()
    mock_db.is_deal_recently_notified = AsyncMock(return_value=False)
    mock_db.log_deal_alert = AsyncMock()

    mock_notifier = MagicMock(spec=Notifier)
    mock_notifier.send_message = AsyncMock(return_value=True)

    radar = StealRadar(Settings(), db=mock_db, notifier=mock_notifier)

    watch_rule = next(r for r in SUPERCOIN_CATEGORY_RULES if r.name == "Flipkart Watches 70%+ SuperCoin & Steal Deals")

    mock_deals = [
        {
            "title": "Hilfiger NCTH1791382 Denim Analog Watch - For Men",
            "price": 10960.0,
            "mrp": 10960.0,
            "discount_percent": 0.0,
            "url": "https://www.flipkart.com/hilfiger-watch/p/itm111",
            "scraped_brand": "Tommy Hilfiger",
            "platform": "flipkart",
            "supercoins_earned": 10851,
            "supercoin_ratio": 0.9901,
            "is_supercoin_deal": True,
        },
        {
            "title": "Titan Workwear Pink Round Dial Women's Watch",
            "price": 8443.0,
            "mrp": 8443.0,
            "discount_percent": 0.0,
            "url": "https://www.flipkart.com/titan-watch/p/itm222",
            "scraped_brand": "Titan",
            "platform": "flipkart",
            "supercoins_earned": 6687,
            "supercoin_ratio": 0.792,
            "is_supercoin_deal": True,
        },
        # Rejected accessory
        {
            "title": "Titan Leather Replacement Watch Strap",
            "price": 999.0,
            "mrp": 1999.0,
            "discount_percent": 50.0,
            "url": "https://www.flipkart.com/titan-strap/p/itm333",
            "scraped_brand": "Titan",
            "platform": "flipkart",
            "is_supercoin_deal": False,
        },
        # Rejected unknown/unapproved brand
        {
            "title": "RandomBrand Cheap Analog Watch",
            "price": 899.0,
            "mrp": 2999.0,
            "discount_percent": 70.0,
            "url": "https://www.flipkart.com/random-watch/p/itm444",
            "scraped_brand": "RandomBrand",
            "platform": "flipkart",
            "is_supercoin_deal": False,
        },
    ]

    mock_fk_scraper = MagicMock()
    mock_fk_scraper.scan_deals = AsyncMock(return_value=mock_deals)

    with patch("radar.get_scraper", return_value=mock_fk_scraper):
        deals = await radar.scan_rule(watch_rule)
        assert len(deals) == 2
        titles = [d["title"] for d in deals]
        assert "Hilfiger NCTH1791382 Denim Analog Watch - For Men" in titles
        assert "Titan Workwear Pink Round Dial Women's Watch" in titles


@pytest.mark.asyncio
async def test_flipkart_scraper_scan_deals_with_brands_and_supercoins(scraper):
    """13. Test FlipkartScraper.scan_deals parses card SuperCoins and matches multi-brands."""
    card_html = """
    <div data-id="WATHILFIGER123" class="_1AtVbE">
        <a href="/hilfiger-analog-watch/p/itm123?pid=WATH123">
            <span class="syl9yP">Tommy Hilfiger</span>
            <div class="KzDlHZ">Hilfiger NCTH1791382 Denim Analog Watch - For Men</div>
        </a>
        <div class="Nx9bqj">₹10,960</div>
        <div class="yRaY8j">₹10,960</div>
        <div class="offer-callout">SuperCoins back: ₹10,851 (99.01%)</div>
    </div>
    <div data-id="BRILLARE999" class="_1AtVbE">
        <a href="/brillare-almond-oil/p/itm999?pid=BROIL123">
            <span class="syl9yP">Brillare</span>
            <div class="KzDlHZ">BRILLARE 100% Pure Cold Pressed Almond Oil 100ml</div>
        </a>
        <div class="Nx9bqj">₹595</div>
        <div class="yRaY8j">₹595</div>
        <div class="offer-callout">SuperCoins ₹590 (99.16%)</div>
    </div>
    """
    with patch.object(scraper, "_static_fetch", AsyncMock(return_value=card_html)):
        deals = await scraper.scan_deals(
            query="watches",
            min_discount=70.0,
            brands=["Tommy Hilfiger", "Brillare"],
        )
        assert len(deals) == 2
        hilfiger_deal = next(d for d in deals if "Hilfiger" in d["title"])
        assert hilfiger_deal["price"] == 10960.0
        assert hilfiger_deal["supercoins_earned"] == 10851
        assert hilfiger_deal["supercoin_ratio"] == 0.9901
        assert hilfiger_deal["is_supercoin_deal"] is True

        brillare_deal = next(d for d in deals if "Brillare" in d["title"])
        assert brillare_deal["price"] == 595.0
        assert brillare_deal["supercoins_earned"] == 590
        assert brillare_deal["supercoin_ratio"] == 0.9916
        assert brillare_deal["is_supercoin_deal"] is True


@pytest.mark.asyncio
async def test_supabase_log_deal_alert_supercoin_fields():
    """14. Verify SupabaseDatabase.log_deal_alert accepts supercoin arguments."""
    from supabase_db import SupabaseDatabase
    from unittest.mock import AsyncMock, patch

    sdb = SupabaseDatabase("https://fake.supabase.co", "fake-key")
    with patch.object(sdb, "_request", AsyncMock()) as mock_req:
        await sdb.log_deal_alert(
            product_url="https://www.flipkart.com/item/p/itm123",
            title="Hilfiger Watch",
            price=10960.0,
            effective_price=10960.0,
            discount_percent=0.0,
            coupon_text="🪙 99% SuperCoins Back",
            platform="flipkart",
            supercoins_earned=10851,
            supercoin_ratio=0.9901,
        )
        mock_req.assert_called_once()
        call_args = mock_req.call_args
        assert call_args[0][0] == "POST"
        assert call_args[0][1] == "/deal_alerts_log"
        payload = call_args[1]["json"]
        assert payload["supercoins_earned"] == 10851
        assert payload["supercoin_ratio"] == 0.9901


def test_supercoin_preceding_preposition_and_bank_offer(scraper):
    """15. Ensure 'with' in product titles and 'Save ₹X with Bank offer' do not falsely block SuperCoin detection."""
    # Sibling divs without periods
    div_html = (
        "<html><body>"
        "<div class='Nx9bqj'>₹10,960</div>"
        "<div>Pay using 50 SuperCoins</div>"
        "<div>SuperCoins back: ₹10,851 (99.01%)</div>"
        "</body></html>"
    )
    res_div = scraper.parse(div_html, "https://www.flipkart.com/hilfiger/p/itm123")
    assert res_div.supercoins_earned == 10851
    assert res_div.supercoin_ratio == 0.9901
    assert res_div.is_supercoin_deal is True

    # Bank offer with "Save" and "with"
    bank_text = "₹10,960 Save ₹50 with Bank Offer SuperCoins back: ₹10,851 (99.01%)"
    coins, ratio, is_deal = scraper._extract_supercoins_from_text(bank_text, 10960.0)
    assert coins == 10851
    assert ratio == 0.9901
    assert is_deal is True

    # Title with "with" (e.g. Titan Workwear Pink Dial Watch)
    title_text = "Titan Workwear Analog Watch with Pink Dial SuperCoins back: ₹6,687 (79.2%)"
    coins2, ratio2, is_deal2 = scraper._extract_supercoins_from_text(title_text, 8443.0)
    assert coins2 == 6687
    assert ratio2 == 0.792
    assert is_deal2 is True


@pytest.mark.asyncio
async def test_scan_deals_multi_brand_url_facets(scraper):
    """16. Verify scan_deals appends multiple brand facets and respects apply_discount_facet=False."""
    captured_urls = []

    async def mock_fetch(url):
        captured_urls.append(url)
        return ""

    with patch.object(scraper, "_static_fetch", side_effect=mock_fetch):
        # Multi-brand SuperCoin sweep (no cash discount facet)
        await scraper.scan_deals(
            query="watches",
            brands=["Tommy Hilfiger", "Titan"],
            min_discount=70.0,
            apply_discount_facet=False,
        )
        assert len(captured_urls) == 1
        url1 = captured_urls[0]
        assert "facets.discount_range_v1" not in url1
        assert "facets.brand%255B%255D%3DTOMMY+HILFIGER" in url1
        assert "facets.brand%255B%255D%3DTITAN" in url1

        # Standard cash discount sweep (applies discount facet)
        await scraper.scan_deals(
            query="casio",
            brand="Casio",
            min_discount=70.0,
            apply_discount_facet=True,
        )
        assert len(captured_urls) == 2
        url2 = captured_urls[1]
        assert "facets.discount_range_v1%255B%255D%3D70%2525%2Bor%2Bmore" in url2
        assert "facets.brand%255B%255D%3DCASIO" in url2


def test_brand_validator_hilfiger_alias_and_title():
    """17. Verify BrandValidator validates 'Hilfiger' scraped brand and title against 'Tommy Hilfiger' target."""
    from brand_validator import BrandValidator, BrandStatus

    bv = BrandValidator()
    # Hilfiger scraped brand against Tommy Hilfiger target
    res1 = bv.validate(
        scraped_brand="Hilfiger",
        title="Hilfiger NCTH1791382 Denim Analog Watch - For Men",
        target_brands=["Tommy Hilfiger", "Titan"],
    )
    assert res1.brand_status == BrandStatus.VERIFIED
    assert res1.confidence_score >= 100

    # Scraped brand Tommy Hilfiger with title starting with Hilfiger
    res2 = bv.validate(
        scraped_brand="Tommy Hilfiger",
        title="Hilfiger NCTH1791382 Denim Analog Watch - For Men",
        target_brands=["Tommy Hilfiger", "Titan"],
    )
    assert res2.brand_status == BrandStatus.VERIFIED
    assert res2.confidence_score >= 100


def test_supercoin_category_rules_have_discount_facet_disabled():
    """18. Verify SUPERCOIN_CATEGORY_RULES have apply_discount_facet disabled so full-price loot isn't dropped."""
    from radar_rules import SUPERCOIN_CATEGORY_RULES

    for r in SUPERCOIN_CATEGORY_RULES:
        assert r.apply_discount_facet is False, f"Rule '{r.name}' should have apply_discount_facet=False"


