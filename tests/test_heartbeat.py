"""Unit tests for the Heartbeat monitoring module (heartbeat.py)."""

from unittest.mock import AsyncMock, MagicMock
import pytest

from config import Settings
from heartbeat import build_heartbeat_message, check_and_send_heartbeat


def test_build_heartbeat_message():
    msg = build_heartbeat_message(active_count=11, rules_count=3, error_count=0, heartbeat_interval_hours=12.0)
    assert "PriceTracker Heartbeat: Active & Healthy" in msg
    assert "11 active products" in msg
    assert "Every 12h" in msg
    assert "IST" in msg


def test_build_heartbeat_message_hourly():
    msg = build_heartbeat_message(active_count=1, rules_count=3, error_count=0, heartbeat_interval_hours=1.0)
    assert "1 active product" in msg
    assert "Hourly" in msg


@pytest.mark.asyncio
async def test_check_and_send_heartbeat_interval_not_elapsed():
    mock_db = MagicMock()
    mock_db.is_deal_recently_notified = AsyncMock(return_value=True)
    mock_notifier = MagicMock()
    mock_notifier.send_telegram = AsyncMock(return_value=True)

    sent = await check_and_send_heartbeat(mock_db, mock_notifier, force=False)
    assert sent is False
    assert not mock_notifier.send_telegram.called


@pytest.mark.asyncio
async def test_check_and_send_heartbeat_dispatches_when_due():
    mock_db = MagicMock()
    mock_db.is_deal_recently_notified = AsyncMock(return_value=False)
    mock_db.get_products = AsyncMock(return_value=[MagicMock(), MagicMock()])
    mock_db.log_deal_alert = AsyncMock()

    mock_notifier = MagicMock()
    mock_notifier.send_telegram = AsyncMock(return_value=True)

    sent = await check_and_send_heartbeat(mock_db, mock_notifier, force=False)
    assert sent is True
    assert mock_notifier.send_telegram.called
    assert mock_db.log_deal_alert.called


@pytest.mark.asyncio
async def test_check_and_send_heartbeat_force():
    mock_db = MagicMock()
    mock_db.is_deal_recently_notified = AsyncMock(return_value=True)  # even if recently sent
    mock_db.get_products = AsyncMock(return_value=[MagicMock()])
    mock_db.log_deal_alert = AsyncMock()

    mock_notifier = MagicMock()
    mock_notifier.send_telegram = AsyncMock(return_value=True)

    sent = await check_and_send_heartbeat(mock_db, mock_notifier, force=True)
    assert sent is True
    assert mock_notifier.send_telegram.called
