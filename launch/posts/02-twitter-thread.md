# Twitter / X launch thread

**When**: ~3 hours into the Show HN run if it's climbing, OR independently at 9 AM US Eastern if HN didn't catch.
**Format**: 8-tweet thread. First tweet is the hook + embedded video. Each subsequent tweet stays under 280 chars (true Twitter, not X-blue 4000-char).
**Media**: Native upload the demo video on tweet 1. Native uploads outperform YouTube links 5:1 in Twitter's algorithm.
**Pin**: Pin the first tweet of the thread to your profile for the launch week.

---

## Tweet 1 (the hook)

```
I open-sourced an analyst dashboard that gives any public company a single
0-100 risk score — with per-feature SHAP explanations and a real-time UI.

Think Bloomberg-lite, self-hosted, $0/seat. 5 minutes from clone to running.

90 sec demo 👇
```

**Attach**: The demo video (native MP4 upload, max 2:20 on Twitter).

**Why it works**:
- Lead with the concrete value, not the project name.
- "Bloomberg-lite, self-hosted, $0/seat" is the snappy comparison that does all the heavy lifting.
- "90 sec demo" sets expectation — they know what they're committing to.
- No hashtags on the first tweet (Twitter under-distributes them).

---

## Tweet 2 (the problem)

```
Every quant tool does ONE thing well.

backtrader: backtests.
vectorbt: vectorised analysis.
qlib: ML research.

None of them answer the question a credit officer actually asks:

"How is this company doing RIGHT NOW?"
```

---

## Tweet 3 (the answer)

```
BCSI computes ONE score from FIVE dimensions:

▸ Risk      — Altman + Beneish + ICR ensemble
▸ Quality   — Piotroski / Graham / Magic Formula
▸ Valuation — DCF + PE + PEG + analyst
▸ Momentum  — price + volume + analyst + news sentiment
▸ Governance — promoter pledge, SEBI, auditor

Renormalises around what data is actually available.
```

---

## Tweet 4 (the differentiator)

```
For credit decisions you need to know WHY.

Every distress probability comes with the top 5 SHAP features that drove it
— so the model is auditable, not a black box.

The "explainability" line on every fintech pitch deck, except actually
implemented.
```

**Attach** (optional): Screenshot of the SHAP drivers table from the dashboard. High contrast, the numbers visible.

---

## Tweet 5 (production-grade signal)

```
Things I built because "actually running this in front of users" is the
goal, not "tutorial completed":

▸ 443 tests, 80% coverage
▸ argon2id passwords + JWT rotation
▸ leader-elected scheduler (safe multi-worker)
▸ audit log, request-ID correlation
▸ Prometheus /metrics

It's not a notebook.
```

---

## Tweet 6 (proof of polish)

```
The fastest way to dismiss an open-source fintech project is
"unmaintained side project."

This one ships with:
▸ a real test suite gated in CI
▸ a multi-step DEPLOYMENT.md
▸ a PRIVACY.md for data-subject requests
▸ a SECURITY.md disclosure policy

Production-shaped from day one.
```

**Why**: Pre-empts the "looks abandoned" critique with concrete artifacts.

---

## Tweet 7 (the offer)

```
MIT licensed. Self-hosted. Runs on a $7/mo VPS.

git clone → docker compose up → http://localhost:8000

No API keys. No SaaS upsell. No 14-day trial timer.

Read the code, fork it, run it for your team.
```

---

## Tweet 8 (the CTA)

```
Repo: github.com/Shekharpadhy/Stock-analysis
Show HN: <HN_LINK>
Demo: <DEMO_URL>

⭐ if this would save your team time.
🐛 file issues — I read every one.
🔁 RT to share with the analyst on your timeline who still F5's a spreadsheet.
```

---

## After publishing

**Hour 0–2**:
- Reply to every quote-tweet and reply within 30 min.
- Engage with anyone who stars the repo and tweets about it.
- If a verified account RTs: reply with a thanks + ONE additional concrete detail (NOT just emoji).

**Hour 2–24**:
- DM the 5–10 specific people you know would actually use this. Personal note > broadcast.
- Search for "open source bloomberg" / "fintech dashboard" / "credit risk python" in Twitter search — reply to recent posts with a relevant one-liner + link. Be useful, not spammy. Cap at ~10 replies.

**Day 2–7**:
- Daily: post ONE follow-up tweet from the calendar (see `30-day-calendar.md`).
- DON'T re-RT your own launch thread. Reach diminishes; engagement halves.

---

## What to do if it flops

If the thread gets <100 impressions in the first 2 hours, the algorithm capped it. Three options:

1. **Pivot the angle**: rewrite Tweet 1 leading with a SPECIFIC thing (e.g., "I open-sourced the SHAP-explainability layer credit teams actually want") and post a NEW thread 3 days later. Don't delete the old one.
2. **Move budget to Reddit**: r/algotrading + r/Python are independent of Twitter's algorithm.
3. **Wait for the blog post (`why-quant-tools-compute-the-same-score-badly.md`)**: the long-form content sustains traffic that the thread doesn't.

Don't grind on Twitter if it didn't catch on day 1. Sunk-cost trap.
