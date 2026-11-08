from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from app.config import Settings
from app.db import init_engine, session_scope
from app.events import InMemoryBus
from app.ingestion.base import RawArticle
from app.jobs import Jobs
from app.nlp.entity_linker import EntityLinker
from app.nlp.sentiment import LexiconSentiment
from app.universe import get_universe

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


def make_prices(n: int = 120, drift: float = 0.002, seed: int = 7, start: float = 100.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rets = drift + rng.normal(0, 0.01, n)
    close = start * np.cumprod(1 + rets)
    days = pd.bdate_range(end=date(2026, 11, 6), periods=n).date
    return pd.DataFrame(
        {"open": close, "high": close * 1.01, "low": close * 0.99, "close": close, "volume": 1e6},
        index=days,
    )


class FakeSource:
    name = "fake"

    def __init__(self, articles: list[RawArticle]):
        self.articles = articles

    def fetch(self) -> list[RawArticle]:
        return list(self.articles)


class FakePrices:
    def __init__(self, drift: float = 0.002):
        self.drift = drift

    def history(self, ticker: str, period: str = "1y") -> pd.DataFrame:
        return make_prices(drift=self.drift, seed=sum(map(ord, ticker)))


@pytest.fixture
def settings() -> Settings:
    return Settings(database_url="sqlite://", redis_url="", sentiment_provider="lexicon")


@pytest.fixture
def db(tmp_path):
    init_engine(f"sqlite:///{tmp_path / 'test.db'}")
    yield


@pytest.fixture
def universe():
    return get_universe()


@pytest.fixture
def linker(universe):
    return EntityLinker(universe)


@pytest.fixture
def lexicon():
    return LexiconSentiment()


def recent_articles(now: datetime | None = None) -> list[RawArticle]:
    now = now or datetime.now(UTC)
    return [
        RawArticle(
            url="https://ex.com/1",
            title="Infosys bags record $2 billion deal, shares surge",
            published_at=now - timedelta(hours=2),
            source="ex.com",
            feed="fake",
        ),
        RawArticle(
            url="https://ex.com/2",
            title="Infosys bags record $2 billion deal; shares surge",
            published_at=now - timedelta(hours=1),
            source="copy.com",
            feed="fake",
        ),
        RawArticle(
            url="https://ex.com/3",
            title="Oil prices jump after OPEC+ cut announced",
            published_at=now - timedelta(hours=3),
            source="ex.com",
            feed="fake",
        ),
        RawArticle(
            url="https://ex.com/4",
            title="Local bakery opens new branch downtown",
            published_at=now - timedelta(hours=3),
            source="ex.com",
            feed="fake",
        ),
    ]


@pytest.fixture
def jobs(settings, db, universe):
    bus = InMemoryBus()
    return Jobs(
        settings=settings,
        universe=universe,
        sources=[FakeSource(recent_articles())],
        sentiment=LexiconSentiment(),
        prices=FakePrices(),
        bus=bus,
    )


@pytest.fixture
def session(db):
    with session_scope() as s:
        yield s
