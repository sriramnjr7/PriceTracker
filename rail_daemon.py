"""rail_daemon.py — Autonomous Railway Commute Intelligence Daemon & Telegram Assistant.

Operates 24/7 background commute lifecycle for Sriram's Hosur <-> ETV Bangalore route:
- Telegram Long-Polling (@SriTrainBot) with inline keyboards
- 7-State Commute Machine (NIGHT_SLEEP, MORNING_PROMPT, MORNING_TRACKING, MIDDAY_STANDBY, EVENING_PROMPT, EVENING_TRACKING, HIBERNATION)
- Dynamic delay notifications & dynamic step-out alerts (shifting with incoming rake 66595)
- Multi-train morning recommendation scanner (detects delayed earlier trains or optimal MEMU)
- Evening milestone departure triggers (e.g. Train 16232 clearing BNC -> 'LEAVE DESK NOW')
- 4-Tier adaptive polling (30s critical, 60s approach, 15m standby, 0 sleep)
- 2-Strike Watchdog monitor with 1-tap fail-safe manual links
- Zero-polling Supabase write guarantee + offline local state persistence
- Complete 14-command /help menu suite
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
import urllib.parse
import urllib.request

# Ensure workspace is in sys.path
root_dir = os.path.dirname(os.path.abspath(__file__))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import rail_tracker

logger = logging.getLogger("rail_daemon")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# Indian Standard Time (IST, UTC+05:30) Helper
IST_TZ = timezone(timedelta(hours=5, minutes=30))


def get_ist_now() -> datetime:
    """Return current datetime in Indian Standard Time (IST, UTC+05:30)."""
    return datetime.now(timezone.utc).astimezone(IST_TZ)

# =============================================================================
# 1. CONFIGURATION & CONSTANTS
# =============================================================================

DEFAULT_BOT_TOKEN = ""
DEFAULT_CHAT_ID = ""

# Strict Isolation: All tokens must be loaded from environment variables or .env file.
# Dedicated Rail bot tokens take precedence; fall back to standard tokens if provided.
TELEGRAM_BOT_TOKEN = (
    os.getenv("TRAIN_BOT_TOKEN")
    or os.getenv("RAIL_TELEGRAM_BOT_TOKEN")
    or os.getenv("TELEGRAM_BOT_TOKEN")
    or DEFAULT_BOT_TOKEN
)
TELEGRAM_CHAT_ID = (
    os.getenv("TRAIN_CHAT_ID")
    or os.getenv("RAIL_TELEGRAM_CHAT_ID")
    or os.getenv("TELEGRAM_CHAT_ID")
    or DEFAULT_CHAT_ID
)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

LOCAL_STATE_FILE = (
    os.path.join(tempfile.gettempdir(), "commute_daily_state.json")
    if os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME")
    else os.path.join(root_dir, "commute_daily_state.json")
)

# State Machine Constants
STATE_NIGHT_SLEEP = "NIGHT_SLEEP"
STATE_MORNING_PROMPT = "MORNING_PROMPT"
STATE_MORNING_TRACKING = "MORNING_TRACKING"
STATE_MIDDAY_STANDBY = "MIDDAY_STANDBY"
STATE_EVENING_PROMPT = "EVENING_PROMPT"
STATE_EVENING_TRACKING = "EVENING_TRACKING"
STATE_HIBERNATION = "HIBERNATION"
STATE_WFH = "WFH"
STATE_BIKE = "BIKE"
STATE_WEEKEND_REST = "WEEKEND_REST"

# Adaptive Polling Tiers (in seconds)
POLL_TIER_CRITICAL = 30     # < 20 mins to step-out / milestone
POLL_TIER_APPROACH = 60     # 20 - 60 mins
POLL_TIER_STANDBY = 900     # Midday / Weekend / > 60 mins (15 minutes)
POLL_TIER_HIBERNATE = 10    # Low frequency for Telegram updates during sleep

# Lead Times (minutes)
LEAD_TIME_HOSUR = 10        # Door-to-PF1: 5m walk + 5m buffer
LEAD_TIME_CRLM = 25         # ETV Desk to Carmelaram PF1
LEAD_TIME_BLRR = 20         # ETV Desk to Bellandur Road PF1


# =============================================================================
# 2. TELEGRAM CLIENT & INLINE KEYBOARD HELPERS
# =============================================================================

class TelegramClient:
    """Synchronous resilient Telegram Bot API client for long-polling and alert pushes."""

    def __init__(self, token: str, default_chat_id: str):
        self.token = token.strip() if token else ""
        self.default_chat_id = default_chat_id.strip() if default_chat_id else ""
        self.base_url = f"https://api.telegram.org/bot{self.token}" if self.token else ""

    def send_message(
        self,
        text: str,
        chat_id: Optional[str] = None,
        reply_markup: Optional[Dict[str, Any]] = None,
        parse_mode: Optional[str] = "Markdown",
    ) -> Optional[Dict[str, Any]]:
        target_chat = chat_id or self.default_chat_id
        if not self.token or not target_chat:
            logger.warning("No Telegram token or chat_id configured. Message dispatch skipped.")
            return None

        # Truncate text if exceeding Telegram message limit
        safe_text = text if len(text) <= 4000 else (text[:3985] + "\n...[truncated]")

        url = f"{self.base_url}/sendMessage"
        payload: Dict[str, Any] = {
            "chat_id": target_chat,
            "text": safe_text,
            "disable_web_page_preview": True,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup:
            payload["reply_markup"] = reply_markup

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                return res.get("result")
        except Exception as exc:
            # Fallback: If Markdown parse error or entity error, retry as plain text
            if payload.get("parse_mode"):
                logger.warning("Telegram send_message failed with parse_mode=%s (%s). Retrying as plain text...", payload["parse_mode"], exc)
                plain_payload = dict(payload)
                plain_payload.pop("parse_mode", None)
                try:
                    retry_req = urllib.request.Request(
                        url,
                        data=json.dumps(plain_payload).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(retry_req, timeout=12) as resp:
                        res = json.loads(resp.read().decode("utf-8"))
                        return res.get("result")
                except Exception as retry_exc:
                    logger.error("Retry sending plain Telegram message also failed: %s", retry_exc)
            else:
                logger.error("Failed to send Telegram message: %s", exc)
            return None

    # Reference to original send_message for resilience unit tests
    _real_send_message = send_message

    def edit_message(
        self,
        message_id: int,
        text: str,
        chat_id: Optional[str] = None,
        reply_markup: Optional[Dict[str, Any]] = None,
        parse_mode: Optional[str] = "Markdown",
    ) -> Optional[Dict[str, Any]]:
        target_chat = chat_id or self.default_chat_id
        if not self.token or not target_chat:
            return None

        safe_text = text if len(text) <= 4000 else (text[:3985] + "\n...[truncated]")

        url = f"{self.base_url}/editMessageText"
        payload: Dict[str, Any] = {
            "chat_id": target_chat,
            "message_id": message_id,
            "text": safe_text,
            "disable_web_page_preview": True,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup:
            payload["reply_markup"] = reply_markup

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                return res.get("result")
        except Exception as exc:
            if payload.get("parse_mode"):
                logger.warning("Telegram edit_message failed with parse_mode=%s (%s). Retrying as plain text...", payload["parse_mode"], exc)
                plain_payload = dict(payload)
                plain_payload.pop("parse_mode", None)
                try:
                    retry_req = urllib.request.Request(
                        url,
                        data=json.dumps(plain_payload).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(retry_req, timeout=12) as resp:
                        res = json.loads(resp.read().decode("utf-8"))
                        return res.get("result")
                except Exception as retry_exc:
                    logger.error("Retry editing plain Telegram message also failed: %s", retry_exc)
            else:
                logger.error("Failed to edit Telegram message: %s", exc)
            return None

    def answer_callback(self, callback_query_id: str, text: Optional[str] = None) -> bool:
        if not self.token:
            return False
        url = f"{self.base_url}/answerCallbackQuery"
        payload = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                return True
        except Exception as exc:
            logger.error("Failed to answer callback query: %s", exc)
            return False

    def get_updates(self, offset: int = 0, timeout: int = 20) -> List[Dict[str, Any]]:
        if not self.token:
            return []
        url = f"{self.base_url}/getUpdates?offset={offset}&timeout={timeout}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "RailRadarDaemon/1.0"})
            with urllib.request.urlopen(req, timeout=timeout + 10) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                return res.get("result", [])
        except Exception as exc:
            logger.debug("getUpdates error: %s", exc)
            return []


# =============================================================================
# 3. ZERO-POLLING STATE PERSISTENCE (LOCAL + SUPABASE)
# =============================================================================

class CommuteStateStore:
    """Manages daily commute state with disk cache and zero-polling Supabase writes."""

    def __init__(self, file_path: Optional[str] = None):
        self.file_path = file_path if file_path is not None else LOCAL_STATE_FILE
        self.state_data = self._load()

    def _get_today_str(self) -> str:
        return get_ist_now().strftime("%Y-%m-%d")

    def _default_state(self) -> Dict[str, Any]:
        return {
            "date": self._get_today_str(),
            "state": STATE_NIGHT_SLEEP,
            "morning_train": rail_tracker.MORNING_TRAIN_MEMU,
            "morning_step_out_time": "08:15",
            "morning_projected_dep": "08:25",
            "morning_delay_mins": 0,
            "morning_prompt_sent": False,
            "morning_stepped_out": False,
            "morning_completed": False,
            "evening_train": "16232",
            "evening_prompt_sent": False,
            "evening_milestone_fired": False,
            "evening_completed": False,
            "last_delay_reported": 0,
            "last_step_out_reported": "08:15",
            "alerts_enabled": True,
            "notes": "",
            "last_updated": get_ist_now().isoformat(),
        }

    def _load(self) -> Dict[str, Any]:
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("date") == self._get_today_str():
                        if "alerts_enabled" not in data:
                            data["alerts_enabled"] = True
                        return data
            except Exception as e:
                logger.error("Error reading local state: %s", e)
        return self._default_state()

    def save(self, sync_supabase: bool = False) -> None:
        """Write to local file, and optionally sync to Supabase on state transitions."""
        self.state_data["last_updated"] = get_ist_now().isoformat()
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(self.state_data, f, indent=2)
        except Exception as e:
            logger.error("Failed to write state file: %s", e)

        if sync_supabase and SUPABASE_URL and SUPABASE_KEY:
            self._sync_to_supabase()

    def _sync_to_supabase(self) -> None:
        """Zero-polling write: called ONLY on state transitions or milestone triggers."""
        try:
            url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/commute_daily_state"
            payload = {
                "date": self.state_data.get("date", get_ist_now().strftime("%Y-%m-%d")),
                "state": self.state_data.get("state", STATE_MIDDAY_STANDBY),
                "morning_train": self.state_data.get("morning_train", rail_tracker.MORNING_TRAIN_MEMU if rail_tracker else "66596"),
                "morning_step_out_time": self.state_data.get("morning_step_out_time", "08:15"),
                "morning_revised_dep": self.state_data.get("morning_projected_dep", "08:25"),
                "morning_delay_mins": self.state_data.get("morning_delay_mins", 0),
                "morning_status": "COMPLETED" if self.state_data.get("morning_completed", False) else "ACTIVE",
                "evening_train": self.state_data.get("evening_train", "16232"),
                "evening_milestone_fired": self.state_data.get("evening_milestone_fired", False),
                "evening_status": "COMPLETED" if self.state_data.get("evening_completed", False) else "ACTIVE",
                "alerts_enabled": self.state_data.get("alerts_enabled", True),
                "notes": self.state_data.get("notes", ""),
                "last_updated": self.state_data.get("last_updated", get_ist_now().isoformat()),
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "Prefer": "resolution=merge-duplicates",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as _:
                logger.info("Successfully synced commute state to Supabase.")
        except Exception as exc:
            logger.warning("Supabase sync skipped/failed: %s", exc)

    def transition_state(self, new_state: str, note: str = "") -> None:
        prev = self.state_data["state"]
        if prev != new_state:
            logger.info("State Machine Transition: [%s] -> [%s] (%s)", prev, new_state, note)
            self.state_data["state"] = new_state
            if note:
                self.state_data["notes"] = note
            self.save(sync_supabase=True)

    def reset_today(self) -> None:
        self.state_data = self._default_state()
        self.save(sync_supabase=True)


# =============================================================================
# 4. RAIL RADAR ENGINE & TELEGRAM BOT ASSISTANT
# =============================================================================

class RailDaemon:
    """The Autonomous Rail Commute Daemon."""

    def __init__(
        self,
        bot_token: str = TELEGRAM_BOT_TOKEN,
        chat_id: str = TELEGRAM_CHAT_ID,
        store: Optional[CommuteStateStore] = None,
        bot: Optional[TelegramClient] = None,
    ):
        self.bot = bot if bot is not None else TelegramClient(bot_token, chat_id)
        self.store = store if store is not None else CommuteStateStore()
        self.update_offset = 0
        self.running = True
        self.last_track_poll_time: float = 0.0

    # -------------------------------------------------------------------------
    # Telegram In-Line Keyboards
    # -------------------------------------------------------------------------

    def get_morning_keyboard(self) -> Dict[str, Any]:
        return {
            "inline_keyboard": [
                [
                    {"text": "🚆 MEMU 66596 (08:25)", "callback_data": "train:66596"},
                    {"text": "🚆 MEMU 06278 (Dharmapuri)", "callback_data": "train:06278"},
                ],
                [
                    {"text": "🚆 Exp 16212 (08:20)", "callback_data": "train:16212"},
                    {"text": "🏍️ Taking Bike", "callback_data": "action:bike"},
                ],
                [
                    {"text": "🏠 WFH Today", "callback_data": "action:wfh"},
                    {"text": "📊 Full Scan", "callback_data": "action:morning_scan"},
                ],
                [
                    {"text": "⏭️ Skip", "callback_data": "action:skip"},
                ],
            ]
        }

    def get_evening_keyboard(self) -> Dict[str, Any]:
        return {
            "inline_keyboard": [
                [
                    {"text": "🚆 66585 (15:48 BLRR)", "callback_data": "track:66585"},
                    {"text": "🚆 16211 (16:42 BLRR)", "callback_data": "track:16211"},
                ],
                [
                    {"text": "🚆 66583 (19:00 BLRR)", "callback_data": "track:66583"},
                    {"text": "🚆 16232 (19:35 CRLM)", "callback_data": "track:16232"},
                ],
                [
                    {"text": "🚆 16527 (20:45 CRLM)", "callback_data": "track:16527"},
                    {"text": "🚆 16236 (21:50 CRLM)", "callback_data": "track:16236"},
                ],
                [
                    {"text": "🏍️ Bike / Cab", "callback_data": "action:bike"},
                    {"text": "🏠 Staying Late", "callback_data": "action:stay"},
                ],
            ]
        }

    def get_stepped_out_keyboard(self) -> Dict[str, Any]:
        return {
            "inline_keyboard": [
                [
                    {"text": "🏁 Reached Station", "callback_data": "action:reached"},
                    {"text": "🔄 Refresh Delay", "callback_data": "action:refresh"},
                ]
            ]
        }

    # -------------------------------------------------------------------------
    # Morning Lifecycle Logic
    # -------------------------------------------------------------------------

    def handle_morning_prompt(self, current_time: Optional[str] = None, now: Optional[datetime] = None) -> None:
        """Triggered at 06:45 AM: Send morning options overview. Strictly guarded to 06:45 - 09:30 AM IST on weekdays."""
        # Weekend guard: Zero proactive morning alerts on Saturday / Sunday
        if now is not None and now.weekday() in (5, 6):
            logger.info("Suppressed handle_morning_prompt: Weekend rest mode (%s)", now.strftime("%A"))
            self.store.transition_state(STATE_WEEKEND_REST, "Weekend rest mode active")
            return

        if not current_time:
            current_time = (now or get_ist_now()).strftime("%H:%M")

        # 1. Strict time-of-day guard: Strictly between 06:45 and 09:30 AM IST only
        if not ("06:45" <= current_time <= "09:30"):
            logger.warning("Rejected handle_morning_prompt execution: current_time %s is outside 06:45 - 09:30 IST window", current_time)
            # Self-heal state machine if incorrectly in STATE_MORNING_PROMPT during midday/evening
            if "09:30" < current_time < "09:40":
                self.store.transition_state(STATE_MORNING_TRACKING, "Self-heal: Active morning tracking")
            elif "09:40" <= current_time < "14:00":
                self.store.transition_state(STATE_MIDDAY_STANDBY, "Self-heal: Midday standby")
            elif "14:00" <= current_time < "15:30":
                self.store.transition_state(STATE_EVENING_PROMPT, "Self-heal: Evening window opened")
            elif "15:30" <= current_time < "23:30":
                self.store.transition_state(STATE_EVENING_TRACKING, "Self-heal: Active evening tracking")
            else:
                self.store.transition_state(STATE_NIGHT_SLEEP, "Self-heal: Night sleep mode")
            return

        if self.store.state_data.get("morning_prompt_sent"):
            return

        scan = rail_tracker.scan_morning_commute_options(reference_time=current_time)
        rec = scan["recommended_train"]
        rake = scan["rake_turnaround"]

        corridor_lines = []
        for opt in scan.get("options", []):
            delay_note = f" (+{opt['delay_mins']}m late)" if opt["is_delayed"] else " (On Time)"
            corridor_lines.append(f"• *{opt['train_name']} ({opt['train_no']})*: Sch {opt['scheduled_departure']} -> Dep ~{opt['projected_departure']} | BLRR ~{opt['dest_eta']}{delay_note}")
        corridor_summary = "\n".join(corridor_lines)

        msg = (
            f"☀️ *Good Morning Sriram!*\n"
            f"Ready for your commute to JPMorgan Chase ETV?\n\n"
            f"📍 *Home*: Gangaiya Venkatachalapathy St (10m walk to PF1)\n"
            f"🎯 *Target*: Desk Login by 11:00 AM\n\n"
            f"🔍 *Live Corridor Status*:\n"
            f"{corridor_summary}\n"
            f"• *Incoming Rake 66595*: {rake['rake_current_station_name']} (Delay: {rake['rake_delay_mins']}m)\n\n"
            f"💡 *Recommendation*: *{rec['train_name']}*\n"
            f"└ {scan['recommendation_reason']}\n\n"
            f"Select your mode of commute today:"
        )

        # Alerts master kill switch guard: suppress proactive prompt if alerts disabled
        if self.store.state_data.get("alerts_enabled", True):
            self.bot.send_message(msg, reply_markup=self.get_morning_keyboard())
        else:
            logger.info("Suppressed morning prompt push alert: Alerts are muted (alerts_enabled=False)")

        self.store.state_data["morning_prompt_sent"] = True
        self.store.state_data["morning_train"] = rec["train_no"]
        self.store.state_data["last_recommended_train"] = rec["train_no"]
        self.store.save()

    def handle_morning_tracking(self, current_time: str, now: Optional[datetime] = None) -> None:
        """
        Continuously tracks active morning train (16212 Salem Exp, 66596 MEMU, or 06278 MEMU).
        Dynamically shifts step-out alerts, detects recommendation flips, and pushes alerts.
        """
        # Weekend guard: Zero proactive morning alerts on Saturday / Sunday
        if now is not None and now.weekday() in (5, 6):
            logger.info("Suppressed handle_morning_tracking: Weekend rest mode (%s)", now.strftime("%A"))
            self.store.state_data["morning_completed"] = True
            self.store.transition_state(STATE_WEEKEND_REST, "Weekend rest mode active")
            return

        # Strict time-of-day guard for morning tracking: strictly between 07:00 and 09:40 AM IST
        if current_time >= "09:40" or current_time < "07:00":
            logger.warning("Morning tracking invoked outside morning hours (%s); auto-completing to midday standby", current_time)
            self.store.state_data["morning_completed"] = True
            self.store.transition_state(STATE_MIDDAY_STANDBY, "Auto-transition: morning window closed")
            return

        scan = rail_tracker.scan_morning_commute_options(reference_time=current_time)
        rec_opt = scan["recommended_train"]
        rake = scan["rake_turnaround"]

        # Default active train to current optimal recommendation if unset
        if not self.store.state_data.get("morning_train"):
            self.store.state_data["morning_train"] = rec_opt["train_no"]

        active_train = self.store.state_data.get("morning_train", rec_opt["train_no"])
        active_opt = next((o for o in scan["options"] if o["train_no"] == active_train), scan["options"][0])

        projected_dep = active_opt["projected_departure"]
        step_out_time = active_opt["step_out_time"]
        current_delay = active_opt["delay_mins"]

        # Update daily store state
        self.store.state_data["morning_projected_dep"] = projected_dep
        self.store.state_data["morning_step_out_time"] = step_out_time
        self.store.state_data["morning_delay_mins"] = current_delay

        last_rec = self.store.state_data.get("last_recommended_train")
        curr_rec = rec_opt["train_no"]

        # 1. Recommendation Flip Detection
        # Detects if relative train arrival/departure order changes (e.g. Salem Exp on time while Hosur MEMU delayed)
        if not last_rec:
            self.store.state_data["last_recommended_train"] = curr_rec
        elif curr_rec != last_rec and rec_opt.get("status") in ("VIABLE", "BOARDING"):
            prev_opt = next((o for o in scan["options"] if o["train_no"] == last_rec), None)
            prev_name = prev_opt["train_name"] if prev_opt else f"Train {last_rec}"
            prev_dep = prev_opt["projected_departure"] if prev_opt else "earlier"

            flip_msg = (
                f"🔄 *Commute Recommendation Shift: Train Order Flipped!*\n\n"
                f"Dynamic schedule update in Hosur morning corridor:\n"
                f"• *{rec_opt['train_name']} ({curr_rec})* is now departing latest at ~*{rec_opt['projected_departure']} AM* (Desk ETA: *{rec_opt['desk_eta']} AM*).\n"
                f"• *{prev_name} ({last_rec})* departs at ~*{prev_dep} AM*.\n\n"
                f"💡 *New Optimal Train*: *{rec_opt['train_name']}*!\n"
                f"{scan.get('recommendation_reason', '')}\n\n"
                f"Revised step-out time from home: ~*{rec_opt['step_out_time']} AM*."
            )
            kb = {
                "inline_keyboard": [
                    [{"text": f"🚆 Switch to {curr_rec} (~{rec_opt['projected_departure']})", "callback_data": f"train:{curr_rec}"}],
                    [{"text": f"Stay with {active_train}", "callback_data": "action:ack"}],
                ]
            }
            if self.store.state_data.get("alerts_enabled", True):
                self.bot.send_message(flip_msg, reply_markup=kb)
            else:
                logger.info("Suppressed morning flip alert push: Alerts muted")

            # Auto-update active tracking if user hasn't pinned a specific train manually
            if not self.store.state_data.get("user_manually_selected_train"):
                self.store.state_data["morning_train"] = curr_rec
                active_train = curr_rec
                active_opt = rec_opt
                projected_dep = active_opt["projected_departure"]
                step_out_time = active_opt["step_out_time"]
                current_delay = active_opt["delay_mins"]
                self.store.state_data["morning_projected_dep"] = projected_dep
                self.store.state_data["morning_step_out_time"] = step_out_time
                self.store.state_data["morning_delay_mins"] = current_delay

            self.store.state_data["last_recommended_train"] = curr_rec
            self.store.state_data["last_delay_reported"] = current_delay
            self.store.state_data["last_step_out_reported"] = step_out_time
            self.store.save(sync_supabase=True)

        last_reported_delay = self.store.state_data.get("last_delay_reported", 0)
        last_reported_step_out = self.store.state_data.get("last_step_out_reported", "08:15")

        # 2. Check if delay changed noticeably (>= 3 minutes shift)
        if abs(current_delay - last_reported_delay) >= 3 or (current_delay > 0 and last_reported_delay == 0):
            if current_delay > last_reported_delay:
                extra_mins = current_delay - last_reported_delay
                time_note = f"⏳ Departure delayed by an additional *{extra_mins} mins*. You have an extra *{extra_mins} mins* at home! Relax."
            elif current_delay < last_reported_delay:
                made_up = last_reported_delay - current_delay
                time_note = f"⚡ Train made up *{made_up} mins*! Departure moved EARLIER to ~*{projected_dep} AM*. New step-out: ~*{step_out_time} AM*. Prepare to leave sooner!"
            else:
                time_note = f"ℹ️ Revised departure from Hosur is ~*{projected_dep} AM* (Step-out: ~*{step_out_time} AM*)."

            if active_train == rail_tracker.MORNING_TRAIN_MEMU:
                rake_loc_str = f"*{rake.get('rake_current_station_name', 'En route')}* ({rake.get('rake_current_station', '')})"
                delay_reason_str = f"Incoming rake ({rake.get('incoming_rake_train', '66595')}) is near {rake_loc_str}, causing turnaround delay at Hosur."
            else:
                loc_str = active_opt.get("current_location", "En route")
                delay_reason_str = f"Train {active_train} is currently near *{loc_str}* with +{current_delay}m delay."

            delay_msg = (
                f"⚠️ *Commute Delay Alert: Train {active_train} ({active_opt['train_name']})*\n\n"
                f"Hey Sriram, there is a delay! {delay_reason_str}\n"
                f"• *Current Delay*: *{current_delay} mins*\n"
                f"• *Revised Hosur Departure*: ~*{projected_dep} AM*\n"
                f"• *New Step-Out Time*: ~*{step_out_time} AM* (was {last_reported_step_out})\n\n"
                f"{time_note}"
            )
            
            # If another train is viable and departing later or sooner
            if rec_opt.get("train_no") != active_train and rec_opt.get("status") in ("VIABLE", "BOARDING"):
                delay_msg += (
                    f"\n\n💡 *Alternative Available*: Train *{rec_opt['train_no']}* departs at ~*{rec_opt['projected_departure']}* "
                    f"and reaches BLRR by *{rec_opt['dest_eta']}* (Desk: {rec_opt['desk_eta']})."
                )
                kb = {
                    "inline_keyboard": [
                        [{"text": f"🚆 Switch to {rec_opt['train_no']}", "callback_data": f"train:{rec_opt['train_no']}"}],
                        [{"text": f"Stay with {active_train}", "callback_data": "action:ack"}],
                    ]
                }
                if self.store.state_data.get("alerts_enabled", True):
                    self.bot.send_message(delay_msg, reply_markup=kb)
                else:
                    logger.info("Suppressed morning delay alternative alert push: Alerts muted")
            else:
                if self.store.state_data.get("alerts_enabled", True):
                    self.bot.send_message(delay_msg)
                else:
                    logger.info("Suppressed morning delay alert push: Alerts muted")

            self.store.state_data["last_delay_reported"] = current_delay
            self.store.state_data["last_step_out_reported"] = step_out_time
            self.store.save(sync_supabase=True)

        # 3. Check Step-Out Alert Trigger: When current_time reaches step_out_time (-1m to 0m)
        diff_to_step_out = rail_tracker.minutes_difference(current_time, step_out_time)
        if -1 <= diff_to_step_out <= 1 and not self.store.state_data.get("morning_stepped_out"):
            alert_msg = (
                f"🚨 *STEP OUT NOW! (Door-to-PF1: 10m)*\n\n"
                f"Time to walk to Hosur Station Platform 1.\n"
                f"• Train: *{active_opt['train_name']} ({active_train})*\n"
                f"• Projected Departure: *{projected_dep} AM*\n"
                f"• Destination Arrival (BLRR): ~*{active_opt['dest_eta']} AM*\n"
                f"• Expected Desk Arrival: ~*{active_opt['desk_eta']} AM*\n\n"
                f"👟 5m walk + 5m platform cushion. Tap below when you reach platform:"
            )
            if self.store.state_data.get("alerts_enabled", True):
                self.bot.send_message(alert_msg, reply_markup=self.get_stepped_out_keyboard())
            else:
                logger.info("Suppressed morning step-out alert push: Alerts muted")
            self.store.state_data["morning_stepped_out"] = True
            self.store.save(sync_supabase=True)

        # 4. Check Morning Completion: When train departs Hosur or time passes 09:40
        if current_time >= "09:40" or rail_tracker.minutes_difference(projected_dep, current_time) > 15:
            self.store.state_data["morning_completed"] = True
            self.store.transition_state(STATE_MIDDAY_STANDBY, "Morning commute completed")

    # -------------------------------------------------------------------------
    # Evening Lifecycle Logic
    # -------------------------------------------------------------------------

    def handle_evening_prompt(self, current_time: Optional[str] = None, now: Optional[datetime] = None) -> None:
        """Triggered at 14:00 PM: Evening commute check-in."""
        # Weekend guard: Zero proactive evening prompts on Saturday / Sunday
        if now is not None and now.weekday() in (5, 6):
            logger.info("Suppressed handle_evening_prompt: Weekend rest mode (%s)", now.strftime("%A"))
            self.store.transition_state(STATE_WEEKEND_REST, "Weekend rest mode active")
            return

        if not current_time:
            current_time = (now or get_ist_now()).strftime("%H:%M")

        if not ("14:00" <= current_time <= "18:00"):
            logger.warning("Rejected handle_evening_prompt execution: current_time %s is outside evening prompt window (14:00 - 18:00 IST)", current_time)
            return

        if self.store.state_data.get("evening_prompt_sent"):
            return

        options = rail_tracker.scan_evening_commute_options(reference_time=current_time)
        msg = (
            f"🌆 *Good Afternoon Sriram!*\n"
            f"Planning your return trip from ETV to Hosur?\n\n"
            f"Upcoming Evening Trains:\n"
        )
        for opt in options[:4]:
            msg += f"• *{opt['train_no']}* ({opt['boarding_station']}): Sch {opt['scheduled_departure']} | Leave desk: ~{opt['leave_desk_time']}\n"
        
        msg += f"\nSelect which train you plan to take tonight:"

        # Alerts master kill switch guard: suppress proactive prompt if alerts disabled
        if self.store.state_data.get("alerts_enabled", True):
            self.bot.send_message(msg, reply_markup=self.get_evening_keyboard())
        else:
            logger.info("Suppressed evening prompt push alert: Proactive alerts are muted (alerts_enabled=False)")

        self.store.state_data["evening_prompt_sent"] = True
        self.store.transition_state(STATE_EVENING_PROMPT, "Sent 14:00 PM evening check-in")

    def handle_evening_tracking(self, current_time: Optional[str] = None, now: Optional[datetime] = None) -> None:
        """
        Monitors evening train (e.g. 16232) and checks milestone triggers
        (e.g. Train 16232 clearing BNC -> 'LEAVE DESK NOW').
        """
        # Weekend guard: Zero proactive evening alerts on Saturday / Sunday
        if now is not None and now.weekday() in (5, 6):
            logger.info("Suppressed handle_evening_tracking: Weekend rest mode (%s)", now.strftime("%A"))
            self.store.transition_state(STATE_WEEKEND_REST, "Weekend rest mode active")
            return

        if not current_time:
            current_time = (now or get_ist_now()).strftime("%H:%M")

        if current_time < "15:30" or current_time >= "23:30":
            logger.warning("Evening tracking invoked outside evening hours (%s)", current_time)
            return

        active_train = self.store.state_data.get("evening_train", "16232")
        status = rail_tracker.get_live_train_status(active_train)

        # Milestone Check
        if not self.store.state_data.get("evening_milestone_fired"):
            milestone = rail_tracker.check_evening_milestone_trigger(active_train, status)
            if milestone and milestone.get("triggered"):
                if self.store.state_data.get("alerts_enabled", True):
                    self.bot.send_message(milestone["message"])
                else:
                    logger.info("Suppressed evening milestone alert push: Alerts muted")
                self.store.state_data["evening_milestone_fired"] = True
                self.store.save(sync_supabase=True)

        # Check if train has departed CRLM/BLRR or passed 22:30
        crlm_stn = next((s for s in status.get("stations", []) if s.get("code") == rail_tracker.STN_CARMELARAM), None)
        if crlm_stn and crlm_stn.get("has_departed"):
            if not self.store.state_data.get("evening_completed"):
                if self.store.state_data.get("alerts_enabled", True):
                    self.bot.send_message(f"🚆 Train {active_train} is en route to Hosur. Enjoy the ride home!")
                else:
                    logger.info("Suppressed evening en-route alert push: Alerts muted")
                self.store.state_data["evening_completed"] = True
                self.store.transition_state(STATE_HIBERNATION, "Evening commute completed")

    # -------------------------------------------------------------------------
    # 14-Command /help Menu Implementation
    # -------------------------------------------------------------------------

    def execute_command(self, cmd_line: str, chat_id: Optional[str] = None) -> None:
        parts = cmd_line.strip().split()
        if not parts:
            return
        cmd = parts[0].lower()
        args = parts[1:]

        logger.info("Executing daemon command: %s %s", cmd, args)

        if cmd in ("/start", "/help"):
            self.cmd_help(chat_id)
        elif cmd == "/status":
            self.cmd_status(chat_id)
        elif cmd in ("/mute", "/pause", "/silence"):
            self.cmd_mute(chat_id)
        elif cmd in ("/unmute", "/resume"):
            self.cmd_unmute(chat_id)
        elif cmd == "/morning":
            self.cmd_morning(chat_id)
        elif cmd == "/evening":
            self.cmd_evening(chat_id)
        elif cmd == "/train":
            train_no = args[0] if args else "66596"
            self.cmd_train(train_no, chat_id)
        elif cmd == "/track":
            train_no = args[0] if args else "66596"
            self.cmd_track(train_no, chat_id)
        elif cmd == "/rake":
            self.cmd_rake(chat_id)
        elif cmd == "/delays":
            self.cmd_delays(chat_id)
        elif cmd == "/wfh":
            self.cmd_wfh(chat_id)
        elif cmd == "/bike":
            self.cmd_bike(chat_id)
        elif cmd == "/station":
            stn = args[0] if args else "HSRA"
            self.cmd_station(stn, chat_id)
        elif cmd == "/eta":
            train_no = args[0] if args else "66596"
            self.cmd_eta(train_no, chat_id)
        elif cmd == "/milestones":
            self.cmd_milestones(chat_id)
        elif cmd in ("/reached", "reached"):
            self.cmd_reached(chat_id)
        elif cmd in ("/stay", "stay"):
            self.cmd_stay(chat_id)
        elif cmd == "/reset":
            self.cmd_reset(chat_id)
        else:
            self.bot.send_message(f"❓ Unknown command `{cmd}`. Use /help to see all 16 available commands.", chat_id=chat_id)

    def cmd_mute(self, chat_id: Optional[str] = None) -> None:
        self.store.state_data["alerts_enabled"] = False
        self.store.save(sync_supabase=True)
        msg = (
            "🔕 *Proactive Telegram Alerts Muted*\n\n"
            "• Autonomous push alerts (morning/evening prompts, live delay shifts, step-out alarms, watchdog) are now silenced.\n"
            "• State machine & timetable tracking continue running in the background.\n"
            "• Direct commands (`/status`, `/train`, `/delays`, `/eta`, `/morning`, `/rake`) remain fully functional.\n\n"
            "💡 Use `/unmute` or the website dashboard toggle to resume alerts anytime."
        )
        self.bot.send_message(msg, chat_id=chat_id)

    def cmd_unmute(self, chat_id: Optional[str] = None) -> None:
        self.store.state_data["alerts_enabled"] = True
        self.store.save(sync_supabase=True)
        msg = (
            "🔔 *Proactive Telegram Alerts Resumed*\n\n"
            "• Autonomous push alerts, dynamic delay shifts, and step-out alarms are now active.\n"
            "💡 Use `/mute` anytime if you need to silence notifications."
        )
        self.bot.send_message(msg, chat_id=chat_id)

    def cmd_help(self, chat_id: Optional[str] = None) -> None:
        msg = (
            f"🚆 *RailRadar Commute Bot — 16 Command Suite*\n"
            f"Autonomous transit intelligence for Hosur <-> ETV Bangalore\n\n"
            f"📋 *Live Operations & Status*:\n"
            f"• `/status` — Live commute state & active train countdown\n"
            f"• `/morning` — Scan 07:30 - 09:30 AM corridor & recommendations\n"
            f"• `/evening` — Scan evening return corridor & desk advisories\n"
            f"• `/train <no>` — Live running status & delay of any train\n"
            f"• `/track <no>` — Set active train for dynamic tracking\n\n"
            f"🔍 *Deep Inspection & Analytics*:\n"
            f"• `/rake` — Inspect incoming rake 66595 & turnaround departure\n"
            f"• `/delays` — View 14-day P10/P50/P90 delay quantiles\n"
            f"• `/eta <no>` — Full station-by-station ETA schedule\n"
            f"• `/station <code>` — View timetable for HSRA, CRLM, or BLRR\n"
            f"• `/milestones` — View departure milestone triggers (e.g. 16232 @ BNC)\n\n"
            f"⚙️ *Overrides & Controls*:\n"
            f"• `/mute` — Emergency kill switch: mute all proactive alerts\n"
            f"• `/unmute` — Resume autonomous proactive alerts\n"
            f"• `/reached` — Pause tracking for the day (sleeps until next commute)\n"
            f"• `/wfh` — Mark today as Work From Home (pauses alerts)\n"
            f"• `/bike` — Switch today's mode to Bike/Road commute\n"
            f"• `/reset` — Reset daily tracking state machine\n"
            f"• `/help` — Display this interactive guide"
        )
        self.bot.send_message(msg, chat_id=chat_id)

    def cmd_status(self, chat_id: Optional[str] = None) -> None:
        st = self.store.state_data
        state = st.get("state", STATE_NIGHT_SLEEP)
        now_str = get_ist_now().strftime("%H:%M")
        alerts_label = "🔔 ACTIVE" if st.get("alerts_enabled", True) else "🔕 MUTED"

        if state == STATE_WEEKEND_REST:
            msg = (
                f"🏖️ *RailRadar Live Status — Weekend Rest*\n\n"
                f"• *State Machine*: `WEEKEND_REST` (Silent Mode)\n"
                f"• *Alerts Master*: {alerts_label}\n"
                f"• *Status*: Weekend rest mode active. Autonomous commute prompts & proactive delay alerts are paused.\n"
                f"• *Next Commute*: Monday morning at *06:45 AM* (Morning Corridor Scan)\n"
                f"• *Corridor Trains*: 06278 (07:07), 66596 (08:26), 16212 (08:54)\n"
                f"• *Current Time*: {now_str} IST\n\n"
                f"💡 _Tip: Interactive commands like `/train <no>`, `/rake`, `/station <stn>`, `/delays`, and `/eta` remain fully functional._"
            )
        elif state == STATE_MIDDAY_STANDBY:
            evening_train = st.get("evening_train", "16232")
            sched = rail_tracker.CORRIDOR_SCHEDULES.get(evening_train, {})
            train_title = sched.get("train_name", "Return Train")
            msg = (
                f"🏢 *RailRadar Live Status — Midday Standby*\n\n"
                f"• *State Machine*: `MIDDAY_STANDBY` (Desk / Office Mode)\n"
                f"• *Alerts Master*: {alerts_label}\n"
                f"• *Morning Inbound*: Completed ✅\n"
                f"• *Tracking Mode*: Standby (zero poll / battery consumption while at desk)\n"
                f"• *Next Window*: Evening Return Corridor (15:30 – 22:00)\n"
                f"• *Default Return Train*: *{evening_train}* ({train_title})\n"
                f"• *Next Scheduled Check-In*: 14:00 PM (Corridor Preview)\n"
                f"• *Current Time*: {now_str} IST\n\n"
                f"💡 _Tip: Use `/evening` to browse all return trains, or `/train {evening_train}` for current position._"
            )
        elif state == STATE_NIGHT_SLEEP:
            wake_target = "Today" if now_str < "06:45" else "Tomorrow"
            msg = (
                f"🌙 *RailRadar Live Status — Overnight Hibernation*\n\n"
                f"• *State Machine*: `NIGHT_SLEEP` (Deep Hibernation)\n"
                f"• *Alerts Master*: {alerts_label}\n"
                f"• *Status*: Commute windows closed for the night. Silent mode active (zero notifications).\n"
                f"• *Next Wake-Up*: {wake_target} at *06:45 AM* (Morning Corridor Scan)\n"
                f"• *Corridor Trains*: 06278 (07:07), 66596 (08:26), 16212 (08:54)\n"
                f"• *Current Time*: {now_str} IST\n\n"
                f"💡 _Tip: Send `/morning` to preview tomorrow's schedule, or `/reset` to force daytime mode._"
            )
        elif state in (STATE_WFH, STATE_BIKE, STATE_HIBERNATION):
            mode_name = "Work From Home" if state == STATE_WFH else ("Bike Commute" if state == STATE_BIKE else "Reached Destination")
            msg = (
                f"⏸️ *RailRadar Live Status — Tracking Paused*\n\n"
                f"• *State Machine*: `{state}` ({mode_name})\n"
                f"• *Alerts Master*: {alerts_label}\n"
                f"• *Status*: Tracking paused for today by user action.\n"
                f"• *Notes*: {st.get('notes', 'No alerts will be sent.')}\n"
                f"• *Current Time*: {now_str} IST\n\n"
                f"💡 _Tip: Send `/reset` to resume autonomous tracking at any time._"
            )
        elif "EVENING" in state:
            active_train = st.get("evening_train", "16232")
            status = rail_tracker.get_live_train_status(active_train)
            msg = (
                f"🌆 *RailRadar Live Status — Evening Return*\n\n"
                f"• *State Machine*: `{state}`\n"
                f"• *Alerts Master*: {alerts_label}\n"
                f"• *Active Train*: *{active_train}* ({status.get('train_name', '')})\n"
                f"• *Current Location*: {status.get('current_station_name', '')} ({status.get('current_station', '')})\n"
                f"• *Live Delay*: *{status.get('delay_minutes', 0)} mins*\n"
                f"• *Boarding Station*: Carmelaram (CRLM) / Bellandur Road (BLRR)\n"
                f"• *Destination*: Hosur (HSRA)\n"
                f"• *Milestone Fired*: {'Yes' if st.get('evening_milestone_fired') else 'Pending'}\n"
                f"• *Data Source*: `{status.get('source', 'CRIS')}`\n"
                f"• *Last Updated*: {status.get('last_updated', '')}"
            )
        else: # Morning Tracking or Morning Prompt
            active_train = st.get("morning_train", rail_tracker.MORNING_TRAIN_MEMU)
            status = rail_tracker.get_live_train_status(active_train)
            msg = (
                f"🌅 *RailRadar Live Status — Morning Inbound*\n\n"
                f"• *State Machine*: `{state}`\n"
                f"• *Alerts Master*: {alerts_label}\n"
                f"• *Active Train*: *{active_train}* ({status.get('train_name', '')})\n"
                f"• *Current Location*: {status.get('current_station_name', '')} ({status.get('current_station', '')})\n"
                f"• *Live Delay*: *{status.get('delay_minutes', 0)} mins*\n"
                f"• *Projected Hosur Dep*: {st.get('morning_projected_dep', '08:25')}\n"
                f"• *Step-Out Time*: *{st.get('morning_step_out_time', '08:15')} AM*\n"
                f"• *Data Source*: `{status.get('source', 'CRIS')}`\n"
                f"• *Last Updated*: {status.get('last_updated', '')}"
            )
        self.bot.send_message(msg, chat_id=chat_id)

    def cmd_morning(self, chat_id: Optional[str] = None) -> None:
        scan = rail_tracker.scan_morning_commute_options()
        rec = scan["recommended_train"]
        rake = scan["rake_turnaround"]

        msg = (
            f"🌅 *Morning Multi-Train Opportunity Scan*\n\n"
            f"💡 *Top Recommendation*: *{rec['train_name']} ({rec['train_no']})*\n"
            f"└ {scan['recommendation_reason']}\n\n"
            f"• *Projected Departure*: ~*{rec['projected_departure']} AM*\n"
            f"• *Step-Out Time*: ~*{rec['step_out_time']} AM* (10m lead time)\n"
            f"• *Arrival at BLRR*: ~*{rec['dest_eta']} AM*\n"
            f"• *ETA at Desk (ETV)*: ~*{rec['desk_eta']} AM* (30m buffer)\n\n"
            f"🔄 *Incoming Rake 66595*: {rake['rake_current_station_name']} | Delay: {rake['rake_delay_mins']}m\n"
        )
        self.bot.send_message(msg, chat_id=chat_id, reply_markup=self.get_morning_keyboard())

    def cmd_evening(self, chat_id: Optional[str] = None) -> None:
        options = rail_tracker.scan_evening_commute_options()
        msg = f"🌆 *Evening Commute Options (ETV -> Hosur)*\n\n"
        for opt in options:
            msg += (
                f"• *{opt['train_no']}* ({opt['boarding_station']})\n"
                f"  └ Est Dep: *{opt['estimated_departure']}* | Delay: {opt['delay_mins']}m\n"
                f"  └ 🏃 Leave Desk: *{opt['leave_desk_time']}* ({opt['lead_time_mins']}m lead)\n"
                f"  └ HSRA Arrival: ~{opt['hosur_eta']}\n\n"
            )
        self.bot.send_message(msg, chat_id=chat_id, reply_markup=self.get_evening_keyboard())

    def cmd_train(self, train_no: str, chat_id: Optional[str] = None) -> None:
        status = rail_tracker.get_live_train_status(train_no)
        msg = (
            f"🚆 *Live Status: Train {train_no}*\n"
            f"*{status.get('train_name')}*\n\n"
            f"• *Status*: {status.get('current_status')}\n"
            f"• *Current Station*: {status.get('current_station_name')} ({status.get('current_station')})\n"
            f"• *Live Delay*: *{status.get('delay_minutes')} mins*\n"
            f"• *Source*: `{status.get('source')}`\n"
            f"• *Timestamp*: {status.get('last_updated')}"
        )
        self.bot.send_message(msg, chat_id=chat_id)

    def cmd_track(self, train_no: str, chat_id: Optional[str] = None) -> None:
        t_no = str(train_no).strip()
        state = self.store.state_data["state"]
        now_time = get_ist_now().strftime("%H:%M")

        sched = rail_tracker.CORRIDOR_SCHEDULES.get(t_no, {})
        is_evening = (
            sched.get("direction") == "EVENING"
            or t_no in ("66585", "16211", "66583", "16232", "16527", "16236")
            or "EVENING" in state
            or ("13:00" <= now_time < "23:30" and not ("06:00" <= now_time < "12:00"))
        )

        if is_evening:
            self.store.state_data["evening_train"] = t_no
            self.store.state_data["user_manually_selected_train"] = True
            self.store.transition_state(STATE_EVENING_TRACKING, f"User tracking evening train {t_no}")
        else:
            self.store.state_data["morning_train"] = t_no
            self.store.state_data["user_manually_selected_train"] = True
            if "06:45" <= now_time < "09:40":
                self.store.transition_state(STATE_MORNING_TRACKING, f"User tracking morning train {t_no}")
            elif "09:40" <= now_time < "14:00":
                self.store.transition_state(STATE_MIDDAY_STANDBY, f"User set morning train {t_no}; midday standby")
            elif "14:00" <= now_time < "15:30":
                self.store.transition_state(STATE_EVENING_PROMPT, f"User set morning train {t_no}; evening window")
            elif "15:30" <= now_time < "23:30":
                self.store.transition_state(STATE_EVENING_TRACKING, f"User set morning train {t_no}; evening tracking")
            else:
                self.store.transition_state(STATE_NIGHT_SLEEP, f"User set morning train {t_no}; night sleep")

        self.bot.send_message(f"✅ Now tracking Train *{t_no}*. Dynamic alerts and departure countdowns are active.", chat_id=chat_id)

    def cmd_rake(self, chat_id: Optional[str] = None) -> None:
        rake = rail_tracker.inspect_rake_turnaround("66596", "66595")
        msg = (
            f"🔍 *Rake Turnaround Inspector: 66595 -> 66596*\n\n"
            f"• *Incoming Train*: 66595 (YPR -> HSRA)\n"
            f"• *Current Location*: {rake['rake_current_station_name']} ({rake['rake_current_station']})\n"
            f"• *Incoming Delay*: {rake['rake_delay_mins']} mins\n"
            f"• *Hosur ETA*: ~{rake['rake_eta_hsra']}\n\n"
            f"• *Outgoing Train*: 66596 (HSRA -> YPR)\n"
            f"• *Scheduled Departure*: {rake['scheduled_hsra_departure']}\n"
            f"• *Projected Turnaround Dep*: *{rake['projected_hsra_departure']}*\n"
            f"• *Dynamic Step-Out*: *{rake['revised_step_out_time']} AM* (10m lead time)\n\n"
            f"📢 *Summary*: {rake['delay_summary']}"
        )
        self.bot.send_message(msg, chat_id=chat_id)

    def cmd_delays(self, chat_id: Optional[str] = None) -> None:
        stats = rail_tracker.load_delay_statistics()
        msg = f"📊 *14-Day Empirical Punctuality Analytics*\n\n"
        if not stats:
            msg += (
                "Telemetry data initializing... Serving default corridor baseline:\n"
                "• *66596* (Hosur MEMU | BLRR): P50: *5m* | P90: *20m* | On-Time: *75%*\n"
                "• *16212* (Salem Exp | BLRR): P50: *12m* | P90: *35m* | On-Time: *65%*\n"
                "• *06278* (Dharmapuri MEMU | BLRR): P50: *8m* | P90: *25m* | On-Time: *70%*\n"
                "• *16232* (Mailaduturai Exp | CRLM): P50: *10m* | P90: *30m* | On-Time: *68%*\n"
            )
        else:
            for t_no, info in stats.items():
                label = info.get("label", f"Train {t_no}")
                stns = info.get("stations", {})
                stn_key = "BLRR" if "BLRR" in stns else ("CRLM" if "CRLM" in stns else next(iter(stns.keys()), ""))
                s_data = stns.get(stn_key, {})
                if s_data:
                    msg += (
                        f"• *{t_no}* ({label[:18]} | {stn_key}):\n"
                        f"  P50: *{s_data.get('P50', 0):.0f}m* | P90: *{s_data.get('P90', 0):.0f}m* | On-Time: *{s_data.get('OnTimePct', 0):.0f}%*\n"
                    )
        self.bot.send_message(msg, chat_id=chat_id)

    def cmd_wfh(self, chat_id: Optional[str] = None) -> None:
        self.store.transition_state(STATE_WFH, "User marked Work From Home")
        self.bot.send_message("🏠 Today marked as *Work From Home*. Rail tracking and step-out alarms paused for today.", chat_id=chat_id)

    def cmd_bike(self, chat_id: Optional[str] = None) -> None:
        self.store.transition_state(STATE_BIKE, "User commuting via Bike")
        self.bot.send_message("🏍️ Commute mode switched to *Bike / Road*. Ride safe on Attibele / Electronic City flyover!", chat_id=chat_id)

    def cmd_stay(self, chat_id: Optional[str] = None) -> None:
        self.store.transition_state(STATE_HIBERNATION, "User staying late / Bangalore")
        self.bot.send_message("🏠 Staying late confirmed. Evening train tracking paused for tonight.", chat_id=chat_id)

    def cmd_station(self, station_code: str, chat_id: Optional[str] = None) -> None:
        raw_stn = station_code.upper().strip()
        stn = rail_tracker.STATION_CODE_ALIASES.get(raw_stn, raw_stn)
        matched = []
        for t_no, sched in rail_tracker.CORRIDOR_SCHEDULES.items():
            for s in sched.get("stations", []):
                if s["code"] == stn:
                    matched.append((t_no, sched["train_name"], s.get("sta"), s.get("std")))

        if not matched:
            self.bot.send_message(f"No scheduled corridor trains found for station `{station_code}`.", chat_id=chat_id)
            return

        msg = f"🚉 *Station Timetable: {stn}*\n\n"
        for t_no, name, sta, std in matched:
            msg += f"• *{t_no}* {name[:20]}: Arr {sta} | Dep {std}\n"
        self.bot.send_message(msg, chat_id=chat_id)

    def cmd_eta(self, train_no: str, chat_id: Optional[str] = None) -> None:
        status = rail_tracker.get_live_train_status(train_no)
        stations = status.get("stations", [])
        msg = f"⏱️ *Station ETAs for Train {train_no}*\n\n"
        if not stations:
            msg += "Live station telemetry currently loading or train not on run.\n"
        else:
            for s in stations[:8]:
                arr_flag = "✅" if s.get("has_departed") else ("🟡" if s.get("has_arrived") else "⏳")
                s_code = s.get("code", "")
                s_name = s.get("name", "")[:14]
                s_sta = s.get("sta", "--")
                s_eta = s.get("eta", s_sta)
                s_delay = s.get("effective_delay", 0)
                msg += f"{arr_flag} *{s_code}* ({s_name}): STA {s_sta} -> ETA *{s_eta}* (+{s_delay}m)\n"
        self.bot.send_message(msg, chat_id=chat_id)

    def cmd_milestones(self, chat_id: Optional[str] = None) -> None:
        msg = (
            f"🎯 *Configured Evening Commute Milestones*\n\n"
            f"• *Train 16232 (Mailaduturai Express)*:\n"
            f"  └ Milestone: *Bangalore Cant (BNC)*\n"
            f"  └ Scheduled BNC Dep: 19:10 -> Carmelaram (CRLM) Arr: 19:35\n"
            f"  └ Action: Departure from BNC triggers *'LEAVE DESK NOW'* notification to JPMorgan Chase Parcel 5 desk (25m lead time).\n\n"
            f"• *Train 66585 (MEMU 15:48)*:\n"
            f"  └ Milestone: *Baiyyappanahalli (BYPL)* (Dep: 15:40)\n"
            f"  └ Boarding: Bellandur Road (BLRR) at 15:48 (+11m walk advantage)\n"
        )
        self.bot.send_message(msg, chat_id=chat_id)

    def cmd_reached(self, chat_id: Optional[str] = None) -> None:
        st = self.store.state_data
        curr_state = st.get("state", "")
        if "MORNING" in curr_state:
            st["morning_completed"] = True
            self.store.transition_state(STATE_MIDDAY_STANDBY, "User reached destination (morning)")
            msg = (
                "🎉 *Destination Reached!*\n\n"
                "Morning commute completed. Tracking is now paused in *MIDDAY_STANDBY*.\n"
                "I will check in with you at *02:00 PM* for your evening return options. Have a productive shift at ETV!"
            )
        else:
            st["evening_completed"] = True
            self.store.transition_state(STATE_HIBERNATION, "User reached home (evening)")
            msg = (
                "🏠 *Welcome Home to Hosur!*\n\n"
                "Commute tracking is officially *paused for the day*.\n"
                "State entered: `HIBERNATION`. Zero alerts will be sent tonight. Sleep well!"
            )
        self.bot.send_message(msg, chat_id=chat_id)

    def cmd_reset(self, chat_id: Optional[str] = None) -> None:
        self.store.reset_today()
        now_ist = get_ist_now()
        current_time = now_ist.strftime("%H:%M")
        if now_ist.weekday() in (5, 6):
            init_state = STATE_WEEKEND_REST
        elif "06:45" <= current_time < "07:30":
            init_state = STATE_MORNING_PROMPT
        elif "07:30" <= current_time < "09:40":
            init_state = STATE_MORNING_TRACKING
        elif "09:40" <= current_time < "14:00":
            init_state = STATE_MIDDAY_STANDBY
        elif "14:00" <= current_time < "15:30":
            init_state = STATE_EVENING_PROMPT
        elif "15:30" <= current_time < "23:30":
            init_state = STATE_EVENING_TRACKING
        else:
            init_state = STATE_NIGHT_SLEEP
        self.store.transition_state(init_state, f"Reset initialized for {current_time} IST (Weekday: {now_ist.weekday()})")
        self.bot.send_message(f"🔄 Daily commute state reset back to default ({init_state}). Next scheduled trigger according to time of day.", chat_id=chat_id)

    # -------------------------------------------------------------------------
    # Telegram Update Polling & Inline Callback Router
    # -------------------------------------------------------------------------

    def process_telegram_updates(self) -> None:
        updates = self.bot.get_updates(offset=self.update_offset, timeout=2)
        for u in updates:
            self.update_offset = u["update_id"] + 1

            # 1. Message command
            if "message" in u:
                msg = u["message"]
                text = msg.get("text", "")
                chat_id = str(msg.get("chat", {}).get("id", ""))
                if text.startswith("/"):
                    self.execute_command(text, chat_id=chat_id)
                elif text.strip().lower() in ("reached", "status", "morning", "evening", "wfh", "bike", "help", "delays", "rake", "stay", "mute", "unmute", "pause", "resume"):
                    self.execute_command("/" + text.strip().lower(), chat_id=chat_id)

            # 2. Inline Callback Query
            elif "callback_query" in u:
                cb = u["callback_query"]
                cb_id = cb["id"]
                data = cb.get("data", "")
                chat_id = str(cb.get("message", {}).get("chat", {}).get("id", ""))

                self.bot.answer_callback(cb_id, text="Received!")

                if data.startswith("train:") or data.startswith("track:"):
                    train_no = data.split(":", 1)[1]
                    self.cmd_track(train_no, chat_id=chat_id)
                elif data in ("action:mute", "action:mute_alerts"):
                    self.cmd_mute(chat_id=chat_id)
                elif data in ("action:unmute", "action:unmute_alerts"):
                    self.cmd_unmute(chat_id=chat_id)
                elif data == "action:wfh":
                    self.cmd_wfh(chat_id=chat_id)
                elif data == "action:bike":
                    self.cmd_bike(chat_id=chat_id)
                elif data == "action:stay":
                    self.cmd_stay(chat_id=chat_id)
                elif data == "action:reached":
                    self.cmd_reached(chat_id=chat_id)
                elif data == "action:morning_scan":
                    self.cmd_morning(chat_id=chat_id)
                elif data == "action:skip":
                    self.store.transition_state(STATE_MIDDAY_STANDBY, "Skipped morning check-in")
                    self.bot.send_message("⏭️ Morning alerts skipped.", chat_id=chat_id)
                elif data == "action:refresh":
                    self.cmd_status(chat_id=chat_id)

    # -------------------------------------------------------------------------
    # Daemon Tick & Adaptive Polling
    # -------------------------------------------------------------------------

    def determine_poll_interval(self, current_time: str) -> int:
        state = self.store.state_data["state"]

        if state in (STATE_WFH, STATE_BIKE, STATE_HIBERNATION, STATE_WEEKEND_REST):
            return POLL_TIER_STANDBY

        if state == STATE_NIGHT_SLEEP:
            return POLL_TIER_HIBERNATE

        if "MORNING" in state:
            step_out = self.store.state_data.get("morning_step_out_time", "08:15")
            proj_dep = self.store.state_data.get("morning_projected_dep", "08:25")
            diff_to_step_out = rail_tracker.minutes_difference(current_time, step_out)
            diff_to_dep = rail_tracker.minutes_difference(current_time, proj_dep)

            # Critical window: within 20 mins before step-out, or between step-out and departure + 10m
            if (-10 <= diff_to_dep <= 30) or (0 <= diff_to_step_out <= 20):
                return POLL_TIER_CRITICAL   # 30s in critical window
            elif 20 < diff_to_step_out <= 60 or 0 <= diff_to_dep <= 60:
                return POLL_TIER_APPROACH   # 60s in approach
            return POLL_TIER_STANDBY

        if "EVENING" in state:
            # Check proximity to 18:30 - 22:00 milestone window
            if "18:30" <= current_time <= "22:00":
                return POLL_TIER_CRITICAL
            return POLL_TIER_APPROACH

        if "23:30" <= current_time or current_time < "06:45":
            return POLL_TIER_HIBERNATE

        return POLL_TIER_STANDBY

    def step(self, now: Optional[datetime] = None) -> int:
        """Single tick of the daemon state machine. Returns sleep duration."""
        if now is None:
            now = get_ist_now()
        current_time = now.strftime("%H:%M")
        is_weekend = now.weekday() in (5, 6)
        state = self.store.state_data["state"]
        now_ts = time.time()

        # Check for day rollover
        today_str = now.strftime("%Y-%m-%d")
        if self.store.state_data.get("date") != today_str:
            logger.info("Day rollover detected. Resetting commute state for %s", today_str)
            self.store.reset_today()
            state = self.store.state_data["state"]

        # 1. State Machine Transitions based on Wall-Clock Time (IST) & Weekend Check
        if is_weekend:
            if state != STATE_WEEKEND_REST:
                self.store.transition_state(STATE_WEEKEND_REST, f"Weekend rest mode ({now.strftime('%A')})")
                state = STATE_WEEKEND_REST
        else:
            # Weekday Transitions: if recovering from weekend rest on Monday
            if state == STATE_WEEKEND_REST:
                if "06:45" <= current_time < "07:30":
                    state = STATE_MORNING_PROMPT
                elif "07:30" <= current_time < "09:40":
                    state = STATE_MORNING_TRACKING
                elif "09:40" <= current_time < "14:00":
                    state = STATE_MIDDAY_STANDBY
                elif "14:00" <= current_time < "15:30":
                    state = STATE_EVENING_PROMPT
                elif "15:30" <= current_time < "23:30":
                    state = STATE_EVENING_TRACKING
                else:
                    state = STATE_NIGHT_SLEEP
                self.store.transition_state(state, "Resumed weekday commute schedule")

            if "06:45" <= current_time < "07:30":
                if state in (STATE_NIGHT_SLEEP, STATE_HIBERNATION):
                    self.store.transition_state(STATE_MORNING_PROMPT, "Morning window opened")
                    state = STATE_MORNING_PROMPT

            elif "07:30" <= current_time < "09:40":
                if state in (STATE_MORNING_PROMPT, STATE_NIGHT_SLEEP):
                    self.store.transition_state(STATE_MORNING_TRACKING, "Active morning tracking")
                    state = STATE_MORNING_TRACKING

            elif "09:40" <= current_time < "14:00":
                if state not in (STATE_MIDDAY_STANDBY, STATE_WFH, STATE_BIKE):
                    self.store.transition_state(STATE_MIDDAY_STANDBY, "Midday standby window")
                    state = STATE_MIDDAY_STANDBY

            elif "14:00" <= current_time < "15:30":
                if state not in (STATE_EVENING_PROMPT, STATE_EVENING_TRACKING, STATE_WFH, STATE_BIKE) and not self.store.state_data.get("evening_prompt_sent"):
                    self.store.transition_state(STATE_EVENING_PROMPT, "Evening window opened")
                    state = STATE_EVENING_PROMPT

            elif "15:30" <= current_time < "23:30":
                if state not in (STATE_EVENING_TRACKING, STATE_HIBERNATION, STATE_WFH, STATE_BIKE):
                    self.store.transition_state(STATE_EVENING_TRACKING, "Active evening tracking")
                    state = STATE_EVENING_TRACKING

            elif "23:30" <= current_time or current_time < "06:45":
                if state not in (STATE_NIGHT_SLEEP, STATE_WFH, STATE_BIKE):
                    self.store.transition_state(STATE_NIGHT_SLEEP, "Night sleep mode")
                    state = STATE_NIGHT_SLEEP

        # Determine poll interval based on updated state
        poll_interval = self.determine_poll_interval(current_time)

        # 2. Execute State Logic if interval elapsed OR if initial prompt is pending
        should_track = (now_ts - self.last_track_poll_time) >= poll_interval
        if state == STATE_MORNING_PROMPT and not self.store.state_data.get("morning_prompt_sent") and "06:45" <= current_time <= "09:30":
            should_track = True
        elif state == STATE_EVENING_PROMPT and not self.store.state_data.get("evening_prompt_sent") and "14:00" <= current_time <= "18:00":
            should_track = True

        if should_track:
            self.last_track_poll_time = now_ts
            if state == STATE_WEEKEND_REST:
                # Proactive push alerts are completely suppressed on weekends
                pass
            elif state == STATE_MORNING_PROMPT:
                if "06:45" <= current_time <= "09:30":
                    self.handle_morning_prompt(current_time, now=now)
                else:
                    logger.warning("Prevented handle_morning_prompt execution: time is %s (outside 06:45 - 09:30 IST)", current_time)
                    if "09:30" < current_time < "09:40":
                        self.store.transition_state(STATE_MORNING_TRACKING, "Auto-correction to morning tracking")
                        state = STATE_MORNING_TRACKING
                    elif "09:40" <= current_time < "14:00":
                        self.store.transition_state(STATE_MIDDAY_STANDBY, "Auto-correction to midday standby")
                        state = STATE_MIDDAY_STANDBY
                    elif "14:00" <= current_time < "15:30":
                        self.store.transition_state(STATE_EVENING_PROMPT, "Auto-correction to evening prompt")
                        state = STATE_EVENING_PROMPT
                    elif "15:30" <= current_time < "23:30":
                        self.store.transition_state(STATE_EVENING_TRACKING, "Auto-correction to evening tracking")
                        state = STATE_EVENING_TRACKING
                    else:
                        self.store.transition_state(STATE_NIGHT_SLEEP, "Auto-correction to night sleep")
                        state = STATE_NIGHT_SLEEP
            elif state == STATE_MORNING_TRACKING:
                if current_time < "09:40":
                    self.handle_morning_tracking(current_time, now=now)
                else:
                    self.store.state_data["morning_completed"] = True
                    self.store.transition_state(STATE_MIDDAY_STANDBY, "Morning commute window closed")
                    state = STATE_MIDDAY_STANDBY
            elif state == STATE_EVENING_PROMPT:
                self.handle_evening_prompt(current_time, now=now)
            elif state == STATE_EVENING_TRACKING:
                self.handle_evening_tracking(current_time, now=now)

            # Check watchdog fail-safe (suppressed during weekend rest or when alerts muted)
            if state != STATE_WEEKEND_REST:
                pending_wd = rail_tracker.watchdog.get_pending_alert()
                if pending_wd and pending_wd.get("triggered"):
                    if self.store.state_data.get("alerts_enabled", True):
                        self.bot.send_message(pending_wd["message"])
                    else:
                        logger.info("Suppressed watchdog fail-safe alert push: Alerts are muted (alerts_enabled=False)")

        # 3. Always poll for Telegram user interactions
        self.process_telegram_updates()

        # 4. Return Adaptive Interval
        return poll_interval

    def run_forever(self) -> None:
        logger.info("RailRadar Commute Daemon starting up for @SriTrainBot (Chat: %s)", self.bot.default_chat_id)
        while self.running:
            try:
                sleep_sec = self.step()
                time.sleep(min(sleep_sec, 10))  # Step frequently enough to catch user commands
            except KeyboardInterrupt:
                logger.info("Daemon stopped by user.")
                break
            except Exception as exc:
                logger.error("Unhandled error in daemon loop: %s", exc, exc_info=True)
                time.sleep(10)


if __name__ == "__main__":
    daemon = RailDaemon()
    daemon.run_forever()
