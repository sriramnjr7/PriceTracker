"""Unit tests for platform detection and scraper parsers (scrapers/)."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from bs4 import BeautifulSoup
from config import Settings
from scrapers import (
    AjioScraper,
    AmazonScraper,
    BaseScraper,
    BigBasketScraper,
    BlinkitScraper,
    CasioScraper,
    ComputechScraper,
    EliteHubsScraper,
    FlipkartScraper,
    GameLootScraper,
    InstamartScraper,
    MyntraScraper,
    ScrapeError,
    ZeptoScraper,
    detect_platform,
    get_scraper,
    resolve_platform,
)


def test_detect_platform_supported_domains():
    """Verify detect_platform identifies all standard and shortened domains."""
    assert detect_platform("https://www.amazon.in/dp/B000GAYQJ0") == "amazon"
    assert detect_platform("https://amzn.in/d/abc123") == "amazon"
    assert detect_platform("https://amzn.to/3xyz") == "amazon"

    assert detect_platform("https://www.flipkart.com/product/p/itm123") == "flipkart"
    assert detect_platform("https://dl.flipkart.com/dl/item") == "flipkart"
    assert detect_platform("https://fkrt.co/xyz") == "flipkart"
    assert detect_platform("https://fkrt.it/xyz") == "flipkart"

    assert detect_platform("https://www.myntra.com/shoes/crocs/123") == "myntra"
    assert detect_platform("https://myntr.it/abc") == "myntra"

    assert detect_platform("https://www.ajio.com/p/12345") == "ajio"
    assert detect_platform("https://ajio.page.link/xyz") == "ajio"

    assert detect_platform("https://casiostore.bhawar.com/products/gbd-300") == "casio"
    assert detect_platform("https://bhawar.com/products/watch") == "casio"

    assert detect_platform("https://elitehubs.com/products/crucial-p3-1tb-ssd") == "elitehubs"
    assert detect_platform("https://computechstore.in/product/controller") == "computech"
    assert detect_platform("https://gameloot.in/shop/ram") == "gameloot"

    assert detect_platform("https://www.bigbasket.com/pd/12345/apple") == "bigbasket"
    assert detect_platform("https://bbinstant.com/item/123") == "bigbasket"

    assert detect_platform("https://blinkit.com/prn/item/prid/123") == "blinkit"
    assert detect_platform("https://www.zepto.com/product/xyz") == "zepto"
    assert detect_platform("https://www.swiggy.com/instamart/item/123") == "instamart"


def test_detect_platform_unsupported():
    """Unsupported URL raises ValueError unless safe=True."""
    with pytest.raises(ValueError, match="Unsupported URL host"):
        detect_platform("https://www.unknown-shop.com/item")

    assert detect_platform("https://www.unknown-shop.com/item", safe=True) is None


@pytest.mark.asyncio
async def test_resolve_platform_with_redirect():
    """Shortened URL followed via redirect should resolve properly."""
    mock_resp = MagicMock()
    mock_resp.url = "https://www.amazon.in/dp/B000GAYQJ0"

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        res = await resolve_platform("https://bit.ly/3xyz")
        assert res == "amazon"


def test_get_scraper_factory():
    """Verify factory returns appropriate scraper instances."""
    assert isinstance(get_scraper("amazon"), AmazonScraper)
    assert isinstance(get_scraper("flipkart"), FlipkartScraper)
    assert isinstance(get_scraper("casio"), CasioScraper)
    assert isinstance(get_scraper("myntra"), MyntraScraper)
    assert isinstance(get_scraper("ajio"), AjioScraper)
    assert isinstance(get_scraper("bigbasket"), BigBasketScraper)
    assert isinstance(get_scraper("blinkit"), BlinkitScraper)
    assert isinstance(get_scraper("zepto"), ZeptoScraper)
    assert isinstance(get_scraper("instamart"), InstamartScraper)

    with pytest.raises(ValueError, match="Unknown platform"):
        get_scraper("invalid_platform")


def test_base_scraper_json_ld_price_extraction():
    """BaseScraper should parse Schema.org JSON-LD price and title."""
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org/",
          "@type": "Product",
          "name": "Sony WH-1000XM5 Wireless Headphones",
          "offers": {
            "@type": "Offer",
            "priceCurrency": "INR",
            "price": "24990",
            "availability": "https://schema.org/InStock"
          }
        }
        </script>
      </head>
      <body></body>
    </html>
    """
    scraper = AmazonScraper()
    result = scraper.parse(html, "https://amazon.in/dp/SONY123")
    assert result.title == "Sony WH-1000XM5 Wireless Headphones"
    assert result.price == 24990.0
    assert result.in_stock is True
    assert result.platform == "amazon"


