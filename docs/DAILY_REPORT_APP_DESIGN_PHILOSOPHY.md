# Daily Report App Design Philosophy

## Four-layer stack

1. **General Research** — markets, sectors, portfolios, individual tickers, expandable research.
2. **Macro** — sector strength/weakness, regime, and rotation tracking.
3. **Opportunity** — uses Research + Macro to identify and score buy opportunities.
4. **Deployment Model** — uses Layers 1–3 plus formulas like Williams Priority to decide where new capital should be deployed.

## Product philosophy

1. **Focus.** The four-layer stack is the primary information architecture. Initial views stay clean and focused. Detailed data is revealed through expansion, clicks, drill-downs, or navigation to the appropriate layer/view.
2. **Expandable detail.** The app supports deep, accurate research without cluttering first views. Important datasets must support filtering, sorting by meaningful metrics, selectable timeframes, detailed views, and the useful capabilities preserved from prior versions.
3. **Transparency.** Important information exposes its origin. Users should be able to inspect sources, timestamps, technical-analysis explanations, news context, model reasoning, and clickable source links.
4. **Hierarchy over accumulation.** Every feature should have a clear home in one of the four layers. Do not add disconnected tabs/cards merely because data is useful.
5. **Decision relevance.** Data should help answer: What is happening? Why is it happening? What should I do with that information? Raw metrics without decision context belong in deeper views.
6. **Cross-layer continuity.** Research feeds Macro, Macro influences Opportunity, and Opportunity feeds Deployment. Ticker/thesis context should persist across layers rather than becoming disconnected views.
7. **Accuracy before immediacy.** Prefer validated and cross-checked data over the fastest available quote. Distinguish verified data, single-source data, derived calculations, estimates, and model inference.
8. **Explainability.** Important scores, rankings, alerts, predictions, and recommendations must be decomposable into contributing factors and weights.
9. **User-controlled abstraction.** Default views answer the important question quickly; deeper views expose raw values, formulas, timeframes, component scores, historical series, sorting, and filters.
10. **Historical context everywhere.** Important metrics should support comparison with prior periods, moving averages, historical percentiles, previous signals, or relevant regimes rather than appearing as isolated numbers.
11. **Efficient computation.** Broad scanners use staged filtering. Cheap signals narrow the universe; expensive research/enrichment runs only on promising candidates. Avoid brute-force provider/API usage.
12. **Storage discipline.** User-created information is durable. Public market data, caches, derived metrics, and temporary artifacts should be bounded, reproducible, and pruned when safe.
13. **Failure visibility.** Missing, stale, partial, or unverified data must not silently become zero, stale-looking-valid data, or misleading scores. Surface source failures, insufficient-history states, timestamps, and degraded verification explicitly.
14. **Actionable alerts, not notification volume.** Alerts should represent meaningful state changes such as Williams threshold crossings, 100MA approaches, thesis invalidation, unusual flow, or regime changes—not routine metric refreshes.
15. **Preserve research state.** A user should be able to move from broad scan → ticker research → thesis → alert → portfolio/deployment decision without losing the evidence, assumptions, sources, or reasoning that produced the decision.

## Working doctrine

**Simple surface, extreme depth underneath, traceable evidence, and every layer progressively narrows information toward a capital-allocation decision.**

## Development rules derived from the philosophy

- Never claim market-wide coverage unless coverage is measured and displayed.
- Coverage, freshness, completeness, verification, and connectivity are separate states.
- Derived scores should expose methodology and component weights.
- Broad-market data should not be stored in ways that can threaten production database availability.
- New features should reuse shared cached observations where possible instead of creating duplicate provider calls.
- Mobile should preserve access to all meaningful detail without forcing dense desktop tables into narrow screens.
- Prefer progressive disclosure over permanently visible controls/cards.
