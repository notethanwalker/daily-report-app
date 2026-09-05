from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Daily Report API", version="0.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://daily-report-app-pearl.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

WATCHLIST = [
    "SPY", "QQQ", "AAOI", "NBIS", "SNDK", "AXTI", "CRBS",
    "IONQ", "OKLO", "GLD", "SMH", "EUV", "DRAM", "BOTZ", "VIX"
]

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
        "version": "0.1"
    }

@app.get("/api/v1/watchlist")
def watchlist():
    return {
        "tickers": WATCHLIST
    }

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
            "flow"
        ],
        "indicators": [
            "100ma",
            "200ma"
        ],
        "flow_thresholds": {
            "stock_trade_dollars": 1000000,
            "options_premium_dollars": 100000,
            "volume_to_open_interest": 2.0
        }
    }
