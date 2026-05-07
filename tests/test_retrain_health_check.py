"""Phase 6 — retrain health check tests.

Covers ``infra.scripts.retrain_health_check`` — the daily cron that reads
last 7 days of brain.freqai_history, classifies AUC health, and Telegram-
alerts on amber/red. Empty state must silently exit 0.

Mocking policy (Iron Law 3): the only mock allowed is the Telegram
``send_alert`` — real Telegram messages would spam the operator during CI.
DB writes are integration tests against real Postgres.
"""
from __future__ import annotations

import os
from typing import Any
from unittest.mock import patch

import pytest


def _postgres_dsn() -> str:
    return (
        f"postgresql://{os.environ['POSTGRES_USER']}:"
        f"{os.environ['POSTGRES_PASSWORD']}@"
        f"{os.environ['POSTGRES_HOST']}:"
        f"{os.environ['POSTGRES_PORT']}/"
        f"{os.environ['POSTGRES_DB']}"
    )


@pytest.fixture
def freqai_conn():
    """Real psycopg conn against trading DB. Cleans freqai_history rows it inserts."""
    psycopg = pytest.importorskip("psycopg")
    conn = psycopg.connect(_postgres_dsn())
    conn.autocommit = False
    yield conn
    # Always rollback — tests insert via this conn so rollback wipes them.
    conn.rollback()
    conn.close()


def _insert(cur: Any, *, auc: float, days_ago: int = 0) -> None:
    cur.execute(
        """
        INSERT INTO brain.freqai_history (retrained_at, pair, tf, train_window_days,
                                          train_rows, auc, model_path, notes)
        VALUES (now() - (%s || ' days')::interval,
                'BTC/USDT', '15m', 90, 100000, %s, '/tmp/m.pkl', 'phase6 fixture')
        """,
        (str(days_ago), auc),
    )


@pytest.mark.integration
def test_compute_health_no_data_returns_no_data_status(freqai_conn) -> None:
    from infra.scripts.retrain_health_check import compute_health
    # Use a tiny window so existing real rows (if any) get excluded reliably.
    # If no rows in window, status='no_data'.
    cur = freqai_conn.cursor()
    cur.execute("SELECT COUNT(*) FROM brain.freqai_history WHERE retrained_at >= now() - interval '7 days'")
    cnt = cur.fetchone()[0]
    if cnt > 0:
        pytest.skip(
            "freqai_history already has real rows in the 7d window; "
            "no_data path can only be tested on a clean DB."
        )
    report = compute_health(freqai_conn)
    assert report.status == "no_data"
    assert report.count == 0


@pytest.mark.integration
def test_compute_health_green_when_avg_above_055(freqai_conn) -> None:
    from infra.scripts.retrain_health_check import compute_health
    cur = freqai_conn.cursor()
    for d in (1, 2, 3):
        _insert(cur, auc=0.60, days_ago=d)
    report = compute_health(freqai_conn)
    assert report.status == "green", f"expected green, got {report}"
    assert abs(report.avg_auc - 0.60) < 1e-9
    assert report.count >= 3


@pytest.mark.integration
def test_compute_health_amber_when_avg_between_052_055(freqai_conn) -> None:
    from infra.scripts.retrain_health_check import compute_health
    cur = freqai_conn.cursor()
    # 0.53 is between 0.52 and 0.55 → amber. Must avoid any row < 0.50 to skip red.
    for d in (1, 2, 3):
        _insert(cur, auc=0.53, days_ago=d)
    report = compute_health(freqai_conn)
    assert report.status == "amber", f"expected amber, got {report}"


@pytest.mark.integration
def test_compute_health_red_when_avg_below_052(freqai_conn) -> None:
    from infra.scripts.retrain_health_check import compute_health
    cur = freqai_conn.cursor()
    for d in (1, 2, 3):
        _insert(cur, auc=0.51, days_ago=d)
    report = compute_health(freqai_conn)
    assert report.status == "red"


@pytest.mark.integration
def test_compute_health_red_when_any_single_below_050(freqai_conn) -> None:
    from infra.scripts.retrain_health_check import compute_health
    cur = freqai_conn.cursor()
    _insert(cur, auc=0.55, days_ago=1)
    _insert(cur, auc=0.55, days_ago=2)
    _insert(cur, auc=0.45, days_ago=3)  # single dip → red
    report = compute_health(freqai_conn)
    assert report.status == "red"


def test_alert_if_unhealthy_skips_for_green() -> None:
    from infra.scripts.retrain_health_check import HealthReport, alert_if_unhealthy
    report = HealthReport(avg_auc=0.62, min_auc=0.6, count=5, status="green")
    with patch("infra.notifications.telegram.send_alert") as send_alert:
        sent = alert_if_unhealthy(report)
    assert sent is False
    send_alert.assert_not_called()


def test_alert_if_unhealthy_skips_for_no_data() -> None:
    from infra.scripts.retrain_health_check import HealthReport, alert_if_unhealthy
    report = HealthReport(avg_auc=0.0, min_auc=0.0, count=0, status="no_data")
    with patch("infra.notifications.telegram.send_alert") as send_alert:
        sent = alert_if_unhealthy(report)
    assert sent is False
    send_alert.assert_not_called()


def test_alert_if_unhealthy_calls_for_amber() -> None:
    from infra.scripts.retrain_health_check import HealthReport, alert_if_unhealthy
    report = HealthReport(avg_auc=0.53, min_auc=0.51, count=5, status="amber")
    with patch("infra.notifications.telegram.send_alert") as send_alert:
        sent = alert_if_unhealthy(report)
    assert sent is True
    send_alert.assert_called_once()


def test_alert_if_unhealthy_calls_for_red() -> None:
    from infra.scripts.retrain_health_check import HealthReport, alert_if_unhealthy
    report = HealthReport(avg_auc=0.45, min_auc=0.40, count=5, status="red")
    with patch("infra.notifications.telegram.send_alert") as send_alert:
        sent = alert_if_unhealthy(report)
    assert sent is True
    send_alert.assert_called_once()


@pytest.mark.integration
def test_log_run_inserts_iteration_runs(freqai_conn) -> None:
    from infra.scripts.retrain_health_check import HealthReport, log_run
    report = HealthReport(avg_auc=0.6, min_auc=0.55, count=3, status="green")
    new_id = log_run(freqai_conn, report)
    assert isinstance(new_id, int) and new_id > 0
    cur = freqai_conn.cursor()
    cur.execute(
        "SELECT run_type, outcome, summary FROM brain.iteration_runs WHERE id=%s",
        (new_id,),
    )
    run_type, outcome, summary = cur.fetchone()
    assert run_type == "health_check"
    assert outcome == "PASS"
    assert "avg_auc" in summary
