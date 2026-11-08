import { useCallback, useEffect, useState } from "react";
import { api, Signal } from "./api";
import SignalBoard from "./components/SignalBoard";
import TickerDetail from "./components/TickerDetail";
import LiveFeed from "./components/LiveFeed";
import PortfolioView from "./components/PortfolioView";

type Tab = "signals" | "portfolio";

export default function App() {
  const [tab, setTab] = useState<Tab>("signals");
  const [signals, setSignals] = useState<Signal[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  const load = useCallback(() => {
    api.latestSignals().then(setSignals).then(() => setError(null)).catch((e) => setError(String(e.message ?? e)));
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 60_000);
    return () => clearInterval(t);
  }, [load]);

  const runNow = async () => {
    setRunning(true);
    try {
      await api.runPipeline();
      load();
    } catch (e) {
      setError(String((e as Error).message));
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo">◆</span> NewsAlpha
          <span className="tagline">world news → explainable stock signals</span>
        </div>
        <nav className="tabs">
          <button className={tab === "signals" ? "active" : ""} onClick={() => setTab("signals")}>Signals</button>
          <button className={tab === "portfolio" ? "active" : ""} onClick={() => setTab("portfolio")}>Paper portfolio</button>
          <button className="ghost" onClick={runNow} disabled={running}>{running ? "Running…" : "Run pipeline now"}</button>
        </nav>
      </header>

      <div className="disclaimer">
        Educational project. Signals are generated automatically and can be wrong. This is not financial advice; all trading here is simulated.
      </div>

      {error && <div className="error">Can't reach the API: {error}</div>}

      <main className="layout">
        <section className="main-col">
          {tab === "signals" ? (
            selected ? (
              <TickerDetail ticker={selected} onBack={() => setSelected(null)} />
            ) : (
              <SignalBoard signals={signals} onSelect={setSelected} />
            )
          ) : (
            <PortfolioView signals={signals} />
          )}
        </section>
        <aside className="side-col">
          <LiveFeed onSignal={load} onSelect={(t) => { setTab("signals"); setSelected(t); }} />
        </aside>
      </main>
    </div>
  );
}
