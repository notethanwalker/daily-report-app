# Intraday Research Warehouse

Status: research branch. No production deployment implied.

## Purpose
Persist reusable intraday market data so QQQ/SPY and options-flow strategies can be tested without repeatedly downloading the same vendor history.

## Tables
- `intraday_bars`: normalized stock/ETF OHLCV with provider/feed provenance.
- `option_intraday_bars`: normalized option-contract OHLCV with underlying, expiry, type and strike.
- `intraday_ingestion_runs`: resumable/auditable ingestion jobs.
- `intraday_research_results`: frozen strategy parameters, metrics and provenance.

Raw vendor payloads are retained in JSON for auditability. Unique constraints include provider, so cross-vendor comparisons do not overwrite one another.

## Free-source adapters
### Twelve Data
Uses existing `TWELVE_DATA_API_KEY`. Supports stock/ETF intraday backfill with date windows.

### Alpaca
Environment variables:
- `ALPACA_API_KEY` (or `APCA_API_KEY_ID`)
- `ALPACA_API_SECRET` (or `APCA_API_SECRET_KEY`)

Stocks default to the free IEX feed. Historical options use the free indicative feed when available. Alpaca options history begins February 2024; the indicative feed is not true OPRA aggressor tape and must not be described as true Net Drift.

### Tiingo
Environment variable:
- `TIINGO_API_TOKEN`

Defaults to Tiingo's derived multi-venue intraday endpoint; IEX can be selected explicitly.

## API
Authenticated routes:
- `GET /api/v1/research/intraday/coverage?symbol=QQQ`
- `POST /api/v1/research/intraday/backfill/stocks`
- `POST /api/v1/research/intraday/backfill/options/alpaca`
- `POST /api/v1/research/intraday/tests/net-drift`

Example stock backfill:
```json
{"symbol":"QQQ","start":"2024-02-01","end":"2026-09-29","provider":"alpaca","interval":"1min","feed":"iex"}
```

Option backfill accepts explicit contract metadata to prevent ambiguous symbol parsing.

## Net Drift proxy v2
The test is causal:
1. Select the nearest common call/put strike to the 09:30 ET QQQ open.
2. Restrict to same-day expiry.
3. Use only option bars from 09:30 through the configured signal time.
4. Signed option pressure = premium × sign(option bar close-open) × (+1 call / -1 put).
5. Normalize by total absolute option premium.
6. Require signed flow direction to agree with QQQ direction from 09:30 to the signal.
7. Measure the configured forward horizon from signal time.
8. Compare with price-momentum-only baseline.

This is a proxy for aggressor-classified Net Drift. Promotion requires tick trades plus contemporaneous NBBO or a vendor-provided aggressor-classified history.

## Research controls
- No look-ahead strike selection.
- Provider/feed stored on every row.
- Cross-provider rows coexist.
- Backtests save parameters and provenance.
- Production trading is not connected to these endpoints.
