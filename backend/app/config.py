from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

DATA_DIR = Path(__file__).parent / "data"


class Settings(BaseSettings):
    """All runtime configuration. Every field can be overridden by an env var."""

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    # Infrastructure
    database_url: str = "sqlite:///./newsalpha.db"
    redis_url: str = ""  # empty -> in-memory event bus (single process only)
    embedded_worker: bool = False  # run the scheduler inside the API process
    cors_origins: str = "http://localhost:5173"

    # Universe
    universe_file: Path = DATA_DIR / "universe.yaml"

    # News ingestion
    news_interval_minutes: int = 10
    gdelt_enabled: bool = True
    gdelt_timespan: str = "6h"
    rss_enabled: bool = True
    rss_feeds: str = (
        "https://feeds.bbci.co.uk/news/business/rss.xml,"
        "https://www.cnbc.com/id/100003114/device/rss/rss.html,"
        "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms,"
        "https://www.livemint.com/rss/markets"
    )
    dedup_hamming_threshold: int = 3

    # Sentiment: "lexicon" (offline, default) or "llm" (any OpenAI-compatible API)
    sentiment_provider: str = "lexicon"
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_api_key: str = ""
    llm_model: str = "llama-3.1-8b-instant"
    llm_timeout_seconds: float = 20.0

    # Prices
    price_interval_minutes: int = 30
    price_history_period: str = "1y"

    # Signal engine
    news_half_life_hours: float = 18.0
    news_lookback_hours: float = 72.0
    news_prior_mass: float = 1.0  # shrinkage: few articles -> score pulled toward 0
    weight_news: float = 0.6
    weight_technical: float = 0.4
    buy_threshold: float = 0.25
    sell_threshold: float = -0.25
    high_volatility: float = 0.55  # annualised; above this thresholds are widened

    # Paper trading
    paper_starting_cash: float = 1_000_000.0
    paper_auto_trade: bool = False
    paper_max_position_pct: float = 0.10

    @property
    def rss_feed_list(self) -> list[str]:
        return [f.strip() for f in self.rss_feeds.split(",") if f.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
