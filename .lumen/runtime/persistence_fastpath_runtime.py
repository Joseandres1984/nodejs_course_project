"""Low-risk persistence fast-path for LUMEN runtime.

Avoids reopening a PostgreSQL connection and re-running CREATE TABLE IF NOT EXISTS
on every load_state/save_state call. The state and cycle-journal schema checks run
once per process after the first successful initialization. Existing behavior and
persisted data formats stay unchanged.
"""
from __future__ import annotations

import threading

import psycopg

import app as lumen_app
import cycle_journal as lumen_cycle_journal

_SCHEMA_READY = False
_SCHEMA_LOCK = threading.Lock()
_CYCLE_SCHEMA_READY = False
_CYCLE_SCHEMA_LOCK = threading.Lock()


def ensure_db_fast() -> bool:
    global _SCHEMA_READY

    if not lumen_app.DATABASE_URL:
        return False
    if _SCHEMA_READY:
        return True

    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return True
        try:
            with psycopg.connect(lumen_app.DATABASE_URL) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """CREATE TABLE IF NOT EXISTS lumen_state (
                            state_key TEXT PRIMARY KEY,
                            payload JSONB NOT NULL,
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )"""
                    )
            _SCHEMA_READY = True
            lumen_app.DB_STATUS.update({"connected": True, "last_error": None})
            return True
        except Exception as exc:
            lumen_app.DB_STATUS.update(
                {"connected": False, "last_error": str(exc)[:180]}
            )
            return False


def ensure_cycle_journal_db_fast() -> bool:
    """Initialize the journal table/index once per process, retrying after failures."""
    global _CYCLE_SCHEMA_READY

    if not lumen_cycle_journal.DATABASE_URL:
        return False
    if _CYCLE_SCHEMA_READY:
        return True

    with _CYCLE_SCHEMA_LOCK:
        if _CYCLE_SCHEMA_READY:
            return True
        try:
            with psycopg.connect(lumen_cycle_journal.DATABASE_URL) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS lumen_cycle_journal (
                            cycle INTEGER PRIMARY KEY,
                            recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            local_time TEXT NOT NULL,
                            status TEXT NOT NULL,
                            source TEXT NOT NULL,
                            payload JSONB NOT NULL
                        )
                        """
                    )
                    cur.execute(
                        "CREATE INDEX IF NOT EXISTS lumen_cycle_journal_recorded_idx "
                        "ON lumen_cycle_journal(recorded_at DESC)"
                    )
            _CYCLE_SCHEMA_READY = True
            return True
        except Exception:
            # Preserve fail-open/retry semantics from cycle_journal.ensure_cycle_journal_db.
            return False


# app.load_state/app.save_state and cycle-journal callers resolve these functions
# at call time, so this safely replaces only redundant schema-check paths.
lumen_app.ensure_db = ensure_db_fast
lumen_cycle_journal.ensure_cycle_journal_db = ensure_cycle_journal_db_fast
