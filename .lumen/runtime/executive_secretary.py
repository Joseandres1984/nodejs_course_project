from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List


VERSION = "1.0-executive-secretary"
MAX_NEWS = 6
MAX_PENDING = 8
MAX_DECISIONS = 6
MAX_RESOLVED = 6
MAX_DEADLINES = 6


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clean(value: Any, limit: int = 360) -> str:
    return " ".join(str(value or "").split())[:limit]


def _sorted(rows: Iterable[Dict[str, Any]], key: str, reverse: bool = True) -> List[Dict[str, Any]]:
    return sorted(list(rows or []), key=lambda x: str(x.get(key) or ""), reverse=reverse)


def _counts(state: Dict[str, Any]) -> Dict[str, int]:
    alerts = state.get("executive_alerts", []) or []
    queue = state.get("operating_action_queue", []) or []
    signals = state.get("unlinked_demand_signals", []) or []
    return {
        "research_leads": len(state.get("research_leads", []) or []),
        "candidate_accounts": len(state.get("candidate_accounts", []) or []),
        "market_opportunities": len(state.get("market_opportunities", []) or []),
        "deals": len(state.get("deals", []) or []),
        "public_procurement_signals": len(signals),
        "pending_actions": len(queue),
        "human_actions": sum(1 for x in alerts if x.get("status") == "open" and x.get("action_required")),
        "inbox_unprocessed": sum(1 for x in state.get("inbox", []) or [] if not x.get("processed")),
        "documents_ocr": sum(1 for x in state.get("document_registry", []) or [] if x.get("extraction_status") == "ocr_required"),
    }


def _news(state: Dict[str, Any], seen: set[str]) -> List[Dict[str, Any]]:
    rows = []
    signals = sorted(
        list(state.get("unlinked_demand_signals", []) or []),
        key=lambda x: (_f(x.get("score")), str(x.get("created_at") or "")),
        reverse=True,
    )
    for row in signals:
        url = str(row.get("url") or "")
        item_id = str(row.get("id") or url)
        rows.append({
            "id": item_id,
            "title": _clean(row.get("title") or row.get("category") or "Señal comercial", 220),
            "summary": _clean(row.get("snippet") or "Demanda pública detectada; falta resolver comprador y requisitos.", 420),
            "category": _clean(row.get("category"), 120),
            "source": _clean(row.get("host"), 120),
            "url": url,
            "score": round(_f(row.get("score")), 1),
            "created_at": row.get("created_at"),
            "new_since_last_brief": item_id not in seen,
            "truth_label": "señal pública; no equivale a oportunidad verificada",
        })
        if len(rows) >= MAX_NEWS:
            break

    # Notification events are already deduplicated by the notification router and are useful as a
    # second source of commercial news without consuming additional web-search quota.
    for event in reversed(list(state.get("notification_events", []) or [])[-30:]):
        if len(rows) >= MAX_NEWS:
            break
        if str(event.get("severity") or "").upper() == "INFO" and event.get("kind") not in {"opportunity_detected"}:
            continue
        item_id = f"notification:{event.get('id') or event.get('key')}"
        if any(x["id"] == item_id for x in rows):
            continue
        rows.append({
            "id": item_id,
            "title": _clean(event.get("title") or "Novedad LUMEN", 220),
            "summary": _clean(event.get("summary"), 420),
            "category": _clean(event.get("kind"), 120),
            "source": "LUMEN",
            "url": "",
            "score": 0.0,
            "created_at": event.get("created_at"),
            "new_since_last_brief": item_id not in seen,
            "truth_label": "evento interno con evidencia según su motor de origen",
        })
    return rows[:MAX_NEWS]


