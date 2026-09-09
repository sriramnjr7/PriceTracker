"""Central configuration for the price tracker.

Every tunable value can be overridden with environment variables, which are
optionally loaded from a ``.env`` file placed in the project root. Defaults
are deliberately polite to the target retailers: long polling intervals,
random 2-5s delays between requests and rotating user agents, so the bot
does not hammer their servers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

try:  # python-dotenv is optional at runtime
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass


# A small pool of realistic desktop/mobile user agents.  A random one is picked
# per request so the traffic does not look like a single headless bot.
DEFAULT_USER_AGENTS: list[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36",
]


def _env_bool(name: str, default: bool = True) -> bool:
    """Parse a boolean-ish environment variable safely."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    """Runtime configuration, assembled from environment variables + defaults."""

    # --- Gemini AI Deal Arbiter -----------------------------------------
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))

    # --- Telegram Bot ----------------------------------------------------
    telegram_bot_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))

    # --- WhatsApp / CallMeBot -------------------------------------------
    whatsapp_phone: str = field(default_factory=lambda: os.getenv("WHATSAPP_PHONE", ""))
    whatsapp_api_key: str = field(default_factory=lambda: os.getenv("WHATSAPP_API_KEY", ""))
    callmebot_url: str = field(
        default_factory=lambda: os.getenv("CALLMEBOT_URL", "https://api.callmebot.com/whatsapp.php")
    )

    # --- Scheduling ------------------------------------------------------
    # Default: check every 30 minutes.  Shortening this is how you get blocked.
    poll_interval_seconds: int = field(
        default_factory=lambda: int(os.getenv("POLL_INTERVAL_SECONDS", "1800"))
    )
    scheduler_jitter_seconds: int = field(
        default_factory=lambda: int(os.getenv("SCHEDULER_JITTER_SECONDS", "30"))
    )

    # --- Storage ---------------------------------------------------------
    database_path: str = field(default_factory=lambda: os.getenv("DATABASE_PATH", "price_tracker.db"))

    # --- HTTP / scraping -------------------------------------------------
    request_timeout: float = field(default_factory=lambda: float(os.getenv("REQUEST_TIMEOUT", "30")))
    retries: int = field(default_factory=lambda: int(os.getenv("RETRIES", "3")))
    # Random delay between sequential requests (seconds) to stay under rate limits.
    min_delay_seconds: float = field(default_factory=lambda: float(os.getenv("MIN_DELAY_SECONDS", "2")))
    max_delay_seconds: float = field(default_factory=lambda: float(os.getenv("MAX_DELAY_SECONDS", "5")))

    # --- Playwright ------------------------------------------------------
    headless: bool = field(default_factory=lambda: _env_bool("HEADLESS", True))
    # How long to let client-side JavaScript render before dumping the DOM.
    js_wait_milliseconds: int = field(default_factory=lambda: int(os.getenv("JS_WAIT_MS", "3500")))

    # --- Geolocation / Quick Commerce ------------------------------------
    default_pincode: str = field(default_factory=lambda: os.getenv("DEFAULT_PINCODE", "560103"))
    backup_pincode: str = field(default_factory=lambda: os.getenv("BACKUP_PINCODE", "635109"))

    pincode_map: dict[str, dict[str, Any]] = field(
        default_factory=lambda: {
            "560103": {"lat": 12.9298, "lon": 77.6848, "city": "Bengaluru", "pincode": "560103"},
            "635109": {"lat": 12.7409, "lon": 77.8253, "city": "Hosur", "pincode": "635109"},
        }
    )

    def get_location(self, pincode: str | None = None) -> dict[str, Any]:
        """Resolve coordinates for a pincode (defaulting to 560103 / 635109)."""
        target = str(pincode or self.default_pincode).strip()
        if target in self.pincode_map:
            return self.pincode_map[target]
        # Default fallback to 560103 (Bengaluru)
        return self.pincode_map["560103"]

    user_agents: list[str] = field(default_factory=lambda: list(DEFAULT_USER_AGENTS))


# Module-level singleton consumed by every scraper/CLI module.
settings = Settings()