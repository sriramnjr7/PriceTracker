import pytest
from bs4 import BeautifulSoup
from config import settings
from scrapers.casio import CasioScraper
from database import Database, get_database
from radar import StealRadar
from radar_rules import RadarRule


@pytest.mark.asyncio
async def test_qa_casio_bhawar_discount_selectors():
    """QA Test 1: Verify extraction of authenticated member 70% silent sale price."""
    scraper = CasioScraper(settings)
    
    # HTML mock simulating Bhawar's exact DOM when logged in for GW-5000HS-7
    mock_html = """
    <div class="product__info-container">
        <h1 class="product__title">GW-5000HS-7</h1>
        <div class="price sw-card-price font-regular price--on-sale price--silent-off">
            <div class="price__container">
                <div class="price__regular">
                    <span class="price-item price-item--regular">MRP ₹ 24,495</span>
                </div>
                <div class="price__sale">
                    <span class="price-item price-item--sale price-item--last">₹ 7,349</span>
                </div>
            </div>
        </div>
        <button type="submit" name="add" class="product-form__submit button">
            <span>Add to cart</span>
        </button>
    </div>
    """
    soup = BeautifulSoup(mock_html, "html.parser")
    price = scraper._extract_price(soup)
    assert price == 7349.0, f"Expected 7349.0 but got {price}"
    
    # Stock check: Add to cart is enabled
    in_stock = scraper._extract_stock(soup)
    assert in_stock is True, "Expected in_stock to be True"
    
    # Calculate discount vs MRP
    reg_el = soup.select_one(".price-item--regular")
    mrp = scraper.clean_price(reg_el.get_text())
    assert mrp == 24495.0
    discount = round((mrp - price) / mrp * 100.0, 1)
    assert discount == 70.0, f"Expected 70.0% but got {discount}%"


@pytest.mark.asyncio
async def test_qa_casio_bhawar_gbd_h2000_discount_selectors():
    """QA Test 2: Verify extraction of GBD-H2000-1A9 silent sale DOM."""
    scraper = CasioScraper(settings)
    mock_html = """
    <div class="product__info-container">
        <h1 class="product__title">GBD-H2000-1A9</h1>
        <div class="price sw-card-price font-regular price--on-sale price--silent-off">
            <span class="price-item price-item--regular">MRP ₹ 44,995</span>
            <span class="price-item price-item--sale price-item--last">₹ 13,499</span>
        </div>
        <button type="submit" name="add" class="product-form__submit button">
            <span>Add to cart</span>
        </button>
    </div>
    """
    soup = BeautifulSoup(mock_html, "html.parser")
    price = scraper._extract_price(soup)
    assert price == 13499.0
    
    reg_el = soup.select_one(".price-item--regular")
    mrp = scraper.clean_price(reg_el.get_text())
    assert mrp == 44995.0
    discount = round((mrp - price) / mrp * 100.0, 1)
    assert discount == 70.0


@pytest.mark.asyncio
async def test_qa_casio_radar_subbrand_filter():
    """QA Test 3: Verify radar correctly sweeps catalog and filters G-Shock sub-brand."""
    radar = StealRadar(settings)
    
    rule = RadarRule(
        name="Casio G-Shock 70%+ Drops",
        category="Watches",
        query="g-shock",
        brand="Casio",
        platforms=["casio"],
        min_discount=70.0,
        required_keywords=["g-shock", "casio"],
    )
    
    # Mock catalog scan output containing silent sales
    mock_deals = [
        {
            "title": "Casio G-Shock GW-5000HS-7",
            "price": 7349.0,
            "mrp": 24495.0,
            "discount_percent": 70.0,
            "in_stock": True,
            "url": "https://casiostore.bhawar.com/products/casio-g-shock-gw-5000hs-7-40th-anniversary-digital-watch",
            "family": "G-Shock",
            "is_silent_sale": True,
        },
        {
            "title": "Casio Edifice ECB-2200P-1A",
            "price": 5698.0,
            "mrp": 18995.0,
            "discount_percent": 70.0,
            "in_stock": True,
            "url": "https://casiostore.bhawar.com/products/casio-edifice-ecb-2200p-1a",
            "family": "Edifice",
            "is_silent_sale": False,
        },
    ]
    
    from unittest.mock import AsyncMock, patch
    with patch("scrapers.casio.CasioScraper.scan_catalog_deals", new_callable=AsyncMock) as mock_scan:
        mock_scan.return_value = mock_deals
        found = await radar.scan_rule(rule)
        
        # Should keep G-Shock and exclude Edifice based on query "g-shock"
        assert len(found) == 1
        assert found[0]["title"] == "Casio G-Shock GW-5000HS-7"
        assert found[0]["discount_percent"] == 70.0
        assert found[0]["effective_price"] == 7349.0
