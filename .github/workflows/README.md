# GitHub Actions — AI-Trading CI/CD

Two workflows, jobhunter pattern (auto-deploy on push):

- **`ci.yml`** — runs on every push & PR to `main`. Postgres + TimescaleDB service, applies init.sql + all migrations, runs pytest. Frontend job runs `tsc --noEmit` + `npm run lint`. **No deploy gate** — runs in parallel with deploy.yml.
- **`deploy.yml`** — runs on every push to `main` (and manual dispatch). SSHes into the VPS and runs `infra/scripts/deploy.sh`, which:
  1. `git fetch + reset --hard origin/main`
  2. Apply ALL `infra/migrations/0*.sql` (idempotent — `CREATE * IF NOT EXISTS` + `DO/EXCEPT` patterns). Any psql failure with `ON_ERROR_STOP=1` aborts the deploy with a clear message — no silent swallow.
  3. `npm ci && npm run build` for `dashboard-ui` (Next.js standalone)
  4. Refresh `pulse-bridge` venv (`pip install -e pulse-bridge`)
  5. Drop `infra/traefik/ai-trading.yml` to `/opt/n8n/traefik/dynamic/` (Traefik file-watch auto-reloads)
  6. `sudo systemctl restart dashboard-ui pulse-bridge` (skips if unit not installed yet — operator authors at first deploy time)
  7. Post-deploy health check via `curl https://ai-trading.alisadikinma.com/login` (retries 60s while Next.js standalone boots)

CI does **not** gate the deploy. They run in parallel. If you want CI-passing-required-before-deploy, switch the `on:` block in `deploy.yml` to `workflow_run` triggered by `ci.yml`.

## Iron Law boundaries

CI/CD only deploys the **cockpit** (dashboard-ui + pulse-bridge). It does **not** auto-deploy:

- `crypto-bot/` (claude-routines, freqtrade-config, strategies) — operator-curated per Iron Law 4
- `freqtrade-fork/` — submodule, separate manual update
- Already-applied migrations 000-006 — Iron Law 4 forbids edits
- `~/.ai-trading/.env` — secrets, operator-managed

Trading body changes reach the VPS via manual `git pull` after explicit operator review. Live trading mode is toggled via env var on VPS, never via deploy.

## Required GitHub Secrets

**Settings → Secrets and variables → Actions** (already configured for srv941303):

| Secret | Value | Purpose |
|---|---|---|
| `VPS_SSH_HOST` | `31.97.188.145` | srv941303 IP |
| `VPS_SSH_USER` | `claudesn` | UID matches `.mcp.json` |
| `VPS_SSH_PORT` | `22` (optional) | SSH port |
| `VPS_SSH_PRIVATE_KEY` | `-----BEGIN OPENSSH PRIVATE KEY-----\n...` | Full private key contents (multi-line). Use a dedicated deploy key, not your personal `id_ed25519` |
| `VPS_SSH_KNOWN_HOSTS` | `<base64>` | Output of `ssh-keyscan -H <vps-host> \| base64 -w0`. Pins host key (defends against MITM + IP reuse) |
| `VPS_PROJECT_PATH` | `/home/claudesn/ai-trading` (optional) | Repo path on VPS — defaults to this if unset |

**5 secrets minimum** (`VPS_SSH_PORT` and `VPS_PROJECT_PATH` have defaults).

## First-run bootstrap on srv941303

One-time setup as `claudesn`. After this, every push to `main` deploys automatically.

