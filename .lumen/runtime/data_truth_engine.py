from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from autonomy_governor import record_decision

MAX_DEALS = 160
MAX_REFRESH_TASKS = 12


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_ts(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    variants = [text, text.replace(" UTC", "+00:00"), text.replace("Z", "+00:00")]
    for item in variants:
        try:
            dt = datetime.fromisoformat(item)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            pass
        try:
            return datetime.strptime(item, "%Y-%m-%d %H:%M:%S %Z").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _age_days(value: Any) -> float | None:
    dt = _parse_ts(value)
    if not dt:
        return None
    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0)


def _latest(rows: List[Dict[str, Any]], keys=("updated_at", "created_at", "ts", "verified_at")) -> Dict[str, Any]:
    best: Dict[str, Any] = {}
    best_dt = None
    for row in rows:
        for key in keys:
            dt = _parse_ts(row.get(key))
            if dt and (best_dt is None or dt > best_dt):
                best = row
                best_dt = dt
                break
    return best


def _account_index(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(x.get("id")): x for x in state.get("candidate_accounts", []) or [] if x.get("id")}


def _linked_offers(state: Dict[str, Any], deal_id: str) -> List[Dict[str, Any]]:
    return [x for x in state.get("offers", []) or [] if str(x.get("deal_id") or "") == deal_id and x.get("source") != "demo/simulación"]


def _linked_docs(state: Dict[str, Any], deal_id: str) -> List[Dict[str, Any]]:
    return [x for x in state.get("document_registry", []) or [] if str(x.get("deal_id") or "") == deal_id]


def _check(label: str, *, present: bool, ts: Any = None, ttl_days: float | None = None, weight: float = 10.0, critical: bool = False) -> Dict[str, Any]:
    age = _age_days(ts)
    if not present:
        status = "MISSING"
        freshness = 0.0
    elif ttl_days is None:
        status = "CURRENT"
        freshness = 1.0
    elif age is None:
        status = "AGE_UNKNOWN"
        freshness = 0.55
    elif age <= ttl_days:
        status = "CURRENT"
        freshness = max(0.65, 1.0 - (age / max(ttl_days, 1.0)) * 0.25)
    elif age <= ttl_days * 2:
        status = "STALE"
        freshness = 0.35
    else:
        status = "EXPIRED"
        freshness = 0.05
    return {
        "field": label,
        "status": status,
        "present": present,
        "age_days": round(age, 2) if age is not None else None,
        "ttl_days": ttl_days,
        "weight": weight,
        "critical": critical,
        "freshness_factor": freshness,
    }