def test_amazon_scraper_html_parsing():
    """Parse Amazon HTML elements with title and price selectors."""
    html = """
    <html>
      <head><title>Amazon.in</title></head>
      <body>
        <span id="productTitle">Casio G-Shock GBD-300-9DR Mens Watch</span>
        <span class="a-price aok-align-center reinventPricePriceToPayMargin priceToPay">
          <span class="a-offscreen">₹3,995.00</span>
        </span>
        <div id="availability">
          <span class="a-size-medium a-color-success">In stock</span>
        </div>
      </body>
    </html>
    """
    scraper = AmazonScraper()
    result = scraper.parse(html, "https://amazon.in/dp/B000GAYQJ0")
    assert "Casio G-Shock GBD-300" in result.title
    assert result.price == 3995.0
    assert result.in_stock is True


def test_amazon_scraper_out_of_stock():
    """Parse Amazon out of stock page."""
    html = """
    <html>
      <body>
        <span id="productTitle">Rare Vintage Casio Watch</span>
        <div id="availability">
          <span>Currently unavailable. We don't know when or if this item will be back in stock.</span>
        </div>
      </body>
    </html>
    """
    scraper = AmazonScraper()
    result = scraper.parse(html, "https://amazon.in/dp/B000GAYQJ0")
    assert result.title == "Rare Vintage Casio Watch"
    assert result.in_stock is False


def test_flipkart_scraper_html_parsing():
    """Parse Flipkart HTML elements."""
    html = """
    <html>
      <body>
        <span class="B_NuCI">Apple iPhone 15 (Black, 128 GB)</span>
        <div class="_30jeq3 _16J030">₹49,999</div>
      </body>
    </html>
    """
    scraper = FlipkartScraper()
    result = scraper.parse(html, "https://flipkart.com/item")
    assert "Apple iPhone 15" in result.title
    assert result.price == 49999.0
    assert result.in_stock is True


def test_casio_scraper_html_parsing():
    """Parse Casio Bhawar store HTML."""
    html = """
    <html>
      <head>
        <meta property="og:title" content="CASIO G-SHOCK GBD-300-9DR WATCH" />
      </head>
      <body>
        <h1 class="product__title">CASIO G-SHOCK GBD-300-9DR WATCH</h1>
        <span class="price-item price-item--sale">₹ 3,995</span>
      </body>
    </html>
    """
    scraper = CasioScraper()
    result = scraper.parse(html, "https://casiostore.bhawar.com/products/casio-gbd-300")
    assert "GBD-300" in result.title
    assert result.price == 3995.0
    assert result.in_stock is True


