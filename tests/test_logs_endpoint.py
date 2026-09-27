"""Unit tests for System Logs endpoint and telemetry parser."""

import os
import pytest
from fastapi.testclient import TestClient

from api.index import app, get_parsed_logs, get_daemon_quick_status


@pytest.fixture
def client():
    return TestClient(app)


def test_daemon_quick_status():
    status = get_daemon_quick_status()
    assert isinstance(status, dict)
    assert "is_running" in status
    assert "status_text" in status
    assert "has_log_file" in status


def test_get_parsed_logs_structure():
    data = get_parsed_logs(limit=10)
    assert isinstance(data, dict)
    assert "status" in data
    assert "daemon" in data
    assert "logs" in data
    assert "recent_issues" in data

    daemon = data["daemon"]
    assert "counts" in daemon
    assert "total" in daemon["counts"]
    assert "errors" in daemon["counts"]
    assert "warnings" in daemon["counts"]
    assert "info" in daemon["counts"]


def test_logs_api_endpoint(client):
    res = client.get("/api/logs?limit=15")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "success"
    assert isinstance(body["logs"], list)
    assert len(body["logs"]) <= 15


def test_logs_api_level_filter(client):
    res = client.get("/api/logs?level=warning&limit=10")
    assert res.status_code == 200
    body = res.json()
    for log in body["logs"]:
        assert log["level"] in ("WARNING", "WARN")


def test_logs_api_search_filter(client):
    res = client.get("/api/logs?search=http&limit=10")
    assert res.status_code == 200
    body = res.json()
    for log in body["logs"]:
        assert "http" in log["message"].lower() or "http" in log["logger"].lower() or "http" in log["raw"].lower()
