"""tests/test_rail_tracker.py — Comprehensive Unit & Integration Tests for RailRadar.

Covers:
1. CRIS NTES wire encryption, decryption & MD5 signatures
2. Delay parsing, time math, and '**UA**' ETA resolution
3. Multi-tier fallback (CRIS -> ConfirmTkt -> Static Empirical)
4. Incoming rake turnaround propagation & dynamic step-out shifting
5. Morning Multi-Train Opportunity Scanner & recommendation engine
6. Evening commute milestone triggers (Train 16232 @ Bangalore Cant)
7. 2-Strike Watchdog fail-safe alerts
8. Empirical 14-day delay analytics & P10/P50/P90 quantiles
9. Telegram Bot 14-command execution suite
10. Daemon State Machine lifecycle & Zero-polling persistence
11. FastAPI REST endpoints & SPA rewrites (/api/rail/status, /api/rail/history, /api/rail/action)
"""

import json
import os
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Ensure root directory is on path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

import rail_tracker
import rail_daemon
from api.index import app


@pytest.fixture
def client():
    return TestClient(app)


# =============================================================================
# 1. CRIS NTES WIRE PROTOCOL TESTS
# =============================================================================

def test_cris_wire_encryption_and_decryption():
    """Verify AES-128-CBC PKCS7 encryption and decryption round-trip."""
    payload = "service=TrainRunningMob&subService=ShowFullRunJson&trainNo=66596&startDate=13-Nov-2026"
    encrypted_hex = rail_tracker.encrypt_cris_payload(payload)
    assert isinstance(encrypted_hex, str)
    assert len(encrypted_hex) > 0

    decrypted = rail_tracker.decrypt_cris_payload(encrypted_hex)
    assert decrypted == payload

    # Test decrypt with MD5 prefix format: "HASH#ENCRYPTED"
    dummy_wire = f"MD5HASH12345#{encrypted_hex}"
    decrypted_with_hash = rail_tracker.decrypt_cris_payload(dummy_wire)
    assert decrypted_with_hash == payload


# =============================================================================
# 2. DELAY & TIME MATH PARSING (HANDLING '**UA**')
# =============================================================================

def test_parse_delay_minutes():
    """Verify parsing various delay string formats and corner cases."""
    assert rail_tracker.parse_delay_minutes("00:07") == 7
    assert rail_tracker.parse_delay_minutes("01:15") == 75
    assert rail_tracker.parse_delay_minutes("On Time") == 0
    assert rail_tracker.parse_delay_minutes("Right Time") == 0
    assert rail_tracker.parse_delay_minutes("RT") == 0
    assert rail_tracker.parse_delay_minutes("") == 0
    assert rail_tracker.parse_delay_minutes(None) == 0
    assert rail_tracker.parse_delay_minutes("-00:05") == -5
    assert rail_tracker.parse_delay_minutes("25 mins") == 25
    assert rail_tracker.parse_delay_minutes("1 hr 10 min") == 70
    assert rail_tracker.parse_delay_minutes(18) == 18


def test_time_math_and_difference():
    """Verify HH:MM addition, subtraction, and difference calculations."""
    assert rail_tracker.add_minutes_to_time("08:25", 10) == "08:35"
    assert rail_tracker.add_minutes_to_time("08:25", -10) == "08:15"
    assert rail_tracker.add_minutes_to_time("08:25 13-Nov", 15) == "08:40"
    assert rail_tracker.minutes_difference("08:15", "08:25") == 10
    assert rail_tracker.minutes_difference("08:40", "08:25") == -15


def test_resolve_eta_handling_ua():
    """Verify that **UA** (Unannounced) ETAs are properly resolved using STA + delay."""
    # When ETA is explicitly given
    assert rail_tracker.resolve_eta("08:57", "09:05", 8) == "09:05"

    # When ETA is **UA** and delay is 0 -> ETA equals STA
    assert rail_tracker.resolve_eta("08:57", "**UA**", 0) == "08:57"

    # When ETA is **UA** and train is delayed by 12 mins -> ETA is STA + 12m
    assert rail_tracker.resolve_eta("08:57", "**UA**", 12) == "09:09"

    # When ETA is empty
    assert rail_tracker.resolve_eta("09:03", "", 7) == "09:10"


# =============================================================================
# 3. RAKE TURNAROUND INSPECTOR & DYNAMIC STEP-OUT SHIFTING
# =============================================================================

def test_rake_turnaround_on_time():
    """When incoming rake 66595 is on time, scheduled 08:25 departure and 08:15 step-out are preserved."""
    with patch("rail_tracker.get_live_train_status") as mock_status:
        mock_status.side_effect = lambda t, d=None: {
            "66595": {
                "train_no": "66595",
                "current_station": "HSRA",
                "current_station_name": "HOSUR",
                "current_status": "Arrived on time",
                "delay_minutes": 0,
                "stations": [{"code": "HSRA", "sta": "08:00", "std": "Destination", "eta": "08:00", "etd": "08:00"}],
            },
            "66596": {
                "train_no": "66596",
                "current_station": "HSRA",
                "current_station_name": "HOSUR",
                "current_status": "Ready on platform",
                "delay_minutes": 0,
                "stations": [{"code": "HSRA", "sta": "Source", "std": "08:25", "eta": "Source", "etd": "08:25"}],
            },
        }[t]

        rake_info = rail_tracker.inspect_rake_turnaround("66596", "66595", reference_time="08:00")
        assert rake_info["is_delayed"] is False
        assert rake_info["scheduled_hsra_departure"] == "08:25"
        assert rake_info["projected_hsra_departure"] == "08:25"
        assert rake_info["revised_step_out_time"] == "08:15"


def test_rake_turnaround_delayed_rake_shifts_step_out():
    """
    CRITICAL USER REQUIREMENT TEST:
    If incoming rake 66595 is delayed arriving at Hosur (e.g. ETA 08:22 AM instead of 08:00 AM),
    Train 66596 cannot depart at 08:25.
    Turnaround requires 10 minutes (ETA 08:22 + 10m = 08:32 AM).
    The step-out alert must dynamically shift from 08:15 AM to 08:22 AM!
    """
    with patch("rail_tracker.get_live_train_status") as mock_status:
        mock_status.side_effect = lambda t, d=None: {
            "66595": {
                "train_no": "66595",
                "current_station": "AEK",
                "current_station_name": "ANEKAL ROAD",
                "current_status": "Running 22 mins late",
                "delay_minutes": 22,
                "stations": [{"code": "HSRA", "sta": "08:00", "std": "Destination", "eta": "08:22", "etd": "08:22"}],
            },
            "66596": {
                "train_no": "66596",
                "current_station": "HSRA",
                "current_station_name": "HOSUR",
                "current_status": "Awaiting rake",
                "delay_minutes": 0,
                "stations": [{"code": "HSRA", "sta": "Source", "std": "08:25", "eta": "Source", "etd": "08:25"}],
            },
        }[t]

        rake_info = rail_tracker.inspect_rake_turnaround("66596", "66595", reference_time="08:00")
        assert rake_info["is_delayed"] is True
        assert rake_info["projected_hsra_departure"] == "08:32"
        # 08:32 - 10m lead time = 08:22 step-out time
        assert rake_info["revised_step_out_time"] == "08:22"
        assert rake_info["effective_delay_mins"] == 7
        assert "Incoming rake (66595)" in rake_info["delay_summary"]
        assert "ANEKAL ROAD" in rake_info["delay_summary"]


# =============================================================================
# 4. MORNING MULTI-TRAIN OPPORTUNITY SCANNER
# =============================================================================

def test_morning_scanner_recommends_earlier_delayed_train():
    """
    USER REQUIREMENT TEST:
    If MEMU 66596 is delayed to 08:55 AM (incoming rake delayed), the user prefers taking the delayed MEMU
    (still reaching desk by 10:33 AM, well ahead of 11:00 AM) with dynamic step-out time shifted to 08:45 AM!
    """
    with patch("rail_tracker.inspect_rake_turnaround") as mock_rake, patch("rail_tracker.get_live_train_status") as mock_exp:
        mock_rake.return_value = {
            "morning_train": "66596",
            "incoming_rake_train": "66595",
            "scheduled_hsra_departure": "08:25",
            "projected_hsra_departure": "08:55",
            "effective_delay_mins": 30,
            "revised_step_out_time": "08:45",
            "is_delayed": True,
            "rake_current_station": "HLE",
            "rake_current_station_name": "HEELALIGE",
            "delay_summary": "Rake 66595 heavily delayed",
            "memu_status": {"stations": [{"code": "BLRR", "sta": "09:03", "eta": "09:33"}]},
        }

        mock_exp.side_effect = lambda t, d=None: {
            "06278": {
                "train_no": "06278",
                "train_name": "Dharmapuri - KSR Bengaluru MEMU",
                "current_station": "BLRR",
                "current_station_name": "BELANDUR ROAD",
                "delay_minutes": 0,
                "stations": [
                    {"code": "HSRA", "sta": "07:05", "std": "07:07", "eta": "07:05", "etd": "07:07", "has_departed": True},
                    {"code": "BLRR", "sta": "07:51", "std": "07:52", "eta": "07:51", "etd": "07:52"},
                ],
            },
            "16212": {
                "train_no": "16212",
                "train_name": "Salem - Yesvantpur Express",
                "current_station": "HSRA",
                "current_station_name": "HOSUR",
                "delay_minutes": 5,
                "stations": [
                    {"code": "HSRA", "sta": "08:18", "std": "08:20", "eta": "08:23", "etd": "08:25"},
                    {"code": "BLRR", "sta": "08:59", "std": "09:00", "eta": "09:04", "etd": "09:05"},
                ],
            },
        }.get(t, {})

        scan = rail_tracker.scan_morning_commute_options(reference_time="08:05")
        rec = scan["recommended_train"]
        assert rec["train_no"] == "66596"
        assert "66596" in scan["recommendation_reason"]
        assert rec["step_out_time"] == "08:45"


# =============================================================================
# 5. EVENING COMMUTE & MILESTONE TRIGGERS
# =============================================================================

def test_evening_commute_scanner():
    """Verify scanning evening return corridor trains from BLRR / CRLM."""
    options = rail_tracker.scan_evening_commute_options(reference_time="16:00")
    assert len(options) > 0
    # Train 66585 boards at BLRR with 20m lead time
    t66585 = next((o for o in options if o["train_no"] == "66585"), None)
    assert t66585 is not None
    assert t66585["boarding_station"] == "BLRR"
    assert t66585["lead_time_mins"] == 20

    # Train 16232 boards at CRLM with 25m lead time
    t16232 = next((o for o in options if o["train_no"] == "16232"), None)
    assert t16232 is not None
    assert t16232["boarding_station"] == "CRLM"
    assert t16232["lead_time_mins"] == 25


def test_evening_milestone_trigger_16232():
    """Train 16232 departure from Bangalore Cant (BNC) triggers 'LEAVE DESK NOW' alert."""
    status_departed = {
        "train_no": "16232",
        "stations": [
            {"code": "SBC", "has_departed": True, "effective_delay": 0},
            {"code": "BNC", "has_departed": True, "etd": "19:12", "effective_delay": 2},
            {"code": "CRLM", "has_departed": False, "eta": "19:37", "effective_delay": 2},
        ],
    }
    trigger = rail_tracker.check_evening_milestone_trigger("16232", status_departed)
    assert trigger is not None
    assert trigger["triggered"] is True
    assert trigger["action"] == "LEAVE_DESK_NOW"
    assert "LEAVE DESK NOW" in trigger["message"]
    assert "19:37" in trigger["message"]

    status_not_departed = {
        "train_no": "16232",
        "stations": [
            {"code": "BNC", "has_departed": False, "effective_delay": 0},
        ],
    }
    assert rail_tracker.check_evening_milestone_trigger("16232", status_not_departed) is None


# =============================================================================
# 6. WATCHDOG 2-STRIKE FAIL-SAFE ALERTS
# =============================================================================

def test_watchdog_two_strike_fail_safe():
    """Verify watchdog requires 2 consecutive failures before firing alert and resets on success."""
    wd = rail_tracker.RailWatchdog(failure_threshold=2)

    # 1st failure -> no alert
    res1 = wd.record_failure("66596", "Connection timeout")
    assert res1 is None
    assert wd.consecutive_failures == 1
    assert wd.alert_triggered is False

    # 2nd failure -> triggers fail-safe alert with direct links
    res2 = wd.record_failure("66596", "SSL Handshake failure")
    assert res2 is not None
    assert res2["triggered"] is True
    assert "Watchdog Fail-Safe Triggered" in res2["message"]
    assert len(res2["links"]) >= 2
    assert wd.alert_triggered is True

    # 3rd failure -> already triggered, no duplicate alert spam
    res3 = wd.record_failure("66596", "Still down")
    assert res3 is None

    # Success resets counter
    wd.record_success()
    assert wd.consecutive_failures == 0
    assert wd.alert_triggered is False


# =============================================================================
# 7. 14-DAY DELAY QUANTILE ANALYTICS
# =============================================================================

def test_empirical_quantiles_analytics():
    """Verify P10, P50, P90, Mean, Std, and On-Time percentages are present."""
    stats = rail_tracker.load_delay_statistics()
    assert "66596" in stats
    blrr_stats = rail_tracker.get_train_delay_stats("66596", "BLRR")
    assert "P50" in blrr_stats
    assert "P90" in blrr_stats
    assert "OnTimePct" in blrr_stats
    assert blrr_stats["P50"] >= 0
    assert blrr_stats["P90"] >= blrr_stats["P50"]


# =============================================================================
# 8. TELEGRAM DAEMON 14 COMMANDS SUITE
# =============================================================================

def test_daemon_14_commands_suite():
    """Verify all 14 Telegram commands parse and execute without exceptions."""
    daemon = rail_daemon.RailDaemon()
    daemon.bot.send_message = MagicMock()

    with patch("rail_tracker.get_live_train_status") as mock_live, \
         patch("rail_tracker.inspect_rake_turnaround") as mock_rake, \
         patch("rail_tracker.scan_morning_commute_options") as mock_morning, \
         patch("rail_tracker.scan_evening_commute_options") as mock_evening:

        mock_live.return_value = {
            "train_no": "66596",
            "train_name": "Hosur - Yesvantpur MEMU",
            "current_station": "HSRA",
            "current_station_name": "HOSUR",
            "current_status": "On time",
            "delay_minutes": 0,
            "source": "CRIS NTES",
            "last_updated": "08:20 AM",
            "stations": [
                {"code": "HSRA", "name": "HOSUR", "station_name": "HOSUR", "sta": "08:25", "std": "08:25", "eta": "08:25", "etd": "08:25", "effective_delay": 0, "has_arrived": False, "has_departed": False},
                {"code": "BLRR", "name": "BELLANDUR ROAD", "station_name": "BELLANDUR ROAD", "sta": "09:03", "std": "09:05", "eta": "09:03", "etd": "09:05", "effective_delay": 0, "has_arrived": False, "has_departed": False},
            ],
        }
        mock_rake.return_value = {
            "morning_train": "66596",
            "incoming_rake_train": "66595",
            "scheduled_hsra_departure": "08:25",
            "projected_hsra_departure": "08:25",
            "effective_delay_mins": 0,
            "revised_step_out_time": "08:15",
            "is_delayed": False,
            "rake_cancelled": False,
            "rake_current_station": "HSRA",
            "rake_current_station_name": "HOSUR",
            "rake_delay_mins": 0,
            "rake_eta_hsra": "08:10",
            "delay_summary": "Incoming rake on time",
        }
        mock_morning.return_value = {
            "recommended_train": {
                "train_no": "66596",
                "train_name": "Hosur - Yesvantpur MEMU",
                "projected_departure": "08:25",
                "step_out_time": "08:15",
                "dest_station": "BLRR",
                "dest_eta": "09:03",
                "desk_eta": "09:33",
                "delay_mins": 0,
            },
            "recommendation_reason": "Train 66596 is the LATEST morning MEMU.",
            "options": [],
            "rake_turnaround": {
                "rake_current_station_name": "HOSUR",
                "rake_delay_mins": 0,
            },
        }
        mock_evening.return_value = [
            {
                "train_no": "66585",
                "train_name": "Bengaluru - Marikuppam MEMU",
                "boarding_station": "BLRR",
                "scheduled_departure": "15:43",
                "estimated_departure": "15:43",
                "delay_mins": 0,
                "leave_desk_time": "15:23",
                "lead_time_mins": 20,
                "hosur_eta": "16:45",
            }
        ]

        commands = [
            "/help",
            "/status",
            "/morning",
            "/evening",
            "/train 66596",
            "/track 66596",
            "/rake",
            "/delays",
            "/wfh",
            "/bike",
            "/station HSRA",
            "/eta 66596",
            "/milestones",
            "/reset",
        ]

        for cmd in commands:
            daemon.execute_command(cmd, chat_id="12345")
            assert daemon.bot.send_message.called, f"Command {cmd} failed to respond."
            daemon.bot.send_message.reset_mock()


