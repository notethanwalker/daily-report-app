# Daily Report App — Disaster Recovery / Host Migration

This repository is the source of truth for application code. Runtime secrets must never be committed.

## Recovery objectives

Recreate the app on a new host with:
- GitHub repo `notethanwalker/daily-report-app`
- backend root: `backend`
- Docker runtime
- PostgreSQL 17-compatible database
- frontend deployed separately from `web/`
- environment variables restored from the operator's secret store or provider dashboard

## Current architecture snapshot

Backend:
- service name: `daily-report-api`
- root directory: `backend`
- runtime: Docker
- region: Oregon
- one instance

Database:
- PostgreSQL 17
- database name: `defaultdb`
- SSL required
- application supports split database environment variables; do not store their values here

Frontend:
- Vercel project: `daily-report-app`
- production alias: `daily-report-app-pearl.vercel.app`
- Git auto-deploy intentionally disabled
- frontend releases are batched and deployed manually only when explicitly approved

## Required database environment variable names

Restore these from the current host's secret settings:
- `AIVEN_DB_USER`
- `AIVEN_DB_HOST`
- `AIVEN_DB_PORT`
- `AIVEN_DB_NAME`
- `AIVEN_DB_PASSWORD`

Copy any provider/auth secrets from the current host's secret settings. Never commit secret values.

## Portable database backup

From a machine/container with PostgreSQL client tools installed:

```bash
export DATABASE_URL='postgresql://USER:PASSWORD@HOST:PORT/DB?sslmode=require'
./ops/backup_database.sh
```

Restore to a new PostgreSQL database:

```bash
export DATABASE_URL='postgresql://USER:PASSWORD@NEW_HOST:PORT/DB?sslmode=require'
./ops/restore_database.sh backups/daily-report-YYYYMMDDTHHMMSSZ.dump
```

## Host migration sequence

1. Provision PostgreSQL 17-compatible storage.
2. Restore the newest logical dump if moving durable user/state data. Public market caches can be reconstructed if necessary.
3. Copy required secret environment variables into the new host.
4. Deploy this repository with `backend/` as the service root and its Dockerfile.
5. Verify `/` returns HTTP 200.
6. Verify database connectivity and authentication.
7. Verify Research, Macro, Opportunity, Deployment, Large Flow and Data Health endpoints.
8. Update frontend backend origin only if the API hostname changes.
9. Keep the old backend available until the new backend passes smoke tests.

## Preserve vs reconstruct

Preserve when possible:
- accounts and durable user identity records
- names/preferences/watchlists
- portfolio data and baselines
- alert definitions/events
- theses and custom events
- report snapshots
- user-specific state

Reconstructible/cache data:
- public market snapshots
- normalized/public OHLC history
- rotation snapshots derived from public data
- candidate caches and feature snapshots
- public flow observations, subject to provider history availability

## Provider-host failure rule

A backend host failure must not imply data loss. The database lives outside Render, application code lives in GitHub, and logical PostgreSQL backups are portable to another provider.
