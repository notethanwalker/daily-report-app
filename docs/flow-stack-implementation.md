# Large Flow Stack — implementation plan

Target stack: **SquawkFlow -> curated X alerts -> Bullflow corroboration -> FINRA delayed confirmation -> Daily Report scoring engine**.

## Design rules

- Raw facts and directional inference remain separate.
- A large call is not automatically bullish and a large put is not automatically bearish.
- Every event keeps provider, source URL, provider timestamp, retrieval timestamp, and raw payload.
- Cross-source matches increase confidence; they do not overwrite source facts.
- Delayed FINRA data is labeled delayed and never presented as real-time.
- X posts are discovery signals only until corroborated.
- Do not scrape X HTML. Use an official API only if credentials/cost are acceptable.
- Keep all external credentials in Render environment variables.

## Normalized flow event

```json
{
  "event_type": "option|equity|social_alert|finra_block",
  "symbol": "NVDA",
  "provider": "squawkflow",
  "occurred_at": "ISO-8601",
  "source_url": "https://...",
  "contract": {
    "side": "call|put|null",
    "strike": 0.0,
    "expiration": "YYYY-MM-DD|null"
  },
  "execution": {
    "price": 0.0,
    "bid": 0.0,
    "ask": 0.0,
    "contracts": 0,
    "premium": 0.0,
    "volume": 0,
    "open_interest": 0,
    "volume_oi_ratio": 0.0,
    "trade_type": "sweep|block|split|unknown",
    "aggression": "ask|above_ask|mid|bid|below_bid|unknown"
  },
  "social": {
    "account": null,
    "post_id": null,
    "text": null
  },
  "provider_score": null,
  "raw": {}
}
```

## Scoring model

Keep two independent outputs.

### Flow significance (0-100)

- 30% size abnormality: premium / contracts vs historical distribution
- 20% volume vs open interest
- 20% execution aggression relative to bid/ask
- 15% persistence/repetition in same symbol/contract family
- 10% cross-source corroboration
- 5% underlying relative volume / market context

Weights should be configurable later.

### Directional inference

Output one of `bullish`, `bearish`, `neutral`, `ambiguous` plus confidence 0-100.

Evidence can include:

- ask/above-ask vs bid/below-bid execution
- call/put side
- repeated same-direction prints
- underlying price response
- option IV/volume context when available
- possible hedge/spread ambiguity

Never infer direction solely from call/put type.

## Source adapters

### 1. SquawkFlow — primary discovery

Implement first. Adapter responsibilities:

- fetch unusual options flow
- normalize symbol, call/put, strike, expiration, premium, contracts, volume, OI, timestamps, trade type, bid/ask if present
- preserve raw payload
- provider-level request timeout/retry
- provider circuit breaker for 429/5xx
- cache recent responses to stay inside the free request allowance

Environment:

- `FLOW_SQUAWKFLOW_ENABLED=true|false`
- `FLOW_SQUAWKFLOW_BASE_URL=`
- no API key unless their access model changes

### 2. Curated X — secondary discovery

Initial accounts:

- `FL0WG0D`
- `unusual_whales`

Use official X API only. Do not scrape site HTML.

Normalize posts into `social_alert` events. Extract ticker, premium, contract terms, side, and timestamp only when explicitly present. Attach extraction confidence. Do not convert an unverified post into a validated option trade.

Environment:

- `FLOW_X_ENABLED=false` by default
- `X_API_BEARER_TOKEN=`
- `FLOW_X_ACCOUNTS=FL0WG0D,unusual_whales`

### 3. Bullflow — corroboration

Treat as corroboration until automated-use terms are confirmed.

Expected use:

- find matching symbol/contract/time-window event
- enrich trade type, bid/ask classification, size-vs-OI, significance when available
- retain Bullflow as a distinct source record

Environment:

- `FLOW_BULLFLOW_ENABLED=false` until ingestion permission is confirmed

### 4. FINRA — delayed institutional confirmation

Use public ATS/OTC block/weekly datasets as delayed context, never as a real-time trade feed.

Expected use:

- aggregate institutional activity baselines
- compare current/previous reporting windows
- add slow confirmation evidence to symbols already flagged by faster sources

Environment:

- `FLOW_FINRA_ENABLED=true`

## Deduplication / correlation

Create an event fingerprint using the best available fields:

`symbol + expiration + strike + call_put + occurred_at bucket + contracts/premium bucket`

Do not collapse different provider records into one row. Instead, create a correlation layer that points multiple source rows to a common cluster. This preserves provenance.

Suggested match windows:

- options machine feeds: +/- 90 seconds
- social alerts: +/- 10 minutes
- FINRA: same security/reporting window only; never exact-trade matching

## Persistence changes

Existing `flow_events` can hold normalized provider rows. Tomorrow add, if needed:

- `event_key` / fingerprint
- `correlation_id`
- `direction_label`
- `direction_confidence`
- `significance_score`
- `corroboration_count`
- `analysis_version`

Prefer a migration before production schema changes instead of expanding `Base.metadata.create_all` indefinitely.

## API target

`GET /api/v1/flow/recent`

Filters:

- symbol
- event_type
- provider
- min_significance
- direction
- limit

Response should expose:

- normalized facts
- significance score
- directional inference + confidence
- corroborating sources
- source links
- latency/delay label

Add `POST /api/v1/flow/refresh` only after auth/rate limiting exists; do not leave a provider-consuming refresh endpoint open publicly.

## Frontend target

Large Flow tab sections:

1. **Highest significance** — sorted by significance, regardless of direction.
2. **Directional candidates** — only events with sufficient direction confidence.
3. **Social discovery** — clearly labeled unverified alerts.
4. **Institutional confirmation** — FINRA delayed context.

Each event expands inline and shows:

- ticker / option contract
- occurred time and retrieval delay
- premium / contracts / volume / OI / vol-OI
- bid/ask execution classification
- trade type
- significance score
- direction + confidence
- corroborating providers
- raw source links
- caveat if hedge/spread/closing activity cannot be excluded

## Implementation order for next update

1. Add common provider adapter + normalized schema.
2. Implement SquawkFlow adapter and rate-limit cache.
3. Implement event fingerprinting, persistence, significance scoring.
4. Wire `/api/v1/flow/recent` to scored events.
5. Build Large Flow frontend cards/table and inline detail view.
6. Add X adapter behind disabled feature flag; enable only after API credentials/cost decision.
7. Add Bullflow adapter only after automated-use terms are verified.
8. Add FINRA ingestion for delayed confirmation/baselines.
9. Add scheduled refresh cadence sized to provider limits.
10. Add auth/rate limiting before exposing manual refresh.

## Acceptance criteria

- No provider can silently classify call=buy/bullish or put=sell/bearish.
- Every visible event links back to at least one original source.
- Provider failures degrade independently; one source cannot blank the entire Flow tab.
- UI states whether each source is real-time, delayed, social/unverified, or corroborated.
- Free/minimal-cost limits are enforced in code, not only documented.
- Provider raw values are never invented by AI.
