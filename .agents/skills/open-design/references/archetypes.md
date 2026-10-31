# OpenDesign Archetypes & Layout Blueprints

Structural layout patterns for high-performance dashboards, real-time monitors, and financial trackers.

---

## 1. The Real-Time Radar / Marquee Ticker

A dense, high-utility status marquee that surfaces recent sweeps, target alerts, and engine telemetry without hogging screen real estate.

```html
<div class="radar-ticker-strip">
  <div class="ticker-label">
    <span class="ticker-pulse-dot"></span>
    <span>RADAR TAPE</span>
  </div>
  <div class="ticker-content">
    <span class="ticker-item"><span class="tag-casio">CASIO</span> GBD-300-9DR: 404 RESTOCK RADAR ACTIVE [60S]</span>
    <span class="ticker-sep">•</span>
    <span class="ticker-item"><span class="tag-fkrt">FLIPKART</span> BUYBOX ISOLATED (RETAILNET ONLY)</span>
    <span class="ticker-sep">•</span>
    <span class="ticker-item"><span class="tag-drop">FLASH DROP</span> NIKE VOMERO 17: ₹7,899 (-42%)</span>
  </div>
</div>
```

---

## 2. Bento Telemetry KPI Grid

A 4-column compact grid designed to present the vital signs of the application at a single glance.

```html
<section class="telemetry-bento-grid">
  <div class="bento-kpi-card">
    <div class="bento-kpi-top">
      <span class="bento-kpi-label">Active Targets</span>
      <span class="bento-kpi-icon">🎯</span>
    </div>
    <div class="bento-kpi-val" id="kpi-active-count">0</div>
    <div class="bento-kpi-sub">Amazon · Flipkart · Casio</div>
  </div>
  <!-- Additional cards for Verified Drops, BuyBox Integrity, Engine Health -->
</section>
```

---

## 3. Trading-Desk Product Card Pattern

Dual-price comparison (Current vs Alert Floor), target distance progress bar, and instant action toolbar.

```html
<div class="terminal-product-card">
  <div class="card-header">
    <span class="store-badge store-casio">Casio India</span>
    <span class="status-indicator live">Tracking</span>
  </div>
  <h3 class="product-title">Casio G-Shock GBD-300-9DR</h3>
  <div class="price-matrix">
    <div class="price-cell">
      <span class="cell-label">Current</span>
      <span class="cell-val">₹9,995</span>
    </div>
    <div class="price-cell text-right">
      <span class="cell-label">Target Floor</span>
      <span class="cell-val font-mono">₹7,995</span>
    </div>
  </div>
  <div class="target-progress-bar">
    <div class="progress-fill" style="width: 75%;"></div>
  </div>
  <div class="card-footer">
    <span class="timestamp">Checked 2m ago</span>
    <div class="action-btn-group">
      <!-- Icon buttons for check now, chart, edit target, pause -->
    </div>
  </div>
</div>
```

---

## 4. Order-Book Style Deals Feed

A compact, streaming transaction feed showing real-time verified price drops.

```html
<div class="order-book-feed">
  <div class="deal-row">
    <div class="deal-info">
      <span class="deal-store-tag">FKRT</span>
      <span class="deal-name">Saucony Triumph 21</span>
    </div>
    <div class="deal-metrics">
      <span class="deal-discount-badge">-70%</span>
      <span class="deal-price">₹5,999</span>
    </div>
  </div>
</div>
```
