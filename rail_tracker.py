"""rail_tracker.py — Railway Intelligence & Live Commute Engine.

Features:
- Direct CRIS NTES Wire Protocol (AES-128-CBC PKCS7 + MD5 signature + legacy SSL)
- Robust delay and station parsing (handling '**UA**', computing ETAs)
- Multi-tier fallback (CRIS Wire -> Scrapling ConfirmTkt -> Empirical Static Schedule)
- Rake Turnaround Inspector (tracking incoming rake 66595 to predict 66596 departure)
- Morning Multi-Train Opportunity Scanner (07:30 - 09:30 HSRA -> BLRR/CRLM corridor)
- Evening Commute Tracker & Desk Departure Milestones (BLRR/CRLM -> HSRA)
- 14-Day P10 / P50 / P90 delay quantile analytics & punctuality metrics
- 2-Strike Watchdog fail-safe monitor with 1-tap manual check links
"""

from __future__ import annotations

import base64
import binascii
import concurrent.futures
import hashlib
import json
import logging
import os
import re
import ssl
import threading
import time
import urllib.parse
import urllib.request
import math
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

IST_TZ = timezone(timedelta(hours=5, minutes=30))


def get_ist_now() -> datetime:
    """Return current datetime in Indian Standard Time (IST, UTC+05:30)."""
    return datetime.now(timezone.utc).astimezone(IST_TZ)

try:
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
    CRYPTOGRAPHY_AVAILABLE = False
    padding = None
    Cipher = None
    algorithms = None
    modes = None

logger = logging.getLogger("rail_tracker")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# =============================================================================
# 1. CORE CONSTANTS & COMMUTE CONFIGURATION
# =============================================================================

CRIS_KEY = b"8EA4DB2CC1EB3DC5"
CRIS_IV = b"7DC5EB3BB4DB6EA8"
CRIS_SCKEY = "645fbc1e56e23365f2f3c204ae0899f6"
CRIS_URL = "https://enquiry.indianrail.gov.in/crisns/AppServAnd"

# Commute lead times & buffers (in minutes)
LEAD_TIME_HOME_HOSUR = 10       # 5m walk + 5m buffer from Gangaiya Venkatachalapathy St to PF1
LEAD_TIME_DESK_CRLM = 25        # 25m from ETV JPMC Parcel 5 to Carmelaram PF1
LEAD_TIME_DESK_BLRR = 20        # 20m from ETV JPMC Parcel 5 to Bellandur Road PF1
WALK_TIME_BLRR_DESK = 30        # 2.2 km walk from BLRR to ETV desk (~30 mins)
RAKE_TURNAROUND_MIN_BUFFER = 10 # Minimum turnaround time needed at Hosur platform for MEMU

# Target Stations
STN_HOSUR = "HSRA"
STN_BELLANDUR = "BLRR"
STN_CARMELARAM = "CRLM"
STN_BNC = "BNC"
STN_SBC = "SBC"
STN_BYPL = "BYPL"
STN_YPR = "YPR"

# Morning corridor trains from Hosur
MORNING_TRAIN_MEMU = "66596"
INCOMING_RAKE_MEMU = "66595"
MORNING_TRAIN_EARLIER_MEMU = "06278"
MORNING_TRAIN_EXP = "16212"

# State Constants
STATE_WEEKEND_REST = "WEEKEND_REST"


def is_weekend(dt: Optional[datetime] = None) -> bool:
    """Return True if the specified datetime (or current IST datetime) is a weekend (Saturday=5, Sunday=6)."""
    if dt is None:
        dt = get_ist_now()
    return dt.weekday() in (5, 6)


# Global switch for fast offline fallback without network I/O
ALLOW_NETWORK: bool = True

# Minimum physical transit times (in minutes) to Hosur (HSRA) from corridor stations
MIN_TRANSIT_TO_HSRA_66595: Dict[str, int] = {
    "YPR": 80,
    "LOGH": 75,
    "HEB": 70,
    "BAND": 55,
    "BYPL": 50,
    "BLRR": 40,
    "CRLM": 35,
    "HLE": 25,
    "AEK": 15,
    "HSRA": 0,
}

MIN_TRANSIT_TO_HSRA_06278: Dict[str, int] = {
    "DPJ": 90,
    "PCV": 75,
    "MZU": 65,
    "RYC": 50,
    "PRNT": 25,
    "KMLM": 13,
    "HSRA": 0,
}

MIN_TRANSIT_TO_HSRA_16212: Dict[str, int] = {
    "SA": 150,
    "OML": 130,
    "SMDT": 120,
    "KVLR": 110,
    "TPP": 95,
    "MPC": 85,
    "SZV": 75,
    "DPJ": 50,
    "PCV": 40,
    "MZU": 35,
    "RYC": 25,
    "PRNT": 20,
    "KMLM": 13,
    "HSRA": 0,
}

STATION_CODE_ALIASES: Dict[str, str] = {
    "BELANDUR ROAD": "BLRR",
    "BELLANDUR ROAD": "BLRR",
    "BELLANDUR": "BLRR",
    "BELANDUR": "BLRR",
    "CARMELARAM": "CRLM",
    "CARMELARAM RAILWAY STATION": "CRLM",
    "HOSUR": "HSRA",
    "BANGALORE CANT": "BNC",
    "BENGALURU CANT": "BNC",
    "BENGALURU CANTONMENT": "BNC",
    "BANGALORE CANTONMENT": "BNC",
    "KSR BENGALURU": "SBC",
    "BANGALORE CITY": "SBC",
    "BENGALURU CITY": "SBC",
    "SBC": "SBC",
    "BAIYAPPANAHALLI": "BYPL",
    "BAIYYAPPANAHALLI": "BYPL",
    "YESVANTPUR": "YPR",
    "YESVANTPUR JN": "YPR",
    "YESHWANTHPUR": "YPR",
    "DHARMAPURI": "DPJ",
    "SALEM": "SA",
    "SALEM JN": "SA",
}

