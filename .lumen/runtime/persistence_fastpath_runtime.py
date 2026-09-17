"""Low-risk persistence fast-path for LUMEN runtime.

Avoids reopening a PostgreSQL connection and re-running CREATE TABLE IF NOT EXISTS
on every load_state/save_state call. The schema check runs once per web process.
The existing app.load_state/app.save_state behavior and persisted data format stay
unchanged.
"""
from __future__ import annotations

import threading

import psycopg

import app as lumen_app

_SCHEMA_READY = False
_SCHEMA_LOCK = threading.Lock()


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


# app.load_state/app.save_state resolve ensure_db in the app module at call time,
# so this safely replaces only the redundant schema-check path.
lumen_app.ensure_db = ensure_db_fast
