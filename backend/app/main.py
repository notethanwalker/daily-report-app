import os
import time
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .models import MarketSnapshot, SecondaryVerificationCache, WatchlistItem
from .providers.alpha_vantage import AlphaVantageError, AlphaVantageProvider
from .providers.frankfurter import FrankfurterProvider
from .providers.gdelt import GdeltProvider
from .providers.twelve_data import TwelveDataError, TwelveDataProvider
from .services.calculations import build_market_snapshot
from .services.validation import build_secondary_metrics, cross_check_market_snapshot

app = FastAPI(
    title="Daily Report API",
    version="0.7"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://daily-report-app-pearl.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Base.metadata.create_all(bind=engine)

DEFAULT_WATCHLIST = [
    "SPY", "QQQ", "AAOI", "NBIS", "SNDK",
    "AXTI", "CRBS", "IONQ", "OKLO", "GLD",
    "SMH", "EUV", "DRAM", "BOTZ", "VIX"
]

MARKET_CACHE_TTL_SECONDS = 900
SECONDARY_CACHE_TTL_SECONDS = 86400
ALPHA_VANTAGE_DAILY_BUDGET = 20
NEWS_CACHE_TTL_SECONDS = 600
CURRENCY_CACHE_TTL_SECONDS = 3600

_market_cache: dict[str, tuple[float, dict]] = {}
_shared_cache: dict[str, tuple[float, dict]] = {}


class TickerRequest(BaseModel):
    symbol: str


def _cached_shared(key: str, ttl: int, loader) -> dict:
    cached = _shared_cache.get(key)
    if cached and (time.time() - cached[0]) < ttl:
        return {**cached[1], "cache": "hit"}

    data = loader()
    _shared_cache[key] = (time.time(), data)
    return {**data, "cache": "miss"}


def _secondary_cache_age_seconds(row: SecondaryVerificationCache) -> float:
    retrieved_at = row.retrieved_at
    if retrieved_at.tzinfo is None:
        retrieved_at = retrieved_at.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - retrieved_at).total_seconds()


def _alpha_requests_used_today(db: Session) -> int:
    day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        db.query(SecondaryVerificationCache)
        .filter(
            SecondaryVerificationCache.provider == "Alpha Vantage",
            SecondaryVerificationCache.retrieved_at >= day_start,
        )
        .count()
    )


def get_secondary_metrics(symbol: str, db: Session) -> dict:
    symbol = symbol.strip().upper()
    cached = db.get(SecondaryVerificationCache, symbol)

    if cached and _secondary_cache_age_seconds(cached) < SECONDARY_CACHE_TTL_SECONDS:
        if cached.payload.get("error"):
            raise AlphaVantageError(cached.payload["error"])
        return cached.payload

    used_today = _alpha_requests_used_today(db)
    if used_today >= ALPHA_VANTAGE_DAILY_BUDGET:
        raise AlphaVantageError(
            f"Daily secondary-verification budget reached ({used_today}/{ALPHA_VANTAGE_DAILY_BUDGET}); "
            "using primary market data until the next UTC day."
        )

    try:
        raw = AlphaVantageProvider().daily_history(symbol)
        metrics = build_secondary_metrics(raw)
        payload = metrics
    except Exception as exc:
        payload = {"error": str(exc)}
        if cached:
            cached.provider = "Alpha Vantage"
            cached.payload = payload
            cached.retrieved_at = datetime.now(timezone.utc)
        else:
            db.add(
                SecondaryVerificationCache(
                    symbol=symbol,
                    provider="Alpha Vantage",
                    payload=payload,
                    retrieved_at=datetime.now(timezone.utc),
                )
            )
        db.commit()
        raise

    if cached:
        cached.provider = "Alpha Vantage"
        cached.payload = payload
        cached.retrieved_at = datetime.now(timezone.utc)
    else:
        db.add(
            SecondaryVerificationCache(
                symbol=symbol,
                provider="Alpha Vantage",
                payload=payload,
                retrieved_at=datetime.now(timezone.utc),
            )
        )
    db.commit()
    return metrics