# Static Corridor Schedules
CORRIDOR_SCHEDULES: Dict[str, Dict[str, Any]] = {
    "06278": {
        "train_no": "06278",
        "train_name": "Dharmapuri - KSR Bengaluru MEMU",
        "direction": "MORNING",
        "origin": "DPJ",
        "destination": "SBC",
        "milestone_station": "KMLM",
        "stations": [
            {"code": "DPJ", "name": "DHARMAPURI", "sta": "Source", "std": "05:00", "halt": 0, "day": 1},
            {"code": "PCV", "name": "PALAKKODU", "sta": "05:21", "std": "05:22", "halt": 1, "day": 1},
            {"code": "MZU", "name": "MARANDAHALLI", "sta": "05:34", "std": "05:35", "halt": 1, "day": 1},
            {"code": "RYC", "name": "RAYAKKOTTAI", "sta": "05:51", "std": "05:52", "halt": 1, "day": 1},
            {"code": "KMLM", "name": "KELAMANGALAM", "sta": "06:12", "std": "06:13", "halt": 1, "day": 1},
            {"code": "HSRA", "name": "HOSUR", "sta": "07:05", "std": "07:07", "halt": 2, "day": 1},
            {"code": "AEK", "name": "ANEKAL ROAD", "sta": "07:22", "std": "07:23", "halt": 1, "day": 1},
            {"code": "HLE", "name": "HEELALIGE", "sta": "07:33", "std": "07:34", "halt": 1, "day": 1},
            {"code": "CRLM", "name": "CARMELARAM", "sta": "07:44", "std": "07:45", "halt": 1, "day": 1},
            {"code": "BLRR", "name": "BELANDUR ROAD", "sta": "07:51", "std": "07:52", "halt": 1, "day": 1},
            {"code": "BYPL", "name": "BAIYAPPANAHALLI", "sta": "08:08", "std": "08:10", "halt": 2, "day": 1},
            {"code": "BNCE", "name": "BENGALURU EAST", "sta": "08:15", "std": "08:16", "halt": 1, "day": 1},
            {"code": "BNC", "name": "BANGALORE CANT", "sta": "08:24", "std": "08:25", "halt": 1, "day": 1},
            {"code": "SBC", "name": "KSR BENGALURU", "sta": "08:50", "std": "Destination", "halt": 0, "day": 1},
        ],
    },
    "66596": {
        "train_no": "66596",
        "train_name": "Hosur - Yesvantpur MEMU",
        "direction": "MORNING",
        "origin": "HSRA",
        "destination": "YPR",
        "rake_train": "66595",
        "stations": [
            {"code": "HSRA", "name": "HOSUR", "sta": "Source", "std": "08:25", "halt": 0, "day": 1},
            {"code": "AEK", "name": "ANEKAL ROAD", "sta": "08:37", "std": "08:38", "halt": 1, "day": 1},
            {"code": "HLE", "name": "HEELALIGE", "sta": "08:48", "std": "08:49", "halt": 1, "day": 1},
            {"code": "CRLM", "name": "CARMELARAM", "sta": "08:57", "std": "08:58", "halt": 1, "day": 1},
            {"code": "BLRR", "name": "BELANDUR ROAD", "sta": "09:03", "std": "09:04", "halt": 1, "day": 1},
            {"code": "BAND", "name": "BANASWADI", "sta": "09:15", "std": "09:16", "halt": 1, "day": 1},
            {"code": "HEB", "name": "HEBBAL", "sta": "09:26", "std": "09:27", "halt": 1, "day": 1},
            {"code": "LOGH", "name": "LOTTEGOLLAHALLI", "sta": "09:33", "std": "09:34", "halt": 1, "day": 1},
            {"code": "YPR", "name": "YESVANTPUR JN", "sta": "10:05", "std": "Destination", "halt": 0, "day": 1},
        ],
    },
    "66595": {
        "train_no": "66595",
        "train_name": "Yesvantpur - Hosur MEMU",
        "direction": "INCOMING_RAKE",
        "origin": "YPR",
        "destination": "HSRA",
        "stations": [
            {"code": "YPR", "name": "YESVANTPUR JN", "sta": "Source", "std": "06:10", "halt": 0, "day": 1},
            {"code": "LOGH", "name": "LOTTEGOLLAHALLI", "sta": "06:19", "std": "06:20", "halt": 1, "day": 1},
            {"code": "HEB", "name": "HEBBAL", "sta": "06:25", "std": "06:26", "halt": 1, "day": 1},
            {"code": "BAND", "name": "BANASWADI", "sta": "06:36", "std": "06:37", "halt": 1, "day": 1},
            {"code": "BLRR", "name": "BELANDUR ROAD", "sta": "06:49", "std": "06:50", "halt": 1, "day": 1},
            {"code": "CRLM", "name": "CARMELARAM", "sta": "06:54", "std": "06:55", "halt": 1, "day": 1},
            {"code": "HLE", "name": "HEELALIGE", "sta": "07:04", "std": "07:05", "halt": 1, "day": 1},
            {"code": "AEK", "name": "ANEKAL ROAD", "sta": "07:14", "std": "07:15", "halt": 1, "day": 1},
            {"code": "HSRA", "name": "HOSUR", "sta": "08:00", "std": "Destination", "halt": 0, "day": 1},
        ],
    },
    "16212": {
        "train_no": "16212",
        "train_name": "Salem - Yesvantpur Express",
        "direction": "MORNING",
        "origin": "SA",
        "destination": "YPR",
        "milestone_station": "KMLM",
        "stations": [
            {"code": "SA", "name": "SALEM JN", "sta": "Source", "std": "05:20", "halt": 0, "day": 1},
            {"code": "DPJ", "name": "DHARMAPURI", "sta": "06:38", "std": "06:40", "halt": 2, "day": 1},
            {"code": "KMLM", "name": "KELAMANGALAM", "sta": "08:04", "std": "08:05", "halt": 1, "day": 1},
            {"code": "HSRA", "name": "HOSUR", "sta": "08:18", "std": "08:20", "halt": 2, "day": 1},
            {"code": "CRLM", "name": "CARMELARAM", "sta": "08:52", "std": "08:53", "halt": 1, "day": 1},
            {"code": "BLRR", "name": "BELANDUR ROAD", "sta": "08:59", "std": "09:00", "halt": 1, "day": 1},
            {"code": "BYPL", "name": "BAIYAPPANAHALLI", "sta": "09:11", "std": "09:12", "halt": 1, "day": 1},
            {"code": "BAND", "name": "BANASWADI", "sta": "09:21", "std": "09:22", "halt": 1, "day": 1},
            {"code": "HEB", "name": "HEBBAL", "sta": "09:34", "std": "09:35", "halt": 1, "day": 1},
            {"code": "YPR", "name": "YESVANTPUR JN", "sta": "10:10", "std": "Destination", "halt": 0, "day": 1},
        ],
    },
    "66585": {
        "train_no": "66585",
        "train_name": "Yesvantpur - Hosur MEMU",
        "direction": "EVENING",
        "origin": "YPR",
        "destination": "HSRA",
        "milestone_station": "BAND",
        "stations": [
            {"code": "YPR", "name": "YESVANTPUR JN", "sta": "Source", "std": "15:00", "halt": 0, "day": 1},
            {"code": "LOGH", "name": "LOTTEGOLLAHALLI", "sta": "15:09", "std": "15:10", "halt": 1, "day": 1},
            {"code": "HEB", "name": "HEBBAL", "sta": "15:15", "std": "15:16", "halt": 1, "day": 1},
            {"code": "BAND", "name": "BANASWADI", "sta": "15:26", "std": "15:27", "halt": 1, "day": 1},
            {"code": "BLRR", "name": "BELANDUR ROAD", "sta": "15:42", "std": "15:43", "halt": 1, "day": 1},
            {"code": "CRLM", "name": "CARMELARAM", "sta": "15:47", "std": "15:48", "halt": 1, "day": 1},
            {"code": "HLE", "name": "HEELALIGE", "sta": "15:58", "std": "15:59", "halt": 1, "day": 1},
            {"code": "AEK", "name": "ANEKAL ROAD", "sta": "16:08", "std": "16:09", "halt": 1, "day": 1},
            {"code": "HSRA", "name": "HOSUR", "sta": "16:34", "std": "Destination", "halt": 0, "day": 1},
        ],
    },
    "16211": {
        "train_no": "16211",
        "train_name": "Yesvantpur - Salem Express",
        "direction": "EVENING",
        "origin": "YPR",
        "destination": "SA",
        "milestone_station": "BAND",
        "stations": [
            {"code": "YPR", "name": "YESVANTPUR JN", "sta": "Source", "std": "15:55", "halt": 0, "day": 1},
            {"code": "LOGH", "name": "LOTTEGOLLAHALLI", "sta": "16:04", "std": "16:05", "halt": 1, "day": 1},
            {"code": "HEB", "name": "HEBBAL", "sta": "16:10", "std": "16:11", "halt": 1, "day": 1},
            {"code": "BAND", "name": "BANASWADI", "sta": "16:21", "std": "16:22", "halt": 1, "day": 1},
            {"code": "BLRR", "name": "BELANDUR ROAD", "sta": "16:35", "std": "16:36", "halt": 1, "day": 1},
            {"code": "CRLM", "name": "CARMELARAM", "sta": "16:41", "std": "16:42", "halt": 1, "day": 1},
            {"code": "HLE", "name": "HEELALIGE", "sta": "16:52", "std": "16:53", "halt": 1, "day": 1},
            {"code": "AEK", "name": "ANEKAL ROAD", "sta": "17:02", "std": "17:03", "halt": 1, "day": 1},
            {"code": "HSRA", "name": "HOSUR", "sta": "17:19", "std": "17:35", "halt": 2, "day": 1},
        ],
    },
    "66583": {
        "train_no": "66583",
        "train_name": "KSR Bengaluru - Dharmapuri MEMU",
        "direction": "EVENING",
        "origin": "SBC",
        "destination": "DPJ",
        "milestone_station": "BNC",
        "stations": [
            {"code": "SBC", "name": "KSR BENGALURU", "sta": "Source", "std": "18:25", "halt": 0, "day": 1},
            {"code": "BNC", "name": "BANGALORE CANT", "sta": "18:34", "std": "18:35", "halt": 1, "day": 1},
            {"code": "BYPL", "name": "BAIYAPPANAHALLI", "sta": "18:44", "std": "18:45", "halt": 1, "day": 1},
            {"code": "BLRR", "name": "BELANDUR ROAD", "sta": "18:54", "std": "18:55", "halt": 1, "day": 1},
            {"code": "CRLM", "name": "CARMELARAM", "sta": "18:59", "std": "19:00", "halt": 1, "day": 1},
            {"code": "HLE", "name": "HEELALIGE", "sta": "19:10", "std": "19:11", "halt": 1, "day": 1},
            {"code": "AEK", "name": "ANEKAL ROAD", "sta": "19:20", "std": "19:21", "halt": 1, "day": 1},
            {"code": "HSRA", "name": "HOSUR", "sta": "19:34", "std": "19:35", "halt": 1, "day": 1},
        ],
    },
    "16232": {
        "train_no": "16232",
        "train_name": "Mailaduturai Express",
        "direction": "EVENING",
        "origin": "SBC",
        "destination": "MV",
        "milestone_station": "BNC",
        "stations": [
            {"code": "SBC", "name": "KSR BENGALURU", "sta": "Source", "std": "19:00", "halt": 0, "day": 1},
            {"code": "BNC", "name": "BANGALORE CANT", "sta": "19:08", "std": "19:10", "halt": 2, "day": 1},
            {"code": "CRLM", "name": "CARMELARAM", "sta": "19:34", "std": "19:35", "halt": 1, "day": 1},
            {"code": "HSRA", "name": "HOSUR", "sta": "20:08", "std": "20:30", "halt": 2, "day": 1},
        ],
    },
    "16527": {
        "train_no": "16527",
        "train_name": "Yesvantpur - Kannur Express",
        "direction": "EVENING",
        "origin": "YPR",
        "destination": "CAN",
        "milestone_station": "BAND",
        "stations": [
            {"code": "YPR", "name": "YESVANTPUR JN", "sta": "Source", "std": "20:00", "halt": 0, "day": 1},
            {"code": "BAND", "name": "BANASWADI", "sta": "20:20", "std": "20:21", "halt": 1, "day": 1},
            {"code": "CRLM", "name": "CARMELARAM", "sta": "20:45", "std": "20:46", "halt": 1, "day": 1},
            {"code": "HSRA", "name": "HOSUR", "sta": "21:35", "std": "21:37", "halt": 2, "day": 1},
        ],
    },
    "16236": {
        "train_no": "16236",
        "train_name": "Tuticorin Express",
        "direction": "EVENING",
        "origin": "SBC",
        "destination": "TN",
        "milestone_station": "BNC",
        "stations": [
            {"code": "SBC", "name": "KSR BENGALURU", "sta": "Source", "std": "21:15", "halt": 0, "day": 1},
            {"code": "BNC", "name": "BANGALORE CANT", "sta": "21:26", "std": "21:28", "halt": 2, "day": 1},
            {"code": "CRLM", "name": "CARMELARAM", "sta": "21:50", "std": "21:51", "halt": 1, "day": 1},
            {"code": "HSRA", "name": "HOSUR", "sta": "22:50", "std": "22:52", "halt": 2, "day": 1},
        ],
    },
}

# =============================================================================
# 2. CRYPTOGRAPHIC ENGINE FOR CRIS NTES WIRE PROTOCOL
# =============================================================================

def encrypt_cris_payload(data_str: str) -> str:
    """Encrypt payload string using AES-128-CBC with PKCS7 padding and return hex string."""
    if not CRYPTOGRAPHY_AVAILABLE or padding is None or Cipher is None:
        raise RuntimeError("cryptography package is required for CRIS AES encryption")
    padder = padding.PKCS7(128).padder()
    padded = padder.update(data_str.encode("utf-8")) + padder.finalize()
    cipher = Cipher(algorithms.AES(CRIS_KEY), modes.CBC(CRIS_IV))
    encryptor = cipher.encryptor()
    ct = encryptor.update(padded) + encryptor.finalize()
    b64 = base64.b64encode(ct)
    return binascii.hexlify(b64).decode().upper()


def decrypt_cris_payload(enc_str: str) -> str:
    """Decrypt CRIS NTES response string from hex/base64 AES-128-CBC."""
    if not CRYPTOGRAPHY_AVAILABLE or padding is None or Cipher is None:
        raise RuntimeError("cryptography package is required for CRIS AES decryption")
    if "#" in enc_str:
        enc_str = enc_str.split("#", 1)[1]
    raw = binascii.unhexlify(enc_str)
    b64 = raw.decode("utf-8", errors="ignore")
    cipher_bytes = base64.b64decode(b64)
    cipher = Cipher(algorithms.AES(CRIS_KEY), modes.CBC(CRIS_IV))
    decryptor = cipher.decryptor()
    padded = decryptor.update(cipher_bytes) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    data = unpadder.update(padded) + unpadder.finalize()
    return data.decode("utf-8")


def query_cris(payload_str: str, timeout: int = 5) -> dict:
    """Directly query the Indian Railways CRIS NTES endpoint."""
    h = hashlib.md5((payload_str + CRIS_SCKEY).encode()).hexdigest().upper()
    wire = f"{h}#{encrypt_cris_payload(payload_str)}"
    body = json.dumps({"jsonIn": wire}).encode("utf-8")

    ctx = ssl.create_default_context()
    try:
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
    except Exception:
        pass

    req = urllib.request.Request(
        CRIS_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "charset": "utf-8",
            "User-Agent": "Dalvik/2.1.0 (Linux; Android 11)",
        },
    )
    with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
        resp_data = resp.read().decode("utf-8")
        resp_json = json.loads(resp_data)
        enc_out = resp_json.get("jsonIn") or resp_json.get("response") or ""
        if not enc_out:
            raise ValueError(f"Empty encrypted payload from CRIS: {resp_json}")
        decrypted = decrypt_cris_payload(enc_out)
        return json.loads(decrypted)


