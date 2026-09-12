from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from autonomy_governor import record_decision

BASE_REINVEST_PCT = max(0.0, min(50.0, float(os.getenv("LUMEN_GROWTH_REINVEST_BASE_PCT", "10"))))
MAX_REINVEST_PCT = max(BASE_REINVEST_PCT, min(50.0, float(os.getenv("LUMEN_GROWTH_REINVEST_MAX_PCT", "20"))))
MIN_REALIZED_FOR_REINVEST_USD = max(0.0, float(os.getenv("LUMEN_GROWTH_REINVEST_MIN_REALIZED_USD", "500")))
MAX_CANDIDATES = 8


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


def _realized_commissions(state: Dict[str, Any]) -> float:
    # Settlement is the source of truth for actual commission receipts.
    settlement = state.get("commission_settlement", {}) or {}
    return round(max(0.0, _f(settlement.get("received_commissions_usd"))), 2)


def _reserved_growth_spend(state: Dict[str, Any]) -> float:
    # Only explicit approved/executed growth investments reserve the planning envelope.
    total = 0.0
    for row in state.get("growth_investments", []) or []:
        if str(row.get("status") or "").lower() in {"approved", "executed", "committed"}:
            total += max(0.0, _f(row.get("amount_usd")))
    return round(total, 2)


def _reinvestment_rate(state: Dict[str, Any], realized: float) -> tuple[float, List[str]]:
    reasons: List[str] = []
    mode = str((state.get("master_governance", {}) or {}).get("company_mode") or "")
    coo = state.get("autonomous_coo", {}) or {}
    health = _f(coo.get("health_score"), 100.0)
    open_incidents = sum(1 for x in state.get("commercial_incidents", []) or [] if str(x.get("status") or "") not in {"resolved", "closed"})
    blocked_counterparties = _i((state.get("counterparty_risk", {}) or {}).get("blocked"))

    if realized < MIN_REALIZED_FOR_REINVEST_USD:
        return 0.0, [f"beneficio realizado inferior al umbral USD {MIN_REALIZED_FOR_REINVEST_USD:,.0f}"]
    if mode in {"RECOVERY", "PROTECT_CASH"}:
        return 0.0, [f"modo constitucional {mode} prioriza preservar caja"]

    rate = BASE_REINVEST_PCT
    reasons.append(f"base de reinversión {BASE_REINVEST_PCT:.1f}%")

    if open_incidents:
        rate = min(rate, 5.0)
        reasons.append("incidentes comerciales abiertos limitan reinversión")
    if blocked_counterparties:
        rate = min(rate, 7.5)
        reasons.append("contrapartes bloqueadas reducen agresividad de crecimiento")
    if health < 70:
        rate = min(rate, 5.0)
        reasons.append("salud operativa baja: primero recuperar confiabilidad")
    elif health < 85:
        rate = min(rate, 10.0)
        reasons.append("salud operativa intermedia: crecimiento prudente")

    if not open_incidents and not blocked_counterparties and health >= 85:
        if realized >= 20000:
            rate = min(MAX_REINVEST_PCT, BASE_REINVEST_PCT + 10.0)
            reasons.append("escala de beneficio realizado habilita mayor inversión de crecimiento")
        elif realized >= 5000:
            rate = min(MAX_REINVEST_PCT, BASE_REINVEST_PCT + 5.0)
            reasons.append("beneficio realizado suficiente para ampliar el fondo de crecimiento")

    return round(max(0.0, min(MAX_REINVEST_PCT, rate)), 1), reasons


def _candidate(code: str, title: str, reason: str, score: float, expected_effect: str, evidence: List[str]) -> Dict[str, Any]:
    return {
        "code": code,
        "title": title,
        "reason": reason,
        "priority_score": round(max(0.0, min(100.0, score)), 1),
        "expected_effect": expected_effect,
        "evidence": evidence[:6],
        "vendor_selected": False,
        "price_verified": False,
        "purchase_authorized": False,
    }


