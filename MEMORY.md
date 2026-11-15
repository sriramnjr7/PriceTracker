# 🧠 SriTrack System Memory & Operational Knowledge Base

> **Definitive system memory, architectural state, restock intelligence, and e-commerce reverse-logistics rules for SriTrack.**

---

## 📌 Executive Status (Current Active State)

| Subsystem | Node / Location | Status | Details |
|---|---|---|---|
| **Local Snipers** | Windows Workstation | **PAUSED (0 PIDs)** | All local python background sniper scripts terminated. Zero local CPU/network overhead. |
| **Cloud Radar Daemon** | Oracle Cloud VM (`140.245.250.104`) | **RUNNING** (`systemd`) | `pricetracker.service` running. Dynamically checks `is_active` per product each sweep loop. |
| **Vercel Gateway** | `https://sritrack.vercel.app` | **LIVE (Serverless)** | Serves dashboard UI, REST API, logs streamer, and Telegram webhook. |
| **Database** | Supabase PostgreSQL (`sritrack`) | **SYNCED** | Cloud database of record. Holds products, price logs, deal alerts, and custom daemon rules. |
| **Watch #111 (Black GBD-300)** | Flipkart (`WATH6HSUVHVMZVPW`) | **PAUSED (`is_active: false`)** | Exchange secured. Tracking paused. **1-Click resume available on Web Console.** |
| **Watch #132 (White GBD-300)** | Flipkart (`WATH6HSUGTFEH4YZ`) | **PAUSED (`is_active: false`)** | Replaced/exchanged. Tracking paused. |
| **Watch #148 (Casio Edifice)** | Glitch listing | **PURGED** | Completely deleted from database. |

---

## 🏆 Case Study: Casio GBD-300-1DR Zero-Cost Exchange Snipe

### 1. Order Milestones & Victory Telemetry
- **Original Purchase**: CASIO G-SHOCK GBD-300-7DR (White) purchased on Flipkart for **₹5,894** (MRP ₹11,725).
- **Target Item**: CASIO G-SHOCK GBD-300-1DR (Stealth Black, `WATH6HSUVHVMZVPW`). Out of stock for multiple weeks; listed at **₹10,294** (effective ₹9,544 after card offers) whenever briefly restocked.
- **The Execution (Sat Nov 7, 2026)**:
  - **19:55:51 IST (14:25:51 UTC)**: SriTrack's 15-second Scrapling radar detected restock of Black GBD-300-1DR at ₹10,294.
  - **Alert Dispatch**: Dispatched 8 high-priority VIP restock notifications to Telegram and logged to Supabase.
  - **Inventory Window Duration**: Exactly **11 minutes** (19:55:51 to 20:07:00 IST) before selling out again.
  - **Exchange Swap Executed**: User triggered variant swap on the active Flipkart order.
  - **Final Price Paid**: **₹0 additional rupees** (Order confirmed at original invoice price of **₹5,894 + 50 SuperCoins**).
  - **Delivery Schedule**: **Saturday, Nov 14, 2026** (Flipkart Assured Seller: Wizrob Fashion, Open Box Delivery).
  - **Flipkart Order Status**: Original White replacement marked **Cancelled / Return approved**; Black GBD-300-1DR marked **Order Confirmed**.

---

## ⚖️ Flipkart Reverse Logistics & OMS Workflow Intelligence

This knowledge was verified through live order execution and reverse engineering of Flipkart's Order Management System (OMS):

### 1. 1-to-1 Variant Exchange Parity (₹0 Delta Rule)
- Flipkart's catalog system groups color and size variants under a single parent listing family (FSN group).
- When initiating a **Variant Exchange** on an existing purchase, the OMS locks the exchange price to the **original order invoice price**, waiving 100% of the live price differential.
- *Proof*: Swapped from ₹5,894 White order to ₹10,294 Black restock without paying the ₹4,400 price difference.

### 2. The "Replacement-in-Transit" Override Maneuver
- **Standard Flow**: A customer initiates a "Replacement" on the final day of the 10-day return window to extend possession time.
- **The Child Order Lockout Trap**: Once a replacement item is marked delivered by the courier, Flipkart's self-service portal demotes the transaction to a "Child Replacement Order". Under child orders, the UI disables color/size variant exchanges and restricts future self-service actions strictly to **"Return for Full Refund"**.
- **The Solution**: If the desired alternate variant restocks *while* the replacement is still open, in transit, or awaiting fulfillment, Flipkart's mobile app allows converting or superseding the open replacement request directly into a **Variant Exchange**, bypassing the child order lockout.

### 3. Open Box Delivery Protocol
- Flipkart flags electronics and high-value fashion (e.g. G-Shock watches) with **Open Box Delivery**.
- The delivery executive must unbox the package in front of the customer to verify physical integrity and model number (`GBD-300-1DR`) before the customer shares the delivery OTP.
- Never share the delivery OTP until the inner Casio tin and black watch unit are inspected.