# =============================================================================
# 3. ROBUST DELAY, TIME, & STATION PARSING
# =============================================================================

def parse_delay_minutes(val: Any) -> int:
    """Parse delay values like '00:07', '01:15', 'On Time', 'Right Time', None, 15 into integer minutes."""
    if val is None or val == "":
        return 0
    if isinstance(val, (int, float)):
        return int(val)
    s = str(val).strip()
    if not s or s.lower() in ("on time", "right time", "rt", "none", "0"):
        return 0
    
    # Check for HH:MM format (positive or negative)
    neg = False
    if s.startswith("-"):
        neg = True
        s = s[1:].strip()
    
    if ":" in s:
        parts = s.split(":")
        try:
            mins = int(parts[0]) * 60 + int(parts[1])
            return -mins if neg else mins
        except Exception:
            pass

    # Check for text patterns e.g. "1 hr 15 min" or "25 mins"
    hr_match = re.search(r"(\d+)\s*(?:hr|hour)", s, re.IGNORECASE)
    min_match = re.search(r"(\d+)\s*(?:min|m)", s, re.IGNORECASE)
    if hr_match or min_match:
        hrs = int(hr_match.group(1)) if hr_match else 0
        mns = int(min_match.group(1)) if min_match else 0
        total = hrs * 60 + mns
        return -total if neg else total

    try:
        return int(float(s))
    except Exception:
        return 0


def clean_time_str(time_val: Any) -> str:
    """Extract clean HH:MM from strings like '08:25 13-Nov', '08:25:00', '7:5', or 'Source'."""
    if not time_val:
        return ""
    s = str(time_val).strip()
    m = re.search(r"(\d{1,2}):(\d{1,2})", s)
    if m:
        try:
            h, mn = int(m.group(1)), int(m.group(2))
            if 0 <= h <= 23 and 0 <= mn <= 59:
                return f"{h:02d}:{mn:02d}"
        except Exception:
            pass
    return s


def format_ampm(time_val: Any) -> str:
    """Format HH:MM into a clean AM/PM string, e.g. '08:25' -> '08:25 AM', '12:15' -> '12:15 PM'."""
    clean = clean_time_str(time_val)
    if not clean or ":" not in clean:
        return str(time_val) if time_val else ""
    try:
        parts = clean.split(":")
        h = int(parts[0])
        suffix = "PM" if h >= 12 else "AM"
        return f"{clean} {suffix}"
    except Exception:
        return clean


def add_minutes_to_time(base_time: str, minutes_to_add: int) -> str:
    """Add minutes to HH:MM string and return updated HH:MM."""
    clean = clean_time_str(base_time)
    if not clean or ":" not in clean:
        return base_time
    try:
        parts = clean.split(":")
        base_dt = datetime(2026, 1, 1, int(parts[0]), int(parts[1]))
        res_dt = base_dt + timedelta(minutes=int(minutes_to_add))
        return res_dt.strftime("%H:%M")
    except Exception:
        return base_time


def minutes_difference(t_from: str, t_to: str, allow_wraparound: bool = True) -> int:
    """Calculate signed minutes difference between t_from and t_to (t_to - t_from).
    Handles day wraparound when times cross midnight (e.g. 23:50 to 00:20 -> +30 mins; 00:20 to 23:50 -> -30 mins).
    Preserves true positive daytime differences (e.g. 08:00 to 21:15 -> +795 mins).
    """
    c1 = clean_time_str(t_from)
    c2 = clean_time_str(t_to)
    if not c1 or not c2 or ":" not in c1 or ":" not in c2:
        return 0
    try:
        p1 = [int(x) for x in c1.split(":")]
        p2 = [int(x) for x in c2.split(":")]
        diff = (p2[0] * 60 + p2[1]) - (p1[0] * 60 + p1[1])
        if allow_wraparound:
            if p1[0] >= 18 and p2[0] <= 6 and diff < 0:
                diff += 1440
            elif p1[0] <= 4 and p2[0] >= 20 and diff > 1200:
                diff -= 1440
        return diff
    except Exception:
        return 0


def resolve_eta(sta: str, eta_raw: Any, delay_mins: int) -> str:
    """Resolve ETAs when CRIS returns '**UA**' or unavailable by applying delay to STA."""
    clean_eta = clean_time_str(eta_raw)
    clean_sta = clean_time_str(sta)
    if clean_eta and clean_eta not in ("**UA**", "UA", "Source", "Destination") and ":" in clean_eta:
        return clean_eta
    if clean_sta and ":" in clean_sta:
        if delay_mins != 0:
            return add_minutes_to_time(clean_sta, delay_mins)
        return clean_sta
    return clean_sta or "On Schedule"


# =============================================================================
# 4. MULTI-TIER DATA EXTRACTION (CRIS -> CONFIRMTKT -> STATIC)
# =============================================================================

def normalize_station_entry(s: dict, running_delay: int = 0) -> dict:
    """Normalize station entries across CRIS and ConfirmTkt into a unified dictionary."""
    code = s.get("SC") or s.get("StationCode") or s.get("stnCode") or ""
    name = s.get("SN") or s.get("StationName") or s.get("stnName") or code

    # Canonical station code resolution using aliases
    clean_code = str(code).upper().strip()
    clean_name = str(name).strip()
    clean_name_upper = clean_name.upper()
    if clean_code in STATION_CODE_ALIASES:
        clean_code = STATION_CODE_ALIASES[clean_code]
    elif clean_name_upper in STATION_CODE_ALIASES:
        clean_code = STATION_CODE_ALIASES[clean_name_upper]
    elif not clean_code or len(clean_code) > 6:
        for alias_name, alias_code in STATION_CODE_ALIASES.items():
            if alias_name in clean_name_upper:
                clean_code = alias_code
                break

    sta_raw = s.get("STA") or s.get("ArrivalTime") or s.get("arr") or ""
    std_raw = s.get("STD") or s.get("DepartureTime") or s.get("dep") or ""
    eta_raw = s.get("ETA") or s.get("ExpectedArrivalTime") or ""
    etd_raw = s.get("ETD") or s.get("ExpectedDepartureTime") or ""
    
    darr_raw = s.get("DARR") or s.get("DelayInArrival") or s.get("arrDelay") or ""
    ddep_raw = s.get("DDEP") or s.get("DelayInDeparture") or s.get("depDelay") or ""
    
    delay_arr = parse_delay_minutes(darr_raw)
    delay_dep = parse_delay_minutes(ddep_raw)
    effective_delay = delay_dep or delay_arr or running_delay
    
    resolved_sta = clean_time_str(sta_raw)
    resolved_std = clean_time_str(std_raw)
    resolved_eta = resolve_eta(resolved_sta, eta_raw, effective_delay)
    resolved_etd = resolve_eta(resolved_std, etd_raw, effective_delay)
    
    has_arrived = bool(s.get("ISA") or s.get("HasArrived") or s.get("isArrived"))
    has_departed = bool(s.get("ISD") or s.get("HasDeparted") or s.get("isDeparted"))
    platform = str(s.get("PF") or s.get("Platform") or s.get("platform") or "1")

    return {
        "code": clean_code or code.upper().strip(),
        "name": clean_name or clean_code,
        "sta": resolved_sta,
        "std": resolved_std,
        "eta": resolved_eta,
        "etd": resolved_etd,
        "delay_arr": delay_arr,
        "delay_dep": delay_dep,
        "effective_delay": effective_delay,
        "has_arrived": has_arrived,
        "has_departed": has_departed,
        "platform": platform,
    }


def fetch_cris_status(train_no: str, date_str: Optional[str] = None) -> dict:
    """Fetch live running status directly from CRIS NTES Wire Protocol."""
    if not date_str:
        date_str = get_ist_now().strftime("%d-%b-%Y")
    payload = f"service=TrainRunningMob&subService=ShowFullRunJson&trainNo={train_no}&startDate={date_str}"
    raw = query_cris(payload)

    raw_stns = raw.get("STNS", [])
    stations = []
    last_known_delay = parse_delay_minutes(raw.get("LDEL", 0))
    
    for s in raw_stns:
        entry = normalize_station_entry(s, last_known_delay)
        stations.append(entry)
        if entry["has_departed"] or entry["has_arrived"]:
            last_known_delay = entry["effective_delay"]

    current_station = raw.get("LSTN") or (stations[0]["code"] if stations else "")
    current_station_name = raw.get("LSTNN") or (stations[0]["name"] if stations else "")
    current_status = raw.get("CPOS") or raw.get("LASTUPD") or f"Running with delay {last_known_delay} mins"

    return {
        "train_no": str(train_no),
        "train_name": raw.get("TNM") or f"Train {train_no}",
        "source": "CRIS_NTES",
        "current_station": current_station,
        "current_station_name": current_station_name,
        "current_status": current_status,
        "delay_minutes": last_known_delay,
        "last_updated": raw.get("LTIME") or get_ist_now().strftime("%H:%M"),
        "stations": stations,
        "raw": raw,
    }


def fetch_confirmtkt_status(train_no: str) -> dict:
    """Fetch live running status using ConfirmTkt fallback."""
    url = f"https://www.confirmtkt.com/train-running-status/{train_no}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        html = resp.read().decode("utf-8", errors="ignore")
    
    m = re.search(r"var\s+data\s*=\s*(\{.*?\});", html, re.DOTALL)
    if not m:
        raise ValueError(f"Could not parse JSON state from ConfirmTkt page for train {train_no}")
    
    data = json.loads(m.group(1))
    raw_stns = data.get("Schedule", []) or data.get("Stations", [])
    overall_delay = parse_delay_minutes(data.get("Delay", 0))

    stations = []
    last_delay = overall_delay
    for s in raw_stns:
        entry = normalize_station_entry(s, last_delay)
        stations.append(entry)
        if entry["has_departed"] or entry["has_arrived"]:
            last_delay = entry["effective_delay"]

    current_station = data.get("CurrentStationCode") or (stations[0]["code"] if stations else "")
    current_station_name = data.get("CurrentStationName") or (stations[0]["name"] if stations else "")
    current_status = data.get("CurrentPositionDetails") or f"Near {current_station_name} | Delay: {overall_delay}m"

    return {
        "train_no": str(train_no),
        "train_name": data.get("TrainName") or f"Train {train_no}",
        "source": "ConfirmTkt",
        "current_station": current_station,
        "current_station_name": current_station_name,
        "current_status": current_status,
        "delay_minutes": overall_delay,
        "last_updated": get_ist_now().strftime("%H:%M"),
        "stations": stations,
        "raw": data,
    }


