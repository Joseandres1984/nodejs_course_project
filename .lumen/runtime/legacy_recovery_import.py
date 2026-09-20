from __future__ import annotations

"""One-time, fail-closed import of sanitized Railway history into LUMEN Zero/D1.

The archive is historical evidence only. It is deliberately stored under an isolated
`legacy_recovery` namespace and is never merged into current companies, contacts,
opportunities or outbound queues. Every recovered counterparty requires fresh
verification before any future use.
"""

import base64
import hashlib
import json
import os
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

os.environ["LUMEN_ZERO_COST_MODE"] = "true"

# Importing the adapter first patches app.load_state/save_state to use D1.
import d1_persistence_runtime  # noqa: E402,F401
import app as lumen_app  # noqa: E402

ARCHIVE_PATH = Path(__file__).resolve().parents[1] / "recovery" / "railway_legacy_accounts_20260919.zlib.b64"
EXPECTED_SHA256 = "fd3a2342a601caf9454277229e7b69a77b5e30ae6015e6576bbf757552de85b1"
RECOVERY_KEY = "railway_20260919"
SNAPSHOT_AT = "2026-09-19T14:45:58Z"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_hash_without_recovery(state: Dict[str, Any]) -> str:
    payload = {k: v for k, v in state.items() if k != "legacy_recovery"}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def load_archive() -> Dict[str, Any]:
    encoded = ARCHIVE_PATH.read_text(encoding="utf-8").strip()
    raw = zlib.decompress(base64.b64decode(encoded.encode("ascii")))
    digest = hashlib.sha256(raw).hexdigest()
    if digest != EXPECTED_SHA256:
        raise RuntimeError(f"legacy archive checksum mismatch: {digest}")
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("legacy archive payload is not an object")
    accounts = payload.get("accounts")
    if not isinstance(accounts, list) or len(accounts) != 580:
        raise RuntimeError(f"legacy archive account count mismatch: {len(accounts) if isinstance(accounts, list) else 'invalid'}")
    if payload.get("historical_only") is not True or payload.get("auto_promote_to_current_pipeline") is not False:
        raise RuntimeError("legacy archive safety policy mismatch")
    return payload


def queue_priority(account: Dict[str, Any]) -> float:
    score = float(account.get("legacy_score") or 0.0)
    if account.get("historical_verified_company"):
        score += 15.0
    if account.get("historical_verified_contact"):
        score += 20.0
    if account.get("type") == "buyer":
        score += 4.0
    reason = str(account.get("legacy_reason") or "")
    if not reason:
        score += 12.0
    elif reason == "recent_successful_contact_window":
        score -= 12.0
    elif reason == "below_outbound_score":
        score -= 8.0
    return round(score, 1)


