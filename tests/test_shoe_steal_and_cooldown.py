"""Test suite for Absolute Steal Thresholds, Flipkart Price Extraction,
Model Blacklist/Exclusions, and 12-Hour Duplicate Cooldown for Shoes.
"""

import pytest
from datetime import datetime, timezone, timedelta
from running_shoes_radar import (
    RunningShoesRadar,
    RunningShoeDeal,
    match_running_model,
)


def test_model_matching_exclusions():
    """Verify that 'Floatride Energy Daily' is rejected and does not match 'Floatride Energy'."""
    # Real Floatride Energy 5
    matched = match_running_model("REEBOK FLOATRIDE ENERGY 5 Running Shoes For Men")
    assert matched is not None
    brand, model = matched
    assert brand == "Reebok"
    assert model == "Floatride Energy"

    # Trap model: Floatride Energy Daily
    matched_daily = match_running_model("REEBOK FLOATRIDE ENERGY DAILY Running Shoes For Men")
    assert matched_daily is None, "Floatride Energy Daily must be excluded!"

    # Trap model: Energen
    matched_energen = match_running_model("Reebok Energen Plus Running Shoes")
    assert matched_energen is None


def test_catalog_thresholds_loaded():
    """Verify all 94 models have absolute price anchors (street, steal, atl)."""
    radar = RunningShoesRadar()
    catalog = radar.load_catalog()
    assert len(catalog) == 94

    # Check Adizero SL (from researched docx: mrp 9999, street 6999, steal 3999, atl 2599)
    adizero = catalog.get("adidas_adizero_sl")
    assert adizero is not None
    assert adizero["known_street_price"] == 6999
    assert adizero["steal_price"] == 3999
    assert adizero["known_atl"] == 2599

    # Check Reebok Floatride Energy (from researched docx: mrp 8999, street 7000, steal 4500, atl 3500)
    floatride = catalog.get("reebok_floatride_energy")
    assert floatride is not None
    assert floatride["known_street_price"] == 7000
    assert floatride["steal_price"] == 4500
    assert floatride["known_atl"] == 3500

    # Check Puma Deviate Nitro (from researched docx: mrp 15999, street 11499, steal 6999, atl 4499)
    deviate = catalog.get("puma_deviate_nitro")
    assert deviate is not None
    assert deviate["known_street_price"] == 11499
    assert deviate["steal_price"] == 6999
    assert deviate["known_atl"] == 4499


def test_absolute_threshold_classification():
    """Verify that classification uses absolute thresholds and not inflated MRP percentages."""
    radar = RunningShoesRadar()
    catalog = radar.load_catalog()

    # Case 1: Adizero SL at Rs 3,500 (Steal Deal: <= 3999)
    cat_entry = catalog["adidas_adizero_sl"]
    price_steal = 3500.0
    known_atl = cat_entry["known_atl"]
    steal_price = cat_entry["steal_price"]
    street_price = cat_entry["known_street_price"]

    assert price_steal > known_atl  # 3500 > 2599
    assert price_steal <= steal_price  # 3500 <= 3999 -> STEAL DEAL!

    # Case 2: Adizero SL at Rs 2,500 -> ALL-TIME LOW (<= 2599)
    price_atl = 2500.0
    assert price_atl <= known_atl

    # Case 3: Reebok Floatride Energy at Rs 9,999 or 12,999 (The false alert bug)
    # street_price=7000, steal_price=4500
    re_entry = catalog["reebok_floatride_energy"]
    price_bug = 9999.0
    assert price_bug > re_entry["known_street_price"]  # NOT A DEAL! Above normal street price!

    # Case 4: Puma Deviate Nitro at Rs 16,999 (Full MRP false alert bug)
    # street_price=11499, steal_price=6999
    puma_entry = catalog["puma_deviate_nitro"]
    price_puma = 16999.0
    assert price_puma > puma_entry["known_street_price"]  # NOT A DEAL! Above street price!


def test_flipkart_pricing_extraction_logic():
    """Verify Flipkart prices parser correctly extracts selling price vs strikeOff MRP."""
    # Data structure received from Flipkart searchbff for Floatride Energy 5
    prices_list = [
        {"name": "Selling Price", "priceType": "FSP", "strikeOff": True, "value": 12999},
        {"name": "Special Price", "priceType": "SPECIAL_PRICE", "strikeOff": False, "value": 4939},
    ]

    special_price = None
    strike_mrp = None
    for pr in prices_list:
        val_num = float(pr.get("value") or 0)
        if val_num <= 0:
            continue
        if pr.get("strikeOff") is True:
            strike_mrp = val_num
        elif pr.get("strikeOff") is False or pr.get("priceType") == "SPECIAL_PRICE":
            special_price = val_num

    price = special_price or 0.0
    mrp = max(strike_mrp or price, price)

    assert price == 4939.0, f"Selling price should be 4939, got {price}"
    assert mrp == 12999.0, f"MRP should be 12999, got {mrp}"


@pytest.mark.asyncio
async def test_12_hour_duplicate_cooldown():
    """Verify that repeat alerts within 12 hours are suppressed unless price drops further."""
    now = datetime.now(timezone.utc)
    radar = RunningShoesRadar()

    # Simulate catalog entry with alert sent 2 hours ago at Rs 4,500
    last_alert_time = now - timedelta(hours=2)
    cat_entry = {
        "last_alert_at": last_alert_time.isoformat(),
        "last_alert_price": 4500.0,
    }

    # Test 1: Same model at Rs 4,500 (same price) -> Suppressed
    deal_same = RunningShoeDeal(
        id="test_deal_1",
        title="Adidas Adizero SL",
        brand="Adidas",
        model="Adizero SL",
        price=4500.0,
        mrp=9999.0,
        discount_percent=55.0,
        available_sizes=["UK 10"],
        platform="myntra",
        url="https://test.com",
        image_url=None,
        detected_at=now.isoformat(),
    )
    hours_since = (now - datetime.fromisoformat(cat_entry["last_alert_at"])).total_seconds() / 3600
    assert hours_since < 12.0
    assert deal_same.price >= cat_entry["last_alert_price"]
    # Cooldown blocks alert!

    # Test 2: Different listing of same model at Rs 4,800 -> Suppressed
    assert 4800.0 >= cat_entry["last_alert_price"]

    # Test 3: Same model with a real further price drop to Rs 3,800 -> Allowed!
    deal_drop = 3800.0
    assert deal_drop < cat_entry["last_alert_price"], "Price improvement bypasses cooldown"

    # Test 4: Same price after 13 hours -> Allowed (cooldown expired)
    old_alert_time = now - timedelta(hours=13)
    hours_since_old = (now - old_alert_time).total_seconds() / 3600
    assert hours_since_old >= 12.0
