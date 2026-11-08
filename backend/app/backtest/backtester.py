"""Walk-forward backtest: replay history day by day, using ONLY information available at that time.

For each trading day t:
  1. as_of = market close on day t
  2. news  = articles published <= as_of (future articles are invisible)
  3. tech  = indicators computed on bars[0..t]
  4. action -> position held from close(t) to close(t+1)
Reports hit rate, forward returns per action, strategy vs buy-and-hold, Sharpe, max drawdown.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.config import Settings
from app.market.indicators import technical_snapshot
from app.market.prices import load_bars
from app.signals.engine import ImpactObs, aggregate_news, decide, load_impacts

MARKET_CLOSE_UTC = {"IN": time(10, 0), "US": time(20, 0)}
WARMUP_BARS = 20


@dataclass
class BacktestResult:
    ticker: str
    days: int
    horizon: int
    trades: int
    hit_rate: float | None
    by_action: dict
    strategy_return: float
    buy_hold_return: float
    sharpe: float | None
    max_drawdown: float
    equity_curve: list[dict]
    daily: list[dict]

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def _max_drawdown(equity: np.ndarray) -> float:
    peaks = np.maximum.accumulate(equity)
    return float(((equity - peaks) / peaks).min()) if len(equity) else 0.0


def run_backtest(
    df: pd.DataFrame,
    obs: list[ImpactObs],
    settings: Settings,
    ticker: str = "",
    market: str = "US",
    horizon: int = 5,
    allow_short: bool = False,
    cost_bps: float = 10.0,
) -> BacktestResult:
    df = df.sort_index()
    close = df["close"].astype(float).to_numpy()
    days = list(df.index)
    close_t = MARKET_CLOSE_UTC.get(market, time(20, 0))

    rows = []
    for i in range(WARMUP_BARS, len(df) - 1):
        as_of = datetime.combine(days[i], close_t, tzinfo=UTC)
        news = aggregate_news(
            obs, as_of, settings.news_half_life_hours, settings.news_lookback_hours, settings.news_prior_mass
        )
        tech = technical_snapshot(df.iloc[: i + 1])
        d = decide(news, tech, settings)
        fwd_end = min(i + horizon, len(df) - 1)
        rows.append(
            {
                "day": str(days[i]),
                "action": d.action,
                "composite": d.composite,
                "news_score": round(news.score, 4),
                "close": close[i],
                "next_ret": close[i + 1] / close[i] - 1,
                "fwd_ret": close[fwd_end] / close[i] - 1 if fwd_end > i else 0.0,
                "has_full_horizon": i + horizon <= len(df) - 1,
            }
        )

    if not rows:
        return BacktestResult(ticker, 0, horizon, 0, None, {}, 0.0, 0.0, None, 0.0, [], [])

    res = pd.DataFrame(rows)
    pos_map = {"BUY": 1.0, "HOLD": 0.0, "SELL": -1.0 if allow_short else 0.0}
    res["position"] = res["action"].map(pos_map)
    turnover = res["position"].diff().abs().fillna(res["position"].abs())
    res["strat_ret"] = res["position"] * res["next_ret"] - turnover * cost_bps / 10_000
    equity = (1 + res["strat_ret"]).cumprod().to_numpy()
    bh = (1 + res["next_ret"]).cumprod().to_numpy()

    scored = res[res["has_full_horizon"]]
    by_action = {}
    for act in ("BUY", "SELL", "HOLD"):
        sub = scored[scored["action"] == act]
        if len(sub):
            hits = (sub["fwd_ret"] > 0) if act == "BUY" else (sub["fwd_ret"] < 0) if act == "SELL" else None
            by_action[act] = {
                "count": int(len(sub)),
                "avg_fwd_return": round(float(sub["fwd_ret"].mean()), 5),
                "hit_rate": round(float(hits.mean()), 4) if hits is not None else None,
            }
    directional = scored[scored["action"] != "HOLD"]
    if len(directional):
        hit = np.where(directional["action"] == "BUY", directional["fwd_ret"] > 0, directional["fwd_ret"] < 0)
        hit_rate = round(float(hit.mean()), 4)
    else:
        hit_rate = None

    std = res["strat_ret"].std()
    sharpe = round(float(res["strat_ret"].mean() / std * np.sqrt(252)), 3) if std and std > 0 else None

    return BacktestResult(
        ticker=ticker,
        days=len(res),
        horizon=horizon,
        trades=int((turnover > 0).sum()),
        hit_rate=hit_rate,
        by_action=by_action,
        strategy_return=round(float(equity[-1] - 1), 5),
        buy_hold_return=round(float(bh[-1] - 1), 5),
        sharpe=sharpe,
        max_drawdown=round(_max_drawdown(equity), 5),
        equity_curve=[
            {"day": d, "strategy": round(float(e), 5), "buy_hold": round(float(b), 5)}
            for d, e, b in zip(res["day"], equity, bh, strict=True)
        ],
        daily=res[["day", "action", "composite", "news_score", "close", "fwd_ret"]].round(5).to_dict("records"),
    )


def backtest_ticker(
    session: Session,
    ticker: str,
    market: str,
    settings: Settings,
    days: int = 120,
    horizon: int = 5,
    allow_short: bool = False,
) -> BacktestResult:
    df = load_bars(session, ticker)
    df = df.iloc[-(days + WARMUP_BARS) :]
    if df.empty:
        return run_backtest(df, [], settings, ticker, market, horizon, allow_short)
    start = datetime.combine(df.index[0], time(0), tzinfo=UTC) - timedelta(hours=settings.news_lookback_hours)
    end = datetime.combine(df.index[-1], time(23, 59), tzinfo=UTC)
    obs = load_impacts(session, ticker, start, end)
    return run_backtest(df, obs, settings, ticker, market, horizon, allow_short)