def build_reverification_queue(accounts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # One queue item per official domain. Keep every original account in the archive;
    # deduplication only prevents wasting future verification work.
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for account in accounts:
        domain = str(account.get("official_domain") or "").strip().lower()
        if not domain:
            continue
        grouped.setdefault(domain, []).append(account)

    queue: List[Dict[str, Any]] = []
    for domain, rows in grouped.items():
        suppressed = any(str(row.get("legacy_reason") or "") == "suppressed_or_optout" for row in rows)
        representative = max(rows, key=queue_priority)
        item = {
            "official_domain": domain,
            "legacy_ids": [str(row.get("legacy_id") or "") for row in rows if row.get("legacy_id")],
            "type": representative.get("type"),
            "priority": queue_priority(representative),
            "status": "suppressed_do_not_contact" if suppressed else "pending_reverification",
            "safe_for_outbound": False,
            "requires_company_reverification": True,
            "requires_contact_reverification": True,
            "historical_verified_company": bool(representative.get("historical_verified_company")),
            "historical_verified_contact": bool(representative.get("historical_verified_contact")),
            "legacy_score": representative.get("legacy_score"),
            "legacy_reason": representative.get("legacy_reason"),
            "do_not_contact": bool(suppressed),
        }
        queue.append(item)

    queue.sort(key=lambda row: (bool(row.get("do_not_contact")), -float(row.get("priority") or 0.0), str(row.get("official_domain") or "")))
    return queue


def main() -> None:
    archive = load_archive()
    if not lumen_app.load_state():
        raise RuntimeError(f"refusing recovery import because current D1 state could not be loaded: {lumen_app.DB_STATUS}")

    before_hash = stable_hash_without_recovery(lumen_app.STATE)
    root = lumen_app.STATE.setdefault("legacy_recovery", {})
    if not isinstance(root, dict):
        raise RuntimeError("existing legacy_recovery namespace is not an object")

    existing = root.get(RECOVERY_KEY)
    if isinstance(existing, dict) and existing.get("archive_sha256") == EXPECTED_SHA256:
        count = len(existing.get("accounts") or [])
        promoted = int(existing.get("auto_promoted_to_current_pipeline") or 0)
        if count != 580 or promoted != 0:
            raise RuntimeError(f"existing recovery record failed safety verification: count={count} promoted={promoted}")
        print({"legacy_recovery_import": {"status": "already_imported", "accounts": count, "auto_promoted": promoted, "safe_for_outbound": 0}}, flush=True)
        return

    accounts = archive["accounts"]
    queue = build_reverification_queue(accounts)
    suppressed = sum(1 for row in queue if row.get("do_not_contact"))
    current = {
        "schema_version": 1,
        "source": archive.get("source"),
        "snapshot_at": archive.get("snapshot_at") or SNAPSHOT_AT,
        "imported_at": utcnow(),
        "archive_sha256": EXPECTED_SHA256,
        "historical_only": True,
        "requires_reverification_before_outbound": True,
        "auto_promote_to_current_pipeline": False,
        "auto_promoted_to_current_pipeline": 0,
        "safe_for_outbound_count": 0,
        "legacy_summary": archive.get("legacy_summary") or {},
        "accounts": accounts,
        "reverification_queue": queue,
        "reverification_queue_count": len(queue) - suppressed,
        "suppressed_do_not_contact_count": suppressed,
        "policy": {
            "preserve_opt_outs": True,
            "fresh_company_verification_required": True,
            "fresh_contact_verification_required": True,
            "quality_gate_required": True,
            "no_legacy_verification_trust": True,
        },
    }
    root[RECOVERY_KEY] = current

    # Safety invariant: the import is allowed to change only legacy_recovery.
    after_hash = stable_hash_without_recovery(lumen_app.STATE)
    if after_hash != before_hash:
        raise RuntimeError("active LUMEN state changed during legacy import; refusing to save")

    if not lumen_app.save_state():
        raise RuntimeError(f"D1 save failed: {lumen_app.DB_STATUS}")

    # Reload from D1 and prove persistence plus isolation policy.
    if not lumen_app.load_state():
        raise RuntimeError("D1 verification reload failed")
    restored = (lumen_app.STATE.get("legacy_recovery") or {}).get(RECOVERY_KEY) or {}
    if len(restored.get("accounts") or []) != 580:
        raise RuntimeError("D1 verification failed: recovered account count is not 580")
    if int(restored.get("auto_promoted_to_current_pipeline") or 0) != 0:
        raise RuntimeError("D1 verification failed: legacy accounts were promoted")
    if int(restored.get("safe_for_outbound_count") or 0) != 0:
        raise RuntimeError("D1 verification failed: legacy accounts became outbound-safe")

    print({
        "legacy_recovery_import": {
            "status": "imported_verified",
            "accounts": 580,
            "unique_domains": len(queue),
            "pending_reverification": len(queue) - suppressed,
            "suppressed_do_not_contact": suppressed,
            "auto_promoted": 0,
            "safe_for_outbound": 0,
            "active_state_unchanged": True,
            "archive_sha256": EXPECTED_SHA256,
        }
    }, flush=True)


if __name__ == "__main__":
    main()
