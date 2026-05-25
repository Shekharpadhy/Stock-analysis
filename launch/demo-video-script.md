# Demo Video Script

**Length**: 90 seconds (the proven sweet spot — long enough to show value, short enough to not lose attention).
**Format**: Screen recording with voice-over. No face cam needed.
**Resolution**: 1920×1080, 30fps. Export as MP4 (H.264) for everywhere except the README — there, render a separate WebP or GIF (max 5MB).
**Tool**: [OBS Studio](https://obsproject.com/) (free, cross-platform) or [Kap](https://getkap.co/) on Mac.

---

## Pre-recording setup

1. **Seed data**: Run these tickers through `/analyze` so they're already in the DB and BCSI scores render instantly:
   - `AAPL` (strong, for the hero shot)
   - `NVDA` (strong but with valuation concerns — good for the dimensions story)
   - `BBBY` (or any defunct/distressed ticker — for the SHAP shot)
   - `JPM`, `BAC`, `WFC` (for the portfolio shot)
2. **Browser**: Chrome, 1440×900 window, zoom at 110% so text reads on small mobile playback. Hide bookmarks bar.
3. **Audio**: Quiet room, basic USB mic (Blue Yeti is overkill — even your phone in front of you works). Bring water.
4. **Cursor**: Smooth, deliberate movements. No fast wiggles. Pause briefly on every button before clicking.

---

## Timecoded script

> **[00:00 – 00:05] HOOK**
> **Visual**: BCSI hero showing NVDA at 78.4 / Strong, all five dimension bars rendered.
> **Voice-over**:
> *"This is one company score. Five dimensions. Real explanations. And it took five minutes to install."*

> **[00:05 – 00:15] PROBLEM**
> **Visual**: Pan slowly across the BCSI hero, highlight each dimension label.
> **Voice-over**:
> *"Every analyst, every PM, every credit officer ends up building the same dashboard. Pull fundamentals. Compute a risk score. Watch for red flags. The tools that exist each do one slice — backtesting libraries, technical charts, ML notebooks — and none of them give you a single, honest, explainable answer to 'how is this company doing.'"*

> **[00:15 – 00:25] SOLUTION INTRO**
> **Visual**: Cut to a clean dashboard view — sector table with multiple companies. Hover BCSI column to show the colour-coded scores.
> **Voice-over**:
> *"BCSI is open source. Self-hosted. Costs a Hetzner VPS to run. And gives you that single number — composed from risk, quality, valuation, momentum, and governance. Each dimension is its own engine, fully auditable in the codebase."*

> **[00:25 – 00:45] DEMO — analyse a ticker**
> **Visual** (this is the sequence):
> 1. Type `NVDA` in the search box (slow, deliberate keys).
> 2. Click **Analyze**.
> 3. Loading spinner for ~2 sec.
> 4. BCSI hero updates. Pause on the score.
> 5. Click to expand the **Risk Analysis** accordion.
> 6. Pause on the risk flags + Altman / Beneish breakdown.
> 7. Collapse, expand **Quality Analysis** — show Piotroski score.
> **Voice-over**:
> *"Type a ticker, hit Analyze. The platform pulls fundamentals from yfinance, runs the Altman Z-score, the Beneish M-score, the Piotroski F-score, a DCF, a PE comp, a momentum blend including news sentiment, and rolls them into the composite. Every dimension is one click away — and shows you the raw inputs, not just the verdict."*

> **[00:45 – 01:00] DEMO — ML + SHAP**
> **Visual**: Switch to the ML distress prediction view. Show the probability (e.g., 12%) and the top-5 SHAP drivers table.
> **Voice-over**:
> *"For credit decisions you need more than a score — you need to know **why**. The ML engine is an XGBoost classifier with per-prediction SHAP attributions, so every prediction tells you exactly which features moved the needle for **this** company."*

> **[01:00 – 01:15] DEMO — real-time + alerts**
> **Visual**:
> 1. Pan to the live price indicator in the header — show the green pulsing dot.
> 2. Cut to the **My Alerts** panel — show 2-3 active subscriptions.
> 3. Briefly show the **My Portfolio** view with sector exposure bars.
> **Voice-over**:
> *"WebSocket price feed in the header — no F5 needed. Per-user watchlists with email and Slack alerts when a company crosses your risk threshold. Aggregate any watchlist into a portfolio view with sector exposure."*

> **[01:15 – 01:25] PROOF**
> **Visual**: Cut to terminal showing `pytest` output: `443 passed, 80% coverage`.
> **Voice-over**:
> *"Four hundred forty-three tests. Eighty percent coverage. Audit log, JWT rotation, leader-elected scheduler, request-ID correlation — this is production-grade, not toy-grade. The DEPLOYMENT, SECURITY, and PRIVACY docs are in the repo."*

> **[01:25 – 01:30] CTA**
> **Visual**: GitHub repo URL on screen, large and centred. `github.com/<your-handle>/bcsi`.
> **Voice-over**:
> *"MIT licensed. Five minutes from clone to running. Link's below — star it if it'd save your team time."*

---

## Editing notes

- **Cuts**: Hard cuts between sections — no fancy transitions, they look amateur on this kind of demo.
- **Music**: Optional. If you add anything, [Uppbeat](https://uppbeat.io/) has free royalty-free options. Keep it low (-20 dB below voice).
- **Captions**: Burn in subtitles. ~30% of viewers will watch muted on mobile. [Submagic](https://www.submagic.co/) or YouTube's auto-caption with manual fixes both work.
- **Thumbnail**: Single still — the BCSI hero on NVDA with the score visible. Big, no extra text.

---

## Where this video goes

| Channel | Format | Notes |
|---|---|---|
| README | Embedded GIF | Render frames 00:25–01:00 as a 30s loop, max 5MB |
| YouTube | Full 90s MP4 | Public, unlisted not enough — Show HN won't index it |
| Twitter/X | First 2:20 of MP4 inline | Native upload outperforms YouTube links 5:1 |
| LinkedIn | Same MP4 | Native upload |
| Show HN | Link in body | YouTube link works fine here |
| Demo site | Embedded `<video>` | Above the fold |

One recording, six channels.
