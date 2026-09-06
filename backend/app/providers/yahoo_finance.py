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


def _earnings_date(calendar):
    if calendar is None:
        return None
    try:
        value = calendar.get("Earnings Date") if hasattr(calendar, "get") else None
        if value is None and hasattr(calendar, "index") and "Earnings Date" in calendar.index:
            value = calendar.loc["Earnings Date"]
        if hasattr(value, "tolist"):
            value = value.tolist()
        if isinstance(value, (list, tuple)):
            value = next((x for x in value if x is not None), None)
        if hasattr(value, "to_pydatetime"):
            value = value.to_pydatetime()
        if isinstance(value, datetime):
            return value.date().isoformat()
        if value:
            text = str(value)
            return text[:10] if len(text) >= 10 else None
    except Exception:
        return None
    return None


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
            try:
                hist=ticker.history(period="5d",auto_adjust=False)
                quote=_float(hist["Close"].dropna().iloc[-1]) if hist is not None and not hist.empty else None
            except Exception: quote=None
            try: calendar=ticker.calendar
            except Exception: calendar=None
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

        quote=quote or _float(fast.get("last_price")) or num("currentPrice","regularMarketPrice")
        revenues=_series_values(income,["Total Revenue"])
        eps_values=_series_values(income,["Diluted EPS","Basic EPS"])
        shares=_float(fast.get("shares")) or num("sharesOutstanding","impliedSharesOutstanding")
        revenue_ttm=sum(revenues[:4]) if len(revenues)>=4 else num("totalRevenue")
        eps_ttm=sum(eps_values[:4]) if len(eps_values)>=4 else num("trailingEps","forwardEps")
        market_cap=num("marketCap") or (quote*shares if quote and shares else None)
        pe=num("trailingPE","forwardPE") or (quote/eps_ttm if quote and eps_ttm and eps_ttm>0 else None)
        ps=num("priceToSalesTrailing12Months") or (market_cap/revenue_ttm if market_cap and revenue_ttm and revenue_ttm>0 else None)
        earnings_growth=None
        if len(eps_values)>=5 and eps_values[4] != 0:
            earnings_growth=(eps_values[0]-eps_values[4])/abs(eps_values[4])
        if earnings_growth is None:earnings_growth=num("earningsGrowth")
        revenue_growth=None
        if len(revenues)>=5 and revenues[4] != 0:
            revenue_growth=(revenues[0]-revenues[4])/abs(revenues[4])
        if revenue_growth is None:revenue_growth=num("revenueGrowth")
        peg=num("pegRatio","trailingPegRatio")
        if peg is None and pe and earnings_growth and earnings_growth>0:
            peg=pe/(earnings_growth*100 if earnings_growth<=5 else earnings_growth)

        payload = {
            "symbol": s,
            "pe_ratio": pe,
            "forward_pe": num("forwardPE"),
            "peg_ratio": peg,
            "price_to_sales_ratio": ps,
            "eps": eps_ttm,
            "revenue_ttm": revenue_ttm,
            "shares_outstanding": shares,
            "quarterly_revenue_growth_yoy": revenue_growth,
            "quarterly_earnings_growth_yoy": earnings_growth,
            "market_cap": market_cap,
            "earnings_date": _earnings_date(calendar),
            "sector": info.get("sector") or info.get("category"),
            "industry": info.get("industry"),
            "provider": self.name,
            "source_url": f"{SOURCE_ROOT}/{s}",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "valuation_refresh_version": 3,
        }
        if all(payload.get(k) is None for k in ["pe_ratio", "peg_ratio", "price_to_sales_ratio", "eps", "revenue_ttm", "shares_outstanding", "market_cap"]):
            raise YahooFinanceError(f"Yahoo Finance returned no usable valuation fields for {s}")
        return payload
