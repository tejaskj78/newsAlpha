"""Background worker. Run standalone with `python -m app.worker`, or embedded in the API."""

import logging
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.blocking import BlockingScheduler

from app.config import get_settings
from app.db import init_engine
from app.jobs import Jobs

log = logging.getLogger(__name__)


def configure(scheduler, jobs: Jobs) -> None:
    s = jobs.settings
    now = datetime.now(UTC)
    # Prices first, news shortly after so the first signals have technicals available
    scheduler.add_job(
        jobs.price_cycle,
        "interval",
        minutes=s.price_interval_minutes,
        next_run_time=now,
        id="prices",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        jobs.news_cycle,
        "interval",
        minutes=s.news_interval_minutes,
        next_run_time=now + timedelta(seconds=20),
        id="news",
        max_instances=1,
        coalesce=True,
    )
    # Re-score hourly even without new news: decay makes old news fade, prices move
    scheduler.add_job(
        jobs.signal_cycle,
        "interval",
        minutes=60,
        next_run_time=now + timedelta(minutes=5),
        id="signals",
        max_instances=1,
        coalesce=True,
    )


def start_background(jobs: Jobs | None = None) -> BackgroundScheduler:
    sched = BackgroundScheduler(timezone="UTC")
    configure(sched, jobs or Jobs())
    sched.start()
    return sched


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    init_engine(get_settings().database_url)
    sched = BlockingScheduler(timezone="UTC")
    configure(sched, Jobs())
    log.info("worker started")
    sched.start()


if __name__ == "__main__":
    main()
