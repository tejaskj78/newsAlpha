"""Seed the database with SYNTHETIC data so the dashboard works offline (no network, no API keys).

    python -m scripts.seed_demo

Every demo article uses the source "demo.local" and an https://demo.local/ URL so it can
never be confused with real news. Delete the database file to start fresh with real data.
"""

import logging
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd

from app.config import get_settings
from app.db import init_engine, session_scope
from app.ingestion.base import RawArticle
from app.ingestion.pipeline import ingest_articles
from app.jobs import Jobs
from app.market.prices import upsert_bars

DEMO_HEADLINES = [
    ("Infosys bags record $2 billion deal from European bank, shares surge", 2),
    ("TCS beats estimates as deal wins rise for third straight quarter", 5),
    ("Oil prices jump after OPEC+ cut extends into next year", 3),
    ("Nvidia shares rally as AI demand from data center customers grows", 1),
    ("Tesla recalls 120,000 vehicles over steering fault", 8),
    ("Tesla faces probe over driver assistance crashes", 20),
    ("HDFC Bank profit rises 18%, asset quality robust", 12),
    ("Rupee falls to record low against the dollar", 6),
    ("Sun Pharma receives USFDA warning letter for Gujarat plant", 9),
    ("Lockheed Martin wins $4 billion missile defense contract", 15),
    ("Missile strike raises geopolitical tensions in the Middle East", 4),
    ("Apple misses estimates as iPhone sales decline in China", 10),
    ("Microsoft Azure growth tops expectations, stock climbs", 7),
    ("US announces new tariffs on imported semiconductors", 30),
    ("Maruti Suzuki reports strong festive season sales growth", 26),
]


def synthetic_prices(seed: int, n: int = 260, start: float = 1000.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = start * np.cumprod(1 + rng.normal(0.0004, 0.015, n))
    days = pd.bdate_range(end=date.today(), periods=n).date
    return pd.DataFrame(
        {"open": close, "high": close * 1.01, "low": close * 0.99, "close": close, "volume": 1e6}, index=days
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    init_engine(settings.database_url)
    jobs = Jobs(settings, sources=[])
    now = datetime.now(UTC)
    with session_scope() as s:
        for i, t in enumerate(jobs.tickers):
            upsert_bars(s, t, synthetic_prices(seed=i, start=float(200 + 150 * i)))
        raw = [
            RawArticle(
                url=f"https://demo.local/article/{k}",
                title=title,
                published_at=now - timedelta(hours=h),
                source="demo.local",
                feed="demo",
            )
            for k, (title, h) in enumerate(DEMO_HEADLINES)
        ]
        stats = ingest_articles(s, raw, jobs.linker, jobs.sentiment, now=now)
        print(f"stored {stats.stored} demo articles")
    print(f"generated {jobs.signal_cycle()} signals")


if __name__ == "__main__":
    main()
