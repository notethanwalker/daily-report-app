from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

import httpx

CNN_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
CNN_PAGE = "https://www.cnn.com/markets/fear-and-greed"
AAII_URL = "https://www.aaii.com/sentiment-survey"
CBOE_URL = "https://www.cboe.com/markets/us/options/market-statistics/daily"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"


def _score_label(score: float) -> str:
    if score <= 20:
        return "Extreme fear"
    if score <= 40:
        return "Fear"
    if score < 60:
        return "Neutral"
    if score < 80:
        return "Greed"
    return "Extreme greed"


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def _cnn() -> dict[str, Any]:
    headers = {"User-Agent": UA, "Accept": "application/json, text/plain, */*", "Origin": "https://www.cnn.com", "Referer": "https://www.cnn.com/"}
    with httpx.Client(timeout=15.0, follow_redirects=True) as client:
        r = client.get(CNN_URL, headers=headers)
        r.raise_for_status()
        d = r.json()
    fg = d.get("fear_and_greed") or {}
    score = float(fg["score"])
    return {
        "id": "cnn_fear_greed",
        "name": "CNN Fear & Greed",
        "score": round(score, 1),
        "label": str(fg.get("rating") or _score_label(score)).replace("_", " ").title(),
        "detail": f"Previous close {float(fg.get('previous_close', score)):.1f}",
        "as_of": fg.get("timestamp"),
        "source_url": CNN_PAGE,
        "provider": "CNN",
        "scale": "0 fear → 100 greed",
    }


def _aaii() -> dict[str, Any]:
    with httpx.Client(timeout=15.0, follow_redirects=True) as client:
        r = client.get(AAII_URL, headers={"User-Agent": UA, "Accept": "text/html"})
        r.raise_for_status()
        text = re.sub(r"\s+", " ", r.text)
    bull = re.search(r"Bullish\s*</?[^>]*>*\s*([0-9]+(?:\.[0-9]+)?)%", text, re.I)
    bear = re.search(r"Bearish\s*</?[^>]*>*\s*([0-9]+(?:\.[0-9]+)?)%", text, re.I)
    if not bull or not bear:
        plain = re.sub(r"<[^>]+>", " ", text)
        bull = re.search(r"Bullish\s+([0-9]+(?:\.[0-9]+)?)%", plain, re.I)
        bear = re.search(r"Bearish\s+([0-9]+(?:\.[0-9]+)?)%", plain, re.I)
    if not bull or not bear:
        raise ValueError("AAII sentiment values not found")
    bullish = float(bull.group(1)); bearish = float(bear.group(1))
    spread = bullish - bearish
    score = _clamp(50.0 + spread * 1.6)
    m = re.search(r"Week ending\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", re.sub(r"<[^>]+>", " ", text), re.I)
    return {
        "id": "aaii_survey",
        "name": "AAII Investor Sentiment",
        "score": round(score, 1),
        "label": "Bullish" if spread >= 8 else "Bearish" if spread <= -8 else "Mixed",
        "detail": f"Bull {bullish:.1f}% · Bear {bearish:.1f}% · spread {spread:+.1f} pp",
        "as_of": m.group(1) if m else None,
        "source_url": AAII_URL,
        "provider": "AAII",
        "scale": "Normalized from bull-bear spread",
        "raw": {"bullish": bullish, "bearish": bearish, "spread": round(spread, 1)},
    }


def _cboe() -> dict[str, Any]:
    with httpx.Client(timeout=15.0, follow_redirects=True) as client:
        r = client.get(CBOE_URL, headers={"User-Agent": UA, "Accept": "text/html"})
        r.raise_for_status()
        plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text))
    m = re.search(r"TOTAL PUT/CALL RATIO\s+([0-9]+(?:\.[0-9]+)?)", plain, re.I)
    if not m:
        raise ValueError("Cboe put/call ratio not found")
    ratio = float(m.group(1))
    # Lower put/call ratios are more risk-on. 0.55≈75, 1.0≈45, 1.35≈20.
    score = _clamp(111.7 - 66.7 * ratio)
    label = "Risk-on" if ratio < 0.75 else "Balanced" if ratio <= 1.0 else "Defensive"
    return {
        "id": "cboe_put_call",
        "name": "Cboe Put/Call",
        "score": round(score, 1),
        "label": label,
        "detail": f"Total put/call ratio {ratio:.2f}",
        "as_of": datetime.now(timezone.utc).date().isoformat(),
        "source_url": CBOE_URL,
        "provider": "Cboe",
        "scale": "Normalized; lower put/call = more risk-on",
        "raw": {"total_put_call_ratio": ratio},
    }


def sentiment_snapshot() -> dict[str, Any]:
    meters = []
    errors = []
    for loader, name in [(_cnn, "CNN"), (_aaii, "AAII"), (_cboe, "Cboe")]:
        try:
            meters.append(loader())
        except Exception:
            errors.append(name)
    return {
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "meters": meters,
        "unavailable": errors,
        "note": "External meters use each publisher's current public reading. AAII and Cboe are normalized to a common 0–100 display only for visual comparison; their raw source values remain shown.",
    }
