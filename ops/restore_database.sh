#!/usr/bin/env bash
set -euo pipefail

: "${DATABASE_URL:?Set DATABASE_URL to the target PostgreSQL connection string.}"
backup="${1:?Usage: ./ops/restore_database.sh backups/daily-report-YYYYMMDDTHHMMSSZ.dump}"

if [[ ! -f "$backup" ]]; then
  echo "Backup not found: $backup" >&2
  exit 1
fi

if [[ -f "${backup}.sha256" ]]; then
  sha256sum -c "${backup}.sha256"
fi

pg_restore \
  --clean \
  --if-exists \
  --no-owner \
  --no-privileges \
  --dbname="$DATABASE_URL" \
  "$backup"

echo "Restore complete from $backup"
