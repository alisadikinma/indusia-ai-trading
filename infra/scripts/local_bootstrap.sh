#!/usr/bin/env bash
# Local development bootstrap — bring up Postgres + apply bootstrap migration.
# Run from repo root after docker compose up:
#   bash infra/scripts/local_bootstrap.sh
#
# Idempotent — safe to re-run.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env"

if [ ! -f "${ENV_FILE}" ]; then
    echo "Missing ${ENV_FILE} — copy infra/secrets/.env.example to .env and fill in values" >&2
    exit 1
fi

# shellcheck disable=SC1090
set -a; source "${ENV_FILE}"; set +a

echo "==> Waiting for postgres healthcheck..."
until docker ps --filter "name=ai-trading-postgres" --format '{{.Status}}' | grep -q healthy; do
    sleep 2
done
echo "    Postgres healthy."

echo "==> Applying bootstrap migration (000_bootstrap_schemas.sql)..."
docker exec -i ai-trading-postgres \
    psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -v ON_ERROR_STOP=1 \
    < "${REPO_ROOT}/infra/migrations/000_bootstrap_schemas.sql"

echo "==> Verifying schema..."
docker exec ai-trading-postgres \
    psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "\dt brain.*"

echo ""
echo "==> Local bootstrap complete."
echo "    DSN: postgresql://${POSTGRES_USER}:****@127.0.0.1:5432/${POSTGRES_DB}"
echo "    Run: pytest tests/integration/ -v"
