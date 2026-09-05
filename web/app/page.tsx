"use client";

import { useEffect, useState } from "react";

const API =
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "https://daily-report-api-ero2.onrender.com";

const TABS = ["Report", "Markets", "World News", "Large Flow", "Macro", "Settings"];

type MarketSnapshot = {
  symbol: string;
  price: number | null;
  previous_close: number | null;
  change: number | null;
  change_percent: number | null;
  seven_day_percent: number | null;
  thirty_day_percent: number | null;
  ytd_percent: number | null;
  high_52_week: number | null;
  low_52_week: number | null;
  ma100: number | null;
  ma200: number | null;
  price_vs_ma100_percent: number | null;
  price_vs_ma200_percent: number | null;
  volume: number | null;
  average_volume_20d: number | null;
  relative_volume: number | null;
  as_of: string | null;
  provider: string;
  source_url: string;
  verification_status: string;
  verification?: {
    primary_provider?: string;
    secondary_provider?: string;
    verified_fields?: string[];
    discrepancy_fields?: string[];
    error?: string;
  };
  data_note?: string;
};

type NewsArticle = {
  title: string;
  url: string;
  domain?: string | null;
  source_country?: string | null;
  language?: string | null;
  published_at?: string | null;
};

type CurrencyRate = {
  pair: string;
  rate: number | null;
  seven_day_percent: number | null;
};

type SecuritySearchResult = {
  symbol: string;
  name?: string | null;
  exchange?: string | null;
  country?: string | null;
  currency?: string | null;
  type?: string | null;
};

type ReportOutlier = {
  symbol: string;
  score: number;
  reason: string;
  change_percent: number | null;
  seven_day_percent: number | null;
  relative_volume: number | null;
};

type DailyReport = {
  id?: number;
  generated_at: string;
  report_date: string;
  watchlist_count: number;
  market_data_count: number;
  missing_market_symbols: string[];
  vix: MarketSnapshot | null;
  markets: MarketSnapshot[];
  currencies: { rates?: CurrencyRate[]; provider?: string; as_of?: string };
  top_market_news: NewsArticle[];
  outliers: ReportOutlier[];
  verification_summary: { verified: number; primary_only: number };
  notes: string[];
};

function money(value: number | null) {
  return value == null ? "—" : `$${value.toFixed(2)}`;
}

