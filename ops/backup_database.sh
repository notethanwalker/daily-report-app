#!/usr/bin/env bash
set -euo pipefail

: "${DATABASE_URL:?Set DATABASE_URL to a PostgreSQL connection string before running this backup.}"

mkdir -p backups
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="backups/daily-report-${stamp}.dump"

pg_dump \
  --format=custom \
  --compress=6 \
  --no-owner \
  --no-privileges \
  --file="$out" \
  "$DATABASE_URL"

sha256sum "$out" > "${out}.sha256"
printf 'Created %s\nChecksum %s\n' "$out" "${out}.sha256"
