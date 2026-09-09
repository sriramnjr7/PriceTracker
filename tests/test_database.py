"""Unit tests for SQLite database persistence layer (database.py)."""

import os
import tempfile
import pytest
import pytest_asyncio
from database import Database, Product, _now, _row_to_product


@pytest_asyncio.fixture
async def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    database = Database(path)
    await database.initialize()
    yield database
    await database.close()
    if os.path.exists(path):
        os.remove(path)


@pytest.mark.asyncio
async def test_database_initialization(db):
    """Database tables should be created and idempotent initialize works."""
    assert db.conn is not None
    await db.initialize()  # should not throw error if called twice
    assert db.conn is not None


@pytest.mark.asyncio
async def test_database_conn_uninitialized():
    """Uninitialized database should raise RuntimeError on conn property."""
    database = Database(":memory:")
    with pytest.raises(RuntimeError, match="Database.initialize\\(\\) must be called first"):
        _ = database.conn


@pytest.mark.asyncio
async def test_add_and_get_product(db):
    """Add product and retrieve it."""
    url = "https://www.amazon.in/dp/B000GAYQJ0"
    pid = await db.add_product(
        url=url,
        platform="amazon",
        title="Casio Watch",
        initial_price=1995.0,
        target_price=1500.0,
        percentage_drop_target=20.0,
    )
    assert pid > 0

    prod = await db.get_product(pid)
    assert prod is not None
    assert prod.id == pid
    assert prod.url == url
    assert prod.platform == "amazon"
    assert prod.title == "Casio Watch"
    assert prod.initial_price == 1995.0
    assert prod.current_price == 1995.0
    assert prod.target_price == 1500.0
    assert prod.percentage_drop_target == 20.0
    assert prod.is_active is True
    assert prod.last_notified_price is None


@pytest.mark.asyncio
async def test_add_duplicate_product_updates(db):
    """Adding same URL should update fields and keep row id."""
    url = "https://www.amazon.in/dp/B000GAYQJ0"
    pid1 = await db.add_product(url=url, platform="amazon", initial_price=2000.0, target_price=1800.0)
    pid2 = await db.add_product(url=url, platform="amazon", initial_price=2000.0, target_price=1500.0)
    assert pid1 == pid2

    prod = await db.get_product(pid1)
    assert prod.target_price == 1500.0


@pytest.mark.asyncio
async def test_get_products_and_filters(db):
    """Retrieve active and inactive products."""
    pid1 = await db.add_product(url="https://amazon.in/p1", platform="amazon", initial_price=100)
    pid2 = await db.add_product(url="https://flipkart.com/p2", platform="flipkart", initial_price=200)

    # Pause pid2
    await db.set_active(pid2, False)

    all_prods = await db.get_products(active_only=False)
    assert len(all_prods) == 2

    active_prods = await db.get_products(active_only=True)
    assert len(active_prods) == 1
    assert active_prods[0].id == pid1


@pytest.mark.asyncio
async def test_remove_product(db):
    """Remove product by ID."""
    pid = await db.add_product(url="https://amazon.in/p1", platform="amazon", initial_price=100)
    assert await db.get_product(pid) is not None

    await db.remove_product(pid)
    assert await db.get_product(pid) is None


@pytest.mark.asyncio
async def test_update_price_and_history(db):
    """Update price logs and verify history."""
    pid = await db.add_product(url="https://amazon.in/p1", platform="amazon", initial_price=1000.0)

    await db.update_price(pid, 900.0, title="Updated Title")
    prod = await db.get_product(pid)
    assert prod.current_price == 900.0
    assert prod.title == "Updated Title"

    await db.update_price(pid, 850.0)
    prod = await db.get_product(pid)
    assert prod.current_price == 850.0

    history = await db.price_history(pid)
    assert len(history) == 2
    assert history[0][0] == 850.0
    assert history[1][0] == 900.0

    # Test update_price with None (out of stock/unavailable)
    await db.update_price(pid, None, title="Out of stock item")
    prod = await db.get_product(pid)
    assert prod.title == "Out of stock item"
    # Price logs count should remain 2
    history2 = await db.price_history(pid)
    assert len(history2) == 2


@pytest.mark.asyncio
async def test_set_last_notified(db):
    """Set last notified price anti-spam marker."""
    pid = await db.add_product(url="https://amazon.in/p1", platform="amazon", initial_price=1000.0)
    await db.set_last_notified(pid, 800.0)

    prod = await db.get_product(pid)
    assert prod.last_notified_price == 800.0


@pytest.mark.asyncio
async def test_deal_alerts_log_and_deduplication(db):
    """Test 24h deal alerts log de-duplication and price drop override."""
    url = "https://amazon.in/dp/DEAL1"

    # Initially not notified
    assert await db.is_deal_recently_notified(url, hours=24, current_price=500.0) is False

    # Log deal alert at 500.0
    await db.log_deal_alert(
        product_url=url,
        title="Test Steal Item",
        price=600.0,
        effective_price=500.0,
        discount_percent=75.0,
        coupon_text="Flat 100 off",
        platform="amazon",
    )

    # Within default 20m window at same price (500.0) -> should be True (recently notified)
    assert await db.is_deal_recently_notified(url, current_price=500.0) is True
    assert await db.is_deal_recently_notified(url, minutes=20, current_price=500.0) is True

    # Within 24h at same price (500.0) -> should be True (recently notified)
    assert await db.is_deal_recently_notified(url, hours=24, current_price=500.0) is True

    # At higher price (510.0) -> should be True (recently notified)
    assert await db.is_deal_recently_notified(url, current_price=510.0) is True

    # When price drops further by >= ₹2 (e.g. 495.0 < 500.0 - 2.0) -> should return False to allow re-alert
    assert await db.is_deal_recently_notified(url, minutes=20, current_price=495.0) is False
    assert await db.is_deal_recently_notified(url, hours=24, current_price=495.0) is False


@pytest.mark.asyncio
async def test_custom_radar_rules_crud(db):
    """Test adding, querying, and deleting custom radar rules in DB."""
    rule_id = await db.add_custom_rule(
        name="Custom Sony XM5",
        query="sony wh-1000xm5",
        category="Audio",
        platforms="amazon,flipkart",
        min_discount=40.0,
        max_price=22000.0,
        min_mrp=25000.0,
        negative_keywords="case,cable,stand",
    )
    assert rule_id > 0

    rules = await db.get_custom_rules(active_only=True)
    assert len(rules) == 1
    r = rules[0]
    assert r["name"] == "Custom Sony XM5"
    assert r["query"] == "sony wh-1000xm5"
    assert r["category"] == "Audio"
    assert r["min_discount"] == 40.0
    assert r["max_price"] == 22000.0

    await db.remove_custom_rule(rule_id)
    rules_after = await db.get_custom_rules(active_only=True)
    assert len(rules_after) == 0
