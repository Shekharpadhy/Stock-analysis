# Deploying BCSI to Render (one-click)

This is the fastest path from "code on GitHub" to "live URL" for BCSI.

**Total time**: ~10 minutes (5 of which are Render's provisioning).
**Cost**: $0 on the free tier. ~$7/month if you want it to stay always-on.

---

## Why Render (and not Vercel / Heroku / etc.)

Vercel is designed for serverless functions and static sites. BCSI is a
long-running FastAPI process with WebSockets, an in-process scheduler, and
a Postgres database — none of which fit Vercel's model.

Render is the closest thing to Vercel's UX for our shape:

- Free tier with managed Postgres + Redis
- Long-running web service (WebSockets just work)
- Auto-deploys from GitHub on every push
- A `render.yaml` blueprint provisions everything in one click

---

## Step 1 — Click the button

In the project root README, click the **Deploy to Render** badge. It looks
like this:

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/YOUR-HANDLE/YOUR-REPO)

You'll be asked to:

1. Sign in to Render (free, GitHub auth available).
2. Authorise Render to read this repo.
3. Confirm the blueprint (just click "Apply").

Render reads [`render.yaml`](render.yaml) and provisions:

- `bcsi-web` — the FastAPI web service (Docker, from the repo Dockerfile)
- `bcsi-db` — managed Postgres (free tier, 1 GB, 90-day backups)
- `bcsi-redis` — managed Redis (free tier, 25 MB)

## Step 2 — Wait for provisioning (~5 min)

Render builds the Docker image, applies Alembic migrations, and starts the
service. Watch the build log in the Render dashboard. You're done when the
web service shows **Live**.

## Step 3 — Get your URL

It's at the top of the `bcsi-web` service page in the Render dashboard.
Format: `https://bcsi-web.onrender.com` (or `bcsi-web-XXXX.onrender.com`
if your service name was taken).

Update the README:

```bash
# Replace the placeholder with your real URL:
sed -i.bak 's|bcsi-web\.onrender\.com|YOUR-ACTUAL-URL|g' README.md
git add README.md
git commit -m "docs: link live demo URL"
git push
```

## Step 4 — Get the admin password

The blueprint asks Render to generate a strong random `ADMIN_PASSWORD`.
Retrieve it:

1. Open the `bcsi-web` service in Render
2. Click **Environment** in the left sidebar
3. Find `ADMIN_PASSWORD` and click the eye icon to reveal it
4. Save it to your password manager

You log in at `https://YOUR-URL/api/v1/auth/token` with:
- Username: `admin`
- Password: (the value from step 3)

## Step 5 (optional) — Configure email / Slack alerts

The blueprint marks the alert delivery vars as `sync: false`, meaning they
must be set manually. In the `bcsi-web` Environment page, fill in:

```
ALERT_SMTP_HOST       = smtp.sendgrid.net          (or your provider)
ALERT_SMTP_USER       = apikey                     (SendGrid convention)
ALERT_SMTP_PASSWORD   = <your-API-key>
ALERT_EMAIL_FROM      = alerts@your-domain.com
ALERT_SLACK_WEBHOOK   = https://hooks.slack.com/services/...   (optional)
```

Hit "Save changes". Render auto-redeploys.

If you skip this step, BCSI still runs — email/Slack alerts simply
no-op until configured. Watchlists, scoring, ML predictions, and the
dashboard all work without them.

---

## What you get on the free tier

- ✅ Full BCSI dashboard, every feature works
- ✅ Auto-deploy on every `git push` to `main`
- ✅ HTTPS, automatic certificate
- ⚠️ Service sleeps after 15 min of inactivity (next request takes ~30s
     to wake) — fine for a demo, awkward for daily use
- ⚠️ Postgres free tier has 90-day backup retention
- ⚠️ Redis free tier is 25 MB (cache only; if exhausted, app keeps working
     but loses the cache speedup)

## Upgrading to keep it always-on

For ~$7/month (Render's "starter" web service plan):

1. `bcsi-web` Settings → **Instance Type** → Starter
2. That's it — no code changes

The service stays warm 24/7. Cold starts disappear.

---

## What can go wrong

| Symptom | Cause | Fix |
|---|---|---|
| Build fails at `pip install` | XGBoost wheel mismatch | Confirm `python:3.11-slim` in Dockerfile; XGBoost has prebuilt wheels for this |
| `/health` returns `down` for database | Wrong `DATABASE_URL` | Verify env var resolved (Render dashboard → Environment) |
| App boots but `/api/v1/auth/token` rejects everything | `ADMIN_PASSWORD` not propagated | Manually set it in the Environment page, save, redeploy |
| WebSocket prices not updating | Browser cached old origin | Hard refresh (Cmd+Shift+R) |
| Alerts not sending | SMTP vars not set | Step 5 above |
| First request takes 30 seconds | Free tier woke from sleep | Expected; upgrade to Starter to eliminate |

If something else breaks, the Render service log is your friend — it
streams stdout from the FastAPI process in real time.

---

## Migrating off Render later

The `render.yaml` is the only Render-specific file in the repo. Everything
else is portable:

- `Dockerfile` works on any container platform (Fly.io, Cloud Run, ECS)
- `docker-entrypoint.sh` honours `$PORT` from any host
- The full self-hosted recipe is in [`DEPLOYMENT.md`](DEPLOYMENT.md)
  (Hetzner VPS + Caddy + docker-compose, ~$6/month, more control)

If you outgrow Render, you can move to a $6 Hetzner VPS without changing a
line of application code.
