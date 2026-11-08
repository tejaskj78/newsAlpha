from datetime import UTC, datetime, time, timedelta

from app.backtest.backtester import run_backtest
from app.signals.engine import ImpactObs
from tests.conftest import make_prices


def test_no_lookahead(settings):
    """A hugely positive article on the last day must not change any earlier decision."""
    df = make_prices(n=60)
    last_day = df.index[-2]
    future = ImpactObs(1, "t", "u", "s", datetime.combine(last_day, time(21), tzinfo=UTC), "direct", "", 1.0, 1.0, 1.0)
    base = run_backtest(df, [], settings, market="US")
    with_future = run_backtest(df, [future], settings, market="US")
    assert base.daily[:-1] == with_future.daily[:-1]


def test_news_drives_trades(settings):
    df = make_prices(n=80, drift=0.0)
    obs = [
        ImpactObs(
            i,
            "good",
            "u",
            "s",
            datetime.combine(d, time(9), tzinfo=UTC) - timedelta(hours=1),
            "direct",
            "",
            1.0,
            0.9,
            0.9,
        )
        for i, d in enumerate(df.index[30:60])
    ]
    r = run_backtest(df, obs, settings, market="IN")
    assert r.by_action.get("BUY", {}).get("count", 0) > 0
    assert r.trades > 0
    assert len(r.equity_curve) == r.days


def test_metrics_shape(settings):
    r = run_backtest(make_prices(n=100), [], settings)
    d = r.to_dict()
    for k in ("hit_rate", "strategy_return", "buy_hold_return", "sharpe", "max_drawdown", "equity_curve"):
        assert k in d
    assert d["max_drawdown"] <= 0
