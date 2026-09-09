# 🛒 SriTrack — Autonomous Price Drop Radar & Intelligence Engine

> **Production-grade, 24/7 autonomous deal radar and price drop tracker for Indian e-commerce (Amazon India, Flipkart, Casio Bhawar, and Q-Commerce), equipped with AI brand validation, authenticated clearance detection, anti-warranty BuyBox isolation, an interactive Telegram bot, and a modern SaaS executive console.**

[![Tests](https://img.shields.io/badge/tests-108%20passed-10b981?style=flat-square)](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/tests)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.14-38bdf8?style=flat-square)](https://python.org)
[![Vercel](https://img.shields.io/badge/deployment-Vercel%20Serverless-000000?style=flat-square&logo=vercel)](https://sritrack.vercel.app/)
[![Supabase](https://img.shields.io/badge/database-Supabase%20PostgreSQL-3ecf8e?style=flat-square&logo=supabase)](https://supabase.com)
[![Scrapling](https://img.shields.io/badge/scraping-Scrapling%20%2B%20Playwright-f59e0b?style=flat-square)](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/scrapers)

---

## 📑 Table of Contents

1. [System Architecture](#-system-architecture)
2. [Codebase Blueprint](#-codebase-blueprint)
3. [Key Capabilities & Innovations](#-key-capabilities--innovations)
   - [Amazon BuyBox Isolation (Anti-Warranty Rejection)](#1-amazon-buybox-isolation-anti-warranty-rejection)
   - [Casio Bhawar Member Clearance Radar (Live Storefront Verification)](#2-casio-bhawar-member-clearance-radar-live-storefront-verification)
   - [Dual Database Layer (SQLite & Supabase PostgreSQL)](#3-dual-database-layer-sqlite--supabase-postgresql)
   - [Modern SaaS Executive Console](#4-modern-saas-executive-console)
   - [AI Brand Validation Arbiter (DeepSeek-R1 / Gemini)](#5-ai-brand-validation-arbiter-deepseek-r1--gemini)
4. [API & Serverless Endpoints](#-api--serverless-endpoints)
5. [Developer & Agent Extension Guide](#-developer--agent-extension-guide)
   - [Adding a New E-Commerce Platform Scraper](#how-to-add-a-new-e-commerce-platform-scraper)
   - [Adding a New Autonomous Radar Rule](#how-to-add-a-new-autonomous-radar-rule)
   - [Extending Authenticated Store Sessions](#how-to-extend-authenticated-store-sessions)
   - [Adding New Notification Channels](#how-to-add-new-notification-channels)
6. [Testing & Quality Assurance](#-testing--quality-assurance)
7. [Deployment & Operations Guide](#-deployment--operations-guide)
   - [Cloud Deployment (Vercel + Supabase)](#1-cloud-deployment-vercel--supabase)
   - [Local Daemon Execution (SQLite + Polling)](#2-local-daemon-execution-sqlite--polling)
8. [Configuration & Environment Variables](#-configuration--environment-variables)
9. [Hard-Earned Gotchas & Lessons Learned](#-hard-earned-gotchas--lessons-learned)

---

## 🏛️ System Architecture

```
                                  [ User Touchpoints ]
                   ┌───────────────────────┴────────────────────────┐
                   ▼                                                ▼
     [ Interactive Telegram Bot ]                   [ Modern SaaS Executive Console ]
   Commands: /track, /list, /check, /sweep            Single Dashboard Nav, ⌘K Filter,
   Instant Webhook via /api/telegram                   Live Clearance Feed, REST APIs
                   │                                                │
                   └───────────────────────┬────────────────────────┘
                                           ▼
                            [ FastAPI Serverless Core ]
                              api/index.py  •  tracker.py
                                           │
       ┌───────────────────────────────────┼───────────────────────────────────┐
       ▼                                   ▼                                   ▼
[ 24/7 Deal Radar ]              [ Multi-Platform Scrapers ]          [ Anti-False-Positive Filter ]
radar.py • radar_rules.py        scrapers/ (Amazon, Casio,             1. Amazon BuyBox Isolation
Continuous catalog sweeps:        Flipkart, Myntra, Ajio,             2. Casio Storefront Verification
Casio 70%+, Apple, G-Shock        Blinkit, Zepto, BigBasket)          3. AI Brand Arbiter (DeepSeek/Gemini)
       │                                   │                                   │
       └───────────────────────────────────┼───────────────────────────────────┘
                                           ▼
                              [ Dual Persistence Layer ]
                                database.py • supabase_db.py
                        SQLite (Local)  ◄───►  Supabase PostgreSQL (Cloud)
```

---

## 🗺️ Codebase Blueprint

| File / Directory | Purpose & Key Responsibilities |
|---|---|
| [`api/index.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/api/index.py) | **Vercel Serverless Gateway**: Exposes REST endpoints (`/api/dashboard/data`, `/api/products`, `/api/sweep`, `/api/cron`), serves the UI, and routes incoming Telegram webhooks. |
| [`api/dashboard.html`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/api/dashboard.html) | **Executive Web Console**: High-performance, mobile-responsive dashboard designed with Linear/Vercel SaaS principles. Single sidebar item (`Dashboard`), `⌘K` search, metric KPIs, and live deal streams. |
| [`tracker.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/tracker.py) | **Core Tracking Engine**: Manages the poll loop, detects price drops vs target thresholds, persists historical price logs, and triggers notifications. |
| [`radar.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/radar.py) | **Steal Deal Radar**: Autonomous category deal hunter that sweeps catalog endpoints, executes multi-stage validation, and prevents alert spamming. |
| [`radar_rules.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/radar_rules.py) | **Radar Sweep Configurations**: Defines category traps (e.g. Casio 70%+ clearance, Apple hardware 50%+, Sony audio drops). |
| [`database.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/database.py) | **SQLite Data Layer**: Async `aiosqlite` implementation used for local daemon runs; exposes unified `get_database()` factory. |
| [`supabase_db.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/supabase_db.py) | **Supabase PostgreSQL Layer**: Production cloud database adapter implementing the exact same interface as `database.py` via HTTP REST. |
| [`supabase_schema.sql`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/supabase_schema.sql) | **Database Schema Definition**: PostgreSQL tables (`products`, `price_logs`, `deal_alerts_log`, `custom_radar_rules`, `system_stats`). |
| [`brand_validator.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/brand_validator.py) | **Heuristic Brand Verification**: Rule-based validator analyzing titles, accessory keywords, compatibility terms, and confidence scoring. |
| [`gemini_validator.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/gemini_validator.py) | **AI Arbiter Engine**: DeepSeek-R1 (via Cloudflare Workers AI) and Google Gemini fallbacks for contextual product verification. |
| [`telegram_bot.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/telegram_bot.py) | **2-Way Telegram Assistant**: Handles incoming chat messages, direct link enrollment (`/track <url> <price>`), and webhook payload processing. |
| [`notifier.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/notifier.py) | **Multi-Channel Dispatcher**: Formats Telegram Markdown alerts with product imagery, savings percentage, and direct buying links. |
| [`config.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/config.py) | **Pydantic Configuration**: Type-safe settings loading from environment variables or `.env` files. |
| [`run_247_radar.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/run_247_radar.py) | **Local Daemon Runner**: Executes 24/7 background loops with long-polling Telegram listener and periodic sweeps. |
| [`scrapers/`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/scrapers) | **Scraper Modules**: Dedicated extraction adapters for Amazon, Casio, Flipkart, Myntra, Ajio, BigBasket, Blinkit, Zepto, and Instamart. |
| [`tests/`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/tests) | **Test Suite**: 108 unit and integration tests covering scrapers, buybox isolation, brand validation, and database operations. |

---

## ⚡ Key Capabilities & Innovations

### 1. Amazon BuyBox Isolation (Anti-Warranty Rejection)
- **The Problem**: On Amazon India, add-on widgets (e.g. 1-Year Extended Warranty by Onsitego or protective cases) are often listed at **₹699**. Generic price selectors inadvertently scrape this accessory price instead of the primary product (e.g. ₹1,895 helmet headset), triggering catastrophic false alerts.
- **The Solution** ([`scrapers/amazon.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/scrapers/amazon.py)):
  1. **Strict Container Anchoring**: Extracts prices strictly within primary BuyBox containers: `#corePriceDisplay_desktop_feature_div`, `#corePrice_feature_div`, `#apex_desktop`, `#priceInsideBuyBox_feature_div`, and `#desktop_buybox`.
  2. **Price Priority**: Prioritizes `.priceToPay` and `.apex-pricetopay-value` classes.
  3. **Unwanted Node Hierarchy Filter**: Evaluates ancestors up to 5 levels up and rejects nodes tagged with `warranty`, `protection`, `insurance`, `accessory`, `fbt`, `sims`, `carousel`, `emi`, `.a-text-price` (strikethrough MRP), or `.apex-basisprice-value`.

### 2. Casio Bhawar Member Clearance Radar (Live Storefront Verification)
- **The Problem**: Bhawar applies the Shopify backend tag `silent_sale_product` to items across its catalog (such as `MTG-B4000B-1ADR` at ₹100,995 MRP) even when no discount is configured. Naive scrapers calculating synthetic 70% discounts based on tags alone generate false positives.
- **The Solution** ([`scrapers/casio.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/scrapers/casio.py)):
  1. **Authenticated Session Handling**: Maintains an authenticated member session via `_get_authenticated_client()` using store credentials (`CASIO_BHAWAR_EMAIL`, `CASIO_BHAWAR_PASSWORD`).
  2. **Live Storefront HTML Verification**: Executes `_verify_product_discount_on_storefront` using `asyncio.Semaphore(5)` to inspect live rendered DOM elements (`.price--on-sale`, `.price--silent-off`).
  3. **Strict Validation**: Requires `reg_price > sale_price` and verified discount percentage $\ge 70\%$.
  4. **Model Prefix Classification Engine**: Classifies models automatically into G-Shock (`GA-`, `GBD-`, `MTG-`), Edifice (`EFB-`, `ECB-`), Vintage (`A168`, `AQ-`), and General (`MTP-`, `LTP-`).

### 3. Dual Database Layer (SQLite & Supabase PostgreSQL)
- Automatically selects the database backend via [`database.py:get_database()`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/database.py#L108):
  - If `SUPABASE_URL` and `SUPABASE_KEY` are provided $\rightarrow$ [`SupabaseDatabase`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/supabase_db.py) (HTTP REST async calls).
  - If unset $\rightarrow$ [`Database`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/database.py) (local async `aiosqlite`).
- Unified API across backends: `add_product`, `get_products`, `get_active_products`, `update_price`, `record_price`, `record_deal_alert`, `get_recent_deal_alerts`, and `delete_product`.

### 4. Modern SaaS Executive Console
- Located at [`api/dashboard.html`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/api/dashboard.html) and deployed live at [https://sritrack.vercel.app/](https://sritrack.vercel.app/).
- **Design Principles**: Linear / Vercel / Raycast dark aesthetic (`#090a0f` base, `#121620` cards, 1px subtle borders).
- **Streamlined Navigation**: Single primary sidebar item (**`Dashboard`**) with active indicator and live badge; no redundant multi-tier navigation.
- **Micro-Interactions**: Instant `⌘K` search filtering, one-click preset trackers, manual sweep trigger, and touch-friendly mobile drawer with dimming backdrop.

### 5. AI Brand Validation Arbiter (DeepSeek-R1 / Gemini)
- Prevents accessories, replacement bands, and compatible cases from triggering alerts for genuine products.
- **Two-Tier Engine**:
  1. [`BrandValidator`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/brand_validator.py): Fast heuristic scoring analyzing title tokens, negative keywords, and compatibility phrases.
  2. [`GeminiValidator`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/gemini_validator.py): LLM verification querying Cloudflare DeepSeek-R1 (with automatic fallback to Google Gemini Flash).

---

## 🔌 API & Serverless Endpoints

The Vercel entrypoint [`api/index.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/api/index.py) routes all incoming requests:

| Method | Endpoint | Description | Payload / Parameters |
|---|---|---|---|
| `GET` | `/` | Serves the standalone Executive Console HTML | None (browser headers) |
| `GET` | `/api/status` | Engine health, uptime, and database connectivity | None |
| `GET` | `/api/dashboard/data` | Real-time JSON telemetry: active products, price history, recent deals, and system stats | None |
| `POST` | `/api/products` | Enrolls a new product URL into 24/7 tracking | `{"url": "...", "target_price": 1300}` |
| `POST` | `/api/products/{id}/check` | Triggers an immediate live price scrape of an item | None |
| `POST` | `/api/products/{id}/toggle` | Pauses or resumes 24/7 tracking for an item | None |
| `DELETE` | `/api/products/{id}` | Permanently removes an item from tracking | None |
| `POST` | `/api/sweep` | Executes a live Deal Radar sweep across Bhawar & Flipkart | None |
| `GET` | `/api/cron` | Automated 24/7 background deal hunter and price tracker | `Authorization: Bearer <CRON_SECRET>` (optional) |
| `POST` | `/api/telegram` | Inbound Telegram Webhook for real-time chat interactions | Telegram Update JSON |
| `GET` | `/api/set-webhook` | One-click Telegram webhook registration helper | None |

---

## 🛠️ Developer & Agent Extension Guide

### How to Add a New E-Commerce Platform Scraper

To add support for a new store (e.g. `tatacliq`, `croma`, or `myntra`):

#### Step 1: Create Scraper Module in `scrapers/<platform>.py`
Subclass `BaseScraper` from [`scrapers/base.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/scrapers/base.py):

```python
# scrapers/croma.py
from __future__ import annotations
import logging
from typing import Optional
from scrapers.base import BaseScraper, ScrapeResult, ScrapeError

logger = logging.getLogger(__name__)

class CromaScraper(BaseScraper):
    platform = "croma"
    prefer_js = False  # Set True if initial HTML lacks price and requires browser JS

    title_selectors = [
        "h1.pdp-title",
        ".product-title",
        "h1",
    ]
    price_selectors = [
        ".amount .new-price",
        ".pdp-price",
        "[data-testid='new-price']",
    ]
    out_of_stock_keywords = [
        "out of stock",
        "sold out",
        "currently unavailable",
    ]

    async def scrape(self, url: str) -> ScrapeResult:
        # 1. Fetch raw HTML via static HTTP or JS renderer
        html = await self._fetch(url)
        soup = self._make_soup(html)

        # 2. Extract title & price using base helpers
        title = self._extract_title(soup)
        price = self._extract_price(soup)
        in_stock = self._check_stock(soup)

        if not price or not title:
            raise ScrapeError(f"Could not extract price/title from {url}")

        return ScrapeResult(
            title=title,
            price=price,
            in_stock=in_stock,
            platform=self.platform,
            url=url,
        )
```

#### Step 2: Register Platform in `scrapers/__init__.py`
Open [`scrapers/__init__.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/scrapers/__init__.py):
1. Import `CromaScraper`.
2. Add domain matching to `resolve_platform(url)`:
   ```python
   elif "croma.com" in netloc:
       return "croma"
   ```
3. Add scraper instance instantiation in `get_scraper(platform)`:
   ```python
   elif platform == "croma":
       return CromaScraper()
   ```

#### Step 3: Add Automated Unit Test
In [`tests/test_scrapers.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/tests/test_scrapers.py), add mock HTML fixtures validating price, title, and out-of-stock handling:
```python
def test_croma_scraper_extracts_price():
    scraper = CromaScraper()
    html = '<h1 class="pdp-title">Sony WH-1000XM5</h1><span class="new-price">₹26,990</span>'
    soup = scraper._make_soup(html)
    assert scraper._extract_price(soup) == 26990.0
```

---

### How to Add a New Autonomous Radar Rule

Radar rules allow category-wide deal traps without specifying a product URL. Open [`radar_rules.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/radar_rules.py) and append a new `RadarRule`:

```python
RadarRule(
    name="Sony Premium Noise-Cancelling Audio (50%+ OFF)",
    category="Audio",
    query="sony wh 1000xm4 1000xm5 linkbuds wf",
    brand="Sony",
    platforms=["amazon", "flipkart"],
    min_discount=50.0,    # Minimum percentage drop
    min_price=5000.0,      # Floor price to reject silicon ear tips/cases
    negative_keywords=[
        "case", "cover", "cable", "adapter", "cushion", "replacement",
        "ear pads", "silicone", "skin"
    ],
    search_url_template={
        "amazon": "https://www.amazon.in/s?k=sony+wh-1000xm5&rh=p_8%3A50-",
        "flipkart": "https://www.flipkart.com/search?q=sony+wh-1000xm5&p%5B%5D=facets.discount_range_v1%255B%255D%3D50%2525%2Bor%2Bmore",
    }
)
```

---

### How to Extend Authenticated Store Sessions

For stores offering customer-only clearance discounts (similar to Casio Bhawar):
1. Implement session initialization in the scraper (e.g. [`scrapers/casio.py:_get_authenticated_client`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/scrapers/casio.py)):
   - Submit credentials to `/account/login`.
   - Store session cookies in `httpx.AsyncClient(cookies=...)`.
2. Inspect rendered customer DOM for discount badges (`.price--on-sale`, `.customer-discount`).
3. Never calculate synthetic discounts based on tags alone. Always verify `sale_price < regular_price`.

---

### How to Add New Notification Channels

Open [`notifier.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/notifier.py):
1. Subclass or extend `Notifier`.
2. Add channel dispatch methods (e.g. `_send_discord(webhook_url, message)` or `_send_slack(webhook_url, message)`).
3. In `send_price_drop()` and `send_deal_alert()`, invoke the new channel alongside Telegram.

---

## 🧪 Testing & Quality Assurance

Run the comprehensive unit and integration test suite:

```bash
# Run full test suite
python -m pytest tests/ -q

# Run specific scraper tests
python -m pytest tests/test_casio_enhancements.py tests/test_amazon_buybox.py -v

# Run radar and brand validator tests
python -m pytest tests/test_radar.py tests/test_brand_validator.py -q
```

**Test Coverage Summary**:
- `test_casio_enhancements.py`: Model classification, catalog pagination, silent deal filtering.
- `test_amazon_buybox.py`: BuyBox price isolation, warranty rejection, accessory filtering.
- `test_brand_validator.py`: Title tokenization, confidence scoring, accessory keyword rejection.
- `test_gemini_validator.py`: Cloudflare DeepSeek-R1 and Gemini AI arbiter evaluations.
- `test_database.py`: CRUD operations, price log history, duplicate handling.
- `test_telegram_bot.py`: Command routing, `/track` parsing, authorization checks.

---

## 🚀 Deployment & Operations Guide

### 1. Cloud Deployment (Vercel + Supabase)

1. **Database Setup**:
   - Create a free database at [Supabase](https://supabase.com).
   - In Supabase **SQL Editor**, paste and execute [`supabase_schema.sql`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/supabase_schema.sql).
2. **Deploy to Vercel**:
   - Push repository to GitHub.
   - Import project in Vercel.
   - Configure Environment Variables (see [Configuration](#-configuration--environment-variables)).
   - Deploy.
3. **Connect Telegram Webhook**:
   - Visit: `https://<your-vercel-domain>/api/set-webhook`
   - Telegram will confirm: `{"ok": true, "result": true, "description": "Webhook was set"}`
4. **Configure 24/7 Periodic Background Sweeper**:
   - Since Vercel Hobby limits scheduled crons to once daily, create a free monitor at [cron-job.org](https://cron-job.org).
   - Set URL: `https://<your-vercel-domain>/api/cron`
   - Schedule: **Every 1 minute** (or 2 minutes).

### 2. Local Daemon Execution (SQLite + Polling)

For local development or running on a personal server/Raspberry Pi:

```bash
# 1. Activate virtual environment
.\.venv\Scripts\Activate.ps1   # Windows PowerShell
source .venv/bin/activate      # Linux / macOS

# 2. Run the 24/7 background runner
python run_247_radar.py
```

The local daemon executes three concurrent loops:
- **Fast-Track Loop (every 90s)**: Sweeps Casio Bhawar & Flipkart for 70%+ clearance deals.
- **Tracking Loop (every 300s)**: Checks all active products in `price_tracker.db`.
- **Telegram Poller**: Real-time long-polling listener for user commands.

---

## ⚙️ Configuration & Environment Variables

Create a `.env` file in the project root:

| Variable | Required | Description | Example |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | **Yes** | Telegram Bot API token from `@BotFather` | `7849201948:AAH...` |
| `TELEGRAM_CHAT_ID` | **Yes** | Target chat/user ID for price alerts | `123456789` |
| `SUPABASE_URL` | *Cloud* | Supabase project URL (enables PostgreSQL) | `https://xyz.supabase.co` |
| `SUPABASE_KEY` | *Cloud* | Supabase `anon` or `service_role` API key | `sb_publishable_...` |
| `CASIO_BHAWAR_EMAIL` | Optional | Account email for Casio Bhawar member clearance | `member@example.com` |
| `CASIO_BHAWAR_PASSWORD` | Optional | Account password for Casio Bhawar | `••••••••` |
| `GEMINI_API_KEY` | Optional | Google Gemini API key for fallback AI validation | `AIzaSy...` |
| `CLOUDFLARE_ACCOUNT_ID` | Optional | Cloudflare Account ID for DeepSeek-R1 | `a1b2c3d4...` |
| `CLOUDFLARE_API_TOKEN` | Optional | Cloudflare API Token for Workers AI | `Bearer token...` |
| `CRON_SECRET` | Optional | Secret token to authenticate `/api/cron` calls | `custom_secure_token` |

---

## 💡 Hard-Earned Gotchas & Lessons Learned

1. **Amazon Extended Warranty & Accessory Hijacking**:
   - Never rely on generic `.a-price` or `.a-color-price` selectors on Amazon. Always anchor strictly to `#corePriceDisplay_desktop_feature_div` or `.priceToPay` and verify no `warranty` or `protection` ancestors exist within 5 parent levels.
2. **Shopify Tags vs Live Discounts**:
   - Do not trust Shopify product tags (e.g. `silent_sale_product`) as proof of discount. Bhawar attaches this tag to full-priced items like `MTG-B4000B-1ADR` (₹100,995). Always inspect the live rendered storefront HTML with an authenticated session.
3. **Windows PowerShell Currency Encoding (`₹`)**:
   - On Windows systems using `cp1252` encoding, printing raw Unicode `₹` (`\u20b9`) without explicit UTF-8 stdout configuration throws `UnicodeEncodeError`. Use safe formatters or set `PYTHONIOENCODING=utf-8`.
4. **Vercel Serverless Concurrency & Timeouts**:
   - Serverless functions have execution limits (10-15s on free tier). When sweeping multi-page catalogs, use `asyncio.Semaphore(5)` and prioritize top clearance handles (`silent-sale`, `sale-products`) before generic catalogs.
5. **Mobile Navigation Overlap**:
   - Avoid complex multi-item sidebars on mobile screens. A single primary `Dashboard` item paired with an off-canvas drawer and a tap-to-dismiss backdrop (`.sidebar-backdrop`) guarantees zero horizontal page scroll and effortless one-thumb navigation.

---

## 📄 License & Maintainer

Maintained by **Sriram** ([@sriramnjr7](https://github.com/sriramnjr7)).  
Designed for autonomous, reliable, and high-frequency price intelligence.