# =============================================================================
# 9. DAEMON STATE MACHINE & ZERO-POLLING PERSISTENCE
# =============================================================================

def test_daemon_state_machine_and_zero_polling(tmp_path):
    """Verify state transitions and that database writes happen only on real transitions."""
    test_state_file = os.path.join(tmp_path, "test_commute_state.json")
    store = rail_daemon.CommuteStateStore(file_path=test_state_file)
    assert store.state_data["state"] == rail_daemon.STATE_NIGHT_SLEEP

    # Transition to MORNING_PROMPT
    store.transition_state(rail_daemon.STATE_MORNING_PROMPT, "Morning wake up")
    assert store.state_data["state"] == rail_daemon.STATE_MORNING_PROMPT

    # WFH override
    store.transition_state(rail_daemon.STATE_WFH, "User selected WFH")
    assert store.state_data["state"] == rail_daemon.STATE_WFH

    # Reset
    store.reset_today()
    assert store.state_data["state"] == rail_daemon.STATE_NIGHT_SLEEP


def test_daemon_cmd_reached_transitions_and_quiets(tmp_path):
    """Test /reached and 'reached' text command pausing tracking into standby/hibernation."""
    test_state_file = os.path.join(tmp_path, "test_commute_state.json")
    store = rail_daemon.CommuteStateStore(file_path=test_state_file)

    class MockBot:
        def __init__(self):
            self.messages = []
        def send_message(self, text, **kwargs):
            self.messages.append(text)
            return {"ok": True}
        def get_updates(self, **kwargs):
            return []

    mock_bot = MockBot()
    daemon = rail_daemon.RailDaemon(store=store, bot=mock_bot)

    # 1. Morning commute reached -> MIDDAY_STANDBY
    store.transition_state(rail_daemon.STATE_MORNING_TRACKING, "Tracking morning train")
    daemon.cmd_reached("12345")
    assert store.state_data["state"] == rail_daemon.STATE_MIDDAY_STANDBY
    assert "Morning commute completed" in mock_bot.messages[-1]

    # 2. Evening commute reached -> HIBERNATION
    store.transition_state(rail_daemon.STATE_EVENING_TRACKING, "Tracking evening train")
    daemon.execute_command("reached", chat_id="12345")
    assert store.state_data["state"] == rail_daemon.STATE_HIBERNATION
    assert "Welcome Home to Hosur" in mock_bot.messages[-1]


def test_daemon_morning_recommendation_flip_notifies_user(tmp_path, monkeypatch):
    """Verify that when Salem Express arrives early/on-time and Hosur MEMU is delayed, a flip alert is sent."""
    test_state_file = os.path.join(tmp_path, "test_flip_state.json")
    store = rail_daemon.CommuteStateStore(file_path=test_state_file)

    class MockBot:
        def __init__(self):
            self.messages = []
            self.reply_markups = []
        def send_message(self, text, reply_markup=None, **kwargs):
            self.messages.append(text)
            self.reply_markups.append(reply_markup)
            return {"ok": True}
        def get_updates(self, **kwargs):
            return []

    mock_bot = MockBot()
    daemon = rail_daemon.RailDaemon(store=store, bot=mock_bot)

    # Initially tracking 16212 (Salem Express) as recommended
    store.state_data["state"] = rail_daemon.STATE_MORNING_TRACKING
    store.state_data["morning_train"] = "16212"
    store.state_data["last_recommended_train"] = "16212"

    # Now simulate condition: Salem Exp 16212 is ON TIME (dep 08:20) and Hosur MEMU 66596 is DELAYED (dep 08:50)
    mock_scan = {
        "reference_time": "07:45",
        "recommended_train": {
            "train_no": "66596",
            "train_name": "Hosur - Yesvantpur MEMU",
            "scheduled_departure": "08:25",
            "projected_departure": "08:50",
            "step_out_time": "08:40",
            "dest_eta": "09:32",
            "desk_eta": "10:02",
            "delay_mins": 25,
            "status": "VIABLE",
        },
        "recommendation_reason": "Train 66596 departs latest at ~08:50 AM, giving extra sleep!",
        "options": [
            {
                "train_no": "66596",
                "train_name": "Hosur - Yesvantpur MEMU",
                "projected_departure": "08:50",
                "step_out_time": "08:40",
                "dest_eta": "09:32",
                "desk_eta": "10:02",
                "delay_mins": 25,
                "status": "VIABLE",
            },
            {
                "train_no": "16212",
                "train_name": "Salem - Yesvantpur Express",
                "projected_departure": "08:20",
                "step_out_time": "08:10",
                "dest_eta": "09:20",
                "desk_eta": "09:50",
                "delay_mins": 0,
                "status": "VIABLE",
            },
        ],
        "rake_turnaround": {"incoming_rake_train": "66595", "rake_delay_mins": 25},
    }

    monkeypatch.setattr(rail_tracker, "scan_morning_commute_options", lambda reference_time=None: mock_scan)

    # Run morning tracking cycle
    daemon.handle_morning_tracking("07:45")

    # Verify flip alert sent!
    assert any("Train Order Flipped" in m for m in mock_bot.messages)
    flip_msg = next(m for m in mock_bot.messages if "Train Order Flipped" in m)
    assert "66596" in flip_msg
    assert "16212" in flip_msg
    assert "08:50 AM" in flip_msg

    # Verify state updated to new optimal train 66596
    assert store.state_data["morning_train"] == "66596"
    assert store.state_data["last_recommended_train"] == "66596"
    assert store.state_data["morning_step_out_time"] == "08:40"


# =============================================================================
# 10. FASTAPI REST ENDPOINTS & SPA REWRITES
# =============================================================================

