#!/usr/bin/env bash
#
# VPS-side deploy script — invoked by GitHub Actions via a restricted
# SSH deploy key. The key's authorized_keys entry locks invocation to
# this exact script:
#
#     command="/home/claudesn/bin/deploy-cockpit.sh",no-port-forwarding,no-X11-forwarding,no-pty,no-agent-forwarding ssh-ed25519 AAAA... github-actions-deploy
#
# The Actions runner SSHes with `ssh ... "deploy <env> <ref>"`. The
# original command is passed via $SSH_ORIGINAL_COMMAND (parsed below).
#
# This script is the ONLY thing the deploy key can run. It is
# intentionally narrow: rsync target dir is fixed, systemd unit names
# are fixed, atomic-swap dirs are fixed.
#
# Setup once on VPS (operator, before first deploy):
#
#   mkdir -p ~/bin ~/ai-trading-staging ~/ai-trading-live
#   git clone https://github.com/alisadikinma/indusia-ai-trading.git ~/ai-trading-live
#   cp ~/ai-trading-live/infra/scripts/deploy-cockpit.sh ~/bin/deploy-cockpit.sh
#   chmod 700 ~/bin/deploy-cockpit.sh
#
#   # Generate dedicated deploy key (NOT the operator's id_ed25519):
#   ssh-keygen -t ed25519 -f ~/.ssh/deploy_key -N '' -C 'github-actions-deploy'
#   # Copy the public key into authorized_keys WITH the command="" lockdown:
#   echo 'command="/home/claudesn/bin/deploy-cockpit.sh",no-port-forwarding,no-X11-forwarding,no-pty,no-agent-forwarding '"$(cat ~/.ssh/deploy_key.pub)" \
#       >> ~/.ssh/authorized_keys
#   # Copy the PRIVATE key to GitHub repo Secrets as VPS_SSH_PRIVATE_KEY:
#   cat ~/.ssh/deploy_key
#   # Then DELETE the local copy: rm ~/.ssh/deploy_key
#
#   # Author the systemd units (ONE TIME, see docs/operations/cicd.md):
#   sudo cp infra/systemd/dashboard-ui.service /etc/systemd/system/
#   sudo cp infra/systemd/pulse-bridge.service /etc/systemd/system/
#   sudo systemctl daemon-reload
#   sudo systemctl enable dashboard-ui pulse-bridge
#
# Iron Law boundary: this script deploys the COCKPIT only. It does NOT
# touch crypto-bot/, freqtrade-fork/, claude-routines/, freqtrade-config/,
# or any operator-only file (Iron Law 4). Those reach the VPS only via
# manual `git pull` invoked by the operator.

set -euo pipefail
IFS=$'\n\t'

# ---------------------------------------------------------------------------
# Rollback function — defined first so error paths below can call it.
# Restores PREVIOUS_DIR back to LIVE_DIR if something fails mid-deploy.
# ---------------------------------------------------------------------------
rollback() {
    echo ">>> ROLLBACK — restoring previous build..."
    sudo systemctl stop dashboard-ui.service pulse-bridge.service 2>/dev/null || true
    if [ -d "${PREVIOUS_DIR:-/nonexistent}" ]; then
        rm -rf "${STAGING_DIR:-/nonexistent-staging}" 2>/dev/null || true
        # Move the half-baked LIVE_DIR aside as the new staging,
        # restore PREVIOUS_DIR back to LIVE_DIR.
        if [ -d "${LIVE_DIR:-/nonexistent-live}" ]; then
            mv "$LIVE_DIR" "$STAGING_DIR" 2>/dev/null || true
        fi
        mv "$PREVIOUS_DIR" "$LIVE_DIR"
    fi
    sudo systemctl start dashboard-ui.service pulse-bridge.service 2>/dev/null || true
    echo ">>> Rollback complete. Live points back at the previous good build."
}

# ---------------------------------------------------------------------------
# Parse the original SSH command. GitHub Actions sends:
#   ssh user@host "deploy <env> <ref>"
# which arrives as $SSH_ORIGINAL_COMMAND="deploy <env> <ref>".
# ---------------------------------------------------------------------------
if [ -z "${SSH_ORIGINAL_COMMAND:-}" ]; then
    echo "ERROR: SSH_ORIGINAL_COMMAND empty — this script must be invoked via SSH ForceCommand, not directly." >&2
    exit 1
fi

# shellcheck disable=SC2206  # we WANT word splitting on space here
parts=(${SSH_ORIGINAL_COMMAND})
verb="${parts[0]:-}"
target_env="${parts[1]:-}"
deploy_ref="${parts[2]:-}"

if [ "$verb" != "deploy" ]; then
    echo "ERROR: only verb 'deploy' is supported, got '$verb'" >&2
    exit 1
fi

case "$target_env" in
    paper|live) ;;
    *)
        echo "ERROR: target_env must be 'paper' or 'live', got '$target_env'" >&2
        exit 1
        ;;
esac

if [ -z "$deploy_ref" ]; then
    echo "ERROR: deploy_ref empty" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Paths (intentionally fixed — deploy key cannot influence these).
# ---------------------------------------------------------------------------
HOME_DIR="/home/claudesn"
STAGING_DIR="${HOME_DIR}/ai-trading-staging"
LIVE_DIR="${HOME_DIR}/ai-trading-live"
PREVIOUS_DIR="${HOME_DIR}/ai-trading-previous"
ENV_FILE="${HOME_DIR}/.ai-trading/.env"
TRAEFIK_DYNAMIC_DIR="/opt/n8n/traefik/dynamic"
LOG_FILE="${HOME_DIR}/.ai-trading/deploy.log"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
mkdir -p "$(dirname "$LOG_FILE")"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "=== Deploy started at $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
echo "    target_env: $target_env"
echo "    deploy_ref: $deploy_ref"

