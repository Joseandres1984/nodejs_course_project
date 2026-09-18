from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

import outbound_engine
import service_revenue_runtime


VERSION = "1.0-service-revenue-outbound-bridge"
SERVICE_URL = outbound_engine.PUBLIC_BASE_URL.rstrip("/") + "/services"

_ORIGINAL_ELIGIBLE = outbound_engine._eligible
_ORIGINAL_MESSAGE_TEXT = outbound_engine._message_text
_ORIGINAL_QUEUE_NEW = outbound_engine._queue_new
_ORIGINAL_SERVICE_TICK = service_revenue_runtime.service_revenue_tick


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _service_contexts(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    contexts: Dict[str, Dict[str, Any]] = {}
    for row in state.get("service_sales_pipeline", []) or []:
        if not isinstance(row, dict):
            continue
        if row.get("source") != "verified_account_fit":
            continue
        if not row.get("proactive_attention_active"):
            continue
        if str(row.get("stage") or "") != "outreach_prepared":
            continue
        account_id = str(row.get("account_id") or "").strip()
        email = str(row.get("email") or "").strip().lower()
        service_id = str(row.get("service_id") or "").strip()
        if not account_id or not email or not service_id:
            continue
        contexts[account_id] = {
            "pipeline_id": row.get("id"),
            "service_opportunity_id": row.get("service_opportunity_id"),
            "service_id": service_id,
            "service_name": row.get("service_name"),
            "company_name": row.get("company_name"),
            "email": email,
            "qualification_score": row.get("qualification_score"),
        }
    return contexts


def _eligible_service_first(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    prospects = list(_ORIGINAL_ELIGIBLE(state) or [])
    contexts = _service_contexts(state)
    for prospect in prospects:
        account = prospect.get("account") or {}
        aid = str(account.get("id") or "")
        ctx = contexts.get(aid)
        email = str(prospect.get("email") or "").strip().lower()
        ready = bool(ctx and str(ctx.get("email") or "").lower() == email)
        prospect["service_revenue_ready"] = ready
        if ready:
            prospect["service_revenue_context"] = dict(ctx)
            reasons = list(prospect.get("reasons") or [])
            reasons.insert(0, f"candidato priorizado para {ctx.get('service_name') or ctx.get('service_id')}")
            prospect["reasons"] = reasons[:8]
    prospects.sort(key=lambda x: (
        0 if x.get("service_revenue_ready") else 1,
        -float(x.get("score") or 0.0),
        str((x.get("account") or {}).get("id") or ""),
    ))
    return prospects


def _service_message_text(account: Dict[str, Any], variant: Dict[str, Any], tracking_url: str):
    ctx = account.get("_lumen_service_revenue_context")
    if not isinstance(ctx, dict):
        return _ORIGINAL_MESSAGE_TEXT(account, variant, tracking_url)

    company = outbound_engine._company(account)
    service_id = str(ctx.get("service_id") or "")
    if service_id == "SRV-SOURCING-EXPRESS":
        kind = "service_sourcing_intro"
        subject = f"{company}: búsqueda de proveedores B2B"
        body = (
            f"Hola equipo de {company},\n\n"
            "LUMEN ofrece un servicio de Sourcing Express para empresas que necesitan encontrar y comparar proveedores para una necesidad B2B concreta. "
            "Podemos investigar alternativas, ordenar evidencia disponible y preparar una preselección para acelerar el análisis, sin comprometer ninguna compra.\n\n"
            "Si hoy tienen una búsqueda activa, con una descripción breve del requerimiento alcanza para evaluar si podemos ayudarlos."
        )
    else:
        kind = "service_b2b_prospecting_intro"
        subject = f"{company}: prospección comercial B2B"
        body = (
            f"Hola equipo de {company},\n\n"
            "LUMEN ofrece un servicio de Prospección B2B para proveedores que quieren priorizar empresas objetivo y señales comerciales compatibles con su oferta. "
            "Trabajamos con evidencia pública y canales corporativos verificables; no prometemos ventas ni respuestas que todavía no existan.\n\n"
            "Si están buscando desarrollar nuevos clientes, con indicarnos qué productos o rubros quieren impulsar podemos evaluar un diagnóstico inicial."
        )
    body += f"\n\nAlcance y consulta: {SERVICE_URL}"
    body += "\n\nSi no corresponde contactarlos por este medio, avísennos y no volveremos a escribir."
    return kind, subject[:180], body[:5000]


def _queue_service_first(state: Dict[str, Any], prospects: List[Dict[str, Any]]) -> int:
    contexts = {
        str((p.get("account") or {}).get("id") or ""): dict(p.get("service_revenue_context") or {})
        for p in prospects
        if p.get("service_revenue_ready") and p.get("service_revenue_context")
    }
    before = len(state.setdefault("outbox", []))
    tagged_accounts: List[Dict[str, Any]] = []
    try:
        for prospect in prospects:
            account = prospect.get("account") or {}
            aid = str(account.get("id") or "")
            ctx = contexts.get(aid)
            if ctx:
                account["_lumen_service_revenue_context"] = ctx
                tagged_accounts.append(account)
        queued = int(_ORIGINAL_QUEUE_NEW(state, prospects) or 0)
    finally:
        for account in tagged_accounts:
            account.pop("_lumen_service_revenue_context", None)

    new_rows = list(state.get("outbox", []) or [])[before:]
    service_queued = 0
    seq_index = {str(x.get("id") or ""): x for x in state.get("outbound_sequences", []) or []}
    pipeline_index = {str(x.get("id") or ""): x for x in state.get("service_sales_pipeline", []) or []}
    for msg in new_rows:
        aid = str(msg.get("counterparty_account_id") or "")
        ctx = contexts.get(aid)
        if not ctx:
            continue
        msg.update({
            "service_revenue": True,
            "service_id": ctx.get("service_id"),
            "service_name": ctx.get("service_name"),
            "service_pipeline_id": ctx.get("pipeline_id"),
            "service_opportunity_id": ctx.get("service_opportunity_id"),
            "purpose": "paid_service_revenue_acquisition",
            "tracking_url": SERVICE_URL,
        })
        seq = seq_index.get(str(msg.get("outbound_sequence_id") or ""))
        if isinstance(seq, dict):
            seq.update({
                "service_revenue": True,
                "service_id": ctx.get("service_id"),
                "service_pipeline_id": ctx.get("pipeline_id"),
                "service_opportunity_id": ctx.get("service_opportunity_id"),
                "tracking_url": SERVICE_URL,
            })
        pipeline = pipeline_index.get(str(ctx.get("pipeline_id") or ""))
        if isinstance(pipeline, dict):
            pipeline["outbound_queue_truth"] = "queued_not_sent"
            pipeline["outbound_message_id"] = msg.get("id")
            pipeline["next_action"] = "Esperar aceptación real del proveedor de email; no contar contacto antes de envío aceptado."
        service_queued += 1

    state["service_revenue_outbound_bridge"] = {
        "version": VERSION,
        "status": "active",
        "service_candidates_in_eligible_set": len(contexts),
        "service_messages_queued_this_cycle": service_queued,
        "all_new_messages_queued_this_cycle": queued,
        "same_outbound_daily_cap": outbound_engine.MAX_NEW_PER_DAY,
        "same_outbound_cycle_cap": outbound_engine.MAX_NEW_PER_CYCLE,
        "paid_spend": False,
        "binding_commitment": False,
        "updated_at": _utcnow(),
    }
    return queued


def _sync_service_outbound_audit(state: Dict[str, Any]) -> Dict[str, int]:
    audits = [x for x in state.get("service_outbound_audit", []) or [] if isinstance(x, dict)]
    by_message = {str(x.get("outbox_id") or ""): x for x in audits if x.get("outbox_id")}
    sequences = {str(x.get("id") or ""): x for x in state.get("outbound_sequences", []) or []}
    observed = accepted = replied = 0

    for msg in state.get("outbox", []) or []:
        if not isinstance(msg, dict) or not msg.get("service_revenue"):
            continue
        outbox_id = str(msg.get("id") or "")
        if not outbox_id:
            continue
        observed += 1
        audit = by_message.get(outbox_id)
        if audit is None:
            audit = {"id": "SVA-" + outbox_id, "outbox_id": outbox_id, "created_at": _utcnow()}
            audits.append(audit)
            by_message[outbox_id] = audit

        error = str(msg.get("last_error") or msg.get("error") or "").strip()
        status = str(msg.get("status") or "").lower()
        provider_accepted = status in {"sent", "delivered", "delivery_verified"} and not error
        seq = sequences.get(str(msg.get("outbound_sequence_id") or ""), {})
        reply_received = bool(seq.get("reply_detected"))
        if not reply_received and provider_accepted:
            try:
                reply_received = bool(outbound_engine._reply_after(state, str(msg.get("contact") or "").strip().lower(), msg.get("sent_at")))
            except Exception:
                reply_received = False

        audit.update({
            "pipeline_id": msg.get("service_pipeline_id"),
            "service_opportunity_id": msg.get("service_opportunity_id"),
            "service_id": msg.get("service_id"),
            "provider_accepted": provider_accepted,
            "accepted_at": msg.get("sent_at") if provider_accepted else audit.get("accepted_at"),
            "reply_received": reply_received,
            "reply_at": audit.get("reply_at") or (_utcnow() if reply_received else None),
            "error": error or None,
            "outbox_status": status,
            "updated_at": _utcnow(),
        })
        accepted += int(provider_accepted)
        replied += int(reply_received)

    state["service_outbound_audit"] = audits[-500:]
    return {"observed": observed, "provider_accepted": accepted, "replied": replied}


def _service_tick_with_outbound_truth(state: Dict[str, Any]) -> Dict[str, Any]:
    audit = _sync_service_outbound_audit(state)
    summary = dict(_ORIGINAL_SERVICE_TICK(state) or {})
    bridge = dict(state.get("service_revenue_outbound_bridge", {}) or {})
    bridge["audit"] = audit
    bridge["updated_at"] = _utcnow()
    state["service_revenue_outbound_bridge"] = bridge
    summary["outbound_bridge"] = bridge
    state["service_revenue_runtime"] = summary
    return summary


if not getattr(outbound_engine, "_lumen_service_revenue_priority_installed", False):
    outbound_engine._eligible = _eligible_service_first
    outbound_engine._message_text = _service_message_text
    outbound_engine._queue_new = _queue_service_first
    outbound_engine._lumen_service_revenue_priority_installed = True

if not getattr(service_revenue_runtime, "_lumen_service_outbound_truth_installed", False):
    service_revenue_runtime.service_revenue_tick = _service_tick_with_outbound_truth
    service_revenue_runtime._lumen_service_outbound_truth_installed = True

print({
    "service_revenue_outbound_bridge": {
        "version": VERSION,
        "status": "installed",
        "priority": "paid_service_candidates_first_within_existing_caps",
        "max_new_per_cycle_unchanged": outbound_engine.MAX_NEW_PER_CYCLE,
        "max_new_per_day_unchanged": outbound_engine.MAX_NEW_PER_DAY,
        "paid_spend": False,
        "binding_authority_changed": False,
    }
}, flush=True)