```bash
ssh claudesn@31.97.188.145

# 1. Clone the repo (uses dedicated deploy key)
git clone git@github.com:alisadikinma/indusia-ai-trading.git ~/ai-trading
cd ~/ai-trading

# 2. Build .env at ~/.ai-trading/.env (operator-managed, not in repo)
mkdir -p ~/.ai-trading
chmod 700 ~/.ai-trading
# Populate with:
#   PG_USER, PG_PASS, PG_DB, PG_HOST, PG_PORT, DATABASE_URL
#   POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB
#       (pulse-bridge dashboard_main expects POSTGRES_*; mirror PG_* values)
#   DASHBOARD_JWT_SECRET (32+ chars; openssl rand -base64 48)
#   DASHBOARD_OPERATOR_USERNAME
#   DASHBOARD_OPERATOR_PASSWORD_ARGON2_HASH (single-quote the value to keep
#       bash from expanding $argon2id under set -u)
#   DASHBOARD_UI_ORIGIN=https://ai-trading.alisadikinma.com (CORS allow-list)
#   NEXT_PUBLIC_DASHBOARD_API_URL=https://ai-trading.alisadikinma.com
#   NEXT_PUBLIC_DASHBOARD_WS_URL=wss://ai-trading.alisadikinma.com/dashboard/ws

# 3. Author systemd units (one-time; deploy.sh skips with warning if missing)
sudo tee /etc/systemd/system/dashboard-ui.service <<'EOF'
[Unit]
Description=AI-Trading dashboard-ui (Next.js standalone)
After=network.target postgresql.service

[Service]
Type=simple
User=claudesn
WorkingDirectory=/home/claudesn/ai-trading/dashboard-ui
EnvironmentFile=/home/claudesn/.ai-trading/.env
Environment=PORT=3000
# 172.17.0.1 = docker bridge gw, reachable from the Traefik container
# without exposing :3000 to the public internet (matches portfolio.yml).
Environment=HOSTNAME=172.17.0.1
ExecStart=/usr/bin/node .next/standalone/server.js
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/pulse-bridge.service <<'EOF'
[Unit]
Description=AI-Trading pulse-bridge dashboard API (FastAPI)
After=network.target postgresql.service

[Service]
Type=simple
User=claudesn
WorkingDirectory=/home/claudesn/ai-trading
EnvironmentFile=/home/claudesn/.ai-trading/.env
# dashboard_main:app serves /dashboard/* (read-only UI API).
# main:app (brain<->body /v1/* HMAC bridge) is a separate service —
# add a second unit on a different port when Phase 4 brings it online.
# Bind to 172.17.0.1 (docker bridge gw) so the Traefik container can
# reach it without exposing :8081 to the public internet.
ExecStart=/home/claudesn/ai-trading/.venv/bin/uvicorn pulse_bridge.dashboard_main:app --host 172.17.0.1 --port 8081
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable dashboard-ui pulse-bridge

# 4. Smoke test the deploy script manually (verifies everything before letting CI fire)
bash infra/scripts/deploy.sh

# 5. Confirm health
curl -sf https://ai-trading.alisadikinma.com/login | head -3
```

After step 5 returns HTML (not curl error), every `git push origin main` will auto-deploy.

## First-run checklist

- [ ] All 5 GitHub secrets configured
- [ ] SSH from a workstation succeeds: `ssh claudesn@31.97.188.145 'whoami'`
- [ ] Repo cloned at `/home/claudesn/ai-trading`, `main` checked out
- [ ] `~/.ai-trading/.env` populated with production values (no defaults, no `change-me`)
- [ ] systemd units installed and enabled (`sudo systemctl is-enabled dashboard-ui pulse-bridge`)
- [ ] Traefik already running on VPS (cohabits with sparkfluence + jobhunter + labelstudio)
- [ ] DNS for `ai-trading.alisadikinma.com` points at VPS IP (verified — DNS-only Cloudflare A record)
- [ ] Smoke test: push a docs-only commit to `main`, watch the Actions tab

## Manual trigger options

**Actions** → **Deploy to VPS** → **Run workflow**:

- **`skip_frontend`** (default `false`) — skip dashboard-ui rebuild. Use when only backend code changed and dashboard-ui artifacts are still current.
- **`force_rebuild`** (default `false`) — nuke `~/ai-trading/.venv` and reinstall pulse-bridge from scratch. Use after `pulse-bridge/pyproject.toml` lockfile changes that aren't picking up via `pip install -e`.

## Troubleshooting

**`Permission denied (publickey)`** — `VPS_SSH_PRIVATE_KEY` doesn't match any line in VPS `~/.ssh/authorized_keys`. Re-paste secret (incl. BEGIN + END lines), verify `cat ~/.ssh/deploy_key.pub` on VPS matches a line in authorized_keys.

**Health check fails after 60s** — Check `journalctl -u dashboard-ui -n 50` on VPS. Common causes: missing env var (pydantic ValidationError), JWT secret <32 chars, Postgres unreachable, port 3000 already taken.

**`systemd unit not installed`** warning during deploy — One-time setup not done. SSH in, install the units per "First-run bootstrap" above.

**Migrations error: schema "brain" does not exist** — `infra/postgres/init.sql` not applied. Run as postgres superuser: `sudo -u postgres psql -d trading -f infra/postgres/init.sql`.

## Concurrency

`concurrency: deploy-production` prevents two deploys running simultaneously. `cancel-in-progress: false` means a push during in-flight deploy queues the new one — does NOT interrupt the active deploy mid-build.
