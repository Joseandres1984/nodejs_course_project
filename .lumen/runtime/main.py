from fastapi import Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from app import app, auth, load_state, save_state, DB_STATUS, STATE, ensure_commerce_state
from commerce import approve_and_close
from control_tower import build_control_tower, render_control_tower
from dashboard_spanish import spanishize_dashboard
from executive_alerts import executive_alert_tick, mark_alerts_seen, reject_approval
from approval_cockpit import build_cockpit, inject_cockpit
from revenue_factory_panel import inject_revenue_factory
from master_command_panel import inject_master_panel
from strategy_simulator_panel import inject_strategy_simulator
from executive_management_panel import inject_executive_management
from business_control_panel import inject_business_control
from negotiation_intelligence_panel import inject_negotiation_intelligence
from order_to_cash_panel import inject_order_to_cash
from payment_rails_panel import inject_payment_rails
from risk_red_team_panel import inject_risk_red_team
from treasury_panel import inject_treasury
from venture_builder_panel import inject_venture_builder
from deal_room import build_deal_room
from deal_room_panel import inject_deal_room_index, render_deal_room
from supplier_network_panel import inject_supplier_network, inject_supplier_squad_detail
from deal_safeguards_panel import inject_safeguards, inject_deal_safeguards


@app.get("/health/persistence")
def persistence_health():
    loaded = load_state()
    if not DB_STATUS.get("connected"):
        raise HTTPException(status_code=503, detail={"postgres": DB_STATUS})
    return {"ok": True, "postgres": DB_STATUS, "state_loaded": loaded}


def _load_control_state() -> None:
    loaded = load_state()
    if not loaded and DB_STATUS.get("configured") and not DB_STATUS.get("connected"):
        raise HTTPException(status_code=503, detail={"status": "control_tower_unavailable", "postgres": DB_STATUS})
    ensure_commerce_state(STATE)


def _real_deal(deal_id: str):
    deal = next((x for x in STATE.get("deals", []) if str(x.get("id")) == str(deal_id)), None)
    if not deal or deal.get("source") == "demo" or str(deal.get("stage") or "") in {"cerrado (simulación)", "closed_simulated"}:
        raise HTTPException(status_code=404, detail="Deal Room inexistente o no corresponde a un deal real")
    return deal


def _venture_for_id(venture_id: str):
    if not venture_id:
        return {}
    return next((x for x in (STATE.get("venture_builder", {}) or {}).get("ventures", []) if str(x.get("id")) == str(venture_id)), {})


def _risk_for_account(account_id: str):
    return (STATE.get("counterparty_risk_index", {}) or {}).get(str(account_id or ""), {}) or {}


@app.get("/command")
def command_redirect(_=Depends(auth)):
    return RedirectResponse("/command-center", status_code=307)


@app.get("/command-center", response_class=HTMLResponse)
def command_center(_=Depends(auth)):
    _load_control_state()
    executive_alert_tick(STATE)
    snapshot = build_control_tower(STATE, DB_STATUS)
    cockpit = build_cockpit(STATE)
    base_html = render_control_tower(snapshot)
    html = inject_cockpit(base_html, cockpit)
    html = inject_revenue_factory(html, STATE)
    html = inject_master_panel(html, STATE)
    html = inject_executive_management(html, STATE)
    html = inject_business_control(html, STATE)
    html = inject_negotiation_intelligence(html, STATE)
    html = inject_order_to_cash(html, STATE)
    html = inject_payment_rails(html, STATE)
    html = inject_treasury(html, STATE)
    html = inject_risk_red_team(html, STATE)
    html = inject_venture_builder(html, STATE)
    html = inject_strategy_simulator(html, STATE)
    html = inject_deal_room_index(html, STATE)
    html = inject_supplier_network(html, STATE)
    html = inject_safeguards(html, STATE)
    html = spanishize_dashboard(html)
    mark_alerts_seen(STATE)
    save_state()
    return HTMLResponse(html)


@app.get("/deal-room/{deal_id}", response_class=HTMLResponse)
def deal_room_view(deal_id: str, _=Depends(auth)):
    _load_control_state()
    deal = _real_deal(deal_id)
    room = build_deal_room(STATE, deal)
    html = render_deal_room(room, STATE)
    html = inject_supplier_squad_detail(html, STATE, deal_id)
    html = inject_deal_safeguards(html, STATE, deal_id)
    html = spanishize_dashboard(html)
    return HTMLResponse(html)