@pytest.mark.asyncio
async def test_casio_search_suggest_model_validation():
    """Ensure search_suggest rejects unrelated models (e.g. GBD-200) when searching for GBD-300."""
    scraper = CasioScraper()
    
    mock_resp_mismatched = MagicMock()
    mock_resp_mismatched.status_code = 200
    mock_resp_mismatched.json.return_value = {
        "resources": {
            "results": {
                "products": [
                    {
                        "title": "GBD-200UU-9",
                        "price": "12995.00",
                        "available": True,
                        "url": "/products/casio-g-shock-gbd-200uu-9dr-white-digital-mens-watch?_pos=1&_psq=g+shock+gbd+300+9dr",
                    }
                ]
            }
        }
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp_mismatched
        # Searching for GBD-300 should NOT match GBD-200UU-9
        res = await scraper._search_suggest("casio-g-shock-gbd-300-9dr-watch")
        assert res is None

    mock_resp_matching = MagicMock()
    mock_resp_matching.status_code = 200
    mock_resp_matching.json.return_value = {
        "resources": {
            "results": {
                "products": [
                    {
                        "title": "GBD-300-7",
                        "price": "12995.00",
                        "available": True,
                        "url": "/products/casio-g-shock-gbd-300-7dr-watch?_pos=1&_psq=gbd-300",
                    }
                ]
            }
        }
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp_matching
        # Searching for GBD-300 SHOULD match GBD-300-7
        res2 = await scraper._search_suggest("casio-g-shock-gbd-300-9dr-watch")
        assert res2 is not None
        assert "GBD-300" in res2.title
        assert res2.price == 12995.0


@pytest.mark.asyncio
async def test_scrape_out_of_stock_returns_valid_result():
    """Verify that scrape() returns a valid ScrapeResult for out of stock products instead of crashing."""
    scraper = AmazonScraper(Settings())
    html_out_of_stock = """
    <html>
      <head><title>Test Out of Stock Wireless Mouse</title></head>
      <body>
        <span id="productTitle">Logitech MX Master 3S Wireless Mouse</span>
        <div id="availability">
          <span class="a-size-medium a-color-price">Currently unavailable.</span>
          <span>We don't know when or if this item will be back in stock.</span>
        </div>
      </body>
    </html>
    """

    with patch.object(scraper, "_static_fetch", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = html_out_of_stock
        result = await scraper.scrape("https://www.amazon.in/dp/B0B4")
        assert result.title == "Logitech MX Master 3S Wireless Mouse"
        assert result.price is None
        assert result.in_stock is False
        assert result.platform == "amazon"


@pytest.mark.asyncio
async def test_elitehubs_scraper_in_stock_and_out_of_stock():
    """Verify EliteHubsScraper correctly parses Shopify .js responses for prices and availability."""
    scraper = EliteHubsScraper()

    mock_js_resp = MagicMock()
    mock_js_resp.status_code = 200
    mock_js_resp.json.return_value = {
        "title": "Crucial P3 1TB NVMe SSD",
        "price": 464500,
        "available": True,
        "variants": [{"title": "Default", "price": 464500, "available": True}],
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_js_resp
        res = await scraper.scrape("https://elitehubs.com/products/crucial-p3-1tb-ssd")
        assert res.title == "Crucial P3 1TB NVMe SSD"
        assert res.price == 4645.0
        assert res.in_stock is True
        assert res.platform == "elitehubs"


@pytest.mark.asyncio
async def test_computech_scraper():
    """Verify ComputechScraper parses JSON-LD price and in-stock status."""
    scraper = ComputechScraper()

    fake_html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org/",
          "@type": "Product",
          "name": "Cosmic Byte Blitz Controller",
          "offers": {
            "@type": "Offer",
            "price": "1699.00",
            "availability": "https://schema.org/InStock"
          }
        }
        </script>
      </head>
      <body><h1>Cosmic Byte Blitz Controller</h1></body>
    </html>
    """

    with patch.object(scraper, "_static_fetch", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = fake_html
        res = await scraper.scrape("https://computechstore.in/product/blitz/")
        assert res.title == "Cosmic Byte Blitz Controller"
        assert res.price == 1699.0
        assert res.in_stock is True
        assert res.platform == "computech"


@pytest.mark.asyncio
async def test_gameloot_scraper_out_of_stock():
    """Verify GameLootScraper parses OutOfStock JSON-LD status."""
    scraper = GameLootScraper()

    fake_html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org/",
          "@type": "Product",
          "name": "Crucial 8GB DDR4 RAM",
          "offers": [{
            "@type": "Offer",
            "price": "2999",
            "availability": "https://schema.org/OutOfStock"
          }]
        }
        </script>
      </head>
      <body>
        <div class="stock out-of-stock">SOLD OUT</div>
      </body>
    </html>
    """

    with patch.object(scraper, "_static_fetch", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = fake_html
        res = await scraper.scrape("https://gameloot.in/shop/ram/")
        assert res.title == "Crucial 8GB DDR4 RAM"
        assert res.price is None
        assert res.in_stock is False
        assert res.platform == "gameloot"