def _pending(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    queue = sorted(
        list(state.get("operating_action_queue", []) or []),
        key=lambda x: _f(x.get("priority_score")),
        reverse=True,
    )
    out = []
    for task in queue[:MAX_PENDING]:
        out.append({
            "key": str(task.get("key") or task.get("object_id") or ""),
            "title": _clean(task.get("title") or task.get("kind") or "Pendiente", 220),
            "reason": _clean(task.get("reason"), 420),
            "priority": round(_f(task.get("priority_score")), 1),
            "owner": "José" if task.get("autonomous") is False else "LUMEN",
            "risk": _clean(task.get("risk"), 80),
            "object_type": task.get("object_type"),
            "object_id": task.get("object_id"),
        })
    return out


def _decisions(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    alerts = [
        x for x in state.get("executive_alerts", []) or []
        if x.get("status") == "open" and x.get("action_required")
    ]
    alerts.sort(
        key=lambda x: ({"critical": 4, "high": 3, "medium": 2, "low": 1}.get(str(x.get("severity") or "").lower(), 0), str(x.get("last_seen_at") or "")),
        reverse=True,
    )
    return [{
        "id": str(x.get("id") or ""),
        "title": _clean(x.get("title") or "Decisión requerida", 220),
        "message": _clean(x.get("message"), 420),
        "recommendation": _clean(x.get("recommendation"), 420),
        "severity": str(x.get("severity") or "medium").lower(),
        "object_type": x.get("object_type"),
        "object_id": x.get("object_id"),
    } for x in alerts[:MAX_DECISIONS]]


def _deadlines(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    sources = (
        ("deal", state.get("deals", []) or []),
        ("opportunity", state.get("market_opportunities", []) or []),
        ("transaction", state.get("transactions", []) or []),
        ("task", state.get("operating_action_queue", []) or []),
    )
    keys = ("due_at", "deadline", "deadline_at", "expires_at", "valid_until", "closing_at", "offer_deadline")
    for kind, items in sources:
        for row in items:
            value = next((row.get(k) for k in keys if row.get(k)), None)
            if not value:
                continue
            rows.append({
                "when": str(value),
                "kind": kind,
                "id": str(row.get("id") or row.get("key") or row.get("object_id") or ""),
                "title": _clean(row.get("title") or row.get("category") or row.get("buyer") or kind, 220),
            })
    return sorted(rows, key=lambda x: x["when"])[:MAX_DEADLINES]


def _admin_attention(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    docs = sum(1 for x in state.get("document_registry", []) or [] if x.get("extraction_status") == "ocr_required")
    inbox = sum(1 for x in state.get("inbox", []) or [] if not x.get("processed"))
    coo = state.get("autonomous_coo", {}) or {}
    attention = coo.get("operational_attention", {}) or {}
    historical_delivery = int(attention.get("historical_delivery_reviews") or 0)
    current_failures = int(attention.get("current_commercial_failures") or 0)
    professional = state.get("professional_casework", {}) or {}
    waiting_budget = int(professional.get("waiting_budget") or 0)
    rows = []
    if docs:
        rows.append({"title": "Documentos pendientes de lectura", "count": docs, "owner": "LUMEN/José", "detail": "Hay documentos marcados para OCR o revisión."})
    if inbox:
        rows.append({"title": "Mensajes sin procesar", "count": inbox, "owner": "LUMEN", "detail": "La bandeja tiene mensajes aún no vinculados/procesados."})
    if current_failures:
        rows.append({"title": "Fallas comerciales actuales", "count": current_failures, "owner": "José/LUMEN", "detail": "Requieren revisión antes de reintentar para evitar duplicados."})
    if historical_delivery:
        rows.append({"title": "Revisión histórica de entrega", "count": historical_delivery, "owner": "Administrativo", "detail": "Antecedentes viejos visibles para auditoría; no representan salud actual."})
    if waiting_budget:
        rows.append({"title": "Expedientes esperando presupuesto de búsqueda", "count": waiting_budget, "owner": "LUMEN", "detail": "Continuarán cuando se libere el presupuesto diario de investigación."})
    return rows[:8]


def _resolved(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for alert in _sorted(state.get("executive_alerts", []) or [], "resolved_at"):
        if alert.get("status") != "resolved" or not alert.get("resolved_at"):
            continue
        rows.append({
            "ts": alert.get("resolved_at"),
            "title": _clean(alert.get("title") or "Alerta resuelta", 220),
            "detail": _clean(alert.get("resolution_action") or "La condición que originó la alerta dejó de estar activa.", 320),
        })
        if len(rows) >= MAX_RESOLVED:
            return rows

    keywords = ("detectó", "actualizó", "resolv", "complet", "verific", "amplió automáticamente", "creó", "recibió")
    for item in state.get("activity", []) or []:
        text = _clean(item.get("msg"), 360)
        if not text or not any(k in text.lower() for k in keywords):
            continue
        rows.append({"ts": item.get("ts"), "title": text, "detail": "Registrado por la actividad operativa de LUMEN."})
        if len(rows) >= MAX_RESOLVED:
            break
    return rows


def build_secretary_snapshot(state: Dict[str, Any], *, mutate_memory: bool = False) -> Dict[str, Any]:
    memory = dict(state.get("executive_secretary_memory", {}) or {})
    previous_counts = dict(memory.get("last_counts", {}) or {})
    seen = set(str(x) for x in memory.get("seen_news_ids", []) or [])
    counts = _counts(state)
    deltas = {key: counts[key] - int(previous_counts.get(key) or 0) for key in counts}
    news = _news(state, seen)
    pending = _pending(state)
    decisions = _decisions(state)
    deadlines = _deadlines(state)
    admin = _admin_attention(state)
    resolved = _resolved(state)
    new_news = sum(1 for x in news if x.get("new_since_last_brief"))

    brief = (
        f"José: {new_news} novedades comerciales desde el último informe, "
        f"{len(pending)} pendientes priorizados y {len(decisions)} decisiones que requieren tu atención. "
        f"LUMEN tiene {counts['public_procurement_signals']} señales de compras públicas registradas."
    )
    if not decisions:
        brief += " No hay decisiones vinculantes pendientes para vos en este momento."

    snapshot = {
        "version": VERSION,
        "updated_at": utcnow(),
        "status": "active",
        "brief": brief,
        "counts": counts,
        "deltas": deltas,
        "news": news,
        "pending": pending,
        "decisions": decisions,
        "deadlines": deadlines,
        "admin_attention": admin,
        "resolved": resolved,
        "policy": {
            "role": "administrative coordination, briefing, follow-up and triage",
            "no_binding_authority": True,
            "no_payments_orders_contracts": True,
            "news_source": "existing LUMEN research and evidence; no extra search quota consumed by secretary",
        },
    }

    if mutate_memory:
        seen.update(str(x.get("id") or "") for x in news if x.get("id"))
        state["executive_secretary_memory"] = {
            "last_counts": counts,
            "seen_news_ids": list(seen)[-400:],
            "last_brief_at": snapshot["updated_at"],
        }
        state["executive_secretary"] = snapshot
    return snapshot


def secretary_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    return build_secretary_snapshot(state, mutate_memory=True)
