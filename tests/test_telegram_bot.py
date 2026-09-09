"""Unit tests for Telegram 2-Way Interactive Tracking Assistant (telegram_bot.py)."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from config import Settings
from database import Database, Product
from scrapers.base import ScrapeResult
from telegram_bot import TelegramAssistant


@pytest.fixture
def mock_db():
    db = MagicMock(spec=Database)
    db.initialize = AsyncMock()
    db.add_product = AsyncMock(return_value=42)
    db.get_products = AsyncMock(return_value=[])
    db.remove_product = AsyncMock()
    db.add_custom_rule = AsyncMock(return_value=99)
    return db


@pytest.fixture
def bot(mock_db):
    test_settings = Settings(telegram_bot_token="test_token", telegram_chat_id="123456")
    assistant = TelegramAssistant(test_settings, db=mock_db)
    assistant.send_reply = AsyncMock(return_value=True)
    return assistant


@pytest.mark.asyncio
async def test_handle_message_start_and_help(bot):
    await bot.handle_message({"chat": {"id": 123}, "text": "/start"})
    bot.send_reply.assert_called_once()
    assert "Welcome to Universal Deal Radar" in bot.send_reply.call_args[0][1]


@pytest.mark.asyncio
async def test_handle_message_status(bot):
    await bot.handle_message({"chat": {"id": 123}, "text": "/status"})
    bot.send_reply.assert_called_once()
    assert "Radar Status: ACTIVE" in bot.send_reply.call_args[0][1]


@pytest.mark.asyncio
async def test_handle_message_list_empty(bot):
    await bot.handle_message({"chat": {"id": 123}, "text": "/list"})
    bot.send_reply.assert_called_once()
    assert "No custom products currently tracked" in bot.send_reply.call_args[0][1]


@pytest.mark.asyncio
async def test_handle_message_list_with_products(bot, mock_db):
    mock_db.get_products.return_value = [
        Product(
            id=1,
            url="https://amazon.in/dp/B001",
            platform="amazon",
            title="Sony WH-1000XM5",
            initial_price=24990.0,
            current_price=24990.0,
            target_price=20000.0,
            percentage_drop_target=None,
            last_checked=None,
            is_active=True,
            last_notified_price=None,
        )
    ]
    await bot.handle_message({"chat": {"id": 123}, "text": "/list"})
    bot.send_reply.assert_called_once()
    assert "Sony WH-1000XM5" in bot.send_reply.call_args[0][1]
    assert "Target: *₹20000*" in bot.send_reply.call_args[0][1]


@pytest.mark.asyncio
async def test_handle_message_remove(bot, mock_db):
    await bot.handle_message({"chat": {"id": 123}, "text": "/remove 42"})
    mock_db.remove_product.assert_called_with(42)
    bot.send_reply.assert_called_with(123, "🗑️ Tracked product #42 has been removed.")


@pytest.mark.asyncio
async def test_handle_url_tracking(bot, mock_db):
    mock_scraper = MagicMock()
    mock_scraper.scrape = AsyncMock(return_value=ScrapeResult(
        title="Casio G-Shock GBD-300",
        price=3995.0,
        in_stock=True,
        platform="amazon",
        url="https://www.amazon.in/dp/B000GAYQJ0",
    ))

    with patch("telegram_bot.get_scraper", return_value=mock_scraper):
        await bot.handle_url_tracking(
            chat_id=123,
            url="https://www.amazon.in/dp/B000GAYQJ0",
            target_price=3500.0,
        )
        mock_db.add_product.assert_called_with(
            url="https://www.amazon.in/dp/B000GAYQJ0",
            platform="amazon",
            target_price=3500.0,
            initial_price=3995.0,
            title="Casio G-Shock GBD-300",
        )
        assert any("Tracking Added Successfully" in str(call) for call in bot.send_reply.call_args_list)


@pytest.mark.asyncio
async def test_handle_natural_language_tracking(bot, mock_db):
    # Mock AI parse intent
    bot.ai.parse_tracking_intent = AsyncMock(return_value={
        "query": "iphone 15",
        "target_price": 50000.0,
        "brand": "Apple",
        "category": "Smartphones",
    })

    # Mock search deal
    mock_scraper = MagicMock()
    mock_scraper.scan_deals = AsyncMock(return_value=[
        {
            "title": "Apple iPhone 15 128GB Black",
            "price": 52999.0,
            "effective_price": 52999.0,
            "mrp": 79900.0,
            "url": "https://amazon.in/dp/IPHONE15",
            "platform": "amazon",
        }
    ])

    with patch("telegram_bot.get_scraper", return_value=mock_scraper):
        await bot.handle_natural_language_tracking(
            chat_id=123,
            text="track if iphone 15 comes under 50k",
        )
        mock_db.add_product.assert_called_with(
            url="https://amazon.in/dp/IPHONE15",
            platform="amazon",
            target_price=50000.0,
            initial_price=52999.0,
            title="Apple iPhone 15 128GB Black",
        )
        assert any("Auto-Discovered & Tracking Active" in str(call) for call in bot.send_reply.call_args_list)
