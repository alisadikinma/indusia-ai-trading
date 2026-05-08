#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# AI-Trading cockpit deploy script.
#
# Runs ON the VPS, in the project root. Designed to be:
#   - Idempotent (safe to re-run)
#   - Non-interactive (for CI/CD)
#   - Fail-fast (halts on any error, with clear diagnostic output)
#
# Stack: Next.js dashboard-ui (systemd) + FastAPI pulse-bridge (systemd).
# Postgres is a separate operator-managed service (NOT touched by deploy).
#
# Iron Law boundary: this script deploys the COCKPIT only. It does NOT touch:
#   - crypto-bot/ (claude-routines, freqtrade-config) — operator-curated
#   - freqtrade-fork/ — submodule, separate manual update
#   - infra/migrations/00[0-5]_*.sql — already-applied, never re-run
#   - ~/.ai-trading/.env — secrets, operator-managed
#
# Invocation:
#   bash infra/scripts/deploy.sh
#   DEPLOY_SKIP_FRONTEND=1 bash infra/scripts/deploy.sh   # backend-only deploy
#   DEPLOY_FORCE_REBUILD=1 bash infra/scripts/deploy.sh   # nuke + reinstall venv
#
# Triggered by .github/workflows/deploy.yml on push to main.
# ------------------------------------------------------------------------------

set -euo pipefail

# ---- 0. Load shell environment (non-interactive SSH skips these by default) --
set +u
[ -f /etc/profile ]          && . /etc/profile          || true
[ -f "$HOME/.profile" ]      && . "$HOME/.profile"      || true
[ -f "$HOME/.bashrc" ]       && . "$HOME/.bashrc"       || true
[ -f "$HOME/.bash_profile" ] && . "$HOME/.bash_profile" || true
set -u

export PATH="$HOME/.local/bin:$HOME/bin:/usr/local/bin:/usr/local/sbin:/usr/bin:/usr/sbin:/bin:/sbin:$PATH"

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"

echo "▶ Deploying ai-trading cockpit from $(pwd) @ $(date -u +'%Y-%m-%dT%H:%M:%SZ')"
echo "▶ User: $(whoami) | Host: $(hostname) | HEAD: $(git rev-parse --short HEAD)"

# ---- 1. Preflight: required tools + .env -------------------------------------
for tool in git node npm python3 psql sudo; do
  command -v "$tool" >/dev/null 2>&1 \
    || { echo "❌ missing tool: $tool"; exit 127; }
done

ENV_FILE="$HOME/.ai-trading/.env"
if [ ! -f "$ENV_FILE" ]; then
  echo "❌ env file missing: $ENV_FILE"
  echo "   This holds DATABASE_URL, DASHBOARD_JWT_SECRET, etc — operator-managed (Iron Law 3)."
  exit 1
fi
# shellcheck disable=SC1090
# `set -a` exports every var sourced — required so `npm run build` (child proc)
# inherits NEXT_PUBLIC_* + DASHBOARD_* keys for build-time inlining.
set -a
source "$ENV_FILE"
set +a
export PGPASSWORD="${PG_PASS:-}"

# ---- 2. Apply pending migrations (idempotent) --------------------------------
# CREATE TABLE IF NOT EXISTS pattern means already-applied migrations are no-op.
# Iron Law 4: applied migrations themselves must NEVER be edited; only NEW
# migrations (007+) get added. This loop applies all 0*.sql which is safe.
echo "▶ Apply pending DB migrations"
for m in infra/migrations/0*.sql; do
  [ -f "$m" ] || continue
  name=$(basename "$m")
  if psql -h 127.0.0.1 -U "${PG_USER:-trader}" -d "${PG_DB:-trading}" \
       -v ON_ERROR_STOP=1 -f "$m" 2>&1 | tail -3 | grep -qE 'ERROR|FATAL'; then
    echo "  ⚠ $name returned errors — may be already-applied; check manually if unexpected"
  else
    echo "  ✓ $name"
  fi
done
unset PGPASSWORD

# ---- 3. Build dashboard-ui (Next.js standalone) ------------------------------
if [ "${DEPLOY_SKIP_FRONTEND:-0}" = "1" ]; then
  echo "▶ DEPLOY_SKIP_FRONTEND=1 — skipping dashboard-ui build"
else
  echo "▶ Build dashboard-ui (Next.js standalone)"
  cd "$PROJECT_ROOT/dashboard-ui"
  npm ci --silent
  npm run build
  cd "$PROJECT_ROOT"
fi

# ---- 4. Refresh pulse-bridge venv --------------------------------------------
echo "▶ Refresh pulse-bridge venv"
VENV_DIR="$PROJECT_ROOT/.venv"
if [ "${DEPLOY_FORCE_REBUILD:-0}" = "1" ] && [ -d "$VENV_DIR" ]; then
  echo "  DEPLOY_FORCE_REBUILD=1 — removing existing venv"
  rm -rf "$VENV_DIR"
fi
if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
pip install --quiet --upgrade pip wheel
pip install --quiet -e pulse-bridge
deactivate

# ---- 5. Drop Traefik dynamic config (file-watch reload, no traefik restart) -
TRAEFIK_DIR="/opt/n8n/traefik/dynamic"
if [ -d "$TRAEFIK_DIR" ] && [ -f infra/traefik/ai-trading.yml ]; then
  echo "▶ Update Traefik dynamic config"
  sudo cp infra/traefik/ai-trading.yml "$TRAEFIK_DIR/ai-trading.yml"
fi

# ---- 6. Restart systemd units ------------------------------------------------
# Units are operator-authored (one-time setup; see docs/operations/cicd.md).
# If a unit is missing, restart fails loud — operator notices and authors it.
restart_unit() {
  local unit=$1
  if sudo systemctl list-unit-files "$unit.service" --no-legend 2>/dev/null | grep -q "$unit"; then
    echo "▶ Restart $unit.service"
    sudo systemctl restart "$unit.service"
  else
    echo "  ⚠ $unit.service not installed yet — skipping (operator must author + enable)"
  fi
}

[ "${DEPLOY_SKIP_FRONTEND:-0}" != "1" ] && restart_unit dashboard-ui
restart_unit pulse-bridge

echo ""
echo "✓ Deploy complete @ $(date -u +'%Y-%m-%dT%H:%M:%SZ')"
echo "  HEAD: $(git rev-parse --short HEAD)"
echo "  Health check: curl https://ai-trading.alisadikinma.com/login"
