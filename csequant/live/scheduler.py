"""Periodic end-of-day refresh of the data cache (and, implicitly, signals).

Run it as a long-lived process:

    python -m csequant.live.scheduler --hour 18 --minute 30

Uses APScheduler if installed, otherwise a dependency-free sleep loop. The CSE
trades end-of-day, so a single daily run after the close is sufficient; intraday
history is not available from the source (see README §Data).
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timedelta

from .. import pipeline
from ..config import load_config
from ..logging_conf import get_logger, setup_logging

log = get_logger(__name__)


def refresh_once(cfg=None):
    """Fetch + cache the latest EOD data once. Returns the coverage frame."""
    cfg = cfg or load_config()
    cov = pipeline.build_cache(cfg)
    n = len(cov) if cov is not None and not cov.empty else 0
    log.info("EOD refresh complete: %d tickers cached", n)
    return cov


def _seconds_until(hour: int, minute: int) -> float:
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def run_scheduler(hour: int = 18, minute: int = 30, weekdays_only: bool = True) -> None:
    """Block forever, refreshing the cache once per day at HH:MM."""
    cfg = load_config()
    setup_logging(cfg.get("logging.level", "INFO"), cfg.path("logging.file"))

    # Prefer APScheduler when available; fall back to a plain loop.
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler  # type: ignore
        from apscheduler.triggers.cron import CronTrigger  # type: ignore

        sched = BlockingScheduler()
        dow = "mon-fri" if weekdays_only else "*"
        sched.add_job(lambda: refresh_once(cfg),
                      CronTrigger(day_of_week=dow, hour=hour, minute=minute))
        log.info("APScheduler: EOD refresh %s at %02d:%02d", dow, hour, minute)
        sched.start()
        return
    except Exception:
        log.info("APScheduler unavailable — using a simple sleep loop")

    log.info("Scheduler started: daily EOD refresh at %02d:%02d", hour, minute)
    try:
        while True:
            time.sleep(_seconds_until(hour, minute))
            if weekdays_only and datetime.now().weekday() >= 5:
                continue
            try:
                refresh_once(cfg)
            except Exception as e:  # keep the loop alive on transient failures
                log.error("EOD refresh failed: %s", e)
            time.sleep(60)  # avoid double-firing within the same minute
    except KeyboardInterrupt:
        log.info("Scheduler stopped")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="csequant EOD scheduler")
    ap.add_argument("--hour", type=int, default=18)
    ap.add_argument("--minute", type=int, default=30)
    ap.add_argument("--once", action="store_true", help="refresh once and exit")
    ap.add_argument("--all-days", action="store_true", help="run on weekends too")
    args = ap.parse_args(argv)
    if args.once:
        refresh_once()
        return 0
    run_scheduler(args.hour, args.minute, weekdays_only=not args.all_days)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
