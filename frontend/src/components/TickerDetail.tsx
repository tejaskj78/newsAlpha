import { useEffect, useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, Backtest, TickerDetail as Detail, ago, pct, signed } from "../api";
import { ActionBadge, ScoreBar } from "./SignalBoard";

const axis = { stroke: "var(--muted)", fontSize: 11 };

export default function TickerDetail({ ticker, onBack }: { ticker: string; onBack: () => void }) {
  const [d, setD] = useState<Detail | null>(null);
  const [bt, setBt] = useState<Backtest | null>(null);
  const [btLoading, setBtLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setD(null);
    setBt(null);
    api.ticker(ticker).then(setD).catch((e) => setErr(e.message));
  }, [ticker]);

  const runBacktest = () => {
    setBtLoading(true);
    api.backtest(ticker).then(setBt).catch((e) => setErr(e.message)).finally(() => setBtLoading(false));
  };

  if (err) return <div className="error">{err}</div>;
  if (!d) return <div className="muted">Loading {ticker}…</div>;
  const s = d.signal;

  return (
    <div className="detail">
      <button className="link" onClick={onBack}>← All signals</button>
      <div className="detail-head">
        <div>
          <h2>{d.name} <span className="muted">{d.ticker}</span></h2>
          <div className="muted small">{d.sector} · {d.market === "IN" ? "NSE India" : "US"}</div>
        </div>
        {s && <ActionBadge action={s.action} />}
      </div>

      {s && (
        <div className="card">
          <p className="summary">{s.explanation.summary}</p>
          <div className="metrics three">
            <div><span className="muted small">News {signed(s.news_score)}</span><ScoreBar value={s.news_score} /></div>
            <div><span className="muted small">Technical {signed(s.technical_score)}</span><ScoreBar value={s.technical_score} /></div>
            <div><span className="muted small">Composite {signed(s.composite)}</span><ScoreBar value={s.composite} /></div>
          </div>
          <div className="muted small">
            BUY above {signed(s.explanation.thresholds.buy)} · SELL below {signed(s.explanation.thresholds.sell)} · confidence {Math.round(s.confidence * 100)}%
          </div>
        </div>
      )}

      <div className="card">
        <h3>Price and moving averages</h3>
        {d.prices.length ? (
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={d.prices}>
              <CartesianGrid stroke="var(--grid)" vertical={false} />
              <XAxis dataKey="day" tick={axis} minTickGap={40} />
              <YAxis tick={axis} domain={["auto", "auto"]} width={60} />
              <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)" }} />
              <Legend />
              <Line dataKey="close" name="Close" stroke="var(--series-1)" dot={false} strokeWidth={2} />
              <Line dataKey="sma20" name="SMA 20" stroke="var(--series-2)" dot={false} strokeWidth={1.5} />
              <Line dataKey="sma50" name="SMA 50" stroke="var(--series-3)" dot={false} strokeWidth={1.5} />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <p className="muted">No price history yet.</p>
        )}
      </div>

      {s && (
        <div className="card">
          <h3>What drove this suggestion</h3>
          {s.explanation.top_articles.length === 0 && <p className="muted">No recent news; this is technicals only.</p>}
          <ul className="drivers">
            {s.explanation.top_articles.map((a) => (
              <li key={`${a.article_id}-${a.theme}`}>
                <span className={`contrib ${a.contribution >= 0 ? "pos" : "neg"}`}>{signed(a.contribution, 3)}</span>
                <div>
                  <a href={a.url} target="_blank" rel="noreferrer">{a.title}</a>
                  <div className="muted small">
                    {a.source} · {ago(a.published_at)} · {a.kind === "theme" ? `macro theme: ${a.theme}` : "direct mention"}
                    {a.kind === "direct" && a.rationale && ` · ${a.rationale}`}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="card">
        <div className="toolbar">
          <h3>Backtest: would these suggestions have worked?</h3>
          <button onClick={runBacktest} disabled={btLoading}>{btLoading ? "Running…" : "Run 180-day backtest"}</button>
        </div>
        {bt && (
          <>
            <div className="stats">
              <div><span className="muted small">Strategy</span><b>{pct(bt.strategy_return)}</b></div>
              <div><span className="muted small">Buy and hold</span><b>{pct(bt.buy_hold_return)}</b></div>
              <div><span className="muted small">Hit rate</span><b>{bt.hit_rate == null ? "–" : `${Math.round(bt.hit_rate * 100)}%`}</b></div>
              <div><span className="muted small">Sharpe</span><b>{bt.sharpe ?? "–"}</b></div>
              <div><span className="muted small">Max drawdown</span><b>{pct(bt.max_drawdown)}</b></div>
              <div><span className="muted small">Trades</span><b>{bt.trades}</b></div>
            </div>
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={bt.equity_curve}>
                <CartesianGrid stroke="var(--grid)" vertical={false} />
                <XAxis dataKey="day" tick={axis} minTickGap={40} />
                <YAxis tick={axis} domain={["auto", "auto"]} width={50} />
                <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)" }} />
                <Legend />
                <Line dataKey="strategy" name="Signal strategy" stroke="var(--series-1)" dot={false} strokeWidth={2} />
                <Line dataKey="buy_hold" name="Buy and hold" stroke="var(--series-3)" dot={false} strokeWidth={1.5} />
              </LineChart>
            </ResponsiveContainer>
            <p className="muted small">Walk-forward replay using only news and prices available at each day's close, 10 bps cost per trade, long-only.</p>
          </>
        )}
      </div>
    </div>
  );
}
