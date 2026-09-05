from datetime import datetime, timezone

import yfinance as yf

SOURCE_ROOT = "https://finance.yahoo.com/quote"


class YahooFinanceError(RuntimeError):
    pass


class YahooFinanceProvider:
    name = "Yahoo Finance"

    def overview(self, symbol: str) -> dict:
        s = symbol.strip().upper()
        try:
            ticker = yf.Ticker(s)
            info = ticker.get_info() or {}
        except Exception as exc:
            raise YahooFinanceError(f"Yahoo Finance request failed for {s}") from exc

        if not info:
            raise YahooFinanceError(f"No Yahoo Finance fundamentals returned for {s}")

        def num(*keys):
            for key in keys:
                value = info.get(key)
                if value in (None, "", "None", "-"):
                    continue
                try:
                    return float(value)
                except (TypeError, ValueError):
                    continue
            return None

        payload = {
            "symbol": s,
            "pe_ratio": num("trailingPE", "forwardPE"),
            "forward_pe": num("forwardPE"),
            "peg_ratio": num("pegRatio", "trailingPegRatio"),
            "price_to_sales_ratio": num("priceToSalesTrailing12Months"),
            "eps": num("trailingEps", "forwardEps"),
            "revenue_ttm": num("totalRevenue"),
            "quarterly_revenue_growth_yoy": num("revenueGrowth"),
            "quarterly_earnings_growth_yoy": num("earningsGrowth"),
            "market_cap": num("marketCap"),
            "sector": info.get("sector") or info.get("category"),
            "industry": info.get("industry"),
            "provider": self.name,
            "source_url": f"{SOURCE_ROOT}/{s}",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }
        if all(payload.get(k) is None for k in ["pe_ratio", "peg_ratio", "price_to_sales_ratio", "eps", "revenue_ttm", "market_cap"]):
            raise YahooFinanceError(f"Yahoo Finance returned no usable valuation fields for {s}")
        return payload
