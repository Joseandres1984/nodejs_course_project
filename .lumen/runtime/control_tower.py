from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Any, Dict, List


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _money(value: Any, currency: str = "USD") -> str:
    try:
        return f"{currency} {float(value):,.0f}"
    except (TypeError, ValueError):
        return f"{currency} 0"


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def _latest_activity(state: Dict[str, Any], limit: int = 12) -> List[Dict[str, Any]]:
    return list(state.get("activity", []) or [])[:limit]


def _human_decisions(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    decisions: List[Dict[str, Any]] = []
    deals = {str(x.get("id")): x for x in state.get("deals", []) if x.get("id")}

    for brief in state.get("approval_briefs", []) or []:
        if brief.get("status") != "human_decision_required":
            continue
        deal_id = str(brief.get("deal_id") or "")
        missing = list(brief.get("preclose_missing") or [])
        decisions.append({
            "key": f"approval:{brief.get('approval_id')}",
            "kind": "binding_approval",
            "title": f"Decidir cierre de {deal_id or 'operación'}",
            "reason": (
                f"Beneficio estimado {_money(brief.get('company_profit'))}; margen {_f(brief.get('company_share_pct')):.1f}%."
                + (f" Antes faltan controles: {', '.join(str(x) for x in missing[:5])}." if missing else " Controles previos sin faltantes reportados.")
            ),
            "deal_id": deal_id,
            "priority": 100 if not missing else 92,
            "ready": not bool(missing),
        })

    for task in state.get("operating_action_queue", []) or []:
        if task.get("autonomous", True):
            continue
        key = f"task:{task.get('key') or task.get('object_id')}"
        if any(x["key"] == key for x in decisions):
            continue
        decisions.append({
            "key": key,
            "kind": str(task.get("kind") or "human_decision"),
            "title": str(task.get("title") or "Decisión humana requerida"),
            "reason": str(task.get("reason") or "La política de autonomía requiere intervención humana."),
            "deal_id": task.get("object_id") if task.get("object_type") == "deal" else None,
            "priority": _f(task.get("priority_score"), 80),
            "ready": False,
        })

    # If a deal is very close to execution but has high-risk preclose gaps, surface it even if no approval brief exists yet.
    for deal_id, deal in deals.items():
        missing = list(deal.get("preclose_missing") or [])
        if not missing:
            continue
        stage = str(deal.get("stage") or "")
        if stage not in {"listo para cerrar", "preclose_validation", "autorizado para cierre"}:
            continue
        key = f"preclose:{deal_id}"
        if any(x["key"] == key for x in decisions):
            continue
        decisions.append({
            "key": key,
            "kind": "preclose_control",
            "title": f"Resolver controles de cierre de {deal_id}",
            "reason": "Faltan: " + ", ".join(str(x) for x in missing[:6]),
            "deal_id": deal_id,
            "priority": 94,
            "ready": False,
        })

    by_key: Dict[str, Dict[str, Any]] = {}
    for decision in decisions:
        key = str(decision["key"])
        if key not in by_key or _f(decision.get("priority")) > _f(by_key[key].get("priority")):
            by_key[key] = decision
    return sorted(by_key.values(), key=lambda x: _f(x.get("priority")), reverse=True)[:8]


def build_control_tower(state: Dict[str, Any], db_status: Dict[str, Any]) -> Dict[str, Any]:
    kpis = state.get("business_kpis", {}) or {}
    cfo = state.get("cfo_war_room", {}) or {}
    finance = kpis.get("finance", {}) or cfo.get("financial_snapshot", {}) or {}
    war = kpis.get("war_room", {}) or {}
    coo = state.get("autonomous_coo", {}) or (state.get("connector_telemetry", {}) or {}).get("autonomous_coo", {}) or {}
    revops = state.get("commercial_execution", {}) or {}
    revops_dir = state.get("commercial_execution_directive", {}) or revops.get("directive", {}) or {}
    docs = state.get("document_intelligence", {}) or {}
    knowledge = state.get("enterprise_knowledge", {}) or {}
    strategy = state.get("corporate_strategy", {}) or state.get("strategic_directive", {}) or {}
    brain = state.get("corporate_brain", {}) or {}
    chief = state.get("chief_of_staff", {}) or {}
    queue = list(state.get("operating_action_queue", []) or [])
    decisions = _human_decisions(state)

    money_now = []
    for row in state.get("war_room", {}).get("top_money_opportunities", []) or []:
        money_now.append(row)
    if not money_now:
        money_now = list((kpis.get("war_room", {}) or {}).get("top_money_opportunities", []) or [])
    if not money_now:
        money_now = list(state.get("cfo_war_room", {}).get("top_money_now", []) or [])

    document_registry = list(state.get("document_registry", []) or [])
    ocr_docs = [x for x in document_registry if x.get("extraction_status") == "ocr_required"]
    quote_docs = [x for x in document_registry if x.get("document_type") == "commercial_quote"]

    graph = state.get("enterprise_knowledge_graph", {}) or {}
    nodes = list(graph.get("nodes", []) or [])
    edges = list(graph.get("edges", []) or [])

    top_actions = queue[:8]
    if not top_actions:
        top_actions = list(chief.get("top_actions", []) or [])[:8]

    ops_guard = coo.get("operational_guard", {}) or {}
    health_score = _f(coo.get("health_score"), 0)
    ops_status = str(coo.get("status") or ("healthy" if db_status.get("connected") else "degraded"))
    outbound_allowed = bool(ops_guard.get("outbound_allowed", False))

    realized = (
        finance.get("realized_profit_usd")
        or finance.get("realized_company_profit_usd")
        or 0
    )
    risk_adjusted = (
        finance.get("risk_adjusted_expected_profit_usd")
        or finance.get("risk_adjusted_profit_usd")
        or 0
    )
    expected = finance.get("expected_company_profit_usd") or finance.get("expected_profit_usd") or 0

    primary_money = war.get("primary_money_move") or state.get("war_room", {}).get("primary_money_move") or {}
    primary_action = top_actions[0] if top_actions else {}

    snapshot = {
        "updated_at": utcnow(),
        "company": {
            "status": ops_status,
            "health_score": round(health_score, 1),
            "postgres_connected": bool(db_status.get("connected")),
            "outbound_allowed": outbound_allowed,
            "last_cycle": state.get("last_tick"),
            "cycles": state.get("ticks"),
        },
        "money": {
            "risk_adjusted_expected_profit_usd": round(_f(risk_adjusted), 2),
            "expected_profit_usd": round(_f(expected), 2),
            "realized_profit_usd": round(_f(realized), 2),
            "primary_money_move": primary_money,
            "top_money_now": money_now[:5],
        },
        "execution": {
            "primary_action": primary_action,
            "top_actions": top_actions,
            "revops_active_cases": _i(revops.get("active_cases") or revops_dir.get("active_cases")),
            "revops_primary_status": revops_dir.get("primary_status"),
            "revops_primary_next_action": revops_dir.get("primary_next_action"),
            "messages_created_last_cycle": revops.get("messages_created"),
        },
        "human_inbox": {
            "count": len(decisions),
            "items": decisions,
            "rule": "Solo escalar decisiones vinculantes, financieras o controles de alta autoridad; el resto permanece autónomo.",
        },
        "strategy": {
            "mode": strategy.get("mode") or (brain.get("strategy", {}) or {}).get("mode"),
            "epoch": strategy.get("strategy_epoch") or (brain.get("strategy", {}) or {}).get("epoch"),
            "thesis": strategy.get("thesis") or (brain.get("strategy", {}) or {}).get("thesis"),
            "focus_categories": strategy.get("focus_categories") or (brain.get("strategy", {}) or {}).get("focus_categories") or [],
            "monthly_objectives": (brain.get("objectives", {}) or {}).get("monthly", []),
            "quarterly_objectives": (brain.get("objectives", {}) or {}).get("quarterly", []),
        },
        "documents": {
            "total": len(document_registry),
            "quotes": len(quote_docs),
            "ocr_required": len(ocr_docs),
            "ocr_items": [{"id": x.get("id"), "filename": x.get("filename"), "sender": x.get("sender")} for x in ocr_docs[:6]],
            "last_report": docs,
        },
        "knowledge": {
            "nodes": len(nodes),
            "edges": len(edges),
            "historical_prices": len(state.get("historical_price_memory", []) or []),
            "reuse_candidates": len(state.get("knowledge_reuse_candidates", []) or []),
            "last_report": knowledge,
        },
        "risk": {
            "blockers": list(ops_guard.get("blockers", []) or [])[:8],
            "warnings": list(ops_guard.get("warnings", []) or [])[:8],
            "engine_failures": list((coo.get("engine_health", {}) or {}).get("failed_now", []) or [])[:8],
            "circuits_open": list((coo.get("engine_health", {}) or {}).get("circuits_open", []) or [])[:8],
        },
        "activity": _latest_activity(state),
    }
    state["control_tower"] = snapshot
    return snapshot


CSS = """
:root{color-scheme:dark;--bg:#061018;--panel:#0b1822;--panel2:#0e202c;--line:#1a3a4b;--muted:#88a2b3;--text:#eef7fb;--lime:#d7ff64;--good:#7ce7b3;--warn:#ffd36a;--bad:#ff8c8c;--blue:#80cfff}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 20% -10%,#12314a 0,#061018 35%);color:var(--text);font:14px Inter,ui-sans-serif,system-ui,-apple-system;padding:22px}.wrap{max-width:1480px;margin:auto}.top{display:flex;align-items:flex-end;justify-content:space-between;gap:18px;margin-bottom:16px}.brand{font-size:32px;font-weight:900;letter-spacing:.12em}.tag{color:var(--muted);margin-top:4px}.stamp{font-size:12px;color:var(--muted);text-align:right}.grid{display:grid;gap:10px}.hero{grid-template-columns:repeat(4,1fr)}.two{grid-template-columns:1.25fr .75fr;margin-top:10px}.three{grid-template-columns:1fr 1fr 1fr;margin-top:10px}.card{background:linear-gradient(180deg,#0d1d28,#09151e);border:1px solid var(--line);border-radius:16px;padding:15px;box-shadow:0 12px 32px #0005}.label{text-transform:uppercase;letter-spacing:.12em;font-size:10px;color:var(--muted)}.metric{font-size:28px;font-weight:850;margin-top:6px}.good{color:var(--good)}.warn{color:var(--warn)}.bad{color:var(--bad)}.lime{color:var(--lime)}.blue{color:var(--blue)}h2{font-size:15px;margin:0 0 12px}h3{font-size:13px;margin:14px 0 8px;color:#b8ceda}.decision{padding:11px;border:1px solid #3b3a27;background:#171a12;border-radius:11px;margin:8px 0}.decision.ready{border-color:#365c45;background:#0d1c15}.title{font-weight:800}.reason{color:#b9cbd5;font-size:12px;margin-top:4px;line-height:1.45}.pill{display:inline-block;border:1px solid #345363;border-radius:999px;padding:4px 8px;font-size:11px;color:#b7d0dc;margin:2px 3px 2px 0}.pill.good{border-color:#315d48}.row{display:flex;justify-content:space-between;gap:12px;padding:8px 0;border-bottom:1px solid #17303e}.row:last-child{border-bottom:0}.small{font-size:11px;color:var(--muted)}.action{padding:9px 0;border-bottom:1px solid #17303e}.action:last-child{border-bottom:0}.priority{font-weight:800;color:var(--lime)}.empty{padding:18px;text-align:center;color:var(--good);border:1px dashed #315d48;border-radius:11px}.activity{max-height:330px;overflow:auto}.bar{height:7px;background:#102632;border-radius:99px;overflow:hidden;margin-top:8px}.bar>span{display:block;height:100%;background:linear-gradient(90deg,#5dd7a0,#d7ff64)}a{color:var(--blue);text-decoration:none}.statusline{display:flex;gap:7px;flex-wrap:wrap;margin-top:8px}.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}@media(max-width:1050px){.hero{grid-template-columns:1fr 1fr}.two,.three{grid-template-columns:1fr}}@media(max-width:620px){body{padding:11px}.hero{grid-template-columns:1fr 1fr}.top{align-items:flex-start;flex-direction:column}.brand{font-size:25px}.metric{font-size:22px}.stamp{text-align:left}}
"""


def render_control_tower(snapshot: Dict[str, Any]) -> str:
    company = snapshot["company"]
    money = snapshot["money"]
    execution = snapshot["execution"]
    inbox = snapshot["human_inbox"]
    strategy = snapshot["strategy"]
    docs = snapshot["documents"]
    knowledge = snapshot["knowledge"]
    risk = snapshot["risk"]

    health = _f(company.get("health_score"))
    health_class = "good" if health >= 85 else "warn" if health >= 65 else "bad"
    health_width = max(0, min(100, health))

    decision_html = ""
    if inbox["items"]:
        for item in inbox["items"]:
            ready = " ready" if item.get("ready") else ""
            decision_html += (
                f'<div class="decision{ready}"><div class="title">{_esc(item.get("title"))}</div>'
                f'<div class="reason">{_esc(item.get("reason"))}</div>'
                f'<div class="small" style="margin-top:6px">{_esc(item.get("kind"))}</div></div>'
            )
    else:
        decision_html = '<div class="empty">No tenés decisiones humanas pendientes. LUMEN puede seguir operando dentro de sus límites.</div>'

    actions_html = ""
    for idx, action in enumerate(execution.get("top_actions", [])[:7], 1):
        actions_html += (
            f'<div class="action"><span class="priority">#{idx}</span> <b>{_esc(action.get("title") or action.get("kind"))}</b>'
            f'<div class="reason">{_esc(action.get("reason"))}</div></div>'
        )
    if not actions_html:
        actions_html = '<div class="empty">Sin acciones operativas pendientes.</div>'

    objectives = []
    for obj in list(strategy.get("monthly_objectives", []) or [])[:4]:
        if isinstance(obj, dict):
            objectives.append(str(obj.get("objective") or obj.get("name") or obj.get("metric") or obj))
        else:
            objectives.append(str(obj))
    objective_html = "".join(f'<span class="pill">{_esc(x)}</span>' for x in objectives) or '<span class="small">Sin objetivos mensuales publicados todavía.</span>'

    risk_rows = []
    for label, rows in (("Blocker", risk.get("blockers", [])), ("Warning", risk.get("warnings", [])), ("Engine", risk.get("engine_failures", [])), ("Circuit", risk.get("circuits_open", []))):
        for row in rows[:4]:
            risk_rows.append(f'<div class="row"><span>{_esc(label)}</span><span class="bad">{_esc(row)}</span></div>')
    risk_html = "".join(risk_rows) or '<div class="empty">Sin bloqueos operativos activos.</div>'

    ocr_html = "".join(
        f'<div class="row"><span>{_esc(x.get("filename"))}</span><span class="warn">OCR requerido</span></div>'
        for x in docs.get("ocr_items", [])
    ) or '<div class="small">No hay documentos pendientes de OCR.</div>'

    activity_html = "".join(
        f'<div class="action"><div>{_esc(x.get("msg"))}</div><div class="small mono">{_esc(x.get("ts"))}</div></div>'
        for x in snapshot.get("activity", [])
    ) or '<div class="small">Sin actividad registrada.</div>'

    focus = ", ".join(str(x) for x in (strategy.get("focus_categories") or [])[:4]) or "sin foco exclusivo"
    revops_status = execution.get("revops_primary_status") or "sin caso prioritario"
    revops_next = execution.get("revops_primary_next_action") or "LUMEN seguirá priorizando automáticamente"
    primary_action = execution.get("primary_action") or {}

    return f'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="30"><title>LUMEN Control Tower</title><style>{CSS}</style></head><body><div class="wrap">
    <div class="top"><div><div class="brand">LUMEN · CONTROL TOWER</div><div class="tag">Command Center ejecutivo · operación autónoma B2B</div></div><div class="stamp">Actualizado {_esc(snapshot.get("updated_at"))}<br>Auto-refresh 30 s · <a href="/api/control-tower">JSON</a></div></div>

    <div class="grid hero">
      <div class="card"><div class="label">Salud operacional</div><div class="metric {health_class}">{health:.0f}/100</div><div class="bar"><span style="width:{health_width:.0f}%"></span></div><div class="statusline"><span class="pill">{_esc(company.get("status"))}</span><span class="pill {'good' if company.get('postgres_connected') else 'bad'}">Postgres {'OK' if company.get('postgres_connected') else 'FAIL'}</span><span class="pill {'good' if company.get('outbound_allowed') else ''}">Outbound {'habilitado' if company.get('outbound_allowed') else 'cerrado'}</span></div></div>
      <div class="card"><div class="label">Beneficio esperado · riesgo ajustado</div><div class="metric lime">{_money(money.get("risk_adjusted_expected_profit_usd"))}</div><div class="small">Esperado bruto: {_money(money.get("expected_profit_usd"))}</div></div>
      <div class="card"><div class="label">Beneficio realizado</div><div class="metric good">{_money(money.get("realized_profit_usd"))}</div><div class="small">Solo resultados reales; simulaciones excluidas.</div></div>
      <div class="card"><div class="label">José debe decidir</div><div class="metric {'warn' if inbox.get('count') else 'good'}">{_i(inbox.get("count"))}</div><div class="small">Solo decisiones vinculantes, financieras o de autoridad alta.</div></div>
    </div>

    <div class="grid two">
      <div class="card"><h2>Qué está haciendo LUMEN ahora</h2><div class="label">Acción #1</div><div class="metric" style="font-size:19px">{_esc(primary_action.get("title") or "Sin acción prioritaria")}</div><div class="reason">{_esc(primary_action.get("reason") or "")}</div><h3>Cola ejecutiva</h3>{actions_html}</div>
      <div class="card"><h2>Bandeja de José</h2>{decision_html}</div>
    </div>

    <div class="grid three">
      <div class="card"><h2>RevOps · conversaciones comerciales</h2><div class="row"><span>Casos activos</span><b>{_i(execution.get("revops_active_cases"))}</b></div><div class="row"><span>Estado prioritario</span><b class="blue">{_esc(revops_status)}</b></div><div class="reason" style="margin-top:9px"><b>Próximo movimiento:</b> {_esc(revops_next)}</div></div>
      <div class="card"><h2>Corporate Brain</h2><div class="row"><span>Modo</span><b class="lime">{_esc(strategy.get("mode") or "sin publicar")}</b></div><div class="row"><span>Epoch</span><b>{_esc(strategy.get("epoch") or "—")}</b></div><div class="reason"><b>Foco:</b> {_esc(focus)}</div><h3>Objetivos del mes</h3>{objective_html}</div>
      <div class="card"><h2>Riesgo & Reliability</h2>{risk_html}</div>
    </div>

    <div class="grid three">
      <div class="card"><h2>Document Intelligence</h2><div class="row"><span>Documentos</span><b>{_i(docs.get("total"))}</b></div><div class="row"><span>Cotizaciones detectadas</span><b>{_i(docs.get("quotes"))}</b></div><div class="row"><span>OCR pendiente</span><b class="{'warn' if docs.get('ocr_required') else 'good'}">{_i(docs.get("ocr_required"))}</b></div><h3>Pendientes</h3>{ocr_html}</div>
      <div class="card"><h2>Enterprise Knowledge Graph</h2><div class="row"><span>Nodos de conocimiento</span><b>{_i(knowledge.get("nodes"))}</b></div><div class="row"><span>Relaciones</span><b>{_i(knowledge.get("edges"))}</b></div><div class="row"><span>Precios históricos trazables</span><b>{_i(knowledge.get("historical_prices"))}</b></div><div class="row"><span>Memoria reutilizable</span><b class="blue">{_i(knowledge.get("reuse_candidates"))}</b></div><div class="reason">Los históricos sirven para priorizar investigación; nunca se asumen como precio vigente.</div></div>
      <div class="card"><h2>Actividad reciente</h2><div class="activity">{activity_html}</div></div>
    </div>
    </div></body></html>'''
