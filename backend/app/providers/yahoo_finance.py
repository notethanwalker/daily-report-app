from datetime import datetime, timezone

import yfinance as yf

SOURCE_ROOT = "https://finance.yahoo.com/quote"


class YahooFinanceError(RuntimeError):
    pass


def _float(value):
    try:
        if value is None:
            return None
        value=float(value)
        return None if value != value else value
    except (TypeError, ValueError):
        return None


def _series_values(frame, names, limit=5):
    if frame is None or getattr(frame, "empty", True):
        return []
    for name in names:
        if name in frame.index:
            vals=[]
            for value in frame.loc[name].dropna().tolist()[:limit]:
                n=_float(value)
                if n is not None: vals.append(n)
            if vals:return vals
    return []


class YahooFinanceProvider:
    name = "Yahoo Finance"

    def overview(self, symbol: str) -> dict:
        s = symbol.strip().upper()
        try:
            ticker = yf.Ticker(s)
            info = ticker.get_info() or {}
            try: fast=dict(ticker.fast_info)
            except Exception: fast={}
            try: income=ticker.quarterly_income_stmt
            except Exception: income=None
        except Exception as exc:
            raise YahooFinanceError(f"Yahoo Finance request failed for {s}") from exc

        def num(*keys):
            for key in keys:
                value = info.get(key)
                if value in (None, "", "None", "-"):
                    continue
                n=_float(value)
                if n is not None:return n
            return None

        revenues=_series_values(income,["Total Revenue"])
        eps_values=_series_values(income,["Diluted EPS","Basic EPS"])
        shares=_float(fast.get("shares")) or num("sharesOutstanding","impliedSharesOutstanding")
        revenue_ttm=sum(revenues[:4]) if len(revenues)>=4 else num("totalRevenue")
        eps_ttm=sum(eps_values[:4]) if len(eps_values)>=4 else num("trailingEps","forwardEps")
        earnings_growth=None
        if len(eps_values)>=5 and eps_values[4] != 0:
            earnings_growth=(eps_values[0]-eps_values[4])/abs(eps_values[4])
        if earnings_growth is None:earnings_growth=num("earningsGrowth")
        revenue_growth=None
        if len(revenues)>=5 and revenues[4] != 0:
            revenue_growth=(revenues[0]-revenues[4])/abs(revenues[4])
        if revenue_growth is None:revenue_growth=num("revenueGrowth")

        payload = {
            "symbol": s,
            "pe_ratio": num("trailingPE", "forwardPE"),
            "forward_pe": num("forwardPE"),
            "peg_ratio": num("pegRatio", "trailingPegRatio"),
            "price_to_sales_ratio": num("priceToSalesTrailing12Months"),
            "eps": eps_ttm,
            "revenue_ttm": revenue_ttm,
            "shares_outstanding": shares,
            "quarterly_revenue_growth_yoy": revenue_growth,
            "quarterly_earnings_growth_yoy": earnings_growth,
            "market_cap": num("marketCap"),
            "sector": info.get("sector") or info.get("category"),
            "industry": info.get("industry"),
            "provider": self.name,
            "source_url": f"{SOURCE_ROOT}/{s}",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }
        if all(payload.get(k) is None for k in ["pe_ratio", "peg_ratio", "price_to_sales_ratio", "eps", "revenue_ttm", "shares_outstanding", "market_cap"]):
            raise YahooFinanceError(f"Yahoo Finance returned no usable valuation fields for {s}")
        return payload