@app.get("/api/deal-room/{deal_id}")
def api_deal_room(deal_id: str, _=Depends(auth)):
    _load_control_state()
    deal = _real_deal(deal_id)
    room = build_deal_room(STATE, deal)
    management = next((x for x in (STATE.get("autonomous_management", {}) or {}).get("deal_portfolio", []) if str(x.get("deal_id")) == str(deal_id)), {})
    venture = _venture_for_id(str(deal.get("venture_id") or ""))
    capital = (STATE.get("capital_priority_index", {}) or {}).get(str(deal_id), {})
    negotiation = (STATE.get("negotiation_plan_index", {}) or {}).get(str(deal_id), {})
    post_sale = [x for x in STATE.get("order_to_cash_cases", []) if str(x.get("deal_id") or "") == str(deal_id)]
    settlement = [x for x in STATE.get("commission_settlement_cases", []) if str(x.get("deal_id") or "") == str(deal_id)]
    red_team_findings = [x for x in STATE.get("red_team_findings", []) if str(x.get("object_id") or "") == str(deal_id)]
    return {
        "deal_room": room,
        "management": management,
        "capital_intelligence": capital,
        "negotiation_intelligence": negotiation,
        "post_sale": post_sale,
        "payment_route": (STATE.get("payment_route_index", {}) or {}).get(str(deal_id), {}),
        "payment_rails": STATE.get("payment_rails", {}),
        "commission_settlement": settlement,
        "growth_treasury": STATE.get("growth_treasury", {}),
        "counterparty_risk": {
            "buyer": _risk_for_account(str(deal.get("buyer_account_id") or "")),
            "supplier": _risk_for_account(str(deal.get("supplier_account_id") or "")),
        },
        "red_team": {"hold": bool(deal.get("red_team_hold")), "findings": red_team_findings},
        "venture": venture,
        "venture_id": deal.get("venture_id"),
        "supplier_squad": (STATE.get("supplier_squad_index", {}) or {}).get(str(deal_id), {}),
        "deal_safeguards": (STATE.get("deal_safeguard_index", {}) or {}).get(str(deal_id), {}),
        "commercial_incidents": [x for x in STATE.get("commercial_incidents", []) if str(x.get("deal_id")) == str(deal_id)],
        "company_mode": (STATE.get("master_governance", {}) or {}).get("company_mode"),
        "master_governance": STATE.get("master_governance", {}),
        "business_controller": STATE.get("business_controller", {}),
        "strategy_simulator": STATE.get("strategy_simulator", {}),
        "strategy_experiment_overlay": STATE.get("strategy_experiment_overlay", {}),
        "postgres": DB_STATUS,
    }


@app.get("/api/control-tower")
def api_control_tower(_=Depends(auth)):
    _load_control_state()
    alerts = executive_alert_tick(STATE)
    snapshot = build_control_tower(STATE, DB_STATUS)
    cockpit = build_cockpit(STATE)
    save_state()
    return {
        "control_tower": snapshot,
        "approval_cockpit": cockpit,
        "executive_alerts": alerts,
        "revenue_factory": STATE.get("revenue_factory", {}),
        "operating_constitution": STATE.get("operating_constitution", {}),
        "master_governance": STATE.get("master_governance", {}),
        "constitutional_runtime_caps": STATE.get("constitutional_runtime_caps", {}),
        "strategy_simulator": STATE.get("strategy_simulator", {}),
        "strategy_experiment_overlay": STATE.get("strategy_experiment_overlay", {}),
        "autonomous_management": STATE.get("autonomous_management", {}),
        "executive_management_overlay": STATE.get("executive_management_overlay", {}),
        "management_category_directives": STATE.get("management_category_directives", []),
        "capital_margin_intelligence": STATE.get("capital_margin_intelligence", {}),
        "business_controller": STATE.get("business_controller", {}),
        "business_controller_overlay": STATE.get("business_controller_overlay", {}),
        "negotiation_intelligence": STATE.get("negotiation_intelligence", {}),
        "counterparty_behavior_profiles": STATE.get("counterparty_behavior_profiles", []),
        "negotiation_plans": list((STATE.get("negotiation_plan_index", {}) or {}).values()),
        "order_to_cash": STATE.get("order_to_cash", {}),
        "order_to_cash_cases": STATE.get("order_to_cash_cases", []),
        "payment_rails": STATE.get("payment_rails", {}),
        "payment_routes": list((STATE.get("payment_route_index", {}) or {}).values()),
        "commission_settlement": STATE.get("commission_settlement", {}),
        "commission_settlement_cases": STATE.get("commission_settlement_cases", []),
        "growth_treasury": STATE.get("growth_treasury", {}),
        "growth_investment_candidates": STATE.get("growth_investment_candidates", []),
        "counterparty_risk": STATE.get("counterparty_risk", {}),
        "counterparty_risk_profiles": STATE.get("counterparty_risk_profiles", []),
        "red_team_audit": STATE.get("red_team_audit", {}),
        "red_team_findings": STATE.get("red_team_findings", []),
        "venture_builder": STATE.get("venture_builder", {}),
        "venture_builder_directive": STATE.get("venture_builder_directive", {}),
        "venture_attribution_stats": STATE.get("venture_attribution_stats", {}),
        "supplier_network": STATE.get("supplier_network", {}),
        "supplier_network_profiles": STATE.get("supplier_network_profiles", []),
        "supplier_squads": STATE.get("supplier_squads", []),
        "procurement_orchestrator": STATE.get("procurement_orchestrator", {}),
        "deal_safeguards": STATE.get("deal_safeguards_report", {}),
        "deal_safeguard_cases": STATE.get("deal_safeguard_cases", []),
        "commercial_incidents": STATE.get("commercial_incidents", []),
        "deal_room": STATE.get("deal_room", {}),
        "deal_rooms": STATE.get("deal_rooms", []),
        "postgres": DB_STATUS,
    }


