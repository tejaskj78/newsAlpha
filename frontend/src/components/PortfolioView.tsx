import { FormEvent, useEffect, useState } from "react";
import { api, Portfolio, Signal, pct } from "../api";

const money = (x: number) => x.toLocaleString(undefined, { maximumFractionDigits: 2 });

export default function PortfolioView({ signals }: { signals: Signal[] }) {
  const [p, setP] = useState<Portfolio | null>(null);
  const [ticker, setTicker] = useState("");
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [qty, setQty] = useState(10);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    api.portfolio().then(setP).catch((e) => setMsg(e.message));
  }, []);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      setP(await api.trade(ticker, side, qty));
      setMsg(`Paper ${side} ${qty} ${ticker} filled at last close.`);
    } catch (err) {
      setMsg((err as Error).message);
    }
  };

  if (!p) return <div className="muted">{msg ?? "Loading portfolio…"}</div>;

  return (
    <div>
      <h2>Paper portfolio</h2>
      <div className="stats card">
        <div><span className="muted small">Equity</span><b>{money(p.equity)}</b></div>
        <div><span className="muted small">Cash</span><b>{money(p.cash)}</b></div>
        <div><span className="muted small">Total return</span><b>{pct(p.total_return, 2)}</b></div>
        <div><span className="muted small">Positions</span><b>{p.positions.length}</b></div>
      </div>

      <form className="card trade-form" onSubmit={submit}>
        <h3>Place a simulated trade</h3>
        <select value={ticker} onChange={(e) => setTicker(e.target.value)} required>
          <option value="">Choose a stock…</option>
          {signals.map((s) => (
            <option key={s.ticker} value={s.ticker}>{s.ticker} ({s.action})</option>
          ))}
        </select>
        <select value={side} onChange={(e) => setSide(e.target.value as "BUY" | "SELL")}>
          <option>BUY</option>
          <option>SELL</option>
        </select>
        <input type="number" min={1} value={qty} onChange={(e) => setQty(Number(e.target.value))} />
        <button type="submit">Submit</button>
        {msg && <span className="muted small">{msg}</span>}
      </form>

      <div className="card table-wrap">
        <h3>Positions</h3>
        <table>
          <thead><tr><th>Ticker</th><th>Qty</th><th>Avg price</th><th>Last</th><th>Value</th><th>P&amp;L</th></tr></thead>
          <tbody>
            {p.positions.map((r) => (
              <tr key={r.ticker}>
                <td>{r.ticker}</td><td>{r.qty}</td><td>{money(r.avg_price)}</td><td>{money(r.last_price)}</td>
                <td>{money(r.value)}</td><td className={r.unrealised_pnl >= 0 ? "txt-buy" : "txt-sell"}>{money(r.unrealised_pnl)}</td>
              </tr>
            ))}
            {!p.positions.length && <tr><td colSpan={6} className="muted">No open positions.</td></tr>}
          </tbody>
        </table>
      </div>

      <div className="card table-wrap">
        <h3>Recent trades</h3>
        <table>
          <thead><tr><th>When</th><th>Side</th><th>Ticker</th><th>Qty</th><th>Price</th><th>Source</th></tr></thead>
          <tbody>
            {p.recent_trades.map((t) => (
              <tr key={t.id}>
                <td>{new Date(t.executed_at).toLocaleString()}</td>
                <td className={t.side === "BUY" ? "txt-buy" : "txt-sell"}>{t.side}</td>
                <td>{t.ticker}</td><td>{t.qty}</td><td>{money(t.price)}</td><td>{t.note}</td>
              </tr>
            ))}
            {!p.recent_trades.length && <tr><td colSpan={6} className="muted">No trades yet.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
