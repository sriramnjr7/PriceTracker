"""Unit tests for the monitoring & threshold evaluation engine (tracker.py)."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from config import Settings
from database import Database, Product
from notifier import Notifier
from scrapers.base import ScrapeResult
from tracker import Tracker


@pytest.fixture
def mock_db():
    db = MagicMock(spec=Database)
    db.get_products = AsyncMock()
    db.update_price = AsyncMock()
    db.set_last_notified = AsyncMock()
    return db


@pytest.fixture
def mock_notifier():
    notifier = MagicMock(spec=Notifier)
    notifier.notify = AsyncMock(return_value=True)
    notifier.send_whatsapp = AsyncMock(return_value=True)
    return notifier


def test_target_text_formatting():
    p1 = Product(id=1, url="", platform="amazon", title="", initial_price=100, current_price=100, target_price=80, percentage_drop_target=None, last_checked=None, is_active=True, last_notified_price=None)
    assert Tracker._target_text(p1) == "₹80"

    p2 = Product(id=2, url="", platform="amazon", title="", initial_price=100, current_price=100, target_price=None, percentage_drop_target=25.0, last_checked=None, is_active=True, last_notified_price=None)
    assert Tracker._target_text(p2) == "25% drop"

    p3 = Product(id=3, url="", platform="amazon", title="", initial_price=100, current_price=100, target_price=None, percentage_drop_target=None, last_checked=None, is_active=True, last_notified_price=None)
    assert Tracker._target_text(p3) == "—"


def test_should_notify_target_price():
    # Hit target price (new_price <= target_price)
    p = Product(id=1, url="", platform="amazon", title="", initial_price=1000, current_price=1000, target_price=800, percentage_drop_target=None, last_checked=None, is_active=True, last_notified_price=None)
    should, drop = Tracker._should_notify(p, old_price=1000, new_price=799)
    assert should is True
    assert drop == 20.1

    # Above target price
    should_not, _ = Tracker._should_notify(p, old_price=1000, new_price=850)
    assert should_not is False


def test_should_notify_percentage_drop():
    p = Product(id=1, url="", platform="amazon", title="", initial_price=1000, current_price=1000, target_price=None, percentage_drop_target=20.0, last_checked=None, is_active=True, last_notified_price=None)
    # 25% drop from 1000 to 750 >= 20%
    should, drop = Tracker._should_notify(p, old_price=1000, new_price=750)
    assert should is True
    assert drop == 25.0

    # 10% drop < 20%
    should_not, _ = Tracker._should_notify(p, old_price=1000, new_price=900)
    assert should_not is False


def test_should_notify_antispam_new_low():
    # Already notified at 750, price is still 750 -> do not re-alert
    p = Product(id=1, url="", platform="amazon", title="", initial_price=1000, current_price=750, target_price=800, percentage_drop_target=None, last_checked=None, is_active=True, last_notified_price=750.0)
    should, _ = Tracker._should_notify(p, old_price=750, new_price=750)
    assert should is False

    # Price bounced up to 780 -> do not re-alert
    should_bounce, _ = Tracker._should_notify(p, old_price=750, new_price=780)
    assert should_bounce is False

    # Price dropped to new low 700 < 750 -> re-alert!
    should_new_low, _ = Tracker._should_notify(p, old_price=750, new_price=700)
    assert should_new_low is True


@pytest.mark.asyncio
async def test_check_product_standard_flow(mock_db, mock_notifier):
    tracker = Tracker(mock_db, mock_notifier)
    prod = Product(
        id=1,
        url="https://www.amazon.in/dp/B000GAYQJ0",
        platform="amazon",
        title="Casio Watch",
        initial_price=2000.0,
        current_price=2000.0,
        target_price=1500.0,
        percentage_drop_target=None,
        last_checked=None,
        is_active=True,
        last_notified_price=None,
    )

    mock_scraper = MagicMock()
    mock_scraper.scrape = AsyncMock(return_value=ScrapeResult(
        title="Casio Watch G-Shock",
        price=1400.0,
        in_stock=True,
        platform="amazon",
        url=prod.url,
    ))

    with patch("tracker.get_scraper", return_value=mock_scraper):
        alerted = await tracker.check_product(prod)
        assert alerted is True
        mock_db.update_price.assert_called_with(1, 1400.0, title="Casio Watch G-Shock")
        mock_notifier.notify.assert_called_once()
        mock_db.set_last_notified.assert_called_with(1, 1400.0)


@pytest.mark.asyncio
async def test_run_once_aggregates_alerts(mock_db, mock_notifier):
    prod1 = Product(id=1, url="https://amazon.in/p1", platform="amazon", title="P1", initial_price=1000.0, current_price=1000.0, target_price=800.0, percentage_drop_target=None, last_checked=None, is_active=True, last_notified_price=None)
    prod2 = Product(id=2, url="https://amazon.in/p2", platform="amazon", title="P2", initial_price=500.0, current_price=500.0, target_price=300.0, percentage_drop_target=None, last_checked=None, is_active=True, last_notified_price=None)

    mock_db.get_products.return_value = [prod1, prod2]

    tracker = Tracker(mock_db, mock_notifier)
    # Mock check_product so prod1 alerts and prod2 does not
    with patch.object(tracker, "check_product", side_effect=[True, False]):
        total_alerts = await tracker.run_once()
        assert total_alerts == 1
