# Daily Report v4 — Decision Stack

Legacy production code is preserved on `legacy-daily-report`. V4 development is isolated on `daily-report-v4-rebuild`.

## Pipeline

1. **Research** — establish point-in-time facts and context for markets, sectors, portfolios and securities.
2. **Macro** — classify sector leadership, weakening, lagging and improving rotation states.
3. **Opportunity** — narrow the broad cached universe before applying richer scoring.
4. **Deployment** — direct new capital using portfolio-aware formulas, beginning with cross-sectional Williams Priority.

## Design principles

- Cache-first and provider-efficient. Broad scans operate on normalized stored data and do not brute-force live APIs.
- Explainable scores. Persist point-in-time inputs/components and show what changed rather than only returning a rank.
- Separate selection from allocation. A valid holding does not automatically deserve the next dollar.
- Preserve existing capabilities. Report, Markets, Portfolio, World News, Events, Flow, Alerts and Theses become inputs/workspaces inside the closest layer rather than being removed.
- No automatic fundamental quality gate yet. Quality gating remains manual until a robust structural-deterioration model is established.
- Williams Priority defaults to new-capital allocation only; existing holdings are not automatically rebalanced.

## Rotation model v4

Starts from the existing rotation score (25% 1D + 45% 7D + 30% 30D, participation-adjusted by relative volume). V4 adds:

- change across stored daily observations;
- 100MA/200MA trend context;
- transition states (`leading_accelerating`, `leading_weakening`, `lagging_improving`, etc.);
- heuristic forward-bias labels such as `early_rotation_candidate` and `rotation_out_risk`;
- conviction based on score magnitude, transition magnitude, directional consistency and data depth.

These labels are not calibrated probabilities and are not direct fund-flow measurements.

## Candidate funnel v4

The broad scanner remains Williams-first and 100MA-second, consistent with the existing Opportunities design.

1. Broad cached equity universe + liquidity/price eligibility.
2. Williams/100MA technical setup buckets (strong / weak / near).
3. Attach sector rotation state without automatically deleting strong counter-rotation setups.
4. Rank with technical setup dominant, then existing buy score, sector context and liquidity.

This avoids expensive random-ticker live searches.

## Score history and explainability

`FeatureSnapshot` remains the source of point-in-time opportunity history. V4 exposes:

- buy/sell score history;
- component deltas;
- largest positive and negative score drivers;
- raw changes in Williams, MA distances, momentum, relative volume, sector score and stored flow context.

Historical snapshots are not recomputed with future inputs.

## Research workspaces

The v4 security workspace composes stored:

- market data;
- registry/sector/industry metadata;
- fundamentals;
- opportunity/features;
- score history and change drivers;
- 72-hour flow context;
- sector rotation state;
- user theses.

Opening the v4 research workspace is cache-first and does not initiate a broad provider refresh.

## Current API surface

- `GET /api/v1/stack/overview`
- `GET /api/v1/stack/sources`
- `GET /api/v1/stack/rotation`
- `GET /api/v1/stack/candidates`
- `GET /api/v1/stack/scores/{symbol}`
- `GET /api/v1/stack/research/{symbol}`
- `GET /api/v1/stack/deployment`

## Next work

- persist dedicated daily rotation snapshots independent of market refresh frequency;
- calibrate rotation-transition hit rates against forward sector relative returns;
- add sector-first candidate discovery budgets and change notifications;
- persist broad-funnel rank history, not only tracked-symbol feature history;
- attach events/news catalysts to research and opportunity explanations;
- connect portfolio exposure/concentration constraints into deployment recommendations.
