from collections import defaultdict
from statistics import mean, pstdev
import time

from sqlalchemy.orm import Session

from ..models import HistoricalDailyBar, WatchlistItem
from ..providers.twelve_data import TwelveDataProvider, SOURCE_URL
from .rotation import SECTORS

THEME_BENCHMARKS = {
    "AAOI": "SMH",
    "SNDK": "SMH",
    "AXTI": "SMH",
    "NBIS": "XLK",
    "IONQ": "XLK",
    "OKLO": "XLE",
    "CRBS": "XLV",
    "BOTZ": "XLK",
    "GLD": "GLD",
}


def _ret(rows, idx, lookback):
    if idx < lookback:
        return None
    a = rows[idx - lookback]["close"]
    b = rows[idx]["close"]
    if not a:
        return None
    return (b / a - 1.0) * 100.0


def _rolling_avg_volume(rows, idx, lookback=20):
    if idx <= 0:
        return None
    start = max(0, idx - lookback)
    sample = [r["volume"] for r in rows[start:idx] if r["volume"] is not None]
    return mean(sample) if sample else None


def _rotation_score(day, week, month, rel_vol):
    score = (day or 0) * 0.25 + (week or 0) * 0.45 + (month or 0) * 0.30
    if rel_vol and rel_vol > 1:
        score *= min(rel_vol, 2.0)
    return round(score, 3)


def backfill_2026(db: Session, year: int = 2026) -> dict:
    symbols = list(SECTORS.keys())
    watchlist = [r.symbol for r in db.query(WatchlistItem).all()]
    for s in THEME_BENCHMARKS:
        if s in watchlist and s not in symbols:
            symbols.append(s)

    provider = TwelveDataProvider()
    inserted = 0
    refreshed = []
    failures = []
    for idx, symbol in enumerate(symbols):
        if idx:
            time.sleep(8.2)
        try:
            raw = provider.daily_history(symbol, outputsize=260)
            values = raw.get("values") or raw.get("data") or []
            for row in values:
                dt = str(row.get("datetime") or row.get("date") or "")[:10]
                if not dt.startswith(f"{year}-"):
                    continue
                close = row.get("close")
                volume = row.get("volume")
                try:
                    close_f = float(close)
                    volume_f = float(volume or 0)
                except (TypeError, ValueError):
                    continue
                existing = db.query(HistoricalDailyBar).filter(
                    HistoricalDailyBar.symbol == symbol,
                    HistoricalDailyBar.bar_date == dt,
                ).first()
                if existing:
                    existing.close = close_f
                    existing.volume = volume_f
                else:
                    db.add(HistoricalDailyBar(
                        symbol=symbol,
                        bar_date=dt,
                        close=close_f,
                        volume=volume_f,
                        provider="Twelve Data",
                        source_url=SOURCE_URL,
                    ))
                    inserted += 1
            db.commit()
            refreshed.append(symbol)
        except Exception as exc:
            db.rollback()
            failures.append({"symbol": symbol, "reason": str(exc)[:160]})
    return {"year": year, "symbols": refreshed, "inserted": inserted, "failures": failures}


def build_macro_history(db: Session, year: int = 2026) -> dict:
    rows = db.query(HistoricalDailyBar).filter(
        HistoricalDailyBar.bar_date >= f"{year}-01-01",
        HistoricalDailyBar.bar_date <= f"{year}-12-31",
    ).order_by(HistoricalDailyBar.symbol, HistoricalDailyBar.bar_date).all()

    by_symbol = defaultdict(list)
    for r in rows:
        by_symbol[r.symbol].append({"date": r.bar_date, "close": r.close, "volume": r.volume})

    sector_series = {}
    all_dates = set()
    for symbol, name in SECTORS.items():
        series = by_symbol.get(symbol, [])
        out = []
        for i, row in enumerate(series):
            day = _ret(series, i, 1)
            week = _ret(series, i, 5)
            month = _ret(series, i, 21)
            avg_vol = _rolling_avg_volume(series, i)
            rel_vol = row["volume"] / avg_vol if avg_vol else None
            score = _rotation_score(day, week, month, rel_vol)
            out.append({
                "date": row["date"],
                "symbol": symbol,
                "name": name,
                "close": row["close"],
                "day_percent": day,
                "seven_day_percent": week,
                "thirty_day_percent": month,
                "relative_volume": rel_vol,
                "rotation_score": score,
            })
            all_dates.add(row["date"])
        sector_series[symbol] = out

    date_snapshots = []
    lookup = {s: {r["date"]: r for r in series} for s, series in sector_series.items()}
    for dt in sorted(all_dates):
        current = [m[dt] for m in lookup.values() if dt in m and m[dt]["seven_day_percent"] is not None]
        current.sort(key=lambda x: x["rotation_score"], reverse=True)
        if not current:
            continue
        leaders = current[:3]
        laggards = list(reversed(current[-3:]))
        spread = leaders[0]["rotation_score"] - laggards[0]["rotation_score"] if laggards else None
        date_snapshots.append({
            "date": dt,
            "leaders": leaders,
            "laggards": laggards,
            "spread": round(spread, 3) if spread is not None else None,
        })

    outliers = []
    for stock, bench in THEME_BENCHMARKS.items():
        stock_rows = by_symbol.get(stock, [])
        bench_rows = by_symbol.get(bench, [])
        if not stock_rows or not bench_rows:
            continue
        s_map = {r["date"]: r for r in stock_rows}
        b_map = {r["date"]: r for r in bench_rows}
        shared = sorted(set(s_map) & set(b_map))
        stock_order = [s_map[d] for d in shared]
        bench_order = [b_map[d] for d in shared]
        diffs = []
        raw_points = []
        for i, dt in enumerate(shared):
            sr = _ret(stock_order, i, 5)
            br = _ret(bench_order, i, 5)
            if sr is None or br is None:
                continue
            diff = sr - br
            diffs.append(diff)
            raw_points.append((dt, sr, br, diff))
        sigma = pstdev(diffs) if len(diffs) > 2 else 0
        mu = mean(diffs) if diffs else 0
        for dt, sr, br, diff in raw_points:
            z = (diff - mu) / sigma if sigma else 0
            if abs(z) >= 1.5 and abs(br) >= 2.0:
                outliers.append({
                    "date": dt,
                    "symbol": stock,
                    "benchmark": bench,
                    "stock_5d_percent": round(sr, 2),
                    "benchmark_5d_percent": round(br, 2),
                    "relative_gap_points": round(diff, 2),
                    "z_score": round(z, 2),
                    "direction": "resisted sector move" if (sr * br < 0 or abs(sr) < abs(br) * 0.35) else "amplified sector move",
                })
    outliers.sort(key=lambda x: abs(x["z_score"]), reverse=True)

    return {
        "year": year,
        "data_points": len(rows),
        "sector_series": sector_series,
        "rotation_timeline": date_snapshots,
        "stock_outliers": outliers[:100],
        "methodology": "Historical rotation uses 1-day, 5-trading-day and 21-trading-day returns with relative-volume amplification. Stock outliers compare 5-day returns with a mapped sector/theme benchmark and flag large standardized divergences.",
    }
