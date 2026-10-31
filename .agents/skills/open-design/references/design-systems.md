# OpenDesign Design Systems

Detailed token specifications for the four primary dark-theme design systems in the OpenDesign catalog.

---

## 1. Trading Terminal (`trading-terminal`)

**Visual Vibe**: Financial market command center, Bloomberg Terminal meets modern web. Dark surfaces, tabular figures, high-contrast cyan/coral signals, readable at high glance velocity.

```css
:root {
  --tt-bg: #090a0f;
  --tt-surface: #12151c;
  --tt-surface-hover: #181c26;
  --tt-border: rgba(255, 255, 255, 0.08);
  --tt-border-strong: rgba(255, 255, 255, 0.16);

  /* Semantic Signals */
  --tt-gain: #00D4AA;        /* Buy / Drop Alert / In Stock */
  --tt-loss: #FF4757;        /* Out of Stock / Floor Missed */
  --tt-warning: #FFB800;     /* Standby / High Volatility */
  --tt-neutral: #82828e;     /* Secondary Metric */

  /* Typography */
  --tt-font-display: 'JetBrains Mono', monospace;
  --tt-font-sans: 'Inter', -apple-system, sans-serif;
  --tt-font-mono: 'JetBrains Mono', monospace;
}
```

---

## 2. Linear App (`linear-app`)

**Visual Vibe**: Achromatic moonlight, precision engineering, subtle luminescence, single signature indigo accent.

```css
:root {
  --ln-bg: #08090a;
  --ln-surface: #0f1011;
  --ln-elevated: #191a1b;
  --ln-hover: #222326;
  --ln-border: rgba(255, 255, 255, 0.06);

  /* Single Signature Accent */
  --ln-accent: #5e6ad2;
  --ln-accent-bright: #7170ff;
  --ln-accent-hover: #828fff;
  --ln-accent-subtle: rgba(94, 106, 210, 0.12);

  /* Text Roles */
  --ln-text-primary: #f7f8f8;
  --ln-text-secondary: #d0d6e0;
  --ln-text-muted: #8a8f98;
}
```

---

## 3. Raycast (`raycast`)

**Visual Vibe**: Snappy launcher, command palette, keyboard-first shortcut badges, graphite pill filters.

```css
:root {
  --rc-bg: #0e0e10;
  --rc-surface: #16161a;
  --rc-surface-hover: #1e1e24;
  --rc-border: rgba(255, 255, 255, 0.07);
  --rc-badge-bg: rgba(255, 255, 255, 0.05);
  --rc-badge-border: rgba(255, 255, 255, 0.10);
  --rc-accent-red: #ff6363;
  --rc-accent-blue: #38bdf8;
}
```

---

## 4. Bento Grid (`bento`)

**Visual Vibe**: Modular cards with varying widths (1 col, 2 col, 3 col), hairline 12px rounded borders, integrated sparklines, and metric cards.

```css
:root {
  --bento-bg: #0b0d13;
  --bento-card: #131722;
  --bento-card-hover: #191e2c;
  --bento-border: rgba(255, 255, 255, 0.08);
  --bento-radius: 12px;
  --bento-gap: 14px;
}
```
