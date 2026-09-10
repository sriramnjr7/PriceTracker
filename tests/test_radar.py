"""Unit tests for the autonomous Steal Radar engine (radar.py & radar_rules.py)."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from brand_validator import BrandStatus, BrandValidationResult
from config import Settings
from database import Database
from gemini_validator import DealValidationResult, GeminiDealValidator
from notifier import Notifier
from radar import StealRadar
from radar_rules import DEFAULT_RADAR_RULES, RadarRule


@pytest.fixture
def mock_db():
    db = MagicMock(spec=Database)
    db.initialize = AsyncMock()
    db.close = AsyncMock()
    db.get_custom_rules = AsyncMock(return_value=[])
    db.is_deal_recently_notified = AsyncMock(return_value=False)
    db.log_deal_alert = AsyncMock()
    return db


@pytest.fixture
def mock_notifier():
    notifier = MagicMock(spec=Notifier)
    notifier.send_message = AsyncMock(return_value=True)
    notifier.send_whatsapp = AsyncMock(return_value=True)
    notifier.send_telegram = AsyncMock(return_value=True)
    return notifier


def test_default_radar_rules_integrity():
    """Verify pre-configured radar rules have valid structure and required fields."""
    assert len(DEFAULT_RADAR_RULES) >= 10
    for rule in DEFAULT_RADAR_RULES:
        assert rule.name
        assert rule.category
        assert rule.query
        assert len(rule.platforms) > 0
        assert rule.min_discount >= 0.0


@pytest.mark.asyncio
async def test_scan_rule_filtering(mock_db, mock_notifier):
    """Test scan_rule applies brand validator, negative keywords, and price floor filters."""
    radar = StealRadar(Settings(), db=mock_db, notifier=mock_notifier)
    radar.ai_validator = MagicMock(spec=GeminiDealValidator)

    rule = RadarRule(
        name="Casio Watch Test",
        category="Watches",
        query="casio g-shock watch",
        brand="Casio",
        platforms=["amazon"],
        min_discount=50.0,
        min_price=2000.0,  # Floor: rejects < 2000
        negative_keywords=["strap", "cover", "case"],
        required_keywords=["casio", "g-shock"],
    )

    mock_scraper = MagicMock()
    mock_scraper.scan_deals = AsyncMock(return_value=[
        # Valid deal
        {
            "title": "Casio G-Shock GA-2100 Carbon Core Guard Watch",
            "price": 3995.0,
            "mrp": 9995.0,
            "discount_percent": 60.0,
            "url": "https://amazon.in/dp/B001",
            "scraped_brand": "Casio",
            "platform": "amazon",
        },
        # Rejected by price floor (price 499 < 2000)
        {
            "title": "Casio Resin Replacement Watch Band",
            "price": 499.0,
            "mrp": 1999.0,
            "discount_percent": 75.0,
            "url": "https://amazon.in/dp/B002",
            "scraped_brand": "Casio",
            "platform": "amazon",
        },
        # Rejected by negative keywords ("strap")
        {
            "title": "Casio G-Shock Heavy Duty Strap for Men",
            "price": 2500.0,
            "mrp": 5000.0,
            "discount_percent": 50.0,
            "url": "https://amazon.in/dp/B003",
            "scraped_brand": "Casio",
            "platform": "amazon",
        },
        # Rejected by brand validator (brand is Siwi / different brand)
        {
            "title": "Siwi Digital Watch for Casio G-Shock lovers",
            "price": 2499.0,
            "mrp": 6999.0,
            "discount_percent": 64.0,
            "url": "https://amazon.in/dp/B004",
            "scraped_brand": "Siwi",
            "platform": "amazon",
        },
    ])

    with patch("radar.get_scraper", return_value=mock_scraper):
        deals = await radar.scan_rule(rule)
        assert len(deals) == 1
        assert deals[0]["title"] == "Casio G-Shock GA-2100 Carbon Core Guard Watch"
        assert deals[0]["brand_validation"]["status"] == BrandStatus.VERIFIED.value


@pytest.mark.asyncio
async def test_process_and_notify_deals(mock_db, mock_notifier):
    """Test deal processing, AI validation, and dispatch to notifier."""
    test_settings = Settings(
        telegram_bot_token="test_token",
        telegram_chat_id="12345",
    )
    radar = StealRadar(test_settings, db=mock_db, notifier=mock_notifier)
    radar.ai_validator.validate_deal = AsyncMock(return_value=DealValidationResult(
        is_genuine_steal=True,
        is_genuine_brand=True,
        is_accessory_or_knockoff=False,
        confidence_score=10,
        reason="Genuine Casio G-Shock deal.",
        model_used="Cloudflare DeepSeek R1",
    ))

    rule = RadarRule(
        name="Casio Watch Test",
        category="Watches",
        query="casio g-shock watch",
        brand="Casio",
        platforms=["casio"],
        min_discount=50.0,
    )

    valid_deal = {
        "title": "Casio G-Shock GBD-300-9DR Watch",
        "price": 3995.0,
        "effective_price": 3995.0,
        "mrp": 9995.0,
        "discount_percent": 60.0,
        "url": "https://casiostore.bhawar.com/products/gbd-300",
        "scraped_brand": "Casio",
        "platform": "casio",
        "coupon_text": None,
    }

    with patch.object(radar, "scan_rule", return_value=[valid_deal]):
        alerts_count = await radar.process_and_notify_deals(rule)
        assert alerts_count == 1
        mock_notifier.send_message.assert_called_once()
        mock_db.log_deal_alert.assert_called_once()


def test_casio_rules_platforms_and_discount_integrity():
    """Verify Casio rules target only Casio Bhawar & Flipkart with >= 50% discount, and unrequested rules are inactive."""
    active_rules = [r for r in DEFAULT_RADAR_RULES if r.is_active]
    assert len(active_rules) == 3  # Casio 70%+, Casio GBD-300, and G-Shock & Edifice 50%+
    
    for rule in active_rules:
        assert set(rule.platforms) == {"casio", "flipkart"}
        assert rule.min_discount >= 50.0
        assert rule.brand == "Casio"
    
    # Check that other rules are deactivated
    inactive_rules = [r for r in DEFAULT_RADAR_RULES if not r.is_active]
    assert len(inactive_rules) >= 8
    inactive_categories = {r.category for r in inactive_rules}
    assert "Fitness & Nutrition" in inactive_categories
    assert "Tech & Storage" in inactive_categories

