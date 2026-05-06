# Bot Cockpit UI

Next.js 16 (App Router) + TypeScript + Tailwind 4 + TradingView Lightweight Charts.
Single-operator JWT auth (argon2id password hash). Tailscale-only access.

This is **sub-block 1.5.A** of the AI Trading 24/7 build — auth shell + protected
route stubs. Live data wires up in 1.5.B (TanStack Query) and 1.5.D (charts).

## Prerequisites

- **Node.js >= 22** (tested on 24.14). Install instructions per platform live in
  [`INSTALL_NOTES.md`](./INSTALL_NOTES.md).
- npm 10+ (ships with Node 22+).

## Setup

```bash
cd dashboard-ui
npm install
cp .env.example .env.local
# then edit .env.local — see "Configuring credentials" below
```

### Configuring credentials

All three variables are mandatory; the server throws on startup if any is missing.

1. Generate an argon2id password hash for the operator:
   ```bash
   node -e "require('./src/lib/password').hashPassword('YOUR_PASSWORD').then(console.log)"
   ```
2. Generate a JWT signing secret (>= 32 chars):
   ```bash
   node -e "console.log(require('node:crypto').randomBytes(48).toString('base64'))"
   ```
3. Populate `.env.local`:
   ```
   DASHBOARD_OPERATOR_USERNAME=ali
   DASHBOARD_OPERATOR_PASSWORD_ARGON2_HASH=$argon2id$v=19$...
   DASHBOARD_JWT_SECRET=<base64-string-from-step-2>
   ```

## Development

```bash
npm run dev      # http://127.0.0.1:3000
npm run build    # production build (output: 'standalone')
npm run start    # serve the production build
npm run lint
```

After `npm run build`, the systemd-friendly artifact lives at
`.next/standalone/server.js` (consumed by `infra/systemd/dashboard-ui.service`).

## End-to-end tests

```bash
npx playwright install chromium   # one-time
npm run test:e2e
```

The Playwright config injects test-only credentials and operates against the
production build (`npm run start`). Real argon2 verify runs against a real hash
in `playwright/fixtures/operator.json`. No mocked auth.

## Routes

| Path | Purpose | Status |
|---|---|---|
| `/login` | Operator sign-in (real JWT cookie) | Live (1.5.A) |
| `/dashboard` | Live equity + positions + brain feed | Stub (1.5.D) |
| `/strategy-lab` | Backtest + walk-forward visualizer | Stub (1.5.E) |
| `/journal` | Append-only brain journal feed | Stub (1.5.F) |
| `/freqai` | FreqAI feature importance + OOS error | Stub (1.5.G) |
| `/iteration-history` | Phase 9.5 iteration ledger | Stub (1.5.G2) |
| `/api/auth/login`, `/api/auth/logout` | JWT cookie session | Live |

`src/middleware.ts` redirects unauthenticated requests to `/login?next=<path>`.

## Iron Laws applied here

- **No mock data.** Auth verifies real argon2 hashes via real argon2, signs
  real JWTs via `jose`, and uses HTTP-only cookies. The login API route hits
  the same env vars production will read.
- **No silent defaults.** `src/lib/auth.ts` throws if any `DASHBOARD_*` env var
  is missing — the dashboard cannot start without explicit operator
  credentials. Do not "fix" by adding defaults.
- **Mocks only in `playwright/fixtures/`.** No mock auth in production code.
