-- =============================================================================
-- Supabase Schema for PriceTracker
-- Run this script in the Supabase SQL Editor (https://supabase.com/dashboard)
-- =============================================================================

-- 1. Tracked Products Table
CREATE TABLE IF NOT EXISTS products (
    id                     BIGSERIAL PRIMARY KEY,
    url                    TEXT UNIQUE NOT NULL,
    platform               TEXT NOT NULL,
    title                  TEXT,
    initial_price          NUMERIC,
    current_price          NUMERIC,
    target_price           NUMERIC,
    percentage_drop_target NUMERIC,
    last_checked           TIMESTAMPTZ,
    is_active              BOOLEAN NOT NULL DEFAULT TRUE,
    last_notified_price    NUMERIC,
    created_at             TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Price History Logs Table
CREATE TABLE IF NOT EXISTS price_logs (
    id         BIGSERIAL PRIMARY KEY,
    product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    price      NUMERIC NOT NULL,
    timestamp  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3. Deal & Pricing Glitch Alerts Log
CREATE TABLE IF NOT EXISTS deal_alerts_log (
    id               BIGSERIAL PRIMARY KEY,
    product_url      TEXT NOT NULL,
    title            TEXT,
    price            NUMERIC,
    effective_price  NUMERIC,
    discount_percent NUMERIC,
    coupon_text      TEXT,
    platform         TEXT,
    notified_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 4. Custom Radar Rules Table
CREATE TABLE IF NOT EXISTS custom_radar_rules (
    id                 BIGSERIAL PRIMARY KEY,
    name               TEXT NOT NULL,
    category           TEXT,
    query              TEXT NOT NULL,
    platforms          TEXT,
    min_discount       NUMERIC DEFAULT 70.0,
    max_price          NUMERIC,
    min_mrp            NUMERIC,
    negative_keywords  TEXT,
    is_active          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for lightning fast lookups & Disk IO budget protection
CREATE INDEX IF NOT EXISTS idx_products_active ON products(is_active);
CREATE INDEX IF NOT EXISTS idx_products_url ON products(url);
CREATE INDEX IF NOT EXISTS idx_price_logs_product ON price_logs(product_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_price_logs_timestamp ON price_logs(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_deal_alerts_url ON deal_alerts_log(product_url, notified_at DESC);
CREATE INDEX IF NOT EXISTS idx_custom_radar_rules_name_id ON custom_radar_rules(name, id DESC);
CREATE INDEX IF NOT EXISTS idx_custom_radar_rules_name_created ON custom_radar_rules(name, created_at DESC);

-- Enable Row Level Security (RLS) but allow service role / anon access with apikey
ALTER TABLE products ENABLE ROW LEVEL SECURITY;
ALTER TABLE price_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE deal_alerts_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE custom_radar_rules ENABLE ROW LEVEL SECURITY;

-- Permissive policies for API operations (Idempotent: drops if already exists)
DROP POLICY IF EXISTS "Allow public read/write on products" ON products;
CREATE POLICY "Allow public read/write on products" ON products FOR ALL USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Allow public read/write on price_logs" ON price_logs;
CREATE POLICY "Allow public read/write on price_logs" ON price_logs FOR ALL USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Allow public read/write on deal_alerts_log" ON deal_alerts_log;
CREATE POLICY "Allow public read/write on deal_alerts_log" ON deal_alerts_log FOR ALL USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Allow public read/write on custom_radar_rules" ON custom_radar_rules;
CREATE POLICY "Allow public read/write on custom_radar_rules" ON custom_radar_rules FOR ALL USING (true) WITH CHECK (true);

-- Seed Initial Casio Bhawar Tracker rows
INSERT INTO products (url, platform, title, initial_price, current_price, target_price, is_active)
VALUES 
    ('https://casiostore.bhawar.com/products/casio-g-shock-gbd-300-7dr-watch', 'casio', 'GBD-300-7', 12995.0, 12995.0, 4000.0, true),
    ('https://casiostore.bhawar.com/collections/g-shock', 'casio', '[Collection: g-shock]', 8186.5, 8186.5, NULL, true),
    ('https://casiostore.bhawar.com/collections/edifice-watches', 'casio', '[Collection: edifice-watches]', 5397.0, 5397.0, NULL, true),
    ('https://casiostore.bhawar.com/collections/casio-vintage', 'casio', '[Collection: casio-vintage]', 1747.5, 1747.5, NULL, true)
ON CONFLICT (url) DO NOTHING;

-- =============================================================================
-- 5. RailRadar Commute Intelligence Tables
-- =============================================================================

-- Commute User & Route Configuration
CREATE TABLE IF NOT EXISTS commute_config (
    id                             BIGSERIAL PRIMARY KEY,
    user_name                      TEXT NOT NULL DEFAULT 'sriram',
    home_station                   TEXT NOT NULL DEFAULT 'HSRA',
    home_lead_minutes              INTEGER NOT NULL DEFAULT 10,
    work_destination               TEXT NOT NULL DEFAULT 'ETV_JPMC_PARCEL_5',
    office_login_target            TIME NOT NULL DEFAULT '11:00:00',
    default_morning_train          TEXT NOT NULL DEFAULT '66596',
    default_evening_train          TEXT NOT NULL DEFAULT '16232',
    preferred_dest_station_morning TEXT NOT NULL DEFAULT 'BLRR',
    preferred_dep_station_evening  TEXT NOT NULL DEFAULT 'CRLM',
    is_active                      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at                     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Daily Commute State (Zero-Polling State Machine Guarantee)
CREATE TABLE IF NOT EXISTS commute_daily_state (
    date                    DATE PRIMARY KEY,
    state                   TEXT NOT NULL DEFAULT 'NIGHT_SLEEP',
    morning_train           TEXT DEFAULT '66596',
    morning_step_out_time   TEXT DEFAULT '08:15',
    morning_revised_dep     TEXT DEFAULT '08:25',
    morning_delay_mins      INTEGER DEFAULT 0,
    morning_status          TEXT DEFAULT 'ACTIVE',
    evening_train           TEXT DEFAULT '16232',
    evening_milestone_fired BOOLEAN DEFAULT FALSE,
    evening_status          TEXT DEFAULT 'ACTIVE',
    notes                   TEXT,
    last_updated            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Historic Commute Rides & Performance
CREATE TABLE IF NOT EXISTS commute_history (
    id                          BIGSERIAL PRIMARY KEY,
    date                        DATE NOT NULL,
    direction                   TEXT NOT NULL, -- 'MORNING' or 'EVENING'
    train_no                    TEXT NOT NULL,
    origin_station              TEXT NOT NULL,
    dest_station                TEXT NOT NULL,
    scheduled_dep               TEXT,
    actual_dep                  TEXT,
    dep_delay_mins              INTEGER DEFAULT 0,
    scheduled_arr               TEXT,
    actual_arr                  TEXT,
    arr_delay_mins              INTEGER DEFAULT 0,
    mode                        TEXT DEFAULT 'TRAIN', -- 'TRAIN', 'BIKE', 'WFH', 'CAB'
    door_to_door_duration_mins  INTEGER,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 14-Day Empirical Train Delay & Punctuality Analytics
CREATE TABLE IF NOT EXISTS train_delay_analytics (
    train_no            TEXT NOT NULL,
    station_code        TEXT NOT NULL,
    train_name          TEXT,
    direction           TEXT, -- 'UP' (to SBC/YPR) or 'DOWN' (to HSRA/SA)
    sample_count        INTEGER DEFAULT 0,
    p10_delay_mins      NUMERIC DEFAULT 0,
    p50_delay_mins      NUMERIC DEFAULT 0,
    p90_delay_mins      NUMERIC DEFAULT 0,
    mean_delay_mins     NUMERIC DEFAULT 0,
    std_delay_mins      NUMERIC DEFAULT 0,
    on_time_percentage  NUMERIC DEFAULT 0,
    last_calculated     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (train_no, station_code)
);

-- Indexes for lightning fast lookups
CREATE INDEX IF NOT EXISTS idx_commute_history_date ON commute_history(date DESC);
CREATE INDEX IF NOT EXISTS idx_commute_history_train ON commute_history(train_no);
CREATE INDEX IF NOT EXISTS idx_train_delay_analytics_train ON train_delay_analytics(train_no);

-- Enable RLS
ALTER TABLE commute_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE commute_daily_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE commute_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE train_delay_analytics ENABLE ROW LEVEL SECURITY;

-- Permissive policies for Rail Commute operations (Idempotent: drops if already exists)
DROP POLICY IF EXISTS "Allow public read/write on commute_config" ON commute_config;
CREATE POLICY "Allow public read/write on commute_config" ON commute_config FOR ALL USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Allow public read/write on commute_daily_state" ON commute_daily_state;
CREATE POLICY "Allow public read/write on commute_daily_state" ON commute_daily_state FOR ALL USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Allow public read/write on commute_history" ON commute_history;
CREATE POLICY "Allow public read/write on commute_history" ON commute_history FOR ALL USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Allow public read/write on train_delay_analytics" ON train_delay_analytics;
CREATE POLICY "Allow public read/write on train_delay_analytics" ON train_delay_analytics FOR ALL USING (true) WITH CHECK (true);

-- Seed Commute Configuration for Sriram
INSERT INTO commute_config (user_name, home_station, home_lead_minutes, work_destination, office_login_target, default_morning_train, default_evening_train)
VALUES ('sriram', 'HSRA', 10, 'ETV_JPMC_PARCEL_5', '11:00:00', '66596', '16232')
ON CONFLICT DO NOTHING;

-- Seed Initial Analytics from 14-day history
INSERT INTO train_delay_analytics (train_no, station_code, train_name, direction, sample_count, p10_delay_mins, p50_delay_mins, p90_delay_mins, mean_delay_mins, std_delay_mins, on_time_percentage)
VALUES 
    ('06278', 'BLRR', 'Dharmapuri - KSR Bengaluru MEMU', 'UP', 7, 12.0, 38.0, 68.0, 41.2, 20.5, 14.3),
    ('06278', 'CRLM', 'Dharmapuri - KSR Bengaluru MEMU', 'UP', 7, 10.0, 35.0, 65.0, 38.0, 19.8, 14.3),
    ('66596', 'BLRR', 'Hosur - Yesvantpur MEMU', 'UP', 7, 4.0, 7.0, 11.8, 7.7, 4.8, 28.6),
    ('66596', 'CRLM', 'Hosur - Yesvantpur MEMU', 'UP', 7, 0.0, 0.0, 4.0, 1.4, 3.5, 85.7),
    ('16212', 'BLRR', 'Salem - Yesvantpur Express', 'UP', 7, 49.0, 62.0, 64.8, 59.1, 7.3, 0.0),
    ('66585', 'BLRR', 'Bangalore Cant - Hosur MEMU', 'DOWN', 7, 10.0, 15.0, 22.0, 15.4, 5.1, 14.3),
    ('16232', 'CRLM', 'Mailaduturai Express', 'DOWN', 7, 0.0, 0.0, 10.0, 2.1, 4.2, 85.7),
    ('66583', 'BLRR', 'Bangalore Cant - Hosur MEMU', 'DOWN', 8, 5.0, 12.0, 25.0, 13.8, 7.5, 25.0),
    ('16527', 'CRLM', 'Yesvantpur - Kannur Express', 'DOWN', 8, 2.0, 8.0, 18.0, 9.2, 6.1, 62.5),
    ('16236', 'CRLM', 'Tuticorin Express', 'DOWN', 8, 0.0, 5.0, 15.0, 6.0, 5.8, 75.0)
ON CONFLICT (train_no, station_code) DO NOTHING;