@app.post("/api/executive-alerts/seen")
def api_alerts_seen(_=Depends(auth)):
    _load_control_state()
    changed = mark_alerts_seen(STATE)
    if not save_state():
        raise HTTPException(status_code=503, detail="No se pudo persistir el estado de alertas")
    return {"ok": True, "marked_seen": changed}


@app.post("/api/executive-decision")
def executive_decision(
    approval_id: str = Form(...),
    decision: str = Form(...),
    reason: str = Form("Decisión tomada desde LUMEN Approval Cockpit"),
    _=Depends(auth),
):
    _load_control_state()
    approval = next((x for x in STATE.get("approvals", []) if str(x.get("id")) == str(approval_id)), None)
    if not approval:
        raise HTTPException(status_code=404, detail="Aprobación inexistente")
    if approval.get("status") != "pending":
        raise HTTPException(status_code=409, detail="La aprobación ya fue procesada")

    deal = next((x for x in STATE.get("deals", []) if x.get("id") == approval.get("deal_id")), None)
    action = str(decision or "").strip().lower()

    if action == "approve":
        if approval.get("kind") != "close_deal":
            raise HTTPException(status_code=400, detail="Este tipo de aprobación no admite cierre desde el Cockpit")
        if not deal:
            raise HTTPException(status_code=409, detail="El deal asociado ya no existe")

        safeguards = deal.get("deal_safeguards", {}) or {}
        if not deal.get("deal_safeguards_cleared") or deal.get("legal_review_required") or deal.get("incident_hold"):
            raise HTTPException(
                status_code=409,
                detail={
                    "status": "approval_blocked_by_deal_safeguards",
                    "deal_id": deal.get("id"),
                    "safe_close_score": safeguards.get("safe_close_score"),
                    "critical_gaps": safeguards.get("critical_gaps", []),
                    "legal_review_required": bool(deal.get("legal_review_required")),
                    "incident_hold": bool(deal.get("incident_hold")),
                    "message": "Deal Safeguards detecta exposición pendiente. No se permite aprobar el cierre hasta resolverla.",
                },
            )

        buyer_risk = _risk_for_account(str(deal.get("buyer_account_id") or ""))
        supplier_risk = _risk_for_account(str(deal.get("supplier_account_id") or ""))
        blocked_risks = [x for x in (buyer_risk, supplier_risk) if x.get("risk_tier") == "BLOCKED"]
        if deal.get("red_team_hold") or blocked_risks:
            raise HTTPException(
                status_code=409,
                detail={
                    "status": "approval_blocked_by_risk_or_red_team",
                    "deal_id": deal.get("id"),
                    "red_team_hold": bool(deal.get("red_team_hold")),
                    "blocked_counterparties": [x.get("account_id") for x in blocked_risks],
                    "message": "Riesgo de Contrapartes o Auditor Interno mantiene un bloqueo. Resolverlo antes de aprobar el cierre.",
                },
            )

        missing = list(deal.get("preclose_missing") or [])
        if missing:
            raise HTTPException(
                status_code=409,
                detail={
                    "status": "approval_blocked_by_preclose",
                    "deal_id": deal.get("id"),
                    "missing": missing,
                    "message": "El estado cambió o faltan controles. LUMEN no permite aprobar todavía.",
                },
            )
        try:
            txn = approve_and_close(STATE, approval_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        STATE.setdefault("activity", []).insert(0, {
            "ts": txn.get("created_at"),
            "msg": f"Panel de Aprobaciones: José aprobó internamente {approval_id} para {approval.get('deal_id')}. No se ejecutó compromiso financiero real.",
        })
    elif action == "reject":
        try:
            reject_approval(STATE, approval_id, reason)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        STATE.setdefault("activity", []).insert(0, {
            "ts": approval.get("rejected_at"),
            "msg": f"Panel de Aprobaciones: José rechazó {approval_id}; el caso vuelve a revisión ejecutiva.",
        })
    else:
        raise HTTPException(status_code=400, detail="Decisión inválida; usar approve o reject")

    STATE["activity"] = STATE.get("activity", [])[:100]
    executive_alert_tick(STATE)
    if not save_state():
        raise HTTPException(status_code=503, detail="La decisión se procesó en memoria pero no pudo persistirse; no continuar hasta recuperar PostgreSQL")
    return RedirectResponse("/command-center", status_code=303)
