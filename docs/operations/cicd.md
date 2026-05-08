# CI/CD runbook — AI-Trading

## Overview

Two GitHub Actions workflows + one VPS-side script.

```
┌──────────────────────────────────────────────────────────────────┐
│ ci.yml                       (always-on, every push + PR)         │
│   ├── python-tests           pytest tests/ pulse-bridge/tests/    │
│   ├── frontend-typecheck     tsc + eslint dashboard-ui            │
│   ├── iron-laws-audit        block PR if operator-only files diff │
│   └── (Iron Law 5 trigger re-asserted on ephemeral postgres)      │
│                                                                    │
│ deploy-cockpit.yml           (manual trigger, gated)              │
│   ├── gate-check             Phase 9 tag + ADR present?           │
│   ├── ci-revalidate          Re-run CI on this exact ref          │
│   └── deploy                 Build → rsync → SSH → systemd        │
│                                                                    │
│ ⛔ NO workflow for           crypto-bot/, freqtrade-fork/,         │
│                              freqtrade-config/, claude-routines/  │
│                              (Iron Law 4: operator-curated only)  │
└──────────────────────────────────────────────────────────────────┘
```

## Iron Law boundaries

- **Law 1** (risk rails): never overridden by CI/CD. The deploy script is
  read-only against `crypto-bot/freqtrade-config/config.json`.
- **Law 2** (no live trade without backtest): `deploy-cockpit.yml` refuses
  to fire unless an annotated tag matching `phase-9-pass-*` points at the
  deploy ref AND a corresponding ADR exists under `docs/decisions/`.
  Defence-in-depth: tag is easy to add by mistake; ADR forces a writeup.
- **Law 3** (no placeholder): both workflows install with `npm ci` and
  `pip install -e .` — deterministic from lockfile / pyproject. No `latest`
  tags, no silent fallback. Secrets are required, not defaulted.
- **Law 4** (operator-only files): `iron-laws-audit` job blocks any PR that
  diffs `CLAUDE.md`, applied migrations 000-006, `freqtrade-config/config.json`,
  `trading-discipline.md`, ADRs, or `references/`. These require operator
  direct-to-main commits.
- **Law 5** (memory append-only): CI re-asserts the `tg_journal_no_update` +
  `tg_journal_no_delete` triggers on every push. If a future migration drops
  them, CI fails loud.

## First-time setup (operator, ONE TIME before first deploy)

### 1. Create the dedicated deploy SSH key on VPS

```bash
ssh claudesn@31.97.188.145
ssh-keygen -t ed25519 -f ~/.ssh/deploy_key -N '' -C 'github-actions-deploy'

# Add the public key to authorized_keys WITH command lockdown:
echo 'command="/home/claudesn/bin/deploy-cockpit.sh",no-port-forwarding,no-X11-forwarding,no-pty,no-agent-forwarding '"$(cat ~/.ssh/deploy_key.pub)" \
    >> ~/.ssh/authorized_keys

# Capture the PRIVATE key (paste into GitHub Secrets, then delete locally):
cat ~/.ssh/deploy_key
# Save to GitHub: Settings → Secrets → Actions → VPS_SSH_PRIVATE_KEY
rm ~/.ssh/deploy_key

# Capture the host key fingerprint for known_hosts pinning:
ssh-keyscan -H 31.97.188.145 | base64 -w0
# Save to GitHub: VPS_SSH_KNOWN_HOSTS
```

### 2. Install the deploy script and dirs on VPS

```bash
ssh claudesn@31.97.188.145
mkdir -p ~/bin ~/ai-trading-staging
cd ~/ai-trading-live  # already cloned
cp infra/scripts/deploy-cockpit.sh ~/bin/deploy-cockpit.sh
chmod 700 ~/bin/deploy-cockpit.sh
```

### 3. Author + install systemd units (ONE TIME — depends on Phase 1.5.I deploy half)

These don't exist in the repo yet. Phase 1.5.I deploy half (deferred until
Phase 9 passes per `project_deploy_deferred_until_phase_9.md`) authors:

- `infra/systemd/dashboard-ui.service` — Next.js standalone, binds 127.0.0.1:3000
- `infra/systemd/pulse-bridge.service` — uvicorn FastAPI, binds 127.0.0.1:8081

When those exist:

```bash
sudo cp ~/ai-trading-live/infra/systemd/dashboard-ui.service /etc/systemd/system/
sudo cp ~/ai-trading-live/infra/systemd/pulse-bridge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable dashboard-ui pulse-bridge
```

### 4. Set GitHub repo secrets

In GitHub UI: **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Value | Purpose |
|---|---|---|
| `VPS_HOST` | `31.97.188.145` | rsync + ssh target |
| `VPS_USER` | `claudesn` | rsync + ssh user |
| `VPS_SSH_PRIVATE_KEY` | content of `~/.ssh/deploy_key` from step 1 | SSH auth (restricted-command key) |
| `VPS_SSH_KNOWN_HOSTS` | base64 of `ssh-keyscan -H 31.97.188.145` from step 1 | Pin VPS host key (MITM defense) |

