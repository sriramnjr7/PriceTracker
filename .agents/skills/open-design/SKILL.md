---
name: open-design
description: Complete AI Design Agent architecture and craft methodology adapted from nexu-io/open-design. Translates briefs into production-grade, brand-aligned interfaces across 4 planes: Design Systems (151 styles including trading-terminal, linear-app, raycast, bento), Universal Craft Rules (typography, color balance, 120-180ms motion discipline, state coverage, anti-slop), Archetype Blueprints (telemetry dashboards, ticker tapes, order books, KPI walls), and Component Tokens.
triggers:
  - open-design
  - od
  - design-system
  - revamp ui
  - craft review
  - design tokens
  - trading-terminal
  - linear-design
metadata:
  author: nexu-io
  version: "1.0.0"
---

# OpenDesign: Collaborative AI Design Agent Architecture

OpenDesign is an open, brand-grade UI architecture that transforms design briefs into production-ready web interfaces, interactive dashboards, and design systems.

---

## 🏛️ The 4-Axis Architecture

OpenDesign operates across four decoupled planes:

```
┌────────────────────────────────────────────────────────┐
│                   1. DESIGN SYSTEMS                     │
│ Brand contracts, tokens, surfaces, typography scales   │
│ (trading-terminal, linear-app, raycast, bento, apple)  │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│                  2. UNIVERSAL CRAFT                    │
│ Absolute rules true across ALL brands: letter-spacing, │
│ 60-30-10 color balance, 120-180ms motion, state matrix │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│                 3. ARCHEYPE TEMPLATES                  │
│ Structural blueprints: Dashboards, Tickers, KPI Bento, │
│ Order Books, Telemetry Streams, Settings & Modals      │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│                 4. AGENT EXECUTION                     │
│ Code synthesis, DOM ID preservation, automated audits  │
└────────────────────────────────────────────────────────┘
```

---

## 🛠️ The 5-Step Execution Workflow

Whenever revamping an existing UI or designing a new screen with `/open-design`:

### Step 1: Select the Design System Archetype
Match the product's core utility to one of OpenDesign's proven design families:

| Design Family | Core Vibe | Best Use Case | Key Tokens |
| :--- | :--- | :--- | :--- |
| **`trading-terminal`** | High-density, financial precision, monospace data, cyan/coral signals | Price tracking, stock radar, live telemetry, crypto/crypto desks | Surface `#090a0f` / `#12151c`, Accent `#00D4AA`, Loss `#ff4d4d` |
| **`linear-app`** | Achromatic moonlight, Inter `cv01/ss03`, single indigo accent, hairline borders | Issue trackers, project management, developer tools | Canvas `#08090a`, Borders `rgba(255,255,255,0.06)`, Accent `#5e6ad2` |
| **`raycast`** | Ultra-snappy launcher, graphite ramps, pill badges, keyboard-first | Command palettes, quick-action utilities, launcher docks | Surface `#141416`, Accents `#ff6363` & `#38bdf8`, Shortcuts pills |
| **`bento`** | Modular information cards, variable aspect ratios, clean visual hierarchy | SaaS overviews, product analytics, executive summary walls | Surface `#161922`, Gap `12px-16px`, Hairline radius `12px` |

### Step 2: Ingest Universal Craft Rules
Enforce the universal standards defined in [references/craft-knowledge.md](references/craft-knowledge.md):
1. **Typography**:
   - ALL CAPS text MUST have `letter-spacing: ≥ 0.05em` (never tight).
   - Monospace tabular figures (`font-variant-numeric: tabular-nums`) for all prices, percentages, timers, and telemetry.
   - Max 3 font weights per view (e.g. 400 regular, 500/600 medium/semibold, 700 bold).
2. **Color Balance (60-30-10 Rule)**:
   - 60% Dominant Canvas / Surface (neutral dark graphite: `#090a0f` to `#141824`).
   - 30% Structural Chrome (borders `rgba(255,255,255,0.08)`, cards, sidebars, muted labels).
   - 10% High-Intent Accents (action buttons, live status dots, price drop pills).
   - Zero gratuitous glows, neon text-shadows, or floating decorative blobs.
3. **Motion Discipline**:
   - UI transitions MUST execute in 120ms to 180ms with `cubic-bezier(0.16, 1, 0.3, 1)`.
   - Never use slow linear transitions (>300ms) or perpetual pulsing elements that distract focus.
4. **State Coverage**:
   - Every interactive component must handle: `default`, `hover`, `active/focus`, `loading`, `empty`, and `error`.

### Step 3: Map Token Architecture
Define a strict CSS token foundation:
```css
:root {
  /* Surfaces */
  --od-bg-canvas: #090a0f;
  --od-bg-surface: #12151c;
  --od-bg-elevated: #181c26;
  --od-bg-hover: #1e2330;
  
  /* Borders */
  --od-border-subtle: rgba(255, 255, 255, 0.07);
  --od-border-medium: rgba(255, 255, 255, 0.12);
  --od-border-focus: var(--od-accent-primary);
  
  /* Typography */
  --od-font-sans: 'Inter', -apple-system, sans-serif;
  --od-font-mono: 'JetBrains Mono', monospace;
  
  /* Accents */
  --od-accent-primary: #00D4AA;       /* High-precision Mint */
  --od-accent-cyan: #38bdf8;          /* Signal Sky */
  --od-accent-amber: #f59e0b;         /* Standby Warning */
  --od-accent-coral: #ff4d4d;         /* Loss / Price Floor */
  --od-accent-indigo: #6366f1;        /* Secondary Action */
}
```

### Step 4: Synthesize Archetype Components
Compose functional modules using patterns from [references/archetypes.md](references/archetypes.md):
- **Live Ticker / Telemetry Tape**: Streaming real-time updates and probe telemetry.
- **Bento KPI Bar**: High-density 4-metric grid with monospace figures and semantic indicators.
- **Trading-Desk Product Cards**: Dual-price comparison (Current vs Floor), target distance progress bar, inline action buttons.
- **Order-Book Deal Stream**: Compact, timestamped deal feed with percentage drop badges.

### Step 5: Verification & Craft Audit
Before shipping, audit against the OpenDesign checklist:
- [ ] No unstyled states (`empty-state`, `loading`, `error` all covered).
- [ ] Tabular numbers used for all financial/metric data.
- [ ] Contrast ratio ≥ 4.5:1 for body copy and ≥ 3:1 for large display.
- [ ] All JavaScript DOM element IDs and event handlers preserved.
- [ ] Responsive down to 360px mobile viewports.

---

## 📚 Reference Library

- [Craft Knowledge](references/craft-knowledge.md) — Universal rules for typography, color, motion, and UX laws.
- [Design Systems](references/design-systems.md) — Detailed specifications for Trading Terminal, Linear, Raycast, and Bento.
- [Archetypes & Patterns](references/archetypes.md) — Production layout blueprints for dashboards, tickers, and cards.
