"""Signal engine: fuse time-decayed news impact with technicals into BUY / SELL / HOLD.

news_score  = sum(w_i * s_i) / (sum(w_i) + prior_mass)
    w_i = relevance * confidence * 0.5 ** (age_hours / half_life)
    prior_mass shrinks the score toward 0 when there is little news (one headline
    should not produce a strong call; ten consistent headlines can).
composite   = w_news * news_score + w_tech * technical_score
action      = BUY if composite > buy_threshold, SELL if < sell_threshold, else HOLD
              (thresholds are widened 1.5x for highly volatile stocks)
"""

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.market.indicators import TechnicalSnapshot, technical_snapshot
from app.market.prices import load_bars
from app.models import Article, ArticleImpact, Signal, as_utc

THEME_MASS_CAP = 1.0  # one macro theme can't contribute more weight than this


@dataclass
class ImpactObs:
    article_id: int
    title: str
    url: str
    source: str
    published_at: datetime
    kind: str
    theme: str
    relevance: float
    score: float
    confidence: float
    rationale: str = ""


@dataclass
class NewsAggregate:
    score: float
    mass: float
    n_articles: int
    contributions: list[dict] = field(default_factory=list)
    themes: dict[str, float] = field(default_factory=dict)


@dataclass
class Decision:
    action: str
    composite: float
    confidence: float
    news: NewsAggregate
    technical: TechnicalSnapshot | None
    explanation: dict


def aggregate_news(
    obs: list[ImpactObs], now: datetime, half_life_h: float, lookback_h: float, prior_mass: float
) -> NewsAggregate:
    weighted: list[tuple[ImpactObs, float]] = []
    for o in obs:
        age_h = (now - as_utc(o.published_at)).total_seconds() / 3600
        if age_h < 0 or age_h > lookback_h:
            continue  # future (look-ahead) or stale
        w = o.relevance * o.confidence * 0.5 ** (age_h / half_life_h)
        weighted.append((o, w))

    # Cap each macro theme's total weight so 30 "tariff" headlines don't drown company news
    theme_mass: dict[str, float] = {}
    for o, w in weighted:
        if o.kind == "theme":
            theme_mass[o.theme] = theme_mass.get(o.theme, 0) + w
    scale = {t: min(1.0, THEME_MASS_CAP / m) for t, m in theme_mass.items() if m > 0}
    weighted = [(o, w * scale.get(o.theme, 1.0) if o.kind == "theme" else w) for o, w in weighted]

    mass = sum(w for _, w in weighted)
    denom = mass + prior_mass
    raw = sum(w * o.score for o, w in weighted)
    score = raw / denom if denom else 0.0

    contributions = sorted(
        (
            {
                "article_id": o.article_id,
                "title": o.title,
                "url": o.url,
                "source": o.source,
                "published_at": as_utc(o.published_at).isoformat(),
                "kind": o.kind,
                "theme": o.theme,
                "sentiment": round(o.score, 3),
                "contribution": round(w * o.score / denom, 4),
                "rationale": o.rationale,
            }
            for o, w in weighted
        ),
        key=lambda c: abs(c["contribution"]),
        reverse=True,
    )
    themes: dict[str, float] = {}
    for c in contributions:
        if c["kind"] == "theme":
            themes[c["theme"]] = round(themes.get(c["theme"], 0) + c["contribution"], 4)
    return NewsAggregate(
        score=max(-1.0, min(1.0, score)),
        mass=mass,
        n_articles=len({o.article_id for o, _ in weighted}),
        contributions=contributions,
        themes=themes,
    )


def _describe(value: float) -> str:
    if value > 0.4:
        return "strongly positive"
    if value > 0.1:
        return "positive"
    if value < -0.4:
        return "strongly negative"
    if value < -0.1:
        return "negative"
    return "neutral"


