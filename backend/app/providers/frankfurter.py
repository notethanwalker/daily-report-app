from datetime import date, datetime, timedelta, timezone

import httpx

BASE_URL = "https://api.frankfurter.app"
SOURCE_URL = "https://frankfurter.dev/"


class FrankfurterError(RuntimeError):
    pass


class FrankfurterProvider:
    name = "Frankfurter"

    def _get(self, path: str, params: dict | None = None) -> dict:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            response = client.get(f"{BASE_URL}{path}", params=params or {})
            response.raise_for_status()
            return response.json()

    def major_currency_snapshot(self) -> dict:
        currencies = ["EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "CNY"]
        requested = ",".join(currencies)
        latest = self._get("/latest", {"from": "USD", "to": requested})

        latest_date = date.fromisoformat(latest["date"])
        window_start = latest_date - timedelta(days=10)
        history = self._get(
            f"/{window_start.isoformat()}..{latest_date.isoformat()}",
            {"from": "USD", "to": requested},
        )

        dated_rates = history.get("rates", {})
        target_date = latest_date - timedelta(days=7)
        available_dates = sorted(
            date.fromisoformat(day)
            for day in dated_rates.keys()
            if date.fromisoformat(day) <= target_date
        )
        if not available_dates:
            available_dates = sorted(date.fromisoformat(day) for day in dated_rates.keys())
        comparison_date = available_dates[-1] if available_dates else None
        historical_rates = dated_rates.get(comparison_date.isoformat(), {}) if comparison_date else {}
        latest_rates = latest.get("rates", {})

        rows = []
        for code in currencies:
            current = latest_rates.get(code)
            previous = historical_rates.get(code)
            change_percent = None
            if current is not None and previous not in (None, 0):
                change_percent = ((current / previous) - 1.0) * 100.0

            rows.append(
                {
                    "pair": f"USD/{code}",
                    "rate": current,
                    "seven_day_percent": change_percent,
                }
            )

        return {
            "base": "USD",
            "as_of": latest.get("date"),
            "comparison_date": comparison_date.isoformat() if comparison_date else None,
            "provider": self.name,
            "source_url": SOURCE_URL,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "rates": rows,
        }
