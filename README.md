# 🛒 Antigravity Price Tracker: 24/7 Autonomous AI Deal Radar

A continuous, autonomous deal-hunting daemon that monitors 9+ major Indian e-commerce platforms (Amazon, Flipkart, Casio Bhawar, Q-Commerce) for category-wide "steal deals" and pricing glitches. 

Unlike standard trackers that monitor specific user-provided URLs, this system **sweeps entire categories** (e.g., all 70%+ drops on G-Shock watches, all 50%+ drops on Apple gadgets) and uses **AI-powered Brand Validation** (Cloudflare DeepSeek-R1 / Gemini) to filter out fake accessories and knockoffs before alerting you via an interactive **Telegram Bot**.

---

## ✨ Key Features

- **Category-Wide Sweeping** — Don't track single URLs. Set rules like "Notify me if ANY G-Shock drops below ₹4000."
- **Casio Fast-Track Loop** — The official Casio Bhawar store runs on an isolated, high-frequency continuous loop (every 60s) to catch flash drops before they sell out, completely bypassing Amazon/Flipkart rate limits.
- **AI Brand Validation System** — 
  - Extracts structured brand metadata from DOM elements (search cards, span tags).
  - Uses an AI Arbiter (DeepSeek-R1 via Cloudflare, fallback to Gemini) to verify product legitimacy.
  - Strict confidence scoring (+100 for exact match, -100 for compatibility phrases like "for Samsung", -150 for explicit third-party brands).
- **2-Way Interactive Telegram Bot** — 
  - Receive rich alerts (Image, Price, MRP, AI Verdict).
  - Add specific personal tracks directly via chat (e.g., `/track https://amazon... 1500`).
- **9 Supported Platforms** — Amazon India, Flipkart, Myntra, Ajio, Casio Store Bhawar, BigBasket, Blinkit, Zepto, and Swiggy Instamart.
- **Stealth Scrapling Engine** — Bypasses TLS fingerprinting, JS challenges, and bot protections using Scrapling and Chrome impersonation.

---

## 🏗️ Architecture

```
[Scraping Layer] 
  Amazon/Flipkart (Broad sweeps every 5m)
  Casio Bhawar (Fast-track loop every 60s)
         |
         v
[Validation Layer]
  1. Price Floor Filter (rejects ₹99 straps)
  2. Negative Keyword Filter (rejects "case", "cover")
  3. Strict BrandValidator Engine (Confidence Score)
  4. AI Arbiter (DeepSeek-R1) Contextual verification
         |
         v
[Dispatch Layer]
  De-duplication Cache (Prevents spam, allows new lows)
  Telegram / WhatsApp Notification Engine
```

---

## 🚀 Setup & Configuration

### 1. Prerequisites
- Python 3.10+
- A Telegram Bot Token (from BotFather)
- Cloudflare Workers AI API Key (for DeepSeek-R1 validation)
- Google Gemini API Key (Fallback AI)

### 2. Installation
```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
```

### 3. Environment Setup
Create a `.env` file in the root directory:
```dotenv
# Telegram
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here

# AI Arbiters
GEMINI_API_KEY=your_gemini_key_here
CLOUDFLARE_ACCOUNT_ID=your_cf_account_id
CLOUDFLARE_API_TOKEN=your_cf_api_token
```

### 4. Customizing Radar Rules
Rules are defined in `radar_rules.py`. You can configure broad sweeps or specific product traps.

```python
# Example: Broad Apple sweep
RadarRule(
    name="Apple All Gadgets & Hardware (50%+ OFF)",
    category="Premium Tech",
    query="apple iphone ipad macbook airpods watch",
    brand="Apple",
    platforms=["amazon", "flipkart"],
    min_discount=50.0,
    min_price=1000.0,
)

# Example: Highly specific GBD-300 Fast-Track
RadarRule(
    name="Casio GBD-300 Specific Tracker",
    category="Watches",
    query="casio g-shock gbd-300 9dr watch",
    brand="Casio",
    platforms=["casio"],
    max_price=4000.0, # Target price threshold
    search_url_template={
        "casio": "https://casiostore.bhawar.com/products/casio-g-shock-gbd-300-9dr-watch",
    }
)
```

---

## 🌐 Vercel Serverless & Supabase Cloud Deployment

PriceTracker can run 100% serverless on **Vercel** with persistent storage on **Supabase (PostgreSQL)** and instantaneous **Telegram Webhooks**.

### 1. Supabase Database Setup (Free)
1. Create a free project at [supabase.com](https://supabase.com).
2. Open the **SQL Editor**, paste the contents of [`supabase_schema.sql`](file:///c:/Users/srira/Downloads/Antigravity/PriceTracker/supabase_schema.sql), and click **Run**.
3. Under **Project Settings -> API**, copy:
   - `Project URL` (`https://<project-ref>.supabase.co`)
   - `anon` or `service_role` API key.

### 2. Deploy to Vercel
1. Push this repository to GitHub and import it on [Vercel](https://vercel.com).
2. In Vercel Project Settings ➡️ **Environment Variables**, add:
   - `TELEGRAM_BOT_TOKEN`: Your Telegram Bot API token
   - `TELEGRAM_CHAT_ID`: Your Telegram numeric chat ID
   - `SUPABASE_URL`: `https://<your-project>.supabase.co`
   - `SUPABASE_KEY`: Your Supabase API key
   - `CRON_SECRET`: *(Optional)* Secret token to protect the cron endpoint
3. Click **Deploy**.

### 3. One-Click Telegram Webhook Setup
Once deployed on Vercel, visit:
`https://<your-vercel-app>.vercel.app/api/set-webhook` in your browser.
Telegram will respond:
`{"action": "setWebhook", "telegram_response": {"ok": true, "result": true, "description": "Webhook was set"}}`

Now, whenever you send any link or command to the bot on Telegram (e.g. `https://amzn.in/... 2000` or `https://casiostore.bhawar.com/... 4000`), Vercel wakes up immediately, scrapes the live item, saves it to Supabase, and confirms tracking in chat!

### 4. 24/7 1-Minute Deal & Price Check Trigger
Since the Vercel Hobby plan restricts native cron jobs to once a day:
1. Create a free account on [cron-job.org](https://cron-job.org).
2. Create a new Cronjob:
   - **URL**: `https://<your-vercel-app>.vercel.app/api/cron`
   - **Schedule**: **Every 1 minute** (or every 2-5 minutes).
3. Save the job. It will ping your Vercel endpoint 24/7, sweeping Casio Bhawar & Flipkart for 70%+ drops and checking your custom tracked items!

---

## 🏃 Running Locally (Daemon Mode)

If you prefer to run locally on your machine with SQLite:
```bash
python run_247_radar.py
```
The local runner will execute:
1. **Casio & Flipkart 70%+ Loop**: Sweeps Bhawar & Flipkart every 90 seconds.
2. **Manual Tracker Loop**: Sweeps active custom tracked products every 300 seconds.
3. **Telegram Long-Polling Listener**: Listens for chat commands and URLs in real-time.