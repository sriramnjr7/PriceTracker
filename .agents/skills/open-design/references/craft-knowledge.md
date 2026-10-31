# Universal Craft Knowledge (OpenDesign)

Brand-agnostic rules true regardless of framework or theme.

---

## 1. Typography & Hierarchy

### Tracking (Letter Spacing) Rules
- **ALL CAPS**: Always apply `letter-spacing: 0.05em` to `0.08em`. Uppercase without tracking looks compressed and unpolished.
- **Display Headlines (≥ 24px)**: Apply negative tracking (`-0.02em` to `-0.03em`) for tight, authoritative hierarchy.
- **Monospace Numbers**: Always specify `font-variant-numeric: tabular-nums` or `font-feature-settings: "tnum"` so numbers align vertically without jitter.

### Weight Discipline
- Never use more than 3 weights per view (Standard: 400 Regular for body, 500/600 Medium/Semibold for labels and headings, 700 Bold for key metrics).
- Differentiate information hierarchy using **font size, opacity, and uppercase labels** rather than multiplying font weights.

---

## 2. Color Balance (The 60-30-10 Rule)

- **60% Background Surface**: Achromatic dark canvas (`#08090a` to `#12151c`).
- **30% Structural Form**: Card surfaces, sidebars, hairline borders (`rgba(255,255,255,0.06)` to `0.10`), muted labels.
- **10% Intentional Accent**: Semantic color signals (`#00D4AA` mint, `#38bdf8` cyan, `#ff4d4d` coral, `#f59e0b` amber).
- **No Color Chaos**: Colors must mean something. Mint = positive / price drop / active; Coral = out of stock / floor reached; Amber = standby / checking.

---

## 3. Animation & Motion Discipline

- **Duration**: 120ms to 180ms for micro-interactions (hover, active, toggle).
- **Easing**: `cubic-bezier(0.16, 1, 0.3, 1)` (snappy ease-out, never linear).
- **Reduced Motion**: Always respect `prefers-reduced-motion: reduce`.
- **Zero Distraction**: No continuous pulsing glow or blinking animations unless signaling a high-priority, real-time alert.

---

## 4. State Coverage Matrix

Every UI component must ship with all 6 states implemented:

| State | Visual Treatment |
| :--- | :--- |
| **Default** | Resting state, hairline border, muted background |
| **Hover** | 1 step lighter surface (`rgba(255,255,255,0.04)`), cursor pointer, subtle border shift |
| **Focus/Active** | Crisp 1.5px outline with 2px offset or accent border ring |
| **Loading** | Clean skeleton placeholder or discrete 6px spinning indicator |
| **Empty** | Helpful illustration or icon, concise title, and 1-click CTA |
| **Error** | Muted coral border/pill, clear actionable recovery description |

---

## 5. Cognitive Laws of UX for Dashboards

1. **Miller’s Law (Chunking)**: Group metrics into 4–5 related units rather than an endless sea of numbers.
2. **Hick's Law (Decision Time)**: Keep action options minimal (e.g. 1 primary button, 1 secondary action).
3. **Fitts’s Law (Target Size)**: Interactive targets must be at least 32px × 32px with adequate padding for desktop and 44px on mobile.
4. **Pareto Principle**: 80% of user attention is on the top 20% of data—ensure current price, target floor, and live status are front and center.
