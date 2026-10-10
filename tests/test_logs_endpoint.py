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


def test_vip_logs_api_endpoint(client):
    res = client.get("/api/logs/vip")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "success"
    assert "watches" in body
    assert isinstance(body["watches"], list)
    assert len(body["watches"]) == 2
    tags = [w["tag"] for w in body["watches"]]
    assert "gbd-h2000" in tags
    assert "gbd-300-9dr" in tags
    assert "logs" in body


def test_vip_in_main_logs_response(client):
    res = client.get("/api/logs?limit=10")
    assert res.status_code == 200
    body = res.json()
    assert "vip" in body
    assert len(body["vip"]["watches"]) == 2


def test_logs_spa_browser_route(client):
    # 1. Direct browser request to /logs
    res_direct = client.get("/logs", headers={"accept": "text/html,application/xhtml+xml"})
    assert res_direct.status_code == 200
    assert "text/html" in res_direct.headers.get("content-type", "")
    assert "<!DOCTYPE html>" in res_direct.text

    # 2. Vercel rewritten request to /api/index.py?_vercel_path=logs
    res_vercel = client.get("/api/index.py?_vercel_path=logs", headers={"accept": "text/html"})
    assert res_vercel.status_code == 200
    assert "text/html" in res_vercel.headers.get("content-type", "")
    assert "<!DOCTYPE html>" in res_vercel.text
