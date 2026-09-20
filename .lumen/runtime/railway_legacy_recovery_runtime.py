from __future__ import annotations

"""Conservative recovery of historical Railway commercial accounts into LUMEN Zero.

The artifact is historical evidence only. This module never authorizes outbound,
never trusts legacy verification flags, and never invents missing fields. Recovered
accounts must pass the current company/contact verification gates again.
"""

import base64
import hashlib
import json
import os
import re
import urllib.parse
import zlib
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import app as lumen_app

VERSION = "1.0-railway-legacy-recovery"
SNAPSHOT_AT = "2026-09-19T14:45:58Z"
SOURCE = "railway_deploy_logs"
BATCH_SIZE = max(1, min(100, int(os.getenv("LUMEN_LEGACY_RECOVERY_BATCH", "50"))))
ARTIFACT = Path(__file__).resolve().parent.parent / "recovery" / "railway_legacy_accounts_20260919.zlib.b64"

URL_FIELDS = (
    "source_url", "official_url", "website", "url", "site", "homepage", "company_url",
)
NAME_FIELDS = ("name", "company_name", "account_name", "business_name", "title")
CATEGORY_FIELDS = ("category", "segment", "industry", "vertical", "sector")
TYPE_FIELDS = ("type", "role", "account_type", "commercial_role")
SUPPRESSION_FIELDS = (
    "suppressed", "opt_out", "optout", "do_not_contact", "do_not_email",
    "outbound_suppressed", "unsubscribe", "unsubscribed", "blocked",
)
TRUE_WORDS = {"1", "true", "yes", "si", "sí", "on", "suppressed", "optout", "opt_out", "blocked"}


def _clean(value: Any, limit: int = 500) -> str:
    text = str(value or "").strip()
    return text[:limit]


def _first(row: Dict[str, Any], fields: Iterable[str], limit: int = 500) -> str:
    for field in fields:
        value = _clean(row.get(field), limit)
        if value:
            return value
    return ""


def _domain_from_text(value: str) -> str:
    text = _clean(value, 1000)
    if not text:
        return ""
    candidate = text if "://" in text else f"https://{text}"
    try:
        host = (urllib.parse.urlparse(candidate).hostname or "").strip().lower()
    except Exception:
        return ""
    host = host.removeprefix("www.")
    if not host or "." not in host or " " in host:
        return ""
    if not re.fullmatch(r"[a-z0-9.-]+", host):
        return ""
    return host[:253]


def _domain(row: Dict[str, Any]) -> str:
    direct = _domain_from_text(_clean(row.get("domain"), 300))
    if direct:
        return direct
    for field in URL_FIELDS:
        value = _domain_from_text(_clean(row.get(field), 1000))
        if value:
            return value
    return ""


def _source_url(row: Dict[str, Any], domain: str) -> str:
    for field in URL_FIELDS:
        value = _clean(row.get(field), 1000)
        if value.startswith(("http://", "https://")):
            return value
    return f"https://{domain}/" if domain else ""


def _suppressed(row: Dict[str, Any]) -> bool:
    for field in SUPPRESSION_FIELDS:
        value = row.get(field)
        if value is True:
            return True
        if isinstance(value, (int, float)) and value != 0:
            return True
        if isinstance(value, str) and value.strip().lower() in TRUE_WORDS:
            return True
    status_text = " ".join(
        _clean(row.get(key), 200).lower()
        for key in ("status", "outbound_status", "suppression_reason", "reason")
    )
    return any(token in status_text for token in ("optout", "opt_out", "opt-out", "suppressed", "unsubscribe", "do_not_contact"))


def _row_hash(row: Dict[str, Any]) -> str:
    raw = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _artifact_rows() -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    encoded = ARTIFACT.read_text(encoding="utf-8").strip()
    packed = base64.b64decode(encoded.encode("ascii"), validate=True)
    raw = zlib.decompress(packed)
    digest = hashlib.sha256(raw).hexdigest()
    payload = json.loads(raw.decode("utf-8"))

    top_level_type = type(payload).__name__
    rows: Any = None
    selected_key = ""
    if isinstance(payload, list):
        rows = payload
        selected_key = "<root-list>"
    elif isinstance(payload, dict):
        for key in ("accounts", "commercial_accounts", "items", "rows", "data"):
            if isinstance(payload.get(key), list):
                rows = payload[key]
                selected_key = key
                break
    if not isinstance(rows, list):
        raise RuntimeError("legacy artifact has no supported account-list container")

    object_rows = [row for row in rows if isinstance(row, dict)]
    field_names = sorted({str(key) for row in object_rows[:25] for key in row.keys()})[:80]
    meta = {
        "artifact_sha256": digest,
        "top_level_type": top_level_type,
        "selected_key": selected_key,
        "rows_total": len(rows),
        "object_rows": len(object_rows),
        "non_object_rows": len(rows) - len(object_rows),
        "sample_field_names": field_names,
    }
    return object_rows, meta


