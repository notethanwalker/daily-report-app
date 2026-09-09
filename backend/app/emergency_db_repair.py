"""One-purpose recovery helper for the 2026-09-09 full-disk incident.

The only mutation this module can perform is dropping the exact, verified
non-unique single-column index named below.  Everything else is read-only
inventory output.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import psycopg
from psycopg.rows import dict_row


TARGET_SCHEMA = "public"
TARGET_TABLE = "normalized_daily_bars"
TARGET_INDEX = "ix_normalized_daily_bars_retrieved_at"
TARGET_COLUMN = "retrieved_at"


VERIFY_SQL = """
SELECT
    ns.nspname AS schema_name,
    tbl.relname AS table_name,
    idx.relname AS index_name,
    i.indisprimary,
    i.indisunique,
    i.indnkeyatts,
    array_agg(att.attname ORDER BY key.ordinality)
        FILTER (WHERE key.ordinality <= i.indnkeyatts) AS key_columns,
    EXISTS (
        SELECT 1 FROM pg_constraint c WHERE c.conindid = idx.oid
    ) AS backs_constraint
FROM pg_class idx
JOIN pg_namespace ns ON ns.oid = idx.relnamespace
JOIN pg_index i ON i.indexrelid = idx.oid
JOIN pg_class tbl ON tbl.oid = i.indrelid
JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS key(attnum, ordinality) ON true
LEFT JOIN pg_attribute att ON att.attrelid = tbl.oid AND att.attnum = key.attnum
WHERE ns.nspname = %s AND idx.relname = %s
GROUP BY ns.nspname, tbl.relname, idx.relname, i.indisprimary,
         i.indisunique, i.indnkeyatts, idx.oid
"""


def _inventory(conn: psycopg.Connection[Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT current_database() AS database, "
            "pg_database_size(current_database()) AS bytes, "
            "pg_size_pretty(pg_database_size(current_database())) AS size"
        )
        result["database"] = cur.fetchone()

        cur.execute(
            """
            SELECT schemaname, relname AS table_name,
                   pg_total_relation_size(relid) AS total_bytes,
                   pg_size_pretty(pg_total_relation_size(relid)) AS total_size,
                   pg_relation_size(relid) AS heap_bytes,
                   pg_indexes_size(relid) AS index_bytes,
                   n_live_tup, n_dead_tup
            FROM pg_stat_user_tables
            ORDER BY pg_total_relation_size(relid) DESC
            """
        )
        result["tables"] = cur.fetchall()

        cur.execute(
            """
            SELECT schemaname, relname AS table_name, indexrelname AS index_name,
                   pg_relation_size(indexrelid) AS bytes,
                   pg_size_pretty(pg_relation_size(indexrelid)) AS size,
                   idx_scan
            FROM pg_stat_user_indexes
            ORDER BY pg_relation_size(indexrelid) DESC
            """
        )
        result["indexes"] = cur.fetchall()
    return result


def repair_once(database_url: str) -> dict[str, Any]:
    with psycopg.connect(database_url, connect_timeout=2, autocommit=True) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SET statement_timeout = '15s'")
            cur.execute("SELECT to_regclass(%s) AS target", (f"{TARGET_SCHEMA}.{TARGET_INDEX}",))
            exists = cur.fetchone()["target"] is not None

            if exists:
                cur.execute(VERIFY_SQL, (TARGET_SCHEMA, TARGET_INDEX))
                row = cur.fetchone()
                expected = (
                    row is not None
                    and row["schema_name"] == TARGET_SCHEMA
                    and row["table_name"] == TARGET_TABLE
                    and row["index_name"] == TARGET_INDEX
                    and row["indisprimary"] is False
                    and row["indisunique"] is False
                    and row["indnkeyatts"] == 1
                    and row["key_columns"] == [TARGET_COLUMN]
                    and row["backs_constraint"] is False
                )
                if not expected:
                    raise RuntimeError(f"REFUSING_DROP verification mismatch: {row!r}")
                cur.execute(f'DROP INDEX "{TARGET_SCHEMA}"."{TARGET_INDEX}"')
                action = "dropped_verified_target_index"
            else:
                action = "target_index_already_absent"

        return {"action": action, "inventory": _inventory(conn)}


def retry_repair(max_attempts: int = 600, delay_seconds: float = 2.0) -> dict[str, Any]:
    database_url = os.environ.get("EMERGENCY_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    last_error = "not attempted"
    for attempt in range(1, max_attempts + 1):
        try:
            result = repair_once(database_url)
            print("EMERGENCY_DB_REPAIR_SUCCESS=" + json.dumps(result, default=str), flush=True)
            return result
        except RuntimeError as exc:
            if str(exc).startswith("REFUSING_DROP"):
                print(f"EMERGENCY_DB_REPAIR_ABORT={exc}", flush=True)
                raise
            last_error = f"{type(exc).__name__}: {exc}"
        except Exception as exc:  # connection/full-disk failures are expected while racing resume
            last_error = f"{type(exc).__name__}: {exc}"

        if attempt == 1 or attempt % 15 == 0:
            print(f"EMERGENCY_DB_REPAIR_WAIT attempt={attempt} error={last_error}", flush=True)
        time.sleep(delay_seconds)

    raise RuntimeError(f"repair window exhausted; last error: {last_error}")


if __name__ == "__main__":
    retry_repair()
