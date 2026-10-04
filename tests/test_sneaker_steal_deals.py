import pytest
from unittest.mock import AsyncMock, patch
from running_shoes_catalog_data import SNEAKER_MODEL_NAMES, STEAL_THRESHOLDS
from running_shoes_radar import RunningShoeDeal, RunningShoesRadar, parse_uk_size, SNEAKER_SIZES, match_running_model


def test_sneaker_model_matching():
    """Verify iconic sneakers match their canonical model names and are identified as sneakers."""
    samples = [
        ("ADIDAS ORIGINALS SL 72 RS Sneakers For Men", "Adidas", "SL 72"),
        ("adidas Originals Samba OG Shoes", "Adidas", "Samba"),
        ("Puma Unisex Palermo Leather Sneakers", "Puma", "Palermo"),
        ("Nike P-6000 Metallic Silver Running Shoes / Sneakers", "Nike", "P-6000"),
        ("ASICS GEL-1130 White Pure Silver", "Asics", "Gel-1130"),
        ("New Balance Unisex 550 White Green Sneakers", "New Balance", "New Balance 550"),
        ("Nike Dunk Low Retro White Black Panda", "Nike", "Dunk Low"),
    ]
    for title, expected_brand, expected_model in samples:
        matched = match_running_model(title)
        assert matched is not None, f"Failed to match {title}"
        brand, model = matched
        assert brand == expected_brand
        assert model == expected_model
        assert model in SNEAKER_MODEL_NAMES, f"{model} should be in SNEAKER_MODEL_NAMES"


def test_sneaker_size_parsing():
    """Verify adult sizes (UK 6 - 12) parse for sneakers while default running filter rejects small sizes."""
    assert parse_uk_size("Size: 7", target_sizes=SNEAKER_SIZES) == 7.0
    assert parse_uk_size("UK 8.5", target_sizes=SNEAKER_SIZES) == 8.5
    assert parse_uk_size("Green , 11", target_sizes=SNEAKER_SIZES) == 11.0
    assert parse_uk_size("UK 6", target_sizes=SNEAKER_SIZES) == 6.0
    
    # Running shoes default restricts to 9.5 - 11.0
    assert parse_uk_size("UK 6") is None
    assert parse_uk_size("UK 10") == 10.0


def test_stacked_deal_effective_price_classification():
    """Verify SL 72 RS with stacked coupon and bank discount triggers ATL/Steal Deal at ₹2,752."""
    radar = RunningShoesRadar()
    
    # SL 72 RS: MRP 9999, Street 6999, Steal 3500, ATL 2752
    deal = RunningShoeDeal(
        id="flipkart_sl72_sample",
        title="ADIDAS ORIGINALS SL 72 RS Sneakers For Men",
        brand="Adidas",
        model="SL 72",
        category="sneaker",
        price=4499.0,  # Listing price
        mrp=9999.0,
        discount_percent=55.0,
        available_sizes=["UK 10"],
        platform="flipkart",
        url="https://www.flipkart.com/adidas-originals-sl-72-rs-sneakers-men/p/itm4eba3f4d8c95e",
        image_url="https://rukmini1.flixcart.com/image/600/720/sample.jpeg",
        detected_at="2026-10-05T00:00:00Z",
        listing_price=4499.0,
        coupon_discount=675.0,
        coupon_code="EXTRA15",
        bank_discount=1072.0,
        bank_name="Axis Bank Credit Card",
        net_effective_price=2752.0,
    )
    
    effective_p = deal.net_effective_price or deal.price
    assert effective_p == 2752.0
    
    thresholds = STEAL_THRESHOLDS["SL 72"]
    assert effective_p <= thresholds["steal"]
    assert effective_p <= thresholds["atl"]


@pytest.mark.asyncio
async def test_telegram_alert_formatting_for_sneakers():
    """Verify telegram alert includes sneaker styling and the stacked multi-tier breakdown."""
    radar = RunningShoesRadar()
    mock_notifier = AsyncMock()
    radar.notifier = mock_notifier
    
    deal = RunningShoeDeal(
        id="flipkart_sl72_deal",
        title="ADIDAS ORIGINALS SL 72 RS Sneakers For Men",
        brand="Adidas",
        model="SL 72",
        category="sneaker",
        price=4499.0,
        mrp=9999.0,
        discount_percent=55.0,
        available_sizes=["UK 10", "UK 11"],
        platform="flipkart",
        url="https://www.flipkart.com/test-sl72",
        image_url="https://rukmini1.flixcart.com/image/600/720/test.jpeg",
        detected_at="2026-10-05T00:00:00Z",
        deal_type="all_time_low",
        lowest_price_seen=2752.0,
        listing_price=4499.0,
        coupon_discount=675.0,
        coupon_code="EXTRA15",
        bank_discount=1072.0,
        bank_name="Axis Bank",
        net_effective_price=2752.0,
    )
    
    await radar._dispatch_telegram_alert(deal)
    assert mock_notifier.send_telegram.called
    msg = mock_notifier.send_telegram.call_args[0][0]
    
    assert "SNEAKER" in msg
    assert "Adidas SL 72" in msg
    assert "Listing: ₹4,499" in msg
    assert "Coupon (EXTRA15): -₹675" in msg
    assert "Bank Offer (Axis Bank): -₹1,072" in msg
    assert "Net Steal Price:* ₹2,752" in msg