function percent(value: number | null) {
  return value == null ? "—" : `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function compact(value: number | null) {
  if (value == null) return "—";
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

export default function Home() {
  const [tickers, setTickers] = useState<string[]>([]);
  const [status, setStatus] = useState("Connecting to backend...");
  const [newTicker, setNewTicker] = useState("");
  const [busySymbol, setBusySymbol] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("Report");
  const [marketData, setMarketData] = useState<Record<string, MarketSnapshot>>({});
  const [marketErrors, setMarketErrors] = useState<Record<string, string>>({});
  const [news, setNews] = useState<NewsArticle[]>([]);
  const [newsStatus, setNewsStatus] = useState("Not loaded");
  const [currencies, setCurrencies] = useState<CurrencyRate[]>([]);
  const [currencyStatus, setCurrencyStatus] = useState("Not loaded");
  const [searchResults, setSearchResults] = useState<SecuritySearchResult[]>([]);
  const [searchStatus, setSearchStatus] = useState("");
  const [report, setReport] = useState<DailyReport | null>(null);
  const [reportStatus, setReportStatus] = useState("Loading report...");

  async function loadWatchlist() {
    try {
      const response = await fetch(`${API}/api/v1/watchlist`, { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      setTickers(data.tickers || []);
      setStatus("Backend connected");
    } catch (error) {
      console.error(error);
      setStatus("Backend connection failed");
    }
  }

  async function loadReport() {
    setReportStatus("Loading report...");
    try {
      const response = await fetch(`${API}/api/v1/report/current`, { cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(data?.detail || `HTTP ${response.status}`);
      setReport(data);
      setReportStatus(`Generated ${new Date(data.generated_at).toLocaleString()}`);
    } catch (error) {
      setReportStatus(error instanceof Error ? error.message : "Report unavailable");
    }
  }

  async function generateReport() {
    setReportStatus("Saving report snapshot...");
    try {
      const response = await fetch(`${API}/api/v1/report/generate`, {
        method: "POST",
        cache: "no-store",
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data?.detail || `HTTP ${response.status}`);
      setReport(data);
      setReportStatus(`Saved report #${data.id} · ${new Date(data.generated_at).toLocaleString()}`);
    } catch (error) {
      setReportStatus(error instanceof Error ? error.message : "Could not save report");
    }
  }

  useEffect(() => {
    loadWatchlist();
    loadReport();
  }, []);

  useEffect(() => {
    const query = newTicker.trim();
    if (query.length < 2) {
      setSearchResults([]);
      setSearchStatus("");
      return;
    }

    const timer = window.setTimeout(async () => {
      setSearchStatus("Searching...");
      try {
        const response = await fetch(`${API}/api/v1/securities/search?q=${encodeURIComponent(query)}`, { cache: "no-store" });
        const data = await response.json();
        if (!response.ok) throw new Error(data?.detail || `HTTP ${response.status}`);
        setSearchResults(data.results || []);
        setSearchStatus(data.results?.length ? "" : "No matches");
      } catch (error) {
        setSearchResults([]);
        setSearchStatus(error instanceof Error ? error.message : "Search unavailable");
      }
    }, 450);

    return () => window.clearTimeout(timer);
  }, [newTicker]);

  async function loadMarketData(symbol: string) {
    if (busySymbol) return;
    setBusySymbol(symbol);
    setMarketErrors((current) => ({ ...current, [symbol]: "" }));

    try {
      const response = await fetch(`${API}/api/v1/markets/${encodeURIComponent(symbol)}`, { cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(data?.detail || `HTTP ${response.status}`);
      setMarketData((current) => ({ ...current, [symbol]: data }));
      await loadReport();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Market data unavailable";
      setMarketErrors((current) => ({ ...current, [symbol]: message }));
    } finally {
      setBusySymbol(null);
    }
  }

  async function loadWorldNews() {
    setNewsStatus("Loading...");
    try {
      const response = await fetch(`${API}/api/v1/news/world?limit=30`, { cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(data?.detail || `HTTP ${response.status}`);
      setNews(data.articles || []);
      setNewsStatus(`${data.articles?.length || 0} articles · ${data.provider}`);
    } catch (error) {
      setNewsStatus(error instanceof Error ? error.message : "News unavailable");
    }
  }

  async function loadCurrencies() {
    setCurrencyStatus("Loading...");
    try {
      const response = await fetch(`${API}/api/v1/macro/currencies`, { cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(data?.detail || `HTTP ${response.status}`);
      setCurrencies(data.rates || []);
      setCurrencyStatus(`As of ${data.as_of || "—"} · ${data.provider}`);
    } catch (error) {
      setCurrencyStatus(error instanceof Error ? error.message : "Currency data unavailable");
    }
  }

  async function addTicker(symbolOverride?: string) {
    const symbol = (symbolOverride || newTicker).trim().toUpperCase();
    if (!symbol || busySymbol) return;
    setBusySymbol(symbol);
    setStatus(`Adding ${symbol}...`);

    try {
      const response = await fetch(`${API}/api/v1/watchlist`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol }),
      });
      if (!response.ok) {
        const detail = await response.json().catch(() => null);
        throw new Error(detail?.detail || `HTTP ${response.status}`);
      }
      setNewTicker("");
      setSearchResults([]);
      await loadWatchlist();
      await loadReport();
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
      const response = await fetch(`${API}/api/v1/watchlist/${encodeURIComponent(symbol)}`, { method: "DELETE" });
      if (!response.ok) {
        const detail = await response.json().catch(() => null);
        throw new Error(detail?.detail || `HTTP ${response.status}`);
      }
      setMarketData((current) => {
        const next = { ...current };
        delete next[symbol];
        return next;
      });
      await loadWatchlist();
      await loadReport();
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
        <span className={`status ${status === "Backend connected" ? "ok" : ""}`}>{status}</span>
      </div>

      <nav className="nav" aria-label="Primary">
        {TABS.map((tab) => (
          <button key={tab} className={activeTab === tab ? "active" : ""} onClick={() => setActiveTab(tab)}>
            {tab}
          </button>
        ))}
      </nav>

      {activeTab === "Report" && (
        <section>
          <div className="card row">
            <div>
              <h2>Daily Report</h2>
              <p className="muted">{reportStatus}</p>
            </div>
            <div className="report-actions">
              <button className="btn" onClick={loadReport}>Refresh view</button>
              <button className="btn" onClick={generateReport}>Save snapshot</button>
            </div>
          </div>

          {report && (
            <>
              <div className="report-summary-grid">
                <article className="card stat-card"><span>Watchlist</span><strong>{report.watchlist_count}</strong></article>
                <article className="card stat-card"><span>Market data loaded</span><strong>{report.market_data_count}</strong></article>
                <article className="card stat-card"><span>2-source verified</span><strong>{report.verification_summary.verified}</strong></article>
                <article className="card stat-card"><span>Primary only</span><strong>{report.verification_summary.primary_only}</strong></article>
              </div>

              {report.missing_market_symbols.length > 0 && (
                <div className="card report-warning">
                  <strong>Market data not loaded yet</strong>
                  <p className="muted">Load these symbols from the Markets tab to populate them without burning requests all at once.</p>
                  <div className="symbol-chips">{report.missing_market_symbols.map((symbol) => <span key={symbol}>{symbol}</span>)}</div>
                </div>
              )}

              {report.vix && (
                <article className="card report-vix">
                  <div><span className="eyebrow">VIX</span><strong>{report.vix.price?.toFixed(2) ?? "—"}</strong></div>
                  <div><span>Daily</span><strong className={(report.vix.change_percent ?? 0) >= 0 ? "positive" : "negative"}>{percent(report.vix.change_percent)}</strong></div>
                  <div><span>7D</span><strong>{percent(report.vix.seven_day_percent)}</strong></div>
                </article>
              )}

              <div className="card">
                <h2>Markets</h2>
                <div className="report-table-wrap">
                  <table className="report-table">
                    <thead><tr><th>Symbol</th><th>Price</th><th>Day</th><th>7D</th><th>100MA</th><th>200MA</th><th>Rel Vol</th><th>Verify</th></tr></thead>
                    <tbody>
                      {report.markets.map((item) => (
                        <tr key={item.symbol}>
                          <td><strong>{item.symbol}</strong></td>
                          <td>{money(item.price)}</td>
                          <td className={(item.change_percent ?? 0) >= 0 ? "positive" : "negative"}>{percent(item.change_percent)}</td>
                          <td>{percent(item.seven_day_percent)}</td>
                          <td>{money(item.ma100)}</td>
                          <td>{money(item.ma200)}</td>
                          <td>{item.relative_volume == null ? "—" : `${item.relative_volume.toFixed(2)}x`}</td>
                          <td>{item.verification_status === "verified" ? "2-source" : "primary"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="grid report-columns">
                <section className="card">
                  <h2>Notable Outliers</h2>
                  <div className="outlier-list">
                    {report.outliers.map((item) => (
                      <div className="outlier-row" key={item.symbol}>
                        <div><strong>{item.symbol}</strong><p>{item.reason}</p></div>
                        <span>{item.score.toFixed(1)}</span>
                      </div>
                    ))}
                  </div>
                </section>

                <section className="card">
                  <h2>Major Currencies</h2>
                  <div className="outlier-list">
                    {(report.currencies.rates || []).map((item) => (
                      <div className="outlier-row" key={item.pair}>
                        <div><strong>{item.pair}</strong><p>{item.rate == null ? "—" : item.rate.toFixed(4)}</p></div>
                        <span className={(item.seven_day_percent ?? 0) >= 0 ? "positive" : "negative"}>{percent(item.seven_day_percent)}</span>
                      </div>
                    ))}
                  </div>
                </section>
              </div>

              <section className="card">
                <h2>Top Market News</h2>
                <div className="news-list compact-news">
                  {report.top_market_news.map((article) => (
                    <a className="news-card-inline" href={article.url} target="_blank" rel="noreferrer" key={article.url}>
                      <strong>{article.title}</strong>
                      <span>{article.domain || "Source"}{article.published_at ? ` · ${article.published_at}` : ""}</span>
                    </a>
                  ))}
                </div>
              </section>
            </>
          )}
        </section>
      )}

      {activeTab === "Markets" && (
        <section>
          <div className="card">
            <h2>Watchlist</h2>
            <p className="muted">Search by ticker or company. Market values use Twelve Data; Alpha Vantage verification is rationed to one persisted check per symbol per day.</p>
            <div className="ticker-add-row">
              <div className="search-wrap">
                <input className="search" value={newTicker} onChange={(e) => setNewTicker(e.target.value)} placeholder="Search ticker or company" maxLength={64} onKeyDown={(e) => { if (e.key === "Enter") addTicker(); }} />
                {(searchResults.length > 0 || searchStatus) && (
                  <div className="search-results">
                    {searchResults.map((result) => (
                      <button key={`${result.symbol}-${result.exchange || ""}`} onClick={() => addTicker(result.symbol)}>
                        <strong>{result.symbol}</strong>
                        <span>{result.name || result.type || "Security"}{result.exchange ? ` · ${result.exchange}` : ""}</span>
                      </button>
                    ))}
                    {searchStatus && <p className="muted search-message">{searchStatus}</p>}
                  </div>
                )}
              </div>
              <button className="btn" onClick={() => addTicker()} disabled={!newTicker.trim() || !!busySymbol}>Add</button>
            </div>
          </div>

          <div className="grid ticker-grid">
            {tickers.map((ticker) => {
              const data = marketData[ticker];
              const error = marketErrors[ticker];
              const verificationLabel = data?.verification_status === "verified"
                ? "verified by 2 sources"
                : data?.verification?.error
                  ? "primary only · secondary deferred"
                  : data?.verification_status?.replaceAll("_", " ") || "primary only";

              return (
                <article className="card ticker-card" key={ticker}>
                  <div className="row">
                    <strong className="ticker-symbol">{ticker}</strong>
                    <button className="btn danger" onClick={() => removeTicker(ticker)} disabled={!!busySymbol}>{busySymbol === ticker ? "Working..." : "Remove"}</button>
                  </div>
                  {!data && !error && <button className="btn load-market" onClick={() => loadMarketData(ticker)} disabled={!!busySymbol}>{busySymbol === ticker ? "Loading..." : "Load market data"}</button>}
                  {error && <div className="market-error"><p>{error}</p><button className="btn" onClick={() => loadMarketData(ticker)} disabled={!!busySymbol}>Retry</button></div>}
                  {data && (
                    <div className="market-metrics">
                      <div className="price-line"><strong>{money(data.price)}</strong><span className={(data.change_percent ?? 0) >= 0 ? "positive" : "negative"}>{percent(data.change_percent)}</span></div>
                      <div className="metric-grid">
                        <span>7D <strong>{percent(data.seven_day_percent)}</strong></span>
                        <span>30D <strong>{percent(data.thirty_day_percent)}</strong></span>
                        <span>YTD <strong>{percent(data.ytd_percent)}</strong></span>
                        <span>100MA <strong>{money(data.ma100)}</strong></span>
                        <span>200MA <strong>{money(data.ma200)}</strong></span>
                        <span>Rel Vol <strong>{data.relative_volume == null ? "—" : `${data.relative_volume.toFixed(2)}x`}</strong></span>
                        <span>52W High <strong>{money(data.high_52_week)}</strong></span>
                        <span>52W Low <strong>{money(data.low_52_week)}</strong></span>
                        <span>Volume <strong>{compact(data.volume)}</strong></span>
                      </div>
                      <p className="source-line">As of {data.as_of || "—"} · {verificationLabel} · <a href={data.source_url} target="_blank" rel="noreferrer">{data.provider}</a></p>
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        </section>
      )}

      {activeTab === "World News" && (
        <section>
          <div className="card row"><div><h2>World News</h2><p className="muted">{newsStatus}</p></div><button className="btn" onClick={loadWorldNews}>Refresh</button></div>
          <div className="news-list">
            {news.map((article) => (
              <a className="card news-card" href={article.url} target="_blank" rel="noreferrer" key={article.url}>
                <strong>{article.title}</strong>
                <p className="source-line">{article.domain || "Source"}{article.source_country ? ` · ${article.source_country}` : ""}{article.published_at ? ` · ${article.published_at}` : ""}</p>
              </a>
            ))}
          </div>
        </section>
      )}

      {activeTab === "Large Flow" && <section className="card"><h2>Large Flow</h2><p className="muted">Large stock prints and unusual options activity require a dedicated flow-data provider.</p></section>}

      {activeTab === "Macro" && (
        <section>
          <div className="card row"><div><h2>Major Currencies</h2><p className="muted">{currencyStatus}</p></div><button className="btn" onClick={loadCurrencies}>Refresh</button></div>
          <div className="grid">
            {currencies.map((item) => (
              <article className="card currency-card" key={item.pair}>
                <strong>{item.pair}</strong>
                <div className="price-line"><span>{item.rate == null ? "—" : item.rate.toFixed(4)}</span><span className={(item.seven_day_percent ?? 0) >= 0 ? "positive" : "negative"}>{percent(item.seven_day_percent)}</span></div>
                <p className="muted">7-day USD cross-rate change</p>
              </article>
            ))}
          </div>
        </section>
      )}

      {activeTab === "Settings" && <section className="card"><h2>Settings</h2><p className="muted">Report sections, thresholds, alerts and provider status will be configurable here.</p></section>}
    </main>
  );
}
