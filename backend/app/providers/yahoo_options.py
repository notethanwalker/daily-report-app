from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import yfinance as yf


class YahooOptionsError(RuntimeError):
    pass


def _num(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        n = float(value)
        return None if n != n else n
    except (TypeError, ValueError):
        return None


class YahooOptionsProvider:
    name = "Yahoo Finance options"

    def activity(self, symbol: str, expirations: int = 2, per_side: int = 8) -> dict[str, Any]:
        s = symbol.strip().upper()
        try:
            ticker = yf.Ticker(s)
            dates = list(ticker.options or [])[: max(1, min(expirations, 3))]
        except Exception as exc:
            raise YahooOptionsError(f"Yahoo options expirations unavailable for {s}") from exc
        if not dates:
            raise YahooOptionsError(f"No listed options expirations found for {s}")

        rows: list[dict[str, Any]] = []
        for expiry in dates:
            try:
                chain = ticker.option_chain(expiry)
            except Exception:
                continue
            for side, frame in (("call", getattr(chain, "calls", None)), ("put", getattr(chain, "puts", None))):
                if frame is None or getattr(frame, "empty", True):
                    continue
                for _, row in frame.iterrows():
                    volume = _num(row.get("volume")) or 0.0
                    oi = _num(row.get("openInterest")) or 0.0
                    bid = _num(row.get("bid"))
                    ask = _num(row.get("ask"))
                    last = _num(row.get("lastPrice"))
                    midpoint = ((bid + ask) / 2.0) if bid is not None and ask is not None and ask >= bid else last
                    premium = volume * midpoint * 100 if midpoint is not None else None
                    rows.append({
                        "event_type": "options_activity",
                        "symbol": s,
                        "provider": self.name,
                        "occurred_at": datetime.now(timezone.utc).isoformat(),
                        "source_url": f"https://finance.yahoo.com/quote/{s}/options",
                        "outlier_score": None,
                        "data": {
                            "side": side,
                            "strike": _num(row.get("strike")),
                            "expiration": expiry,
                            "premium": premium,
                            "contracts": volume,
                            "volume": volume,
                            "open_interest": oi,
                            "volume_oi_ratio": (volume / oi) if oi > 0 else None,
                            "last_price": last,
                            "bid": bid,
                            "ask": ask,
                            "direction": None,
                            "aggression": None,
                        },
                    })

        if not rows:
            raise YahooOptionsError(f"No options activity returned for {s}")
        rows.sort(key=lambda x: ((x.get("data") or {}).get("premium") or 0.0, (x.get("data") or {}).get("volume_oi_ratio") or 0.0), reverse=True)
        return {
            "provider": self.name,
            "source_url": f"https://finance.yahoo.com/quote/{s}/options",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "events": rows[: max(4, min(per_side * 2, 20))],
            "note": "Fallback is aggregate listed options activity, ranked by estimated premium (displayed volume × midpoint × 100). It is not a confirmed single trade or trader direction.",
        }
