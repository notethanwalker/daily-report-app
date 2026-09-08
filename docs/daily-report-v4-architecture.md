# Daily Report v4 — Decision Stack

## Archive boundary

- `legacy-daily-report` preserves the pre-v4 application at commit `a697fc0207365e3cbaa2632e035068eabf65e6f3`.
- `daily-report-v4-rebuild` is the clean development branch for the new build.
- Existing features are not removed; each is assigned to the closest decision layer.

## Product model

Daily Report v4 is a four-layer decision pipeline:

1. **Research** — establish what is happening in markets, sectors, portfolios and individual securities.
2. **Macro** — measure market regime, sector strength/weakness and likely rotation paths.
3. **Opportunity** — rank attractive sectors and securities using the research and macro layers.
4. **Deployment** — convert upstream evidence into suggested new-capital allocation on a monthly / bi-monthly cadence.

The application should make the pipeline explicit: **market state → sector state → candidate opportunity → capital deployment**.

## Layer 1: Research

### Existing capabilities to retain
- Daily Report
- Markets/watchlists
- Portfolio
- Security research workspaces
- World news
- Events
- Large flow
- Fundamental data
- Theses
- Alerts
- Data health/provenance

### v4 direction
- A unified security workspace should expose price/technical state, fundamentals, news/events, flow, portfolio exposure, thesis state, source freshness and historical changes.
- A sector workspace should aggregate constituents, breadth, relative strength, earnings/news/events and flow.
- Research data must retain `provider`, `as_of`, `retrieved_at`, verification state and methodology wherever possible.

## Layer 2: Macro

### Existing capabilities to retain
- Macro
- Regime
- Currency data
- Sector rotation
- Breadth/liquidity proxies
- Relevant world news and events

### v4 direction
- Replace isolated heatmaps with a persistent sector/rotation state model.
- Track level, momentum, acceleration/deceleration, breadth, relative volume and regime compatibility.
- Maintain a rotation history so the app can distinguish one-day noise from durable transitions.
- Produce explicit confidence and evidence fields rather than a single unexplained score.

## Layer 3: Opportunity

### Existing capabilities to retain
- Opportunities
- Technical buy scores
- 100MA proximity
- Williams %R
- Flow outliers
- Catalysts/events
- Fundamental context
- Watchlist discovery

### v4 direction
- Use a funnel to avoid brute-force provider scans:
  1. rank sectors/themes from cached macro data;
  2. generate candidate symbols from watchlists, portfolios, sector universes and incrementally refreshed registries;
  3. score only candidates using cached technical/fundamental/event/flow features;
  4. queue expensive refreshes only for the highest-value stale candidates.
- Persist score components and prior scores so score changes are explainable.

## Layer 4: Deployment

### Canonical research finding to preserve
**Williams Priority is a cross-sectional new-capital allocation model, not primarily an individual-stock timing rule.**

For a selected basket, use the prior completed 14-month Williams %R to rank securities from most oversold to least oversold. New capital is allocated by rank while existing positions are left untouched unless a separate rebalancing model is explicitly enabled.

### Named basket
**AI Buildout Basket:** `NBIS, MU, AAOI, NVDA, SMH`

### v4 direction
- Separate security selection from allocation. A valid holding does not automatically deserve the next dollar.
- Deployment recommendations should combine:
  - user-selected eligible basket;
  - Williams Priority rank;
  - opportunity score;
  - macro/sector regime score;
  - portfolio concentration/exposure constraints;
  - manual eligibility gate for fundamentals/quality until a robust automated gate is proven.
- Output recommended dollars and weights for a user-entered contribution amount.
- Keep the formula transparent and versioned.

## Backend architecture

### Provider hierarchy
- Shared/cache-first reads should remain the default.
- Twelve Data remains the current primary shared snapshot source where configured.
- Alpaca Basic/IEX is available as an optional independent OHLC/history source when backend credentials are configured. It is suitable for historical research/cross-checking, not as a consolidated real-time tape.
- Yahoo Finance remains quota-free fallback/valuation coverage.
- SEC EDGAR Company Facts remains the primary public fundamental-history source where supported.
- Alpha Vantage remains quota-aware and should be used only when it materially fills a missing field or independent check.
- GDELT/Google News RSS, Frankfurter/ECB, public economic calendars, Nasdaq company events and stored SquawkFlow observations remain specialized inputs.

### Efficiency rules
- One shared symbol cache across users.
- Persist daily history and computed features.
- Background/incremental universe refresh rather than request-time full-market scans.
- Refresh queues prioritized by user exposure, opportunity likelihood, staleness and upcoming catalysts.
- Expensive provider requests are candidate-driven.
- Derived features should be recomputed from stored raw data when possible instead of refetched.

## UI architecture

Primary navigation should become:
- **Command** — pipeline summary and current decisions
- **Research**
- **Macro**
- **Opportunity**
- **Deployment**

Secondary tools are nested within those layers rather than deleted:
- Report / Markets / Portfolio / Security Research / World News / Events / Large Flow / Theses → Research
- Regime / currencies / sector rotation → Macro
- scanner / alerts / catalyst queue → Opportunity
- portfolio allocation / Williams Priority / future rebalancing experiments → Deployment
- Settings / data health / account controls remain global.

## Development rule

Do not silently change a live investment formula because a backtest looks better. Formula changes must be versioned, documented and tested on held-out baskets/time periods before replacing the prior model.