def fetch_static_fallback_status(train_no: str, empirical_delay: int = 0) -> dict:
    """Return offline static schedule fallback when live scraping fails, seeded with empirical P50 delay."""
    sched = CORRIDOR_SCHEDULES.get(str(train_no))
    if not sched:
        return {
            "train_no": str(train_no),
            "train_name": f"Train {train_no}",
            "source": "STATIC_EMPTY",
            "current_station": "HSRA",
            "current_station_name": "HOSUR",
            "current_status": "Scheduled timetable (Static fallback)",
            "delay_minutes": empirical_delay,
            "last_updated": get_ist_now().strftime("%H:%M"),
            "stations": [],
        }

    stations = []
    for s in sched["stations"]:
        sta = s.get("sta", "")
        std = s.get("std", "")
        eta = add_minutes_to_time(sta, empirical_delay) if sta not in ("Source", "") else sta
        etd = add_minutes_to_time(std, empirical_delay) if std not in ("Destination", "") else std
        stations.append({
            "code": s["code"],
            "name": s["name"],
            "sta": sta,
            "std": std,
            "eta": eta,
            "etd": etd,
            "delay_arr": empirical_delay,
            "delay_dep": empirical_delay,
            "effective_delay": empirical_delay,
            "has_arrived": False,
            "has_departed": False,
            "platform": "1",
        })

    return {
        "train_no": str(train_no),
        "train_name": sched.get("train_name", f"Train {train_no}"),
        "source": "STATIC_FALLBACK",
        "current_station": stations[0]["code"] if stations else "HSRA",
        "current_station_name": stations[0]["name"] if stations else "HOSUR",
        "current_status": f"Scheduled timetable + {empirical_delay}m empirical P50 delay",
        "delay_minutes": empirical_delay,
        "last_updated": get_ist_now().strftime("%H:%M"),
        "stations": stations,
    }


class RailWatchdog:
    """2-Strike Watchdog monitor with circuit-breaker protection and fail-safe alerts."""

    def __init__(self, failure_threshold: int = 2, circuit_cooldown_seconds: float = 60.0):
        self._lock = threading.Lock()
        self.failure_threshold = failure_threshold
        self.circuit_cooldown_seconds = circuit_cooldown_seconds
        self.consecutive_failures = 0
        self.last_failure_reason = ""
        self.last_failure_timestamp = 0.0
        self.alert_triggered = False
        self._pending_alert: Optional[Dict[str, Any]] = None

    def is_circuit_open(self) -> bool:
        """Circuit breaker: If failures reach threshold within cooldown window, block network queries."""
        with self._lock:
            if self.consecutive_failures >= self.failure_threshold:
                if (time.time() - self.last_failure_timestamp) < self.circuit_cooldown_seconds:
                    return True
            return False

    def record_success(self) -> None:
        with self._lock:
            self.consecutive_failures = 0
            self.last_failure_reason = ""
            self.alert_triggered = False
            self._pending_alert = None

    def reset(self) -> None:
        """Reset watchdog failure counters and pending alerts."""
        self.record_success()

    def get_pending_alert(self) -> Optional[Dict[str, Any]]:
        """Retrieve and consume any pending watchdog fail-safe alert for Telegram dispatch."""
        with self._lock:
            alert = self._pending_alert
            if alert:
                self._pending_alert = None
                return alert
            return None

    def record_failure(self, train_no: str, error: Exception | str) -> Optional[Dict[str, Any]]:
        with self._lock:
            self.consecutive_failures += 1
            self.last_failure_timestamp = time.time()
            self.last_failure_reason = str(error)
            logger.warning(
                "RailWatchdog: Scraping failure #%d for train %s: %s",
                self.consecutive_failures,
                train_no,
                error,
            )

            if self.consecutive_failures >= self.failure_threshold and not self.alert_triggered:
                self.alert_triggered = True
                msg = (
                    f"⚠️ *RailRadar Watchdog Fail-Safe Triggered*\n"
                    f"Both Indian Railways CRIS NTES and ConfirmTkt were unresponsive after {self.consecutive_failures} consecutive queries.\n\n"
                    f"Falling back to *Empirical P50 Timetables*. Click below for 1-tap manual inspection:\n"
                    f"• [Direct CRIS NTES Portal](https://enquiry.indianrail.gov.in/crisns/)\n"
                    f"• [ConfirmTkt Live Status](https://www.confirmtkt.com/train-running-status/{train_no})\n"
                    f"• [Where Is My Train Live](https://www.whereismytrain.in/)"
                )
                alert_dict = {
                    "triggered": True,
                    "consecutive_failures": self.consecutive_failures,
                    "train_no": train_no,
                    "message": msg,
                    "links": [
                        {"label": "CRIS NTES", "url": "https://enquiry.indianrail.gov.in"},
                        {"label": "ConfirmTkt", "url": f"https://www.confirmtkt.com/train-running-status/{train_no}"},
                    ],
                }
                self._pending_alert = alert_dict
                return alert_dict
            return None


# Global watchdog instance
watchdog = RailWatchdog(failure_threshold=2)


_MAX_STATION_PROGRESS: Dict[str, dict] = {}  # train_no -> {"date": str, "idx": int, "station": str, "delay": int}


def _get_train_corridor_sequence(train_no: str) -> List[str]:
    """Return the ordered list of station codes for a train, including intermediate stops."""
    sched = CORRIDOR_SCHEDULES.get(train_no)
    if not sched:
        return []
    sched_codes = [s.get("code") for s in sched.get("stations", [])]
    if train_no == MORNING_TRAIN_EXP:  # 16212
        intermediate = list(MIN_TRANSIT_TO_HSRA_16212.keys())  # SA through HSRA
        post_hsra = [c for c in sched_codes if c not in intermediate]
        return intermediate + post_hsra
    elif train_no == MORNING_TRAIN_EARLIER_MEMU:  # 06278
        intermediate = list(MIN_TRANSIT_TO_HSRA_06278.keys())  # DPJ through HSRA
        post_hsra = [c for c in sched_codes if c not in intermediate]
        return intermediate + post_hsra
    return sched_codes


def _enforce_station_monotonicity(train_no: str, status: dict) -> dict:
    """
    Prevents scraper jitter where a train that has already passed advanced stations
    (e.g. PRNT or KMLM) suddenly jumps back to its origin station (e.g. SA with 0 delay).
    Station progress along the scheduled corridor can only monotonically advance.
    """
    if not status or not status.get("stations"):
        return status

    corridor_codes = _get_train_corridor_sequence(train_no)
    if not corridor_codes:
        return status

    curr_stn = status.get("current_station", "")
    if curr_stn not in corridor_codes:
        return status

    curr_idx = corridor_codes.index(curr_stn)
    today_str = get_ist_now().strftime("%Y-%m-%d")

    rec = _MAX_STATION_PROGRESS.get(train_no)
    if not rec or rec.get("date") != today_str:
        _MAX_STATION_PROGRESS[train_no] = {
            "date": today_str,
            "idx": curr_idx,
            "station": curr_stn,
            "delay": status.get("delay_minutes", 0),
        }
        return status

    max_idx = rec["idx"]
    if curr_idx < max_idx:
        logger.warning(
            "Detected backward station jump for train %s: reported %s (idx %d) < max %s (idx %d). Discarding jitter.",
            train_no,
            curr_stn,
            curr_idx,
            corridor_codes[max_idx],
            max_idx,
        )
        highest_code = corridor_codes[max_idx]
        status["current_station"] = highest_code
        status["current_station_name"] = highest_code
        if "delay" in rec:
            status["delay_minutes"] = max(status.get("delay_minutes", 0), rec["delay"])
        status["status"] = "In Transit"

        for s in status.get("stations", []):
            s_code = s.get("code")
            if s_code in corridor_codes and corridor_codes.index(s_code) < max_idx:
                s["has_departed"] = True
                s["has_arrived"] = True
    else:
        _MAX_STATION_PROGRESS[train_no] = {
            "date": today_str,
            "idx": curr_idx,
            "station": curr_stn,
            "delay": status.get("delay_minutes", 0),
        }

    return status


def get_live_train_status(train_no: str, date_str: Optional[str] = None) -> dict:
    """Multi-tier resolver: CRIS -> ConfirmTkt -> Static Schedule with Watchdog supervision."""
    train_no_str = str(train_no).strip()

    if ALLOW_NETWORK:
        if watchdog.is_circuit_open():
            logger.info("RailWatchdog circuit breaker OPEN for %s — bypassing network, serving empirical schedule", train_no_str)
        else:
            # Tier 1: CRIS NTES Wire Protocol
            try:
                status = fetch_cris_status(train_no_str, date_str)
                if status.get("stations") and len(status["stations"]) > 0:
                    watchdog.record_success()
                    return _enforce_station_monotonicity(train_no_str, status)
            except Exception as exc_cris:
                logger.warning("CRIS query failed for train %s: %s. Falling back to ConfirmTkt...", train_no_str, exc_cris)

            # Tier 2: ConfirmTkt Web Scrape
            try:
                status = fetch_confirmtkt_status(train_no_str)
                if status.get("stations") and len(status["stations"]) > 0:
                    watchdog.record_success()
                    return _enforce_station_monotonicity(train_no_str, status)
            except Exception as exc_ctkt:
                logger.warning("ConfirmTkt scrape failed for train %s: %s. Falling back to Static...", train_no_str, exc_ctkt)
                watchdog.record_failure(train_no_str, f"ConfirmTkt: {exc_ctkt}")

    # Tier 3: Static Empirical Fallback
    stats = get_train_delay_stats(train_no_str, STN_HOSUR)
    p50_delay = int(round(stats.get("P50", 0)))
    static_status = fetch_static_fallback_status(train_no_str, empirical_delay=p50_delay)
    if watchdog.alert_triggered:
        static_status["watchdog_alert"] = True
    return _enforce_station_monotonicity(train_no_str, static_status)


# =============================================================================
# 5. EMPIRICAL DELAY ANALYTICS & QUANTILES
# =============================================================================

DELAY_STATS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scratch", "delay_summary_stats.json")
DELAY_HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scratch", "delay_history_14d.json")

_cached_stats: Optional[Dict[str, Any]] = None


def load_delay_statistics() -> Dict[str, Any]:
    """Load precalculated 14-day delay statistics from disk or compute them."""
    global _cached_stats
    if _cached_stats is not None:
        return _cached_stats

    if os.path.exists(DELAY_STATS_FILE):
        try:
            with open(DELAY_STATS_FILE, "r", encoding="utf-8") as f:
                _cached_stats = json.load(f)
                return _cached_stats
        except Exception as e:
            logger.error("Error reading delay_summary_stats.json: %s", e)

    # If summary file missing, try computing from history
    if os.path.exists(DELAY_HISTORY_FILE):
        try:
            with open(DELAY_HISTORY_FILE, "r", encoding="utf-8") as f:
                history_data = json.load(f)
            stats = {}
            for t_no, info in history_data.items():
                label = info.get("label", f"Train {t_no}")
                history = info.get("history", [])
                stns_found = set()
                for h in history:
                    for k in h.keys():
                        if k.endswith("_delay"):
                            stns_found.add(k.replace("_delay", ""))
                def _calc_p(data: List[float], p: float) -> float:
                    if not data:
                        return 0.0
                    s = sorted(data)
                    k = (len(s) - 1) * (p / 100.0)
                    f = int(k)
                    c = min(f + 1, len(s) - 1)
                    w = k - f
                    return float(s[f] * (1.0 - w) + s[c] * w)

                stats[t_no] = {"label": label, "stations": {}}
                for stn in sorted(stns_found):
                    delays = [float(h[f"{stn}_delay"]) for h in history if f"{stn}_delay" in h]
                    if not delays:
                        continue
                    n = len(delays)
                    mean_val = sum(delays) / n
                    var_val = sum((x - mean_val) ** 2 for x in delays) / n
                    std_val = math.sqrt(var_val)
                    on_time_pct = (sum(1 for d in delays if d <= 5) / n) * 100.0

                    stats[t_no]["stations"][stn] = {
                        "N": n,
                        "P10": round(_calc_p(delays, 10), 1),
                        "P50": round(_calc_p(delays, 50), 1),
                        "P90": round(_calc_p(delays, 90), 1),
                        "Mean": round(mean_val, 1),
                        "Std": round(std_val, 1),
                        "OnTimePct": round(on_time_pct, 1),
                        "RawDelays": delays,
                    }
            _cached_stats = stats
            return _cached_stats
        except Exception as exc:
            logger.error("Failed to compute delay statistics: %s", exc)

    return {}


