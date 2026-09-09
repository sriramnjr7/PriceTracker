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

-- Indexes for lightning fast lookups
CREATE INDEX IF NOT EXISTS idx_products_active ON products(is_active);
CREATE INDEX IF NOT EXISTS idx_products_url ON products(url);
CREATE INDEX IF NOT EXISTS idx_price_logs_product ON price_logs(product_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_deal_alerts_url ON deal_alerts_log(product_url, notified_at DESC);

-- Enable Row Level Security (RLS) but allow service role / anon access with apikey
ALTER TABLE products ENABLE ROW LEVEL SECURITY;
ALTER TABLE price_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE deal_alerts_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE custom_radar_rules ENABLE ROW LEVEL SECURITY;

-- Permissive policies for API operations
CREATE POLICY "Allow public read/write on products" ON products FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow public read/write on price_logs" ON price_logs FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow public read/write on deal_alerts_log" ON deal_alerts_log FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow public read/write on custom_radar_rules" ON custom_radar_rules FOR ALL USING (true) WITH CHECK (true);

-- Seed Initial Casio Bhawar Tracker rows
INSERT INTO products (url, platform, title, initial_price, current_price, target_price, is_active)
VALUES 
    ('https://casiostore.bhawar.com/products/casio-g-shock-gbd-300-7dr-watch', 'casio', 'GBD-300-7', 12995.0, 12995.0, 4000.0, true),
    ('https://casiostore.bhawar.com/collections/g-shock', 'casio', '[Collection: g-shock]', 8186.5, 8186.5, NULL, true),
    ('https://casiostore.bhawar.com/collections/edifice-watches', 'casio', '[Collection: edifice-watches]', 5397.0, 5397.0, NULL, true),
    ('https://casiostore.bhawar.com/collections/casio-vintage', 'casio', '[Collection: casio-vintage]', 1747.5, 1747.5, NULL, true)
ON CONFLICT (url) DO NOTHING;
