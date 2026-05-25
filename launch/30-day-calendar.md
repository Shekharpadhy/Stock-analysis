# 30-day promo calendar

Everything in `launch/posts/` and `launch/blog/` slots into a date below.
The principle: **never repeat content, never go dark for >48h**. Reach is
compound — small daily moves outperform infrequent big swings.

**Daily commitment**: ~30 minutes. Most of that is replying to comments,
not posting new things.

---

## Week 1 — Launch

| Day | Date | Channel | Asset | Notes |
|---|---|---|---|---|
| 1 | Mon | GitHub | Final repo polish: README screenshot + demo GIF embedded | Single most-important asset; do this before anything else |
| 1 | Mon | LinkedIn | Post `05-linkedin.md`, 7:30 AM ET | Hits finance professionals before they check Twitter |
| 2 | Tue | Hacker News | Submit `01-show-hn.md`, 8 AM PT | Stay on the post for the first 4 hours |
| 2 | Tue | Twitter/X | Post `02-twitter-thread.md` 3h into HN if climbing, else independently | Native video upload, not YouTube link |
| 3 | Wed | r/algotrading | Post `03-reddit-algotrading.md`, 9 AM ET | Day 2 of HN; let HN settle before adding another platform |
| 4 | Thu | Personal blog | Publish `01-why-quant-tools-compute-the-same-score-badly.md` | Set canonical URL here; cross-posts will reference it |
| 4 | Thu | Twitter/X | "New post: here's why every quant tool computes the same score badly" → blog link | One tweet, not a thread |
| 5 | Fri | r/Python | Post `04-reddit-python.md`, 10 AM ET | Use mandatory template; mods enforce it |
| 5 | Fri | LinkedIn | Share blog post `01` as a LinkedIn Article (native) | Maximises reach in your network |
| 6 | Sat | — | Quiet day. Reply to weekend HN/Reddit comments | DO NOT post on weekends; engagement is half |
| 7 | Sun | — | Plan week 2 from this week's analytics | Note: which platform converted? double down there |

---

## Week 2 — Substance

| Day | Date | Channel | Asset | Notes |
|---|---|---|---|---|
| 8 | Mon | dev.to | Cross-post blog `01` (with canonical link to your blog) | dev.to community engages mid-week |
| 9 | Tue | Personal blog | Publish `02-putting-shap-in-front-of-a-credit-officer.md` | The "I'd actually use this" piece |
| 9 | Tue | Twitter/X | New thread: "5 reasons most ML in fintech never gets deployed" — soft pitch for post 02 | Lead with the problem, link the post at the end |
| 10 | Wed | LinkedIn | Post the SHAP screenshot from blog `02` with a 200-word commentary + repo link | Finance-professional crowd cares more about this than dev tooling |
| 11 | Thu | r/MachineLearning | "Embedding SHAP in production ML APIs — what worked" | Use blog `02` as basis; r/ML hates self-promo but loves technical writeups |
| 11 | Thu | Medium | Cross-post blog `02` (48h after canonical) | Medium algorithm now indexes it; canonical signal already established |
| 12 | Fri | Hacker News | Submit blog `02` as a "Show HN: I built…" follow-up if first didn't catch, OR an "I wrote about…" link if it did | Different angle, different chance |
| 13 | Sat | — | Quiet | — |
| 14 | Sun | Email outreach | DM 10 specific finance Twitter accounts who'd actually care; personalised, NOT broadcast | Manual; one of the highest-ROI activities of the month |

---

## Week 3 — Practical

| Day | Date | Channel | Asset | Notes |
|---|---|---|---|---|
| 15 | Mon | Personal blog | Publish `03-self-hosting-bloomberg-lite-for-seven-dollars.md` | Practical, tactical, screenshotable |
| 15 | Mon | r/selfhosted | Post about blog 03 with hosting walkthrough | r/selfhosted loves "$X/month replaces $Y SaaS" framing |
| 16 | Tue | r/sysadmin | Different angle: "Deployed a multi-user fintech app on a $5 VPS — here's the setup" | Linux/devops audience, different from r/Python |
| 17 | Wed | Twitter/X | Thread: "I run a Bloomberg-shaped tool for $6/month. Here's the entire setup" | Show the actual Caddyfile, the docker-compose, the cron. People love the numbers |
| 18 | Thu | LinkedIn | Long-form post: cost comparison Bloomberg vs BCSI for small finance teams | Engages your professional network on the cost angle |
| 19 | Fri | indie hackers forum | Post about the build process: lessons learned shipping v1.0 | Different audience again; indie hackers love the journey post |
| 20 | Sat | — | Quiet | — |
| 21 | Sun | Analytics review | Star count, traffic sources, top blog posts. Decide week 4 angle | What's working? What isn't? |

