import os
import time

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .models import WatchlistItem
from .providers.twelve_data import TwelveDataError, TwelveDataProvider
from .services.calculations import build_market_snapshot

app = FastAPI(
    title="Daily Report API",
    version="0.3"
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

MARKET_CACHE_TTL_SECONDS = 300
_market_cache: dict[str, tuple[float, dict]] = {}


class TickerRequest(BaseModel):
    symbol: str


def get_market_snapshot(symbol: str, force: bool = False) -> dict:
    symbol = symbol.strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="Ticker symbol is required")

    cached = _market_cache.get(symbol)
    if cached and not force and (time.time() - cached[0]) < MARKET_CACHE_TTL_SECONDS:
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
        "version": "0.3",
        "providers": {
            "twelve_data": {
                "configured": bool(os.getenv("TWELVE_DATA_API_KEY")),
            }
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
def market_snapshot(symbol: str, force: bool = False):
    return get_market_snapshot(symbol, force=force)


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
        },
        "market_cache_ttl_seconds": MARKET_CACHE_TTL_SECONDS,
    }
