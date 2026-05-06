#!/usr/bin/env bash
# AI Trading 24/7 — VPS provisioning script (Phase 1 deployment).
#
# Idempotent. Run on a fresh Hetzner CX22 Ubuntu 24.04 VPS as root.
# After completion, log out and SSH back in as 'trader' for normal ops.
#
# Usage:
#   ssh root@<vps-public-ip>
#   curl -O https://raw.githubusercontent.com/<org>/<repo>/main/infra/scripts/provision_vps.sh
#   chmod +x provision_vps.sh
#   ./provision_vps.sh <github-repo-url> <tailscale-auth-key>
#
# Out-of-band prerequisites (operator must do these BEFORE running this script):
#   1. Provision Hetzner CX22 in Frankfurt (FSN1 datacenter), Ubuntu 24.04.
#      - 2 vCPU AMD, 4GB RAM, 40GB SSD
#      - Add SSH public key during provisioning
#      - Note the public IPv4 address
#   2. Generate a Tailscale auth key:
#      https://login.tailscale.com/admin/settings/keys → "Generate auth key"
#      Mark as "Reusable: no", "Ephemeral: no", "Tags: tag:trading-bot"
#   3. Create a Telegram bot:
#      Telegram → @BotFather → /newbot → save token
#      Send any message to bot from your account → curl getUpdates → grab user_id
#   4. (Optional, for DNS) point a hostname like trading.example.com at VPS IP.

set -euo pipefail

REPO_URL="${1:?Usage: $0 <github-repo-url> <tailscale-auth-key>}"
TAILSCALE_AUTHKEY="${2:?Usage: $0 <github-repo-url> <tailscale-auth-key>}"
INSTALL_DIR="/opt/ai-trading"
DEPLOY_USER="trader"

echo "==> [1/9] System update + base packages"
DEBIAN_FRONTEND=noninteractive apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    ca-certificates curl gnupg lsb-release \
    git build-essential pkg-config \
    python3.12 python3.12-venv python3-pip \
    postgresql-client \
    ufw fail2ban \
    jq make

echo "==> [2/9] UFW firewall — allow SSH only (Tailscale handles UI access)"
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment 'SSH'
# Tailscale interface gets full access (UI ports reachable through it)
ufw allow in on tailscale0
ufw --force enable
ufw status verbose

echo "==> [3/9] Install Tailscale + join tailnet"
if ! command -v tailscale &> /dev/null; then
    curl -fsSL https://tailscale.com/install.sh | sh
fi
tailscale up --authkey="${TAILSCALE_AUTHKEY}" --hostname="ai-trading-frankfurt" --ssh
TAILSCALE_IP=$(tailscale ip -4 | head -1)
echo "    Tailscale IP: ${TAILSCALE_IP}"

echo "==> [4/9] Install Docker + docker compose"
if ! command -v docker &> /dev/null; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable --now docker
fi

echo "==> [5/9] Install Node.js 22 (for dashboard-ui)"
if ! command -v node &> /dev/null || [[ "$(node --version)" != v22* ]]; then
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
    apt-get install -y -qq nodejs
fi

echo "==> [6/9] Create deploy user + directories"
if ! id "${DEPLOY_USER}" &> /dev/null; then
    useradd -m -s /bin/bash -G docker "${DEPLOY_USER}"
fi
mkdir -p "${INSTALL_DIR}" "${INSTALL_DIR}/logs" /run/pulse
chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "${INSTALL_DIR}" /run/pulse

echo "==> [7/9] Clone repo (or fast-forward if already present)"
if [ ! -d "${INSTALL_DIR}/.git" ]; then
    sudo -u "${DEPLOY_USER}" git clone --recurse-submodules "${REPO_URL}" "${INSTALL_DIR}"
else
    sudo -u "${DEPLOY_USER}" git -C "${INSTALL_DIR}" fetch --all --prune
    sudo -u "${DEPLOY_USER}" git -C "${INSTALL_DIR}" pull --ff-only
    sudo -u "${DEPLOY_USER}" git -C "${INSTALL_DIR}" submodule update --init --recursive
fi

echo "==> [8/9] Python venv + project deps"
sudo -u "${DEPLOY_USER}" python3.12 -m venv "${INSTALL_DIR}/.venv"
sudo -u "${DEPLOY_USER}" "${INSTALL_DIR}/.venv/bin/pip" install --upgrade pip
sudo -u "${DEPLOY_USER}" "${INSTALL_DIR}/.venv/bin/pip" install -e "${INSTALL_DIR}[dev]"
# Freqtrade deps:
sudo -u "${DEPLOY_USER}" "${INSTALL_DIR}/.venv/bin/pip" install -e "${INSTALL_DIR}/freqtrade-fork[freqai]"

echo "==> [9/9] Install systemd units"
install -m 0644 -o root -g root "${INSTALL_DIR}/infra/systemd/freqtrade.service" /etc/systemd/system/
install -m 0644 -o root -g root "${INSTALL_DIR}/infra/systemd/pulse-bridge.service" /etc/systemd/system/
install -m 0644 -o root -g root "${INSTALL_DIR}/infra/systemd/dashboard-api.service" /etc/systemd/system/
install -m 0644 -o root -g root "${INSTALL_DIR}/infra/systemd/dashboard-ui.service" /etc/systemd/system/
systemctl daemon-reload

echo ""
echo "============================================================"
echo "  Provisioning complete."
echo ""
echo "  Tailscale IP: ${TAILSCALE_IP}"
echo "  Install dir:  ${INSTALL_DIR}"
echo "  Deploy user:  ${DEPLOY_USER}"
echo ""
echo "  Next manual steps (operator):"
echo "    1. Edit ${INSTALL_DIR}/.env with real values from"
echo "       infra/secrets/.env.example template"
echo "    2. cd ${INSTALL_DIR}/infra && docker compose up -d"
echo "    3. psql trading -f migrations/000_bootstrap_schemas.sql"
echo "    4. systemctl enable --now pulse-bridge dashboard-api dashboard-ui"
echo "       (Do NOT enable freqtrade.service until Phase 9 backtest passes)"
echo "    5. From operator laptop: tailscale up; visit http://${TAILSCALE_IP}:3000"
echo "============================================================"
