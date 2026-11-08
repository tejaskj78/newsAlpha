from datetime import timedelta

from app.market.indicators import rsi, technical_snapshot
from app.signals.engine import ImpactObs, aggregate_news, decide
from tests.conftest import NOW, make_prices


def obs(score, hours_ago, kind="direct", theme="", rel=1.0, conf=0.8, aid=None):
    return ImpactObs(
        article_id=aid if aid is not None else int(hours_ago * 100 + score * 10),
        title=f"article {score} {hours_ago}",
        url="u",
        source="s",
        published_at=NOW - timedelta(hours=hours_ago),
        kind=kind,
        theme=theme,
        relevance=rel,
        score=score,
        confidence=conf,
    )


def test_rsi_bounds():
    r = rsi(make_prices()["close"]).dropna()
    assert ((r >= 0) & (r <= 100)).all()


def test_technical_uptrend_positive():
    snap = technical_snapshot(make_prices(drift=0.004))
    assert snap is not None and snap.factors["trend"] > 0


def test_technical_needs_history():
    assert technical_snapshot(make_prices(n=10)) is None


def test_recent_news_weighs_more():
    fresh = aggregate_news([obs(0.8, 1), obs(-0.8, 60)], NOW, 18, 72, 1.5)
    assert fresh.score > 0


def test_future_news_is_ignored():
    agg = aggregate_news([obs(0.9, -5)], NOW, 18, 72, 1.5)  # published 5h in the future
    assert agg.n_articles == 0 and agg.score == 0


def test_shrinkage_single_article_weaker_than_many():
    one = aggregate_news([obs(0.8, 1, aid=1)], NOW, 18, 72, 1.5)
    many = aggregate_news([obs(0.8, h, aid=h) for h in range(1, 8)], NOW, 18, 72, 1.5)
    assert 0 < one.score < many.score


def test_theme_mass_is_capped():
    flood = [obs(-0.3, 1, kind="theme", theme="trade_war", aid=i) for i in range(30)]
    company = [obs(0.8, 1, aid=100), obs(0.8, 2, aid=101)]
    agg = aggregate_news(flood + company, NOW, 18, 72, 1.5)
    assert agg.score > 0  # two strong company headlines beat thirty generic tariff stories


def test_decide_buy_sell_hold(settings):
    up = technical_snapshot(make_prices(drift=0.004))
    pos = aggregate_news([obs(0.9, h, aid=h) for h in range(1, 6)], NOW, 18, 72, 1.5)
    neg = aggregate_news([obs(-0.9, h, aid=h) for h in range(1, 6)], NOW, 18, 72, 1.5)
    empty = aggregate_news([], NOW, 18, 72, 1.5)
    assert decide(pos, up, settings).action == "BUY"
    assert decide(neg, None, settings).action == "SELL"
    assert decide(empty, None, settings).action == "HOLD"


def test_explanation_lists_drivers(settings):
    agg = aggregate_news([obs(0.9, 1, aid=1), obs(0.1, 2, aid=2)], NOW, 18, 72, 1.5)
    d = decide(agg, None, settings)
    assert d.explanation["top_articles"][0]["article_id"] == 1
    assert d.explanation["summary"].startswith(d.action)