def test_api_rail_status_endpoint(client):
    """GET /api/rail/status returns comprehensive live commute telemetry."""
    resp = client.get("/api/rail/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "morning_scan" in data
    assert "rake_turnaround" in data
    assert "step_out_time" in data
    assert "lead_times" in data
    assert data["lead_times"]["home_to_pf1"] == 10


def test_api_rail_history_endpoint(client):
    """GET /api/rail/history?days=14 returns 14-day delay percentiles."""
    resp = client.get("/api/rail/history?days=14")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "stats" in data
    assert "corridor_trains" in data
    assert "66596" in data["corridor_trains"]


def test_api_rail_action_endpoint(client):
    """POST /api/rail/action executes WFH, Bike, Select Train, and Reset actions."""
    # Action WFH
    resp_wfh = client.post("/api/rail/action", json={"action": "wfh"})
    assert resp_wfh.status_code == 200
    assert "Work From Home" in resp_wfh.json()["message"]

    # Action Select Train
    resp_track = client.post("/api/rail/action", json={"action": "select_train", "train_no": "16212"})
    assert resp_track.status_code == 200
    assert "16212" in resp_track.json()["message"]

    # Action Reached
    resp_reached = client.post("/api/rail/action", json={"action": "reached"})
    assert resp_reached.status_code == 200

    # Action Reset
    resp_reset = client.post("/api/rail/action", json={"action": "reset"})
    assert resp_reset.status_code == 200


def test_spa_rail_radar_routes(client):
    """Verify that browser routes /rail-radar, /rail, /commute serve Dashboard HTML."""
    for path in ["/rail-radar", "/rail", "/commute"]:
        resp = client.get(path, headers={"Accept": "text/html"})
        assert resp.status_code == 200
        assert "<!DOCTYPE html>" in resp.text
        assert "Rail Radar" in resp.text


# =============================================================================
# 11. EDGE CASES & ADAPTIVE POLLING TESTS
# =============================================================================

def test_adaptive_polling_tiers():
    """Verify 4-tier adaptive polling calculates correct intervals based on state and lead time."""
    daemon = rail_daemon.RailDaemon()

    # 1. Critical window: 10 mins until step-out -> Tier 1 (30s)
    daemon.store.state_data["state"] = rail_daemon.STATE_MORNING_TRACKING
    daemon.store.state_data["morning_step_out_time"] = "08:15"
    assert daemon.determine_poll_interval("08:05") == rail_daemon.POLL_TIER_CRITICAL

    # 2. Approach window: 45 mins until step-out -> Tier 2 (60s)
    assert daemon.determine_poll_interval("07:30") == rail_daemon.POLL_TIER_APPROACH

    # 3. Standby / Midday -> Tier 3 (900s / 15m)
    daemon.store.state_data["state"] = rail_daemon.STATE_MIDDAY_STANDBY
    assert daemon.determine_poll_interval("11:00") == rail_daemon.POLL_TIER_STANDBY

    # 4. WFH / Bike override -> Standby (900s)
    daemon.store.state_data["state"] = rail_daemon.STATE_WFH
    assert daemon.determine_poll_interval("08:10") == rail_daemon.POLL_TIER_STANDBY

    # 5. Night sleep -> Hibernate (10s low-frequency loop)
    daemon.store.state_data["state"] = rail_daemon.STATE_NIGHT_SLEEP
    assert daemon.determine_poll_interval("23:15") == rail_daemon.POLL_TIER_HIBERNATE


def test_proactive_delay_notification_dispatch():
    """Verify daemon dispatches proactive push notification when delay increases by >= 3 mins."""
    daemon = rail_daemon.RailDaemon()
    daemon.bot.send_message = MagicMock()
    daemon.store.state_data["state"] = rail_daemon.STATE_MORNING_TRACKING
    daemon.store.state_data["last_delay_reported"] = 0
    daemon.store.state_data["last_step_out_reported"] = "08:15"

    with patch("rail_tracker.scan_morning_commute_options") as mock_scan:
        mock_scan.return_value = {
            "options": [
                {
                    "train_no": "66596",
                    "train_name": "Hosur MEMU",
                    "projected_departure": "08:35",
                    "step_out_time": "08:25",
                    "dest_eta": "09:13",
                    "desk_eta": "09:43",
                    "delay_mins": 10,
                    "status": "VIABLE",
                }
            ],
            "recommended_train": {
                "train_no": "66596",
                "train_name": "Hosur MEMU",
                "projected_departure": "08:35",
                "step_out_time": "08:25",
                "dest_eta": "09:13",
                "desk_eta": "09:43",
                "delay_mins": 10,
                "status": "VIABLE",
            },
            "rake_turnaround": {
                "incoming_rake_train": "66595",
                "rake_current_station": "AEK",
                "rake_current_station_name": "ANEKAL ROAD",
                "rake_delay_mins": 10,
            },
        }

        # 1. 10m delay shift (diff >= 3m) -> dispatches Telegram message
        daemon.handle_morning_tracking("08:00")
        assert daemon.bot.send_message.called
        call_msg = daemon.bot.send_message.call_args[0][0]
        assert "Commute Delay Alert" in call_msg
        assert "10 mins" in call_msg
        assert "08:25 AM" in call_msg
        assert daemon.store.state_data["last_delay_reported"] == 10
        assert daemon.store.state_data["morning_step_out_time"] == "08:25"

        # 2. Small 1m shift (from 10m to 11m) -> no spam notification sent!
        daemon.bot.send_message.reset_mock()
        mock_scan.return_value["options"][0]["delay_mins"] = 11
        daemon.handle_morning_tracking("08:01")
        assert not daemon.bot.send_message.called


def test_step_out_trigger_alert_fires_at_window():
    """Verify step-out push alert fires precisely at step_out_time."""
    daemon = rail_daemon.RailDaemon()
    daemon.bot.send_message = MagicMock()
    daemon.store.state_data["state"] = rail_daemon.STATE_MORNING_TRACKING
    daemon.store.state_data["morning_step_out_time"] = "08:20"
    daemon.store.state_data["last_delay_reported"] = 5
    daemon.store.state_data["morning_stepped_out"] = False

    with patch("rail_tracker.scan_morning_commute_options") as mock_scan:
        mock_scan.return_value = {
            "options": [
                {
                    "train_no": "66596",
                    "train_name": "Hosur MEMU",
                    "projected_departure": "08:30",
                    "step_out_time": "08:20",
                    "dest_eta": "09:08",
                    "desk_eta": "09:38",
                    "delay_mins": 5,
                    "status": "VIABLE",
                }
            ],
            "recommended_train": {
                "train_no": "66596",
                "status": "VIABLE",
            },
            "rake_turnaround": {"incoming_rake_train": "66595", "rake_current_station": "AEK", "rake_current_station_name": "AEK", "rake_delay_mins": 5},
        }

        # Current time is 08:20 (matches step_out_time 08:20)
        daemon.handle_morning_tracking("08:20")
        assert daemon.bot.send_message.called
        call_msg = daemon.bot.send_message.call_args[0][0]
        assert "STEP OUT NOW" in call_msg
        assert daemon.store.state_data["morning_stepped_out"] is True


# =============================================================================
# 11. ENHANCED EDGE CASE & USER REQUIREMENT VERIFICATION
# =============================================================================

def test_morning_scanner_recommends_delayed_other_memu_06278():
    """
    Verify that when comparing morning MEMUs (e.g. Express has departed or is unavailable),
    the scanner recommends whichever MEMU departs latest.

    Case 1: When Train 06278 is delayed and departs Hosur at 08:35 AM while 66596 is on time at 08:25 AM,
    06278 is the latest viable train, so the scanner recommends 06278.

    Case 2: When Train 66596 is delayed to 08:45 AM while 06278 departs earlier at 08:15 AM,
    66596 is the latest viable train, so the scanner recommends 66596.
    """
    with patch("rail_tracker.inspect_rake_turnaround") as mock_rake, patch("rail_tracker.get_live_train_status") as mock_status:
        # Case 1: 66596 on-time at 08:25 AM; 06278 delayed to 08:35 AM; 16212 departed
        mock_rake.return_value = {
            "morning_train": "66596",
            "incoming_rake_train": "66595",
            "scheduled_hsra_departure": "08:25",
            "projected_hsra_departure": "08:25",
            "effective_delay_mins": 0,
            "revised_step_out_time": "08:15",
            "is_delayed": False,
            "rake_cancelled": False,
            "rake_current_station": "HSRA",
            "rake_current_station_name": "HOSUR",
            "delay_summary": "Incoming rake on time",
            "memu_status": {"stations": [{"code": "BLRR", "sta": "09:03", "eta": "09:03"}]},
        }

        mock_status.side_effect = lambda t, d=None: {
            "06278": {
                "train_no": "06278",
                "train_name": "Dharmapuri - KSR Bengaluru MEMU",
                "current_station": "KMLM",
                "current_station_name": "KELAMANGALAM",
                "delay_minutes": 88,
                "stations": [
                    {"code": "HSRA", "sta": "07:05", "std": "07:07", "eta": "08:33", "etd": "08:35", "has_arrived": False, "has_departed": False},
                    {"code": "BLRR", "sta": "07:51", "std": "07:52", "eta": "09:19", "etd": "09:20", "has_arrived": False, "has_departed": False},
                ],
            },
            "16212": {
                "train_no": "16212",
                "train_name": "Salem Express",
                "current_station": "SBC",
                "current_station_name": "BENGALURU",
                "delay_minutes": 0,
                "stations": [
                    {"code": "HSRA", "sta": "08:18", "std": "08:20", "eta": "08:20", "etd": "08:20", "has_arrived": True, "has_departed": True},
                ],
            },
        }[t]

        scan = rail_tracker.scan_morning_commute_options(reference_time="08:00")
        assert len(scan["options"]) == 3
        opt_06278 = next((o for o in scan["options"] if o["train_no"] == "06278"), None)
        assert opt_06278 is not None
        assert opt_06278["type"] == "MEMU"
        assert opt_06278["is_delayed"] is True
        assert opt_06278["status"] in ("VIABLE", "BOARDING")
        assert opt_06278["projected_departure"] == "08:35"
        assert opt_06278["step_out_time"] == "08:25"

        # 06278 departs at 08:35 (later than 66596's 08:25), so 06278 is recommended!
        rec = scan["recommended_train"]
        assert rec["train_no"] == "06278"
        assert "08:35" in scan["recommendation_reason"]

        # Case 2: 66596 delayed to 08:45 AM; 06278 at 08:15 AM; 16212 departed
        mock_rake.return_value["projected_hsra_departure"] = "08:45"
        mock_rake.return_value["effective_delay_mins"] = 20
        mock_rake.return_value["is_delayed"] = True

        mock_status.side_effect = lambda t, d=None: {
            "06278": {
                "train_no": "06278",
                "train_name": "Dharmapuri - KSR Bengaluru MEMU",
                "current_station": "KMLM",
                "current_station_name": "KELAMANGALAM",
                "delay_minutes": 68,
                "stations": [
                    {"code": "HSRA", "sta": "07:05", "std": "07:07", "eta": "08:13", "etd": "08:15", "has_arrived": False, "has_departed": False},
                    {"code": "BLRR", "sta": "07:51", "std": "07:52", "eta": "08:59", "etd": "09:00", "has_arrived": False, "has_departed": False},
                ],
            },
            "16212": {
                "train_no": "16212",
                "train_name": "Salem Express",
                "current_station": "SBC",
                "delay_minutes": 0,
                "stations": [{"code": "HSRA", "std": "08:20", "etd": "08:20", "has_departed": True}],
            },
        }[t]

        scan2 = rail_tracker.scan_morning_commute_options(reference_time="08:00")
        # 66596 departs at 08:45 (later than 06278's 08:15), so 66596 is recommended!
        rec2 = scan2["recommended_train"]
        assert rec2["train_no"] == "66596"
        assert "08:45" in scan2["recommendation_reason"]


def test_morning_scanner_recommends_salem_express_16212_for_12pm_shift():
    """
    USER REQUIREMENT TEST:
    'wHY IS sALEM yESVANTPUR NOT RECOMMENDED? i WANT TO LEAVE AS LATE AS POSSIBLE IN MORNING,
    AS MY SHIFT STARTS ONLY AT 12pm'

    When Train 16212 (Salem - Yesvantpur Express) departs Hosur at 08:54 AM (delay 24m)
    and reaches BLRR at 09:54 AM (ETV desk by 10:24 AM, 96 mins ahead of 12 PM shift),
    the scanner MUST recommend Train 16212 over 66596 (08:26 AM) and 06278 (07:07 AM)
    because it departs latest, maximizing sleep and home comfort!
    """
    with patch("rail_tracker.inspect_rake_turnaround") as mock_rake, patch("rail_tracker.get_live_train_status") as mock_status:
        mock_rake.return_value = {
            "morning_train": "66596",
            "incoming_rake_train": "66595",
            "scheduled_hsra_departure": "08:25",
            "projected_hsra_departure": "08:26",
            "effective_delay_mins": 1,
            "revised_step_out_time": "08:16",
            "is_delayed": True,
            "rake_cancelled": False,
            "rake_current_station": "HSRA",
            "rake_current_station_name": "HOSUR",
            "delay_summary": "1m late",
            "memu_status": {"stations": [{"code": "BLRR", "sta": "09:03", "eta": "09:08"}]},
        }

        mock_status.side_effect = lambda t, d=None: {
            "06278": {
                "train_no": "06278",
                "train_name": "Dharmapuri - KSR Bengaluru MEMU",
                "current_station": "HSRA",
                "current_station_name": "HOSUR",
                "delay_minutes": 0,
                "stations": [
                    {"code": "HSRA", "sta": "07:05", "std": "07:07", "eta": "07:07", "etd": "07:07", "has_arrived": False, "has_departed": False},
                    {"code": "BLRR", "sta": "07:51", "std": "07:52", "eta": "07:51", "etd": "07:52", "has_arrived": False, "has_departed": False},
                ],
            },
            "16212": {
                "train_no": "16212",
                "train_name": "Salem - Yesvantpur Express",
                "current_station": "KMLM",
                "current_station_name": "KELAMANGALAM",
                "delay_minutes": 24,
                "stations": [
                    {"code": "HSRA", "sta": "08:18", "std": "08:20", "eta": "08:52", "etd": "08:54", "has_arrived": False, "has_departed": False},
                    {"code": "BLRR", "sta": "08:59", "std": "09:00", "eta": "09:54", "etd": "09:55", "has_arrived": False, "has_departed": False},
                ],
            },
        }[t]

        scan = rail_tracker.scan_morning_commute_options(reference_time="08:00")
        assert len(scan["options"]) == 3

        # Train 16212 departs at 08:54 AM (later than 66596's 08:26 AM and 06278's 07:07 AM)
        rec = scan["recommended_train"]
        assert rec["train_no"] == "16212"
        assert rec["projected_departure"] == "08:54"
        assert rec["step_out_time"] == "08:44"
        assert rec["desk_eta"] == "10:24"
        assert "16212" in scan["recommendation_reason"]
        assert "sleep" in scan["recommendation_reason"].lower()
        assert "12:00 PM" in scan["recommendation_reason"]


def test_morning_scanner_filters_salem_express_if_delayed_past_cutoff():
    """
    If Train 16212 is severely delayed past the safety cutoff (Desk ETA > 11:30 AM),
    the scanner must filter it out and safely fall back to Train 66596!
    """
    with patch("rail_tracker.inspect_rake_turnaround") as mock_rake, patch("rail_tracker.get_live_train_status") as mock_status:
        mock_rake.return_value = {
            "morning_train": "66596",
            "incoming_rake_train": "66595",
            "scheduled_hsra_departure": "08:25",
            "projected_hsra_departure": "08:30",
            "effective_delay_mins": 5,
            "revised_step_out_time": "08:20",
            "is_delayed": True,
            "rake_cancelled": False,
            "rake_current_station": "HSRA",
            "rake_current_station_name": "HOSUR",
            "delay_summary": "5m late",
            "memu_status": {"stations": [{"code": "BLRR", "sta": "09:03", "eta": "09:15"}]},
        }

        mock_status.side_effect = lambda t, d=None: {
            "06278": {
                "train_no": "06278",
                "current_station": "SBC",
                "stations": [{"code": "HSRA", "std": "07:07", "etd": "07:07", "has_departed": True}],
            },
            "16212": {
                "train_no": "16212",
                "train_name": "Salem Express",
                "current_station": "SA",
                "delay_minutes": 180,
                # Projected to reach BLRR at 11:45 AM -> Desk ETA is 12:15 PM (past 11:30 cutoff!)
                "stations": [
                    {"code": "HSRA", "sta": "08:18", "std": "08:20", "eta": "10:45", "etd": "10:50", "has_arrived": False, "has_departed": False},
                    {"code": "BLRR", "sta": "08:59", "std": "09:00", "eta": "11:45", "etd": "11:46", "has_arrived": False, "has_departed": False},
                ],
            },
        }[t]

        scan = rail_tracker.scan_morning_commute_options(reference_time="08:00")
        rec = scan["recommended_train"]
        # Must fall back to 66596 because 16212 arrives after 11:30 AM!
        assert rec["train_no"] == "66596"
        assert rec["projected_departure"] == "08:30"


def test_rake_turnaround_location_physical_delay():
    """
    USER REQUIREMENT TEST:
    'send a message saying hey there is a delay, the train is stil at here, so possible delay.'
    
    If incoming rake 66595 is still physically at Banaswadi (BAND) at 07:50 AM,
    minimum run time from BAND to HSRA is 55 mins.
    Even if reported delay is only 5m, the physical arrival at Hosur cannot be before 08:45 AM!
    """
    with patch("rail_tracker.get_live_train_status") as mock_status:
        mock_status.side_effect = lambda t, d=None: {
            "66595": {
                "train_no": "66595",
                "current_station": "BAND",
                "current_station_name": "BANASWADI",
                "current_status": "Running 5 mins late",
                "delay_minutes": 5,
                "stations": [{"code": "HSRA", "sta": "08:00", "std": "Destination", "eta": "08:05", "has_arrived": False}],
            },
            "66596": {
                "train_no": "66596",
                "current_station": "HSRA",
                "current_station_name": "HOSUR",
                "delay_minutes": 0,
                "stations": [{"code": "HSRA", "sta": "Source", "std": "08:25"}],
            },
        }[t]

        rake_info = rail_tracker.inspect_rake_turnaround("66596", "66595", reference_time="07:50")
        assert rake_info["is_delayed"] is True
        # 07:50 + 55m min transit = 08:45 ETA at Hosur.
        # + 10m platform turnaround = 08:55 projected departure!
        assert rake_info["rake_eta_hsra"] == "08:45"
        assert rake_info["projected_hsra_departure"] == "08:55"
        assert rake_info["revised_step_out_time"] == "08:45"
        assert "still at BANASWADI (BAND)" in rake_info["delay_summary"]
        assert "Hey Sriram, there is a delay" in rake_info["delay_summary"]


def test_rake_cancelled_triggers_alternative_recommendation():
    """If incoming rake 66595 is cancelled or terminates short, scanner recommends alternative."""
    with patch("rail_tracker.get_live_train_status") as mock_status:
        mock_status.side_effect = lambda t, d=None: {
            "66595": {
                "train_no": "66595",
                "current_station": "AEK",
                "current_station_name": "ANEKAL ROAD",
                "current_status": "Terminated short at AEK due to track maintenance",
                "delay_minutes": 999,
                "stations": [{"code": "HSRA", "sta": "08:00", "std": "Destination", "eta": "CANCELLED"}],
            },
            "66596": {
                "train_no": "66596",
                "current_station": "HSRA",
                "current_station_name": "HOSUR",
                "delay_minutes": 0,
                "stations": [{"code": "HSRA", "sta": "Source", "std": "08:25"}],
            },
            "06278": {
                "train_no": "06278",
                "train_name": "Dharmapuri - KSR Bengaluru MEMU",
                "current_station": "KMLM",
                "current_station_name": "KELAMANGALAM",
                "delay_minutes": 65,
                "stations": [
                    {"code": "HSRA", "sta": "07:05", "std": "07:07", "eta": "08:12", "etd": "08:14", "has_arrived": False, "has_departed": False},
                    {"code": "BLRR", "sta": "07:51", "std": "07:52", "eta": "08:56", "etd": "08:57", "has_arrived": False, "has_departed": False},
                ],
            },
            "16212": {
                "train_no": "16212",
                "train_name": "Salem Express",
                "current_station": "HSRA",
                "current_station_name": "HOSUR",
                "delay_minutes": 0,
                "stations": [{"code": "HSRA", "sta": "08:18", "std": "08:20", "eta": "08:18", "etd": "08:20", "has_arrived": False, "has_departed": False}],
            },
        }[t]

        rake_info = rail_tracker.inspect_rake_turnaround("66596", "66595", reference_time="08:00")
        assert rake_info["rake_cancelled"] is True
        assert rake_info["projected_hsra_departure"] == "CANCELLED"

        scan = rail_tracker.scan_morning_commute_options(reference_time="08:00")
        rec = scan["recommended_train"]
        # Train 66596 is cancelled, so recommended train must be 06278 or 16212!
        assert rec["train_no"] in ("06278", "16212")
        assert "cancelled" in scan["recommendation_reason"].lower()


def test_watchdog_dispatch_via_daemon():
    """Verify that when watchdog fires, rail_daemon.step() detects and sends the Telegram alert."""
    daemon = rail_daemon.RailDaemon()
    daemon.bot.send_message = MagicMock()
    daemon.store.state_data["state"] = rail_daemon.STATE_MORNING_TRACKING

    # Trigger watchdog manually
    rail_tracker.watchdog.record_failure("66596", "Connection refused")
    alert = rail_tracker.watchdog.record_failure("66596", "Connection refused")
    assert alert is not None
    assert alert["triggered"] is True

    # Execute daemon step
    daemon.last_track_poll_time = 0.0  # Force tracking poll
    with patch("rail_tracker.scan_morning_commute_options") as mock_scan:
        mock_scan.return_value = {
            "options": [{"train_no": "66596", "train_name": "MEMU", "projected_departure": "08:25", "step_out_time": "08:15", "delay_mins": 0, "status": "VIABLE"}],
            "recommended_train": {"train_no": "66596", "train_name": "MEMU", "projected_departure": "08:25", "step_out_time": "08:15", "delay_mins": 0, "status": "VIABLE"},
            "rake_turnaround": {"incoming_rake_train": "66595", "rake_current_station": "HSRA", "rake_current_station_name": "HOSUR", "rake_delay_mins": 0},
        }
        weekday_morning = datetime(2026, 11, 16, 8, 0, 0, tzinfo=rail_daemon.IST_TZ)
        daemon.step(now=weekday_morning)

        # Bot must have dispatched the watchdog alert message!
        calls = [c[0][0] for c in daemon.bot.send_message.call_args_list]
        watchdog_msgs = [m for m in calls if "Watchdog Fail-Safe Triggered" in m]
        assert len(watchdog_msgs) >= 1
        assert "CRIS NTES" in watchdog_msgs[0]

    # Reset watchdog
    rail_tracker.watchdog.record_success()


def test_adaptive_polling_critical_window_persists_during_walk():
    """
    CRITICAL WINDOW FIX TEST:
    At 08:16 AM (after step-out 08:15 and before departure 08:25),
    determine_poll_interval must stay in POLL_TIER_CRITICAL (30s) so the user is actively tracked!
    """
    daemon = rail_daemon.RailDaemon()
    daemon.store.state_data["state"] = rail_daemon.STATE_MORNING_TRACKING
    daemon.store.state_data["morning_step_out_time"] = "08:15"
    daemon.store.state_data["morning_projected_dep"] = "08:25"

    # 1. 08:16 AM -> 1 minute after step-out, 9 minutes before departure -> CRITICAL
    assert daemon.determine_poll_interval("08:16") == rail_daemon.POLL_TIER_CRITICAL

    # 2. 08:24 AM -> 1 minute before departure -> CRITICAL
    assert daemon.determine_poll_interval("08:24") == rail_daemon.POLL_TIER_CRITICAL

    # 3. 08:28 AM -> 3 minutes after departure -> still in CRITICAL buffer
    assert daemon.determine_poll_interval("08:28") == rail_daemon.POLL_TIER_CRITICAL


def test_delay_decrease_train_made_up_time_alert():
    """Verify that when delay decreases, alert copy warns that departure moved earlier."""
    daemon = rail_daemon.RailDaemon()
    daemon.bot.send_message = MagicMock()
    daemon.store.state_data["state"] = rail_daemon.STATE_MORNING_TRACKING
    daemon.store.state_data["last_delay_reported"] = 20
    daemon.store.state_data["last_step_out_reported"] = "08:35"

    with patch("rail_tracker.scan_morning_commute_options") as mock_scan:
        mock_scan.return_value = {
            "options": [
                {
                    "train_no": "66596",
                    "train_name": "Hosur MEMU",
                    "projected_departure": "08:35",
                    "step_out_time": "08:25",
                    "dest_eta": "09:13",
                    "desk_eta": "09:43",
                    "delay_mins": 10,
                    "status": "VIABLE",
                }
            ],
            "recommended_train": {
                "train_no": "66596",
                "train_name": "Hosur MEMU",
                "projected_departure": "08:35",
                "step_out_time": "08:25",
                "dest_eta": "09:13",
                "desk_eta": "09:43",
                "delay_mins": 10,
                "status": "VIABLE",
            },
            "rake_turnaround": {
                "incoming_rake_train": "66595",
                "rake_current_station": "AEK",
                "rake_current_station_name": "ANEKAL ROAD",
                "rake_delay_mins": 10,
            },
        }

        # Delay dropped from 20 to 10 (made up 10 mins!)
        daemon.handle_morning_tracking("08:10")
        assert daemon.bot.send_message.called
        call_msg = daemon.bot.send_message.call_args[0][0]
        assert "made up *10 mins*" in call_msg
        assert "Prepare to leave sooner" in call_msg
        assert "extra" not in call_msg.lower()


def test_afternoon_tracking_switches_to_evening_tracking():
    """Tracking an evening train in the afternoon switches to EVENING_TRACKING, not MORNING_TRACKING."""
    daemon = rail_daemon.RailDaemon()
    daemon.bot.send_message = MagicMock()
    daemon.store.state_data["state"] = rail_daemon.STATE_MIDDAY_STANDBY

    # Track evening train 66585
    daemon.cmd_track("66585")
    assert daemon.store.state_data["evening_train"] == "66585"
    assert daemon.store.state_data["state"] == rail_daemon.STATE_EVENING_TRACKING
    assert daemon.store.state_data["morning_train"] == rail_tracker.MORNING_TRAIN_MEMU


def test_boarding_status_window():
    """At 08:22 AM (3 mins before 08:25 AM departure), status is BOARDING, not DEPARTED."""
    with patch("rail_tracker.inspect_rake_turnaround") as mock_rake, patch("rail_tracker.get_live_train_status") as mock_status:
        mock_rake.return_value = {
            "morning_train": "66596",
            "incoming_rake_train": "66595",
            "scheduled_hsra_departure": "08:25",
            "projected_hsra_departure": "08:25",
            "effective_delay_mins": 0,
            "revised_step_out_time": "08:15",
            "is_delayed": False,
            "rake_cancelled": False,
            "rake_current_station": "HSRA",
            "rake_current_station_name": "HOSUR",
            "delay_summary": "On time",
            "memu_status": {"stations": [{"code": "BLRR", "sta": "09:03", "eta": "09:03"}]},
        }

        mock_status.return_value = {
            "train_no": "16212",
            "current_station": "HSRA",
            "delay_minutes": 0,
            "stations": [{"code": "HSRA", "std": "08:20", "etd": "08:20", "has_departed": True}],
        }

        scan = rail_tracker.scan_morning_commute_options(reference_time="08:22")
        opt_66596 = next(o for o in scan["options"] if o["train_no"] == "66596")
        assert opt_66596["status"] == "BOARDING"
        assert scan["recommended_train"]["train_no"] == "66596"


def test_morning_prompt_strict_guard_at_midday():
    """CRITICAL TEST: Ensure handle_morning_prompt strictly refuses to fire at 12:29 PM (midday) or any non-morning time on weekdays."""
    daemon = rail_daemon.RailDaemon()
    daemon.bot.send_message = MagicMock()
    daemon.store.state_data["morning_prompt_sent"] = False

    weekday_dt = datetime(2026, 11, 16, 12, 29, 0, tzinfo=rail_daemon.IST_TZ)

    # 1. At 12:29 PM (the user's reported bug time), prompt must be strictly rejected
    daemon.handle_morning_prompt("12:29", now=weekday_dt)
    assert daemon.bot.send_message.call_count == 0, "Morning prompt must NEVER fire at 12:29 PM"
    assert daemon.store.state_data["state"] == rail_daemon.STATE_MIDDAY_STANDBY, "Must self-heal to MIDDAY_STANDBY"

    # 2. At 14:15 PM (afternoon), rejected and heals to EVENING_PROMPT
    daemon.handle_morning_prompt("14:15", now=datetime(2026, 11, 16, 14, 15, 0, tzinfo=rail_daemon.IST_TZ))
    assert daemon.bot.send_message.call_count == 0
    assert daemon.store.state_data["state"] == rail_daemon.STATE_EVENING_PROMPT

    # 3. At 18:00 PM (evening), rejected and heals to EVENING_TRACKING
    daemon.handle_morning_prompt("18:00", now=datetime(2026, 11, 16, 18, 0, 0, tzinfo=rail_daemon.IST_TZ))
    assert daemon.bot.send_message.call_count == 0
    assert daemon.store.state_data["state"] == rail_daemon.STATE_EVENING_TRACKING

    # 4. At 23:00 PM (late evening), rejected and heals to EVENING_TRACKING
    daemon.handle_morning_prompt("23:00", now=datetime(2026, 11, 16, 23, 0, 0, tzinfo=rail_daemon.IST_TZ))
    assert daemon.bot.send_message.call_count == 0
    assert daemon.store.state_data["state"] == rail_daemon.STATE_EVENING_TRACKING

    # 4b. At 23:45 PM (night past 23:30 cutoff), rejected and heals to NIGHT_SLEEP
    daemon.handle_morning_prompt("23:45", now=datetime(2026, 11, 16, 23, 45, 0, tzinfo=rail_daemon.IST_TZ))
    assert daemon.bot.send_message.call_count == 0
    assert daemon.store.state_data["state"] == rail_daemon.STATE_NIGHT_SLEEP

    # 5. At 07:00 AM (valid morning window on weekday), allowed to fire
    daemon.store.state_data["morning_prompt_sent"] = False
    with patch("rail_tracker.scan_morning_commute_options") as mock_scan:
        mock_scan.return_value = {
            "options": [{"train_no": "66596", "train_name": "MEMU", "scheduled_departure": "08:25", "projected_departure": "08:25", "dest_eta": "09:03", "delay_mins": 0, "is_delayed": False}],
            "recommended_train": {"train_no": "66596", "train_name": "Hosur MEMU"},
            "rake_turnaround": {"rake_current_station_name": "Yesvantpur Jn", "rake_delay_mins": 0},
            "recommendation_reason": "On time",
        }
        daemon.handle_morning_prompt("07:00", now=datetime(2026, 11, 16, 7, 0, 0, tzinfo=rail_daemon.IST_TZ))
        assert daemon.bot.send_message.call_count == 1
        assert daemon.store.state_data["morning_prompt_sent"] is True


def test_daemon_step_simulated_midday_heals_state():
    """Verify daemon.step() at 12:29 PM IST on a weekday transitions erroneous states to MIDDAY_STANDBY without firing morning prompt."""
    daemon = rail_daemon.RailDaemon()
    daemon.bot.send_message = MagicMock()
    daemon.bot.get_updates = MagicMock(return_value=[])
    daemon.store.state_data["state"] = rail_daemon.STATE_MORNING_PROMPT

    # Simulate 12:29 PM IST on a weekday (Monday Nov 16, 2026)
    simulated_midday = datetime(2026, 11, 16, 12, 29, 0, tzinfo=rail_daemon.IST_TZ)
    daemon.last_track_poll_time = 0.0

    daemon.step(now=simulated_midday)

    # State machine must auto-heal to MIDDAY_STANDBY and send zero messages
    assert daemon.store.state_data["state"] == rail_daemon.STATE_MIDDAY_STANDBY
    assert daemon.bot.send_message.call_count == 0


def test_cmd_track_at_midday_avoids_morning_tracking():
    """Verify tracking a morning train at 12:29 PM sets the train but preserves MIDDAY_STANDBY."""
    daemon = rail_daemon.RailDaemon()
    daemon.bot.send_message = MagicMock()
    daemon.store.state_data["state"] = rail_daemon.STATE_MIDDAY_STANDBY

    with patch("rail_daemon.get_ist_now") as mock_now:
        mock_now.return_value = datetime(2026, 11, 16, 12, 29, 0, tzinfo=rail_daemon.IST_TZ)
        daemon.cmd_track("66596")
        assert daemon.store.state_data["morning_train"] == "66596"
        assert daemon.store.state_data["state"] == rail_daemon.STATE_MIDDAY_STANDBY


def test_ist_timezone_conversion_from_utc():
    """Verify UTC 06:59 AM corresponds to IST 12:29 PM and prevents false morning trigger on UTC servers."""
    utc_dt = datetime(2026, 11, 15, 6, 59, 0, tzinfo=rail_daemon.timezone.utc)
    ist_dt = utc_dt.astimezone(rail_daemon.IST_TZ)
    assert ist_dt.strftime("%H:%M") == "12:29", "06:59 UTC must be 12:29 IST"


def test_morning_prompt_at_0935_heals_to_morning_tracking():
    """Verify handle_morning_prompt at 09:35 AM IST on weekday self-heals to MORNING_TRACKING without sending alert."""
    daemon = rail_daemon.RailDaemon()
    daemon.bot.send_message = MagicMock()
    daemon.store.state_data["morning_prompt_sent"] = False

    weekday_dt = datetime(2026, 11, 16, 9, 35, 0, tzinfo=rail_daemon.IST_TZ)
    daemon.handle_morning_prompt("09:35", now=weekday_dt)
    assert daemon.bot.send_message.call_count == 0
    assert daemon.store.state_data["state"] == rail_daemon.STATE_MORNING_TRACKING


def test_evening_prompt_and_tracking_guarded_at_midday():
    """Verify handle_evening_prompt and handle_evening_tracking reject execution at midday (12:29 PM)."""
    daemon = rail_daemon.RailDaemon()
    daemon.bot.send_message = MagicMock()
    weekday_dt = datetime(2026, 11, 16, 12, 29, 0, tzinfo=rail_daemon.IST_TZ)

    daemon.handle_evening_prompt("12:29", now=weekday_dt)
    assert daemon.bot.send_message.call_count == 0

    daemon.handle_evening_tracking("12:29", now=weekday_dt)
    assert daemon.bot.send_message.call_count == 0


def test_api_rail_status_ist_time():
    """Verify /api/rail/status returns current IST time regardless of local system timezone."""
    from fastapi.testclient import TestClient
    from api.index import app
    client = TestClient(app)

    with patch("api.index.get_ist_now") as mock_ist:
        mock_ist.return_value = datetime(2026, 11, 15, 12, 29, 0, tzinfo=rail_daemon.IST_TZ)
        res = client.get("/api/rail/status")
        assert res.status_code == 200
        data = res.json()
        assert data["current_time"] == "12:29"


# =============================================================================
# 12. WEEKEND REST & SECRET HYGIENE TESTS
# =============================================================================

def test_weekend_rest_state_transition():
    """Verify daemon.step() on Sunday/Saturday enters STATE_WEEKEND_REST and stays silent."""
    daemon = rail_daemon.RailDaemon()
    daemon.bot.send_message = MagicMock()
    daemon.bot.get_updates = MagicMock(return_value=[])
    daemon.store.state_data["state"] = rail_daemon.STATE_MORNING_PROMPT

    # Sunday, Nov 15, 2026 at 12:29 PM IST
    sunday_dt = datetime(2026, 11, 15, 12, 29, 0, tzinfo=rail_daemon.IST_TZ)
    daemon.last_track_poll_time = 0.0

    poll_interval = daemon.step(now=sunday_dt)

    assert daemon.store.state_data["state"] == rail_daemon.STATE_WEEKEND_REST
    assert daemon.bot.send_message.call_count == 0, "No notifications allowed on Sunday!"
    assert poll_interval == rail_daemon.POLL_TIER_STANDBY


def test_weekend_rest_suppresses_all_prompts_and_tracking():
    """Verify morning/evening prompts and tracking calls are strictly suppressed on weekends."""
    daemon = rail_daemon.RailDaemon()
    daemon.bot.send_message = MagicMock()
    sunday_dt = datetime(2026, 11, 15, 8, 0, 0, tzinfo=rail_daemon.IST_TZ)

    # 1. Morning prompt
    daemon.handle_morning_prompt("08:00", now=sunday_dt)
    assert daemon.bot.send_message.call_count == 0
    assert daemon.store.state_data["state"] == rail_daemon.STATE_WEEKEND_REST

    # 2. Morning tracking
    daemon.handle_morning_tracking("08:15", now=sunday_dt)
    assert daemon.bot.send_message.call_count == 0
    assert daemon.store.state_data["state"] == rail_daemon.STATE_WEEKEND_REST

    # 3. Evening prompt
    daemon.handle_evening_prompt("14:00", now=sunday_dt)
    assert daemon.bot.send_message.call_count == 0
    assert daemon.store.state_data["state"] == rail_daemon.STATE_WEEKEND_REST

    # 4. Evening tracking
    daemon.handle_evening_tracking("16:00", now=sunday_dt)
    assert daemon.bot.send_message.call_count == 0
    assert daemon.store.state_data["state"] == rail_daemon.STATE_WEEKEND_REST


def test_cmd_status_during_weekend_rest():
    """Verify /status during weekend rest clearly reports WEEKEND_REST with resume time."""
    daemon = rail_daemon.RailDaemon()
    daemon.bot.send_message = MagicMock()
    daemon.store.state_data["state"] = rail_daemon.STATE_WEEKEND_REST

    daemon.cmd_status()
    assert daemon.bot.send_message.call_count == 1
    call_text = daemon.bot.send_message.call_args[0][0]
    assert "Weekend Rest" in call_text
    assert "WEEKEND_REST" in call_text
    assert "Monday morning" in call_text


def test_cmd_reset_on_weekend():
    """Verify /reset on weekend initializes to STATE_WEEKEND_REST."""
    daemon = rail_daemon.RailDaemon()
    daemon.bot.send_message = MagicMock()

    with patch("rail_daemon.get_ist_now") as mock_now:
        mock_now.return_value = datetime(2026, 11, 15, 13, 0, 0, tzinfo=rail_daemon.IST_TZ)
        daemon.cmd_reset()
        assert daemon.store.state_data["state"] == rail_daemon.STATE_WEEKEND_REST
        assert "WEEKEND_REST" in daemon.bot.send_message.call_args[0][0]


def test_midday_morning_tracking_killswitch():
    """Ensure handle_morning_tracking at >= 09:40 strictly marks completed and transitions to MIDDAY_STANDBY."""
    daemon = rail_daemon.RailDaemon()
    daemon.bot.send_message = MagicMock()
    daemon.store.state_data["state"] = rail_daemon.STATE_MORNING_TRACKING
    weekday_midday = datetime(2026, 11, 16, 13, 0, 0, tzinfo=rail_daemon.IST_TZ)

    daemon.handle_morning_tracking("13:00", now=weekday_midday)
    assert daemon.store.state_data["morning_completed"] is True
    assert daemon.store.state_data["state"] == rail_daemon.STATE_MIDDAY_STANDBY
    assert daemon.bot.send_message.call_count == 0


def test_secrets_hygiene_no_hardcoded_tokens_in_code():
    """CRITICAL SECURITY TEST: Ensure no Telegram bot tokens are hardcoded in source code."""
    assert rail_daemon.DEFAULT_BOT_TOKEN == "", "DEFAULT_BOT_TOKEN must be empty string in version control"

    repo_files = [
        os.path.join(root_dir, "rail_daemon.py"),
        os.path.join(root_dir, "rail_tracker.py"),
        os.path.join(root_dir, "MEMORY.md"),
        os.path.join(root_dir, "RAIL_COMMUTE_README.md"),
    ]

    import re
    # Match any exposed bot token: 9-11 digits followed by colon and 35 alphanumeric/hyphen chars
    token_pattern = re.compile(r"\b\d{9,11}:[A-Za-z0-9_-]{35}\b")

    for file_path in repo_files:
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
                matches = token_pattern.findall(content)
                assert len(matches) == 0, f"Exposed token found in {file_path}: {matches}"


def test_monday_morning_boundary_transition_0644_to_0645():
    """Verify clean Monday morning transition from NIGHT_SLEEP directly into MORNING_PROMPT at 06:45 AM."""
    import time
    rail_tracker.watchdog.reset()
    daemon = rail_daemon.RailDaemon()
    daemon.bot.send_message = MagicMock()
    daemon.bot.get_updates = MagicMock(return_value=[])

    # 1. Monday at 06:44 AM (window not yet opened)
    monday_0644 = datetime(2026, 11, 16, 6, 44, 0, tzinfo=rail_daemon.IST_TZ)
    daemon.store.state_data["date"] = "2026-11-16"
    daemon.store.state_data["state"] = rail_daemon.STATE_NIGHT_SLEEP
    daemon.store.state_data["morning_prompt_sent"] = False
    daemon.last_track_poll_time = time.time() - 30

    interval_0644 = daemon.step(now=monday_0644)
    assert daemon.store.state_data["state"] == rail_daemon.STATE_NIGHT_SLEEP
    assert daemon.store.state_data["morning_prompt_sent"] is False
    assert daemon.bot.send_message.call_count == 0

    # 2. Monday at 06:45 AM (window opens!)
    monday_0645 = datetime(2026, 11, 16, 6, 45, 0, tzinfo=rail_daemon.IST_TZ)
    interval_0645 = daemon.step(now=monday_0645)

    assert daemon.store.state_data["state"] == rail_daemon.STATE_MORNING_PROMPT
    assert daemon.store.state_data["morning_prompt_sent"] is True, "Morning prompt must fire immediately at 06:45"
    assert daemon.bot.send_message.call_count == 1
    call_text = daemon.bot.send_message.call_args[0][0]
    assert "Good Morning Sriram" in call_text


def test_weekend_guards_when_now_is_none():
    """Verify weekend suppression works in daemon.step() when now argument is omitted (now=None)."""
    daemon = rail_daemon.RailDaemon()
    daemon.bot.send_message = MagicMock()
    daemon.bot.get_updates = MagicMock(return_value=[])
    sunday_dt = datetime(2026, 11, 15, 8, 30, 0, tzinfo=rail_daemon.IST_TZ)

    with patch("rail_daemon.get_ist_now", return_value=sunday_dt):
        poll = daemon.step() # No now argument provided!
        assert daemon.bot.send_message.call_count == 0
        assert daemon.store.state_data["state"] == rail_daemon.STATE_WEEKEND_REST
        assert poll == rail_daemon.POLL_TIER_STANDBY


def test_api_rail_status_enforces_weekend_rest():
    """Verify /api/rail/status strictly returns WEEKEND_REST on Saturday/Sunday even if cached state was weekday."""
    import asyncio
    from api.index import api_rail_status

    sunday_dt = datetime(2026, 11, 15, 12, 0, 0, tzinfo=rail_daemon.IST_TZ)
    with patch("api.index.get_ist_now", return_value=sunday_dt):
        with patch("api.index._fetch_supabase_commute_state", return_value={"date": "2026-11-15", "state": "MIDDAY_STANDBY"}):
            resp = asyncio.run(api_rail_status())
            import json
            data = json.loads(resp.body.decode("utf-8"))
            assert data["state"] == "WEEKEND_REST"


def test_minutes_difference_midnight_wraparound():
    """Verify minutes_difference handles day wraparounds across midnight cleanly and preserves wide daytime intervals."""
    # Crossing midnight forward (e.g. late night train arriving after midnight)
    assert rail_tracker.minutes_difference("23:50", "00:20") == 30
    assert rail_tracker.minutes_difference("23:30", "00:15") == 45
    assert rail_tracker.minutes_difference("22:50", "00:10") == 80

    # Crossing midnight backward
    assert rail_tracker.minutes_difference("00:20", "23:50") == -30
    assert rail_tracker.minutes_difference("00:15", "23:30") == -45

    # Same day normal differences
    assert rail_tracker.minutes_difference("08:15", "08:25") == 10
    assert rail_tracker.minutes_difference("08:25", "08:15") == -10

    # Wide daytime spans (>12 hours) must NOT be inverted to negative
    assert rail_tracker.minutes_difference("08:00", "21:15") == 795
    assert rail_tracker.minutes_difference("06:45", "22:00") == 915
    assert rail_tracker.minutes_difference("07:00", "20:00") == 780


def test_station_code_alias_resolution():
    """Verify STATION_CODE_ALIASES resolves long or colloquial station names to official IR codes."""
    raw_entry = {"SC": "", "SN": "Belandur Road", "STA": "08:59", "STD": "09:00"}
    norm = rail_tracker.normalize_station_entry(raw_entry)
    assert norm["code"] == "BLRR"

    raw_entry_crlm = {"SC": "CARMELARAM", "SN": "Carmelaram", "STA": "08:52", "STD": "08:53"}
    norm_crlm = rail_tracker.normalize_station_entry(raw_entry_crlm)
    assert norm_crlm["code"] == "CRLM"

    daemon = rail_daemon.RailDaemon()
    daemon.bot.send_message = MagicMock()
    daemon.cmd_station("bellandur")
    assert daemon.bot.send_message.called
    msg = daemon.bot.send_message.call_args[0][0]
    assert "Station Timetable: BLRR" in msg


def test_extreme_delay_past_cutoff_triggers_bike_or_wfh_warning():
    """When all morning trains are delayed past 11:30 AM desk cutoff, generate urgent warning."""
    with patch("rail_tracker.inspect_rake_turnaround") as mock_rake, patch("rail_tracker.get_live_train_status") as mock_status:
        mock_rake.return_value = {
            "morning_train": "66596",
            "incoming_rake_train": "66595",
            "scheduled_hsra_departure": "08:25",
            "projected_hsra_departure": "11:15",
            "effective_delay_mins": 170,
            "revised_step_out_time": "11:05",
            "is_delayed": True,
            "rake_cancelled": False,
            "rake_current_station": "BAND",
            "rake_current_station_name": "BANASWADI",
            "delay_summary": "170m delay",
            "memu_status": {"stations": [{"code": "BLRR", "sta": "09:03", "eta": "11:53"}]},
        }
        mock_status.side_effect = lambda t, d=None: {
            "06278": {
                "train_no": "06278",
                "train_name": "Dharmapuri MEMU",
                "current_station": "DPJ",
                "delay_minutes": 250,
                "stations": [
                    {"code": "HSRA", "sta": "07:05", "std": "07:07", "eta": "11:35", "etd": "11:37", "has_arrived": False, "has_departed": False},
                    {"code": "BLRR", "sta": "07:51", "std": "07:52", "eta": "12:15", "etd": "12:16", "has_arrived": False, "has_departed": False},
                ],
            },
            "16212": {
                "train_no": "16212",
                "train_name": "Salem Express",
                "current_station": "SA",
                "delay_minutes": 200,
                "stations": [
                    {"code": "HSRA", "sta": "08:18", "std": "08:20", "eta": "11:40", "etd": "11:42", "has_arrived": False, "has_departed": False},
                    {"code": "BLRR", "sta": "08:59", "std": "09:00", "eta": "12:20", "etd": "12:21", "has_arrived": False, "has_departed": False},
                ],
            },
        }[t]

        scan = rail_tracker.scan_morning_commute_options(reference_time="08:00")
        assert "WARNING: Severe delays" in scan["recommendation_reason"]
        assert "Bike / Cab" in scan["recommendation_reason"]
        assert "WFH" in scan["recommendation_reason"]


def test_telegram_client_markdown_resilience_retry():
    """Verify TelegramClient automatically retries sending as plain text when Markdown parsing fails."""
    import io
    import urllib.error

    client = rail_daemon.TelegramClient("test_token", "123456")

    error_resp = urllib.error.HTTPError(
        url="https://api.telegram.org/bottest_token/sendMessage",
        code=400,
        msg="Bad Request: can't parse entities in message text",
        hdrs={},
        fp=io.BytesIO(b'{"ok": false, "description": "Bad Request: can\'t parse entities"}'),
    )

    success_resp = MagicMock()
    success_resp.read.return_value = json.dumps({"ok": True, "result": {"message_id": 999}}).encode("utf-8")
    success_resp.__enter__.return_value = success_resp

    with patch.object(rail_daemon.TelegramClient, "send_message", rail_daemon.TelegramClient._real_send_message):
        with patch("urllib.request.urlopen", side_effect=[error_resp, success_resp]) as mock_urlopen:
            res = client.send_message("Unclosed *markdown test [with error", parse_mode="Markdown", is_direct_reply=True)
            assert res is not None
            assert res.get("message_id") == 999
            assert mock_urlopen.call_count == 2
            first_payload = json.loads(mock_urlopen.call_args_list[0][0][0].data.decode("utf-8"))
            second_payload = json.loads(mock_urlopen.call_args_list[1][0][0].data.decode("utf-8"))
            assert first_payload.get("parse_mode") == "Markdown"
            assert "parse_mode" not in second_payload


def test_api_rail_action_smart_direction_and_reset():
    """Verify /api/rail/action correctly tracks evening trains during midday and initializes reset state."""
    import asyncio
    from api.index import api_rail_action
    from starlette.requests import Request

    async def _run():
        scope = {"type": "http", "method": "POST", "headers": []}

        # 1. Select evening train 16232 at 16:00
        req_16232 = Request(scope)
        req_16232._json = {"action": "select_train", "train_no": "16232"}
        with patch("api.index.get_ist_now", return_value=datetime(2026, 11, 16, 16, 0, 0, tzinfo=rail_daemon.IST_TZ)):
            resp = await api_rail_action(req_16232)
            data = json.loads(resp.body.decode("utf-8"))
            assert data["state"]["state"] == rail_daemon.STATE_EVENING_TRACKING
            assert data["state"]["evening_train"] == "16232"

        # 2. Reset at 08:30 AM should initialize to MORNING_TRACKING, not NIGHT_SLEEP
        req_reset = Request(scope)
        req_reset._json = {"action": "reset"}
        with patch("api.index.get_ist_now", return_value=datetime(2026, 11, 16, 8, 30, 0, tzinfo=rail_daemon.IST_TZ)):
            resp = await api_rail_action(req_reset)
            data = json.loads(resp.body.decode("utf-8"))
            assert data["state"]["state"] == rail_daemon.STATE_MORNING_TRACKING

    asyncio.run(_run())


def test_scan_morning_commute_effective_delay_flag():
    """Verify Train 16212 sets is_delayed=True and correct delay note when physical transit lag applies."""
    with patch("rail_tracker.inspect_rake_turnaround") as mock_rake, patch("rail_tracker.get_live_train_status") as mock_status:
        mock_rake.return_value = {
            "morning_train": "66596",
            "incoming_rake_train": "66595",
            "scheduled_hsra_departure": "08:25",
            "projected_hsra_departure": "08:25",
            "effective_delay_mins": 0,
            "revised_step_out_time": "08:15",
            "is_delayed": False,
            "rake_cancelled": False,
            "rake_current_station": "HSRA",
            "rake_current_station_name": "HOSUR",
            "delay_summary": "On time",
            "memu_status": {"stations": [{"code": "BLRR", "sta": "09:03", "eta": "09:03"}]},
        }
        mock_status.side_effect = lambda t, d=None: {
            "06278": {
                "train_no": "06278",
                "train_name": "Dharmapuri MEMU",
                "current_station": "HSRA",
                "delay_minutes": 0,
                "stations": [
                    {"code": "HSRA", "sta": "07:05", "std": "07:07", "eta": "07:05", "etd": "07:07", "has_arrived": True, "has_departed": True},
                    {"code": "BLRR", "sta": "07:51", "std": "07:52", "eta": "07:51", "etd": "07:52", "has_arrived": True, "has_departed": True},
                ],
            },
            "16212": {
                "train_no": "16212",
                "train_name": "Salem Express",
                # Train reported 0 delay by NTES, but is physically still at DPJ (50m from Hosur) at 08:00 AM
                "current_station": "DPJ",
                "current_station_name": "DHARMAPURI",
                "delay_minutes": 0,
                "stations": [
                    {"code": "HSRA", "sta": "08:18", "std": "08:20", "eta": "08:18", "etd": "08:20", "has_arrived": False, "has_departed": False},
                    {"code": "BLRR", "sta": "08:59", "std": "09:00", "eta": "08:59", "etd": "09:00", "has_arrived": False, "has_departed": False},
                ],
            },
        }[t]

        scan = rail_tracker.scan_morning_commute_options(reference_time="08:00")
        exp_opt = next(o for o in scan["options"] if o["train_no"] == "16212")
        # Physical transit: 08:00 + 50m + 2m buffer = 08:52 departure -> +32m delay vs 08:20 schedule
        assert exp_opt["is_delayed"] is True
        assert exp_opt["effective_delay_mins"] == 32
        assert "Delay: 32m" in exp_opt["details"]


def test_rail_daemon_evening_tracking_extended_to_2330():
    """Verify evening tracking remains active past 22:30 up to 23:30 to cover late trains (e.g. 16236)."""
    import tempfile
    import uuid
    daemon = rail_daemon.RailDaemon(store=rail_daemon.CommuteStateStore(file_path=os.path.join(tempfile.gettempdir(), f"test_ev_{uuid.uuid4().hex}.json")))
    daemon.bot.send_message = MagicMock()

    # 1. At 22:45 IST on a weekday (Monday), state should remain EVENING_TRACKING, not NIGHT_SLEEP
    now_2245 = datetime(2026, 11, 16, 22, 45, 0, tzinfo=rail_daemon.IST_TZ)
    daemon.store.state_data["state"] = rail_daemon.STATE_EVENING_TRACKING
    daemon.store.state_data["date"] = "2026-11-16"
    daemon.store.state_data["evening_train"] = "16236"
    with patch("rail_tracker.get_live_train_status") as mock_status:
        mock_status.return_value = {
            "train_no": "16236",
            "current_station": "CRLM",
            "delay_minutes": 10,
            "stations": [
                {"code": "CRLM", "sta": "21:50", "eta": "22:00", "has_departed": False},
                {"code": "HSRA", "sta": "22:50", "eta": "23:00", "has_departed": False},
            ],
        }
        interval = daemon.step(now=now_2245)
        assert daemon.store.state_data["state"] == rail_daemon.STATE_EVENING_TRACKING

    # 2. At 23:35 IST, state cleanly transitions to STATE_NIGHT_SLEEP
    now_2335 = datetime(2026, 11, 16, 23, 35, 0, tzinfo=rail_daemon.IST_TZ)
    interval_night = daemon.step(now=now_2335)
    assert daemon.store.state_data["state"] == rail_daemon.STATE_NIGHT_SLEEP
    assert interval_night == rail_daemon.POLL_TIER_HIBERNATE


# =============================================================================
# BACKTEST VERIFICATION SUITE: 8 COMPREHENSIVE DEFECT AUDIT PATCHES
# =============================================================================

def test_patch3_minutes_difference_overnight_and_wide_spans():
    """Verify minutes_difference overnight wrap and wide daytime intervals."""
    # 1. Midnight forward
    assert rail_tracker.minutes_difference("23:50", "00:20") == 30
    # 2. Midnight reverse
    assert rail_tracker.minutes_difference("00:20", "23:50") == -30
    # 3. Wide daytime span: 04:00 to 20:00 must be +960 mins, NOT -480 mins
    assert rail_tracker.minutes_difference("04:00", "20:00") == 960
    assert rail_tracker.minutes_difference("03:00", "22:00") == 1140
    # 4. Wide overnight span: 00:15 to 23:45 is -30 mins (yesterday's train)
    assert rail_tracker.minutes_difference("00:15", "23:45") == -30


def test_patch1_scan_morning_commute_two_stage_tiering():
    """Verify 2-Stage Tiering: Tier 1 (<= 11:30), Tier 2 (<= 12:00), and Fallback to earliest arrival."""
    # Scenario A: Tier 1 (all trains reach desk before 11:30 AM cutoff)
    with patch("rail_tracker.inspect_rake_turnaround") as mock_rake, patch("rail_tracker.get_live_train_status") as mock_status:
        mock_rake.return_value = {
            "morning_train": "66596",
            "incoming_rake_train": "66595",
            "scheduled_hsra_departure": "08:25",
            "projected_hsra_departure": "08:25",
            "effective_delay_mins": 0,
            "revised_step_out_time": "08:15",
            "is_delayed": False,
            "rake_cancelled": False,
            "rake_current_station": "HSRA",
            "rake_current_station_name": "HOSUR",
            "delay_summary": "On time",
            "memu_has_departed": False,
            "memu_status": {"stations": [{"code": "BLRR", "sta": "09:03", "eta": "09:03"}]},
        }
        mock_status.side_effect = lambda t, d=None: {
            "06278": {
                "train_no": "06278",
                "train_name": "Dharmapuri MEMU",
                "current_station": "HSRA",
                "delay_minutes": 0,
                "stations": [
                    {"code": "HSRA", "sta": "07:05", "std": "07:07", "eta": "07:05", "etd": "07:07", "has_arrived": True, "has_departed": True},
                    {"code": "BLRR", "sta": "07:51", "std": "07:52", "eta": "07:51", "etd": "07:52", "has_arrived": True, "has_departed": True},
                ],
            },
            "16212": {
                "train_no": "16212",
                "train_name": "Salem Express",
                "current_station": "HSRA",
                "delay_minutes": 0,
                "stations": [
                    {"code": "HSRA", "sta": "08:18", "std": "08:20", "eta": "08:18", "etd": "08:20", "has_arrived": False, "has_departed": False},
                    {"code": "BLRR", "sta": "08:59", "std": "09:00", "eta": "08:59", "etd": "09:00", "has_arrived": False, "has_departed": False},
                ],
            },
        }[t]

        scan = rail_tracker.scan_morning_commute_options(reference_time="08:00")
        # 66596 departs 08:25 (desk 09:33), 16212 departs 08:20 (desk 09:29) -> 66596 is latest departure in Tier 1
        assert scan["recommended_train"]["train_no"] == "66596"
        assert "comfortably ahead of your 12:00 PM shift cutoff" in scan["recommendation_reason"]

    # Scenario B: Tier 2 (delays breach 11:30 buffer, but trains arrive before 12:00 PM hard start)
    with patch("rail_tracker.inspect_rake_turnaround") as mock_rake, patch("rail_tracker.get_live_train_status") as mock_status:
        mock_rake.return_value = {
            "morning_train": "66596",
            "incoming_rake_train": "66595",
            "scheduled_hsra_departure": "08:25",
            "projected_hsra_departure": "10:30",
            "effective_delay_mins": 125,
            "revised_step_out_time": "10:20",
            "is_delayed": True,
            "rake_cancelled": False,
            "rake_current_station": "CRLM",
            "rake_current_station_name": "CARMELARAM",
            "delay_summary": "Delayed",
            "memu_has_departed": False,
            # Desk ETA = 11:08 + 30 = 11:38 AM (Tier 2: > 11:30, <= 12:00)
            "memu_status": {"stations": [{"code": "BLRR", "sta": "09:03", "eta": "11:08"}]},
        }
        mock_status.side_effect = lambda t, d=None: {
            "06278": {
                "train_no": "06278",
                "train_name": "Dharmapuri MEMU",
                "current_station": "HSRA",
                "delay_minutes": 200,
                # Desk ETA = 11:15 + 30 = 11:45 AM (Tier 2: > 11:30, <= 12:00)
                "stations": [
                    {"code": "HSRA", "sta": "07:05", "std": "07:07", "eta": "10:25", "etd": "10:27", "has_arrived": False, "has_departed": False},
                    {"code": "BLRR", "sta": "07:51", "std": "07:52", "eta": "11:15", "etd": "11:16", "has_arrived": False, "has_departed": False},
                ],
            },
            "16212": {
                "train_no": "16212",
                "train_name": "Salem Express",
                "current_station": "DPJ",
                "delay_minutes": 180,
                # Desk ETA = 11:20 + 30 = 11:50 AM (Tier 2: > 11:30, <= 12:00)
                "stations": [
                    {"code": "HSRA", "sta": "08:18", "std": "08:20", "eta": "10:35", "etd": "10:37", "has_arrived": False, "has_departed": False},
                    {"code": "BLRR", "sta": "08:59", "std": "09:00", "eta": "11:20", "etd": "11:21", "has_arrived": False, "has_departed": False},
                ],
            },
        }[t]

        scan = rail_tracker.scan_morning_commute_options(reference_time="08:00")
        # All 3 trains in Tier 2; latest departure is 16212 at 10:37 AM
        assert scan["recommended_train"]["train_no"] == "16212"
        assert "CAUTION: Corridor delays have breached the 11:30 AM buffer" in scan["recommendation_reason"]
        assert "reaching before your 12:00 PM shift start" in scan["recommendation_reason"]

    # Scenario C: Severe delays past 12:00 PM -> selects earliest arrival
    with patch("rail_tracker.inspect_rake_turnaround") as mock_rake, patch("rail_tracker.get_live_train_status") as mock_status:
        mock_rake.return_value = {
            "morning_train": "66596",
            "incoming_rake_train": "66595",
            "scheduled_hsra_departure": "08:25",
            "projected_hsra_departure": "11:45",
            "effective_delay_mins": 200,
            "revised_step_out_time": "11:35",
            "is_delayed": True,
            "rake_cancelled": False,
            "rake_current_station": "CRLM",
            "rake_current_station_name": "CARMELARAM",
            "delay_summary": "Severe delay",
            "memu_has_departed": False,
            # Desk ETA = 12:23 PM (past 12:00 PM)
            "memu_status": {"stations": [{"code": "BLRR", "sta": "09:03", "eta": "11:53"}]},
        }
        mock_status.side_effect = lambda t, d=None: {
            "06278": {
                "train_no": "06278",
                "train_name": "Dharmapuri MEMU",
                "current_station": "DPJ",
                "delay_minutes": 250,
                # Desk ETA = 12:45 PM
                "stations": [
                    {"code": "HSRA", "sta": "07:05", "std": "07:07", "eta": "11:35", "etd": "11:37", "has_arrived": False, "has_departed": False},
                    {"code": "BLRR", "sta": "07:51", "std": "07:52", "eta": "12:15", "etd": "12:16", "has_arrived": False, "has_departed": False},
                ],
            },
            "16212": {
                "train_no": "16212",
                "train_name": "Salem Express",
                "current_station": "SA",
                "delay_minutes": 200,
                # Desk ETA = 12:50 PM
                "stations": [
                    {"code": "HSRA", "sta": "08:18", "std": "08:20", "eta": "11:40", "etd": "11:42", "has_arrived": False, "has_departed": False},
                    {"code": "BLRR", "sta": "08:59", "std": "09:00", "eta": "12:20", "etd": "12:21", "has_arrived": False, "has_departed": False},
                ],
            },
        }[t]

        scan = rail_tracker.scan_morning_commute_options(reference_time="08:00")
        # Must pick 16212 (earliest arriving among severe delay options)
        assert scan["recommended_train"]["train_no"] == "16212"
        assert "WARNING: Severe delays across all corridor trains" in scan["recommendation_reason"]
        assert "Bike / Cab" in scan["recommendation_reason"]


def test_patch2_train_16212_no_time_machine_destination_eta():
    """Verify Train 16212 computes dest_eta using exp_effective_delay, preventing time machine arrivals."""
    with patch("rail_tracker.inspect_rake_turnaround") as mock_rake, patch("rail_tracker.get_live_train_status") as mock_status:
        mock_rake.return_value = {
            "morning_train": "66596",
            "incoming_rake_train": "66595",
            "scheduled_hsra_departure": "08:25",
            "projected_hsra_departure": "08:25",
            "effective_delay_mins": 0,
            "revised_step_out_time": "08:15",
            "is_delayed": False,
            "rake_cancelled": False,
            "rake_current_station": "HSRA",
            "rake_current_station_name": "HOSUR",
            "delay_summary": "On time",
            "memu_has_departed": False,
            "memu_status": {"stations": [{"code": "BLRR", "sta": "09:03", "eta": "09:03"}]},
        }
        mock_status.side_effect = lambda t, d=None: {
            "06278": {
                "train_no": "06278",
                "train_name": "Dharmapuri MEMU",
                "current_station": "HSRA",
                "delay_minutes": 0,
                "stations": [
                    {"code": "HSRA", "sta": "07:05", "std": "07:07", "eta": "07:05", "etd": "07:07", "has_arrived": True, "has_departed": True},
                    {"code": "BLRR", "sta": "07:51", "std": "07:52", "eta": "07:51", "etd": "07:52", "has_arrived": True, "has_departed": True},
                ],
            },
            "16212": {
                "train_no": "16212",
                "train_name": "Salem Express",
                # Upstream delay reported as 0, but train is physically at DPJ at 08:00 AM
                # Transit: 50m + 2m = 52m -> Projected Hosur Dep: 08:52 AM -> Effective Delay: +32m
                "current_station": "DPJ",
                "current_station_name": "DHARMAPURI",
                "delay_minutes": 0,
                "stations": [
                    {"code": "HSRA", "sta": "08:18", "std": "08:20", "eta": "08:18", "etd": "08:20", "has_arrived": False, "has_departed": False},
                    {"code": "BLRR", "sta": "08:59", "std": "09:00", "eta": "08:59", "etd": "09:00", "has_arrived": False, "has_departed": False},
                ],
            },
        }[t]

        scan = rail_tracker.scan_morning_commute_options(reference_time="08:00")
        exp_opt = next(o for o in scan["options"] if o["train_no"] == "16212")

        # Projected departure: 08:52 AM
        assert exp_opt["projected_departure"] == "08:52"
        # Destination ETA at BLRR must be 08:59 + 32m = 09:31 AM (NOT 08:59 AM!)
        assert exp_opt["dest_eta"] == "09:31"
        assert exp_opt["dest_eta"] > exp_opt["projected_departure"], "Arrival must occur AFTER departure!"
        # Desk ETA = 09:31 + 30m = 10:01 AM
        assert exp_opt["desk_eta"] == "10:01"


def test_patch4_safe_etd_resolution_none_and_whitespace():
    """Verify safe etd resolution handles None, whitespace, and 'Destination' without crashing."""
    with patch("rail_tracker.inspect_rake_turnaround") as mock_rake, patch("rail_tracker.get_live_train_status") as mock_status:
        mock_rake.return_value = {
            "morning_train": "66596",
            "incoming_rake_train": "66595",
            "scheduled_hsra_departure": "08:25",
            "projected_hsra_departure": "08:35",
            "effective_delay_mins": 10,
            "revised_step_out_time": "08:25",
            "is_delayed": True,
            "rake_cancelled": False,
            "rake_current_station": "HSRA",
            "rake_current_station_name": "HOSUR",
            "delay_summary": "Turnaround delay",
            "memu_has_departed": False,
            "memu_status": {"stations": [{"code": "BLRR", "sta": "09:03", "eta": "09:13"}]},
        }
        mock_status.side_effect = lambda t, d=None: {
            "06278": {
                "train_no": "06278",
                "train_name": "Dharmapuri MEMU",
                "current_station": "HSRA",
                "delay_minutes": 15,
                "stations": [
                    # etd is explicitly None
                    {"code": "HSRA", "sta": "07:05", "std": "07:07", "eta": "07:20", "etd": None, "has_arrived": False, "has_departed": False},
                    {"code": "BLRR", "sta": "07:51", "std": "07:52", "eta": "08:06", "etd": None, "has_arrived": False, "has_departed": False},
                ],
            },
            "16212": {
                "train_no": "16212",
                "train_name": "Salem Express",
                "current_station": "HSRA",
                "delay_minutes": 20,
                "stations": [
                    # etd is whitespace
                    {"code": "HSRA", "sta": "08:18", "std": "08:20", "eta": "08:38", "etd": "   ", "has_arrived": False, "has_departed": False},
                    {"code": "BLRR", "sta": "08:59", "std": "09:00", "eta": "09:19", "etd": "Destination", "has_arrived": False, "has_departed": False},
                ],
            },
        }[t]

        scan = rail_tracker.scan_morning_commute_options(reference_time="07:00")
        memu2 = next(o for o in scan["options"] if o["train_no"] == "06278")
        exp = next(o for o in scan["options"] if o["train_no"] == "16212")

        # 07:07 + 15m = 07:22
        assert memu2["projected_departure"] == "07:22"
        # 08:20 + 20m = 08:40
        assert exp["projected_departure"] == "08:40"


def test_patch5_train_66596_has_departed_flag():
    """Verify Train 66596 marks has_departed and sets DEPARTED status when it leaves Hosur."""
    with patch("rail_tracker.inspect_rake_turnaround") as mock_rake, patch("rail_tracker.get_live_train_status") as mock_status:
        mock_rake.return_value = {
            "morning_train": "66596",
            "incoming_rake_train": "66595",
            "scheduled_hsra_departure": "08:25",
            "projected_hsra_departure": "08:25",
            "effective_delay_mins": 0,
            "revised_step_out_time": "08:15",
            "is_delayed": False,
            "rake_cancelled": False,
            "rake_current_station": "AEK",
            "rake_current_station_name": "ANEKAL ROAD",
            "delay_summary": "Departed Hosur",
            "memu_has_departed": True,
            "memu_status": {"stations": [{"code": "BLRR", "sta": "09:03", "eta": "09:03"}]},
        }
        mock_status.side_effect = lambda t, d=None: {
            "06278": {
                "train_no": "06278",
                "train_name": "Dharmapuri MEMU",
                "current_station": "BLRR",
                "delay_minutes": 0,
                "stations": [
                    {"code": "HSRA", "sta": "07:05", "std": "07:07", "eta": "07:05", "etd": "07:07", "has_arrived": True, "has_departed": True},
                ],
            },
            "16212": {
                "train_no": "16212",
                "train_name": "Salem Express",
                "current_station": "HSRA",
                "delay_minutes": 0,
                "stations": [
                    {"code": "HSRA", "sta": "08:18", "std": "08:20", "eta": "08:30", "etd": "08:32", "has_arrived": False, "has_departed": False},
                    {"code": "BLRR", "sta": "08:59", "std": "09:00", "eta": "09:11", "etd": "09:12", "has_arrived": False, "has_departed": False},
                ],
            },
        }[t]

        scan = rail_tracker.scan_morning_commute_options(reference_time="08:28")
        memu_opt = next(o for o in scan["options"] if o["train_no"] == "66596")
        assert memu_opt["status"] == "DEPARTED"
        # Since 66596 departed, recommended train must be 16212
        assert scan["recommended_train"]["train_no"] == "16212"


def test_patch6_api_overnight_default_and_reached_action():
    """Verify API overnight status defaults to NIGHT_SLEEP and evening reached transitions to HIBERNATION."""
    import asyncio
    from api.index import _build_offline_rail_status, api_rail_action

    # 1. Overnight offline status defaults to NIGHT_SLEEP
    st_0200 = _build_offline_rail_status("02:00", {})
    assert st_0200["state"] == "NIGHT_SLEEP"

    st_2345 = _build_offline_rail_status("23:45", {})
    assert st_2345["state"] == "NIGHT_SLEEP"

    # 2. Daytime offline status defaults to STANDBY
    st_1200 = _build_offline_rail_status("12:00", {})
    assert st_1200["state"] == "STANDBY"

    # 3. Action reached in the evening transitions to HIBERNATION
    async def _test_actions():
        from unittest.mock import AsyncMock
        # Mock request for evening reached
        mock_req_evening = MagicMock()
        mock_req_evening.json = AsyncMock(return_value={"action": "reached"})
        with patch("api.index.get_ist_now") as mock_now, patch("api.index._fetch_supabase_commute_state", return_value={"state": "EVENING_TRACKING"}):
            mock_now.return_value = datetime(2026, 11, 16, 20, 0, 0, tzinfo=rail_daemon.IST_TZ)
            resp = await api_rail_action(mock_req_evening)
            body = json.loads(resp.body.decode("utf-8"))
            assert body["state"]["state"] == rail_daemon.STATE_HIBERNATION
            assert body["state"]["evening_completed"] is True
            assert "Evening commute completed" in body["message"]

        # Mock request for morning reached
        mock_req_morning = MagicMock()
        mock_req_morning.json = AsyncMock(return_value={"action": "reached"})
        with patch("api.index.get_ist_now") as mock_now, patch("api.index._fetch_supabase_commute_state", return_value={"state": "MORNING_TRACKING"}):
            mock_now.return_value = datetime(2026, 11, 16, 9, 15, 0, tzinfo=rail_daemon.IST_TZ)
            resp = await api_rail_action(mock_req_morning)
            body = json.loads(resp.body.decode("utf-8"))
            assert body["state"]["state"] == rail_daemon.STATE_MIDDAY_STANDBY
            assert body["state"]["morning_completed"] is True

    asyncio.run(_test_actions())


def test_patch7_telegram_action_stay_handler_and_milestones():
    """Verify action:stay transitions daemon to STATE_HIBERNATION and milestone_station is set."""
    # 1. Timetable milestones
    assert rail_tracker.CORRIDOR_SCHEDULES["66585"]["milestone_station"] == "BYPL"
    assert rail_tracker.CORRIDOR_SCHEDULES["66583"]["milestone_station"] == "BYPL"

    # 2. Daemon telegram action:stay
    import tempfile
    import uuid
    daemon = rail_daemon.RailDaemon(store=rail_daemon.CommuteStateStore(file_path=os.path.join(tempfile.gettempdir(), f"test_stay_{uuid.uuid4().hex}.json")))
    daemon.bot.send_message = MagicMock()
    daemon.bot.answer_callback = MagicMock()

    stay_update = {
        "update_id": 9999,
        "callback_query": {
            "id": "cb_stay_1",
            "data": "action:stay",
            "message": {"chat": {"id": 123456}},
        },
    }
    with patch.object(daemon.bot, "get_updates", return_value=[stay_update]):
        daemon.process_telegram_updates()
        assert daemon.store.state_data["state"] == rail_daemon.STATE_HIBERNATION
        assert daemon.bot.send_message.call_count == 1
        msg = daemon.bot.send_message.call_args[0][0]
        assert "Staying late confirmed" in msg


def test_patch8_supabase_sync_safe_dict_access_with_empty_state(guard_supabase_sync, monkeypatch):
    """Verify _sync_to_supabase does not raise KeyError when state_data has missing or empty keys."""
    import tempfile
    import uuid

    store = rail_daemon.CommuteStateStore(file_path=os.path.join(tempfile.gettempdir(), f"test_sb_{uuid.uuid4().hex}.json"))
    store.state_data = {}  # Empty state dict

    mock_url = MagicMock()
    monkeypatch.setattr(rail_daemon, "SUPABASE_URL", "https://mock.supabase.co")
    monkeypatch.setattr(rail_daemon, "SUPABASE_KEY", "mock_key")
    monkeypatch.setattr(rail_daemon.urllib.request, "urlopen", mock_url)

    # Invoke the actual _sync_to_supabase implementation saved on the guard fixture
    guard_supabase_sync._original(store)
    assert mock_url.call_count == 1
    req = mock_url.call_args[0][0]
    payload = json.loads(req.data.decode("utf-8"))
    assert payload["morning_train"] == "66596"
    assert payload["state"] == rail_daemon.STATE_MIDDAY_STANDBY
    assert payload["morning_status"] == "ACTIVE"


# =============================================================================
# EXTENDED AUDIT BACKTESTS: TIME NORMALIZATION, TIE-BREAKING, AND SAFE RESOLUTION
# =============================================================================

def test_clean_time_str_unpadded_and_single_digits():
    """Verify clean_time_str parses single-digit hours/minutes and normalizes to HH:MM."""
    assert rail_tracker.clean_time_str("7:5") == "07:05"
    assert rail_tracker.clean_time_str("7:5 13-Nov") == "07:05"
    assert rail_tracker.clean_time_str("7:05") == "07:05"
    assert rail_tracker.clean_time_str("07:5") == "07:05"
    assert rail_tracker.clean_time_str("08:25:00") == "08:25"
    assert rail_tracker.clean_time_str("Source") == "Source"
    assert rail_tracker.clean_time_str(None) == ""
    assert rail_tracker.clean_time_str("") == ""
    # add_minutes_to_time works seamlessly on unpadded inputs with date suffixes
    assert rail_tracker.add_minutes_to_time("7:5 13-Nov", 15) == "07:20"


def test_format_ampm_distinction():
    """Verify format_ampm handles morning, midday, afternoon, and midnight correctly."""
    assert rail_tracker.format_ampm("08:25") == "08:25 AM"
    assert rail_tracker.format_ampm("11:30") == "11:30 AM"
    assert rail_tracker.format_ampm("12:00") == "12:00 PM"
    assert rail_tracker.format_ampm("12:15") == "12:15 PM"
    assert rail_tracker.format_ampm("15:30") == "15:30 PM"
    assert rail_tracker.format_ampm("00:15") == "00:15 AM"
    assert rail_tracker.format_ampm("") == ""


def test_tier_tie_breaking_picks_earlier_desk_arrival():
    """Verify that when two trains have identical departure times, the one with earlier desk ETA is selected."""
    with patch("rail_tracker.inspect_rake_turnaround") as mock_rake, patch("rail_tracker.get_live_train_status") as mock_status:
        mock_rake.return_value = {
            "morning_train": "66596",
            "incoming_rake_train": "66595",
            "scheduled_hsra_departure": "08:25",
            "projected_hsra_departure": "08:25",
            "effective_delay_mins": 0,
            "revised_step_out_time": "08:15",
            "is_delayed": False,
            "rake_cancelled": False,
            "rake_current_station": "HSRA",
            "rake_current_station_name": "HOSUR",
            "delay_summary": "On time",
            "memu_has_departed": False,
            "memu_status": {"stations": [{"code": "BLRR", "sta": "09:10", "eta": "09:10"}]},  # desk eta 09:40
        }
        mock_status.side_effect = lambda t, d=None: {
            "06278": {
                "train_no": "06278",
                "train_name": "Dharmapuri MEMU",
                "current_station": "HSRA",
                "delay_minutes": 0,
                "stations": [
                    {"code": "HSRA", "sta": "07:05", "std": "07:07", "eta": "07:05", "etd": "07:07", "has_arrived": True, "has_departed": True},
                    {"code": "BLRR", "sta": "07:51", "std": "07:52", "eta": "07:51", "etd": "07:52", "has_arrived": True, "has_departed": True},
                ],
            },
            "16212": {
                "train_no": "16212",
                "train_name": "Salem Express",
                "current_station": "HSRA",
                "delay_minutes": 5,
                "stations": [
                    # Train 16212 departs at 08:25 (delayed from 08:20) and reaches BLRR at 08:59 -> desk eta 09:29
                    {"code": "HSRA", "sta": "08:18", "std": "08:20", "eta": "08:23", "etd": "08:25", "has_arrived": False, "has_departed": False},
                    {"code": "BLRR", "sta": "08:59", "std": "09:00", "eta": "08:59", "etd": "09:00", "has_arrived": False, "has_departed": False},
                ],
            },
        }.get(t, {})

        scan = rail_tracker.scan_morning_commute_options(reference_time="07:45")
        # Both 66596 and 16212 depart at 08:25.
        # 16212 desk ETA is 09:34, 66596 desk ETA is 09:40.
        # Tie-breaker should pick 16212 because it arrives at desk earlier!
        assert scan["recommended_train"]["train_no"] == "16212"
        assert scan["recommended_train"]["desk_eta"] == "09:34"


def test_scan_evening_commute_options_safe_dict_access():
    """Verify scan_evening_commute_options does not crash on missing etd/sta/has_departed keys."""
    mock_status = {
        "train_no": "66585",
        "current_station": "BNC",
        "delay_minutes": 15,
        "stations": [
            # Station dictionary with missing etd key and no has_departed key
            {"code": "BLRR", "name": "BELLANDUR", "std": "15:48"},
            {"code": "HSRA", "name": "HOSUR"},
        ],
    }
    with patch("rail_tracker.get_live_train_status", return_value=mock_status):
        opts = rail_tracker.scan_evening_commute_options(reference_time="15:00")
        assert len(opts) > 0
        opt_66585 = next(o for o in opts if o["train_no"] == "66585")
        # Fallback uses sch_dep 15:48 + delay 15m = 16:03
        assert opt_66585["estimated_departure"] == "16:03"
        # Desk leave time is 16:03 - 20m lead time to BLRR = 15:43
        assert opt_66585["leave_desk_time"] == "15:43"


def test_check_evening_milestone_trigger_safe_dict_access():
    """Verify check_evening_milestone_trigger handles missing station keys gracefully without KeyError."""
    # Stations missing has_departed, effective_delay, eta
    status_sparse = {
        "train_no": "16232",
        "stations": [
            {"code": "BNC", "name": "BANGALORE CANT", "std": "19:10"},
            {"code": "CRLM", "name": "CARMELARAM"},
        ],
    }
    # Should not raise KeyError
    trig = rail_tracker.check_evening_milestone_trigger("16232", status_sparse)
    assert trig is None

    # When has_departed is True but eta is missing (computed dynamically from sta 19:35 + 0 delay)
    status_departed = {
        "train_no": "16232",
        "stations": [
            {"code": "BNC", "name": "BANGALORE CANT", "has_departed": True, "std": "19:10"},
            {"code": "CRLM", "name": "CARMELARAM"},
        ],
    }
    trig2 = rail_tracker.check_evening_milestone_trigger("16232", status_departed)
    assert trig2 is not None
    assert trig2["triggered"] is True
    assert trig2["crlm_eta"] == "19:35"
    assert trig2["boarding_station"] == "CRLM"
    assert trig2["lead_time_mins"] == 25


def test_api_rail_action_stay():
    """Verify api_rail_action supports action:stay to transition to HIBERNATION."""
    import asyncio
    from unittest.mock import AsyncMock
    from api.index import api_rail_action

    async def _test():
        mock_req = MagicMock()
        mock_req.json = AsyncMock(return_value={"action": "stay"})
        resp = await api_rail_action(mock_req)
        assert resp.status_code == 200
        body = json.loads(resp.body.decode("utf-8"))
        assert body["status"] == "ok"
        assert body["state"]["state"] == rail_daemon.STATE_HIBERNATION
        assert body["state"]["evening_completed"] is True
        assert "Staying late confirmed" in body["message"]

    asyncio.run(_test())


def test_transit_window_guard_midday_and_overnight():
    """Verify inspect_rake_turnaround and 06278 do not calculate afternoon physical transit at 14:00."""
    with patch("rail_tracker.get_live_train_status") as mock_status:
        mock_status.side_effect = lambda t, d=None: {
            "66595": {
                "train_no": "66595",
                "current_station": "BNC",  # Transit 60 mins
                "delay_minutes": 0,
                "stations": [{"code": "HSRA", "sta": "08:00", "has_arrived": False}],
            },
            "66596": {
                "train_no": "66596",
                "current_station": "HSRA",
                "delay_minutes": 0,
                "stations": [{"code": "HSRA", "sta": "08:20", "std": "08:25", "has_arrived": False, "has_departed": False}],
            },
            "06278": {
                "train_no": "06278",
                "current_station": "DPJ",  # Transit 80 mins
                "delay_minutes": 0,
                "stations": [{"code": "HSRA", "sta": "07:05", "std": "07:07", "has_arrived": False, "has_departed": False}],
            },
            "16212": {
                "train_no": "16212",
                "current_station": "SA",
                "delay_minutes": 0,
                "stations": [{"code": "HSRA", "sta": "08:18", "std": "08:20", "has_arrived": False, "has_departed": False}],
            },
        }.get(t, {})

        # At 14:00 (midday/afternoon):
        # 66595 should NOT project 14:00 + 60m = 15:00 arrival (which would make 66596 depart at 15:10).
        rake = rail_tracker.inspect_rake_turnaround("66596", "66595", reference_time="14:00")
        assert rake["projected_hsra_departure"] == "08:25"

        # 06278 should NOT project 14:00 + 82m = 15:22 departure.
        scan = rail_tracker.scan_morning_commute_options(reference_time="14:00")
        opt_06278 = next(o for o in scan["options"] if o["train_no"] == "06278")
        assert opt_06278["projected_departure"] == "07:07"


def test_daemon_cmd_eta_safe_station_access():
    """Verify daemon.cmd_eta does not raise KeyError when stations have missing keys."""
    import tempfile
    import uuid
    daemon = rail_daemon.RailDaemon(store=rail_daemon.CommuteStateStore(file_path=os.path.join(tempfile.gettempdir(), f"test_cmd_eta_{uuid.uuid4().hex}.json")))
    daemon.bot.send_message = MagicMock()

    mock_sparse_status = {
        "train_no": "16232",
        "stations": [
            # Minimal station dict with missing sta, eta, effective_delay, has_departed, has_arrived
            {"code": "SBC", "name": "KSR BENGALURU"},
            {"code": "BNC", "name": "BANGALORE CANT", "has_arrived": True},
        ],
    }
    with patch("rail_tracker.get_live_train_status", return_value=mock_sparse_status):
        daemon.cmd_eta("16232", chat_id="12345")
        assert daemon.bot.send_message.call_count == 1
        msg = daemon.bot.send_message.call_args[0][0]
        assert "Station ETAs for Train 16232" in msg
        assert "BNC" in msg


# =============================================================================
# 12. ALERTS MASTER KILL SWITCH / ON-OFF TOGGLE TESTS
# =============================================================================

def test_alerts_enabled_default_and_persistence(tmp_path):
    """Verify alerts_enabled defaults to True, persists False to disk, and resets cleanly."""
    state_file = str(tmp_path / "commute_test_alerts.json")
    store = rail_daemon.CommuteStateStore(file_path=state_file)
    assert store.state_data.get("alerts_enabled") is True

    # Mutate to False and save
    store.state_data["alerts_enabled"] = False
    store.save()

    # Reload from disk
    store2 = rail_daemon.CommuteStateStore(file_path=state_file)
    assert store2.state_data.get("alerts_enabled") is False

    # Reset today restores True
    store2.reset_today()
    assert store2.state_data.get("alerts_enabled") is True


def test_alerts_muted_suppresses_proactive_pushes_while_preserving_state(tmp_path):
    """Verify switching alerts OFF suppresses proactive Telegram pushes while preserving internal state transitions."""
    state_file = str(tmp_path / "commute_test_muted.json")
    store = rail_daemon.CommuteStateStore(file_path=state_file)
    store.state_data["alerts_enabled"] = False
    store.state_data["morning_train"] = "66596"
    store.state_data["morning_prompt_sent"] = False
    store.save()

    daemon = rail_daemon.RailDaemon(store=store)
    daemon.bot.send_message = MagicMock()

    # 1. handle_morning_prompt: Should suppress Telegram message dispatch but record state
    daemon.handle_morning_prompt(current_time="07:15")
    assert daemon.bot.send_message.call_count == 0
    assert daemon.store.state_data["morning_prompt_sent"] is True
    assert daemon.store.state_data["morning_train"] is not None

    # 2. handle_morning_tracking: Telegram push suppressed, but delay and step-out state MUST be recorded
    fake_scan = {
        "options": [
            {
                "train_no": "66596",
                "train_name": "Hosur MEMU",
                "scheduled_departure": "08:25",
                "projected_departure": "08:45",
                "step_out_time": "08:35",
                "dest_eta": "09:23",
                "desk_eta": "09:53",
                "delay_mins": 20,
                "is_delayed": True,
                "status": "VIABLE",
            }
        ],
        "recommended_train": {
            "train_no": "66596",
            "train_name": "Hosur MEMU",
            "scheduled_departure": "08:25",
            "projected_departure": "08:45",
            "step_out_time": "08:35",
            "dest_eta": "09:23",
            "desk_eta": "09:53",
            "delay_mins": 20,
            "is_delayed": True,
            "status": "VIABLE",
        },
        "rake_turnaround": {
            "rake_current_station_name": "HEELALIGE",
            "rake_current_station": "HLE",
            "rake_delay_mins": 20,
        },
        "recommendation_reason": "Optimal MEMU rake",
    }
    with patch("rail_tracker.scan_morning_commute_options", return_value=fake_scan):
        daemon.handle_morning_tracking(current_time="08:35")
        # Assert ZERO messages sent to Telegram
        assert daemon.bot.send_message.call_count == 0
        # Assert internal state updated properly despite muted alerts
        assert daemon.store.state_data["morning_delay_mins"] == 20
        assert daemon.store.state_data["morning_step_out_time"] == "08:35"
        assert daemon.store.state_data["morning_stepped_out"] is True

    # 3. handle_evening_prompt: Should suppress message but record prompt sent and transition
    daemon.store.state_data["evening_prompt_sent"] = False
    daemon.handle_evening_prompt(current_time="14:15")
    assert daemon.bot.send_message.call_count == 0
    assert daemon.store.state_data["evening_prompt_sent"] is True
    assert daemon.store.state_data["state"] == rail_daemon.STATE_EVENING_PROMPT

    # 4. handle_evening_tracking: Milestone trigger should NOT push message, but record fired
    fake_status = {
        "train_name": "Mailaduturai Express",
        "current_status": "Departed BNC",
        "stations": [{"code": "CRLM", "has_departed": False}],
    }
    fake_milestone = {"triggered": True, "message": "LEAVE DESK NOW"}
    with patch("rail_tracker.get_live_train_status", return_value=fake_status), \
         patch("rail_tracker.check_evening_milestone_trigger", return_value=fake_milestone):
        daemon.handle_evening_tracking(current_time="19:15")
        assert daemon.bot.send_message.call_count == 0
        assert daemon.store.state_data["evening_milestone_fired"] is True


def test_switching_alerts_on_resumes_alerts(tmp_path):
    """Verify switching alerts back ON restores proactive Telegram alert dispatches."""
    state_file = str(tmp_path / "commute_test_resume.json")
    store = rail_daemon.CommuteStateStore(file_path=state_file)
    store.state_data["alerts_enabled"] = True
    store.state_data["morning_prompt_sent"] = False
    store.save()

    daemon = rail_daemon.RailDaemon(store=store)
    daemon.bot.send_message = MagicMock()

    daemon.handle_morning_prompt(current_time="07:15")
    assert daemon.bot.send_message.call_count == 1
    msg = daemon.bot.send_message.call_args[0][0]
    assert "Good Morning Sriram" in msg


def test_direct_commands_still_answer_when_alerts_muted(tmp_path):
    """Verify user-initiated direct commands (/status, /morning, /delays, /eta, /rake, /help) answer with muted indicator."""
    state_file = str(tmp_path / "commute_test_cmds.json")
    store = rail_daemon.CommuteStateStore(file_path=state_file)
    store.state_data["alerts_enabled"] = False
    store.save()

    daemon = rail_daemon.RailDaemon(store=store)
    daemon.bot.send_message = MagicMock()

    # /status command
    daemon.cmd_status(chat_id="test_chat")
    assert daemon.bot.send_message.call_count == 1
    status_msg = daemon.bot.send_message.call_args[0][0]
    assert "🔕 MUTED" in status_msg

    # /morning command
    daemon.bot.send_message.reset_mock()
    daemon.cmd_morning(chat_id="test_chat")
    assert daemon.bot.send_message.call_count == 1

    # /help command
    daemon.bot.send_message.reset_mock()
    daemon.cmd_help(chat_id="test_chat")
    assert daemon.bot.send_message.call_count == 1
    help_msg = daemon.bot.send_message.call_args[0][0]
    assert "/mute" in help_msg
    assert "/unmute" in help_msg

    # /mute and /unmute commands
    daemon.bot.send_message.reset_mock()
    daemon.execute_command("/mute", chat_id="test_chat")
    assert daemon.store.state_data["alerts_enabled"] is False
    assert "Muted" in daemon.bot.send_message.call_args[0][0]

    daemon.bot.send_message.reset_mock()
    daemon.execute_command("/unmute", chat_id="test_chat")
    assert daemon.store.state_data["alerts_enabled"] is True
    assert "Resumed" in daemon.bot.send_message.call_args[0][0]


def test_api_rail_status_and_action_toggle_alerts(client):
    """Verify GET /api/rail/status returns alerts_enabled and POST /api/rail/action toggles alerts cleanly."""
    # 1. Verify GET /api/rail/status returns alerts_enabled
    res = client.get("/api/rail/status")
    assert res.status_code == 200
    data = res.json()
    assert "alerts_enabled" in data
    assert isinstance(data["alerts_enabled"], bool)

    # 2. Toggle alerts via POST /api/rail/action
    toggle_res = client.post("/api/rail/action", json={"action": "toggle_alerts"})
    assert toggle_res.status_code == 200
    toggle_data = toggle_res.json()
    assert toggle_data["status"] == "ok"
    assert "alerts_enabled" in toggle_data

    # 3. Explicitly set alerts to False
    set_false_res = client.post("/api/rail/action", json={"action": "set_alerts", "enabled": False})
    assert set_false_res.status_code == 200
    assert set_false_res.json()["alerts_enabled"] is False

    # 4. GET /api/rail/status should reflect False
    status_false = client.get("/api/rail/status").json()
    assert status_false["alerts_enabled"] is False

    # 5. Restore alerts to True
    set_true_res = client.post("/api/rail/action", json={"action": "unmute_alerts"})
    assert set_true_res.status_code == 200
    assert set_true_res.json()["alerts_enabled"] is True


def test_watchdog_alert_consumed_and_suppressed_when_muted(tmp_path):
    """Verify watchdog fail-safe alert is consumed and not sent when alerts are muted."""
    state_file = str(tmp_path / "commute_test_wd.json")
    store = rail_daemon.CommuteStateStore(file_path=state_file)
    now_dt = datetime(2026, 11, 16, 11, 0)
    store.state_data["date"] = now_dt.strftime("%Y-%m-%d")
    store.state_data["alerts_enabled"] = False
    store.state_data["state"] = rail_daemon.STATE_MIDDAY_STANDBY
    store.save()

    daemon = rail_daemon.RailDaemon(store=store)
    daemon.bot.send_message = MagicMock()

    rail_tracker.watchdog._pending_alert = {"triggered": True, "message": "CRIS scraping failed"}
    daemon.step(now=now_dt)
    # Assert message was suppressed
    assert daemon.bot.send_message.call_count == 0
    # Assert watchdog pending alert was consumed so it doesn't leak later
    assert rail_tracker.watchdog.get_pending_alert() is None


# =============================================================================
# TESTS: GENERALIZED MILESTONES, PARALLEL SCRAPING & RESILIENT SUPABASE SYNC
# =============================================================================

def test_dynamic_evening_milestone_blrr():
    """Verify check_evening_milestone_trigger dynamically selects BLRR with 20m lead time for trains stopping at BLRR."""
    status_66585 = {
        "train_no": "66585",
        "delay_minutes": 7,
        "stations": [
            {"code": "BYPL", "name": "BAIYAPPANAHALLI", "has_departed": True, "etd": "15:48", "std": "15:41"},
            {"code": "BLRR", "name": "BELANDUR ROAD", "sta": "15:58", "std": "15:59"},  # eta missing, sta=15:58 + 7m delay = 16:05
        ],
    }
    trigger = rail_tracker.check_evening_milestone_trigger("66585", status_66585)
    assert trigger is not None
    assert trigger["triggered"] is True
    assert trigger["boarding_station"] == "BLRR"
    assert trigger["lead_time_mins"] == 20
    assert trigger["boarding_eta"] == "16:05"
    assert trigger["crlm_eta"] == "16:05"
    assert "Bellandur Road (BLRR)" in trigger["message"]
    assert "20 mins lead time" in trigger["message"]


def test_dynamic_evening_milestone_crlm_with_delay():
    """Verify check_evening_milestone_trigger computes CRLM dynamic ETA from scheduled sta + delay when eta is missing."""
    status_16232 = {
        "train_no": "16232",
        "delay_minutes": 5,
        "stations": [
            {"code": "BNC", "name": "BANGALORE CANT", "has_departed": True, "etd": "19:15", "std": "19:10"},
            {"code": "CRLM", "name": "CARMELARAM", "sta": "19:35", "std": "19:36"},
        ],
    }
    trigger = rail_tracker.check_evening_milestone_trigger("16232", status_16232)
    assert trigger is not None
    assert trigger["triggered"] is True
    assert trigger["boarding_station"] == "CRLM"
    assert trigger["lead_time_mins"] == 25
    assert trigger["boarding_eta"] == "19:40"
    assert trigger["crlm_eta"] == "19:40"
    assert "Carmelaram (CRLM)" in trigger["message"]
    assert "25 mins lead time" in trigger["message"]


def test_resilient_supabase_sync_pgrst204_fallback_daemon(tmp_path, guard_supabase_sync, monkeypatch):
    """Verify rail_daemon._sync_to_supabase catches HTTP 400 PGRST204 and retries without alerts_enabled."""
    import urllib.error
    import io

    state_file = str(tmp_path / "commute_test_pgrst.json")
    store = rail_daemon.CommuteStateStore(file_path=state_file)
    store.state_data["state"] = rail_daemon.STATE_MORNING_TRACKING
    store.state_data["alerts_enabled"] = True

    calls = []

    def mock_urlopen(req, timeout=5):
        data = json.loads(req.data.decode("utf-8"))
        calls.append(data)
        if len(calls) == 1:
            # First attempt: Supabase returns 400 with PGRST204
            err_body = json.dumps({
                "code": "PGRST204",
                "message": "Could not find the 'alerts_enabled' column of 'commute_daily_state' in the schema cache"
            }).encode("utf-8")
            fp = io.BytesIO(err_body)
            raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", hdrs={}, fp=fp)
        # Second attempt succeeds
        return io.BytesIO(b"{}")

    monkeypatch.setattr(rail_daemon, "SUPABASE_URL", "https://mock.supabase.co")
    monkeypatch.setattr(rail_daemon, "SUPABASE_KEY", "mock-key")
    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        guard_supabase_sync._original(store)

    assert len(calls) == 2
    assert "alerts_enabled" in calls[0]
    assert "alerts_enabled" not in calls[1]
    assert calls[1]["state"] == rail_daemon.STATE_MORNING_TRACKING


def test_resilient_supabase_sync_pgrst204_fallback_api():
    """Verify api.index._sync_to_supabase retries without alerts_enabled on HTTP 400 PGRST204."""
    import httpx
    from api.index import _sync_to_supabase

    state_payload = {
        "date": "2026-11-16",
        "state": "EVENING_TRACKING",
        "morning_train": "66596",
        "evening_train": "16232",
        "alerts_enabled": True,
    }

    call_payloads = []

    async def mock_post(self, url, headers=None, json=None):
        call_payloads.append(json)
        if len(call_payloads) == 1:
            req = httpx.Request("POST", url)
            return httpx.Response(
                400,
                text='{"code": "PGRST204", "message": "Could not find \'alerts_enabled\' in schema cache"}',
                request=req
            )
        req = httpx.Request("POST", url)
        return httpx.Response(201, text='{"status": "created"}', request=req)

    async def _test():
        with patch.dict(os.environ, {"SUPABASE_URL": "https://mock.supabase.co", "SUPABASE_KEY": "mock-key"}), \
             patch.object(httpx.AsyncClient, "post", mock_post):
            success = await _sync_to_supabase(state_payload)
            assert success is True

    import asyncio
    asyncio.run(_test())


def test_telegram_client_master_gatekeeper_blocks_proactive_alerts(tmp_path):
    """Verify TelegramClient master gatekeeper strictly drops unsolicited alerts when muted, on weekends, or off-hours."""
    state_file = str(tmp_path / "test_gatekeeper.json")
    store = rail_daemon.CommuteStateStore(file_path=state_file)
    client = rail_daemon.TelegramClient("test_token", "123456", store=store)

    with patch.object(rail_daemon.TelegramClient, "send_message", rail_daemon.TelegramClient._real_send_message):
        # 1. Blocked when store alerts_enabled is False
        store.state_data["alerts_enabled"] = False
        res_muted = client.send_message("🚨 Test Alert: Muted State", is_direct_reply=False)
        assert res_muted is None

        # 2. Blocked on Sunday even if alerts_enabled is True
        store.state_data["alerts_enabled"] = True
        sunday_dt = datetime(2026, 11, 15, 8, 30, 0, tzinfo=rail_daemon.IST_TZ)
        with patch("rail_daemon.get_ist_now", return_value=sunday_dt):
            res_sunday = client.send_message("🚨 Test Alert: Sunday Alert", is_direct_reply=False)
            assert res_sunday is None

        # 3. Blocked at Midnight (00:15 AM) on Weekday
        monday_midnight = datetime(2026, 11, 16, 0, 15, 0, tzinfo=rail_daemon.IST_TZ)
        with patch("rail_daemon.get_ist_now", return_value=monday_midnight):
            res_midnight = client.send_message("🚨 Test Alert: Midnight Spurt", is_direct_reply=False)
            assert res_midnight is None

        # 4. Allowed during Authorized Commute Window (Monday 07:15 AM)
        monday_morning = datetime(2026, 11, 16, 7, 15, 0, tzinfo=rail_daemon.IST_TZ)
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"ok": True, "result": {"message_id": 100}}).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("rail_daemon.get_ist_now", return_value=monday_morning), \
             patch("urllib.request.urlopen", return_value=mock_resp):
            res_ok = client.send_message("☀️ Authorized Morning Alert", is_direct_reply=False)
            assert res_ok is not None
            assert res_ok["message_id"] == 100

        # 5. Direct replies ALWAYS permitted regardless of time/mute status
        with patch("rail_daemon.get_ist_now", return_value=monday_midnight), \
             patch("urllib.request.urlopen", return_value=mock_resp):
            store.state_data["alerts_enabled"] = False
            res_direct = client.send_message("📊 Status Response", is_direct_reply=True)
            assert res_direct is not None
            assert res_direct["message_id"] == 100

    assert len(call_payloads) == 2
    assert "alerts_enabled" in call_payloads[0]
    assert "alerts_enabled" not in call_payloads[1]
    assert call_payloads[1]["state"] == "EVENING_TRACKING"


