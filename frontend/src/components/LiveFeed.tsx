import { useEffect, useRef, useState } from "react";
import { api, ago, NewsItem } from "../api";

interface FeedItem {
  key: string;
  kind: "article" | "signal" | "trade";
  title: string;
  url?: string;
  at: string;
  tickers: string[];
  action?: string;
}

const fromNews = (n: NewsItem): FeedItem => ({
  key: `a${n.id}`,
  kind: "article",
  title: n.title,
  url: n.url,
  at: n.published_at,
  tickers: [...new Set(n.impacts.filter((i) => i.kind === "direct").map((i) => i.ticker))],
});

export default function LiveFeed({ onSignal, onSelect }: { onSignal: () => void; onSelect: (t: string) => void }) {
  const [items, setItems] = useState<FeedItem[]>([]);
  const [live, setLive] = useState(false);
  const onSignalRef = useRef(onSignal);
  onSignalRef.current = onSignal;

  useEffect(() => {
    api.news(undefined, 40).then((ns) => setItems(ns.map(fromNews))).catch(() => {});
    const es = new EventSource(api.streamUrl());
    const push = (it: FeedItem) => setItems((prev) => [it, ...prev.filter((p) => p.key !== it.key)].slice(0, 80));
    es.addEventListener("hello", () => setLive(true));
    es.onerror = () => setLive(false);
    es.addEventListener("article", (e) => {
      const d = JSON.parse((e as MessageEvent).data);
      push({ key: `a${d.id}`, kind: "article", title: d.title, url: d.url, at: d.published_at, tickers: d.tickers });
    });
    let debounce: number | undefined;
    es.addEventListener("signal", (e) => {
      const d = JSON.parse((e as MessageEvent).data);
      if (d.action !== "HOLD") {
        push({ key: `s${d.ticker}${d.created_at}`, kind: "signal", title: d.summary, at: d.created_at, tickers: [d.ticker], action: d.action });
      }
      clearTimeout(debounce);
      debounce = window.setTimeout(() => onSignalRef.current(), 500);
    });
    es.addEventListener("trade", (e) => {
      const d = JSON.parse((e as MessageEvent).data);
      push({ key: `t${Date.now()}`, kind: "trade", title: `Paper ${d.side} ${d.qty} ${d.ticker} @ ${d.price.toFixed(2)}`, at: new Date().toISOString(), tickers: [d.ticker] });
    });
    return () => es.close();
  }, []);

  return (
    <div className="card feed">
      <div className="toolbar">
        <h3>Live feed</h3>
        <span className={`dot ${live ? "on" : ""}`} title={live ? "connected" : "reconnecting"} />
      </div>
      {items.length === 0 && <p className="muted small">Waiting for news…</p>}
      <ul>
        {items.map((it) => (
          <li key={it.key} className={`feed-${it.kind}`}>
            <div className="muted small">
              {it.kind === "signal" ? <b className={`txt-${it.action?.toLowerCase()}`}>{it.action}</b> : it.kind === "trade" ? "TRADE" : "NEWS"} · {ago(it.at)}
            </div>
            {it.url ? <a href={it.url} target="_blank" rel="noreferrer">{it.title}</a> : <span>{it.title}</span>}
            {it.tickers.length > 0 && (
              <div className="chips">
                {it.tickers.map((t) => <button key={t} className="chip" onClick={() => onSelect(t)}>{t}</button>)}
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
