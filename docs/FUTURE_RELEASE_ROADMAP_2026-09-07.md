# Future Release Roadmap — 2026-09-07

This roadmap implements and refines the nine opportunities identified by the production audit. The governing rule is that richer intelligence must preserve data lineage and uncertainty rather than turn missing evidence into confident-looking output.

## 1. Portfolio intelligence — IMPLEMENTED, EXPAND NEXT

Current tranche:
- sector, theme, listing-geography proxy and currency exposure
- top-1/top-3 concentration, HHI and effective-position count
- mechanical scenario shocks
- stored portfolio performance versus SPY when enough history exists
- existing Portfolio Risk view continues to own beta, volatility and correlation clusters

Recommended changes:
- Add factor-proxy exposure as a separately labeled layer rather than pretending cached fundamentals provide institutional factor-model exposures.
- Add user-selectable benchmarks (SPY, QQQ, SMH or a custom ticker).
- Add issuer revenue geography only when an authoritative fundamentals source supports it; do not substitute listing geography.
- Later support user-authored scenario sets and correlated multi-asset shocks.

## 2. Opportunity score history — IMPLEMENTED

Current tranche:
- latest-versus-prior component deltas
- new and removed threshold flags
- score delta
- current market-source age

Recommended changes:
- Persist source-age metadata inside every future FeatureSnapshot so source-age changes can be compared historically.
- Add 7D/30D attribution summaries once enough snapshots exist.
- Add a compact waterfall visualization showing which components drove the net score move.

## 3. Advanced options-flow clustering — IMPLEMENTED WITH DELIBERATE LIMITS

Current tranche groups repeated observations by ticker, option side, expiration, strike and reported direction/aggression. It aggregates observation count, premium, contracts/volume, first/last seen, provider and confidence.

Revision to the original proposal:
- Do **not** call repeated contract signatures “repeated participant behavior.” The current feed does not expose participant identity.
- Do **not** infer opening versus closing unless a provider supplies reliable open/close evidence. Open interest alone is insufficient to prove transaction intent.

Recommended next step:
- Add strategy-shape clustering (verticals, calendars, straddles/strangles) only where temporally linked legs can be supported by the feed.
- If a richer licensed feed is added, preserve `participant_behavior_supported` and `opening_closing_supported` capability flags rather than changing semantics silently.

## 4. News/catalyst impact mapping — IMPLEMENTED

Current tranche:
- maps stored report news to watchlist and portfolio symbols through ticker/company/theme matches
- maps explicit ticker custom events
- shows current portfolio exposure linked to matched symbols
- labels ordinary news mapping as association-only, not proven causality

Recommended changes:
- Add sector/macro transmission paths (for example, rates -> duration-sensitive holdings) as a transparent rule graph.
- Score mapping confidence separately from expected impact magnitude.
- Add countervailing exposures so a story can show both beneficiaries and risks.

## 5. Confidence-weighted market regime — IMPLEMENTED

Current tranche:
- transparent cross-asset risk-on/risk-off votes
- evidence completeness
- directional agreement confidence
- stored daily regime snapshots and transition history

Recommended changes:
- Split one headline regime into independent dimensions: risk appetite, growth, inflation, liquidity and dollar/rates pressure.
- Calibrate thresholds against stored history before adding probabilistic language.
- Add “uncertain” as an explicit state when coverage or agreement is too low rather than forcing a directional label.

## 6. User-customizable dashboards — PARTIALLY IMPLEMENTED

Current tranche:
- private saved layout profiles
- active layout selection
- reorder, hide/show, density and column count for the top Report dashboard cards
- observer-driven runtime so saved layouts reapply when the Report tab mounts later

Recommended changes:
- Expand the same persisted profile format to all Report cards, then other workspaces.
- Add drag-and-drop only after keyboard-accessible reorder controls remain available.
- Add card sizing using a constrained grid (`small`, `medium`, `wide`) instead of arbitrary pixel dimensions so mobile layouts remain deterministic.
- Add layout duplication and reset-to-default.

## 7. Snapshot comparison/export — IMPLEMENTED FIRST STAGE

Current tranche:
- compare two stored Daily Report snapshots without refreshing either
- symbol price changes, verification-state comparison and news additions/removals
- CSV and JSON export
- browser Print / Save PDF

Recommended changes:
- Add deterministic server-generated PDF only after the printable layout is stabilized.
- Add comparison of moving-average distance, outlier rank and macro/regime state.
- Preserve snapshot timestamps and provider lineage in every future export format.

Product decision still open: Report snapshots currently remain shared market-data artifacts, consistent with the existing architecture. Do not silently convert them to per-user private records without an explicit product decision.

## 8. Alert templates — PARTIALLY IMPLEMENTED, CAPABILITY-AWARE

Immediately executable templates:
- 100MA proximity
- 200MA proximity
- unusual relative volume

Designed but intentionally disabled until evaluator support exists:
- upcoming earnings/catalyst window
- persistent flow cluster
- portfolio concentration
- regime transition

Recommended changes:
- Extend the scheduler with typed evaluators for non-ticker state instead of faking them through a placeholder ticker.
- Add template-specific threshold controls and preview the current value before creating the rule.
- Add “notify once per transition” semantics for regime changes instead of numeric threshold comparison.

## 9. Mobile-first dense-data views — IMPLEMENTED BASELINE

Current tranche:
- sticky ticker and price columns in grouped Markets tables
- contained horizontal table scrolling
- responsive one-column future intelligence cards
- minimum 44px mobile interaction targets
- compact/comfortable saved dashboard density

Recommended changes:
- Add optional swipeable metric-group paging with visible page indicators; never rely on swipe as the only navigation method.
- Add sticky symbol headers inside long Research/Portfolio expanded cards.
- Test actual rendered layouts at 320, 360, 390, 430, 768, 1024 and common desktop widths before calling the mobile work complete.

## Suggested release sequencing

### Release A — Intelligence foundations
Ship the current tranche: portfolio intelligence, score explanations, flow clustering, impact mapping, regime confidence, first-stage layouts, snapshot compare/export, capability-aware alert templates and mobile hardening.

### Release B — Typed alert engine + dashboard expansion
Add catalyst/cluster/portfolio/regime evaluators, layout sizing/duplication/reset, all Report cards, and source-age persistence.

### Release C — Higher-order analytics
Add factor proxies, user-selectable benchmarks/scenarios, strategy-shape flow clustering, macro transmission graphs and multidimensional regime classification.

### Release D — Rich exports and polished mobile UX
Add deterministic PDF generation, export bundles, swipe/page navigation, rendered-device regression testing and shareable read-only report links if desired.
