import asyncio
import json
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.backtest.backtester import backtest_ticker
from app.config import get_settings
from app.db import get_session
from app.events import get_bus
from app.market.indicators import rsi, sma
from app.market.prices import load_bars
from app.models import Article, ArticleImpact, Signal, as_utc
from app.portfolio.paper import TradeError, execute, get_account, last_price, snapshot
from app.universe import get_universe

router = APIRouter(prefix="/api")

DISCLAIMER = (
    "Educational project. Signals are generated automatically from news and price data, "
    "may be wrong, and are NOT financial advice. Paper trading only."
)


def _ticker_or_404(ticker: str) -> str:
    t = ticker.upper()
    if t not in get_universe().tickers:
        raise HTTPException(404, f"unknown ticker {ticker}")
    return t


def signal_dict(s: Signal) -> dict:
    u = get_universe().tickers.get(s.ticker)
    return {
        "id": s.id,
        "ticker": s.ticker,
        "name": u.name if u else s.ticker,
        "sector": u.sector if u else "",
        "market": u.market if u else "",
        "action": s.action,
        "composite": s.composite,
        "news_score": s.news_score,
        "technical_score": s.technical_score,
        "confidence": s.confidence,
        "price": s.price,
        "created_at": as_utc(s.created_at).isoformat(),
        "explanation": s.explanation,
    }


@router.get("/health")
def health(session: Session = Depends(get_session)) -> dict:
    return {
        "status": "ok",
        "articles": session.scalar(select(func.count(Article.id))),
        "signals": session.scalar(select(func.count(Signal.id))),
        "disclaimer": DISCLAIMER,
    }


@router.get("/universe")
def universe() -> dict:
    u = get_universe()
    return {
        "tickers": [
            {"symbol": t.symbol, "name": t.name, "sector": t.sector, "market": t.market} for t in u.tickers.values()
        ],
        "themes": [{"key": th.key, "description": th.description, "impacts": th.impacts} for th in u.themes.values()],
    }


@router.get("/signals/latest")
def latest_signals(session: Session = Depends(get_session)) -> list[dict]:
    latest_ids = select(func.max(Signal.id)).group_by(Signal.ticker)
    rows = session.scalars(select(Signal).where(Signal.id.in_(latest_ids))).all()
    rows = sorted(rows, key=lambda s: abs(s.composite), reverse=True)
    return [signal_dict(s) for s in rows]


@router.get("/signals/{ticker}")
def signal_history(
    ticker: str, limit: int = Query(100, le=1000), session: Session = Depends(get_session)
) -> list[dict]:
    t = _ticker_or_404(ticker)
    rows = session.scalars(select(Signal).where(Signal.ticker == t).order_by(Signal.id.desc()).limit(limit))
    return [signal_dict(s) for s in rows]


@router.get("/news")
def news(
    ticker: str | None = None, limit: int = Query(50, le=500), session: Session = Depends(get_session)
) -> list[dict]:
    q = select(Article).order_by(Article.published_at.desc()).limit(limit)
    if ticker:
        t = _ticker_or_404(ticker)
        q = q.where(Article.id.in_(select(ArticleImpact.article_id).where(ArticleImpact.ticker == t)))
    out = []
    for a in session.scalars(q):
        out.append(
            {
                "id": a.id,
                "title": a.title,
                "url": a.url,
                "source": a.source,
                "feed": a.feed,
                "country": a.country,
                "published_at": as_utc(a.published_at).isoformat(),
                "model": a.sentiment_model,
                "impacts": [
                    {
                        "ticker": i.ticker,
                        "kind": i.kind,
                        "theme": i.theme,
                        "score": round(i.score, 3),
                        "relevance": i.relevance,
                        "rationale": i.rationale,
                    }
                    for i in a.impacts
                    if not ticker or i.ticker == ticker.upper()
                ],
            }
        )
    return out


