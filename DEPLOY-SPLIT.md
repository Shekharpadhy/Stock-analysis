# Split Deployment — Vercel frontend + Render backend

This is the path you chose: dashboard hosted on **Vercel** (fast static-asset
CDN), API hosted on **Render** (FastAPI + Postgres + Redis + WebSockets).

Tradeoff vs the full-Render single-domain deploy: one extra moving piece
(the CORS allowlist) and two URLs to keep in sync. The benefit is genuinely
faster frontend page-load and a `*.vercel.app` URL that's noticeably nicer
to share than `*.onrender.com`.

**Total time**: ~15 minutes.

---

## Step 1 — Deploy the backend to Render

This is identical to [`DEPLOY-RENDER.md`](DEPLOY-RENDER.md); follow that
guide first. When done you'll have a backend URL like:

```
https://bcsi-web.onrender.com
```

**Write it down — you'll paste it into two places in the next steps.**

Quick sanity check:

```bash
curl -s https://bcsi-web.onrender.com/api/v1/health | jq .status
# Expected: "ok"  (or "degraded" if the scheduler isn't fully up yet — fine)
```

---

## Step 2 — Wire the frontend to the backend URL

Open `frontend/index.html` and change the one inline script tag near the
bottom:

```html
<!-- BEFORE -->
<script>window.BCSI_BACKEND_URL = "";</script>

<!-- AFTER (use YOUR Render URL — NO trailing slash) -->
<script>window.BCSI_BACKEND_URL = "https://bcsi-web.onrender.com";</script>
```

That's the only frontend change. `app.js` reads `window.BCSI_BACKEND_URL`
on load and routes every API call + WebSocket to it.

Commit + push:

```bash
git add frontend/index.html
git commit -m "config: point frontend at production Render backend"
git push
```

---

## Step 3 — Deploy the frontend to Vercel

Two ways, pick one:

### Option A — Vercel CLI (faster, but requires local Node)

```bash
npm install -g vercel
cd /path/to/Stock-analysis
vercel deploy --prod
```

When asked:
- *Set up and deploy?* → **Y**
- *Which scope?* → your personal account
- *Link to existing project?* → **N** (or **Y** if you already created one)
- *Project name?* → `stock-analysis` (or whatever you like)
- *In which directory is your code located?* → `./`

Vercel reads [`vercel.json`](vercel.json), which already points at the
`frontend/` directory and sets the security headers. About 30 seconds later:

```
✅  Production: https://stock-analysis.vercel.app
```

That's your shareable URL.

### Option B — Vercel dashboard (no local Node needed)

1. Go to <https://vercel.com/new>.
2. Click **Import** next to the `Shekharpadhy/Stock-analysis` repo.
3. Framework Preset: **Other**.
4. Root Directory: **./** (the default).
5. Build & Output settings: leave at defaults — `vercel.json` overrides them.
6. Click **Deploy**.

About 30 seconds later you'll see the live URL in the dashboard.

---

## Step 4 — Update Render's CORS allowlist with your real Vercel URL

The `render.yaml` ships with a placeholder `https://stock-analysis.vercel.app`.
If your actual Vercel URL is different (preview deploys get unique URLs):

1. Render dashboard → `bcsi-web` service → **Environment** (left sidebar).
2. Edit `CORS_ORIGINS`. Set to a comma-separated list:
   ```
   https://stock-analysis.vercel.app,https://stock-analysis-shekharpadhy.vercel.app
   ```
   Include every Vercel URL that should be able to call the API — typically
   the production URL plus your preview-deploy pattern.
3. Save. Render auto-redeploys (~1 minute).

**Why this matters**: without it, browsers will block every API call from
the Vercel-hosted frontend with a CORS error. The dashboard will show an
empty page and the network tab will be red.

---

## Step 5 — Update the README

Replace the live-demo URL placeholder in `README.md`:

```bash
# Replace the Render-only placeholder with your real Vercel URL
sed -i.bak 's|bcsi-web\.onrender\.com|stock-analysis.vercel.app|g' README.md
rm README.md.bak

git add README.md
git commit -m "docs: link live Vercel demo URL"
git push
```

---

## How it all fits together

```
        ┌─────────────────────────┐
USER ──▶│ stock-analysis.vercel.app│ (static HTML/CSS/JS)
        └────────┬────────────────┘
                 │  fetch / WebSocket
                 ▼
        ┌─────────────────────────┐
        │ bcsi-web.onrender.com   │ (FastAPI + APScheduler)
        └────────┬────────────────┘
                 │
        ┌────────┴────────┬─────────────┐
        ▼                 ▼             ▼
   bcsi-db          bcsi-redis    background jobs
  (Postgres)        (cache)       (alerts, retrain)
```

Vercel hosts only the static `frontend/` directory; every API path,
WebSocket connection, and auth flow goes to Render.

---

## Testing the split deploy

1. Open `https://stock-analysis.vercel.app` in a browser.
2. Open dev tools → **Network** tab.
3. Click **Analyze** with a ticker.
4. Watch the network requests — they should fire to `bcsi-web.onrender.com`,
   not to `vercel.app`. If they go to `vercel.app/api/v1/...` you'll see
   404s — that means step 2 wasn't done or didn't deploy.
5. The live price indicator in the header should turn green within a few
   seconds — that confirms the WebSocket connection to Render works.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Page loads, all API calls 404 | `BCSI_BACKEND_URL` not set or empty | Re-check step 2; verify in browser console: `window.BCSI_BACKEND_URL` |
| API calls fail with CORS error | Vercel domain not in Render's `CORS_ORIGINS` | Step 4 above |
| Live indicator stays red | WebSocket blocked (CORS or wrong scheme) | Check `wss://` not `ws://` in dev tools → Network → WS tab |
| Render `/health` shows `down` | Postgres URL not resolved | Render dashboard → Environment → verify `DATABASE_URL` is set |
| First load takes 30s | Render free tier woke from sleep | Expected; upgrade to Starter ($7/mo) to eliminate |
| Vercel shows blank page | Output directory wrong | `vercel.json` should have `"outputDirectory": "frontend"` |

---

## Going back to single-domain (full Render) later

If you decide split-domain isn't worth it:

1. Edit `frontend/index.html` → reset `window.BCSI_BACKEND_URL = ""`.
2. Push. Vercel auto-redeploys to same-origin mode (but now points at
   Vercel which has no API — so just stop using the Vercel URL).
3. Visit `https://bcsi-web.onrender.com` directly — it serves the
   frontend too (FastAPI mounts `frontend/` as a static directory).

No code rollback needed — the same codebase supports both modes.
