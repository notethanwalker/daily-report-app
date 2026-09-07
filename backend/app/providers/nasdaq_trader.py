from __future__ import annotations

from datetime import datetime, timezone

import httpx

NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
SOURCE_URL = "https://www.nasdaqtrader.com/Trader.aspx?id=SymbolDirDefs"


class NasdaqTraderError(RuntimeError):
    pass


def _parse_pipe(text: str) -> list[dict]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return []
    headers = lines[0].split("|")
    out = []
    for line in lines[1:]:
        if line.startswith("File Creation Time"):
            continue
        values = line.split("|")
        if len(values) != len(headers):
            continue
        out.append(dict(zip(headers, values)))
    return out


def _clean_symbol(value: str | None) -> str | None:
    s = str(value or "").strip().upper()
    if not s or s in {"N/A", "NONE"}:
        return None
    return s


class NasdaqTraderProvider:
    name = "Nasdaq Trader"

    def _get_text(self, url: str) -> str:
        try:
            with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                response = client.get(url, headers={"User-Agent": "daily-report-app/1.0"})
                response.raise_for_status()
                return response.text
        except Exception as exc:
            raise NasdaqTraderError("Nasdaq Trader symbol directory request failed") from exc

    def us_equity_universe(self) -> dict:
        nasdaq = _parse_pipe(self._get_text(NASDAQ_LISTED_URL))
        other = _parse_pipe(self._get_text(OTHER_LISTED_URL))
        rows: dict[str, dict] = {}

        for r in nasdaq:
            symbol = _clean_symbol(r.get("Symbol"))
            if not symbol or str(r.get("Test Issue") or "N").upper() == "Y":
                continue
            rows[symbol] = {
                "symbol": symbol,
                "name": r.get("Security Name") or None,
                "exchange": "NASDAQ",
                "asset_type": "ETF" if str(r.get("ETF") or "N").upper() == "Y" else "Stock",
            }

        exchange_map = {"A": "NYSE American", "N": "NYSE", "P": "NYSE Arca", "Z": "Cboe BZX", "V": "IEX"}
        for r in other:
            symbol = _clean_symbol(r.get("ACT Symbol") or r.get("NASDAQ Symbol"))
            if not symbol or str(r.get("Test Issue") or "N").upper() == "Y":
                continue
            rows[symbol] = {
                "symbol": symbol,
                "name": r.get("Security Name") or None,
                "exchange": exchange_map.get(str(r.get("Exchange") or "").upper(), r.get("Exchange") or None),
                "asset_type": "ETF" if str(r.get("ETF") or "N").upper() == "Y" else "Stock",
            }

        return {
            "provider": self.name,
            "source_url": SOURCE_URL,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "symbols": sorted(rows.values(), key=lambda x: x["symbol"]),
        }
