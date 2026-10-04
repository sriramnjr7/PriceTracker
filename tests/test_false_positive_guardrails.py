"""Unit tests verifying root-cause fixes for false positive price drop and back-in-stock alerts."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bs4 import BeautifulSoup
from scrapers.flipkart import FlipkartScraper
from tracker import Tracker
from database import Product


def test_evofox_ad_price_rejected_over_primary_price():
    """Verify that sponsored ad carousel items (₹461) are ignored in favor of primary buybox (₹1,599)."""
    html = """
    <html>
      <body>
        <!-- Top Sponsored Ad Carousel -->
        <div class="carousel-container" data-tracking-id="pla/p2psimilar">
          <a href="/tech-aura-ps-2-wired-dualshock-remote-controller/p/itmded5eeb688ed2?pid=ACCG6G9QH5XDNZCR&fm=advertisement">
            <div class="v1zwn21n">₹461</div>
          </a>
        </div>

        <!-- Primary Product Detail & Buybox -->
        <h1 class="VU-ZEz">EVOFOX One S Universal 3-Mode Wireless & Wired Bluetooth Gamepad</h1>
        <div class="hl05eU">
          <div class="Nx9bqj CxhGGd">₹1,599</div>
        </div>
        <button>Buy Now</button>
      </body>
    </html>
    """
    scraper = FlipkartScraper()
    url = "https://www.flipkart.com/evofox-one-s-universal-3-mode-wireless-wired-bluetooth-gamepad/p/itm062cf4a1b5665?pid=ACCHA24ZRYT3CYHR"
    result = scraper.parse(html, url)
    assert result.price == 1599.0
    assert result.price != 461.0
    assert result.in_stock is True


def test_ad_price_in_foreign_anchor_rejected_even_without_standard_selectors():
    """Even if standard buybox selectors are missing (React Native / hashed classes),

    prices inside foreign /p/ links or ad carousels must never be picked up as primary price.
    """
    html = """
    <html>
      <body>
        <!-- Sponsored item at top of DOM -->
        <div class="_1psv1zeb9">
          <a href="/other-accessory-controller/p/itm9999999999999?pid=ACCOTHER12345678&fm=advertisement">
            <div class="v1zwn21n">₹461</div>
          </a>
        </div>

        <!-- Main Product Title -->
        <h1>EVOFOX One S Universal 3-Mode Wireless & Wired Bluetooth Gamepad</h1>

        <!-- Mobile React unclassed price block (NOT inside foreign anchor) -->
        <div class="main-price-block">
          <div>₹1,599</div>
        </div>
        <button>Add to Cart</button>
      </body>
    </html>
    """
    scraper = FlipkartScraper()
    url = "https://www.flipkart.com/evofox-one-s-universal-3-mode-wireless-wired-bluetooth-gamepad/p/itm062cf4a1b5665?pid=ACCHA24ZRYT3CYHR"
    result = scraper.parse(html, url)
    assert result.price == 1599.0
    assert result.price != 461.0


def test_wd_variant_capacity_switch_marked_out_of_stock():
    """When a 1TB SKU is requested, but Flipkart rendered active 'Capacity: 250 GB'

    (because 1TB is out of stock), the scraper must flag in_stock = False.
    """
    html = """
    <html>
      <body>
        <h1 class="VU-ZEz">WESTERN DIGITAL WD Black SN770 1 TB Desktop, Laptop Black PCIe NVMe Internal Solid State Drive (SSD)</h1>
        <div class="variant-section">
          <div>Capacity: 250 GB</div>
        </div>
        <div class="Nx9bqj CxhGGd">₹2,951</div>
        <button>Buy Now</button>
      </body>
    </html>
    """
    scraper = FlipkartScraper()
    url = "https://www.flipkart.com/western-digital-wd-black-sn770-1-tb-desktop-laptop-internal-solid-state-drive-ssd-wds100t3x0e/p/itm2996885fa5723"
    result = scraper.parse(html, url)
    # Target 1-tb requested, but page rendered active 250 GB variant -> must be marked out of stock
    assert result.in_stock is False


def test_wd_matching_capacity_in_stock():
    """When a 1TB SKU is requested and page confirms 'Capacity: 1 TB', in_stock is True."""
    html = """
    <html>
      <body>
        <h1 class="VU-ZEz">WESTERN DIGITAL WD Black SN770 1 TB Desktop, Laptop Black PCIe NVMe Internal Solid State Drive (SSD)</h1>
        <div class="variant-section">
          <div>Capacity: 1 TB</div>
        </div>
        <div class="Nx9bqj CxhGGd">₹6,499</div>
        <button>Buy Now</button>
      </body>
    </html>
    """
    scraper = FlipkartScraper()
    url = "https://www.flipkart.com/western-digital-wd-black-sn770-1-tb-desktop-laptop-internal-solid-state-drive-ssd-wds100t3x0e/p/itm2996885fa5723"
    result = scraper.parse(html, url)
    assert result.in_stock is True
    assert result.price == 6499.0


def test_tracker_variant_consistency_guard():
    """Verify Tracker._is_variant_consistent catches capacity and RAM mismatches."""
    # 1 TB vs 250 GB
    assert not Tracker._is_variant_consistent(
        "WESTERN DIGITAL WD Black SN770 1 TB SSD",
        "https://flipkart.com/wd-1-tb/p/123",
        "WESTERN DIGITAL WD Black SN770 250 GB SSD"
    )
    # 1 TB vs 500 GB
    assert not Tracker._is_variant_consistent(
        "WESTERN DIGITAL WD Black SN770 1 TB SSD",
        "https://flipkart.com/wd-1-tb/p/123",
        "WESTERN DIGITAL WD Black SN770 500 GB SSD"
    )
    # 1 TB vs 1 TB (Consistent)
    assert Tracker._is_variant_consistent(
        "WESTERN DIGITAL WD Black SN770 1 TB SSD",
        "https://flipkart.com/wd-1-tb/p/123",
        "WESTERN DIGITAL WD Black SN770 1 TB SSD"
    )
    # Crucial 8GB RAM vs 16GB RAM
    assert not Tracker._is_variant_consistent(
        "Crucial 3200MHz DDR4 8GB Notebook RAM",
        "https://flipkart.com/crucial-8gb-ram/p/123",
        "Crucial 3200MHz DDR4 16GB Notebook RAM"
    )


@pytest.mark.asyncio
async def test_tracker_anomaly_drop_confirmation_gate():
    """When a single-tick drop exceeds 50%, tracker must re-probe and reject transient anomalies."""
    mock_db = MagicMock()
    mock_db.update_price = AsyncMock()
    mock_notifier = MagicMock()
    mock_notifier.notify = AsyncMock()

    tracker = Tracker(mock_db, mock_notifier)

    product = Product(
        id=45,
        url="https://www.flipkart.com/evofox-one-s/p/itm123?pid=ACCHA24ZRYT3CYHR",
        platform="flipkart",
        title="EVOFOX One S Universal 3-Mode Wireless & Wired Bluetooth Gamepad",
        initial_price=1599.0,
        current_price=1599.0,
        target_price=1350.0,
        percentage_drop_target=None,
        last_checked="2026-10-04T20:20:00",
        is_active=True,
        last_notified_price=None,
    )

    # First scrape returns anomalous price 461.0 (71% drop)
    # Second re-probe returns true price 1599.0
    mock_scraper = MagicMock()
    mock_result_anomaly = MagicMock(title=product.title, price=461.0, in_stock=True)
    mock_result_reprobe = MagicMock(title=product.title, price=1599.0, in_stock=True)
    mock_scraper.scrape = AsyncMock(side_effect=[mock_result_anomaly, mock_result_reprobe])

    with patch("tracker.get_scraper", return_value=mock_scraper):
        notified = await tracker.check_product(product)

    # Should NOT have alerted because re-probe corrected the price back to 1599.0
    assert notified is False
    mock_notifier.notify.assert_not_called()
