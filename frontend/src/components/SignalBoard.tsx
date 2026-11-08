import { useMemo, useState } from "react";
import { Action, Signal, ago, signed } from "../api";

const ORDER: Record<Action, number> = { BUY: 0, SELL: 1, HOLD: 2 };

export function ActionBadge({ action }: { action: Action }) {
  return <span className={`badge badge-${action.toLowerCase()}`}>{action}</span>;
}

export function ScoreBar({ value }: { value: number }) {
  const w = Math.min(Math.abs(value), 1) * 50;
  return (
    <div className="scorebar" title={signed(value)}>
      <div className="scorebar-mid" />
      <div className={`scorebar-fill ${value >= 0 ? "pos" : "neg"}`}
        style={value >= 0 ? { left: "50%", width: `${w}%` } : { left: `${50 - w}%`, width: `${w}%` }} />
    </div>
  );
}

export default function SignalBoard({ signals, onSelect }: { signals: Signal[]; onSelect: (t: string) => void }) {
  const [market, setMarket] = useState<"ALL" | "IN" | "US">("ALL");
  const rows = useMemo(
    () =>
      signals
        .filter((s) => market === "ALL" || s.market === market)
        .sort((a, b) => ORDER[a.action] - ORDER[b.action] || Math.abs(b.composite) - Math.abs(a.composite)),
    [signals, market],
  );

  if (!signals.length) {
    return (
      <div className="empty">
        <h2>No signals yet</h2>
        <p>The worker fetches news every few minutes. Click <b>Run pipeline now</b>, or seed demo data with
          <code>python -m scripts.seed_demo</code>.</p>
      </div>
    );
  }

  return (
    <>
      <div className="toolbar">
        <h2>Latest suggestions</h2>
        <div className="seg">
          {(["ALL", "IN", "US"] as const).map((m) => (
            <button key={m} className={market === m ? "active" : ""} onClick={() => setMarket(m)}>
              {m === "ALL" ? "All" : m === "IN" ? "India" : "US"}
            </button>
          ))}
        </div>
      </div>
      <div className="grid">
        {rows.map((s) => (
          <button key={s.ticker} className="card signal-card" onClick={() => onSelect(s.ticker)}>
            <div className="card-head">
              <div>
                <div className="sym">{s.ticker}</div>
                <div className="muted small">{s.name} · {s.sector}</div>
              </div>
              <ActionBadge action={s.action} />
            </div>
            <div className="metrics">
              <div><span className="muted small">News</span><ScoreBar value={s.news_score} /></div>
              <div><span className="muted small">Technical</span><ScoreBar value={s.technical_score} /></div>
            </div>
            <div className="card-foot small">
              <span>Score <b>{signed(s.composite)}</b></span>
              <span>Confidence <b>{Math.round(s.confidence * 100)}%</b></span>
              <span className="muted">{ago(s.created_at)}</span>
            </div>
            <p className="summary small">{s.explanation.summary}</p>
          </button>
        ))}
      </div>
    </>
  );
}
