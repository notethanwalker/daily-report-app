from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from ..providers.alpha_vantage import AlphaVantageProvider
from ..providers.yahoo_finance import YahooFinanceProvider


@dataclass(frozen=True)
class FreshnessPolicy:
    ttl_seconds: int
    priority: int


FRESHNESS_POLICIES = {
    "market": FreshnessPolicy(15 * 60, 100),
    "flow": FreshnessPolicy(30, 95),
    "news": FreshnessPolicy(10 * 60, 80),
    "macro": FreshnessPolicy(30 * 60, 75),
    "fx": FreshnessPolicy(60 * 60, 65),
    "history": FreshnessPolicy(30 * 24 * 60 * 60, 55),
    "fundamentals": FreshnessPolicy(7 * 24 * 60 * 60, 40),
    "daily_features": FreshnessPolicy(24 * 60 * 60, 50),
}

PROVIDER_POLICY = {
    "market": {"primary":"Twelve Data","fallback":None,"cache":"15m during market window"},
    "history": {"primary":"Twelve Data","fallback":None,"cache":"persistent daily bars"},
    "fundamentals": {"primary":"Alpha Vantage","fallback":"Yahoo Finance","cache":"7d"},
    "flow": {"primary":"SquawkFlow","fallback":"stored observations","cache":"30s"},
    "news": {"primary":"GDELT","fallback":"Google News RSS","cache":"10m"},
    "fx": {"primary":"Frankfurter","fallback":None,"cache":"60m"},
    "events": {"primary":"MacroRadar","fallback":"cached Yahoo earnings dates","cache":"request + persistent fundamentals"},
}


def is_stale(retrieved_at, data_class: str, now=None) -> bool:
    if retrieved_at is None:
        return True
    now = now or datetime.now(timezone.utc)
    if retrieved_at.tzinfo is None:
        retrieved_at = retrieved_at.replace(tzinfo=timezone.utc)
    policy = FRESHNESS_POLICIES.get(data_class, FreshnessPolicy(3600, 50))
    return (now - retrieved_at).total_seconds() > policy.ttl_seconds


class ProviderOrchestrator:
    """Central provider fallback policy. Provider-specific callers remain small and replaceable."""

    def fundamentals(self, symbol: str, allow_alpha: bool = True) -> tuple[dict, list[str]]:
        errors: list[str] = []
        providers: list[tuple[str, Callable[[], dict]]] = []
        if allow_alpha:
            providers.append(("Alpha Vantage", lambda: AlphaVantageProvider().overview(symbol)))
        providers.append(("Yahoo Finance", lambda: YahooFinanceProvider().overview(symbol)))
        for name, loader in providers:
            try:
                payload = loader()
                payload["orchestration_path"] = [p[0] for p in providers]
                return payload, errors
            except Exception as exc:
                errors.append(f"{name}: {exc}")
        raise RuntimeError("; ".join(errors) or "No fundamentals provider available")

    def describe(self) -> dict:
        return PROVIDER_POLICY