def get_train_delay_stats(train_no: str, station_code: Optional[str] = None) -> dict:
    """Retrieve P10, P50, P90, Mean, Std, and OnTime% for a given train and station."""
    stats = load_delay_statistics()
    t_info = stats.get(str(train_no), {})
    stations_data = t_info.get("stations", {})
    if not stations_data:
        # Default baseline if no history exists
        return {"N": 0, "P10": 0.0, "P50": 5.0, "P90": 20.0, "Mean": 7.0, "Std": 5.0, "OnTimePct": 75.0}

    if station_code and station_code.upper() in stations_data:
        return stations_data[station_code.upper()]

    # Return primary corridor station (BLRR or CRLM)
    for preferred in ["BLRR", "CRLM", "HSRA"]:
        if preferred in stations_data:
            return stations_data[preferred]

    # Return first available station
    first_stn = next(iter(stations_data.values()))
    return first_stn


# =============================================================================
# 6. RAKE TURNAROUND INSPECTOR & DYNAMIC STEP-OUT SHIFTING
# =============================================================================

def inspect_rake_turnaround(
    morning_train: str = MORNING_TRAIN_MEMU,
    rake_train: str = INCOMING_RAKE_MEMU,
    date_str: Optional[str] = None,
    reference_time: Optional[str] = None,
    allow_network: bool = True,
    rake_status: Optional[dict] = None,
    memu_status: Optional[dict] = None,
) -> dict:
    """
    Rake Turnaround Inspector:
    Tracks incoming train 66595 (YPR -> HSRA) to determine actual platform availability
    and departure time for morning MEMU 66596 (HSRA -> YPR).
    
    If 66595 is delayed arriving at Hosur, 66596 cannot depart at 08:25 AM.
    Physical turnaround requires at least RAKE_TURNAROUND_MIN_BUFFER (10 mins).
    Revised Step-Out Time = Projected_HSRA_Departure - LEAD_TIME_HOME_HOSUR (10 mins).
    """
    if not reference_time:
        reference_time = get_ist_now().strftime("%H:%M")

    if rake_status is None:
        rake_status = get_live_train_status(rake_train, date_str) if allow_network else fetch_static_fallback_status(rake_train)
    if memu_status is None:
        memu_status = get_live_train_status(morning_train, date_str) if allow_network else fetch_static_fallback_status(morning_train)

    # Find Hosur station info for both trains
    rake_hsra = next((s for s in rake_status.get("stations", []) if s["code"] == STN_HOSUR), None)
    memu_hsra = next((s for s in memu_status.get("stations", []) if s["code"] == STN_HOSUR), None)

    scheduled_rake_arr = rake_hsra.get("sta", "08:00") if rake_hsra else "08:00"
    scheduled_memu_dep = memu_hsra.get("std", "08:25") if memu_hsra else "08:25"

    # Check for cancellation, diversion, or short-termination before Hosur
    raw_status = (rake_status.get("current_status") or "").lower()
    raw_details = str(rake_status.get("raw", "")).lower()
    memu_raw_status = (memu_status.get("current_status") or "").lower()
    memu_raw_details = str(memu_status.get("raw", "")).lower()
    curr_stn = rake_status.get("current_station", "").upper()

    is_cancelled = (
        "cancel" in raw_status
        or "cancel" in raw_details
        or "cancel" in memu_raw_status
        or "cancel" in memu_raw_details
    )
    is_diverted = (
        "divert" in raw_status
        or "divert" in raw_details
        or "divert" in memu_raw_status
        or "divert" in memu_raw_details
    )
    is_short_terminated = (
        ("terminate" in raw_status or "short" in raw_status)
        and curr_stn != STN_HOSUR
    )

    if is_cancelled or is_diverted or is_short_terminated:
        reason = "CANCELLED" if is_cancelled else ("DIVERTED" if is_diverted else f"TERMINATED SHORT at {curr_stn}")
        return {
            "morning_train": morning_train,
            "incoming_rake_train": rake_train,
            "scheduled_hsra_departure": scheduled_memu_dep,
            "projected_hsra_departure": "CANCELLED",
            "effective_delay_mins": 999,
            "revised_step_out_time": "CANCELLED",
            "is_delayed": True,
            "rake_cancelled": True,
            "rake_current_station": curr_stn,
            "rake_current_station_name": rake_status.get("current_station_name", curr_stn),
            "rake_delay_mins": 999,
            "rake_eta_hsra": "CANCELLED",
            "rake_status_text": f"Rake {rake_train} {reason}",
            "delay_summary": f"🚨 Rake {rake_train} is {reason}! Train {morning_train} will not run normally. Switch to alternative train immediately.",
            "memu_has_departed": False,
            "memu_status": memu_status,
            "rake_status": rake_status,
        }

    # Incoming rake ETA at Hosur from reported delay / schedule
    rake_delay = rake_status.get("delay_minutes", 0)
    if rake_hsra:
        reported_rake_eta = rake_hsra.get("eta") or add_minutes_to_time(scheduled_rake_arr, rake_delay)
    else:
        reported_rake_eta = add_minutes_to_time(scheduled_rake_arr, rake_delay)

    # Physical transit constraint from rake's current location:
    # If the train is still at station S, it physically requires MIN_TRANSIT_TO_HSRA_66595[S] minutes to reach Hosur!
    min_transit = MIN_TRANSIT_TO_HSRA_66595.get(curr_stn)
    rake_has_arrived = (curr_stn == STN_HOSUR) or bool(rake_hsra and rake_hsra.get("has_arrived"))

    is_morning_window = ("05:00" <= reference_time < "10:30") if reference_time else True
    location_min_arrival = scheduled_rake_arr
    if is_morning_window and not rake_has_arrived and min_transit is not None and reference_time:
        location_min_arrival = add_minutes_to_time(reference_time, min_transit)

    # Take whichever ETA is later: reported ETA or physical location-based arrival
    rake_eta_hsra = reported_rake_eta
    if is_morning_window and minutes_difference(rake_eta_hsra, location_min_arrival) > 0:
        rake_eta_hsra = location_min_arrival

    # Physical constraint: MEMU cannot depart before (Rake_ETA + 10 mins turnaround)
    min_physical_dep = add_minutes_to_time(rake_eta_hsra, RAKE_TURNAROUND_MIN_BUFFER)

    # Directly reported MEMU ETD from CRIS if available
    etd_val = memu_hsra.get("etd") if memu_hsra else None
    direct_memu_etd = etd_val if (etd_val and str(etd_val).strip() not in ("Destination", "")) else ""
    
    # Take whichever departure is later: physical turnaround, direct reported ETD, or scheduled
    projected_departure = scheduled_memu_dep
    if minutes_difference(scheduled_memu_dep, min_physical_dep) > 0:
        projected_departure = min_physical_dep
    if direct_memu_etd and minutes_difference(projected_departure, direct_memu_etd) > 0:
        projected_departure = direct_memu_etd

    effective_delay = max(0, minutes_difference(scheduled_memu_dep, projected_departure))
    revised_step_out = add_minutes_to_time(projected_departure, -LEAD_TIME_HOME_HOSUR)

    is_delayed = effective_delay > 0
    current_rake_loc = f"{rake_status.get('current_station_name', 'En route')} ({rake_status.get('current_station', '')})"
    
    delay_summary = (
        f"Hey Sriram, there is a delay! Incoming rake ({rake_train}) is still at {current_rake_loc}, "
        f"so possible delay from Hosur. ETA Hosur: ~{rake_eta_hsra}. Minimum turnaround departure: ~{min_physical_dep}."
        if is_delayed
        else f"Incoming rake ({rake_train}) is on time near {current_rake_loc}. Scheduled Hosur departure: {scheduled_memu_dep}."
    )

    return {
        "morning_train": morning_train,
        "incoming_rake_train": rake_train,
        "scheduled_hsra_departure": scheduled_memu_dep,
        "projected_hsra_departure": projected_departure,
        "effective_delay_mins": effective_delay,
        "revised_step_out_time": revised_step_out,
        "is_delayed": is_delayed,
        "rake_cancelled": False,
        "rake_current_station": rake_status.get("current_station", ""),
        "rake_current_station_name": rake_status.get("current_station_name", ""),
        "rake_delay_mins": rake_delay,
        "rake_eta_hsra": rake_eta_hsra,
        "rake_status_text": rake_status.get("current_status", ""),
        "delay_summary": delay_summary,
        "memu_has_departed": bool(memu_hsra and memu_hsra.get("has_departed")),
        "memu_status": memu_status,
        "rake_status": rake_status,
    }


# =============================================================================
# 7. MORNING MULTI-TRAIN OPPORTUNITY SCANNER (07:30 - 09:30 WINDOW)
# =============================================================================

