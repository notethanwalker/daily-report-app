"use client";

import { useEffect, useState } from "react";

const API =
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "https://daily-report-api-ero2.onrender.com";

export default function Home() {
  const [tickers, setTickers] = useState<string[]>([]);
  const [status, setStatus] = useState("Connecting to backend...");
  const [newTicker, setNewTicker] = useState("");

  useEffect(() => {
    async function loadWatchlist() {
      try {
        const response = await fetch(`${API}/api/v1/watchlist`);

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

    loadWatchlist();
  }, []);

  function addTicker() {
    const symbol = newTicker.trim().toUpperCase();

    if (symbol && !tickers.includes(symbol)) {
      setTickers([...tickers, symbol]);
    }

    setNewTicker("");
  }

  function removeTicker(symbol: string) {
    setTickers(tickers.filter((ticker) => ticker !== symbol));
  }

  return (
    <main>
      <h1>Daily Report</h1>
      <p>{status}</p>

      <section>
        <h2>Watchlist</h2>

        <div>
          <input
            value={newTicker}
            onChange={(e) => setNewTicker(e.target.value)}
            placeholder="Ticker"
            onKeyDown={(e) => {
              if (e.key === "Enter") addTicker();
            }}
          />

          <button onClick={addTicker}>Add</button>
        </div>

        <div>
          {tickers.map((ticker) => (
            <div key={ticker}>
              <strong>{ticker}</strong>{" "}
              <button onClick={() => removeTicker(ticker)}>Remove</button>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
