"""Unit tests for Cloudflare & Gemini Dual AI Deal Arbiter & Natural Language Intent Parser."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from config import Settings
from gemini_validator import DealValidationResult, GeminiDealValidator


@pytest.fixture
def validator():
    test_settings = Settings(
        gemini_api_key="",
        telegram_bot_token="",
        telegram_chat_id="",
    )
    val = GeminiDealValidator(test_settings)
    val.cf_token = ""
    val.gemini_client = None
    return val


@pytest.mark.asyncio
async def test_rule_gatekeeper_accessory_phrases(validator):
    """Obvious accessory/compatibility phrases should be rejected immediately without calling AI."""
    res1 = await validator.validate_deal(
        title="Silicone Resin Strap for G-Shock Watch",
        category="Watches",
        selling_price=499.0,
        mrp=1999.0,
        discount_percent=75.0,
        platform="amazon",
    )
    assert res1.is_genuine_steal is False
    assert res1.is_accessory_or_knockoff is True
    assert "Accessory/compatibility phrasing" in res1.reason
    assert res1.model_used == "Rule Gatekeeper"

    res2 = await validator.validate_deal(
        title="Spigen Armor Case for iPhone 15 Pro",
        category="Smartphones",
        selling_price=999.0,
        mrp=2999.0,
        discount_percent=66.0,
        platform="amazon",
    )
    assert res2.is_genuine_steal is False
    assert res2.is_accessory_or_knockoff is True


@pytest.mark.asyncio
async def test_rule_gatekeeper_knockoff_brands(validator):
    """Known knockoff brands (e.g. Poppex, Sounce, V2A) should be rejected immediately."""
    res = await validator.validate_deal(
        title="Poppex Sport Analog Digital Watch for Men",
        category="Watches",
        selling_price=399.0,
        mrp=2999.0,
        discount_percent=86.0,
        platform="flipkart",
    )
    assert res.is_genuine_steal is False
    assert res.is_accessory_or_knockoff is True
    assert "Third-party/knockoff brand" in res.reason


@pytest.mark.asyncio
async def test_heuristic_fallback_when_no_ai_keys(validator):
    """When no API tokens are configured, legitimate hardware passes heuristic gatekeeper."""
    res = await validator.validate_deal(
        title="Apple iPhone 15 128GB Black",
        category="Smartphones",
        selling_price=48999.0,
        mrp=79900.0,
        discount_percent=38.7,
        platform="amazon",
        scraped_brand="Apple",
    )
    assert res.is_genuine_steal is True
    assert res.is_genuine_brand is True
    assert res.is_accessory_or_knockoff is False
    assert res.model_used == "Heuristic Brand Gatekeeper"


@pytest.mark.asyncio
async def test_cloudflare_ai_evaluation():
    """Mock Cloudflare Workers AI DeepSeek-R1 response parsing with <think> striping."""
    test_settings = Settings()
    val = GeminiDealValidator(test_settings)
    val.cf_token = "fake-token"
    val.cf_account_id = "fake-acc"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{
            "message": {
                "content": "<think>This is a real Casio watch and huge discount.</think>{\"is_genuine_steal\": true, \"is_genuine_brand\": true, \"is_accessory_or_knockoff\": false, \"confidence_score\": 10, \"reason\": \"Genuine Casio G-Shock timepiece at massive clearance discount.\"}"
            }
        }]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        res = await val.validate_deal(
            title="Casio G-Shock GA-2100-1A1DR Carbon Core Guard Watch",
            category="Watches",
            selling_price=3995.0,
            mrp=9995.0,
            discount_percent=60.0,
            platform="amazon",
            scraped_brand="Casio",
        )
        assert res.is_genuine_steal is True
        assert res.is_genuine_brand is True
        assert res.model_used == "Cloudflare DeepSeek R1"
        assert "Genuine Casio G-Shock" in res.reason


@pytest.mark.asyncio
async def test_gemini_fallback_evaluation():
    """Mock Gemini SDK generate_content fallback."""
    test_settings = Settings(gemini_api_key="fake-gemini-key")
    val = GeminiDealValidator(test_settings)
    val.cf_token = ""  # Cloudflare disabled
    val.gemini_client = MagicMock()

    mock_response = MagicMock()
    mock_response.text = '{"is_genuine_steal": true, "is_genuine_brand": true, "is_accessory_or_knockoff": false, "confidence_score": 9, "reason": "Verified genuine Apple product."}'
    val.gemini_client.models.generate_content.return_value = mock_response

    res = await val.validate_deal(
        title="Apple AirPods Pro (2nd Gen)",
        category="Audio",
        selling_price=12999.0,
        mrp=24900.0,
        discount_percent=48.0,
        platform="flipkart",
        scraped_brand="Apple",
    )
    assert res.is_genuine_steal is True
    assert res.model_used == "Google Gemini 3.5 Flash"


@pytest.mark.asyncio
async def test_parse_tracking_intent_regex_fallback(validator):
    """Verify fallback natural language regex parsing when no AI API is available."""
    # Test '50k' target price
    parsed1 = await validator.parse_tracking_intent("track if iphone 15 comes under 50k")
    assert parsed1["target_price"] == 50000.0
    assert "iphone" in parsed1["query"].lower()

    # Test numeric target price
    parsed2 = await validator.parse_tracking_intent("alert me if sony xm5 drops below 20000")
    assert parsed2["target_price"] == 20000.0

    # Test query without price
    parsed3 = await validator.parse_tracking_intent("track crocs classic clogs")
    assert parsed3["target_price"] is None
    assert "crocs classic clogs" in parsed3["query"].lower()
