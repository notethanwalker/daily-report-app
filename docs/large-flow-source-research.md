# Large Flow source research

Updated: 2026-09-05

## Goal
Build the Large Flow tab with the lowest feasible recurring cost while keeping raw facts, source provenance, and directional inference separate.

## Source tiers

### Tier 1 — structured/public feeds

**SquawkFlow public API**
- Public unusual-options endpoint: `/api/v1/options/flow/unusual`.
- Anonymous access currently permits 60 requests/hour/IP; public flow data is cached on a short interval.
- Useful as the first machine-readable discovery source because it does not require scraping social media or paying for OPRA directly.
- Store every observation with provider timestamp, retrieval timestamp, original fields, and source URL.
- Treat provider score as evidence only; calculate our own significance and direction scores.

**Bullflow public ticker pages**
- Public pages expose completed-session unusual options flow with contract, timestamp, premium, execution side, size, sweep/block classification, size-vs-OI, and a provider significance score.
- Valuable for end-of-session validation and historical examples.
- Do not assume public HTML pages are licensed for automated redistribution. Before production ingestion, check/obtain permission or an official API/feed.

**FINRA OTC/ATS data**
- Keep as authoritative delayed equity-block context and historical baselines.
- Not real-time and not trade-level options data.

### Tier 2 — social discovery

**X: @FL0WG0D (Flow God)**
- Frequently posts large options-print summaries such as ticker, premium, call/put, and inferred buyer/seller language.
- Appears affiliated with/promotes Bullflow, so social alerts may be downstream of that platform rather than an independent source.
- Best use: discovery and alert corroboration, not raw market truth.

**X: @unusual_whales**
- Broad market/news account tied to Unusual Whales' flow platform. Posts can surface notable flow but the account also publishes general market/news content.
- Best use: discovery/corroboration. Structured Unusual Whales API is preferable if budget later permits.

**X ingestion method**
- Prefer official X API rather than HTML scraping.
- Current X API is pay-per-use; post reads are priced per resource. Polling only a small curated account list can therefore stay low-cost if frequency and returned-post counts are tightly capped.
- Parse candidate posts with regex/structured extraction for ticker, premium, call/put, strike, expiration, buyer/seller wording, timestamp, and post URL.
- Never convert phrases such as `call buyer` into guaranteed bullish direction. Save the author's label separately from our inference.

### Tier 3 — paid structured providers, only if justified

**Unusual Whales API**
- Real-time options flow with bid/ask, greeks, OI, volume, dark-pool data and WebSocket support.
- Strong technical fit but currently above the project's free/minimal-cost target for ongoing API use.
- Free/trial access can be used for one-time schema testing; do not architect the product around a trial.

**SpotGamma / OptionStrat / other flow platforms**
- Useful for methodology comparison and validation.
- Subscription pricing generally exceeds the desired recurring cost for this project.

## Recommended v1 pipeline

1. SquawkFlow public unusual-flow API for machine-readable discovery.
2. X API for a very small curated list: initially @FL0WG0D and @unusual_whales, later other high-signal accounts only if they add independent value.
3. Bullflow public pages as manual/research corroboration until automation rights/API access are clear.
4. FINRA for delayed equity-block confirmation and historical normalization.
5. Existing Twelve Data price/volume context for underlying confirmation.
6. Normalize all candidates into `flow_events`.
7. Deduplicate by symbol + contract + time window + premium/size similarity.
8. Score independently:
   - significance: size/premium abnormality, vol/OI, execution aggressiveness, persistence;
   - confirmation: agreement across independent sources and underlying price/volume response;
   - direction: bullish/bearish/neutral/ambiguous with a separate confidence score.

## Important implementation rules
- Preserve original source URL and exact source timestamp.
- Mark delayed sources as delayed.
- Keep social/vendor classifications separate from our computed classification.
- Do not infer causality from a large print alone.
- Never fabricate missing strike, expiration, bid/ask, OI, or trade-side data.
- Cache aggressively to stay inside free/low-cost quotas.
