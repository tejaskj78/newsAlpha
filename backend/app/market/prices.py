import logging
from datetime import date
from typing import Protocol

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PriceBar

log = logging.getLogger(__name__)
COLUMNS = ["open", "high", "low", "close", "volume"]


class PriceProvider(Protocol):
    def history(self, ticker: str, period: str = "1y") -> pd.DataFrame:
        """Daily OHLCV indexed by date, columns: open high low close volume."""
        ...


class YahooPriceProvider:
    """Free daily prices via yfinance. Works for NSE (.NS), BSE (.BO) and US tickers."""

    def history(self, ticker: str, period: str = "1y") -> pd.DataFrame:
        import yfinance as yf

        df = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=True)
        if df.empty:
            return pd.DataFrame(columns=COLUMNS)
        df = df.rename(columns=str.lower)[COLUMNS]
        df.index = pd.to_datetime(df.index).date
        return df


def upsert_bars(session: Session, ticker: str, df: pd.DataFrame) -> int:
    existing = {b.day: b for b in session.scalars(select(PriceBar).where(PriceBar.ticker == ticker))}
    n = 0
    for day, row in df.iterrows():
        d: date = day if isinstance(day, date) else pd.Timestamp(day).date()
        values = {c: float(row[c]) for c in COLUMNS}
        bar = existing.get(d)
        if bar:
            for k, v in values.items():
                setattr(bar, k, v)
        else:
            session.add(PriceBar(ticker=ticker, day=d, **values))
        n += 1
    return n


def load_bars(session: Session, ticker: str, until: date | None = None) -> pd.DataFrame:
    q = select(PriceBar).where(PriceBar.ticker == ticker).order_by(PriceBar.day)
    if until:
        q = q.where(PriceBar.day <= until)
    rows = session.scalars(q).all()
    if not rows:
        return pd.DataFrame(columns=COLUMNS)
    return pd.DataFrame([{c: getattr(r, c) for c in COLUMNS} for r in rows], index=[r.day for r in rows])


def refresh_prices(session: Session, provider: PriceProvider, tickers: list[str], period: str) -> dict:
    result = {}
    for t in tickers:
        try:
            result[t] = upsert_bars(session, t, provider.history(t, period))
        except Exception as exc:
            log.warning("price refresh failed for %s: %s", t, exc)
            result[t] = 0
    return result
