"""tests/test_serverless_resilience.py — Verification of Vercel Serverless Fault Isolation & Timeout Guards.

Tests:
1. Blast-radius isolation: api/index.py resilience when rail_tracker / rail_daemon are unavailable.
2. Serverless timeout guard: api_rail_status fallback when CRIS is slow / times out.
3. Fast fallback: Static schedule accuracy and Supabase cache integration.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import api.index as api_index
from api.index import app, api_rail_status, api_rail_history, api_rail_action, _build_offline_rail_status


@pytest.fixture
def client():
    return TestClient(app)


def test_blast_radius_rail_status_when_modules_unavailable(client):
    """When rail modules fail to load, /api/rail/status returns a safe degraded response instead of crashing."""
    with patch.object(api_index, "RAIL_MODULES_AVAILABLE", False), \
         patch.object(api_index, "rail_tracker", None):
        resp = client.get("/api/rail/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "morning_scan" in data
        assert "rake_turnaround" in data
        assert "step_out_time" in data
        assert "lead_times" in data
        assert data["lead_times"]["home_to_pf1"] == 10
        assert data["morning_scan"]["recommended_train"]["train_no"] == "66596"


def test_blast_radius_rail_history_when_modules_unavailable(client):
    """When rail modules fail to load, /api/rail/history returns a safe empty structure."""
    with patch.object(api_index, "RAIL_MODULES_AVAILABLE", False), \
         patch.object(api_index, "rail_tracker", None):
        resp = client.get("/api/rail/history?days=14")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["days"] == 14
        assert "66596" in data["corridor_trains"]


def test_blast_radius_rail_action_when_daemon_unavailable(client):
    """When rail daemon fails to load, /api/rail/action returns 503 instead of crashing."""
    with patch.object(api_index, "RAIL_MODULES_AVAILABLE", False), \
         patch.object(api_index, "rail_daemon", None):
        resp = client.post("/api/rail/action", json={"action": "wfh"})
        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "error"


def test_serverless_timeout_guard_triggers_fast_fallback(client):
    """When live CRIS scan exceeds timeout or times out, api_rail_status falls back to static schedule."""
    # Force live scan in executor to raise TimeoutError
    with patch("api.index.asyncio.wait_for", side_effect=asyncio.TimeoutError("CRIS connection timed out")):
        resp = client.get("/api/rail/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "morning_scan" in data
        assert "rake_turnaround" in data
        assert data["morning_scan"]["recommended_train"]["train_no"] == "66596"
        assert data["lead_times"]["home_to_pf1"] == 10


def test_serverless_timeout_guard_with_supabase_cache(client):
    """When live CRIS times out, cached Supabase state is used to restore live morning delay."""
    cached_supabase = {
        "state": "MORNING_TRACKING",
        "morning_train": "66596",
        "morning_step_out_time": "08:35",
        "morning_projected_dep": "08:45",
        "morning_delay_mins": 20,
    }
    with patch("api.index.asyncio.wait_for", side_effect=asyncio.TimeoutError()), \
         patch("api.index._fetch_supabase_commute_state", new=AsyncMock(return_value=cached_supabase)):
        resp = client.get("/api/rail/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["step_out_time"] == "08:35"
        assert data["morning_scan"]["recommended_train"]["delay_mins"] == 20
        assert data["morning_scan"]["recommended_train"]["projected_departure"] == "08:45"


def test_cryptography_missing_guard_in_rail_tracker():
    """Verify that if cryptography is not available, encrypt/decrypt raise clean RuntimeError."""
    import rail_tracker
    with patch.object(rail_tracker, "CRYPTOGRAPHY_AVAILABLE", False):
        with pytest.raises(RuntimeError, match="cryptography package is required"):
            rail_tracker.encrypt_cris_payload("test")

        with pytest.raises(RuntimeError, match="cryptography package is required"):
            rail_tracker.decrypt_cris_payload("test")
