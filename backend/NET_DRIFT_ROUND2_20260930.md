# Net Drift Confirmation — Round 2 (2026-09-30)

## Status
Research-only. The earlier Round 1 5/5 result did not survive a larger fresh cohort.

## Data and causal setup
- Underlying: QQQ 1-minute bars.
- Options: same-day-expiry QQQ option 5-minute bars.
- Fresh complete option sessions: 11 trading days, 2026-09-08 through 2026-09-22 (subject to free-provider rate limits).
- ATM strike chosen from the 09:30 ET QQQ open, before the signal.
- Signal time: 10:30 ET.
- Primary horizon: 11:30 ET; also tested +30m, +2h, and close.
- Signed option-pressure proxy:
  premium × sign(option bar close-open) × (+1 call / -1 put), normalized by absolute option premium.
- This is NOT true aggressor-classified Net Drift. Tick trades + contemporaneous NBBO remain required for promotion.

## Results
### Broad price control
Across 41 QQQ sessions (2026-08-03 through 2026-09-29), simple 10:30 price-direction continuation:
- +30m: 21/41 positive, +0.012% average directional return.
- +60m: 24/41 positive, +0.033% average.
- +120m: 19/41 positive, -0.013% average.
- To close: 19/41 positive, +0.056% average.

### Net Drift proxy, price/flow agreement
11 eligible sessions:
- +30m: 6/11 positive, -0.003% average.
- +60m: 6/11 positive, ~0.000% average.
- +120m: 6/11 positive, +0.047% average.
- To close: 5/11 positive, -0.026% average.

Conclusion: simple agreement is not an edge in this cohort.

### Pressure magnitude
Require |normalized pressure| >= 0.05 (9 trades):
- +60m: 5/9 positive, +0.025% average.
- +120m: 6/9 positive, +0.111% average.

Require |normalized pressure| >= 0.10 (7 trades):
- +60m: 3/7 positive, +0.008% average.
- +120m: 5/7 positive, +0.149% average.
- To close: 5/7 positive, +0.164% average.

This suggests any useful effect may operate more as a strong-pressure persistence filter and at longer intraday horizons, not as immediate continuation.

### Pressure persistence / acceleration
Rule: signed pressure has the same sign at 10:00 and 10:30, and absolute normalized pressure is larger at 10:30.
Only 2/11 sessions qualified:
- +30m: 2/2, +0.126% average.
- +60m: 2/2, +0.206% average.
- +120m: 2/2, +0.400% average.
- To close: 2/2, +0.370% average.

This is a hypothesis only. n=2 is too small for inference and must not be promoted or optimized further without a larger dataset.

## Interpretation
1. The earlier 5/5 Round 1 signal was fragile and should not be treated as validated.
2. Gross call-vs-put premium remains unsuitable.
3. Simple price + signed-pressure agreement does not add meaningful short-horizon edge in the fresh cohort.
4. Strong pressure may contain information at ~2-hour horizons.
5. Persistence/acceleration is the most interesting next branch, but currently has only two observations.
6. The proper promotion test remains ~1 year of true aggressor-classified trade+NBBO data.

## Next gate
Backfill QQQ/SPY intraday warehouse using free equity feeds plus Alpaca indicative option history from Feb-2024 onward. Then:
- freeze signal times (10:00, 10:30, 11:00),
- freeze magnitude thresholds before looking at full-period results,
- test persistence/acceleration separately,
- stratify by realized volatility, gap, trend/regime and event days,
- compare against exposure-matched price momentum,
- finally repeat on true tick+NBBO data before any deployment conclusion.
