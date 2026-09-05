"use client";

import { useEffect, useState } from "react";

const API =
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "https://daily-report-api-ero2.onrender.com";

const TABS = ["Report", "Markets", "World News", "Large Flow", "Macro", "Settings"];

export default function Home() {
  const [tickers, setTickers] = useState<string[]>([]);
  const [status, setStatus] = useState("Connecting to backend...");
  const [newTicker, setNewTicker] = useState("");
  const [busySymbol, setBusySymbol] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("Report");

  async function loadWatchlist() {
    try {
      const response = await fetch(`${API}/api/v1/watchlist`, {
        cache: "no-store",
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const data = await response.json();
      setTickers(data.tickers || []);
      setStatus("Backend connected");
    } catch (error) {
      console.error(error);
      setStatus("Backend connection failed");
    }
  }

  useEffect(() => {
    loadWatchlist();
  }, []);

  async function addTicker() {
    const symbol = newTicker.trim().toUpperCase();

    if (!symbol || busySymbol) return;

    setBusySymbol(symbol);
    setStatus(`Adding ${symbol}...`);

    try {
      const response = await fetch(`${API}/api/v1/watchlist`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ symbol }),
      });

      if (!response.ok) {
        const detail = await response.json().catch(() => null);
        throw new Error(detail?.detail || `HTTP ${response.status}`);
      }

      setNewTicker("");
      await loadWatchlist();
    } catch (error) {
      console.error(error);
      setStatus(`Could not add ${symbol}`);
    } finally {
      setBusySymbol(null);
    }
  }

  async function removeTicker(symbol: string) {
    if (busySymbol) return;

    setBusySymbol(symbol);
    setStatus(`Removing ${symbol}...`);

    try {
      const response = await fetch(
        `${API}/api/v1/watchlist/${encodeURIComponent(symbol)}`,
        { method: "DELETE" }
      );

      if (!response.ok) {
        const detail = await response.json().catch(() => null);
        throw new Error(detail?.detail || `HTTP ${response.status}`);
      }

      await loadWatchlist();
    } catch (error) {
      console.error(error);
      setStatus(`Could not remove ${symbol}`);
    } finally {
      setBusySymbol(null);
    }
  }

  return (
    <main className="container">
      <div className="row">
        <div>
          <h1>Daily Report</h1>
          <p className="muted">Market intelligence dashboard</p>
        </div>
        <span className={`status ${status === "Backend connected" ? "ok" : ""}`}>
          {status}
        </span>
      </div>

      <nav className="nav" aria-label="Primary">
        {TABS.map((tab) => (
          <button
            key={tab}
            className={activeTab === tab ? "active" : ""}
            onClick={() => setActiveTab(tab)}
          >
            {tab}
          </button>
        ))}
      </nav>

      {activeTab === "Report" && (
        <section className="card">
          <h2>Daily Report</h2>
          <p className="muted">
            Live verified market data, news, macro and flow analysis will populate here as providers are connected.
          </p>
        </section>
      )}

      {activeTab === "Markets" && (
        <section>
          <div className="card">
            <h2>Watchlist</h2>
            <div className="ticker-add-row">
              <input
                className="search"
                value={newTicker}
                onChange={(e) => setNewTicker(e.target.value.toUpperCase())}
                placeholder="Add ticker, e.g. MU"
                maxLength={20}
                onKeyDown={(e) => {
                  if (e.key === "Enter") addTicker();
                }}
              />
              <button className="btn" onClick={addTicker} disabled={!newTicker.trim() || !!busySymbol}>
                Add
              </button>
            </div>
          </div>

          <div className="grid ticker-grid">
            {tickers.map((ticker) => (
              <article className="card ticker-card" key={ticker}>
                <div className="row">
                  <strong className="ticker-symbol">{ticker}</strong>
                  <button
                    className="btn danger"
                    onClick={() => removeTicker(ticker)}
                    disabled={!!busySymbol}
                  >
                    {busySymbol === ticker ? "Working..." : "Remove"}
                  </button>
                </div>
                <p className="muted">Market data pending provider connection.</p>
              </article>
            ))}
          </div>
        </section>
      )}

      {activeTab === "World News" && (
        <section className="card">
          <h2>World News</h2>
          <p className="muted">Relevant global market events will be clustered, sourced and timestamped here.</p>
        </section>
      )}

      {activeTab === "Large Flow" && (
        <section className="card">
          <h2>Large Flow</h2>
          <p className="muted">Large stock prints and unusual options activity will appear here once a flow provider is connected.</p>
        </section>
      )}

      {activeTab === "Macro" && (
        <section className="card">
          <h2>Macro</h2>
          <p className="muted">VIX, currencies, rates, commodities and macro outliers will appear here.</p>
        </section>
      )}

      {activeTab === "Settings" && (
        <section className="card">
          <h2>Settings</h2>
          <p className="muted">Report sections, thresholds, alerts and provider status will be configurable here.</p>
        </section>
      )}
    </main>
  );
}
