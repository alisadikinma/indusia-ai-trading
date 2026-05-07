# pulse-bridge

FastAPI shim — two routers in one app:

- `/v1/*` — Claude Code CLI ↔ Freqtrade bridge (Phase 4 owns `pulse_bridge/main.py`).
- `/dashboard/*` — Read-only API consumed by `dashboard-ui` (Phase 1.5.B/C, this package).

## Install (editable)

```bash
cd pulse-bridge
pip install -e ".[dev]"
```

## Run dashboard API

```bash
set -a; source ../.env; set +a
uvicorn pulse_bridge.dashboard_main:app --host 127.0.0.1 --port 8081
```

## Tests

```bash
pytest tests/ -v
```

Tests run against the real Postgres on `127.0.0.1:5544` configured via `../.env`.
