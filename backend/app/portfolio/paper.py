"""Paper trading: simulated money only. Long-only, no leverage."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PaperAccount, PaperPosition, PaperTrade, PriceBar, Signal, as_utc


class TradeError(ValueError):
    pass


def get_account(session: Session, starting_cash: float) -> PaperAccount:
    acct = session.scalar(select(PaperAccount).order_by(PaperAccount.id).limit(1))
    if acct is None:
        acct = PaperAccount(cash=starting_cash, starting_cash=starting_cash)
        session.add(acct)
        session.flush()
    return acct


def last_price(session: Session, ticker: str) -> float | None:
    bar = session.scalar(select(PriceBar).where(PriceBar.ticker == ticker).order_by(PriceBar.day.desc()).limit(1))
    return bar.close if bar else None


def _position(session: Session, acct: PaperAccount, ticker: str) -> PaperPosition | None:
    return session.scalar(
        select(PaperPosition).where(PaperPosition.account_id == acct.id, PaperPosition.ticker == ticker)
    )


def execute(
    session: Session,
    acct: PaperAccount,
    ticker: str,
    side: str,
    qty: float,
    price: float,
    signal_id: int | None = None,
    note: str = "",
) -> PaperTrade:
    side = side.upper()
    if qty <= 0 or price <= 0:
        raise TradeError("qty and price must be positive")
    pos = _position(session, acct, ticker)
    if side == "BUY":
        cost = qty * price
        if cost > acct.cash + 1e-9:
            raise TradeError(f"insufficient cash: need {cost:.2f}, have {acct.cash:.2f}")
        acct.cash -= cost
        if pos:
            pos.avg_price = (pos.avg_price * pos.qty + cost) / (pos.qty + qty)
            pos.qty += qty
        else:
            session.add(PaperPosition(account_id=acct.id, ticker=ticker, qty=qty, avg_price=price))
    elif side == "SELL":
        if not pos or pos.qty < qty - 1e-9:
            raise TradeError("cannot sell more than you hold (long-only)")
        acct.cash += qty * price
        pos.qty -= qty
        if pos.qty <= 1e-9:
            session.delete(pos)
    else:
        raise TradeError("side must be BUY or SELL")
    trade = PaperTrade(
        account_id=acct.id, ticker=ticker, side=side, qty=qty, price=price, signal_id=signal_id, note=note
    )
    session.add(trade)
    session.flush()
    return trade


def snapshot(session: Session, acct: PaperAccount) -> dict:
    positions = []
    equity = acct.cash
    for p in session.scalars(select(PaperPosition).where(PaperPosition.account_id == acct.id)):
        px = last_price(session, p.ticker) or p.avg_price
        value = p.qty * px
        equity += value
        positions.append(
            {
                "ticker": p.ticker,
                "qty": p.qty,
                "avg_price": round(p.avg_price, 4),
                "last_price": round(px, 4),
                "value": round(value, 2),
                "unrealised_pnl": round((px - p.avg_price) * p.qty, 2),
            }
        )
    trades = session.scalars(
        select(PaperTrade).where(PaperTrade.account_id == acct.id).order_by(PaperTrade.id.desc()).limit(50)
    )
    return {
        "cash": round(acct.cash, 2),
        "equity": round(equity, 2),
        "starting_cash": acct.starting_cash,
        "total_return": round(equity / acct.starting_cash - 1, 5),
        "positions": positions,
        "recent_trades": [
            {
                "id": t.id,
                "ticker": t.ticker,
                "side": t.side,
                "qty": t.qty,
                "price": t.price,
                "executed_at": as_utc(t.executed_at).isoformat(),
                "note": t.note,
            }
            for t in trades
        ],
    }


def auto_trade(
    session: Session, acct: PaperAccount, signals: list[Signal], max_position_pct: float
) -> list[PaperTrade]:
    """Follow signals: BUY sizes a position by confidence, SELL closes it."""
    equity = snapshot(session, acct)["equity"]
    trades = []
    for s in signals:
        if not s.price:
            continue
        pos = _position(session, acct, s.ticker)
        if s.action == "BUY" and not pos:
            budget = min(acct.cash, equity * max_position_pct * max(0.25, s.confidence))
            qty = int(budget // s.price)
            if qty > 0:
                trades.append(execute(session, acct, s.ticker, "BUY", qty, s.price, s.id, "auto"))
        elif s.action == "SELL" and pos:
            trades.append(execute(session, acct, s.ticker, "SELL", pos.qty, s.price, s.id, "auto"))
    return trades
