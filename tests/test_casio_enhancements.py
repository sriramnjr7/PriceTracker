"""Unit tests for enhanced Casio scraper, prefix classifier, and catalog sweep."""

import pytest
from config import Settings
from scrapers.casio import CasioScraper
from brand_validator import BrandValidator, BrandStatus


@pytest.fixture
def casio_scraper():
    return CasioScraper(Settings())


def test_classify_casio_gshock_prefix(casio_scraper):
    family, formatted = casio_scraper._classify_casio_watch("GA-2100-1A1", ["RESIN"], "casio-g-shock-ga-2100-1adr")
    assert family == "G-Shock"
    assert "Casio G-Shock" in formatted
    assert "GA-2100-1A1" in formatted


def test_classify_casio_edifice_prefix(casio_scraper):
    family, formatted = casio_scraper._classify_casio_watch("EFB-730D-3A", ["100PGP"], "efb-730d-3a")
    assert family == "Edifice"
    assert "Casio Edifice" in formatted
    assert "EFB-730D-3A" in formatted


def test_classify_casio_mtp_vt03d(casio_scraper):
    family, formatted = casio_scraper._classify_casio_watch(
        "MTP-VT03D-1B",
        ["CASIO-MENS-METAL", "silent_sale_product"],
        "casio-mtp-vt03d-1bdf-black-analog-mens-watch"
    )
    assert family == "Casio"
    assert formatted == "Casio MTP-VT03D-1B"


def test_classify_casio_vintage(casio_scraper):
    family, formatted = casio_scraper._classify_casio_watch(
        "A1000MPG-9",
        ["A-1000", "VINTAGE"],
        "casio-vintage-a1000mpg-9ef-rose-gold"
    )
    assert family == "Vintage"
    assert "Casio Vintage" in formatted


def test_brand_validator_trusted_casio_bypass():
    validator = BrandValidator()
    result = validator.validate(
        scraped_brand="Casio",
        title="Casio MTP-VT03D-1B",
        target_brands=["casio", "g-shock", "edifice"],
        is_trusted_store=True
    )
    assert result.brand_status == BrandStatus.VERIFIED
    assert result.confidence_score >= 100


def test_casio_extract_stock_disabled_button(casio_scraper):
    """Ensure disabled or sold-out submit buttons evaluate strictly as out-of-stock."""
    from bs4 import BeautifulSoup
    html = """
    <div>
        <button id="ProductSubmitButton-template--main" type="submit" name="add" class="product-form__submit button" disabled="">
            <span class="sold-out-message">Sold out</span>
        </button>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    assert casio_scraper._extract_stock(soup) is False


def test_casio_extract_stock_active_button(casio_scraper):
    """Ensure enabled add-to-cart submit button evaluates as in-stock."""
    from bs4 import BeautifulSoup
    html = """
    <div>
        <button id="ProductSubmitButton-template--main" type="submit" name="add" class="product-form__submit button">
            <span>Add to cart</span>
        </button>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    assert casio_scraper._extract_stock(soup) is True


@pytest.mark.asyncio
async def test_casio_scrape_product_shopify_js_crosscheck(casio_scraper):
    """Verify that Shopify .js available=False overrides any optimistic HTML parsing."""
    from unittest.mock import AsyncMock, patch, MagicMock

    mock_html_resp = MagicMock()
    mock_html_resp.status_code = 200
    mock_html_resp.url = "https://casiostore.bhawar.com/products/casio-g-shock-gbd-300-9dr-watch"
    mock_html_resp.text = """
    <html>
      <body>
        <h1 class="product__title">GBD-300-9</h1>
        <span class="price-item price-item--sale">₹ 3,899</span>
        <button type="submit" name="add" class="product-form__submit">Add to cart</button>
      </body>
    </html>
    """

    mock_js_resp = MagicMock()
    mock_js_resp.status_code = 200
    mock_js_resp.json.return_value = {
        "available": False,
        "variants": [{"id": 123, "available": False, "price": 1299500}]
    }

    client = AsyncMock()
    async def fake_get(url, *args, **kwargs):
        if url.endswith(".js"):
            return mock_js_resp
        return mock_html_resp

    client.get = fake_get
    client.is_closed = False

    with patch.object(casio_scraper, "_get_authenticated_client", return_value=client):
        result = await casio_scraper.scrape_product("https://casiostore.bhawar.com/products/casio-g-shock-gbd-300-9dr-watch")
        assert result.price == 3899.0
        assert result.in_stock is False

