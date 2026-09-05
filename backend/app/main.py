import os
import time

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .models import MarketSnapshot, WatchlistItem
from .providers.frankfurter import FrankfurterProvider
from .providers.gdelt import GdeltProvider
from .providers.twelve_data import TwelveDataError, TwelveDataProvider
from .services.calculations import build_market_snapshot

app = FastAPI(
    title="Daily Report API",
    version="0.5"
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


def get_market_snapshot(symbol: str) -> dict:
    symbol = symbol.strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="Ticker symbol is required")

    cached = _market_cache.get(symbol)
    if cached and (time.time() - cached[0]) < MARKET_CACHE_TTL_SECONDS:
        return {**cached[1], "cache": "hit"}

    try:
        provider = TwelveDataProvider()
        raw = provider.market_snapshot_raw(symbol)
        snapshot = build_market_snapshot(raw)
    except TwelveDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Market data unavailable for {symbol}: {exc}") from exc

    _market_cache[symbol] = (time.time(), snapshot)
    return {**snapshot, "cache": "miss"}


@app.get("/")
def root():
    return {
        "status": "ok",
        "service": "Daily Report API"
    }


@app.get("/api/v1/health")
def health():
    return {
        "status": "ok",
        "version": "0.5",
        "providers": {
            "twelve_data": {
                "configured": bool(os.getenv("TWELVE_DATA_API_KEY")),
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
def market_snapshot(symbol: str, db: Session = Depends(get_db)):
    result = get_market_snapshot(symbol)

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
            "secondary_market_data": None,
            "world_news": "GDELT",
            "currencies": "Frankfurter",
        },
        "cache_ttl_seconds": {
            "market": MARKET_CACHE_TTL_SECONDS,
            "news": NEWS_CACHE_TTL_SECONDS,
            "currencies": CURRENCY_CACHE_TTL_SECONDS,
        },
    }