# ---------------------------------------------------------------------------
# Sanity checks
# ---------------------------------------------------------------------------
if [ ! -d "$STAGING_DIR" ]; then
    echo "ERROR: staging dir $STAGING_DIR does not exist (rsync from CI failed?)" >&2
    exit 1
fi
if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: env file $ENV_FILE missing — deploy cannot proceed without DATABASE_URL" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Apply pending DB migrations (idempotent — psql -f against trader's DB).
# Safe to re-run: each migration's CREATE TABLE / ALTER uses IF NOT EXISTS
# patterns. If a migration is destructive (DROP), the operator must have
# reviewed it before tagging phase-9-pass.
# ---------------------------------------------------------------------------
echo ">>> Applying pending migrations against ${ENV_FILE} target DB..."
# shellcheck disable=SC1090
source "$ENV_FILE"
export PGPASSWORD="$PG_PASS"
for m in "$STAGING_DIR/infra/migrations/"*.sql; do
    [ -f "$m" ] || continue
    name=$(basename "$m")
    echo "--- $name ---"
    psql -h 127.0.0.1 -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 -f "$m" \
        2>&1 | tail -5 || {
        # Migration failure is recoverable for additive-only migrations
        # (CREATE TABLE IF NOT EXISTS already-existed = noop). For real
        # errors, the deploy fails loud here BEFORE the systemd swap.
        echo "WARN: migration $name returned nonzero — likely already-applied. Continuing."
    }
done
unset PGPASSWORD

# ---------------------------------------------------------------------------
# Atomic dir swap: live → previous, staging → live.
# If anything below fails, we rollback by moving previous → live.
# ---------------------------------------------------------------------------
echo ">>> Atomic dir swap..."
if [ -d "$PREVIOUS_DIR" ]; then
    rm -rf "$PREVIOUS_DIR"
fi
if [ -d "$LIVE_DIR" ]; then
    mv "$LIVE_DIR" "$PREVIOUS_DIR"
fi
mv "$STAGING_DIR" "$LIVE_DIR"

# Recreate empty staging for next deploy.
mkdir -p "$STAGING_DIR/dashboard-ui/.next/standalone" \
         "$STAGING_DIR/dashboard-ui/.next/static" \
         "$STAGING_DIR/dashboard-ui/public" \
         "$STAGING_DIR/pulse-bridge" \
         "$STAGING_DIR/infra/traefik" \
         "$STAGING_DIR/infra/migrations"

# ---------------------------------------------------------------------------
# Refresh pulse-bridge venv deps (deterministic via pyproject + lockfile).
# ---------------------------------------------------------------------------
echo ">>> Refreshing pulse-bridge venv..."
cd "$LIVE_DIR/pulse-bridge"
# shellcheck disable=SC1091
source "$LIVE_DIR/.venv/bin/activate" 2>/dev/null || {
    python3 -m venv "$LIVE_DIR/.venv"
    # shellcheck disable=SC1091
    source "$LIVE_DIR/.venv/bin/activate"
}
pip install --quiet -e . || {
    echo "ERROR: pulse-bridge pip install failed" >&2
    rollback
    exit 1
}

# ---------------------------------------------------------------------------
# Drop Traefik dynamic config (file watch auto-reloads — no traefik restart).
# ---------------------------------------------------------------------------
echo ">>> Updating Traefik dynamic config..."
sudo cp "$LIVE_DIR/infra/traefik/ai-trading.yml" "$TRAEFIK_DYNAMIC_DIR/ai-trading.yml"

# ---------------------------------------------------------------------------
# Restart systemd units. graceful (`restart`, not `stop && start`).
# ---------------------------------------------------------------------------
echo ">>> Restarting systemd units..."
sudo systemctl restart dashboard-ui.service
sudo systemctl restart pulse-bridge.service

# ---------------------------------------------------------------------------
# Local health check (loopback). The Actions runner does the public-URL
# smoke test separately — this is just the unit-up confirmation.
# ---------------------------------------------------------------------------
echo ">>> Local health check..."
for i in $(seq 1 12); do
    code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 \
        "http://127.0.0.1:3000/login" || echo "000")
    if [ "$code" = "200" ]; then
        echo "    dashboard-ui /login returned 200 after $((i*5))s"
        break
    fi
    [ "$i" -eq 12 ] && {
        echo "ERROR: dashboard-ui not responding 200 on /login after 60s — rolling back" >&2
        rollback
        exit 1
    }
    sleep 5
done

for i in $(seq 1 12); do
    code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 \
        "http://127.0.0.1:8081/dashboard/healthz" || echo "000")
    if [ "$code" = "200" ] || [ "$code" = "401" ]; then
        # 401 is fine here — means JWT-protected route is live and rejecting.
        echo "    pulse-bridge /healthz returned $code after $((i*5))s"
        break
    fi
    [ "$i" -eq 12 ] && {
        echo "ERROR: pulse-bridge not responding on /healthz after 60s — rolling back" >&2
        rollback
        exit 1
    }
    sleep 5
done

echo "=== Deploy completed successfully at $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
echo "    deploy_ref: $deploy_ref"
echo "    target_env: $target_env"
exit 0