def get_market_snapshot(symbol: str, db: Session, verify: bool = True) -> dict:
    symbol = symbol.strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="Ticker symbol is required")

    cached = _market_cache.get(symbol)
    if cached and (time.time() - cached[0]) < MARKET_CACHE_TTL_SECONDS:
        return {**cached[1], "cache": "hit"}

    try:
        raw = TwelveDataProvider().market_snapshot_raw(symbol)
        snapshot = build_market_snapshot(raw)
    except TwelveDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Market data unavailable for {symbol}: {exc}") from exc

    if verify and os.getenv("ALPHA_VANTAGE_API_KEY"):
        try:
            secondary = get_secondary_metrics(symbol, db)
            snapshot.update(cross_check_market_snapshot(snapshot, secondary))
        except Exception as exc:
            snapshot["verification_status"] = "primary_only"
            snapshot["verification"] = {
                "primary_provider": snapshot.get("provider"),
                "secondary_provider": "Alpha Vantage",
                "error": str(exc),
            }

    _market_cache[symbol] = (time.time(), snapshot)
    return {**snapshot, "cache": "miss"}


@app.get("/")
def root():
    return {
        "status": "ok",
        "service": "Daily Report API"
    }


@app.get("/api/v1/health")
def health(db: Session = Depends(get_db)):
    used_today = _alpha_requests_used_today(db) if os.getenv("ALPHA_VANTAGE_API_KEY") else 0
    return {
        "status": "ok",
        "version": "0.7",
        "providers": {
            "twelve_data": {
                "configured": bool(os.getenv("TWELVE_DATA_API_KEY")),
            },
            "alpha_vantage": {
                "configured": bool(os.getenv("ALPHA_VANTAGE_API_KEY")),
                "daily_budget": ALPHA_VANTAGE_DAILY_BUDGET,
                "used_today": used_today,
                "remaining_today": max(ALPHA_VANTAGE_DAILY_BUDGET - used_today, 0),
            },
            "gdelt": {"configured": True},
            "frankfurter": {"configured": True},
        },
    }


@app.get("/api/v1/watchlist")
def get_watchlist(db: Session = Depends(get_db)):
    items = db.query(WatchlistItem).order_by(
        WatchlistItem.created_at
    ).all()

    if not items:
        for symbol in DEFAULT_WATCHLIST:
            db.add(WatchlistItem(symbol=symbol))

        db.commit()

        items = db.query(WatchlistItem).order_by(
            WatchlistItem.created_at
        ).all()

    return {
        "tickers": [item.symbol for item in items]
    }


@app.post("/api/v1/watchlist")
def add_ticker(
    request: TickerRequest,
    db: Session = Depends(get_db)
):
    symbol = request.symbol.strip().upper()

    if not symbol:
        raise HTTPException(
            status_code=400,
            detail="Ticker symbol is required"
        )

    if len(symbol) > 20 or not all(char.isalnum() or char in ".-^" for char in symbol):
        raise HTTPException(status_code=400, detail="Invalid ticker symbol format")

    existing = db.get(WatchlistItem, symbol)

    if existing:
        return {
            "status": "exists",
            "symbol": symbol
        }

    db.add(WatchlistItem(symbol=symbol))
    db.commit()

    return {
        "status": "added",
        "symbol": symbol
    }


@app.delete("/api/v1/watchlist/{symbol}")
def remove_ticker(
    symbol: str,
    db: Session = Depends(get_db)
):
    symbol = symbol.strip().upper()

    item = db.get(WatchlistItem, symbol)

    if not item:
        raise HTTPException(
            status_code=404,
            detail="Ticker not found"
        )

    db.delete(item)
    db.commit()
    _market_cache.pop(symbol, None)

    return {
        "status": "removed",
        "symbol": symbol
    }