def _investment_candidates(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    kpis = state.get("business_kpis", {}) or {}
    funnel = kpis.get("funnel", {}) or {}
    conversion = kpis.get("conversion", {}) or {}
    docs = state.get("document_registry", []) or []
    ocr_count = sum(1 for x in docs if x.get("extraction_status") == "ocr_required")
    risk = state.get("counterparty_risk", {}) or {}
    coo = state.get("autonomous_coo", {}) or {}
    health = _f(coo.get("health_score"), 100.0)
    scout_budget = state.get("scout_budget", {}) or {}
    used = _i(scout_budget.get("queries_used"))
    daily = _i(scout_budget.get("daily_budget"))
    verified_companies = _i(funnel.get("verified_companies"))
    verified_contacts = _i(funnel.get("verified_corporate_emails"))
    response_pct = _f(conversion.get("sent_to_response_pct"))

    if daily and used >= max(1, int(daily * 0.85)):
        out.append(_candidate(
            "market_data_and_research",
            "Datos de mercado e investigación",
            "El presupuesto de búsqueda se consume casi por completo; una herramienta mejor podría ampliar cobertura o reducir costo por oportunidad.",
            92,
            "más compradores/proveedores verificados por unidad de investigación",
            [f"scout_budget:{used}/{daily}"],
        ))
    elif verified_companies < 8:
        out.append(_candidate(
            "market_data_and_research",
            "Datos de mercado e investigación",
            "La base de empresas verificadas todavía es pequeña; priorizar herramientas que mejoren descubrimiento y validación.",
            82,
            "aumentar densidad de pipeline verificable",
            [f"verified_companies:{verified_companies}"],
        ))

    if verified_companies > 0 and verified_contacts / max(1, verified_companies) < 0.55:
        out.append(_candidate(
            "corporate_contact_data",
            "Datos corporativos y enriquecimiento de contactos",
            "Menos del 55% de las empresas verificadas tiene email corporativo verificado.",
            91,
            "mejorar contactabilidad sin inferir correos personales",
            [f"verified_contacts:{verified_contacts}", f"verified_companies:{verified_companies}"],
        ))

    if _i(funnel.get("outbound_sent")) >= 5 and response_pct < 20:
        out.append(_candidate(
            "crm_and_communication",
            "CRM y automatización de comunicación",
            "Existe volumen de salida pero la respuesta observada es baja; investigar herramientas que mejoren seguimiento, trazabilidad y entregabilidad.",
            84,
            "aumentar respuestas y reducir seguimiento manual",
            [f"sent_to_response_pct:{response_pct}"],
        ))

    if ocr_count:
        out.append(_candidate(
            "document_ai_ocr",
            "OCR e inteligencia documental",
            f"Hay {ocr_count} documentos que no pueden procesarse sin OCR.",
            min(96, 75 + ocr_count * 4),
            "reducir documentos bloqueados y acelerar cotizaciones/requisitos",
            [f"ocr_required:{ocr_count}"],
        ))

    enhanced = _i(risk.get("enhanced_review"))
    blocked = _i(risk.get("blocked"))
    if enhanced or blocked:
        out.append(_candidate(
            "compliance_and_counterparty_data",
            "Riesgo, compliance y datos de contrapartes",
            "El motor de riesgo tiene contrapartes en revisión reforzada o bloqueadas; mejores fuentes pueden reducir incertidumbre antes de operar.",
            min(98, 80 + enhanced * 3 + blocked * 6),
            "mejorar verificación y evitar operaciones con exposición innecesaria",
            [f"enhanced_review:{enhanced}", f"blocked:{blocked}"],
        ))

    if health < 90:
        out.append(_candidate(
            "infrastructure_and_observability",
            "Infraestructura y observabilidad",
            f"La salud operativa reportada es {health:.0f}/100.",
            min(95, 75 + (90 - health)),
            "elevar disponibilidad y reducir ciclos fallidos",
            [f"health_score:{health}"],
        ))

    simulator = state.get("strategy_simulator", {}) or {}
    recommended = simulator.get("recommended_scenario", {}) or {}
    evidence_strength = _f(recommended.get("evidence_strength"))
    if simulator and evidence_strength < 0.55:
        out.append(_candidate(
            "analytics_and_experimentation",
            "Analítica y experimentación",
            "El Gemelo Digital todavía tiene fuerza de evidencia limitada; mejorar medición puede acelerar aprendizaje sin aumentar exposición.",
            76,
            "mejorar decisiones basadas en conversión y beneficio real",
            [f"digital_twin_evidence:{evidence_strength:.2f}"],
        ))

    if not out:
        out.append(_candidate(
            "automation_integrations",
            "Automatización e integraciones",
            "No existe hoy un cuello de botella crítico; mantener exploración de herramientas que reduzcan costo operativo por deal.",
            62,
            "reducir trabajo repetitivo y acelerar el ciclo comercial",
            ["no_critical_tool_bottleneck_observed"],
        ))

    by_code: Dict[str, Dict[str, Any]] = {}
    for row in out:
        old = by_code.get(row["code"])
        if old is None or row["priority_score"] > old["priority_score"]:
            by_code[row["code"]] = row
    return sorted(by_code.values(), key=lambda x: _f(x.get("priority_score")), reverse=True)[:MAX_CANDIDATES]


def _materialize_investment_task(state: Dict[str, Any], envelope: float, candidate: Dict[str, Any]) -> None:
    if envelope < 100 or _f(candidate.get("priority_score")) < 75:
        return
    suggested = round(min(envelope, max(50.0, envelope * 0.50)), 2)
    task = {
        "key": f"growth_treasury|{candidate.get('code')}",
        "kind": "growth_investment",
        "title": f"Evaluar inversión de crecimiento: {candidate.get('title')}",
        "reason": f"Sobre de reinversión planificado USD {envelope:,.2f}. {candidate.get('reason')}",
        "impact": min(98.0, 70.0 + _f(candidate.get("priority_score")) * 0.28),
        "urgency": min(94.0, 60.0 + _f(candidate.get("priority_score")) * 0.30),
        "confidence": 0.72,
        "effort": 1.0,
        "risk": "medium",
        "autonomous": False,
        "object_type": "growth_investment",
        "object_id": str(candidate.get("code") or "tooling"),
        "payload": {
            "planning_envelope_usd": envelope,
            "suggested_max_spend_usd": suggested,
            "candidate": candidate,
            "purchase_authorized": False,
        },
        "priority_score": min(94.0, _f(candidate.get("priority_score"))),
        "created_at": utcnow(),
    }
    queue = list(state.get("operating_action_queue", []) or [])
    by_key = {str(x.get("key")): x for x in queue if x.get("key")}
    by_key[task["key"]] = task
    state["operating_action_queue"] = sorted(by_key.values(), key=lambda x: _f(x.get("priority_score")), reverse=True)[:120]


def growth_treasury_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    realized = _realized_commissions(state)
    reserved = _reserved_growth_spend(state)
    reinvest_pct, rate_reasons = _reinvestment_rate(state, realized)
    gross_envelope = round(realized * reinvest_pct / 100.0, 2)
    available_envelope = round(max(0.0, gross_envelope - reserved), 2)
    candidates = _investment_candidates(state)
    primary = candidates[0] if candidates else None

    if primary:
        _materialize_investment_task(state, available_envelope, primary)

    report = {
        "updated_at": utcnow(),
        "mode": "autonomous_growth_treasury_planning",
        "realized_commissions_usd": realized,
        "reinvestment_rate_pct": reinvest_pct,
        "gross_reinvestment_envelope_usd": gross_envelope,
        "reserved_growth_spend_usd": reserved,
        "available_reinvestment_envelope_usd": available_envelope,
        "protected_not_allocated_usd": round(max(0.0, realized - gross_envelope), 2),
        "rate_reasons": rate_reasons,
        "investment_candidates": candidates,
        "primary_candidate": primary,
        "policy": {
            "base_pct": BASE_REINVEST_PCT,
            "max_pct": MAX_REINVEST_PCT,
            "minimum_realized_before_reinvestment_usd": MIN_REALIZED_FOR_REINVEST_USD,
        },
        "governance": {
            "cash_truth_rule": "El sobre se calcula únicamente sobre comisiones efectivamente recibidas según Commission Settlement; no sobre pipeline, propuestas ni facturas pendientes.",
            "planning_rule": "El sobre es una capacidad de planificación, no una afirmación de saldo bancario libre ni una transferencia de fondos.",
            "investment_rule": "LUMEN puede detectar el cuello de botella, investigar opciones y recomendar presupuesto; cualquier suscripción, compra, transferencia o compromiso financiero requiere aprobación humana explícita.",
            "vendor_rule": "No se asigna proveedor ni precio de software sin evidencia actual y trazable.",
        },
    }
    state["growth_treasury"] = report
    state["growth_investment_candidates"] = candidates

    if primary:
        record_decision(
            state,
            engine="Growth Treasury",
            object_type="company",
            object_id="LUMEN",
            decision="allocate_growth_planning_envelope",
            reason=f"Comisiones realizadas USD {realized:,.2f}; reinversión planificada {reinvest_pct:.1f}% = USD {available_envelope:,.2f}; prioridad: {primary.get('title')}.",
            action="score_opportunity",
            confidence=0.82 if realized >= MIN_REALIZED_FOR_REINVEST_USD else 0.68,
            evidence_refs=list(primary.get("evidence") or []),
            allowed=True,
            requires_approval=available_envelope > 0,
        )
    return report