def test_evening_milestone_trigger_suppressed_if_target_already_departed():
    """Verify check_evening_milestone_trigger returns None if the target station has already departed."""
    # 1. CRLM target train (16232)
    status_16232 = {
        "train_no": "16232",
        "delay_minutes": 5,
        "stations": [
            {"code": "BNC", "name": "BANGALORE CANT", "has_departed": True, "etd": "19:15"},
            {"code": "CRLM", "name": "CARMELARAM", "has_departed": True, "sta": "19:35", "etd": "19:40"},
        ],
    }
    trigger = rail_tracker.check_evening_milestone_trigger("16232", status_16232)
    assert trigger is None

    # 2. BLRR target train (66585)
    status_66585 = {
        "train_no": "66585",
        "delay_minutes": 2,
        "stations": [
            {"code": "BYPL", "name": "BAIYAPPANAHALLI", "has_departed": True, "etd": "15:43"},
            {"code": "BLRR", "name": "BELANDUR ROAD", "has_departed": True, "sta": "15:58", "etd": "16:00"},
        ],
    }
    trigger_blrr = rail_tracker.check_evening_milestone_trigger("66585", status_66585)
    assert trigger_blrr is None


def test_add_minutes_to_time_string_tolerance():
    """Verify add_minutes_to_time safely handles string integers without crashing."""
    assert rail_tracker.add_minutes_to_time("19:35", "5") == "19:40"
    assert rail_tracker.add_minutes_to_time("08:15", "-10") == "08:05"


