from __future__ import annotations

"""Zero-cost reuse of already stored, buyer-bound public demand evidence.

This module never searches the web. It only re-evaluates evidence that LUMEN already persisted and
may promote a verified buyer to demand_signal=True when the evidence is explicitly linked to that
buyer, contains a strong demand term, has a public URL and reaches the existing Demand Intelligence
threshold (75). No requirement field is inferred and no contact/outbound gate is relaxed.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Tuple
from urllib.parse import urlparse

import app
import demand_intelligence

VERSION = "1.0-exact-stored-demand-reuse"
MIN_SCORE = 75


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _host(value: Any) -> str:
    try:
        return (urlparse(str(value or "")).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _linked_account_id(row: Dict[str, Any]) -> str:
    for key in ("account_id", "buyer_account_id", "candidate_account_id", "linked_account_id"):
        value = _text(row.get(key))
        if value:
            return value
    return ""


def _url(row: Dict[str, Any]) -> str:
    for key in ("url", "source_url", "demand_evidence_url", "official_url"):
        value = _text(row.get(key))
        if value.startswith("http://") or value.startswith("https://"):
            return value
    return ""


def _strong_term_present(row: Dict[str, Any]) -> bool:
    blob = " ".join(
        _text(row.get(k)).lower()
        for k in ("title", "snippet", "summary", "need", "category", "query")
        if _text(row.get(k))
    )
    return any(term in blob for term in demand_intelligence.STRONG_DEMAND_TERMS)


def _evidence_rows(state: Dict[str, Any]) -> Iterable[Tuple[str, Dict[str, Any]]]:
    for key in (
        "demand_signals",
        "public_procurement_signals",
        "unlinked_demand_signals",
        "research_leads",
    ):
        for row in state.get(key, []) or []:
            if isinstance(row, dict):
                yield key, row


def _score(account: Dict[str, Any], row: Dict[str, Any]) -> int:
    try:
        existing = int(float(row.get("score") or row.get("demand_score") or 0))
    except (TypeError, ValueError):
        existing = 0
    item = {
        "title": _text(row.get("title") or row.get("name")),
        "snippet": _text(row.get("snippet") or row.get("summary") or row.get("need")),
        "url": _url(row),
    }
    try:
        rescored = int((demand_intelligence._score(account, item) or {}).get("score") or 0)
    except Exception:
        rescored = 0
    return max(existing, rescored)


def run_once(state: Dict[str, Any] | None = None) -> Dict[str, Any]:
    if state is None:
        if not app.load_state():
            report = {"version": VERSION, "status": "state_unavailable", "promoted": 0, "searches_used": 0}
            print({"demand_inventory_reuse": report}, flush=True)
            return report
        state = app.STATE

    accounts = {
        str(row.get("id") or ""): row
        for row in state.get("candidate_accounts", []) or []
        if isinstance(row, dict) and row.get("id")
    }
    candidates = {
        aid: row
        for aid, row in accounts.items()
        if row.get("type") == "buyer" and row.get("verified_company") and not row.get("demand_signal")
    }

    reviewed = 0
    exact_linked = 0
    strong = 0
    qualified = 0
    promoted = 0
    rejected_low_score = 0
    rejected_no_url = 0
    rejected_no_strong_term = 0
    evidence_used: List[Dict[str, Any]] = []

    for source_key, row in _evidence_rows(state):
        reviewed += 1
        aid = _linked_account_id(row)
        account = candidates.get(aid)
        if not account:
            continue
        exact_linked += 1
        url = _url(row)
        if not url:
            rejected_no_url += 1
            continue
        if not _strong_term_present(row):
            rejected_no_strong_term += 1
            continue
        strong += 1
        score = _score(account, row)
        if score < MIN_SCORE:
            rejected_low_score += 1
            continue
        qualified += 1

        # Exact buyer lineage is mandatory. A same-domain URL is useful corroboration but not a
        # substitute for the explicit account link, especially for government procurement portals.
        evidence_urls = list(account.get("demand_evidence_urls", []) or [])
        if url not in evidence_urls:
            evidence_urls.append(url)
        account["demand_evidence_urls"] = evidence_urls[-6:]
        account["demand_evidence_url"] = url
        account["demand_score"] = max(float(account.get("demand_score") or 0), float(score))
        account["demand_signal"] = True
        account["demand_status"] = "public_signal_verified_from_stored_exact_evidence"
        account["status"] = "demand_verified"
        account["demand_last_checked"] = _now()
        account["demand_verification_basis"] = "stored_public_evidence_exact_account_lineage"
        account["next_action"] = "Construir tesis de oportunidad y validar requerimiento/contacto comercial"
        account.pop("demand_next_check", None)

        demand_signals = state.setdefault("demand_signals", [])
        already = any(
            isinstance(x, dict)
            and str(x.get("account_id") or "") == aid
            and _url(x) == url
            for x in demand_signals
        )
        if not already:
            demand_signals.append({
                "id": f"SIG-REUSE-{aid}-{len(demand_signals)+1}",
                "account_id": aid,
                "category": account.get("category"),
                "url": url,
                "title": _text(row.get("title") or row.get("name"))[:300],
                "snippet": _text(row.get("snippet") or row.get("summary") or row.get("need"))[:700],
                "score": score,
                "source": "stored_exact_public_evidence_reuse",
                "source_inventory": source_key,
                "created_at": _now(),
            })

        evidence_used.append({
            "account_id": aid,
            "source_inventory": source_key,
            "score": score,
            "host": _host(url),
        })
        promoted += 1
        candidates.pop(aid, None)

    report = {
        "version": VERSION,
        "status": "active",
        "reviewed_rows": reviewed,
        "verified_buyers_without_demand_before": len(candidates) + promoted,
        "exact_linked_rows": exact_linked,
        "strong_demand_rows": strong,
        "qualified_rows": qualified,
        "promoted": promoted,
        "rejected_low_score": rejected_low_score,
        "rejected_no_url": rejected_no_url,
        "rejected_no_strong_term": rejected_no_strong_term,
        "remaining_verified_buyers_without_demand": len(candidates),
        "searches_used": 0,
        "minimum_score_unchanged": MIN_SCORE,
        "exact_buyer_lineage_required": True,
        "requirements_inferred": False,
        "outbound_gate_relaxed": False,
        "evidence_used": evidence_used[:10],
        "updated_at": _now(),
    }
    state["demand_inventory_reuse"] = report
    app.save_state()
    print({"demand_inventory_reuse": report}, flush=True)
    return report