### 5. Set GitHub Environment with manual approval

**Settings → Environments → New environment** for each of:

- `cockpit-paper` — required reviewer: operator's GitHub user
- `cockpit-live` — required reviewer: operator's GitHub user, deployment branches: `main` only

The deploy job in `deploy-cockpit.yml` references these via `environment.name` —
GitHub will pause the workflow with a "Review deployments" button.

### 6. Configure branch protection on `main`

**Settings → Branches → Add branch protection rule** for `main`:

- ☑ Require pull request before merging
- ☑ Require status checks to pass: `python-tests`, `frontend-typecheck`, `iron-laws-audit`
- ☑ Require branches to be up to date before merging
- ☑ Require linear history
- ☐ Allow force pushes (NEVER on main)
- Operator can still bypass for direct commits to operator-only files (admin override).

## How to deploy (after first-time setup)

### When Phase 9 passes

```bash
# 1. Operator runs walk-forward locally or on VPS, sees PASS verdict:
python -m infra.backtest.walk_forward --strategy-version v1.<chosen> ...
# Exit code 0, all 4 criteria green in all folds.

# 2. Operator authors the Phase 9 pass ADR:
gaspol-adr  # creates docs/decisions/YYYY-MM-DD-NNN-phase-9-pass-v1.0.md
#   with: strategy_version, per-fold metrics table, gate evaluator stdout,
#         operator sign-off, link to walk-forward run row in brain.backtest_runs.

# 3. Operator tags the commit:
git tag -a phase-9-pass-v1.0 -m "Walk-forward 5/5 PASS for strategy v1.0"
git push origin main
git push origin phase-9-pass-v1.0
```

### Trigger the deploy

GitHub UI: **Actions → Deploy cockpit → Run workflow**:

| Input | Value |
|---|---|
| Branch / tag | `phase-9-pass-v1.0` (the tag you pushed) |
| target_environment | `paper` (always start here, even if Phase 9 passed for live) |
| confirm_phase_9 | `YES_PHASE_9_GATE_GREEN` (exact match) |
| ref | `phase-9-pass-v1.0` |

GitHub will:

1. Run `gate-check` job → verify tag + ADR.
2. Run `ci-revalidate` job → re-run pytest + tsc + lint on this exact ref.
3. Pause for manual approval (GitHub Environment gate).
4. Run `deploy` job → build, rsync to VPS staging, trigger deploy script,
   atomic dir swap, systemctl restart, smoke test.

If smoke test fails, deploy script auto-rolls back to previous good build.

### After paper trade (3-4 weeks per Phase 10)

Repeat the deploy with `target_environment: live` after Phase 12 gate.

## Failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| `gate-check` fails: "tag missing" | Operator hasn't tagged or pushed tag | Run step 3 of "When Phase 9 passes" |
| `gate-check` fails: "ADR missing" | Tag pushed but no ADR file | Run step 2 of "When Phase 9 passes" |
| `confirm_phase_9` mismatch | Typo in input | Type exactly `YES_PHASE_9_GATE_GREEN` |
| `ci-revalidate` fails | Tests broke between last green CI and deploy ref | Fix tests, re-tag, re-deploy |
| `rsync` fails: "Permission denied" | SSH key lockdown rejecting rsync | Check `command=` in authorized_keys — rsync needs to be allowed (workflow uses scp internally; if so, rsync is fine because it's via ssh + `cd` is explicit) |
| Smoke test fails: 502 | systemd unit didn't come up | SSH manual: `journalctl -u dashboard-ui -n 50`. Deploy script should have rolled back automatically. |
| Smoke test fails: 404 | Traefik dynamic config not loaded | Check `/opt/n8n/traefik/dynamic/ai-trading.yml` exists, traefik logs for parse errors |
| Smoke test fails: 503 | DB unreachable from pulse-bridge | Check `~/.ai-trading/.env` DATABASE_URL, postgres is running |

## What CI/CD does NOT handle

- **Crypto-bot / strategy code changes**: operator-only via direct git pull on
  VPS after manual review. Never auto-deployed.
- **Migration rollbacks**: forward-only by design. Operator authors a new
  migration to undo. CI/CD applies migrations forward; never auto-rollbacks.
- **Postgres backups**: separate cron, separate concern. CI/CD assumes the
  operator has independent backup discipline.
- **Live $100 ramp gate (Phase 12)**: per-week drift gate is operator-driven.
  No CI workflow auto-graduates from paper → live.
- **Telegram alerts**: separate concern. The deploy script writes to
  `~/.ai-trading/deploy.log` for the operator's review.

## Adding workflow_call to ci.yml (one-time)

The deploy workflow's `ci-revalidate` job uses `uses: ./.github/workflows/ci.yml`.
For this to work, `ci.yml` needs `on: workflow_call:` added to its triggers.
First-time fix:

```yaml
on:
  push:
    ...
  pull_request:
    ...
  workflow_call:    # ← add this
```

This is intentionally not in the initial ci.yml so a future operator notices
and consciously enables reusability before the first deploy.