@router.get("/tickers/{ticker}")
def ticker_detail(ticker: str, days: int = Query(180, le=750), session: Session = Depends(get_session)) -> dict:
    t = _ticker_or_404(ticker)
    df = load_bars(session, t)
    chart = []
    if not df.empty:
        df = df.copy()
        df["sma20"] = sma(df["close"], 20)
        df["sma50"] = sma(df["close"], 50)
        df["rsi14"] = rsi(df["close"])
        for day, r in df.tail(days).iterrows():
            chart.append(
                {
                    "day": str(day),
                    "close": round(r["close"], 4),
                    **{k: (None if r[k] != r[k] else round(float(r[k]), 4)) for k in ("sma20", "sma50", "rsi14")},
                }
            )
    latest = session.scalar(select(Signal).where(Signal.ticker == t).order_by(Signal.id.desc()).limit(1))
    info = get_universe().tickers[t]
    return {
        "ticker": t,
        "name": info.name,
        "sector": info.sector,
        "market": info.market,
        "prices": chart,
        "signal": signal_dict(latest) if latest else None,
    }


class BacktestRequest(BaseModel):
    ticker: str
    days: int = Field(120, ge=20, le=750)
    horizon: int = Field(5, ge=1, le=30)
    allow_short: bool = False


@router.post("/backtest")
def backtest(req: BacktestRequest, session: Session = Depends(get_session)) -> dict:
    t = _ticker_or_404(req.ticker)
    info = get_universe().tickers[t]
    return backtest_ticker(session, t, info.market, get_settings(), req.days, req.horizon, req.allow_short).to_dict()


@router.get("/portfolio")
def portfolio(session: Session = Depends(get_session)) -> dict:
    return snapshot(session, get_account(session, get_settings().paper_starting_cash))


class TradeRequest(BaseModel):
    ticker: str
    side: str = Field(pattern="^(BUY|SELL|buy|sell)$")
    qty: float = Field(gt=0)


@router.post("/portfolio/trade")
def trade(req: TradeRequest, session: Session = Depends(get_session)) -> dict:
    t = _ticker_or_404(req.ticker)
    price = last_price(session, t)
    if price is None:
        raise HTTPException(409, "no price available yet for this ticker")
    acct = get_account(session, get_settings().paper_starting_cash)
    try:
        execute(session, acct, t, req.side, req.qty, price, note="manual")
    except TradeError as exc:
        raise HTTPException(400, str(exc)) from exc
    return snapshot(session, acct)


@router.post("/admin/run")
async def run_pipeline(request: Request, job: str = Query("all", pattern="^(all|news|prices|signals)$")) -> dict:
    jobs = request.app.state.jobs
    fn = {"all": jobs.run_all, "news": jobs.news_cycle, "prices": jobs.price_cycle, "signals": jobs.signal_cycle}[job]
    return {"job": job, "result": await asyncio.to_thread(fn)}


@router.get("/stream")
async def stream(request: Request) -> StreamingResponse:
    """Server-Sent Events: live signals, articles and trades."""

    async def gen():
        sub = get_bus().subscribe()
        yield f"event: hello\ndata: {json.dumps({'at': datetime.now(UTC).isoformat()})}\n\n"
        nxt = asyncio.ensure_future(anext(sub))
        try:
            while not await request.is_disconnected():
                done, _ = await asyncio.wait({nxt}, timeout=15)
                if not done:
                    yield ": keep-alive\n\n"
                    continue
                msg = nxt.result()
                yield f"event: {msg['event']}\ndata: {json.dumps(msg['data'], default=str)}\n\n"
                nxt = asyncio.ensure_future(anext(sub))
        finally:
            nxt.cancel()
            await sub.aclose()

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.get("/stats")
def stats(session: Session = Depends(get_session)) -> dict:
    since = datetime.now(UTC) - timedelta(hours=24)
    by_source = session.execute(
        select(Article.source, func.count(Article.id))
        .where(Article.published_at >= since)
        .group_by(Article.source)
        .order_by(func.count(Article.id).desc())
        .limit(10)
    ).all()
    return {
        "articles_24h": sum(n for _, n in by_source),
        "top_sources": [{"source": s, "count": n} for s, n in by_source],
    }
