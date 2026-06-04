# Self-hosting a Bloomberg-lite for $7 a month

> **Cross-post target**: Hashnode → dev.to → r/selfhosted (this is the audience this post is for).
> **Length**: ~1,400 words.
> **Hook**: The pragmatic, "I'd actually do this on a Friday afternoon" piece. Tactical and concrete. Sells to the r/selfhosted + indie-hacker crowd, not the quant Twitter crowd.

---

Bloomberg Terminal is $24,000 per seat per year, and you have to call a salesperson to get it. FactSet and Capital IQ aren't much cheaper. For a small team or solo analyst, the entire institutional-grade tooling category prices you out.

This post is a concrete walkthrough of self-hosting BCSI — open-source, MIT-licensed company risk intelligence — on the cheapest credible VPS, configuring it for production, and running it for a real team. Total monthly cost is about $7, and the entire setup takes about an hour.

I'll cover the hosting choice, the security configuration that's actually needed (not the cargo-cult version), the backup story, and the things people get wrong on first deploy.

## The hosting choice

Three VPS providers I'd consider for this workload:

**Hetzner CX21** — 4 GB RAM, 2 vCPU, 40 GB SSD, in Falkenstein or Helsinki. €4.51/month including 20 TB egress. This is what I run on. Best price/performance in Europe; the data residency is a nice bonus for GDPR-adjacent use cases.

**OVH VPS Value** — similar specs in the US/EU, ~$5/month. Comparable to Hetzner; pick whichever has a datacentre closer to your users.

**DigitalOcean Basic Droplet (2 GB)** — $12/month, easier UI if you're new to VPS management, costs almost 3× Hetzner but gives you a clickier console.

For BCSI's footprint — a FastAPI process, a Postgres, a Redis, an APScheduler — 2 GB RAM is the floor. The XGBoost model load is the spiky bit; it sits around 200 MB resident. With Postgres+Redis+Python, you're comfortably under 1.5 GB total. The 4 GB Hetzner box is overkill but gives you headroom to grow.

What you do **not** need at this scale:
- Kubernetes (genuinely; a docker compose file is the right shape)
- A load balancer (the FastAPI process can handle hundreds of req/sec with the SlowAPI throttles in place)
- A separate scheduler VM (one Hetzner box runs everything until ~50 concurrent users)
- Managed Postgres (the Hetzner Postgres in docker-compose with daily pg_dump to S3 is fine until you grow past your single-instance comfort zone)

The shape that works at this scale is: **one VPS, docker-compose, Caddy in front of it, daily backup cron to S3 or Backblaze B2.** Anything more complex is premature.

## The 60-minute setup

```bash
# 1. Spin up the Hetzner box (Debian 12, SSH key auth, no password).
#    Takes 30 seconds in the Hetzner console.

ssh root@<your-vps-ip>

# 2. Lock the box down: SSH hardening, unattended-upgrades, ufw.
apt update && apt upgrade -y
apt install -y ufw unattended-upgrades fail2ban
ufw default deny incoming
ufw allow ssh
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
dpkg-reconfigure -plow unattended-upgrades   # Enable auto-security patches

# Disable password SSH:
sed -i 's/#*PasswordAuthentication .*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/#*PermitRootLogin .*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
systemctl restart sshd

# 3. Install Docker.
curl -fsSL https://get.docker.com | sh

# 4. Clone BCSI.
git clone https://github.com/Shekharpadhy/Stock-analysis.git /opt/bcsi
cd /opt/bcsi

# 5. Generate strong secrets.
cat > .env <<EOF
APP_ENV=production
JWT_SECRET=$(python3 -c 'import secrets;print(secrets.token_urlsafe(64))')
ADMIN_PASSWORD=$(python3 -c 'import secrets;print(secrets.token_urlsafe(24))')
DATABASE_URL=postgresql+psycopg2://bcsi:bcsi_local_only@db:5432/bcsi
REDIS_URL=redis://redis:6379/0
CORS_ORIGINS=https://bcsi.your-domain.com
PUBLIC_BASE_URL=https://bcsi.your-domain.com
ALERT_SMTP_HOST=smtp.sendgrid.net
ALERT_SMTP_USER=apikey
ALERT_SMTP_PASSWORD=<your-sendgrid-key>
ALERT_EMAIL_FROM=alerts@your-domain.com
SCHEDULER_ENABLED=true
RATE_LIMIT_ENABLED=true
LOG_FORMAT=json
EOF

# IMPORTANT: read the ADMIN_PASSWORD from .env and save it somewhere safe.
# This is your only chance to recover it.
grep ADMIN_PASSWORD .env

# 6. Boot it up.
docker compose up -d

# 7. Verify health.
curl -s http://localhost:8000/api/v1/health | python3 -m json.tool
```

That's the application running. Now you need TLS in front of it, which is a 10-line Caddyfile:

```bash
# 8. Install Caddy on the host (NOT in docker — Caddy needs port 80/443 directly).
apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | tee /etc/apt/trusted.gpg.d/caddy-stable.asc
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
apt update && apt install -y caddy

# 9. Configure Caddy. Replace the domain with yours.
cat > /etc/caddy/Caddyfile <<EOF
bcsi.your-domain.com {
    encode gzip
    reverse_proxy localhost:8000
    @ws path /api/v1/ws/*
    reverse_proxy @ws localhost:8000
    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Content-Type-Options    "nosniff"
        Referrer-Policy           "strict-origin-when-cross-origin"
    }
}
EOF

systemctl reload caddy

# Caddy auto-provisions Let's Encrypt certs. Wait ~30 seconds and visit
# your domain — you should see the BCSI dashboard over HTTPS.
```