def scan_morning_commute_options(
    reference_time: Optional[str] = None,
    date_str: Optional[str] = None,
    allow_network: bool = True,
) -> dict:
    """
    Morning Multi-Train Opportunity Scanner:
    Scans all candidate morning trains (07:30 - 09:30 AM) heading HSRA -> BLRR / CRLM.
    
    Evaluates:
    - Train 66596 (08:25 AM MEMU) via Rake Turnaround Inspector
    - Train 06278 (07:07 AM Dharmapuri - Bengaluru MEMU, if delayed into morning window)
    - Train 16212 (08:20 AM Salem Express)
    
    If 66596 is delayed, or another train arrives/departs Hosur earlier or in the optimal window,
    it dynamically recommends the best train, calculating revised step-out times and arrival at ETV desk.
    """
    if not reference_time:
        reference_time = get_ist_now().strftime("%H:%M")

    # Query candidate morning corridor trains in parallel to minimize latency (< 1.0s)
    morning_trains = [INCOMING_RAKE_MEMU, MORNING_TRAIN_MEMU, MORNING_TRAIN_EARLIER_MEMU, MORNING_TRAIN_EXP]
    statuses: dict[str, dict] = {}
    if allow_network:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(morning_trains))) as executor:
            future_to_tno = {executor.submit(get_live_train_status, t_no, date_str): t_no for t_no in morning_trains}
            for fut in concurrent.futures.as_completed(future_to_tno):
                t_no = future_to_tno[fut]
                try:
                    statuses[t_no] = fut.result()
                except Exception as exc:
                    logger.warning("Parallel morning status fetch failed for %s: %s", t_no, exc)
                    statuses[t_no] = fetch_static_fallback_status(t_no)
    else:
        for t_no in morning_trains:
            statuses[t_no] = fetch_static_fallback_status(t_no)

    # 1. Inspect Rake Turnaround for Train 66596
    memu_rake = inspect_rake_turnaround(
        MORNING_TRAIN_MEMU,
        INCOMING_RAKE_MEMU,
        date_str,
        reference_time=reference_time,
        allow_network=allow_network,
        rake_status=statuses.get(INCOMING_RAKE_MEMU),
        memu_status=statuses.get(MORNING_TRAIN_MEMU),
    )
    
    # 2. Inspect Train 06278 (Dharmapuri - KSR Bengaluru MEMU)
    memu2_status = statuses.get(MORNING_TRAIN_EARLIER_MEMU) or fetch_static_fallback_status(MORNING_TRAIN_EARLIER_MEMU)
    memu2_hsra = next((s for s in memu2_status.get("stations", []) if s["code"] == STN_HOSUR), None)
    memu2_blrr = next((s for s in memu2_status.get("stations", []) if s["code"] == STN_BELLANDUR), None)
    memu2_crlm = next((s for s in memu2_status.get("stations", []) if s["code"] == STN_CARMELARAM), None)

    memu2_sch_dep = memu2_hsra.get("std", "07:07") if memu2_hsra else "07:07"
    memu2_delay = memu2_status.get("delay_minutes", 0)
    memu2_etd_val = memu2_hsra.get("etd") if memu2_hsra else None
    memu2_projected_dep = memu2_etd_val if (memu2_etd_val and str(memu2_etd_val).strip() not in ("Destination", "")) else add_minutes_to_time(memu2_sch_dep, memu2_delay)

    # Physical transit check for 06278 if still en route to Hosur
    is_morning_window = ("05:00" <= reference_time < "10:30") if reference_time else True
    memu2_curr_stn = memu2_status.get("current_station", "").upper()
    memu2_transit = MIN_TRANSIT_TO_HSRA_06278.get(memu2_curr_stn)
    memu2_has_arrived = (memu2_curr_stn == STN_HOSUR) or bool(memu2_hsra and memu2_hsra.get("has_arrived"))
    if is_morning_window and not memu2_has_arrived and memu2_transit is not None and reference_time:
        loc_dep = add_minutes_to_time(reference_time, memu2_transit + 2)
        if minutes_difference(memu2_projected_dep, loc_dep) > 0:
            memu2_projected_dep = loc_dep

    memu2_effective_delay = max(0, minutes_difference(memu2_sch_dep, memu2_projected_dep))
    memu2_step_out = add_minutes_to_time(memu2_projected_dep, -LEAD_TIME_HOME_HOSUR)

    # BLRR arrival for 06278
    memu2_sta = memu2_blrr.get("sta", "07:51") if memu2_blrr else "07:51"
    if memu2_effective_delay > 0:
        memu2_dest_eta = add_minutes_to_time(memu2_sta, memu2_effective_delay)
    else:
        memu2_dest_eta = (memu2_blrr.get("eta") if memu2_blrr else None) or memu2_sta

    memu2_desk_eta = add_minutes_to_time(memu2_dest_eta, WALK_TIME_BLRR_DESK)
    memu2_minutes_until_dep = minutes_difference(reference_time, memu2_projected_dep)

    # 3. Inspect Train 16212 (Salem - Yesvantpur Express)
    exp_status = statuses.get(MORNING_TRAIN_EXP) or fetch_static_fallback_status(MORNING_TRAIN_EXP)
    exp_hsra = next((s for s in exp_status.get("stations", []) if s["code"] == STN_HOSUR), None)
    exp_blrr = next((s for s in exp_status.get("stations", []) if s["code"] == STN_BELLANDUR), None)
    exp_crlm = next((s for s in exp_status.get("stations", []) if s["code"] == STN_CARMELARAM), None)

    exp_sch_dep = exp_hsra.get("std", "08:20") if exp_hsra else "08:20"
    exp_delay = exp_status.get("delay_minutes", 0)
    exp_etd_val = exp_hsra.get("etd") if exp_hsra else None
    exp_projected_dep = exp_etd_val if (exp_etd_val and str(exp_etd_val).strip() not in ("Destination", "")) else add_minutes_to_time(exp_sch_dep, exp_delay)
    # Cancellation checks for 06278 and 16212
    memu2_cancelled = (
        "cancel" in (memu2_status.get("current_status") or "").lower()
        or "cancel" in str(memu2_status.get("raw", "")).lower()
    )
    exp_cancelled = (
        "cancel" in (exp_status.get("current_status") or "").lower()
        or "cancel" in str(exp_status.get("raw", "")).lower()
    )

    # Physical transit check for 16212 if still en route to Hosur
    is_morning_window = ("05:00" <= reference_time < "10:30") if reference_time else True
    exp_curr_stn = exp_status.get("current_station", "").upper()
    exp_transit = MIN_TRANSIT_TO_HSRA_16212.get(exp_curr_stn)
    exp_has_arrived = (exp_curr_stn == STN_HOSUR) or bool(exp_hsra and exp_hsra.get("has_arrived"))
    if is_morning_window and not exp_has_arrived and exp_transit is not None and reference_time:
        loc_exp_dep = add_minutes_to_time(reference_time, exp_transit + 2)
        if minutes_difference(exp_projected_dep, loc_exp_dep) > 0:
            exp_projected_dep = loc_exp_dep

    exp_effective_delay = max(0, minutes_difference(exp_sch_dep, exp_projected_dep))
    exp_step_out = add_minutes_to_time(exp_projected_dep, -LEAD_TIME_HOME_HOSUR)

    exp_sta = exp_blrr.get("sta", "08:59") if exp_blrr else ("09:05" if exp_crlm else "08:59")
    if exp_effective_delay > 0:
        if exp_blrr and exp_blrr.get("eta") and exp_blrr.get("eta") != exp_sta and minutes_difference(exp_projected_dep, exp_blrr.get("eta")) >= 25:
            exp_dest_eta = exp_blrr.get("eta")
        elif exp_crlm and exp_crlm.get("eta") and exp_crlm.get("eta") != exp_sta and minutes_difference(exp_projected_dep, exp_crlm.get("eta")) >= 25:
            exp_dest_eta = exp_crlm.get("eta")
        else:
            exp_dest_eta = add_minutes_to_time(exp_sta, exp_effective_delay)
    else:
        exp_dest_eta = (exp_blrr.get("eta") if exp_blrr else None) or exp_sta

    exp_desk_eta = add_minutes_to_time(exp_dest_eta, WALK_TIME_BLRR_DESK)
    exp_minutes_until_dep = minutes_difference(reference_time, exp_projected_dep)

    # 4. MEMU 66596 destination arrival (BLRR)
    memu_blrr = next((s for s in memu_rake["memu_status"].get("stations", []) if s["code"] == STN_BELLANDUR), None)
    memu_delay = memu_rake["effective_delay_mins"]
    memu_sta = memu_blrr.get("sta", "09:03") if memu_blrr else "09:03"
    if memu_delay > 0:
        memu_blrr_eta = add_minutes_to_time(memu_sta, memu_delay)
    else:
        memu_blrr_eta = (memu_blrr.get("eta") if memu_blrr else None) or memu_sta

    memu_desk_eta = add_minutes_to_time(memu_blrr_eta, WALK_TIME_BLRR_DESK)
    memu_minutes_until_dep = (
        minutes_difference(reference_time, memu_rake["projected_hsra_departure"])
        if not memu_rake.get("rake_cancelled")
        else -999
    )

    def determine_status(mins: int, has_departed: bool = False, cancelled: bool = False) -> str:
        if cancelled:
            return "CANCELLED"
        if has_departed or mins < -2:
            return "DEPARTED"
        if -2 <= mins < 5:
            return "BOARDING"
        return "VIABLE"

    options = [
        {
            "train_no": MORNING_TRAIN_MEMU,
            "train_name": "Hosur - Yesvantpur MEMU",
            "type": "MEMU",
            "scheduled_departure": memu_rake["scheduled_hsra_departure"],
            "projected_departure": memu_rake["projected_hsra_departure"],
            "step_out_time": memu_rake["revised_step_out_time"],
            "dest_station": STN_BELLANDUR,
            "dest_eta": memu_blrr_eta,
            "desk_eta": memu_desk_eta,
            "delay_mins": memu_delay,
            "current_location": f"Rake: {memu_rake['rake_current_station_name']} ({memu_rake['rake_current_station']})",
            "is_delayed": memu_rake["is_delayed"],
            "minutes_until_dep": memu_minutes_until_dep,
            "door_to_door_duration": minutes_difference(memu_rake["revised_step_out_time"], memu_desk_eta) if not memu_rake.get("rake_cancelled") else 0,
            "status": determine_status(memu_minutes_until_dep, has_departed=bool(memu_rake.get("memu_has_departed")), cancelled=memu_rake.get("rake_cancelled")),
            "details": memu_rake["delay_summary"],
        },
        {
            "train_no": MORNING_TRAIN_EARLIER_MEMU,
            "train_name": "Dharmapuri - KSR Bengaluru MEMU",
            "type": "MEMU",
            "scheduled_departure": memu2_sch_dep,
            "projected_departure": memu2_projected_dep,
            "step_out_time": memu2_step_out,
            "dest_station": STN_BELLANDUR,
            "dest_eta": memu2_dest_eta,
            "desk_eta": memu2_desk_eta,
            "delay_mins": memu2_effective_delay,
            "current_location": f"{memu2_status.get('current_station_name', '')} ({memu2_curr_stn})",
            "is_delayed": memu2_effective_delay > 0,
            "minutes_until_dep": memu2_minutes_until_dep,
            "door_to_door_duration": minutes_difference(memu2_step_out, memu2_desk_eta),
            "status": determine_status(memu2_minutes_until_dep, has_departed=bool(memu2_hsra and memu2_hsra.get("has_departed")), cancelled=memu2_cancelled),
            "details": f"Dharmapuri MEMU currently near {memu2_status.get('current_station_name', '')} (Delay: {memu2_effective_delay}m).",
        },
        {
            "train_no": MORNING_TRAIN_EXP,
            "train_name": "Salem - Yesvantpur Express",
            "type": "EXPRESS",
            "scheduled_departure": exp_sch_dep,
            "projected_departure": exp_projected_dep,
            "step_out_time": exp_step_out,
            "dest_station": STN_BELLANDUR,
            "dest_eta": exp_dest_eta,
            "desk_eta": exp_desk_eta,
            "delay_mins": exp_delay,
            "effective_delay_mins": exp_effective_delay,
            "current_location": f"{exp_status.get('current_station_name', '')} ({exp_status.get('current_station', '')})",
            "is_delayed": exp_effective_delay > 0,
            "minutes_until_dep": exp_minutes_until_dep,
            "door_to_door_duration": minutes_difference(exp_step_out, exp_desk_eta),
            "status": determine_status(exp_minutes_until_dep, has_departed=bool(exp_hsra and exp_hsra.get("has_departed")), cancelled=exp_cancelled),
            "details": f"Salem Express currently near {exp_status.get('current_station_name', '')} (Delay: {exp_effective_delay}m).",
        },
    ]

    # Intelligent Recommendation Logic: Max-Sleep Utility Optimization
    # Target shift: 12:00 PM. Target desk arrival: <= 11:30 AM (30-minute safety buffer).
    # Objective: Among all viable trains reaching desk before cutoff, pick the LATEST departing train!
    viable = [o for o in options if o["status"] in ("VIABLE", "BOARDING")]

    if not viable:
        recommended = options[0]
        rec_reason = "All morning trains appear to have departed or are in departure."
    else:
        # 1. Filter out 66596 if incoming rake 66595 is cancelled
        active_viable = [
            o for o in viable
            if not (o["train_no"] == MORNING_TRAIN_MEMU and memu_rake.get("rake_cancelled"))
        ]
        if not active_viable:
            active_viable = viable

        # 2. Safety Cutoff & 2-Stage Tiering:
        # Tier 1: Desk ETA <= 11:30 AM (comfortable >= 30m buffer ahead of 12:00 PM shift start)
        # Tier 2: Desk ETA <= 12:00 PM (hard shift start cutoff)
        SHIFT_CUTOFF_DESK = "11:30"
        SHIFT_HARD_START = "12:00"

        tier1 = [o for o in active_viable if minutes_difference(o.get("desk_eta", "12:00"), SHIFT_CUTOFF_DESK) >= 0]
        tier2 = [o for o in active_viable if minutes_difference(o.get("desk_eta", "12:00"), SHIFT_HARD_START) >= 0]

        def _dep_minutes(o: dict) -> int:
            try:
                parts = o.get("projected_departure", "00:00").split(":")
                return int(parts[0]) * 60 + int(parts[1])
            except Exception:
                return 0

        def _arr_minutes(o: dict) -> int:
            try:
                parts = o.get("desk_eta", "23:59").split(":")
                return int(parts[0]) * 60 + int(parts[1])
            except Exception:
                return 9999

        # Tie-breaker key: latest departure, but if departures equal, earliest desk arrival
        def _tier_rank(o: dict) -> tuple[int, int]:
            return (_dep_minutes(o), -_arr_minutes(o))

        # Fallback key: earliest desk arrival, but if arrivals equal, latest departure
        def _fallback_rank(o: dict) -> tuple[int, int]:
            return (_arr_minutes(o), -_dep_minutes(o))

        if tier1:
            recommended = max(tier1, key=_tier_rank)
            pool = tier1
        elif tier2:
            recommended = max(tier2, key=_tier_rank)
            pool = tier2
        else:
            recommended = min(active_viable, key=_fallback_rank)
            pool = active_viable

        if not tier1 and not tier2:
            rec_delay = recommended.get("effective_delay_mins") or recommended.get("delay_mins") or 0
            delay_note = f" (delay: +{rec_delay}m)" if recommended.get("is_delayed") else ""
            rec_reason = (
                f"🚨 WARNING: Severe delays across all corridor trains! Even earliest arriving option Train {recommended['train_no']} "
                f"({recommended['train_name']}) won't reach desk until ~{format_ampm(recommended['desk_eta'])}{delay_note}, "
                f"missing your 12:00 PM hard shift start. Strongly consider taking Bike / Cab (/bike) or WFH (/wfh) today!"
            )
        elif not tier1 and tier2:
            rec_delay = recommended.get("effective_delay_mins") or recommended.get("delay_mins") or 0
            delay_note = f" (delay: +{rec_delay}m)" if recommended.get("is_delayed") else ""
            rec_reason = (
                f"⚠️ CAUTION: Corridor delays have breached the 11:30 AM buffer! Train {recommended['train_no']} "
                f"({recommended['train_name']}) departs Hosur at ~{format_ampm(recommended['projected_departure'])}{delay_note} "
                f"and arrives at desk by ~{format_ampm(recommended['desk_eta'])}, reaching before your 12:00 PM shift start."
            )
        elif memu_rake.get("rake_cancelled"):
            rec_reason = (
                f"⚠️ Train {MORNING_TRAIN_MEMU} rake is CANCELLED! Recommend taking Train {recommended['train_no']} "
                f"({recommended['train_name']}) departing Hosur at ~{format_ampm(recommended['projected_departure'])}. "
                f"Reaches BLRR at ~{format_ampm(recommended['dest_eta'])} (ETV Desk: ~{format_ampm(recommended['desk_eta'])})."
            )
        elif len(pool) == 1:
            rec_delay = recommended.get("effective_delay_mins") or recommended.get("delay_mins") or 0
            delay_note = f" (delay: +{rec_delay}m)" if recommended.get("is_delayed") else " (on schedule)"
            rec_reason = (
                f"Train {recommended['train_no']} ({recommended['train_name']}) is your sole qualifying option reaching desk before 11:30 AM "
                f"(departs Hosur at ~{format_ampm(recommended['projected_departure'])}{delay_note}, BLRR ~{format_ampm(recommended['dest_eta'])}, Desk ~{format_ampm(recommended['desk_eta'])})."
            )
        else:
            delay_note = f" (delay: +{recommended['delay_mins']}m)" if recommended.get("is_delayed") else " (on schedule)"
            rec_reason = (
                f"Train {recommended['train_no']} ({recommended['train_name']}) departs Hosur latest at ~{format_ampm(recommended['projected_departure'])}{delay_note}, "
                f"maximizing your sleep and home time! Reaches BLRR at ~{format_ampm(recommended['dest_eta'])} and ETV desk by ~{format_ampm(recommended['desk_eta'])} "
                f"(comfortably ahead of your 12:00 PM shift cutoff)."
            )

    return {
        "reference_time": reference_time,
        "recommended_train": recommended,
        "recommendation_reason": rec_reason,
        "options": options,
        "rake_turnaround": memu_rake,
        "statuses": statuses,
    }