---

## Week 4 — Sustain

| Day | Date | Channel | Asset | Notes |
|---|---|---|---|---|
| 22 | Mon | Hacker News | "Ask HN: How would you extend an open-source company-risk dashboard?" | Converts lurkers to commenters; brings in feature suggestions |
| 23 | Tue | Twitter/X | Post a real user's screenshot (with permission) showing their setup or a specific catch | Social proof beats your own claims 5:1 |
| 24 | Wed | r/algotrading | Follow-up: "BCSI 2 weeks in — what we learned from 200 users" (use real numbers) | If you have actual user data; if not, skip |
| 25 | Thu | Personal blog | Short post: "v1.1 plans based on community feedback" | Shows momentum; tells stargazers it's not abandoned |
| 26 | Fri | LinkedIn | Repost / refresh blog 01 with a "month-in review" framing | Reaches the LinkedIn audience that missed week 1 |
| 27 | Sat | — | Quiet | — |
| 28 | Sun | Newsletter outreach | Pitch the project to fintech / dev newsletters (Pointer, TLDR newsletter, Last Week in AWS) | Long-tail traffic; one inclusion can add 200 stars |
| 29 | Mon | Twitter/X | "Month-in review: BCSI launched 30 days ago. Here's where it stands" | Transparent stats — stars, issues, PRs, deploys |
| 30 | Tue | Reflect | Decide: continue the cadence at lower frequency, OR pivot to feature dev | The decision matters |

---

## Cadence after day 30

Sustained: ~2 posts/week (1 long-form, 1 social) + replying to issues + the next release-cycle blog post when v1.1 ships.

If month 1 conclusively didn't work (< 100 stars), the issue is positioning, not effort. Consider:

- Reskinning around a sharper niche ("the credit-risk SHAP tool" instead of "the dashboard")
- Specific industry blogs (Bank Innovation, Finextra, RiskNet) instead of dev channels
- Direct outreach to specific firms — 5 conversations beat 500 stars for actual usage

---

## Replying playbook

Replies are 80% of where stars come from. Three rules:

1. **Within 30 minutes for the first 4 hours of any post.** Faster than this triggers algo distribution.
2. **Substance, not gratitude.** "Good point — here's why I made that tradeoff" > "Thanks for the kind words!"
3. **One concrete piece of additional value per reply.** Link to the specific file, paste the relevant 3 lines of code, screenshot the precise UI element.

The reply-to-impression ratio is the actual conversion lever. Posts with replies in the top sub-thread convert 4-5× higher than posts with the author absent.

---

## When to abandon a channel

Honest decision tree:

- **HN, < 50 upvotes in 2h**: dead. Move on. Try again with a different angle in 60 days.
- **Reddit subreddit, < 20 upvotes in 4h**: dead in that sub. The sub doesn't want it; don't re-post.
- **Twitter, < 200 impressions in 2h**: algo capped. Try a new thread with a different hook 4-5 days later.
- **LinkedIn, < 100 impressions in 4h**: algo capped. Network's not your conversion channel; focus elsewhere.

Don't grind on a dead channel. Diagnose, decide, redirect.

---

## What gets tracked

Daily for the first 30 days:

| Metric | Source | Why |
|---|---|---|
| GitHub stars | repo page | Headline number |
| Repo visitors (unique) | GitHub insights | Read-to-star ratio |
| Repo clones | GitHub insights | Strong intent signal |
| Issues filed | GitHub | Stars + intent (people only file issues for things they care about) |
| Demo URL hits | server logs | If you have a live demo — conversion proof |
| Replies to your posts | manual | The flywheel input |

A 1% star-to-visitor ratio is normal. 3% is excellent. < 0.5% means the README isn't doing its job — revisit it.
