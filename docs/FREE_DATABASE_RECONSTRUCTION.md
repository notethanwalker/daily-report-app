# Free database reconstruction

## Provider decision

| Provider | Free database storage | Card/overage posture | Compatibility | Decision |
|---|---:|---|---|---|
| Neon Free | 0.5 GB/project | No card required | PostgreSQL | Selected for exact compatibility and no billing trap |
| Supabase Free | 0.5 GB/project | Free projects may pause after inactivity | PostgreSQL | Rejected: same storage cap plus inactivity behavior |
| CockroachDB Basic | 10 GiB plus monthly request-unit allowance | Payment method required for free monthly credits; spend limit can be zero | PostgreSQL wire-compatible, not identical | Rejected: billing posture and compatibility changes |
| Render Free Postgres | 1 GB | Time-limited free database | PostgreSQL | Rejected: expiration and demonstrated no-space recovery deadlock |

The provider change is only half of the fix. The application now defaults to a
free-tier storage profile with a 400 MiB application budget and a stop threshold
at 90%. Full-universe ingestion and database-backed archive uploads are disabled.
Only tracked/watchlist/portfolio history is rebuilt.

## Reconstruction sources

The reconstruction script creates every registered schema table, then restores
only data supported by code or deployment secrets:

- the encrypted owner account from the existing bootstrap environment variables;
- the 15-symbol default watchlist;
- the Joint Fidelity portfolio, cash value, and nine positions from the audited seed;
- bounded refresh jobs for those portfolio positions.

It deliberately does not fabricate other users, later watchlist edits, alerts,
push subscriptions, theses, custom events, preferences, or historical caches.

## Required environment

Set the new pooled PostgreSQL connection as `DATABASE_URL` and retain the existing
`AUTH_BOOTSTRAP_ADMIN_*` and encryption environment variables. Recommended safety
settings are:

```text
FREE_TIER_DATABASE_MODE=true
DATABASE_STORAGE_BUDGET_BYTES=419430400
DATABASE_STORAGE_STOP_RATIO=0.90
ENABLE_BROAD_MARKET_INGEST=false
ENABLE_DATABASE_ARCHIVE_UPLOADS=false
```

Run:

```bash
python scripts/reconstruct_database.py
```

The command is idempotent and prints table counts plus current database capacity.
