# 🛒 SriTrack — Autonomous Deal Radar & Executive Tracking Engine

> **Production-grade, 24/7 autonomous deal radar, footwear harvester, and price drop intelligence engine for Indian e-commerce (Amazon India, Flipkart, Myntra, Tata CLiQ, Ajio, Casio Bhawar, and Q-Commerce). Features AI brand validation, anti-warranty BuyBox isolation, 94-model running shoe benchmark catalog, 2-way Telegram assistant, and a modern SaaS glassmorphism executive console.**

[![Tests](https://img.shields.io/badge/tests-188%20passed-10b981?style=flat-square)](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/tests)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.14-38bdf8?style=flat-square)](https://python.org)
[![Vercel](https://img.shields.io/badge/deployment-Vercel%20Serverless-000000?style=flat-square&logo=vercel)](https://sritrack.vercel.app/)
[![Supabase](https://img.shields.io/badge/database-Supabase%20PostgreSQL-3ecf8e?style=flat-square&logo=supabase)](https://supabase.com)
[![Scrapling](https://img.shields.io/badge/scraping-Scrapling%20%2B%20curl__cffi-f59e0b?style=flat-square)](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/scrapers)
[![Antigravity](https://img.shields.io/badge/architecture-Antigravity%202.0%20%7C%20gstack-7c3aed?style=flat-square)](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/AGENTS.md)

---

## 📑 Table of Contents

1. [System Architecture & Routing Map](#-system-architecture--routing-map)
2. [Codebase Blueprint](#-codebase-blueprint)
3. [Core Subsystems & Innovations](#-core-subsystems--innovations)
   - [1. Running Shoes Harvester & Benchmark Catalog](#1-running-shoes-harvester--benchmark-catalog)
   - [2. Casio Bhawar Member Clearance Radar](#2-casio-bhawar-member-clearance-radar)
   - [3. Amazon BuyBox Isolation (Anti-Warranty Rejection)](#3-amazon-buybox-isolation-anti-warranty-rejection)
   - [4. AI Brand Validation Arbiter (DeepSeek-R1 / Gemini)](#4-ai-brand-validation-arbiter-deepseek-r1--gemini)
   - [5. Personal Inventory & Ownership Archive (My Collection)](#5-personal-inventory--ownership-archive-my-collection)
   - [6. Cloud Logging & Real-Time Telemetry Streaming](#6-cloud-logging--real-time-telemetry-streaming)
4. [Complete API & Serverless Reference](#-complete-api--serverless-reference)
5. [Antigravity IDE & Engineering Workflows (gstack)](#-antigravity-ide--engineering-workflows-gstack)
6. [Security Architecture & Threat Model (CSO Audit)](#-security-architecture--threat-model-cso-audit)
7. [Testing & Quality Assurance (188 Tests)](#-testing--quality-assurance-188-tests)
8. [Deployment & Operations Guide](#-deployment--operations-guide)
9. [Configuration & Environment Variables](#-configuration--environment-variables)
10. [Hard-Earned Gotchas & Lessons Learned](#-hard-earned-gotchas--lessons-learned)

---

## 🏛️ System Architecture & Routing Map

SriTrack operates as a hybrid serverless/daemon engine. In production on Vercel, incoming HTTP traffic is processed through an intelligent Single Page Application (SPA) routing layer backed by Supabase PostgreSQL. Locally or on dedicated hardware, a persistent 24/7 background runner executes automated sweeps and long-polls Telegram.

```
                                  [ User Touchpoints ]
                   ┌───────────────────────┴────────────────────────┐
                   ▼                                                ▼
     [ Interactive Telegram Bot ]                   [ Modern SaaS Executive Console ]
   Commands: /track, /list, /check, /sweep            Tab Navigation: Dashboard, Running Shoes,
   Instant Webhook via /api/telegram                  My Collection, Live System Logs
                   │                                                │
                   └───────────────────────┬────────────────────────┘
                                           ▼
                            [ Vercel Serverless Gateway ]
                           vercel.json  •  api/index.py
                                           │
         ┌─────────────────────────────────┼─────────────────────────────────┐
         ▼                                 ▼                                 ▼
[ SPA Page Navigation ]          [ REST API Subsystems ]           [ 24/7 Deal Radar ]
  /                              /api/status                      radar.py • running_shoes_radar.py
  /running-shoes                 /api/dashboard/data              Continuous catalog sweeps:
  /my-collection                 /api/running-shoes/status        Casio 70%+, 94 Running Shoes,
  /logs                          /api/logs, /api/sweep            Flipkart, Myntra, Tata CLiQ
         │                                 │                                 │
         └─────────────────────────────────┼─────────────────────────────────┘
                                           ▼
                              [ Dual Persistence Layer ]
                                database.py • supabase_db.py
                        SQLite (Local)  ◄───►  Supabase PostgreSQL (Cloud)
```

### Vercel SPA Routing & Query Parameter Normalization
`vercel.json` routes all non-static paths to the serverless function:
```json
{
  "rewrites": [
    { "source": "/(.*)", "destination": "/api/index.py?_vercel_path=$1" }
  ]
}
```
- **SPA Page Routes (`/`, `/running-shoes`, `/my-collection`, `/logs`)**: When accessed from a web browser (`Accept: text/html`), `api/index.py` immediately serves `api/dashboard.html`. The frontend JavaScript inspects `window.location.pathname` upon load and switches to the active tab without page reloads.
- **REST Endpoints (`/api/...`)**: When invoked by AJAX (`fetch()`) or external automation, `api/index.py` extracts `_vercel_path`, executes the appropriate backend controller, and outputs typed JSON.

---

## 🗺️ Codebase Blueprint

| File / Component | Purpose & Architecture |
|---|---|
| [`api/index.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/api/index.py) | **Vercel Serverless Core**: Entrypoint handling route rewrites, constant-time auth (`/api/auth/login`), running shoe telemetry, system log streaming, and Telegram webhooks. |
| [`api/dashboard.html`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/api/dashboard.html) | **Executive Web Console**: High-density glassmorphism UI featuring single-page tabs (Dashboard, Running Shoes, My Collection, System Logs), `⌘K` search, live charts, and modals. |
| [`running_shoes_radar.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/running_shoes_radar.py) | **Footwear Radar Engine**: Manages 94-model running catalog, size normalization (UK 9.5–11), trap model rejection, multi-platform sweeps, and deal caching. |
| [`running_shoes_catalog_data.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/running_shoes_catalog_data.py) | **Footwear Market Intelligence**: Whitelist regex patterns, exclusion rules, and researched benchmark price thresholds (`mrp`, `known_street_price`, `steal_price`, `known_atl`). |
| [`running_shoes_catalog.json`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/running_shoes_catalog.json) | **Tracked Footwear State**: Catalog cache storing active deal status, last seen prices, and sizes across 11 brands. |
| [`running_shoes_config.json`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/running_shoes_config.json) | **Footwear Harvester Config**: Global toggle, price boundaries (₹4,000–₹5,999), target sizes, platform toggles, and brand switches. |
| [`radar.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/radar.py) | **Deal Radar Engine**: Sweeps general e-commerce categories and Casio clearance catalogs, executing anti-spam cooldowns and multi-stage price validation. |
| [`radar_rules.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/radar_rules.py) | **Autonomous Radar Rules**: Preconfigured sweep rules for Casio Bhawar 70%+, Apple hardware, Sony audio, and smart accessories. |
| [`collection_data.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/collection_data.py) | **Personal Inventory Controller**: Manages owned items, purchase records, archive states, and custom uploaded assets. |
| [`tracker.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/tracker.py) | **Product Poller**: Background polling coordinator, price drop calculator, and historical price recorder. |
| [`brand_validator.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/brand_validator.py) | **Heuristic Brand Filter**: Rule-based validator rejecting third-party straps, cases, screen protectors, and counterfeit listings. |
| [`gemini_validator.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/gemini_validator.py) | **AI Arbiter Engine**: DeepSeek-R1 (via Cloudflare Workers AI) and Google Gemini Flash fallbacks for contextual product validation. |
| [`database.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/database.py) | **SQLite Database Layer**: Asynchronous local storage (`aiosqlite`) for development and local daemon operation. |
| [`supabase_db.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/supabase_db.py) | **Supabase PostgreSQL Layer**: Production cloud database adapter implementing the unified database protocol via HTTP REST. |
| [`supabase_schema.sql`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/supabase_schema.sql) | **Cloud Database Schema**: Tables for `products`, `price_logs`, `deal_alerts_log`, `custom_radar_rules`, and `system_stats`. |
| [`notifier.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/notifier.py) | **Notification Dispatcher**: Formats Telegram Markdown alerts with product thumbnails, discount calculations, and direct affiliate/store links. |
| [`telegram_bot.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/telegram_bot.py) | **Telegram Bot Assistant**: Interactive command handler (`/track`, `/list`, `/check`, `/sweep`, `/status`) and webhook processor. |
| [`config.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/config.py) | **Settings Layer**: Pydantic-based configuration reading environment variables with secure defaults. |
| [`run_247_radar.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/run_247_radar.py) | **Persistent Daemon Runner**: 24/7 multi-threaded runner with periodic catalog sweep intervals and long-polling Telegram loop. |
| [`heartbeat.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/heartbeat.py) | **Daemon Liveness Monitor**: Writes periodic timestamp heartbeats to prevent stalled background workers. |
| [`scrapers/`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/scrapers) | **Platform Scraper Suite**: Scrapers for Amazon (`amazon.py`), Flipkart (`flipkart.py`), Casio Bhawar (`casio.py`), Myntra (`myntra.py`), Ajio (`ajio.py`), and Q-Commerce (`qcommerce.py`). |
| [`tests/`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/tests) | **Automated Test Suite**: 188 unit, regression, and integration tests across 24 test suites. |

---

## ⚡ Core Subsystems & Innovations

### 1. Running Shoes Harvester & Benchmark Catalog
The footwear tracking engine ([`running_shoes_radar.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/running_shoes_radar.py) and [`running_shoes_catalog_data.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/running_shoes_catalog_data.py)) tracks high-performance running silhouettes across 11 whitelisted brands:
- **Whitelisted Brands**: Saucony, Hoka, Brooks, Nike, Adidas, Puma, Asics, New Balance, Skechers, Reebok, On Running.
- **Benchmark Pricing Model**:
  Every catalog model is initialized with static market research data:
  * `mrp`: Maximum Retail Price in India (e.g. Saucony Hurricane ₹17,990).
  * `known_street_price`: Typical street discounted price (e.g. ₹12,990).
  * `steal_price`: Algorithmic deal threshold that triggers high-priority alerts (e.g. ₹7,999).
  * `known_atl`: Historical All-Time Low seen across Indian storefronts (e.g. ₹5,499).
  * `available_sizes`: Guarded target UK/IND sizes (`["UK 9.5", "UK 10", "UK 10.5", "UK 11"]`).
- **Telemetry States Explained**:
  * **Why `current_price: null` appears**: Before the crawler discovers an active in-stock listing on Myntra, Flipkart, Tata CLiQ, or Ajio matching the exact model and size, `current_price` remains `null`.
  * **Why `status: "TRACKING"` appears**: Indicates the shoe silhouette is actively watched by the radar. When a live discount is scraped, status transitions to `"STEAL DEAL"` or `"AVAILABLE"`, and `times_seen` increments.
- **Trap Model Blacklist Engine**:
  Cheaper entry-level lifestyle and walking shoes are strictly rejected via regex:
  ```python
  TRAP_MODELS_BLACKLIST = re.compile(
      r"\b(energen|rewind|runfalcon|galaxy|coreracer|fluidflow|downshifter|"
      r"revolution|quest|defy\s*all\s*day|softride|anzarun|flyer\s*runner|flyer|enzo|better\s*foam|"
      r"jolt|patriot|raiden|gel[-\s]?contend|contend|arishi|roav|cohesion|excursion|versafoam|"
      r"duramo\s+(?:10|sl|lite|rc)|court|badminton|tennis|cricket|kids|gs|ps|infant|junior)\b",
      re.IGNORECASE,
  )
  ```

### 2. Casio Bhawar Member Clearance Radar
- **Authenticated Session**: Logs into Bhawar using `CASIO_BHAWAR_EMAIL` and `CASIO_BHAWAR_PASSWORD`.
- **Live DOM Verification**: Inspects live rendered storefront HTML elements (`.price--on-sale`, `.price--silent-off`) using `asyncio.Semaphore(5)` to prevent false alerts triggered by Shopify backend tags.
- **VIP Watches Priority Watch**: Continuously tracks flagship pieces:
  * **G-Shock GBD-H2000** (Heart Rate + GPS Multi-Sport)
  * **G-Shock GBD-300-9DR** (Slim High-Luminosity Bluetooth Step Tracker)

### 3. Amazon BuyBox Isolation (Anti-Warranty Rejection)
- **The Problem**: On Amazon India, add-on widgets (such as a 1-Year Extended Warranty by Onsitego or protective cases) are frequently priced at **₹699**. Generic price selectors inadvertently scrape this accessory price instead of the primary product, triggering catastrophic false alerts.
- **The Solution** ([`scrapers/amazon.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/scrapers/amazon.py)):
  1. **Strict Container Anchoring**: Extracts prices strictly within primary BuyBox containers: `#corePriceDisplay_desktop_feature_div`, `#corePrice_feature_div`, `#apex_desktop`, `#priceInsideBuyBox_feature_div`, and `#desktop_buybox`.
  2. **Ancestry Evaluation Filter**: Evaluates ancestors up to 5 levels up and rejects nodes tagged with `warranty`, `protection`, `insurance`, `accessory`, `fbt`, `sims`, `carousel`, `emi`, `.a-text-price` (strikethrough MRP), or `.apex-basisprice-value`.

### 4. AI Brand Validation Arbiter (DeepSeek-R1 / Gemini)
- Two-tier validation preventing accessories and counterfeit listings from triggering alerts:
  1. [`BrandValidator`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/brand_validator.py): Sub-millisecond heuristic scoring analyzing title tokens, negative keywords, and compatibility phrases.
  2. [`GeminiValidator`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/gemini_validator.py): LLM verification querying Cloudflare DeepSeek-R1 with automatic fallback to Google Gemini Flash.

### 5. Personal Inventory & Ownership Archive (My Collection)
- Personal asset and watch inventory management ([`collection_data.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/collection_data.py)):
  * Tracks serial numbers, purchase dates, purchase prices, estimated market values, and ownership status.
  * Supports archiving items, restoring archived watches, and serving custom photographic assets via `/assets/collection/{filename}`.

### 6. Cloud Logging & Real-Time Telemetry Streaming
- Serverless environments lack persistent local filesystems. SriTrack routes background daemon logs into Supabase `custom_radar_rules` table under keys `DAEMON_LOG` and `VIP_LOG`.
- The dashboard frontend streams these logs via `/api/logs` with real-time level filtering (`ERROR`, `WARNING`, `INFO`) and full-text search.

---

## 🔌 Complete API & Serverless Reference

All routes are dispatched through [`api/index.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/api/index.py):

| Method | Endpoint | Description | Request Format / Parameters | Response Type |
|---|---|---|---|---|
| `GET` | `/` | Executive Dashboard Web Console | Browser Request (`Accept: text/html`) | `text/html` |
| `GET` | `/running-shoes` | Running Shoes Radar Tab | Browser Request (`Accept: text/html`) | `text/html` |
| `GET` | `/my-collection` | Personal Inventory & Archive Tab | Browser Request (`Accept: text/html`) | `text/html` |
| `GET` | `/logs` | System Logs Telemetry Tab | Browser Request (`Accept: text/html`) | `text/html` |
| `POST` | `/api/auth/login` | Dashboard Password Authentication | `{"password": "...", "email": "..."}` | `application/json` |
| `GET` | `/api/status` | System health, uptime, and database count | None | `application/json` |
| `GET` | `/api/dashboard/data` | Real-time telemetry, active items, and deals | None | `application/json` |
| `POST` | `/api/products` | Enroll a new product into 24/7 tracking | `{"url": "...", "target_price": 4999}` | `application/json` |
| `POST` | `/api/products/{id}/check` | Immediate live price scrape of single item | None | `application/json` |
| `POST` | `/api/products/{id}/toggle` | Pause or resume tracking for an item | None | `application/json` |
| `POST` | `/api/products/{id}/target-price` | Update target price threshold | `{"target_price": 4499}` | `application/json` |
| `DELETE` | `/api/products/{id}` | Permanently delete tracked product | None | `application/json` |
| `GET` | `/api/products/{id}/history` | Historical price chart series data | `?range=weekly` (or `monthly`, `all`) | `application/json` |
| `GET` | `/api/running-shoes/status` | Footwear radar telemetry, catalog, and deals | None | `application/json` |
| `POST` | `/api/running-shoes/toggle` | Toggle footwear radar active state | `{"active": true}` | `application/json` |
| `POST` | `/api/running-shoes/toggle-brand` | Toggle specific brand tracking | `{"brand": "Saucony", "enabled": true}` | `application/json` |
| `POST` | `/api/running-shoes/toggle-shoe` | Pause or resume tracking for a single silhouette | `{"id": "shoe_saucony_hurricane"}` | `application/json` |
| `POST` | `/api/running-shoes/sweep` | Trigger on-demand footwear sweep | None | `application/json` |
| `GET` | `/api/logs` | Fetch system execution logs | `?limit=250&level=warning&search=...` | `application/json` |
| `GET` | `/api/logs/vip` | Fetch VIP watches clearance logs | None | `application/json` |
| `DELETE`| `/api/logs` | Clear local and cloud log buffers | None | `application/json` |
| `GET` | `/api/collection` | Fetch owned inventory items | None | `application/json` |
| `POST` | `/api/collection` | Add item to personal collection | Multipart/JSON item payload | `application/json` |
| `POST` | `/api/collection/{id}/archive` | Archive or restore collection item | None | `application/json` |
| `DELETE`| `/api/collection/{id}` | Remove item from collection | None | `application/json` |
| `POST` | `/api/sweep` | Trigger live Casio & Flipkart deal sweep | None | `application/json` |
| `GET` | `/api/cron` | Automated 24/7 background scanner endpoint | `Authorization: Bearer <CRON_SECRET>` | `application/json` |
| `POST` | `/api/telegram` | Telegram Webhook endpoint | Telegram Update JSON | `application/json` |
| `GET` | `/api/set-webhook` | 1-Click Telegram Webhook configuration | None | `application/json` |

---

## 🛠️ Antigravity IDE & Engineering Workflows (gstack)

SriTrack is optimized for pair-programming and deployment within **Google Antigravity IDE** and the **gstack** workflow suite:

### 1. gstack Slash Commands
- `/office-hours`: YC Office Hours feature refinement asking the 6 forcing questions (demand reality, status quo, desperate specificity, narrowest wedge, observation, future-fit).
- `/plan-ceo-review`: Challenges scope, cuts complexity, and validates customer value.
- `/plan-eng-review`: Locks schemas, edge cases, failure modes, and performance bottlenecks.
- `/review`: Pre-landing code review analyzing diffs for regressions, trust boundaries, SQL injection risks, and side effects.
- `/cso`: Chief Security Officer audit covering OWASP Top 10, STRIDE threat models, and secret leaks.
- `/qa`: Autonomous browser verification of frontend flows.
- `/scrape`: Targeted web scraping using Scrapling fetchers.
- `/ship`: Prepares diffs, executes test suites, and pushes clean Git commits.

### 2. Antigravity Agent Configuration
- Model behaviors, prompt overlays, and scraper settings are configured in [`AGENTS.md`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/AGENTS.md) and [`GEMINI.md`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/GEMINI.md).
- Custom skills reside in `.agents/skills/` (`review`, `cso`, `qa`, `scrape`, `office-hours`, `plan-ceo-review`).

---

## 🔒 Security Architecture & Threat Model (CSO Audit)

### 1. STRIDE Threat Model
- **Spoofing**: Telegram webhook validated via secret path tokens and bot token validation. Login endpoints enforce constant-time password matching (`hmac.compare_digest`).
- **Tampering**: All price update queries in SQLite and PostgreSQL use parameterized inputs (`?` and Supabase PostgREST parameter binding) to eliminate SQL injection risks.
- **Repudiation**: Every price update, alert dispatch, and manual sweep is timestamped and recorded in `price_logs` and `deal_alerts_log`.
- **Information Disclosure**: Internal traceback details are suppressed in production. Database files (`price_tracker.db`) and secret configs (`.env`) are excluded via `.gitignore`.
- **Denial of Service**: External web scrapers implement `asyncio.Semaphore(5)` to prevent local thread exhaustion, paired with browser impersonation (`impersonate="chrome"`) to avoid IP bans.
- **Elevation of Privilege**: Admin dashboard mutations (`toggle`, `delete`, `sweep`) require server-side session authentication.

### 2. Credential Hygiene
- All sensitive credentials (`TELEGRAM_BOT_TOKEN`, `SUPABASE_KEY`, `CASIO_BHAWAR_PASSWORD`, `GEMINI_API_KEY`) are loaded via [`config.py`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/config.py) from environment variables. No secrets are committed to version control.

---

## 🧪 Testing & Quality Assurance (188 Tests)

The test suite covers unit logic, external platform HTML mocks, false positive rejection, and serverless routing:

```bash
# Execute entire test suite
python -m pytest tests/

# Execute specific subsystems
python -m pytest tests/test_running_shoes_radar.py tests/test_logs_endpoint.py
python -m pytest tests/test_amazon_variants.py tests/test_flipkart_variants.py
python -m pytest tests/test_brand_validator.py tests/test_casio_enhancements.py
```

### Test Suite Breakdown (188 Passed):
- `test_amazon_variants.py`: Amazon Twister multi-color ASIN extraction and parent-asin normalization.
- `test_auth.py`: Constant-time login hashing, bad password rejection, and session validation.
- `test_brand_validator.py`: Title tokenization, compatibility filter, and counterfeit score rejection.
- `test_casio_enhancements.py`: Model classification, catalog pagination, silent deal filtering.
- `test_cli.py`: Terminal commands, formatting, and argument parsing.
- `test_collection.py`: Personal inventory CRUD, archive state toggling, asset path resolvers.
- `test_database.py`: Dual-backend protocol compliance, price log retention, duplicate handling.
- `test_false_positive_guardrails.py`: Accessory rejection and extreme discount sanity checks.
- `test_flipkart_variants.py`: Flipkart size-filtered variant price extraction.
- `test_gemini_validator.py`: AI arbiter evaluations via DeepSeek and Gemini.
- `test_heartbeat.py`: Daemon liveness monitor and timeout detection.
- `test_logs_endpoint.py`: Cloud log parser, level filtering, and `/logs` SPA browser route validation.
- `test_notifier.py`: Telegram message formatting, photo attachments, and discount badge calculations.
- `test_price_history.py`: Sparkline price series generation and period aggregators.
- `test_qa_casio_sales.py`: Storefront DOM discount extraction and price delta verification.
- `test_qcommerce_radar.py`: Blinkit, Zepto, and Instamart product pricing.
- `test_radar.py`: Autonomous deal radar sweeps and rule evaluation.
- `test_running_shoes_radar.py`: 94-model whitelist matching, trap model rejection, size normalization, and `/running-shoes` SPA routing.
- `test_scrapers.py`: HTML parser resilience across Amazon, Flipkart, Myntra, Ajio, and Casio.
- `test_shoe_steal_and_cooldown.py`: Steal deal alerts and notification cooldown timers.
- `test_sneaker_steal_deals.py`: Lifestyle sneaker pricing and multi-size availability.
- `test_target_price_endpoint.py`: Real-time target price updates.
- `test_telegram_bot.py`: Command dispatching (`/track`, `/list`, `/check`, `/sweep`).
- `test_tracker.py`: Background tracking loop and price drop alert triggers.

---

## 🚀 Deployment & Operations Guide

### 1. Cloud Deployment (Vercel + Supabase)
1. **Database Setup**:
   - Create a free PostgreSQL instance on [Supabase](https://supabase.com).
   - In Supabase **SQL Editor**, execute [`supabase_schema.sql`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/supabase_schema.sql).
2. **Deploy to Vercel**:
   - Push repository to GitHub.
   - Import the repository in Vercel.
   - Configure Environment Variables (see [Configuration](#-configuration--environment-variables)).
   - Deploy.
3. **Connect Telegram Webhook**:
   - Visit: `https://<your-vercel-domain>/api/set-webhook`
   - Telegram will confirm: `{"ok": true, "result": true, "description": "Webhook was set"}`
4. **Configure Automated Cron Sweeper**:
   - Setup a monitor at [cron-job.org](https://cron-job.org) targeting `https://<your-vercel-domain>/api/cron`.
   - Set execution interval to **Every 1 minute**.

### 2. Local 24/7 Daemon Execution (Windows / Linux)
```powershell
# Windows PowerShell
.\start_radar_daemon.cmd

# Linux / macOS
python run_247_radar.py
```
The local runner executes three concurrent loops:
- **Fast-Track Loop (every 90s)**: Sweeps Casio clearance & Flipkart deals.
- **Tracking Loop (every 300s)**: Checks all enrolled products.
- **Telegram Poller**: Real-time long-polling listener for user commands.

---

## ⚙️ Configuration & Environment Variables

Create a `.env` file in the project root:

| Variable | Required | Description | Example |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | **Yes** | Telegram Bot API token from `@BotFather` | `7849201948:AAH...` |
| `TELEGRAM_CHAT_ID` | **Yes** | Target chat ID for instant price drop alerts | `123456789` |
| `SUPABASE_URL` | *Cloud* | Supabase project URL (enables PostgreSQL) | `https://xyz.supabase.co` |
| `SUPABASE_KEY` | *Cloud* | Supabase `anon` or `service_role` API key | `sb_publishable_...` |
| `CASIO_BHAWAR_EMAIL` | Optional | Account email for Casio Bhawar member clearance | `member@example.com` |
| `CASIO_BHAWAR_PASSWORD` | Optional | Account password for Casio Bhawar | `••••••••` |
| `GEMINI_API_KEY` | Optional | Google Gemini API key for AI brand validation | `AIzaSy...` |
| `CLOUDFLARE_ACCOUNT_ID` | Optional | Cloudflare Account ID for DeepSeek-R1 | `a1b2c3d4...` |
| `CLOUDFLARE_API_TOKEN` | Optional | Cloudflare API Token for Workers AI | `Bearer token...` |
| `CRON_SECRET` | Optional | Secret token protecting `/api/cron` | `custom_secure_token` |
| `DASHBOARD_PASSWORD` | Optional | Password protecting web console actions | `8910` |

---

## 💡 Hard-Earned Gotchas & Lessons Learned

1. **SPA Route Interception on Vercel Rewrites**:
   - Rewriting `/(.*)` to `/api/index.py?_vercel_path=$1` causes clean paths like `running-shoes` or `logs` to reach the Python entrypoint. Unconditional substring matching (`"running-shoes" in clean`) without checking `is_browser_request` dumps raw JSON to browsers. Always prioritize `Accept: text/html` requests for top-level client routes.
2. **Pre-Initialized Benchmark Catalogs**:
   - Footwear and collector catalogs seed benchmark market data (`mrp`, `known_street_price`, `steal_price`, `known_atl`) at initialization while leaving `current_price` as `null` and `status` as `"TRACKING"` until a live scraping pass verifies stock in target sizes.
3. **Amazon Extended Warranty & Accessory Hijacking**:
   - Never rely on generic `.a-price` or `.a-color-price` selectors on Amazon India. Always anchor strictly to `#corePriceDisplay_desktop_feature_div` or `.priceToPay` and verify no `warranty` or `protection` ancestors exist within 5 parent levels.
4. **Shopify Tags vs Live Storefront Discounts**:
   - Never trust backend product tags like `silent_sale_product` on Shopify stores. Bhawar tags high-end items like `MTG-B4000B-1ADR` (₹100,995) with this tag even at full retail price. Always verify live rendered HTML classes (`.price--on-sale`) using an authenticated member session.
5. **Windows Currency Encoding (`₹`)**:
   - On Windows consoles using `cp1252`, printing raw Unicode `₹` (`\u20b9`) without UTF-8 stdout configuration throws `UnicodeEncodeError`. Always use safe formatters or set `PYTHONIOENCODING=utf-8`.

---

## 📄 License & Maintainer

Maintained by **Sriram** ([@sriramnjr7](https://github.com/sriramnjr7)).  
Autonomous price intelligence engineered for precision, speed, and zero false alerts.