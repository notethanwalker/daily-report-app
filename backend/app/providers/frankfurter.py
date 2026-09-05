from datetime import date, datetime, timedelta, timezone

import httpx

BASE_URL = "https://api.frankfurter.app"
SOURCE_URL = "https://frankfurter.dev/"


class FrankfurterError(RuntimeError):
    pass


class FrankfurterProvider:
    name = "Frankfurter"

    def _get(self, path: str, params: dict | None = None) -> dict:
        with httpx.Client(timeout=20.0) as client:
            response = client.get(f"{BASE_URL}{path}", params=params or {})
            response.raise_for_status()
            return response.json()

    def major_currency_snapshot(self) -> dict:
        currencies = ["EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "CNY"]
        latest = self._get("/latest", {"from": "USD", "to": ",".join(currencies)})

        target_date = date.today() - timedelta(days=7)
        historical = self._get(
            f"/{target_date.isoformat()}",
            {"from": "USD", "to": ",".join(currencies)},
        )

        rows = []
        latest_rates = latest.get("rates", {})
        historical_rates = historical.get("rates", {})

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
            "comparison_date": historical.get("date"),
            "provider": self.name,
            "source_url": SOURCE_URL,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "rates": rows,
        }
