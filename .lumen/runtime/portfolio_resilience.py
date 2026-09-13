from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict


def _norm(value: Any) -> str:
    return " ".join(str(value or "").lower().strip().split())


def _age_days(value: Any):
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S UTC", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            ts = datetime.strptime(text, fmt)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds() / 86400.0)
        except ValueError:
            pass
    return None


def resilience_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    accounts = state.get("candidate_accounts", []) or []
    buyers = {str(x.get("id")): x for x in accounts if x.get("type") == "buyer" and x.get("id")}
    suppliers = {}
    for account in accounts:
        if account.get("type") == "supplier" and account.get("verified_company"):
            suppliers.setdefault(_norm(account.get("category")), []).append(account)

    resilient = 0
    single_source = 0
    stale = 0
    for opp in state.get("market_opportunities", []) or []:
        category = _norm(opp.get("category"))
        selected = str(opp.get("supplier_account_id") or "")
        backups = [x for x in suppliers.get(category, []) if str(x.get("id") or "") != selected]
        opp["supplier_backup_count"] = len(backups)
        opp["single_source_risk"] = len(backups) == 0
        if backups:
            resilient += 1
        else:
            single_source += 1

        buyer = buyers.get(str(opp.get("buyer_account_id") or ""), {})
        age = _age_days(buyer.get("demand_last_checked") or opp.get("updated_at") or opp.get("created_at"))
        opp["demand_freshness_days"] = round(age, 1) if age is not None else None
        if age is None:
            freshness = "UNKNOWN"
        elif age <= 14:
            freshness = "FRESH"
        elif age <= 30:
            freshness = "AGING"
        else:
            freshness = "STALE"
            stale += 1
        opp["demand_freshness_status"] = freshness
        opp["elite_attention_state"] = (
            "REFRESH_DEMAND" if freshness == "STALE"
            else "BUILD_SUPPLIER_BACKUP" if opp["single_source_risk"]
            else "RESILIENT_ACTIVE"
        )

    report = {
        "opportunities": len(state.get("market_opportunities", []) or []),
        "resilient": resilient,
        "single_source": single_source,
        "stale_demand": stale,
    }
    state["portfolio_resilience"] = report
    return report


def adjust_lane(state: Dict[str, Any], lane: Dict[str, Any]) -> Dict[str, Any]:
    opp_id = str(lane.get("opportunity_id") or "")
    opp = next((x for x in state.get("market_opportunities", []) or [] if str(x.get("id") or "") == opp_id), {})
    if not opp:
        return lane
    score = float(lane.get("score") or 0)
    backups = int(opp.get("supplier_backup_count") or 0)
    freshness = str(opp.get("demand_freshness_status") or "UNKNOWN")
    score += 4 if backups else -5
    if freshness == "AGING":
        score -= 4
    elif freshness == "STALE":
        score -= 12
    lane["score"] = round(max(0.0, min(100.0, score)), 2)
    lane["supplier_backup_count"] = backups
    lane["single_source_risk"] = bool(opp.get("single_source_risk"))
    lane["demand_freshness_status"] = freshness
    lane["elite_attention_state"] = opp.get("elite_attention_state")
    return lane
