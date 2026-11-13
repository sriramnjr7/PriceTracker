"""Local Flipkart Multi-Item Sniper & Personalized Deal Radar.

Tracks 2 priority items with personalized user session pricing (Plus, pincode, account coupons):
1. CASIO G-SHOCK GBD-300-7DR (White) - Alerts if price <= Rs 6,500 (currently ~Rs 6,945).
2. CASIO G-SHOCK GBD-300-1DR (Black) - Alerts if restocked for Rs 0 1-to-1 variant exchange!

Features:
- Reads cookies from 'flipkart_session_cookies.json' (exported via Start_Login_Flipkart.cmd).
- High-speed 15s cadence using Scrapling TLS Chrome impersonation.
- Auto-opens browser directly to product buy page on trigger.
- Native Windows Desktop Notification (Toast) + triple audible beeps.
- Instant Telegram alert with 1-click Buy Now button.
- Strictly local: DOES NOT touch or interfere with Oracle VM server.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import time
import webbrowser
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Any, Optional

import httpx
from bs4 import BeautifulSoup

# Ensure project root is in sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from config import settings
from scrapers.flipkart import FlipkartScraper

try:
    import winsound
except ImportError:
    winsound = None

try:
    from scrapling import Fetcher
except ImportError:
    Fetcher = None

# =====================================================================
# PATHS & CONFIGURATION
# =====================================================================
COOKIES_FILE = os.path.join(BASE_DIR, "flipkart_session_cookies.json")
LOG_FILE_PATH = os.path.join(BASE_DIR, "local_sniper.log")
CHECK_INTERVAL_SECONDS = 15
ALERT_COOLDOWN_SECONDS = 180  # 3 minutes cooldown per target before re-alerting

# =====================================================================
# TARGET DEFINITIONS
# =====================================================================
TARGETS = [
    {
        "id": "gbd300_white",
        "name": "CASIO GBD-300-7DR (White)",
        "pid": "WATH6HSU8VDHMGFM",
        "url": "https://www.flipkart.com/casio-gbd-300-7dr-g-shock-digital-watch-men/p/itm81760a02be985?pid=WATH6HSU8VDHMGFM",
        "target_desc": "In Stock & Price <= Rs 6,500 (User buy/exchange target)",
        "trigger": lambda in_stock, price, eff: in_stock and (
            (price and price <= 6500) or (eff and eff <= 6500)
        ),
    },
    {
        "id": "gbd300_black",
        "name": "CASIO GBD-300-1DR (Black)",
        "pid": "WATH6HSUVHVMZVPW",
        "url": "https://www.flipkart.com/casio-gbd-300-1dr-g-shock-digital-watch-men/p/itm81760a02be985?pid=WATH6HSUVHVMZVPW",
        "target_desc": "In Stock (1-to-1 Zero-Cost Variant Exchange Trigger)",
        "trigger": lambda in_stock, price, eff: in_stock and (
            price is not None and price <= 13000
        ),
    },
]

# Track last alert timestamp per target
last_alerted: dict[str, float] = {}

# =====================================================================
# LOGGING SETUP
# =====================================================================
logger = logging.getLogger("LocalSniper")
logger.setLevel(logging.INFO)
logger.propagate = False

log_formatter = logging.Formatter(
    fmt="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(log_formatter)
logger.addHandler(console_handler)

file_handler = RotatingFileHandler(
    LOG_FILE_PATH,
    maxBytes=10 * 1024 * 1024,
    backupCount=5,
    encoding="utf-8",
)
file_handler.setFormatter(log_formatter)
logger.addHandler(file_handler)


# =====================================================================
# SESSION COOKIES HELPER
# =====================================================================
def load_flipkart_cookies() -> tuple[dict[str, str], str]:
    """Load Flipkart session cookies exported by login_flipkart.py."""
    if not os.path.exists(COOKIES_FILE):
        return {}, ""

    try:
        with open(COOKIES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        cookie_dict: dict[str, str] = {}
        if isinstance(data, list):
            for c in data:
                if isinstance(c, dict) and "name" in c and "value" in c:
                    cookie_dict[c["name"]] = str(c["value"])
        elif isinstance(data, dict):
            cookie_dict = {k: str(v) for k, v in data.items()}

        cookie_header = "; ".join([f"{k}={v}" for k, v in cookie_dict.items()])
        return cookie_dict, cookie_header
    except Exception as exc:
        logger.warning("Error loading session cookies from %s: %s", COOKIES_FILE, exc)
        return {}, ""


# =====================================================================
# NOTIFICATIONS & ALARMS
# =====================================================================
def sound_alarm() -> None:
    """Sound an urgent 3-beep tone on Windows."""
    if winsound:
        try:
            for _ in range(3):
                winsound.Beep(1300, 300)
                time.sleep(0.08)
        except Exception:
            pass


def show_windows_toast(title: str, message: str) -> None:
    """Show a native Windows Toast notification."""
    escaped_title = title.replace('"', '`"')
    escaped_msg = message.replace('"', '`"')
    powershell_script = f"""
    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
    $template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
    $textNodes = $template.GetElementsByTagName("text")
    $textNodes.Item(0).AppendChild($template.CreateTextNode("{escaped_title}")) | Out-Null
    $textNodes.Item(1).AppendChild($template.CreateTextNode("{escaped_msg}")) | Out-Null
    $toast = [Windows.UI.Notifications.ToastNotification]::new($template)
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("SriTrack Local Sniper").Show($toast)
    """
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", powershell_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        logger.debug("Windows toast error: %s", exc)


async def send_telegram_alert(target: dict[str, Any], price: Optional[float], eff_price: Optional[float]) -> None:
    """Send immediate Telegram alert with 1-click Buy Now button."""
    bot_token = settings.telegram_bot_token
    chat_id = settings.telegram_chat_id
    if not bot_token or not chat_id:
        return

    p_str = f"₹{price:g}" if price else "In Stock"
    eff_str = f"\n💳 *Effective Offer Deal:* ₹{eff_price:g}" if eff_price and price and eff_price < price else ""

    text = (
        "🚨🚨🚨 *SRITRACK LOCAL SNIPER TRIGGER!* 🚨🚨🚨\n\n"
        f"🎯 *Item:* {target['name']}\n"
        "🔥 *STATUS: TARGET MET / READY TO SNIPE!*\n"
        f"💰 *Price:* {p_str}{eff_str}\n"
        f"📋 *Target Rule:* {target['target_desc']}\n\n"
        f"🛒 *OPEN & BUY INSTANTLY:* {target['url']}\n\n"
        "⚡ *Dispatched via Local Personalized Radar (15s)*"
    )

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": {
            "inline_keyboard": [
                [{"text": "🛒 BUY NOW INSTANTLY", "url": target["url"]}]
            ]
        },
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                logger.info("⚡ [TELEGRAM] Alert sent for %s!", target["name"])
            else:
                logger.error("[TELEGRAM] Failed alert: %s", resp.text)
    except Exception as exc:
        logger.error("[TELEGRAM] Exception sending alert: %s", exc)


# =====================================================================
# FETCHING & SCRAPING ENGINE
# =====================================================================
class AuthenticatedScraper:
    def __init__(self, parser: FlipkartScraper):
        self.parser = parser

    async def fetch_page(self, url: str, cookie_dict: dict[str, str], cookie_header: str) -> Optional[str]:
        """Fetch Flipkart page passing authenticated session cookies."""
        # 1. Scrapling Fetcher with Chrome TLS Impersonation & Cookies
        if Fetcher:
            try:
                response = await asyncio.to_thread(
                    Fetcher.get,
                    url,
                    impersonate="chrome",
                    cookies=cookie_dict if cookie_dict else None,
                    timeout=10,
                    follow_redirects=True,
                )
                if response.status == 200:
                    html = getattr(response, "html_content", "") or (
                        response.body.decode("utf-8", errors="ignore")
                        if hasattr(response, "body")
                        else ""
                    )
                    if html and len(html) > 3000:
                        return html
            except Exception as exc:
                logger.debug("Scrapling authenticated fetch error: %s", exc)

        # 2. Fallback to httpx GET with realistic headers & Cookie
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8",
            "Referer": "https://www.google.com/",
            "Sec-Ch-Ua": '"Google Chrome";v="129", "Not=A?Brand";v="8", "Chromium";v="129"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        }
        if cookie_header:
            headers["Cookie"] = cookie_header

        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200 and len(resp.text) > 3000:
                    return resp.text
        except Exception as exc:
            logger.debug("httpx authenticated fetch error: %s", exc)

        return None

    def parse_with_personalization(self, html: str, url: str) -> tuple[Optional[float], Optional[float], bool, str]:
        """Parse HTML for base price, personalized WOW deal / effective price, and in_stock."""
        soup = BeautifulSoup(html, "html.parser")
        title = self.parser._extract_title(soup)
        base_price = self.parser._extract_price(soup, url=url)
        in_stock = self.parser._extract_stock(soup, url=url)
        eff_price, _ = self.parser._extract_offers_and_effective_price(soup, base_price, html=html)

        # Additional check for Flipkart's "WOW! DEAL Buy at ₹X,XXX" banner
        wow_match = re.search(r"Buy at\s*₹?\s*([0-9,]+)", html, re.I)
        if wow_match:
            try:
                wow_val = float(wow_match.group(1).replace(",", ""))
                if base_price and 0 < wow_val < base_price:
                    eff_price = wow_val
                elif not base_price:
                    eff_price = wow_val
            except Exception:
                pass

        return base_price, eff_price, in_stock, title


# =====================================================================
# MAIN SNIPER LOOP
# =====================================================================
async def main() -> None:
    print("=" * 75)
    print("🎯 SRITRACK LOCAL MULTI-SNIPER & PERSONALIZED DEAL RADAR")
    print("=" * 75)

    cookie_dict, cookie_header = load_flipkart_cookies()
    if cookie_dict:
        print(f"🔐 Authenticated Session Active: Loaded {len(cookie_dict)} cookies from flipkart_session_cookies.json")
        print("   (Personalized discounts, Flipkart Plus coupons & pincode pricing enabled)")
    else:
        print("⚠️  No session cookies found! Running in GUEST MODE.")
        print("👉 Tip: Run 'Start_Login_Flipkart.cmd' to log into your account and unlock")
        print("   your personal coupons (e.g. ₹2,599 off on GBD-300 White)!")

    print(f"⏱️  Cadence      : Every {CHECK_INTERVAL_SECONDS} seconds")
    print(f"📄 Audit Log    : {LOG_FILE_PATH}")
    print("-" * 75)
    for i, t in enumerate(TARGETS, 1):
        print(f" {i}. {t['name']}")
        print(f"    Target: {t['target_desc']}")
    print("=" * 75)
    print("\nRadar running... Press Ctrl+C to stop.\n")

    parser = FlipkartScraper(settings)
    engine = AuthenticatedScraper(parser)
    loop_count = 0

    while True:
        loop_count += 1
        t_loop_start = time.monotonic()
        results_summary: list[str] = []

        # Re-check cookies periodically (in case user logged in while running)
        if loop_count % 20 == 0:
            cookie_dict, cookie_header = load_flipkart_cookies()

        for target in TARGETS:
            try:
                html = await engine.fetch_page(target["url"], cookie_dict, cookie_header)
                if not html:
                    results_summary.append(f"{target['name'][:10]}: FETCH_ERR")
                    continue

                base_price, eff_price, in_stock, _ = engine.parse_with_personalization(html, target["url"])

                stock_str = "IN_STOCK" if in_stock else "OOS"
                price_str = f"₹{base_price:,.0f}" if base_price else "N/A"
                if eff_price and base_price and eff_price < base_price:
                    price_str += f" (Eff: ₹{eff_price:,.0f})"

                results_summary.append(f"{target['name'][:14]}: {stock_str} @ {price_str}")

                # Check trigger condition
                triggered = target["trigger"](in_stock, base_price, eff_price)

                if triggered:
                    now = time.time()
                    last_time = last_alerted.get(target["id"], 0.0)

                    if now - last_time >= ALERT_COOLDOWN_SECONDS:
                        last_alerted[target["id"]] = now
                        logger.warning(
                            "🚨🚨🚨 TARGET MET FOR %s! Price: %s | InStock: %s! EXECUTING SNIPE ALERTS!",
                            target["name"], price_str, in_stock
                        )

                        # 1. Open Browser immediately
                        try:
                            webbrowser.open(target["url"])
                        except Exception as b_err:
                            logger.debug("Failed opening browser: %s", b_err)

                        # 2. Sound Urgent Beep Alarm
                        asyncio.create_task(asyncio.to_thread(sound_alarm))

                        # 3. Windows Toast Notification
                        show_windows_toast(
                            f"🔥 SNIPER ALERT: {target['name']}",
                            f"Status: {stock_str} | Price: {price_str}! Click to buy now."
                        )

                        # 4. Telegram Alert
                        await send_telegram_alert(target, base_price, eff_price)

            except Exception as exc:
                results_summary.append(f"{target['name'][:10]}: ERR({exc})")

            # 1.5s gentle stagger between requests
            await asyncio.sleep(1.5)

        elapsed = time.monotonic() - t_loop_start
        status_line = f"[{datetime.now().strftime('%H:%M:%S')}] LOOP #{loop_count:04d} | " + " | ".join(results_summary)
        logger.info(status_line)

        # Sleep remaining time to maintain CHECK_INTERVAL_SECONDS
        remaining = max(1.0, CHECK_INTERVAL_SECONDS - elapsed)
        await asyncio.sleep(remaining)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nLocal Sniper stopped by user.")

