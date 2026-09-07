# Daily Report App — Non-user backlog reconciliation

Date: 2026-09-06

This document consolidates the previously separate Daily Report app issue lists. User/account setup, onboarding, invitations, and access configuration are intentionally deferred.

## Resolved before this reconciliation

- Initial loading screen and scoped loading states.
- Specific network/provider/timeout error messages and retry actions.
- Markets watchlist ticker removal.
- Markets row click/tap expands a security inline rather than using the old card-mode market view.
- Expanded market view includes fundamentals, moving averages, Williams %R, valuation metrics, source links, refresh, and removal.
- World News, Events, Portfolio, Opportunities, Macro, Regime, Research, Alerts, Theses, Settings/Data Health, and Command Center surfaces are present in the current architecture.
- User-specific watchlist references and globally shared symbol/provider caches are already separated architecturally; user setup itself remains deferred.

## Fixed in this reconciliation

### Market-data verification

Problem: scheduled market refreshes and some on-demand refreshes could persist/display primary-only Twelve Data snapshots even though verification status was exposed in the UI.

Fix:
- Yahoo Finance daily history is now an independent secondary verification source.
- On-demand market refreshes always attempt the Yahoo cross-check even if a legacy caller passes `verify=false`.
- Scheduled market refreshes also perform the cross-check.
- Provider disagreements are preserved as discrepancies rather than averaged away.
- Alpha Vantage remains quota-aware/tertiary instead of determining whether normal verification can occur.

### Historical rotation continuity

Problem: history refresh eligibility was based mainly on having at least 120 bars. Once that threshold was reached, history could stop advancing and sector-rotation history could become stale.

Fix:
- The scheduler now checks the date of the newest historical bar.
- Stale or missing histories are re-enqueued even after the initial 120-bar backfill.
- Macro-sector history and watchlist history therefore continue tracking forward.
- Data Health now reports macro-history freshness and latest bar coverage.

### Large Flow intelligence

Problem: a significance/direction scorer existed but was not authoritative in the live flow endpoint, while the UI primarily surfaced the provider's unusualness score and simple call/put execution coloring.

Fix:
- Flow-v2 separates significance from inferred direction.
- Significance uses premium/contract size, volume/open-interest, execution classification, provider unusualness, cached market-cap context, relative-volume context when available, and independent-source corroboration.
- Direction confidence is reported separately and includes an explicit hedge/spread/roll/open-close warning.
- The Large Flow UI defaults to significance ranking and shows derived direction, confidence, provider score, and analysis reasons.
- Public social accounts such as Flow God or Unusual Whales are not scraped or fabricated as data. They can become corroborating discovery signals only through a lawful structured/API-accessible source.

### Data health / observability

Problem: health reporting did not make historical staleness or verification coverage sufficiently visible.

Fix:
- Data Health now reports fresh/stale/missing history per symbol.
- It reports latest historical bar and bar count.
- It reports verified/partially verified, discrepancy, and primary-only market coverage.
- It reports macro-history freshness across the full tracked macro universe.
- Provider roles now identify Yahoo as market verification + fundamentals fallback and Alpha Vantage as tertiary/quota-aware.

## Audited and retained as already implemented

The following areas were reviewed as part of the reconciliation and did not require replacement architecture:

- Event/catalyst workspaces and expanded event catalog.
- Research/security workspace and on-demand hydration.
- Portfolio and opportunity tooling.
- Alert and thesis tooling.
- Regime/macro intelligence and rotation reasoning.
- Data/provider caching and shared global-symbol architecture.
- Loading/error/retry behavior.
- Market watchlist management and inline expanded security view.

## Explicitly deferred

- User setup and onboarding.
- User invitations/access provisioning.
- Final multi-user acceptance testing tied to those setup flows.

## Validation

The reconciliation is kept on branch `reconcile-non-user-backlog-2026-09-06` in draft PR #1 until CI validation is complete and the changes are deliberately approved for promotion. Production is not intentionally merged from this reconciliation branch.