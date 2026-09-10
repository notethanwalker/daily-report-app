# Opportunity Factor Validation — 2026-09-09

Model: `opportunity-formula-v1`

## Method
- Source: Yahoo Finance via `yfinance`, adjusted daily OHLCV.
- Basket: 21 symbols from the existing quant-research plan (semis, mega-cap growth, broad ETFs).
- History: 2010-01-08 through 2026-09-09.
- Sampling: last trading session of each W-FRI week per symbol.
- Chronological split: discovery through 2021-09-03; validation afterward.
- Forward returns: close-to-close 5D / 20D / 60D, beginning after the observation date.
- Features: computed point-in-time only; no future values enter feature computation.
- Production governance: this evidence does **not** automatically change criterion status or weights.

## 20D validation snapshot

| Criterion | Validation rank IC | Top-quartile excess return | Symbol hit rate vs basket mean | Preliminary review gate |
| --- | ---: | ---: | ---: | --- |
| Williams %R score | -0.0031 | +0.258% | 42.86% | No |
| 100MA proximity score | -0.0117 | -0.472% | 47.62% | No |
| 50MA proximity score | -0.0161 | -0.269% | 42.86% | No |
| 100MA slope score | +0.0511 | +0.628% | 52.38% | No |
| 5D approach velocity score | +0.0061 | +0.236% | 52.38% | **Yes** |
| Relative volume score | +0.0193 | +0.342% | 52.38% | No |

The review gate requires at least 100 discovery samples, 60 validation samples, positive discovery and validation rank IC, and positive discovery and validation top-quartile excess at 20D. Passing it means only "worthy of further review," not validated.

## Important interpretation
- Approach velocity is the only factor that passed the initial mechanical review gate.
- Williams still showed positive top-quartile excess in validation (+0.258% at 20D; +1.763% at 60D), but its 20D validation rank IC was slightly negative. This supports keeping it as a baseline hypothesis rather than calling it validated.
- 50MA and 100MA proximity were weak when tested as standalone score dimensions in this basket. That does **not** disprove their use as conditional setup filters or interaction terms with Williams; the current test measures marginal standalone ranking behavior.
- 100MA slope and relative volume improved in the validation period but did not meet the discovery/validation consistency gate.

## Limitations
1. The basket uses current symbols and is not a point-in-time market universe; survivorship bias remains.
2. The basket is deliberately tilted toward technology/growth plus broad ETFs, so sector generalization is unproven.
3. Forward windows overlap, especially at 20D and 60D, so raw sample counts overstate independent observations.
4. Yahoo adjusted history is suitable for exploratory research but promotion to `validated` should require an independent data/sample cross-check.
5. The proximity transforms are discrete and create ties; future validation should test raw/continuous distance and interaction forms rather than assuming the current transform is optimal.

## Next research step
Run an independent, more diversified basket and test interactions explicitly:
- Williams × 100MA proximity
- Williams × approach velocity
- Williams × positive 100MA slope
- conditional 100MA proximity only when price remains above the MA
- continuous/volatility-normalized MA distance

Do not promote any criterion to `validated` until it survives that step and the broader anti-overfit protocol in `docs/quant-research-plan.md`.
