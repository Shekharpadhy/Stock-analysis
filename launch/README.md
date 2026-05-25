# BCSI Launch Kit

Everything you need to take BCSI from "good code on GitHub" to "actively
promoted launch with measurable reach."

This kit is the full **sustained promo + demo video** track laid out in
the response to the user's question. Each file is a self-contained asset
— open it, follow the instructions, execute.

## What's here

```
launch/
├── README.md                          ← you are here
├── demo-video-script.md               ← 90-sec script, timecoded, single-take
├── 30-day-calendar.md                 ← what to post when, replies playbook
├── posts/
│   ├── 01-show-hn.md                  ← Hacker News launch post + critique cheatsheet
│   ├── 02-twitter-thread.md           ← 8-tweet thread, hook-first
│   ├── 03-reddit-algotrading.md       ← r/algotrading post, technical angle
│   ├── 04-reddit-python.md            ← r/Python post, using their mandatory template
│   └── 05-linkedin.md                 ← LinkedIn post, B2B / finance-professional tone
└── blog/
    ├── 01-why-quant-tools-compute-the-same-score-badly.md    ← Design rationale (~1,800 words)
    ├── 02-putting-shap-in-front-of-a-credit-officer.md       ← Practical use case (~1,600 words)
    └── 03-self-hosting-bloomberg-lite-for-seven-dollars.md   ← Tactical deploy guide (~1,400 words)
```

Total content: **~5,000 words of blog post + 5 social posts + 1 video
script + a 30-day playbook**. Enough to fill the entire first month
without writing anything new.

## Execution order

The order matters — assets reference each other and audiences overlap.
Don't skip ahead.

1. **Record the video** (`demo-video-script.md`) — single most important
   asset. 90 seconds, one take. Render two outputs: a full MP4 for
   YouTube/Twitter/LinkedIn, and a 30-second GIF for the README hero.
2. **Drop the GIF into the project root README** — replaces the
   `[ADD A DEMO GIF HERE]` placeholder. Without this asset, every
   other post converts ~3× worse.
3. **Replace `<your-handle>` placeholders** in every file with your
   actual GitHub handle. Quick grep:
   ```bash
   grep -r '<your-handle>' launch/
   ```
4. **Set up tracking** before day 1 — at minimum, bookmark the GitHub
   Insights page for the repo. If you want richer analytics, drop a
   Plausible or Umami snippet on the demo site (don't use Google
   Analytics — privacy-conscious devs notice and downgrade your
   credibility silently).
5. **Follow the 30-day-calendar.md verbatim for week 1.** After that
   you can improvise; the calendar's job is to remove "what now?"
   friction from the days that matter most.

## Pre-launch checklist

Before posting anything publicly:

- [ ] Demo video recorded, edited, and uploaded to YouTube (public)
- [ ] Demo GIF (30s, < 5 MB) embedded above the fold in main README
- [ ] At least one demo deployment running publicly at a stable URL,
      so click-throughs from posts don't get a 404
- [ ] At least one fake/seed user account configured on the demo site
      with example data so visitors can poke around without registering
- [ ] All `<your-handle>` / `<your-domain>` placeholders replaced
- [ ] OpenAPI docs work at `/docs` on the demo site
- [ ] `/health` returns 200 OK
- [ ] CHANGELOG.md notes the v1.0 release
- [ ] A GitHub release tag (`v1.0.0`) created with the changelog as body
- [ ] You've manually run through the entire quickstart on a fresh VPS
      — finding the broken step on launch day is the worst-case scenario

## After day 30

The kit ends. What happens next is up to you. The honest options:

**Option A — Keep promoting**. Reduce cadence to 2 substantive posts a
week, focus on shipping features that give you the next "month-in-review"
story to tell. Average projects that broke 1k stars typically had 6-12
months of sustained content effort.

**Option B — Stop promoting, keep maintaining**. Reply to issues, ship
v1.1 quarterly, let the long-tail traffic from existing blog posts and
search compound. Honest end-state for most solo projects.

**Option C — Stop entirely**. Lock the repo, archive it, move on. This
is also fine. Not every well-built project deserves the maintenance tax.

There's no right answer. The decision is mostly about what you want from
this project — credibility for your CV, an actual product, a learning
artifact, or a portfolio piece. All four are legitimate.

## What I can't help with from here

Once you start posting, the loop is:

- Post → wait for replies → reply with substance → repeat

I (the AI that wrote this kit) can't sit at the keyboard with you for
that part. But every asset above is designed to work with the *minimum*
amount of real-time effort from you — the prep is done. You're left
with the irreducibly human work: replying to humans.

Good luck. Honestly, the project deserves the shot.
