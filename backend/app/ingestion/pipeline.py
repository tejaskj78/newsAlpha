"""News pipeline: fetch -> exact dedup -> near-dup dedup -> link -> sentiment -> store impacts."""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.base import NewsSource, RawArticle
from app.ingestion.dedup import NearDuplicateIndex, simhash, to_signed
from app.models import Article, ArticleImpact
from app.nlp.entity_linker import EntityLinker
from app.nlp.sentiment import SentimentModel

log = logging.getLogger(__name__)
MAX_AGE = timedelta(days=4)


@dataclass
class IngestStats:
    fetched: int = 0
    duplicates: int = 0
    irrelevant: int = 0
    stored: int = 0
    tickers_touched: set[str] = field(default_factory=set)
    new_article_ids: list[int] = field(default_factory=list)


def _canonical_url(url: str) -> str:
    return url.split("#")[0].split("?utm_")[0].rstrip("/")


def ingest_articles(
    session: Session,
    raw: list[RawArticle],
    linker: EntityLinker,
    sentiment: SentimentModel,
    dedup_threshold: int = 3,
    now: datetime | None = None,
) -> IngestStats:
    now = now or datetime.now(UTC)
    stats = IngestStats(fetched=len(raw))

    recent_cutoff = now - timedelta(days=2)
    index = NearDuplicateIndex(
        dedup_threshold,
        list(session.scalars(select(Article.simhash).where(Article.published_at >= recent_cutoff))),
    )
    seen_urls: set[str] = set()

    for item in sorted(raw, key=lambda a: a.published_at):
        url = _canonical_url(item.url)
        published = item.published_at if item.published_at.tzinfo else item.published_at.replace(tzinfo=UTC)
        if not item.title or now - published > MAX_AGE or url in seen_urls:
            stats.duplicates += url in seen_urls
            continue
        seen_urls.add(url)
        if session.scalar(select(Article.id).where(Article.url == url)):
            stats.duplicates += 1
            continue
        fp = simhash(item.title)
        if index.is_duplicate(fp):
            stats.duplicates += 1
            continue
        index.add(fp)

        links = linker.link(item.title, item.summary)
        if not links:
            stats.irrelevant += 1
            continue

        direct = sorted({lk.ticker for lk in links if lk.kind == "direct"})
        result = sentiment.analyze(item.title, item.summary, direct) if direct else None

        article = Article(
            url=url,
            title=item.title,
            summary=item.summary,
            source=item.source,
            feed=item.feed,
            country=item.country,
            published_at=published,
            simhash=to_signed(fp),
            sentiment_model=result.model if result else "theme-only",
        )
        for lk in links:
            if lk.kind == "direct":
                assert result is not None
                article.impacts.append(
                    ArticleImpact(
                        ticker=lk.ticker,
                        kind="direct",
                        relevance=lk.relevance,
                        score=result.for_ticker(lk.ticker),
                        confidence=result.confidence,
                        rationale=result.reasons.get(lk.ticker, f"mentions '{lk.matched}'"),
                    )
                )
            else:
                article.impacts.append(
                    ArticleImpact(
                        ticker=lk.ticker,
                        kind="theme",
                        theme=lk.theme,
                        relevance=lk.relevance,
                        score=lk.impact,
                        confidence=0.6,
                        rationale=f"macro theme '{lk.theme}' (matched '{lk.matched}')",
                    )
                )
            stats.tickers_touched.add(lk.ticker)
        session.add(article)
        session.flush()
        stats.new_article_ids.append(article.id)
        stats.stored += 1

    log.info(
        "ingest: fetched=%d stored=%d dup=%d irrelevant=%d",
        stats.fetched,
        stats.stored,
        stats.duplicates,
        stats.irrelevant,
    )
    return stats


def fetch_all(sources: list[NewsSource]) -> list[RawArticle]:
    out: list[RawArticle] = []
    for src in sources:
        try:
            got = src.fetch()
            log.info("source %s returned %d articles", src.name, len(got))
            out.extend(got)
        except Exception:
            log.exception("source %s crashed", src.name)
    return out