def decide(news: NewsAggregate, tech: TechnicalSnapshot | None, settings: Settings) -> Decision:
    if tech is not None:
        composite = settings.weight_news * news.score + settings.weight_technical * tech.score
    else:
        composite = news.score

    buy_t, sell_t = settings.buy_threshold, settings.sell_threshold
    high_vol = bool(tech and tech.volatility20 and tech.volatility20 > settings.high_volatility)
    if high_vol:
        buy_t, sell_t = buy_t * 1.5, sell_t * 1.5

    action = "BUY" if composite > buy_t else "SELL" if composite < sell_t else "HOLD"

    coverage = 1 - math.exp(-news.mass) if news.mass else 0.0
    agreement = 1.0
    if tech is not None and abs(news.score) > 0.05 and abs(tech.score) > 0.05:
        agreement = 1.0 if (news.score > 0) == (tech.score > 0) else 0.7
    strength = min(1.0, abs(composite) / (2 * max(abs(buy_t), abs(sell_t))))
    confidence = round(strength * (0.4 + 0.6 * coverage) * agreement, 3)

    parts = [f"News is {_describe(news.score)} ({news.score:+.2f}) across {news.n_articles} article(s)"]
    if news.contributions:
        top = news.contributions[0]
        parts.append(f'biggest driver: "{top["title"][:90]}"')
    if tech is not None:
        tparts = [f"technicals {_describe(tech.score)} ({tech.score:+.2f})"]
        if tech.rsi14 is not None:
            tparts.append(f"RSI {tech.rsi14:.0f}")
        if tech.sma20 is not None:
            tparts.append("price above 20-day MA" if tech.close > tech.sma20 else "price below 20-day MA")
        parts.append(", ".join(tparts))
    else:
        parts.append("no price history yet, news only")
    if high_vol:
        parts.append("high volatility, so a stronger signal was required")

    explanation = {
        "summary": f"{action}: " + "; ".join(parts) + ".",
        "top_articles": news.contributions[:5],
        "themes": news.themes,
        "news_mass": round(news.mass, 3),
        "technical": tech.to_dict() if tech else None,
        "thresholds": {"buy": round(buy_t, 3), "sell": round(sell_t, 3)},
        "weights": {"news": settings.weight_news, "technical": settings.weight_technical},
    }
    return Decision(action, round(composite, 4), confidence, news, tech, explanation)


def load_impacts(session: Session, ticker: str, since: datetime, until: datetime) -> list[ImpactObs]:
    rows = session.execute(
        select(ArticleImpact, Article)
        .join(Article, Article.id == ArticleImpact.article_id)
        .where(ArticleImpact.ticker == ticker)
        .where(Article.published_at >= since, Article.published_at <= until)
    ).all()
    return [
        ImpactObs(
            article_id=a.id,
            title=a.title,
            url=a.url,
            source=a.source,
            published_at=a.published_at,
            kind=i.kind,
            theme=i.theme,
            relevance=i.relevance,
            score=i.score,
            confidence=i.confidence,
            rationale=i.rationale,
        )
        for i, a in rows
    ]


def compute_decision(session: Session, ticker: str, settings: Settings, now: datetime | None = None) -> Decision:
    now = now or datetime.now(UTC)
    obs = load_impacts(session, ticker, now - timedelta(hours=settings.news_lookback_hours), now)
    news = aggregate_news(
        obs, now, settings.news_half_life_hours, settings.news_lookback_hours, settings.news_prior_mass
    )
    tech = technical_snapshot(load_bars(session, ticker, until=now.date()))
    return decide(news, tech, settings)


def generate_signals(
    session: Session, tickers: list[str], settings: Settings, now: datetime | None = None
) -> list[Signal]:
    now = now or datetime.now(UTC)
    out = []
    for t in tickers:
        d = compute_decision(session, t, settings, now)
        sig = Signal(
            ticker=t,
            created_at=now,
            action=d.action,
            composite=d.composite,
            news_score=round(d.news.score, 4),
            technical_score=round(d.technical.score, 4) if d.technical else 0.0,
            confidence=d.confidence,
            price=d.technical.close if d.technical else None,
            explanation=d.explanation,
        )
        session.add(sig)
        out.append(sig)
    session.flush()
    return out