def _deal_truth(state: Dict[str, Any], deal: Dict[str, Any], accounts: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    deal_id = str(deal.get("id") or "")
    offers = _linked_offers(state, deal_id)
    offer = _latest(offers)
    docs = _linked_docs(state, deal_id)
    buyer = accounts.get(str(deal.get("buyer_account_id") or ""), {})
    supplier = accounts.get(str(deal.get("supplier_account_id") or ""), {})
    route = (state.get("payment_route_index", {}) or {}).get(deal_id, {}) or {}
    trade = deal.get("trade", {}) or {}
    cross_border = bool(deal.get("cross_border")) or bool(trade.get("destination_country"))
    near_close = str(deal.get("stage") or "") in {
        "propuesta preparada", "negociación", "renegociación", "preclose_validation",
        "listo para cerrar", "autorizado para cierre", "listo para cierre aprobado",
    } or bool(deal.get("close_execution_ready_for_approval"))

    buyer_ts = buyer.get("last_verified_at") or buyer.get("verified_at") or buyer.get("updated_at") or buyer.get("created_at")
    supplier_ts = supplier.get("last_verified_at") or supplier.get("verified_at") or supplier.get("updated_at") or supplier.get("created_at")
    offer_ts = offer.get("updated_at") or offer.get("created_at") or offer.get("ts")
    trade_ts = trade.get("fx_updated_at") or trade.get("updated_at") or trade.get("created_at")
    doc = _latest(docs)
    doc_ts = doc.get("updated_at") or doc.get("created_at") or doc.get("processed_at")

    checks = [
        _check("buyer_identity", present=bool(buyer and buyer.get("verified_company")), ts=buyer_ts, ttl_days=90, weight=12, critical=near_close),
        _check("supplier_identity", present=bool(supplier and supplier.get("verified_company")), ts=supplier_ts, ttl_days=90, weight=12, critical=near_close),
        _check("supplier_quote", present=bool(offer and _f(offer.get("amount")) > 0 and offer.get("currency")), ts=offer_ts, ttl_days=14, weight=22, critical=near_close),
        _check("payment_route", present=bool(route.get("status") == "READY"), ts=route.get("updated_at"), ttl_days=7, weight=12, critical=near_close),
        _check("safe_close", present=bool(deal.get("deal_safeguards_cleared")) and not bool(deal.get("incident_hold")), ts=(deal.get("deal_safeguards") or {}).get("updated_at"), ttl_days=2, weight=18, critical=near_close),
        _check("document_evidence", present=bool(docs), ts=doc_ts, ttl_days=60, weight=8, critical=False),
    ]
    if cross_border:
        checks.append(_check("trade_fx_terms", present=bool(trade), ts=trade_ts, ttl_days=2, weight=16, critical=near_close))
    total_weight = sum(_f(x.get("weight")) for x in checks) or 1.0
    score = sum(_f(x.get("weight")) * _f(x.get("freshness_factor")) for x in checks) / total_weight * 100.0
    critical_refresh = [x["field"] for x in checks if x.get("critical") and x.get("status") in {"MISSING", "STALE", "EXPIRED"}]
    refresh = [x["field"] for x in checks if x.get("status") in {"MISSING", "STALE", "EXPIRED", "AGE_UNKNOWN"}]
    if critical_refresh:
        truth_class = "CRITICAL_REFRESH"
    elif score < 55:
        truth_class = "STALE"
    elif score < 78:
        truth_class = "PARTIAL"
    else:
        truth_class = "CURRENT"
    return {
        "deal_id": deal_id,
        "score": round(max(0.0, min(100.0, score)), 2),
        "truth_class": truth_class,
        "near_close": near_close,
        "critical_refresh": critical_refresh,
        "refresh_required": refresh,
        "checks": checks,
        "updated_at": utcnow(),
        "rule": "Hechos operativos envejecen; histórico, hipótesis y dato actual no son equivalentes.",
    }


def _refresh_tasks(state: Dict[str, Any], rows: List[Dict[str, Any]]) -> int:
    queue = list(state.get("operating_action_queue", []) or [])
    by_key = {str(x.get("key")): x for x in queue if x.get("key")}
    created = 0
    for row in sorted(rows, key=lambda x: (bool(x.get("critical_refresh")), -_f(x.get("score"))), reverse=True):
        if created >= MAX_REFRESH_TASKS or not row.get("refresh_required"):
            continue
        critical = bool(row.get("critical_refresh"))
        priority = 98.0 if critical else 82.0 if _f(row.get("score")) < 60 else 70.0
        key = f"data_truth|{row.get('deal_id')}"
        by_key[key] = {
            "key": key,
            "kind": "data_truth_refresh",
            "title": f"Actualizar evidencia crítica de {row.get('deal_id')}",
            "reason": "Campos a refrescar: " + ", ".join(row.get("refresh_required") or []),
            "impact": 98.0 if critical else 78.0,
            "urgency": priority,
            "confidence": 0.98,
            "effort": 1.0,
            "risk": "medium" if critical else "low",
            "autonomous": True,
            "object_type": "deal",
            "object_id": str(row.get("deal_id") or ""),
            "payload": {"truth_score": row.get("score"), "critical_refresh": row.get("critical_refresh"), "refresh_required": row.get("refresh_required")},
            "priority_score": priority,
            "created_at": utcnow(),
        }
        created += 1
    state["operating_action_queue"] = sorted(by_key.values(), key=lambda x: _f(x.get("priority_score")), reverse=True)[:120]
    return created


def data_truth_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    accounts = _account_index(state)
    rows: List[Dict[str, Any]] = []
    for deal in (state.get("deals", []) or [])[:MAX_DEALS]:
        if deal.get("source") == "demo" or str(deal.get("stage") or "") in {"closed_simulated", "cerrado (simulación)"}:
            continue
        row = _deal_truth(state, deal, accounts)
        rows.append(row)
        deal["data_truth_score"] = row["score"]
        deal["data_truth_class"] = row["truth_class"]
        deal["truth_refresh_required"] = list(row["refresh_required"])
        deal["truth_close_hold"] = bool(row["critical_refresh"])
        deal["data_truth_updated_at"] = row["updated_at"]

    rows.sort(key=lambda x: (bool(x.get("critical_refresh")), -_f(x.get("score"))), reverse=True)
    tasks = _refresh_tasks(state, rows)
    scores = [_f(x.get("score")) for x in rows]
    report = {
        "updated_at": utcnow(),
        "mode": "continuous_data_truth_and_freshness",
        "deals_reviewed": len(rows),
        "average_truth_score": round(sum(scores) / len(scores), 2) if scores else 100.0,
        "critical_refresh": sum(1 for x in rows if x.get("critical_refresh")),
        "stale_or_partial": sum(1 for x in rows if x.get("truth_class") in {"STALE", "PARTIAL"}),
        "refresh_tasks_created": tasks,
        "rows": rows[:80],
        "governance": {
            "truth_rule": "Dato presente no equivale a dato actual; cada evidencia relevante tiene fuente/frescura y puede expirar.",
            "close_rule": "Datos críticos vencidos cerca del cierre generan truth_close_hold y deben refrescarse antes de tratar el paquete como listo.",
            "no_fabrication": "Falta de timestamp se trata como edad desconocida, nunca como información fresca.",
        },
    }
    state["data_truth_engine"] = report
    state["data_truth_index"] = {str(x.get("deal_id")): x for x in rows if x.get("deal_id")}
    if rows:
        worst = rows[0]
        record_decision(
            state,
            engine="Data Truth Engine",
            object_type="deal",
            object_id=str(worst.get("deal_id") or ""),
            decision=f"truth:{str(worst.get('truth_class') or '').lower()}",
            reason=f"Truth score {worst.get('score')}; refrescar: {', '.join(worst.get('refresh_required') or []) or 'nada'}.",
            action="research_public",
            confidence=0.98,
            evidence_refs=[],
            allowed=True,
            requires_approval=False,
        )
    return report


def enforce_truth_on_closing(state: Dict[str, Any]) -> Dict[str, Any]:
    truth = state.get("data_truth_index", {}) or {}
    packs = state.get("closing_packs", []) or []
    blocked = 0
    for pack in packs:
        deal_id = str(pack.get("deal_id") or "")
        row = truth.get(deal_id, {}) or {}
        if not row.get("critical_refresh"):
            continue
        if pack.get("status") == "READY_FOR_HUMAN_APPROVAL":
            pack["status"] = "BUILDING"
            pack["missing"] = list(dict.fromkeys(list(pack.get("missing") or []) + ["data_truth_refresh"]))
            pack["truth_hold"] = True
            pack["truth_score"] = row.get("score")
            blocked += 1
        deal = next((x for x in state.get("deals", []) or [] if str(x.get("id") or "") == deal_id), None)
        if deal:
            deal["close_execution_ready_for_approval"] = False
    if packs:
        state["closing_pack_index"] = {str(x.get("deal_id")): x for x in packs if x.get("deal_id")}
        closing = state.get("closing_orchestrator", {}) or {}
        closing["packs"] = packs
        closing["ready_for_human_approval"] = sum(1 for x in packs if x.get("status") == "READY_FOR_HUMAN_APPROVAL")
        closing["truth_blocked"] = blocked
        state["closing_orchestrator"] = closing
    report = {"updated_at": utcnow(), "closing_packs_truth_blocked": blocked}
    state["data_truth_close_guard"] = report
    return report
