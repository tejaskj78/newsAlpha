"""Technical indicators and a bounded technical score in [-1, 1]."""

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


def sma(series: pd.Series, n: int) -> pd.Series:
    return series.rolling(n, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder's RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = gain / loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(loss != 0, 100.0)


def annualised_volatility(close: pd.Series, n: int = 20) -> pd.Series:
    return np.log(close).diff().rolling(n, min_periods=n).std() * np.sqrt(252)


@dataclass
class TechnicalSnapshot:
    close: float
    rsi14: float | None
    sma20: float | None
    sma50: float | None
    momentum5: float | None  # 5-day return
    volatility20: float | None
    score: float
    factors: dict[str, float]

    def to_dict(self) -> dict:
        return asdict(self)


def _f(x) -> float | None:
    return None if x is None or pd.isna(x) else float(x)


def technical_snapshot(df: pd.DataFrame) -> TechnicalSnapshot | None:
    """Compute indicators on the last bar. Needs >= 20 bars; uses what is available."""
    if df is None or len(df) < 20:
        return None
    close = df["close"].astype(float)
    r = _f(rsi(close).iloc[-1])
    s20 = _f(sma(close, 20).iloc[-1])
    s50 = _f(sma(close, 50).iloc[-1]) if len(close) >= 50 else None
    mom = _f(close.iloc[-1] / close.iloc[-6] - 1) if len(close) >= 6 else None
    vol = _f(annualised_volatility(close).iloc[-1])
    last = float(close.iloc[-1])

    factors: dict[str, float] = {}
    # Mean reversion: oversold -> +, overbought -> -
    if r is not None:
        if r < 30:
            factors["rsi"] = (30 - r) / 30
        elif r > 70:
            factors["rsi"] = -(r - 70) / 30
        else:
            factors["rsi"] = 0.0
    # Trend: price above both moving averages, and fast MA above slow MA
    if s20 is not None:
        trend = 0.5 if last > s20 else -0.5
        if s50 is not None:
            trend += 0.5 if s20 > s50 else -0.5
        factors["trend"] = trend
    # Momentum normalised by volatility (a 3% move means more for a calm stock)
    if mom is not None and vol:
        weekly_vol = vol * np.sqrt(5 / 252)
        factors["momentum"] = float(np.tanh(mom / weekly_vol / 2)) if weekly_vol > 0 else 0.0

    weights = {"rsi": 0.3, "trend": 0.4, "momentum": 0.3}
    total_w = sum(weights[k] for k in factors)
    score = sum(weights[k] * v for k, v in factors.items()) / total_w if total_w else 0.0
    return TechnicalSnapshot(
        close=last,
        rsi14=r,
        sma20=s20,
        sma50=s50,
        momentum5=mom,
        volatility20=vol,
        score=float(np.clip(score, -1, 1)),
        factors={k: round(v, 4) for k, v in factors.items()},
    )