@app.get("/api/v1/markets/{symbol}")
def market_snapshot(
    symbol: str,
    verify: bool = True,
    db: Session = Depends(get_db),
):
    result = get_market_snapshot(symbol, db=db, verify=verify)

    if result.get("cache") == "miss":
        db.add(
            MarketSnapshot(
                symbol=(result.get("symbol") or symbol).upper(),
                as_of=str(result.get("as_of") or ""),
                provider=str(result.get("provider") or "unknown"),
                payload={key: value for key, value in result.items() if key != "cache"},
            )
        )
        db.commit()

    return result


@app.get("/api/v1/markets/{symbol}/history")
def market_snapshot_history(
    symbol: str,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    symbol = symbol.strip().upper()
    rows = (
        db.query(MarketSnapshot)
        .filter(MarketSnapshot.symbol == symbol)
        .order_by(MarketSnapshot.retrieved_at.desc())
        .limit(limit)
        .all()
    )

    return {
        "symbol": symbol,
        "snapshots": [
            {
                "id": row.id,
                "as_of": row.as_of,
                "provider": row.provider,
                "retrieved_at": row.retrieved_at.isoformat(),
                "data": row.payload,
            }
            for row in rows
        ],
    }


@app.get("/api/v1/news/world")
def world_news(limit: int = Query(default=25, ge=1, le=50)):
    try:
        return _cached_shared(
            f"world_news:{limit}",
            NEWS_CACHE_TTL_SECONDS,
            lambda: GdeltProvider().search(
                '(economy OR markets OR trade OR tariffs OR sanctions OR semiconductor OR "artificial intelligence" OR energy OR oil OR central bank)',
                max_records=limit,
                timespan="24h",
            ),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"World news unavailable: {exc}") from exc


@app.get("/api/v1/news/market")
def market_news(limit: int = Query(default=15, ge=1, le=30)):
    try:
        return _cached_shared(
            f"market_news:{limit}",
            NEWS_CACHE_TTL_SECONDS,
            lambda: GdeltProvider().search(
                '(stocks OR "stock market" OR equities OR Nasdaq OR S&P OR Federal Reserve OR earnings OR inflation)',
                max_records=limit,
                timespan="24h",
            ),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Market news unavailable: {exc}") from exc


@app.get("/api/v1/macro/currencies")
def currencies():
    try:
        return _cached_shared(
            "major_currencies",
            CURRENCY_CACHE_TTL_SECONDS,
            lambda: FrankfurterProvider().major_currency_snapshot(),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Currency data unavailable: {exc}") from exc


@app.get("/api/v1/report/config")
def config():
    return {
        "sections": [
            "vix",
            "markets",
            "currencies",
            "macro",
            "market_news",
            "world_news",
            "outliers",
            "flow",
        ],
        "indicators": [
            "100ma",
            "200ma"
        ],
        "flow_thresholds": {
            "stock_trade_dollars": 1_000_000,
            "options_premium_dollars": 100_000,
            "volume_to_open_interest": 2.0,
        },
        "providers": {
            "primary_market_data": "Twelve Data",
            "secondary_market_data": "Alpha Vantage",
            "world_news": "GDELT",
            "currencies": "Frankfurter",
        },
        "verification": {
            "secondary_cache_ttl_seconds": SECONDARY_CACHE_TTL_SECONDS,
            "alpha_vantage_daily_budget": ALPHA_VANTAGE_DAILY_BUDGET,
            "strategy": "One secondary request per symbol per 24h, persisted across deploys; hard cap leaves provider headroom.",
        },
        "cache_ttl_seconds": {
            "market": MARKET_CACHE_TTL_SECONDS,
            "news": NEWS_CACHE_TTL_SECONDS,
            "currencies": CURRENCY_CACHE_TTL_SECONDS,
        },
    }
