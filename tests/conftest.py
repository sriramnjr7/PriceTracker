"""conftest.py — Global test configurations and isolation fixtures.

Guarantees 100% network isolation for tests:
1. No automated test can ever accidentally fire real Telegram API messages to any bot.
2. No automated test can ever mutate the live production Supabase commute_daily_state table.
3. Tests run against a temporary state file, preventing pollution of the workspace commute_daily_state.json.
"""

import os
import tempfile
from unittest.mock import MagicMock, patch
import pytest
import rail_daemon
import rail_tracker


@pytest.fixture(autouse=True)
def guard_telegram_network_calls():
    """Autouse fixture that patches TelegramClient.send_message across all test suites."""
    with patch.object(rail_daemon.TelegramClient, "send_message", return_value={"ok": True}) as mock_send:
        yield mock_send


@pytest.fixture(autouse=True)
def reset_watchdog():
    """Autouse fixture resetting rail watchdog before and after each test."""
    rail_tracker.watchdog.reset()
    yield
    rail_tracker.watchdog.reset()


@pytest.fixture(autouse=True)
def guard_supabase_sync():
    """Autouse fixture that prevents tests from mutating live Supabase database."""
    with patch.object(rail_daemon.CommuteStateStore, "_sync_to_supabase", return_value=None) as mock_sync:
        yield mock_sync


@pytest.fixture(autouse=True)
def isolate_local_state_file(tmp_path, monkeypatch):
    """Autouse fixture isolating local state file to temp directory for every test."""
    temp_state = str(tmp_path / "commute_daily_state.json")
    monkeypatch.setattr(rail_daemon, "LOCAL_STATE_FILE", temp_state)
    yield temp_state
