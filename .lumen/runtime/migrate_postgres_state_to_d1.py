from __future__ import annotations

"""One-shot migration of the legacy PostgreSQL/Supabase LUMEN state into Cloudflare D1.

Requires LEGACY_DATABASE_URL plus the normal LUMEN_D1_* variables. It performs one read from the
legacy lumen_state/global row and writes the exact JSON object through the D1 chunked adapter.
"""

import os
import sys
from typing import Any, Dict

import psycopg

LEGACY_DATABASE_URL = os.getenv("LEGACY_DATABASE_URL", "").strip()

if not LEGACY_DATABASE_URL:
    raise SystemExit("LEGACY_DATABASE_URL is required")
if not all(os.getenv(name, "").strip() for name in ("LUMEN_D1_ACCOUNT_ID", "LUMEN_D1_DATABASE_ID", "LUMEN_D1_API_TOKEN")):
    raise SystemExit("LUMEN_D1_ACCOUNT_ID, LUMEN_D1_DATABASE_ID and LUMEN_D1_API_TOKEN are required")

with psycopg.connect(LEGACY_DATABASE_URL) as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT payload FROM lumen_state WHERE state_key='global' LIMIT 1")
        row = cur.fetchone()

if not row or not isinstance(row[0], dict):
    raise SystemExit("Legacy lumen_state/global row was not found or was not JSON")

legacy_state: Dict[str, Any] = row[0]

# Import the normal app before installing the D1 adapter, then hand the exact legacy state to it.
import app  # noqa: E402
import d1_persistence_runtime as d1  # noqa: E402

app.STATE.clear()
app.STATE.update(legacy_state)

if not d1.save_state():
    raise SystemExit(f"D1 save failed: {app.DB_STATUS}")
if not d1.load_state():
    raise SystemExit(f"D1 verification read failed: {app.DB_STATUS}")

print(
    {
        "migration": "postgres_to_d1",
        "status": "success",
        "top_level_keys": len(app.STATE),
        "state_bytes": app.DB_STATUS.get("state_bytes"),
        "state_chunks": app.DB_STATUS.get("state_chunks"),
    },
    flush=True,
)
