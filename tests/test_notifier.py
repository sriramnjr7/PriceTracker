"""Unit tests for notification dispatch engine (notifier.py)."""

from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest
from config import Settings
from database import Product
from notifier import Notifier, _fmt_price, build_message


def test_fmt_price():
    assert _fmt_price(1999.0) == "₹1999"
    assert _fmt_price(1999.5) == "₹1999.5"
    assert _fmt_price(None) == "?"


def test_build_message():
    msg = build_message(
        title="Casio G-Shock Watch",
        old_price=8000.0,
        new_price=4000.0,
        drop_percent=50.0,
        target_text="₹4500",
        buy_url="https://amazon.in/dp/123",
    )
    assert "PRICE DROP ALERT!" in msg
    assert "Casio G-Shock Watch" in msg
    assert "₹8000" in msg
    assert "₹4000" in msg
    assert "50% OFF!" in msg
    assert "₹4500" in msg
    assert "https://amazon.in/dp/123" in msg


def test_build_message_restock():
    msg = build_message(
        title="Casio G-Shock GBD-300-9",
        old_price=None,
        new_price=3899.0,
        drop_percent=0.0,
        target_text="₹4000",
        buy_url="https://casiostore.bhawar.com/products/casio-g-shock-gbd-300-9dr-watch",
        is_restock=True,
    )
    assert "BACK IN STOCK / STEAL DEAL ALERT!" in msg
    assert "Casio G-Shock GBD-300-9" in msg
    assert "₹3899" in msg
    assert "₹4000" in msg



@pytest.mark.asyncio
async def test_shorten_url_success():
    notifier = Notifier()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "https://tinyurl.com/xyz123"

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        short = await notifier.shorten_url("https://amazon.in/dp/B000GAYQJ0")
        assert short == "https://tinyurl.com/xyz123"


@pytest.mark.asyncio
async def test_shorten_url_failure_fallback():
    notifier = Notifier()
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.ConnectError("Connection failed")
        raw_url = "https://amazon.in/dp/B000GAYQJ0"
        res = await notifier.shorten_url(raw_url)
        assert res == raw_url


@pytest.mark.asyncio
async def test_send_telegram_missing_credentials():
    test_settings = Settings(telegram_bot_token="", telegram_chat_id="")
    notifier = Notifier(test_settings)
    assert await notifier.send_telegram("Hello") is False


@pytest.mark.asyncio
async def test_send_telegram_success():
    test_settings = Settings(telegram_bot_token="fake_bot_token", telegram_chat_id="123456789")
    notifier = Notifier(test_settings)
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        res = await notifier.send_telegram("Test message")
        assert res is True
        mock_post.assert_called_once()


@pytest.mark.asyncio
async def test_send_whatsapp_success():
    test_settings = Settings(whatsapp_phone="+919876543210", whatsapp_api_key="fake_wa_key")
    notifier = Notifier(test_settings)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "Message sent successfully"

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        res = await notifier.send_whatsapp("Test WhatsApp message")
        assert res is True


@pytest.mark.asyncio
async def test_notify_flow():
    test_settings = Settings(telegram_bot_token="fake_bot_token", telegram_chat_id="123456789")
    notifier = Notifier(test_settings)

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, \
         patch.object(notifier, "shorten_url", return_value="https://tinyurl.com/item123"):
        mock_post.return_value = mock_resp
        prod = Product(
            id=1,
            url="https://amazon.in/dp/item123",
            platform="amazon",
            title="Sample Earbuds",
            initial_price=2000.0,
            current_price=2000.0,
            target_price=1500.0,
            percentage_drop_target=25.0,
            last_checked=None,
            is_active=True,
            last_notified_price=None,
        )
        res = await notifier.notify(
            product=prod,
            old_price=2000.0,
            new_price=1400.0,
            drop_percent=30.0,
            target_text="₹1500",
        )
        assert res is True