def test_fetch_supabase_commute_state_parses_completion_and_milestones():
    """Verify _fetch_supabase_commute_state parses morning_status, evening_status, and evening_milestone_fired."""
    import httpx
    from api.index import _fetch_supabase_commute_state

    mock_row = {
        "date": "2026-11-16",
        "state": "MIDDAY_STANDBY",
        "morning_train": "66596",
        "morning_step_out_time": "08:15",
        "morning_revised_dep": "08:25",
        "morning_delay_mins": 0,
        "morning_status": "COMPLETED",
        "evening_train": "16232",
        "evening_status": "COMPLETED",
        "evening_milestone_fired": True,
        "alerts_enabled": False,
        "notes": "Arrived on time",
    }

    async def mock_get(self, url, headers=None):
        req = httpx.Request("GET", url)
        return httpx.Response(200, json=[mock_row], request=req)

    async def _test():
        with patch.dict(os.environ, {"SUPABASE_URL": "https://mock.supabase.co", "SUPABASE_KEY": "mock-key"}), \
             patch.object(httpx.AsyncClient, "get", mock_get):
            parsed = await _fetch_supabase_commute_state("2026-11-16")
            assert parsed is not None
            assert parsed["morning_status"] == "COMPLETED"
            assert parsed["morning_completed"] is True
            assert parsed["evening_status"] == "COMPLETED"
            assert parsed["evening_completed"] is True
            assert parsed["evening_milestone_fired"] is True
            assert parsed["alerts_enabled"] is False

    import asyncio
    asyncio.run(_test())


