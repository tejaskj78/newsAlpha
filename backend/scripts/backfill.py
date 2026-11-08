"""Backfill historical prices + news so the backtester has something to chew on.

    python -m scripts.backfill --days 60

GDELT keeps ~3 months of article history in the DOC API, so --days above ~90 only adds prices.
Fetching is slow on purpose (GDELT asks for one request every 5 seconds).
"""

import argparse
import logging
from datetime import UTC, datetime, timedelta

from app.config import get_settings
from app.db import init_engine, session_scope
from app.ingestion.gdelt import GdeltSource
from app.ingestion.pipeline import ingest_articles
from app.jobs import Jobs

log = logging.getLogger("backfill")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--window-hours", type=int, default=24)
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = get_settings()
    init_engine(settings.database_url)
    jobs = Jobs(settings)

    log.info("refreshing prices: %s", jobs.price_cycle())

    gdelt = GdeltSource(jobs.universe, max_records=250)
    end = datetime.now(UTC)
    start = end - timedelta(days=args.days)
    cursor = start
    total = 0
    while cursor < end:
        nxt = min(cursor + timedelta(hours=args.window_hours), end)
        raw = gdelt.fetch(start=cursor, end=nxt)
        with session_scope() as s:
            stats = ingest_articles(s, raw, jobs.linker, jobs.sentiment, settings.dedup_hamming_threshold, now=nxt)
        total += stats.stored
        log.info("%s -> %s: fetched %d, stored %d", cursor.date(), nxt.date(), stats.fetched, stats.stored)
        cursor = nxt
    log.info("done, stored %d articles; generating signals", total)
    jobs.signal_cycle()


if __name__ == "__main__":
    main()