def _existing_keys(accounts: List[Dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for account in accounts:
        if not isinstance(account, dict):
            continue
        domain = _domain(account)
        if domain:
            keys.add(f"domain:{domain}")
            continue
        source = _source_url(account, "")
        name = _first(account, NAME_FIELDS, 300).lower()
        if source or name:
            keys.add(f"fallback:{source.lower()}|{name}")
    return keys


def _identity_key(row: Dict[str, Any], domain: str, source_url: str, name: str) -> str:
    if domain:
        return f"domain:{domain}"
    if source_url or name:
        return f"fallback:{source_url.lower()}|{name.lower()}"
    return ""


def _safe_legacy_metadata(row: Dict[str, Any], row_hash: str) -> Dict[str, Any]:
    # Preserve the original record under a namespace so current production gates cannot
    # mistake stale legacy flags for current verification truth.
    return {
        "source": SOURCE,
        "snapshot_at": SNAPSHOT_AT,
        "row_sha256": row_hash,
        "original": row,
    }


def _to_candidate(row: Dict[str, Any], index: int) -> Tuple[Dict[str, Any] | None, str]:
    domain = _domain(row)
    source_url = _source_url(row, domain)
    name = _first(row, NAME_FIELDS, 300)
    key = _identity_key(row, domain, source_url, name)
    if not key:
        return None, "missing_identity"

    category = _first(row, CATEGORY_FIELDS, 300)
    role = _first(row, TYPE_FIELDS, 80).lower()
    account_type = "buyer" if role in {"buyer", "comprador", "client", "customer"} else "supplier" if role in {"supplier", "proveedor", "vendor"} else "unknown"
    is_suppressed = _suppressed(row)
    row_hash = _row_hash(row)

    candidate: Dict[str, Any] = {
        "id": f"legacy-{row_hash[:20]}",
        "name": name or domain,
        "domain": domain,
        "source_url": source_url,
        "category": category,
        "type": account_type,
        "confidence": 0.0,
        "status": "suppressed" if is_suppressed else "verification_required",
        "verification_status": "suppressed_legacy" if is_suppressed else "verification_required",
        "verified_company": False,
        "verified_contact": False,
        "legacy_recovered": True,
        "legacy_recovery_eligible": not is_suppressed,
        "legacy_source_index": index,
        "legacy": _safe_legacy_metadata(row, row_hash),
    }
    if is_suppressed:
        candidate.update({
            "outbound_suppressed": True,
            "suppression_reason": "legacy_suppression_preserved",
            "next_action": "No contactar; supresión histórica preservada",
        })
    else:
        candidate["next_action"] = "Reverificar empresa y contacto con evidencia pública actual"
    return candidate, key


def recover_once() -> Dict[str, Any]:
    rows, artifact_meta = _artifact_rows()
    if not lumen_app.load_state():
        return {
            "version": VERSION,
            "status": "state_unavailable_fail_closed",
            **artifact_meta,
            "batch_size": BATCH_SIZE,
            "newly_queued": 0,
            "duplicates_skipped": 0,
            "invalid_skipped": 0,
            "suppressed_preserved": 0,
            "outbound_triggered": False,
            "persisted": False,
        }

    state = lumen_app.STATE
    accounts = state.setdefault("candidate_accounts", [])
    if not isinstance(accounts, list):
        raise RuntimeError("candidate_accounts is not a list")

    recovery = state.setdefault("railway_legacy_recovery", {})
    digest = str(artifact_meta.get("artifact_sha256") or "")
    if recovery.get("artifact_sha256") != digest:
        recovery.clear()
        recovery.update({
            "version": VERSION,
            "artifact_sha256": digest,
            "source": SOURCE,
            "snapshot_at": SNAPSHOT_AT,
            "cursor": 0,
            "newly_queued_total": 0,
            "duplicates_skipped_total": 0,
            "invalid_skipped_total": 0,
            "suppressed_preserved_total": 0,
            "complete": False,
        })

    start = max(0, min(len(rows), int(recovery.get("cursor") or 0)))
    end = min(len(rows), start + BATCH_SIZE)
    existing = _existing_keys(accounts)

    newly_queued = 0
    duplicates_skipped = 0
    invalid_skipped = 0
    suppressed_preserved = 0

    for index in range(start, end):
        row = rows[index]
        candidate, key = _to_candidate(row, index)
        if candidate is None:
            invalid_skipped += 1
            continue
        if key in existing:
            duplicates_skipped += 1
            continue
        accounts.append(candidate)
        existing.add(key)
        newly_queued += 1
        if candidate.get("outbound_suppressed"):
            suppressed_preserved += 1

    recovery["cursor"] = end
    recovery["complete"] = end >= len(rows)
    recovery["rows_total"] = len(rows)
    recovery["newly_queued_total"] = int(recovery.get("newly_queued_total") or 0) + newly_queued
    recovery["duplicates_skipped_total"] = int(recovery.get("duplicates_skipped_total") or 0) + duplicates_skipped
    recovery["invalid_skipped_total"] = int(recovery.get("invalid_skipped_total") or 0) + invalid_skipped
    recovery["suppressed_preserved_total"] = int(recovery.get("suppressed_preserved_total") or 0) + suppressed_preserved
    recovery["last_batch"] = {
        "start": start,
        "end": end,
        "newly_queued": newly_queued,
        "duplicates_skipped": duplicates_skipped,
        "invalid_skipped": invalid_skipped,
        "suppressed_preserved": suppressed_preserved,
    }
    recovery["outbound_triggered"] = False

    persisted = bool(lumen_app.save_state())
    return {
        "version": VERSION,
        "status": "complete" if recovery.get("complete") else "recovering",
        **artifact_meta,
        "batch_size": BATCH_SIZE,
        "cursor_before": start,
        "cursor_after": end,
        "newly_queued": newly_queued,
        "duplicates_skipped": duplicates_skipped,
        "invalid_skipped": invalid_skipped,
        "suppressed_preserved": suppressed_preserved,
        "newly_queued_total": recovery.get("newly_queued_total"),
        "duplicates_skipped_total": recovery.get("duplicates_skipped_total"),
        "invalid_skipped_total": recovery.get("invalid_skipped_total"),
        "suppressed_preserved_total": recovery.get("suppressed_preserved_total"),
        "outbound_triggered": False,
        "persisted": persisted,
    }
