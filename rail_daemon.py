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
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
import urllib.parse
import urllib.request

# Ensure workspace is in sys.path
root_dir = os.path.dirname(os.path.abspath(__file__))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

import rail_tracker

logger = logging.getLogger("rail_daemon")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# =============================================================================
# 1. CONFIGURATION & CONSTANTS
# =============================================================================

DEFAULT_BOT_TOKEN = "9074983932:AAFEZubE34Mw4ORMPgJsRJgsjrH6DEyqFZU"
DEFAULT_CHAT_ID = "716060462"

# Strict Isolation: Only use TRAIN_BOT_TOKEN or RAIL_TELEGRAM_BOT_TOKEN.
# NEVER fall back to PriceTracker's TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID.
TELEGRAM_BOT_TOKEN = os.getenv("TRAIN_BOT_TOKEN") or os.getenv("RAIL_TELEGRAM_BOT_TOKEN") or DEFAULT_BOT_TOKEN
TELEGRAM_CHAT_ID = os.getenv("TRAIN_CHAT_ID") or os.getenv("RAIL_TELEGRAM_CHAT_ID") or DEFAULT_CHAT_ID

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

# Adaptive Polling Tiers (in seconds)
POLL_TIER_CRITICAL = 30     # < 20 mins to step-out / milestone
POLL_TIER_APPROACH = 60     # 20 - 60 mins
POLL_TIER_STANDBY = 900     # Midday / > 60 mins (15 minutes)
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
        self.token = token
        self.default_chat_id = default_chat_id
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    def send_message(
        self,
        text: str,
        chat_id: Optional[str] = None,
        reply_markup: Optional[Dict[str, Any]] = None,
        parse_mode: str = "Markdown",
    ) -> Optional[Dict[str, Any]]:
        target_chat = chat_id or self.default_chat_id
        if not target_chat:
            logger.warning("No chat_id configured for Telegram notification.")
            return None

        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": target_chat,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
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
            logger.error("Failed to send Telegram message: %s", exc)
            return None

    def edit_message(
        self,
        message_id: int,
        text: str,
        chat_id: Optional[str] = None,
        reply_markup: Optional[Dict[str, Any]] = None,
        parse_mode: str = "Markdown",
    ) -> Optional[Dict[str, Any]]:
        target_chat = chat_id or self.default_chat_id
        url = f"{self.base_url}/editMessageText"
        payload = {
            "chat_id": target_chat,
            "message_id": message_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
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
            logger.error("Failed to edit Telegram message: %s", exc)
            return None

    def answer_callback(self, callback_query_id: str, text: Optional[str] = None) -> bool:
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

    def __init__(self, file_path: str = LOCAL_STATE_FILE):
        self.file_path = file_path
        self.state_data = self._load()

    def _get_today_str(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

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
            "notes": "",
            "last_updated": datetime.now().isoformat(),
        }

    def _load(self) -> Dict[str, Any]:
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("date") == self._get_today_str():
                        return data
            except Exception as e:
                logger.error("Error reading local state: %s", e)
        return self._default_state()

    def save(self, sync_supabase: bool = False) -> None:
        """Write to local file, and optionally sync to Supabase on state transitions."""
        self.state_data["last_updated"] = datetime.now().isoformat()
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
                "date": self.state_data["date"],
                "state": self.state_data["state"],
                "morning_train": self.state_data["morning_train"],
                "morning_step_out_time": self.state_data["morning_step_out_time"],
                "morning_revised_dep": self.state_data["morning_projected_dep"],
                "morning_delay_mins": self.state_data["morning_delay_mins"],
                "morning_status": "COMPLETED" if self.state_data["morning_completed"] else "ACTIVE",
                "evening_train": self.state_data["evening_train"],
                "evening_milestone_fired": self.state_data["evening_milestone_fired"],
                "evening_status": "COMPLETED" if self.state_data["evening_completed"] else "ACTIVE",
                "notes": self.state_data["notes"],
                "last_updated": self.state_data["last_updated"],
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

    def handle_morning_prompt(self, current_time: str) -> None:
        """Triggered at 06:45 AM: Send morning options overview."""
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

        self.bot.send_message(msg, reply_markup=self.get_morning_keyboard())
        self.store.state_data["morning_prompt_sent"] = True
        self.store.save()

    def handle_morning_tracking(self, current_time: str) -> None:
        """
        Continuously tracks Train 66596 and incoming rake 66595 (or active selected train).
        Dynamically shifts step-out alert and sends delay notifications if delayed.
        """
        active_train = self.store.state_data.get("morning_train", rail_tracker.MORNING_TRAIN_MEMU)
        
        # 1. Evaluate Rake Turnaround & Morning Scanner
        scan = rail_tracker.scan_morning_commute_options(reference_time=current_time)
        active_opt = next((o for o in scan["options"] if o["train_no"] == active_train), scan["options"][0])
        rec_opt = scan["recommended_train"]
        rake = scan["rake_turnaround"]

        projected_dep = active_opt["projected_departure"]
        step_out_time = active_opt["step_out_time"]
        current_delay = active_opt["delay_mins"]

        # Update daily store state
        self.store.state_data["morning_projected_dep"] = projected_dep
        self.store.state_data["morning_step_out_time"] = step_out_time
        self.store.state_data["morning_delay_mins"] = current_delay

        last_reported_delay = self.store.state_data.get("last_delay_reported", 0)
        last_reported_step_out = self.store.state_data.get("last_step_out_reported", "08:15")

        # 2. Check if delay changed noticeably (>= 3 minutes shift)
        if abs(current_delay - last_reported_delay) >= 3 or (current_delay > 0 and last_reported_delay == 0):
            # Proactive Delay Alert Requirement:
            # "Wait, that shouldnt be the case right? Lets say if the other memu is delayed, you need to recommend
            # that memu train to me, I want the last delayed one, and also, if it is delayed, you'll be notifying with the delay,
            # like later, send a message saying hey there is a delay, the train is stil at here, so possible delay."
            if current_delay > last_reported_delay:
                extra_mins = current_delay - last_reported_delay
                time_note = f"⏳ Departure delayed by an additional *{extra_mins} mins*. You have an extra *{extra_mins} mins* at home! Relax."
            elif current_delay < last_reported_delay:
                made_up = last_reported_delay - current_delay
                time_note = f"⚡ Train made up *{made_up} mins*! Departure moved EARLIER to ~*{projected_dep} AM*. New step-out: ~*{step_out_time} AM*. Prepare to leave sooner!"
            else:
                time_note = f"ℹ️ Revised departure from Hosur is ~*{projected_dep} AM* (Step-out: ~*{step_out_time} AM*)."

            rake_loc_str = f"*{rake.get('rake_current_station_name', 'En route')}* ({rake.get('rake_current_station', '')})"
            delay_msg = (
                f"⚠️ *Commute Delay Alert: Train {active_train}*\n\n"
                f"Hey Sriram, there is a delay! Incoming rake ({rake.get('incoming_rake_train', '66595')}) is still near {rake_loc_str}, so possible delay from Hosur.\n"
                f"• *Current Delay*: *{current_delay} mins*\n"
                f"• *Revised Hosur Departure*: ~*{projected_dep} AM*\n"
                f"• *New Step-Out Time*: ~*{step_out_time} AM* (was {last_reported_step_out})\n\n"
                f"{time_note}"
            )
            
            # If an earlier delayed train (e.g. 06278 or 16212) becomes a better recommendation
            if rec_opt["train_no"] != active_train and rec_opt["status"] in ("VIABLE", "BOARDING"):
                delay_msg += (
                    f"\n\n💡 *Alternative Available*: Train *{rec_opt['train_no']}* departs at ~*{rec_opt['projected_departure']}* "
                    f"and reaches BLRR by *{rec_opt['dest_eta']}* (Desk: {rec_opt['desk_eta']})."
                )
                kb = {
                    "inline_keyboard": [
                        [{"text": f"🚆 Switch to {rec_opt['train_no']}", "callback_data": f"train:{rec_opt['train_no']}"}],
                        [{"text": "Stay with MEMU", "callback_data": "action:ack"}],
                    ]
                }
                self.bot.send_message(delay_msg, reply_markup=kb)
            else:
                self.bot.send_message(delay_msg)

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
            self.bot.send_message(alert_msg, reply_markup=self.get_stepped_out_keyboard())
            self.store.state_data["morning_stepped_out"] = True
            self.store.save(sync_supabase=True)

        # 4. Check Morning Completion: When train departs Hosur or time passes 09:40
        if current_time >= "09:40" or rail_tracker.minutes_difference(projected_dep, current_time) > 15:
            self.store.state_data["morning_completed"] = True
            self.store.transition_state(STATE_MIDDAY_STANDBY, "Morning commute completed")

    # -------------------------------------------------------------------------
    # Evening Lifecycle Logic
    # -------------------------------------------------------------------------

    def handle_evening_prompt(self, current_time: str) -> None:
        """Triggered at 14:00 PM: Evening commute check-in."""
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
        self.bot.send_message(msg, reply_markup=self.get_evening_keyboard())
        self.store.state_data["evening_prompt_sent"] = True
        self.store.transition_state(STATE_EVENING_PROMPT, "Sent 14:00 PM evening check-in")

    def handle_evening_tracking(self, current_time: str) -> None:
        """
        Monitors evening train (e.g. 16232) and checks milestone triggers
        (e.g. Train 16232 clearing BNC -> 'LEAVE DESK NOW').
        """
        active_train = self.store.state_data.get("evening_train", "16232")
        status = rail_tracker.get_live_train_status(active_train)

        # Milestone Check
        if not self.store.state_data.get("evening_milestone_fired"):
            milestone = rail_tracker.check_evening_milestone_trigger(active_train, status)
            if milestone and milestone.get("triggered"):
                self.bot.send_message(milestone["message"])
                self.store.state_data["evening_milestone_fired"] = True
                self.store.save(sync_supabase=True)

        # Check if train has departed CRLM/BLRR or passed 22:30
        crlm_stn = next((s for s in status.get("stations", []) if s["code"] == rail_tracker.STN_CARMELARAM), None)
        if crlm_stn and crlm_stn["has_departed"]:
            if not self.store.state_data.get("evening_completed"):
                self.bot.send_message(f"🚆 Train {active_train} is en route to Hosur. Enjoy the ride home!")
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
        elif cmd == "/reset":
            self.cmd_reset(chat_id)
        else:
            self.bot.send_message(f"❓ Unknown command `{cmd}`. Use /help to see all 14 available commands.", chat_id=chat_id)

    def cmd_help(self, chat_id: Optional[str] = None) -> None:
        msg = (
            f"🚆 *RailRadar Commute Bot — 14 Command Suite*\n"
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
            f"• `/reached` — Pause tracking for the day (sleeps until next commute)\n"
            f"• `/wfh` — Mark today as Work From Home (pauses alerts)\n"
            f"• `/bike` — Switch today's mode to Bike/Road commute\n"
            f"• `/reset` — Reset daily tracking state machine\n"
            f"• `/help` — Display this interactive guide"
        )
        self.bot.send_message(msg, chat_id=chat_id)

    def cmd_status(self, chat_id: Optional[str] = None) -> None:
        st = self.store.state_data
        active_train = st.get("morning_train" if "MORNING" in st["state"] else "evening_train", "66596")
        status = rail_tracker.get_live_train_status(active_train)

        msg = (
            f"📡 *RailRadar Live Status*\n\n"
            f"• *State Machine*: `{st['state']}`\n"
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
        now_time = datetime.now().strftime("%H:%M")

        sched = rail_tracker.CORRIDOR_SCHEDULES.get(t_no, {})
        is_evening = (
            sched.get("direction") == "EVENING"
            or t_no in ("66585", "16211", "66583", "16232", "16527", "16236")
            or "EVENING" in state
            or ("13:00" <= now_time < "23:00" and not ("06:00" <= now_time < "12:00"))
        )

        if is_evening:
            self.store.state_data["evening_train"] = t_no
            self.store.transition_state(STATE_EVENING_TRACKING, f"User tracking evening train {t_no}")
        else:
            self.store.state_data["morning_train"] = t_no
            self.store.transition_state(STATE_MORNING_TRACKING, f"User tracking morning train {t_no}")

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

    def cmd_station(self, station_code: str, chat_id: Optional[str] = None) -> None:
        stn = station_code.upper().strip()
        matched = []
        for t_no, sched in rail_tracker.CORRIDOR_SCHEDULES.items():
            for s in sched.get("stations", []):
                if s["code"] == stn:
                    matched.append((t_no, sched["train_name"], s.get("sta"), s.get("std")))

        if not matched:
            self.bot.send_message(f"No scheduled corridor trains found for station `{stn}`.", chat_id=chat_id)
            return

        msg = f"🚉 *Station Timetable: {stn}*\n\n"
        for t_no, name, sta, std in matched:
            msg += f"• *{t_no}* {name[:20]}: Arr {sta} | Dep {std}\n"
        self.bot.send_message(msg, chat_id=chat_id)

    def cmd_eta(self, train_no: str, chat_id: Optional[str] = None) -> None:
        status = rail_tracker.get_live_train_status(train_no)
        stations = status.get("stations", [])
        msg = f"⏱️ *Station ETAs for Train {train_no}*\n\n"
        for s in stations[:8]:
            arr_flag = "✅" if s["has_departed"] else ("🟡" if s["has_arrived"] else "⏳")
            msg += f"{arr_flag} *{s['code']}* ({s['name'][:14]}): STA {s['sta']} -> ETA *{s['eta']}* (+{s['effective_delay']}m)\n"
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
        self.bot.send_message("🔄 Daily commute state reset back to default. Next scheduled trigger: 06:45 AM.", chat_id=chat_id)

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
                elif text.strip().lower() in ("reached", "status", "morning", "evening", "wfh", "bike", "help", "delays", "rake"):
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
                elif data == "action:wfh":
                    self.cmd_wfh(chat_id=chat_id)
                elif data == "action:bike":
                    self.cmd_bike(chat_id=chat_id)
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

        if state in (STATE_WFH, STATE_BIKE, STATE_HIBERNATION):
            return POLL_TIER_STANDBY

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

        if "22:30" <= current_time or current_time < "06:45":
            return POLL_TIER_HIBERNATE

        return POLL_TIER_STANDBY

    def step(self) -> int:
        """Single tick of the daemon state machine. Returns sleep duration."""
        now = datetime.now()
        current_time = now.strftime("%H:%M")
        state = self.store.state_data["state"]
        now_ts = time.time()
        poll_interval = self.determine_poll_interval(current_time)

        # Check for day rollover
        today_str = now.strftime("%Y-%m-%d")
        if self.store.state_data.get("date") != today_str:
            logger.info("Day rollover detected. Resetting commute state for %s", today_str)
            self.store.reset_today()
            state = self.store.state_data["state"]

        # 1. State Machine Transitions based on Wall-Clock Time
        if "06:45" <= current_time < "07:30":
            if state in (STATE_NIGHT_SLEEP, STATE_HIBERNATION):
                self.store.transition_state(STATE_MORNING_PROMPT, "Morning window opened")
                state = STATE_MORNING_PROMPT

        elif "07:30" <= current_time < "09:40":
            if state in (STATE_MORNING_PROMPT, STATE_NIGHT_SLEEP):
                self.store.transition_state(STATE_MORNING_TRACKING, "Active morning tracking")
                state = STATE_MORNING_TRACKING

        elif "09:40" <= current_time < "14:00":
            if state in (STATE_MORNING_TRACKING, STATE_MORNING_PROMPT):
                self.store.transition_state(STATE_MIDDAY_STANDBY, "Midday standby")
                state = STATE_MIDDAY_STANDBY

        elif "14:00" <= current_time < "15:30":
            if state == STATE_MIDDAY_STANDBY and not self.store.state_data.get("evening_prompt_sent"):
                self.store.transition_state(STATE_EVENING_PROMPT, "Evening window opened")
                state = STATE_EVENING_PROMPT

        elif "15:30" <= current_time < "22:30":
            if state in (STATE_EVENING_PROMPT, STATE_MIDDAY_STANDBY):
                self.store.transition_state(STATE_EVENING_TRACKING, "Active evening tracking")
                state = STATE_EVENING_TRACKING

        elif "22:30" <= current_time or current_time < "06:45":
            if state != STATE_NIGHT_SLEEP:
                self.store.transition_state(STATE_NIGHT_SLEEP, "Night sleep mode")
                state = STATE_NIGHT_SLEEP

        # 2. Execute State Logic if interval elapsed
        should_track = (now_ts - self.last_track_poll_time) >= poll_interval
        if should_track:
            self.last_track_poll_time = now_ts
            if state == STATE_MORNING_PROMPT:
                self.handle_morning_prompt(current_time)
            elif state == STATE_MORNING_TRACKING:
                self.handle_morning_tracking(current_time)
            elif state == STATE_EVENING_PROMPT:
                self.handle_evening_prompt(current_time)
            elif state == STATE_EVENING_TRACKING:
                self.handle_evening_tracking(current_time)

            # Check watchdog fail-safe
            pending_wd = rail_tracker.watchdog.get_pending_alert()
            if pending_wd and pending_wd.get("triggered"):
                self.bot.send_message(pending_wd["message"])

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