---

## 📊 Restock Cadence & Catalog Sync Telemetry

Analysis of 107 restock alerts recorded in Supabase `deal_alerts_log`:
- **Restock Interval**: Restocks occur on average every **3.5 days** (73 to 83 hours) when batches cycle through regional fulfillment hubs (e.g. Wizrob Fashion).
- **Time-of-Day Clusters**:
  - **Morning Cluster**: 10:00 AM – 01:30 PM IST (warehouse receiving scans).
  - **Night Cluster**: 09:30 PM – 01:00 AM IST (system inventory reconcile and cart abandonment release).
- **Catalog Sync Leading Indicator**:
  - Flipkart catalog updates frequently exhibit a **midnight price drop / metadata change** that precedes actual inventory allocation by 12 to 24 hours. A price fluctuation without immediate buy button availability signals an imminent restock batch.

---

## 🎛️ 1-Click Web Console Control (Pause / Resume Runbook)

SriTrack implements stateless, zero-restart tracking controls:

```
[ Web Dashboard: https://sritrack.vercel.app ]
                     │
         User clicks "Resume Alerts"
                     │
                     ▼
       POST /api/products/111/toggle
                     │
                     ▼
  Supabase DB: UPDATE products SET is_active = true
                     │
                     ▼
  Cloud Daemon (Oracle VM run_247_radar.py)
  Reads db_prod.is_active on next 15s/60s loop
  ──> Immediately resumes high-frequency surveillance!
```

### How to Toggle Surveillance:
1. **Via Executive Web Console**:
   - Navigate to `https://sritrack.vercel.app/`
   - In the **VIP Clearance Radar** cards on the main dashboard, locate:
     `GBD-300-1DR • Flipkart Restock Sniper`
   - Click the button:
     - **"Resume Alerts"** (when paused) — Turns button green and instantly re-arms radar.
     - **"Pause Alerts"** (when active) — Suspends scraping passes for Product #111.
2. **Via Main Products Table**:
   - Find row #111 (`CASIO G-SHOCK GBD-300-1DR`).
   - Click the **Pause / Resume** icon button in the Actions column.
3. **Via Telegram Bot**:
   - Send `/track https://www.flipkart.com/casio-gbd-300-1dr-g-shock-digital-watch-men/p/itmd46dfdac5b669?pid=WATH6HSUVHVMZVPW 10500` to re-enroll or update threshold.
4. **Via cURL / REST API**:
   ```bash
   curl -X POST https://sritrack.vercel.app/api/products/111/toggle
   ```

---

## 🛡️ Engineering & Security Standards
- **TLS Fingerprint Impersonation**: Always use Scrapling with `impersonate="chrome"` for Flipkart and Casio requests to bypass cloud anti-bot filters.
- **SQL / API Hygiene**: Database mutations in `supabase_db.py` use PostgREST parameterized endpoints; no raw string interpolation in SQL.
- **Credentials Isolation**: Zero session cookies or passwords in version control. `flipkart_session_cookies.json` and `.env` are strictly `.gitignore`d.

---

## 🚆 RailRadar Commute Intelligence Architecture & Operating Memory

> **Autonomous Transit System for Sriram's Hosur &harr; ETV Bangalore Daily Commute**  
> **Shift:** 12:00 PM &ndash; 08:30 PM+ | **Office:** JPMorgan Chase, Parcel 5 (Back Gate), Embassy Tech Village (ETV)  
> **Home:** Gangaiya Venkatachalapathy St, Nehru Nagar Ext, Hosur (180m from Railway Station PF1)  
> **Telegram Bot:** `@SriTrainBot` (Token: Configured via `TRAIN_BOT_TOKEN` in `.env` / Secrets | Chat: `716060462`)  
> **Cloud Daemon:** Oracle Cloud VM (`140.245.250.104` &middot; `railradar.service`)  
> **Web & API:** `https://sritrack.vercel.app/` (Tab: `/rail-radar` &middot; API: `/api/rail/*`)

### 1. Commuter Persona & Geography Rules
- **Work Shift Start:** **12:00 PM**.
- **Desk Location:** JPMorgan Chase, Parcel 5, Embassy Tech Village (ETV), Outer Ring Road, Bangalore. Entrance strictly through **ETV Back Gate**.
- **Home Location:** Gangaiya Venkatachalapathy St, Nehru Nagar Ext, Hosur (directly opposite Hosur Station Platform 1).
  - Walk distance: **180 meters** (3–5 mins).
  - Doorstep Lead Time in RailRadar: **10 minutes** (5m walk + 5m buffer for FOB/platform entry).