# =============================================================================
# 8. EVENING COMMUTE SCANNER & MILESTONE MONITORS
# =============================================================================

def scan_evening_commute_options(
    reference_time: Optional[str] = None,
    date_str: Optional[str] = None,
    allow_network: bool = True,
) -> list[dict]:
    """Scan evening trains from BLRR / CRLM corridor to Hosur and compute desk departure advisories."""
    if not reference_time:
        reference_time = get_ist_now().strftime("%H:%M")

    evening_trains = ["66585", "16211", "66583", "16232", "16527", "16236"]
    results = []

    # Query evening corridor trains in parallel to minimize latency (< 1.0s)
    statuses: dict[str, dict] = {}
    if allow_network:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(evening_trains))) as executor:
            future_to_tno = {executor.submit(get_live_train_status, t_no, date_str): t_no for t_no in evening_trains}
            for fut in concurrent.futures.as_completed(future_to_tno):
                t_no = future_to_tno[fut]
                try:
                    statuses[t_no] = fut.result()
                except Exception as exc:
                    logger.warning("Parallel evening status fetch failed for %s: %s", t_no, exc)
                    statuses[t_no] = fetch_static_fallback_status(t_no)
    else:
        for t_no in evening_trains:
            statuses[t_no] = fetch_static_fallback_status(t_no)

    for t_no in evening_trains:
        status = statuses.get(t_no) or fetch_static_fallback_status(t_no)
        sched = CORRIDOR_SCHEDULES.get(t_no, {})
        
        # Check if train stops at BLRR (+11m advantage) or CRLM
        blrr_stn = next((s for s in status.get("stations", []) if s.get("code") == STN_BELLANDUR), None)
        crlm_stn = next((s for s in status.get("stations", []) if s.get("code") == STN_CARMELARAM), None)
        hsra_stn = next((s for s in status.get("stations", []) if s.get("code") == STN_HOSUR), None)

        if not blrr_stn and not crlm_stn and sched:
            static_st = fetch_static_fallback_status(t_no)
            blrr_stn = next((s for s in static_st.get("stations", []) if s.get("code") == STN_BELLANDUR), None)
            crlm_stn = next((s for s in static_st.get("stations", []) if s.get("code") == STN_CARMELARAM), None)
            hsra_stn = next((s for s in static_st.get("stations", []) if s.get("code") == STN_HOSUR), None)
            status = static_st

        if blrr_stn:
            board_stn = STN_BELLANDUR
            sch_dep = blrr_stn.get("std", "")
            etd_val = blrr_stn.get("etd")
            lead_time = LEAD_TIME_DESK_BLRR
        elif crlm_stn:
            board_stn = STN_CARMELARAM
            sch_dep = crlm_stn.get("std", "")
            etd_val = crlm_stn.get("etd")
            lead_time = LEAD_TIME_DESK_CRLM
        else:
            continue

        delay = status.get("delay_minutes", 0)
        est_dep = etd_val if (etd_val and str(etd_val).strip() not in ("Destination", "")) else (add_minutes_to_time(sch_dep, delay) if sch_dep else "")
        leave_desk_time = add_minutes_to_time(est_dep, -lead_time) if est_dep else ""
        hsra_eta = hsra_stn.get("eta", "") if hsra_stn else ""

        # Determine viability status
        diff_to_leave = minutes_difference(reference_time, leave_desk_time) if leave_desk_time else -999
        diff_to_board = minutes_difference(reference_time, est_dep) if est_dep else -999
        if diff_to_board < 0:
            opt_status = "DEPARTED"
        elif diff_to_leave <= 0:
            opt_status = "BOARDING"
        else:
            opt_status = "VIABLE"

        milestone_stn = sched.get("milestone_station") or ("BAND" if t_no in ("66585", "16211", "16527") else "BNC")

        results.append({
            "train_no": t_no,
            "train_name": sched.get("train_name", f"Train {t_no}"),
            "boarding_station": board_stn,
            "scheduled_departure": sch_dep,
            "estimated_departure": est_dep,
            "boarding_sta": est_dep,
            "projected_departure": est_dep,
            "leave_desk_time": leave_desk_time,
            "lead_time_mins": lead_time,
            "hosur_eta": hsra_eta,
            "delay_mins": delay,
            "milestone_station": milestone_stn,
            "status": opt_status,
            "current_location": f"{status.get('current_station_name', '')} ({status.get('current_station', '')})",
            "status_text": status.get("current_status", ""),
        })

    return results


def get_static_morning_commute_options(
    reference_time: Optional[str] = None,
    date_str: Optional[str] = None,
) -> dict:
    """Fast, offline static evaluation of morning commute options with zero network calls."""
    return scan_morning_commute_options(reference_time=reference_time, date_str=date_str, allow_network=False)


