from __future__ import annotations

"""Cloudflare D1 persistence adapter for LUMEN Zero.

This module intentionally patches only app.ensure_db/load_state/save_state. The rest of LUMEN
continues to use the same in-memory STATE object and the same persistence calls as the production
runtime. State is compressed and chunked so it is not tied to D1's per-row string size.
"""

import base64
import hashlib
import json
import os
import urllib.error
import urllib.request
import zlib
from datetime import datetime, timezone
from typing import Any, Dict, List

import app as lumen_app

ACCOUNT_ID = os.getenv("LUMEN_D1_ACCOUNT_ID", "").strip()
DATABASE_ID = os.getenv("LUMEN_D1_DATABASE_ID", "").strip()
API_TOKEN = os.getenv("LUMEN_D1_API_TOKEN", "").strip()
ZERO_MODE = os.getenv("LUMEN_ZERO_COST_MODE", "true").strip().lower() in {"1", "true", "yes", "on"}
CHUNK_CHARS = max(100_000, min(700_000, int(os.getenv("LUMEN_D1_CHUNK_CHARS", "450000"))))
HTTP_TIMEOUT = max(5.0, min(45.0, float(os.getenv("LUMEN_D1_HTTP_TIMEOUT", "20"))))
STATE_KEY = "global"

_CONFIGURED = bool(ACCOUNT_ID and DATABASE_ID and API_TOKEN)
_SCHEMA_READY = False


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _endpoint() -> str:
    return f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/d1/database/{DATABASE_ID}/query"


