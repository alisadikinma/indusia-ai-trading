# `freqtrade-config/` — Custom strategy + config (parent-tracked)

This directory holds our strategy code, config template, and backtest data
files. It lives at the repo root (not inside `freqtrade-fork/user_data/`)
because Freqtrade upstream's `.gitignore` excludes `user_data/*` — files there
would not be tracked by either repo. Keeping them here in the parent repo
gives us clean version control and simple deployment.

Freqtrade is invoked with explicit `--strategy-path` and `--config` flags
pointing at this directory; see `infra/systemd/freqtrade.service` for the
production invocation pattern.

## Layout

```
freqtrade-config/
├── strategies/
│   ├── __init__.py
│   └── ClaudeOversightStrategy.py   <- Phase 3 v1 strategy
├── data/
│   └── binance/                     <- Feather OHLCV files for backtests
│       └── BTC_USDT-15m.feather     <- exported from brain.ohlcv
├── config.json                      <- committed template (no secrets)
└── README.md                        <- this file
```

## Strategy: `ClaudeOversightStrategy`

Trend-following v1: EMA20 / EMA50 cross + ADX(14) > 25 + 2×ATR(14) trailing
stop. See the module docstring for the full rule set.

The strategy does three Phase-3 things:

1. Generates entry/exit signals deterministically from indicators.
2. On every confirmed entry, writes a row to `brain.signals` (Postgres) so
   the dashboard WebSocket fan-out (Phase 1.5.C) sees it in real time.
3. Implements a `custom_stoploss` that uses the latest ATR(14) to trail the
   stop at 2× ATR below the high-water mark — the bot-side enforcement of
   Iron Law 1's "per-trade stop-loss: 2× ATR(14) trailing" rail.

Phase 4 will replace `confirm_trade_entry` to additionally call the PULSE
bridge for Claude's approve/veto/resize verdict before allowing the trade.
Phase 7 will wire FreqAI predictions in.

## Configuration

The committed `config.json` is a template:

* `dry_run: true` — Iron Law 2: no live trade until Phase 12 sign-off.
* `db_url` points at the local Postgres (port 5544) using SQLAlchemy psycopg3
  syntax: `postgresql+psycopg://...`. Override the password at runtime.
* All exchange / Telegram / API-server credentials are blank — fill them in
  at runtime via a local override file (see below) or systemd
  `EnvironmentFile=`.

### Local development overrides

```bash
cp freqtrade-config/config.json freqtrade-config/config.local.json
# Edit freqtrade-config/config.local.json — set real Postgres password,
# Telegram token (if testing notifications), API server password, etc.
```

`freqtrade-config/config.local.json` is gitignored. Run Freqtrade against it:

```bash
freqtrade backtesting --config freqtrade-config/config.local.json \
    --strategy ClaudeOversightStrategy \
    --timerange 20240101-20240131 --pair BTC/USDT
```

## Generating backtest data

Freqtrade reads OHLCV from `freqtrade-config/data/<exchange>/<PAIR>-<tf>.feather`.
Our canonical OHLCV store is the `brain.ohlcv` Postgres table. The bridge
script lives at `infra/scripts/export_freqtrade_data.py`:

```bash
# from repo root, with .env loaded:
set -a && source .env && set +a
python infra/scripts/export_freqtrade_data.py \
    --pair BTC/USDT --tf 15m --resample-from 1m \
    --start 2024-01-01 --end 2024-02-01 \
    --datadir freqtrade-fork/freqtrade-config/data
```

`--resample-from 1m` is needed because Phase 2 only loaded 1-minute candles;
the script aggregates them on the fly into the requested target timeframe.

## Postgres write path

`ClaudeOversightStrategy._write_signal_to_brain` opens a lazy psycopg
connection from `POSTGRES_HOST` / `POSTGRES_PORT` / `POSTGRES_DB` /
`POSTGRES_USER` / `POSTGRES_PASSWORD` env vars (hard-fail on missing — Iron
Law 3, no silent default). The connection is reused across calls behind a
thread lock; Freqtrade may invoke strategy callbacks from worker threads.

The `brain.signals` `AFTER INSERT` trigger
(`infra/migrations/002_pg_notify_triggers.sql`) fires `pg_notify
('dashboard_signals', payload)` automatically — UI WS clients see the
signal in real time.

### Failure policy

If the Postgres write fails, `confirm_trade_entry` returns `False` and the
trade is blocked. We are paper-trade-only at this phase (Iron Law 2); losing
journal visibility is worse than missing one signal. A live-mode operator
will revisit this default once Phase 10 paper-trading clears.
