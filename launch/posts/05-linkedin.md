# LinkedIn launch post

**When**: Day 1, between HN and Twitter. LinkedIn audience is offset from dev Twitter — finance / banking / risk professionals you're not reaching elsewhere.
**Time**: Tuesday-Thursday, 7:30 AM US Eastern. Pre-coffee, before-meeting window is highest-engagement on LinkedIn.
**Format**: Native post with the demo video uploaded directly (not a YouTube link — LinkedIn under-distributes external video links by 4–5×).
**Length**: 1,200–1,500 chars. LinkedIn truncates at ~210 chars in-feed — make those first two lines work.

---

## Post body

```
I spent 3 weeks building the credit-risk dashboard I always wished existed.

It's open source. Anyone in banking, asset management, or credit research
can run it for the cost of a VPS — about $7 a month.

Here's the problem it solves:

Every analyst, PM, and credit officer ends up with the same workflow.
Pull fundamentals from one tool. Compute a risk score in Excel. Watch
news in Bloomberg. Track positions in a fourth system. Each piece does
ONE job and none of them agree on definitions.

BCSI gives you a single, honest, explainable answer:

→ One 0-100 score per company
→ Composed from 5 dimensions: Risk, Quality, Valuation, Momentum,
  Governance
→ Every dimension shows its work (no black-box scoring)
→ ML-backed distress prediction with SHAP — every probability tells you
  exactly which 5 features drove it
→ Real-time price feed, multi-user watchlists, email + Slack alerts
→ India-specific governance signals (promoter pledge, SEBI enforcement,
  auditor changes) — the things Bloomberg doesn't track for Indian
  equities

It runs as a self-hosted web app. No SaaS upsell. No per-seat pricing.
No "contact us for enterprise."

This is closer to a finished platform than a research toolkit. It has
the things you'd expect from a production system: audit logs, JWT
rotation, deep health checks, Prometheus metrics, structured logging,
and a coverage-gated CI.

If your team is doing single-name credit work or sector monitoring and
the spreadsheet has gotten unwieldy, I'd love to know what's missing
that would make it useful to you.

Code, demo video, and docs: <REPO_URL>

#OpenSource #Fintech #CreditRisk #Python #QuantitativeFinance
```

---

## Hashtag strategy

5 hashtags is the LinkedIn sweet spot. The ones above target:

| Hashtag | Why |
|---|---|
| `#OpenSource` | Hits the broader software audience, dilutes the finance-only signal |
| `#Fintech` | The natural finance audience |
| `#CreditRisk` | The narrow, high-conversion audience (this is who'd actually deploy it) |
| `#Python` | Surfaces in the technical-but-finance-adjacent feed |
| `#QuantitativeFinance` | Catches researchers + quant teams |

Avoid: `#AI`, `#ChatGPT`, `#MachineLearning` — saturated, hashtag spam, dilutes the signal.

---

## Engagement playbook

LinkedIn's algorithm is comment-driven, not like-driven. To trigger
distribution:

**Hour 0–1**:
- Ask 3-5 specific people in your network to comment (NOT just like).
  Personal DMs work: "I just posted about a project I think you'd find
  interesting — any chance you'd leave a one-line take?" The comments
  trigger the algorithm.
- Reply to every commenter with 2+ sentence answers (NOT thumbs-up
  emoji). LinkedIn treats single-emoji replies as low-effort.

**Hour 1–24**:
- DM the top 10 connections in finance/banking individually with the
  link. Personal, not broadcast. "Saw you working on [X]; this might be
  relevant" beats "check out my project."

**Day 2–7**:
- Resurface in a comment on a related post. Don't repost yourself —
  LinkedIn punishes that hard.

---

## Connection-request boilerplate (for follow-ups)

When someone interacts with the post, you can connect with them. Use
this template:

```
Hi [name] — thanks for engaging with the BCSI post. Saw you work on
[X] at [company]; if it's useful for your team I'd love to hear what's
missing. Happy to talk through anything not in the README.
```

Convert ~10-20% of engaged-post viewers into connections. These are the
people most likely to a) star the repo, b) file useful issues, c) refer
the project to others in their org.

---

## What success looks like

- 50+ reactions in first 4 hours → algorithm is distributing it
- 10+ substantive comments (not just "great work!") → high-quality reach
- 5+ direct messages from finance professionals → the actual conversion
  metric

LinkedIn stars-per-impression is far lower than HN/Reddit, but the
**quality** of engaged users is way higher. One LinkedIn DM from a head
of credit risk at a real bank is worth more than 50 random stars.
