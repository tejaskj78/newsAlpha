const BASE = import.meta.env.VITE_API_URL ?? "";

export type Action = "BUY" | "SELL" | "HOLD";

export interface Driver {
  article_id: number;
  title: string;
  url: string;
  source: string;
  published_at: string;
  kind: "direct" | "theme";
  theme: string;
  sentiment: number;
  contribution: number;
  rationale: string;
}

export interface Signal {
  id: number;
  ticker: string;
  name: string;
  sector: string;
  market: string;
  action: Action;
  composite: number;
  news_score: number;
  technical_score: number;
  confidence: number;
  price: number | null;
  created_at: string;
  explanation: {
    summary: string;
    top_articles: Driver[];
    themes: Record<string, number>;
    technical: { rsi14: number | null; sma20: number | null; sma50: number | null; volatility20: number | null } | null;
    thresholds: { buy: number; sell: number };
  };
}

export interface PricePoint {
  day: string;
  close: number;
  sma20: number | null;
  sma50: number | null;
  rsi14: number | null;
}

export interface TickerDetail {
  ticker: string;
  name: string;
  sector: string;
  market: string;
  prices: PricePoint[];
  signal: Signal | null;
}

export interface NewsItem {
  id: number;
  title: string;
  url: string;
  source: string;
  published_at: string;
  impacts: { ticker: string; kind: string; theme: string; score: number }[];
}

export interface Backtest {
  days: number;
  trades: number;
  hit_rate: number | null;
  strategy_return: number;
  buy_hold_return: number;
  sharpe: number | null;
  max_drawdown: number;
  by_action: Record<string, { count: number; avg_fwd_return: number; hit_rate: number | null }>;
  equity_curve: { day: string; strategy: number; buy_hold: number }[];
}

export interface Portfolio {
  cash: number;
  equity: number;
  starting_cash: number;
  total_return: number;
  positions: { ticker: string; qty: number; avg_price: number; last_price: number; value: number; unrealised_pnl: number }[];
  recent_trades: { id: number; ticker: string; side: string; qty: number; price: number; executed_at: string; note: string }[];
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(BASE + path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(body.detail ?? `${r.status} ${r.statusText}`);
  }
  return r.json();
}

export const api = {
  latestSignals: () => req<Signal[]>("/api/signals/latest"),
  ticker: (t: string) => req<TickerDetail>(`/api/tickers/${encodeURIComponent(t)}`),
  news: (ticker?: string, limit = 40) =>
    req<NewsItem[]>(`/api/news?limit=${limit}${ticker ? `&ticker=${encodeURIComponent(ticker)}` : ""}`),
  backtest: (ticker: string, days = 180) =>
    req<Backtest>("/api/backtest", { method: "POST", body: JSON.stringify({ ticker, days }) }),
  portfolio: () => req<Portfolio>("/api/portfolio"),
  trade: (ticker: string, side: "BUY" | "SELL", qty: number) =>
    req<Portfolio>("/api/portfolio/trade", { method: "POST", body: JSON.stringify({ ticker, side, qty }) }),
  runPipeline: () => req<unknown>("/api/admin/run?job=all", { method: "POST" }),
  streamUrl: () => `${BASE}/api/stream`,
};

export const pct = (x: number | null | undefined, digits = 1) =>
  x == null ? "–" : `${x >= 0 ? "+" : ""}${(x * 100).toFixed(digits)}%`;

export const signed = (x: number, digits = 2) => `${x >= 0 ? "+" : ""}${x.toFixed(digits)}`;

export const ago = (iso: string) => {
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 60) return `${Math.max(mins, 0)}m ago`;
  if (mins < 48 * 60) return `${Math.round(mins / 60)}h ago`;
  return `${Math.round(mins / 1440)}d ago`;
};
