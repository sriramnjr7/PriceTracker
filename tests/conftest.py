"""conftest.py — Global test configurations and isolation fixtures.

Guarantees 100% network isolation for tests so that no automated test
can ever accidentally fire real Telegram API messages to any bot
(neither MyStealRadar nor SriTrainBot).
"""

from unittest.mock import MagicMock, patch
import pytest
import rail_daemon


@pytest.fixture(autouse=True)
def guard_telegram_network_calls():
    """Autouse fixture that patches TelegramClient.send_message across all test suites."""
    with patch.object(rail_daemon.TelegramClient, "send_message", return_value={"ok": True}) as mock_send:
        yield mock_send