def test_telegram_client_master_gatekeeper_blocks_proactive_alerts(tmp_path):
    """Verify TelegramClient master gatekeeper strictly drops unsolicited alerts when muted, on weekends, or off-hours."""
    state_file = str(tmp_path / "test_gatekeeper.json")
    store = rail_daemon.CommuteStateStore(file_path=state_file)
    client = rail_daemon.TelegramClient("test_token", "123456", store=store)

    with patch.object(rail_daemon.TelegramClient, "send_message", rail_daemon.TelegramClient._real_send_message):
        # 1. Blocked when store alerts_enabled is False
        store.state_data["alerts_enabled"] = False
        res_muted = client.send_message("🚨 Test Alert: Muted State", is_direct_reply=False)
        assert res_muted is None

        # 2. Blocked on Sunday even if alerts_enabled is True
        store.state_data["alerts_enabled"] = True
        sunday_dt = datetime(2026, 11, 15, 8, 30, 0, tzinfo=rail_daemon.IST_TZ)
        with patch("rail_daemon.get_ist_now", return_value=sunday_dt):
            res_sunday = client.send_message("🚨 Test Alert: Sunday Alert", is_direct_reply=False)
            assert res_sunday is None

        # 3. Blocked at Midnight (00:15 AM) on Weekday
        monday_midnight = datetime(2026, 11, 16, 0, 15, 0, tzinfo=rail_daemon.IST_TZ)
        with patch("rail_daemon.get_ist_now", return_value=monday_midnight):
            res_midnight = client.send_message("🚨 Test Alert: Midnight Spurt", is_direct_reply=False)
            assert res_midnight is None

        # 4. Allowed during Authorized Commute Window (Monday 07:15 AM)
        monday_morning = datetime(2026, 11, 16, 7, 15, 0, tzinfo=rail_daemon.IST_TZ)
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"ok": True, "result": {"message_id": 100}}).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("rail_daemon.get_ist_now", return_value=monday_morning), \
             patch("urllib.request.urlopen", return_value=mock_resp):
            res_ok = client.send_message("☀️ Authorized Morning Alert", is_direct_reply=False)
            assert res_ok is not None
            assert res_ok["message_id"] == 100

        # 5. Direct replies ALWAYS permitted regardless of time/mute status
        with patch("rail_daemon.get_ist_now", return_value=monday_midnight), \
             patch("urllib.request.urlopen", return_value=mock_resp):
            store.state_data["alerts_enabled"] = False
            res_direct = client.send_message("📊 Status Response", is_direct_reply=True)
            assert res_direct is not None
            assert res_direct["message_id"] == 100









