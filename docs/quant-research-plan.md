# Quant Research Framework

Goal: identify robust contribution/deployment strategies without paid data and without overfitting.

## Data hierarchy
1. Alpaca structured stock bars/snapshots when available.
2. Yahoo Finance adjusted OHLC via GitHub runner for long split-adjusted histories.
3. Stooq fallback.
4. Alpha Vantage for cross-checks, point-in-time listings, corporate actions, macro and fundamentals when quota permits.
5. SEC/Nasdaq and existing app providers for primary-source validation.

## Data rules
- Cache raw OHLC once per symbol/date range and compute indicators locally.
- Preserve source, retrieval time, adjustment method, and data hash.
- Cross-check sample dates and corporate actions before declaring a result canonical.
- Prefer point-in-time universes to current-index constituent lists when testing many stocks.

## Williams research grid
Initial parameter grid:
- Williams window: 7, 14, 21, 28 trading days.
- Oversold threshold: -60, -70, -75, -80, -85, -90.
- Trigger: fresh crossing only, previous day above threshold.
- Contribution: $1,000 on first trading day monthly.
- Deployment variants to test later: all cash, 25/50/75% partial deployment, maximum-wait fallback, MA/regime filters.

## Required evaluation
For every strategy/ticker/window:
- Ending portfolio value vs matched monthly DCA.
- Shares accumulated and effective basis.
- Remaining cash and maximum cash waiting.
- Number of triggers and average deployment latency.
- Money-weighted return / XIRR.
- Maximum drawdown and recovery time.
- Rolling-start performance.
- Performance by market regime.

## Anti-overfit protocol
1. Discovery set: broad historical/ticker sample used to identify candidate rules.
2. Validation set: untouched tickers and/or later time period.
3. Final holdout: never used for parameter selection.
4. Prefer broad plateaus of good parameters over a single sharp optimum.
5. Report median result, hit rate vs DCA, dispersion and worst-case result, not only average/maximum.
6. Re-test candidates across sectors and secular winners/losers.
7. Treat transaction costs/taxes as optional sensitivity tests; never let omission create hidden leverage or impossible execution assumptions.

## First research sequence
1. NVDA, MU, AMD, AVGO, TSM, ASML, AMAT, LRCX, KLAC, QCOM.
2. High-growth non-semis: AMZN, META, GOOGL, MSFT, TSLA, NFLX.
3. Broad ETFs: SPY, QQQ, SMH, IWM, XLK.
4. User-focus names where history permits: NBIS, AAOI, SNDK, AXTI, IONQ, OKLO.
5. Broader point-in-time universe after the strategy family is narrowed.

A strategy is interesting only if it beats DCA across a meaningful share of independent samples, survives rolling-start tests, and does not rely on extreme cash waiting or one exceptional ticker.