def _request(body: Dict[str, Any]) -> Any:
    request = urllib.request.Request(
        _endpoint(),
        data=json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {API_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "LUMEN-Zero/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        detail = exc.read(6000).decode("utf-8", errors="replace")
        raise RuntimeError(f"D1 HTTP {exc.code}: {detail[:1000]}") from exc
    except Exception as exc:
        raise RuntimeError(f"D1 request failed: {type(exc).__name__}: {str(exc)[:700]}") from exc

    if not isinstance(payload, dict) or payload.get("success") is False:
        raise RuntimeError(f"D1 API error: {str(payload)[:1200]}")
    if payload.get("errors"):
        raise RuntimeError(f"D1 API errors: {str(payload.get('errors'))[:1200]}")
    return payload.get("result", payload)


def _statement_rows(statement: Any) -> List[Dict[str, Any]]:
    if isinstance(statement, dict):
        rows = statement.get("results")
        if isinstance(rows, list):
            return [x for x in rows if isinstance(x, dict)]
    return []


def _result_statements(result: Any) -> List[Any]:
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        return [result]
    return []


def ensure_db() -> bool:
    global _SCHEMA_READY
    if not ZERO_MODE or not _CONFIGURED:
        lumen_app.DB_STATUS.update({
            "configured": _CONFIGURED,
            "connected": False,
            "backend": "cloudflare_d1",
            "zero_cost_mode": ZERO_MODE,
            "last_error": "D1 credentials missing" if ZERO_MODE and not _CONFIGURED else "zero mode disabled",
        })
        return False
    if _SCHEMA_READY:
        return True
    try:
        result = _request({
            "batch": [
                {
                    "sql": "CREATE TABLE IF NOT EXISTS lumen_state_manifest (state_key TEXT PRIMARY KEY, encoding TEXT NOT NULL, chunk_count INTEGER NOT NULL, payload_sha256 TEXT NOT NULL, uncompressed_bytes INTEGER NOT NULL, updated_at TEXT NOT NULL)",
                    "params": [],
                },
                {
                    "sql": "CREATE TABLE IF NOT EXISTS lumen_state_chunks (state_key TEXT NOT NULL, chunk_no INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY (state_key, chunk_no))",
                    "params": [],
                },
                {
                    "sql": "CREATE INDEX IF NOT EXISTS idx_lumen_state_chunks_key ON lumen_state_chunks(state_key, chunk_no)",
                    "params": [],
                },
            ]
        })
        statements = _result_statements(result)
        if statements and any(isinstance(x, dict) and x.get("success") is False for x in statements):
            raise RuntimeError(f"D1 schema batch failed: {str(statements)[:1200]}")
        _SCHEMA_READY = True
        lumen_app.DB_STATUS.update({
            "configured": True,
            "connected": True,
            "backend": "cloudflare_d1",
            "zero_cost_mode": True,
            "last_error": None,
        })
        return True
    except Exception as exc:
        lumen_app.DB_STATUS.update({
            "configured": True,
            "connected": False,
            "backend": "cloudflare_d1",
            "zero_cost_mode": True,
            "last_error": str(exc)[:500],
        })
        return False


def _encode_state() -> tuple[List[str], str, int]:
    raw = json.dumps(
        lumen_app.STATE,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    packed = zlib.compress(raw, level=6)
    encoded = base64.b64encode(packed).decode("ascii")
    chunks = [encoded[i:i + CHUNK_CHARS] for i in range(0, len(encoded), CHUNK_CHARS)] or [""]
    return chunks, digest, len(raw)


def _decode_state(chunks: List[str], expected_sha256: str) -> Dict[str, Any]:
    encoded = "".join(chunks)
    raw = zlib.decompress(base64.b64decode(encoded.encode("ascii")))
    digest = hashlib.sha256(raw).hexdigest()
    if expected_sha256 and digest != expected_sha256:
        raise RuntimeError("D1 state checksum mismatch")
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("D1 state payload is not a JSON object")
    return payload


def load_state() -> bool:
    if not ensure_db():
        return False
    try:
        result = _request({
            "batch": [
                {
                    "sql": "SELECT encoding, chunk_count, payload_sha256, uncompressed_bytes, updated_at FROM lumen_state_manifest WHERE state_key = ? LIMIT 1",
                    "params": [STATE_KEY],
                },
                {
                    "sql": "SELECT chunk_no, payload FROM lumen_state_chunks WHERE state_key = ? ORDER BY chunk_no ASC",
                    "params": [STATE_KEY],
                },
            ]
        })
        statements = _result_statements(result)
        manifest_rows = _statement_rows(statements[0]) if len(statements) >= 1 else []
        chunk_rows = _statement_rows(statements[1]) if len(statements) >= 2 else []
        if not manifest_rows:
            lumen_app.DB_STATUS.update({"connected": True, "last_error": None, "state_initialized": False})
            return False

        manifest = manifest_rows[0]
        if str(manifest.get("encoding") or "") != "zlib+base64+json":
            raise RuntimeError(f"Unsupported D1 state encoding: {manifest.get('encoding')}")
        expected_count = int(manifest.get("chunk_count") or 0)
        if expected_count <= 0 or len(chunk_rows) != expected_count:
            raise RuntimeError(f"Incomplete D1 state: expected {expected_count} chunks, got {len(chunk_rows)}")
        payload = _decode_state(
            [str(row.get("payload") or "") for row in chunk_rows],
            str(manifest.get("payload_sha256") or ""),
        )

        current = lumen_app.default_state()
        current.update(payload)
        lumen_app.ensure_commerce_state(current)
        lumen_app.STATE.clear()
        lumen_app.STATE.update(current)
        lumen_app.DB_STATUS.update({
            "connected": True,
            "last_error": None,
            "backend": "cloudflare_d1",
            "state_initialized": True,
            "state_chunks": expected_count,
            "state_bytes": int(manifest.get("uncompressed_bytes") or 0),
            "state_updated_at": manifest.get("updated_at"),
        })
        return True
    except Exception as exc:
        lumen_app.DB_STATUS.update({"connected": False, "last_error": str(exc)[:500], "backend": "cloudflare_d1"})
        return False


def save_state() -> bool:
    if not ensure_db():
        return False
    try:
        chunks, digest, raw_bytes = _encode_state()
        batch: List[Dict[str, Any]] = [
            {"sql": "DELETE FROM lumen_state_chunks WHERE state_key = ?", "params": [STATE_KEY]},
        ]
        for idx, payload in enumerate(chunks):
            batch.append({
                "sql": "INSERT INTO lumen_state_chunks(state_key, chunk_no, payload) VALUES (?, ?, ?)",
                "params": [STATE_KEY, idx, payload],
            })
        batch.append({
            "sql": "INSERT INTO lumen_state_manifest(state_key, encoding, chunk_count, payload_sha256, uncompressed_bytes, updated_at) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(state_key) DO UPDATE SET encoding=excluded.encoding, chunk_count=excluded.chunk_count, payload_sha256=excluded.payload_sha256, uncompressed_bytes=excluded.uncompressed_bytes, updated_at=excluded.updated_at",
            "params": [STATE_KEY, "zlib+base64+json", len(chunks), digest, raw_bytes, _utcnow()],
        })
        result = _request({"batch": batch})
        statements = _result_statements(result)
        if statements and any(isinstance(x, dict) and x.get("success") is False for x in statements):
            raise RuntimeError(f"D1 save batch failed: {str(statements)[:1200]}")
        lumen_app.DB_STATUS.update({
            "configured": True,
            "connected": True,
            "backend": "cloudflare_d1",
            "zero_cost_mode": True,
            "last_error": None,
            "state_initialized": True,
            "state_chunks": len(chunks),
            "state_bytes": raw_bytes,
        })
        return True
    except Exception as exc:
        lumen_app.DB_STATUS.update({"connected": False, "last_error": str(exc)[:500], "backend": "cloudflare_d1"})
        return False


if ZERO_MODE:
    lumen_app.ensure_db = ensure_db
    lumen_app.load_state = load_state
    lumen_app.save_state = save_state
    lumen_app.DATABASE_URL = ""
    lumen_app.DB_STATUS.update({
        "configured": _CONFIGURED,
        "connected": False,
        "backend": "cloudflare_d1",
        "zero_cost_mode": True,
        "last_error": None if _CONFIGURED else "D1 credentials missing",
    })
    print({
        "d1_persistence_runtime": {
            "status": "installed" if _CONFIGURED else "awaiting_credentials",
            "backend": "cloudflare_d1",
            "chunk_chars": CHUNK_CHARS,
            "zero_cost_mode": True,
        }
    }, flush=True)
