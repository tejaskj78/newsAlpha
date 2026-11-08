"""The three periodic jobs. Shared by the standalone worker, the embedded worker, and the admin API."""

import contextlib
import logging
from contextlib import contextmanager
from datetime import UTC, datetime

from app.config import Settings, get_settings
from app.db import session_scope
from app.events import EventBus, get_bus
from app.ingestion.base import NewsSource
from app.ingestion.gdelt import GdeltSource
from app.ingestion.pipeline import fetch_all, ingest_articles
from app.ingestion.rss import RssSource
from app.market.prices import PriceProvider, YahooPriceProvider, refresh_prices
from app.models import Article, as_utc
from app.nlp.entity_linker import EntityLinker
from app.nlp.sentiment import SentimentModel, build_sentiment_model
from app.portfolio.paper import auto_trade, get_account
from app.signals.engine import generate_signals
from app.universe import Universe, get_universe

log = logging.getLogger(__name__)


@contextmanager
def distributed_lock(settings: Settings, name: str, ttl: int = 600):
    """Prevent two worker replicas running the same job at once (no-op without Redis)."""
    if not settings.redis_url:
        yield True
        return
    import redis

    lock = redis.Redis.from_url(settings.redis_url).lock(f"newsalpha:lock:{name}", timeout=ttl)
    acquired = lock.acquire(blocking=False)
    try:
        yield acquired
    finally:
        if acquired:
            with contextlib.suppress(Exception):
                lock.release()


class Jobs:
    def __init__(
        self,
        settings: Settings | None = None,
        universe: Universe | None = None,
        sources: list[NewsSource] | None = None,
        sentiment: SentimentModel | None = None,
        prices: PriceProvider | None = None,
        bus: EventBus | None = None,
    ):
        self.settings = settings or get_settings()
        self.universe = universe or get_universe()
        if sources is None:
            sources = []
            if self.settings.gdelt_enabled:
                sources.append(GdeltSource(self.universe, timespan=self.settings.gdelt_timespan))
            if self.settings.rss_enabled:
                sources.append(RssSource(self.settings.rss_feed_list))
        self.sources = sources
        self.linker = EntityLinker(self.universe)
        self.sentiment = sentiment or build_sentiment_model(self.settings, self.universe)
        self.prices = prices or YahooPriceProvider()
        self.bus = bus or get_bus()

    @property
    def tickers(self) -> list[str]:
        return list(self.universe.tickers)

    def news_cycle(self) -> dict:
        with distributed_lock(self.settings, "news") as ok:
            if not ok:
                return {"skipped": "locked"}
            raw = fetch_all(self.sources)
            with session_scope() as s:
                stats = ingest_articles(s, raw, self.linker, self.sentiment, self.settings.dedup_hamming_threshold)
                for art in s.query(Article).filter(Article.id.in_(stats.new_article_ids)).limit(25):
                    self.bus.publish(
                        "article",
                        {
                            "id": art.id,
                            "title": art.title,
                            "url": art.url,
                            "source": art.source,
                            "published_at": as_utc(art.published_at).isoformat(),
                            "tickers": sorted({i.ticker for i in art.impacts if i.kind == "direct"}),
                        },
                    )
            result = {
                "fetched": stats.fetched,
                "stored": stats.stored,
                "duplicates": stats.duplicates,
                "irrelevant": stats.irrelevant,
            }
        if stats.stored:
            result["signals"] = self.signal_cycle()
        return result

    def price_cycle(self) -> dict:
        with distributed_lock(self.settings, "prices") as ok:
            if not ok:
                return {"skipped": "locked"}
            with session_scope() as s:
                return refresh_prices(s, self.prices, self.tickers, self.settings.price_history_period)

    def signal_cycle(self) -> int:
        now = datetime.now(UTC)
        with session_scope() as s:
            signals = generate_signals(s, self.tickers, self.settings, now)
            if self.settings.paper_auto_trade:
                acct = get_account(s, self.settings.paper_starting_cash)
                trades = auto_trade(s, acct, signals, self.settings.paper_max_position_pct)
                for t in trades:
                    self.bus.publish("trade", {"ticker": t.ticker, "side": t.side, "qty": t.qty, "price": t.price})
            for sig in signals:
                self.bus.publish(
                    "signal",
                    {
                        "ticker": sig.ticker,
                        "action": sig.action,
                        "composite": sig.composite,
                        "confidence": sig.confidence,
                        "created_at": as_utc(sig.created_at).isoformat(),
                        "summary": sig.explanation.get("summary", ""),
                    },
                )
            return len(signals)

    def run_all(self) -> dict:
        return {"prices": self.price_cycle(), "news": self.news_cycle(), "signals": self.signal_cycle()}
