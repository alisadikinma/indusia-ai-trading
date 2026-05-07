"""Phase 6 — daily FreqAI retrain health check.

Triggered by systemd timer (06:00 UTC). Reads brain.freqai_history rolling
7 days. If avg(auc) < 0.52 OR any single retrain auc < 0.50 → Telegram alert
+ log to iteration_runs. Otherwise silent (no news = good news).

Empty state (no rows yet — Phase 7 hasn't populated freqai_history): exit
0 with status='no_data'. No alert.

Iron Law 3 (anti-placeholder):
  * Real psycopg connection, real Telegram send_alert() call.
  * No silent env defaults — os.environ[...] raises KeyError on missing.
  * The only mock allowed is in tests via @patch.

Usage:
  python -m infra.scripts.retrain_health_check

Exit codes:
  0: status in {'green', 'no_data'}
  1: status in {'amber', 'red'}  (so systemd OnFailure=... could be wired)
"""
from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger("retrain_health_check")


# Status thresholds — explicit constants, no magic numbers in logic.
GREEN_AUC_AVG = 0.55
AMBER_AUC_AVG = 0.52
SINGLE_AUC_RED = 0.50
WINDOW_DAYS = 7


@dataclass
class HealthReport:
    avg_auc: float
    min_auc: float
    count: int
    status: str  # 'green' | 'amber' | 'red' | 'no_data'


# ---------------------------------------------------------------------------
# Postgres
# ---------------------------------------------------------------------------
def _postgres_dsn() -> str:
    return (
        f"postgresql://{os.environ['POSTGRES_USER']}:"
        f"{os.environ['POSTGRES_PASSWORD']}@"
        f"{os.environ['POSTGRES_HOST']}:"
        f"{os.environ['POSTGRES_PORT']}/"
        f"{os.environ['POSTGRES_DB']}"
    )


def _connect() -> Any:
    import psycopg
    return psycopg.connect(_postgres_dsn())


# ---------------------------------------------------------------------------
# Health computation
# ---------------------------------------------------------------------------
def compute_health(conn: Any, window_days: int = WINDOW_DAYS) -> HealthReport:
    """Read last N days from freqai_history; classify health."""
    sql = """
        SELECT AVG(auc)::float, MIN(auc)::float, COUNT(*)::int
        FROM brain.freqai_history
        WHERE retrained_at >= now() - (%s || ' days')::interval
    """
    with conn.cursor() as cur:
        cur.execute(sql, (str(window_days),))
        row = cur.fetchone()

    avg_auc, min_auc, count = row if row else (None, None, 0)
    if not count:
        return HealthReport(avg_auc=0.0, min_auc=0.0, count=0, status="no_data")

    avg_auc = float(avg_auc or 0.0)
    min_auc = float(min_auc or 0.0)

    # Red wins over amber if either condition triggers.
    if avg_auc < AMBER_AUC_AVG or min_auc < SINGLE_AUC_RED:
        status = "red"
    elif avg_auc < GREEN_AUC_AVG:
        status = "amber"
    else:
        status = "green"

    return HealthReport(avg_auc=avg_auc, min_auc=min_auc, count=count, status=status)


# ---------------------------------------------------------------------------
# Alerting
# ---------------------------------------------------------------------------
def alert_if_unhealthy(report: HealthReport) -> bool:
    """Send a Telegram alert iff status is amber or red. Returns True if sent."""
    if report.status not in {"amber", "red"}:
        return False

    # Real Telegram call — module hard-fails if env missing (which is the
    # correct production behaviour: silent failure on alerts is unacceptable).
    from infra.notifications.telegram import send_alert

    icon = {"amber": "WARN", "red": "RED"}[report.status]
    text = (
        f"<b>FreqAI retrain health: {icon}</b>\n"
        f"window: {WINDOW_DAYS}d, retrains: {report.count}\n"
        f"avg AUC: {report.avg_auc:.3f}\n"
        f"min AUC: {report.min_auc:.3f}\n"
        f"thresholds: green&gt;={GREEN_AUC_AVG:.2f} avg, "
        f"amber&gt;={AMBER_AUC_AVG:.2f} avg, "
        f"red if avg&lt;{AMBER_AUC_AVG:.2f} or min&lt;{SINGLE_AUC_RED:.2f}"
    )
    send_alert(text, parse_mode="HTML")
    return True


# ---------------------------------------------------------------------------
# iteration_runs logging
# ---------------------------------------------------------------------------
def log_run(conn: Any, report: HealthReport) -> int:
    sql = """
        INSERT INTO brain.iteration_runs (started_at, completed_at, run_type, summary, outcome)
        VALUES (now(), now(), 'health_check', %s, %s)
        RETURNING id
    """
    summary = json.dumps(asdict(report))
    outcome = "PASS" if report.status in {"green", "no_data"} else "FAIL_RETRY"
    with conn.cursor() as cur:
        cur.execute(sql, (summary, outcome))
        new_id = int(cur.fetchone()[0])
    conn.commit()
    return new_id


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    _postgres_dsn()  # eager validation

    try:
        with _connect() as conn:
            report = compute_health(conn)
            logger.info("health report: %s", report)
            sent = alert_if_unhealthy(report)
            log_run(conn, report)
    except Exception as exc:
        logger.exception("retrain_health_check failed: %s", exc)
        return 1

    if report.status in {"green", "no_data"}:
        logger.info("status=%s; no alert needed (sent=%s)", report.status, sent)
        return 0
    logger.warning("status=%s; alert sent=%s", report.status, sent)
    return 1


if __name__ == "__main__":
    sys.exit(main())