You're live. About 50 minutes if you're working from this template.

## What this setup gets right that most "self-host X" guides don't

**TLS automatically renews.** Caddy handles Let's Encrypt automatically. You'll never get the 4 AM "cert expired" page.

**The scheduler is safely on.** `SCHEDULER_ENABLED=true` works because BCSI uses DB-backed leader election (`scheduler_lock` table). If you later scale to two app workers, the lock prevents the cron jobs from double-firing. Most "self-host X" guides skip this and you discover it the hard way when alerts double-fire.

**Rate limiting is on by default.** `RATE_LIMIT_ENABLED=true` enables the slowapi throttles on auth endpoints. Brute-forcing the admin login from across the internet hits a 10-attempts-per-minute ceiling.

**The app refuses to boot with insecure defaults.** Forgetting to set `JWT_SECRET` or leaving `ADMIN_PASSWORD=change-me` would let the app start in v0.9 and silently leave you exposed. v1.0 explicitly refuses to start in `APP_ENV=production` until you've overridden them. Documented in `DEPLOYMENT.md`.

**JSON logs work out of the box.** `LOG_FORMAT=json` makes the output ingestable by any log shipper. If you later add Loki or Datadog or Elastic, you're not rewriting log code.

## The backup story

The data that matters lives in Postgres. Everything else is either ephemeral (Redis cache) or trivially regenerable (the ML model retrains weekly).

The minimum-viable backup is a daily `pg_dump` to off-site object storage:

```bash
# 10. Backup script.
cat > /usr/local/bin/bcsi-backup.sh <<'EOF'
#!/bin/bash
set -euo pipefail

TS=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR=/var/backups/bcsi
mkdir -p "$BACKUP_DIR"

docker compose -f /opt/bcsi/docker-compose.yml exec -T db \
    pg_dump -U bcsi --format=custom bcsi \
    > "$BACKUP_DIR/bcsi-$TS.pgdump"

# Ship to Backblaze B2 (cheaper than S3 for backup workloads).
b2 upload-file my-bcsi-backups "$BACKUP_DIR/bcsi-$TS.pgdump" "bcsi-$TS.pgdump"

# Keep last 14 days locally.
find "$BACKUP_DIR" -name 'bcsi-*.pgdump' -mtime +14 -delete
EOF

chmod +x /usr/local/bin/bcsi-backup.sh

# 11. Schedule daily at 03:00 UTC.
(crontab -l 2>/dev/null; echo "0 3 * * * /usr/local/bin/bcsi-backup.sh") | crontab -
```

Backblaze B2 storage is $0.006/GB-month. A typical BCSI database with 6 months of analyses is under 500 MB. You're paying cents per month for backups.

The thing most "set up backups" guides skip is the **restore drill**. Once a quarter, spin up a second VPS, restore the latest backup, verify the dashboard loads. If you've never tested restoration, you don't have backups — you have hopes.

## Cost summary

| Item | Monthly cost |
|---|---|
| Hetzner CX21 VPS | €4.51 (~$5) |
| Domain name (Cloudflare or Namesilo) | ~$1 |
| Backblaze B2 backup storage | $0.01 |
| SendGrid free tier (100 emails/day) | $0 |
| **Total** | **~$6/month** |

Compare to:

| Tool | Monthly cost |
|---|---|
| Bloomberg Terminal | $2,000+ |
| FactSet (smallest tier) | $1,200+ |
| Capital IQ Pro | $1,500+ |
| Simply Wall St (Pro) | $20 |
| BCSI self-hosted | **$6** |

You're getting Bloomberg-shaped capabilities for the price of a coffee.

## What's genuinely missing

I'm not pretending this replaces Bloomberg. Bloomberg has:

- Real-time tick data (BCSI is delayed market data via yfinance)
- Fixed income coverage (BCSI is equities)
- Global depth (BCSI is US + India fully, EU partial, no LATAM/Africa)
- The chat network (this is honestly the actual moat — and BCSI doesn't try)
- Levered analyst research (BCSI uses public yfinance recommendations)

If your work depends on tick-level execution or fixed-income coverage, Bloomberg is the right tool and the price is justified. BCSI is for analysts whose actual workflow is "screen, score, monitor, alert" — which, in my experience, is what 80% of the seats in front of a Bloomberg are actually doing.

## Where to go from here

The full deployment guide — including the scheduler-singleton constraint, JWT rotation procedure, and a pre-deployment checklist — is in [`DEPLOYMENT.md`](https://github.com/Shekharpadhy/Stock-analysis/blob/main/DEPLOYMENT.md) in the repo.

If you spin this up and hit issues, file an issue on GitHub — every install is a chance for me to find another rough edge in the docs.

---

**BCSI is at github.com/Shekharpadhy/Stock-analysis. MIT licensed, $6/month to run, 60 minutes to deploy. If you're paying for Simply Wall St or FactSet and the spreadsheet is doing 80% of the work anyway, this might be the thing you've been waiting for.**

*Star the repo if you'd actually deploy it.*