- **Morning Station & Walk:**
  - De-board Station: **Bellandur Road (`BLRR`)**.
  - Morning Walk: **2.2 km** (exactly 30 mins) via Level Crossing &rarr; Panathur Main Road &rarr; GEAR Innovative School Road &rarr; ETV Back Gate.
  - Reason for BLRR: Avoids Carmelaram highway auto congestion and auto fare gouging; scenic walking route directly into Parcel 5 back gate.
- **Evening Station & Rapido Bike Taxi:**
  - Origin: ETV Back Gate.
  - Transit Mode: **Rapido Bike Taxi**.
  - Destinations:
    - **Bellandur Road (`BLRR`):** 2.5 km bike ride (8–12 mins, ~₹35). Recommended for MEMU 66585 and 06277.
    - **Carmelaram (`CRLM`):** 4.8 km bike ride (15–20 mins, ~₹60). Recommended for Express 16211 and night expresses (12677, 11013).

### 2. Algorithmic Decision Engine: Max-Sleep Utility Optimization
- **Shift Cutoff:** Desk arrival $\le$ 11:30 AM (30-minute safety buffer ahead of 12:00 PM shift).
- **Objective Function:** Among all viable morning trains reaching desk before 11:30 AM, **select the train that departs Hosur latest** ($\arg\max_{t} T_{\text{dep}}(t)$).
- **Primary Recommendation:** **Train 16212 (Salem &rarr; Yesvantpur Intercity Express)**:
  - Scheduled: 08:20 AM. Historical mean delay: +34.1 mins.
  - Departs Hosur: ~08:54 AM.
  - Arrives BLRR: ~09:54 AM.
  - Arrives ETV Desk: **~10:24 AM** (via 30-min walk).
  - **Net Gain:** **+45.4 extra minutes of sleep and home time every single morning** compared to old MEMU-only policy!
  - **Safety Margin:** 96 minutes ahead of 12:00 PM shift start.
- **Backup Hierarchy:**
  1. **Train 66596 (Hosur &rarr; Yesvantpur MEMU):** Departs Hosur ~08:26 AM, Desk ~09:38 AM. Guarded by incoming rake 66595 (if 66595 is cancelled, 66596 is automatically bypassed).
  2. **Train 06278 (Dharmapuri &rarr; SBC MEMU):** Departs Hosur ~07:07 AM, Desk ~08:21 AM. Ultra-early fallback for line blocks.

### 3. Data Science & Probability Validation (10,000-Day Monte Carlo)
- **Empirical Delay Metrics (N=70):**
  - Train 16212: Mean 34.1m &plusmn; 8.8m | P10: 24m | P50 (Median): 34m | P90: 45m | Max: 55m.
  - Train 66596: Mean 1.4m &plusmn; 1.7m | P50: 1m | P90: 6m.
- **Monte Carlo Results across 10,000 Commute Days (with +50m tail shocks):**
  - Modal Train Selection: 16212 (88.4%), 66596 (11.6%).
  - Desk ETA Quantiles: P50 = 10:24 AM | P90 = 10:39 AM | P99 = 11:05 AM.
  - **Absolute Worst Case (P100):** **11:25 AM** (still 35 mins before 12:00 PM shift!).
  - **On-Time Probability (&le; 12:00 PM):** **100.00%**.

### 4. 7-State Autonomous Commute Daemon (`rail_daemon.py`)
- **Strict Bot Isolation:** Dedicated token loaded via `TRAIN_BOT_TOKEN` or `RAIL_TELEGRAM_BOT_TOKEN`. NEVER share or mix with PriceTracker.
- **Zero-Polling Supabase Write Guarantee:** State transitions only ($\le 7$ rows/day). Zero polling writes.
- **State Machine Lifecycle:**
  1. `NIGHT_SLEEP` (22:30 – 06:45)
  2. `MORNING_PROMPT` (06:45 AM corridor scan & recommendation)
  3. `MORNING_TRACKING` (Adaptive polling: 30s critical window)
  4. `MIDDAY_STANDBY` (10:00 – 14:00 PM)
  5. `EVENING_PROMPT` (14:00 PM interactive check-in)
  6. `EVENING_TRACKING` (Milestone monitoring & Rapido advisories)
  7. `HIBERNATION` (Paused until 06:45 AM next morning)
- **The `/reached` Command:** Sending `/reached` or simply typing `reached` immediately pauses tracking for the day and puts the daemon to sleep.
- **Workday Overrides:**
  - `/wfh`: Marks today as Work From Home; suspends tracking.
  - `/bike`: Marks today as Bike Commute; suspends train alerts.
  - `/reset`: Clears daily tracking state back to default.

### 5. Production Infrastructure Runbook
- **Oracle VM:**
  - Service: `sudo systemctl status railradar`
  - Restart: `sudo systemctl restart railradar`
  - Logs: `journalctl -u railradar -f`
- **Vercel Web App:**
  - URL: `https://sritrack.vercel.app/`
  - Rail Dashboard: `/rail-radar`
  - Status API: `/api/rail/status`