def get_static_evening_commute_options(
    reference_time: Optional[str] = None,
    date_str: Optional[str] = None,
) -> list[dict]:
    """Fast, offline static evaluation of evening commute options with zero network calls."""
    return scan_evening_commute_options(reference_time=reference_time, date_str=date_str, allow_network=False)


def check_morning_milestone_trigger(train_no: str, status_dict: dict, reference_time: Optional[str] = None) -> Optional[dict]:
    """
    Evaluate if an inbound morning train has reached/cleared its physical milestone station.
    - For Train 16212 (Salem Exp) and Train 06278 (Dharmapuri MEMU):
      Physical milestone is KELAMANGALAM (KMLM) - 13.5 km / ~14 mins before Hosur PF1.
      When train reaches or departs KMLM, triggers immediate STEP OUT NOW notification.
    - For Train 66596 (Hosur MEMU):
      Originates at Hosur from incoming rake 66595 (scheduled dep 08:25 AM).
      Step-out time is strictly 08:15 AM (10m walk). Early rake arrival before 08:10 AM
      must NEVER trigger early step out.
    """
    t_no = str(train_no).strip()
    sched = CORRIDOR_SCHEDULES.get(t_no, {})
    t_name = sched.get("train_name", f"Train {t_no}")
    stations = status_dict.get("stations", [])
    curr_stn = status_dict.get("current_station", "").upper()
    delay = status_dict.get("delay_minutes", 0)

    # If train has already departed from Hosur, milestone has expired
    hsra_stn = next((s for s in stations if s.get("code") == STN_HOSUR), None)
    if hsra_stn and hsra_stn.get("has_departed"):
        return None

    if t_no in (MORNING_TRAIN_EXP, MORNING_TRAIN_EARLIER_MEMU):  # 16212, 06278
        # Milestone station: KELAMANGALAM (KMLM)
        kmlm_stn = next((s for s in stations if s.get("code") == "KMLM"), None)
        kmlm_reached = False
        if kmlm_stn and (kmlm_stn.get("has_departed") or kmlm_stn.get("has_arrived")):
            kmlm_reached = True
        elif curr_stn == "KMLM":
            kmlm_reached = True
        # If train is already at Hosur PF1 (arrived but not departed)
        elif curr_stn == STN_HOSUR or (hsra_stn and hsra_stn.get("has_arrived")):
            return {
                "triggered": True,
                "action": "STEP_OUT_NOW",
                "train_no": t_no,
                "train_name": t_name,
                "milestone_station": "HSRA",
                "milestone_station_name": "HOSUR",
                "target_station": STN_HOSUR,
                "lead_time_mins": 10,
                "message": (
                    f"🚨 *STEP OUT NOW! (Door-to-PF1: 10m)*\n\n"
                    f"Train *{t_name} ({t_no})* is currently arriving / at *HOSUR (HSRA) PF1*!\n"
                    f"• Walk Time to PF1: 10 mins\n"
                    f"• Live Delay: *+{delay} mins*\n\n"
                    f"👟 Walk immediately to Platform 1 to board!"
                ),
            }

        if kmlm_reached:
            return {
                "triggered": True,
                "action": "STEP_OUT_NOW",
                "train_no": t_no,
                "train_name": t_name,
                "milestone_station": "KMLM",
                "milestone_station_name": "KELAMANGALAM",
                "target_station": STN_HOSUR,
                "lead_time_mins": 10,
                "message": (
                    f"🚨 *STEP OUT NOW! (Door-to-PF1: 10m)*\n\n"
                    f"Train *{t_name} ({t_no})* has reached / cleared *KELAMANGALAM (KMLM)*!\n"
                    f"• Proximity: ~13.5 km to Hosur (~14 mins running time)\n"
                    f"• Walk Time to PF1: 10 mins (5m walk + 5m platform cushion)\n"
                    f"• Live Delay: *+{delay} mins*\n\n"
                    f"👟 Time to step out from home NOW to catch Platform 1!"
                ),
            }

    elif t_no == MORNING_TRAIN_MEMU:  # 66596
        # When 66596 is on time (dep 08:25), scheduled step out is 08:15 AM
        # Early rake arrival at Hosur (e.g. 07:35 AM) must NOT trigger premature step out
        if reference_time and reference_time < "08:10":
            return None

        if hsra_stn and (hsra_stn.get("has_arrived") or curr_stn == STN_HOSUR):
            return {
                "triggered": True,
                "action": "STEP_OUT_NOW",
                "train_no": t_no,
                "train_name": t_name,
                "milestone_station": "HSRA",
                "milestone_station_name": "HOSUR",
                "target_station": STN_HOSUR,
                "lead_time_mins": 10,
                "message": (
                    f"🚨 *STEP OUT NOW! (Door-to-PF1: 10m)*\n\n"
                    f"Incoming rake for *{t_name} (66596)* is at *HOSUR (HSRA)*!\n"
                    f"• Rake turnaround: ~15 mins\n"
                    f"• Walk Time to PF1: 10 mins\n\n"
                    f"👟 Time to step out from home NOW to board at Platform 1!"
                ),
            }

    return None


def check_evening_milestone_trigger(train_no: str, status_dict: dict, reference_time: Optional[str] = None) -> Optional[dict]:
    """
    Evaluate if an evening train has cleared its milestone station.
    Dynamically determines boarding station:
    - If BLRR is in the schedule, use BLRR (lead time 20m, LEAD_TIME_DESK_BLRR)
    - If CRLM is in the schedule, use CRLM (lead time 25m, LEAD_TIME_DESK_CRLM)
    Computes boarding ETA dynamically from scheduled arrival (sta) + delay.
    """
    t_no = str(train_no).strip()
    sched = CORRIDOR_SCHEDULES.get(t_no)
    if not sched:
        return None

    milestone_code = sched.get("milestone_station")
    if not milestone_code:
        if t_no in ("16232", "16236", "66583"):
            milestone_code = "BNC"
        elif t_no in ("66585", "16211", "16527"):
            milestone_code = "BAND"

    if not milestone_code:
        return None

    sched_stations = sched.get("stations", [])
    sched_codes = [s.get("code") for s in sched_stations]
    stations = status_dict.get("stations", [])
    status_codes = [s.get("code") for s in stations]

    # Dynamically determine boarding station: BLRR (preferred/closer to desk) or CRLM
    target_code = None
    target_name = None
    lead_time = None
    sched_target_stn = None

    if STN_BELLANDUR in sched_codes or STN_BELLANDUR in status_codes:
        target_code = STN_BELLANDUR
        target_name = "Bellandur Road (BLRR)"
        lead_time = LEAD_TIME_DESK_BLRR
        sched_target_stn = next((s for s in sched_stations if s.get("code") == STN_BELLANDUR), None)
    elif STN_CARMELARAM in sched_codes or STN_CARMELARAM in status_codes:
        target_code = STN_CARMELARAM
        target_name = "Carmelaram (CRLM)"
        lead_time = LEAD_TIME_DESK_CRLM
        sched_target_stn = next((s for s in sched_stations if s.get("code") == STN_CARMELARAM), None)
    else:
        return None

    m_stn = next((s for s in stations if s.get("code") == milestone_code), None)
    target_stn = next((s for s in stations if s.get("code") == target_code), None)
    curr_stn = status_dict.get("current_station", "").upper()
    delay = status_dict.get("delay_minutes", 0)

    # If the train has already departed the target boarding station, milestone trigger is expired
    if target_stn and target_stn.get("has_departed"):
        return None

    # Compute target boarding ETA
    target_eta = target_stn.get("eta") if target_stn else None
    if not target_eta or str(target_eta).strip() in ("", "Source", "Destination"):
        sch_sta = (target_stn.get("sta") if target_stn else None) or (sched_target_stn.get("sta") if sched_target_stn else "")
        if sch_sta and sch_sta not in ("Source", "Destination", ""):
            target_eta = add_minutes_to_time(sch_sta, delay)
        else:
            target_eta = (m_stn.get("etd") if m_stn else None) or ""

    dep_time = (m_stn.get("etd") if m_stn else None) or (m_stn.get("std") if m_stn else "") or ""

    # 1. Urgent Check: Train has already reached or is arriving at target station (BLRR / CRLM)
    if (target_stn and target_stn.get("has_arrived")) or (curr_stn == target_code):
        return {
            "triggered": True,
            "train_no": t_no,
            "train_name": sched.get("train_name", f"Train {t_no}"),
            "milestone_station": target_code,
            "departure_time": target_eta,
            "boarding_station": target_code,
            "boarding_eta": target_eta,
            "crlm_eta": target_eta,
            "lead_time_mins": lead_time,
            "action": "LEAVE_DESK_NOW",
            "message": (
                f"🚨 *URGENT: Train {t_no} Arriving at {target_name} NOW!*\n\n"
                f"Train *{sched.get('train_name', f'Train {t_no}')}* is arriving / at *{target_name}*!\n"
                f"• Current Delay: *+{delay} mins*\n\n"
                f"🏃 *LEAVE DESK IMMEDIATELY* to catch Platform at {target_name}!"
            ),
        }

    # 2. Milestone Reached Check: Milestone departed OR current station is at/past milestone
    m_reached = False
    m_idx = sched_codes.index(milestone_code) if milestone_code in sched_codes else -1
    t_idx = sched_codes.index(target_code) if target_code in sched_codes else 999

    if m_stn and (m_stn.get("has_departed") or m_stn.get("has_arrived")):
        m_reached = True
    elif m_idx != -1:
        # Check if any station between milestone and target has arrived or departed
        for s in stations:
            sc = s.get("code")
            if sc in sched_codes:
                s_idx = sched_codes.index(sc)
                if m_idx <= s_idx <= t_idx and (s.get("has_arrived") or s.get("has_departed")):
                    m_reached = True
                    break
        if not m_reached and curr_stn:
            c_idx = sched_codes.index(curr_stn) if curr_stn in sched_codes else -1
            if m_idx <= c_idx <= t_idx:
                m_reached = True

    if m_reached:
        return {
            "triggered": True,
            "train_no": t_no,
            "train_name": sched.get("train_name", f"Train {t_no}"),
            "milestone_station": milestone_code,
            "departure_time": dep_time,
            "boarding_station": target_code,
            "boarding_eta": target_eta,
            "crlm_eta": target_eta,
            "lead_time_mins": lead_time,
            "action": "LEAVE_DESK_NOW",
            "message": (
                f"🚨 *MILESTONE TRIGGER: Train {t_no}*\n\n"
                f"Train *{sched.get('train_name', f'Train {t_no}')}* has departed / cleared *{milestone_code}*!\n"
                f"• Expected *{target_name}* arrival: ~*{target_eta}*\n"
                f"• Live Delay: *+{delay} mins*\n\n"
                f"🏃 *LEAVE DESK NOW* (ETV JPMC Parcel 5 &rarr; {target_code}: ~{lead_time} mins lead time)."
            ),
        }

    return None
