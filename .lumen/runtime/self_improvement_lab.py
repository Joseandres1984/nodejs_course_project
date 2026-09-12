from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List

from autonomy_governor import record_decision

MAX_PROPOSALS = 10
MAX_HISTORY = 160


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _proposal(code: str, title: str, area: str, reason: str, evidence: Dict[str, Any], metric: str, impact: float, confidence: float, *, autonomous_test: bool, code_change: bool = False) -> Dict[str, Any]:
    return {
        "id": f"IMP-{code}",
        "code": code,
        "title": title,
        "area": area,
        "reason": reason,
        "evidence": evidence,
        "target_metric": metric,
        "impact_score": round(max(0.0, min(100.0, impact)), 2),
        "evidence_confidence": round(max(0.0, min(1.0, confidence)), 3),
        "priority_score": round(max(0.0, min(100.0, impact * 0.68 + confidence * 32.0)), 2),
        "autonomous_test_allowed": bool(autonomous_test and not code_change),
        "code_change_required": bool(code_change),
        "production_deploy_allowed": False,
        "status": "PROPOSED",
        "success_condition": "La métrica objetivo mejora sin deteriorar Safe Close, calidad, incidentes ni beneficio realizado.",
        "failure_condition": "No mejora tras muestra suficiente o empeora riesgo/beneficio; revertir/descartar.",
        "created_at": utcnow(),
    }


def _build_proposals(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    calibration = state.get("decision_calibration", {}) or {}
    truth = state.get("data_truth_engine", {}) or {}
    controller_memory = state.get("business_controller_memory", {}) or {}
    strategy = state.get("strategy_simulator", {}) or {}
    quality = state.get("quality_gate", {}) or state.get("quality", {}) or {}
    negotiation = state.get("negotiation_intelligence", {}) or {}
    portfolio_hist = state.get("portfolio_optimizer_history", []) or []

    overconfident = [x for x in calibration.get("engine_profiles", []) or [] if x.get("status") in {"OVERCONFIDENT", "SLIGHTLY_OVERCONFIDENT"}]
    for row in overconfident[:3]:
        out.append(_proposal(
            f"CAL-{str(row.get('engine') or 'engine').replace(' ','_')[:32]}",
            f"Recalibrar confianza de {row.get('engine')}",
            "calibración",
            f"Confianza promedio {row.get('average_confidence')} vs éxito observado {row.get('observed_success_rate')} con n={row.get('resolved_decisions')}.",
            {"calibration_gap": row.get("calibration_gap"), "brier_score": row.get("brier_score"), "multiplier": row.get("confidence_multiplier")},
            "calibration_gap",
            92 if row.get("status") == "OVERCONFIDENT" else 78,
            min(0.98, 0.55 + int(row.get("resolved_decisions") or 0) / 50.0),
            autonomous_test=True,
        ))

    critical_truth = int(truth.get("critical_refresh") or 0)
    stale = int(truth.get("stale_or_partial") or 0)
    reviewed = int(truth.get("deals_reviewed") or 0)
    if critical_truth > 0 or (reviewed >= 5 and stale / max(1, reviewed) >= 0.35):
        out.append(_proposal(
            "TRUTH-FRESHNESS",
            "Aumentar disciplina de refresco de datos",
            "datos",
            "Una fracción relevante del pipeline usa evidencia vencida, incompleta o con antigüedad desconocida.",
            {"critical_refresh": critical_truth, "stale_or_partial": stale, "deals_reviewed": reviewed, "average_truth_score": truth.get("average_truth_score")},
            "average_truth_score",
            94 if critical_truth else 82,
            0.94 if reviewed >= 5 else 0.70,
            autonomous_test=True,
        ))

    interventions = controller_memory.get("intervention_history", []) or []
    recent_interventions = interventions[-12:]
    negative = [x for x in recent_interventions if x.get("outcome") == "negative"]
    inconclusive = [x for x in recent_interventions if x.get("outcome") == "inconclusive"]
    if len(negative) >= 2:
        modes = Counter(str(x.get("mode") or "") for x in negative)
        mode, count = modes.most_common(1)[0]
        out.append(_proposal(
            f"CTRL-{mode or 'MODE'}",
            f"Revisar intervención {mode or 'del Controller'}",
            "control empresarial",
            "La misma familia de intervención acumuló resultados negativos suficientes para cuestionar su política actual.",
            {"negative_recent": len(negative), "mode_negative_count": count},
            "risk_adjusted_expected_profit_usd",
            88,
            min(0.95, 0.65 + count * 0.08),
            autonomous_test=False,
            code_change=True,
        ))
    elif len(inconclusive) >= 5:
        out.append(_proposal(
            "CTRL-HORIZON",
            "Revisar horizonte de evaluación del Controller",
            "control empresarial",
            "Muchas intervenciones terminan no concluyentes; puede faltar muestra o el horizonte ser demasiado corto.",
            {"inconclusive_recent": len(inconclusive), "sample": len(recent_interventions)},
            "intervention_conclusive_rate",
            70,
            0.76,
            autonomous_test=False,
            code_change=True,
        ))

    active_experiment = strategy.get("active_experiment") or {}
    completed = strategy.get("completed_experiments", []) or []
    negative_exp = [x for x in completed[-12:] if x.get("outcome") == "negative"]
    if len(negative_exp) >= 2:
        out.append(_proposal(
            "STRATEGY-NEGATIVE",
            "Reducir peso de escenarios con evidencia negativa",
            "estrategia",
            "El Gemelo Digital acumula escenarios con resultados negativos; deben perder prioridad futura.",
            {"negative_recent_experiments": len(negative_exp), "active_experiment": active_experiment.get("id")},
            "supported_experiment_rate",
            76,
            0.80,
            autonomous_test=True,
        ))

    blocked_messages = int(quality.get("blocked") or quality.get("blocked_messages") or 0)
    checked_messages = int(quality.get("checked") or quality.get("messages_checked") or 0)
    if checked_messages >= 10 and blocked_messages / max(1, checked_messages) >= 0.25:
        out.append(_proposal(
            "QUALITY-OUTBOUND",
            "Reducir mensajes rechazados antes del Quality Gate",
            "comunicación",
            "Demasiados mensajes llegan al último control con defectos; conviene corregir plantillas/generadores aguas arriba.",
            {"blocked": blocked_messages, "checked": checked_messages, "blocked_rate": round(blocked_messages/max(1,checked_messages),3)},
            "quality_gate_block_rate",
            80,
            0.90,
            autonomous_test=False,
            code_change=True,
        ))

    neg_summary = negotiation.get("summary", {}) or {}
    exhausted = int(neg_summary.get("walk_away") or neg_summary.get("exhausted") or 0)
    if exhausted >= 3:
        out.append(_proposal(
            "NEGOTIATION-ROUNDS",
            "Revisar estrategia de rondas de negociación",
            "negociación",
            "Varias negociaciones agotaron presión autónoma; conviene estudiar si precio/plazo/condiciones están mal secuenciados.",
            {"exhausted_cases": exhausted},
            "successful_concession_rate",
            72,
            0.70,
            autonomous_test=False,
            code_change=True,
        ))

    recent_primary = [str(x.get("primary_kind") or "") for x in portfolio_hist[-12:] if x.get("primary_kind")]
    switches = sum(1 for i in range(1, len(recent_primary)) if recent_primary[i] != recent_primary[i-1])
    if len(recent_primary) >= 8 and switches >= 6:
        out.append(_proposal(
            "PORTFOLIO-THRASH",
            "Reducir oscilación de prioridades económicas",
            "cartera",
            "El Portfolio Optimizer cambia demasiado seguido de prioridad principal; aumentar hysteresis/hold puede proteger ejecución.",
            {"cycles": len(recent_primary), "primary_switches": switches, "sequence": recent_primary},
            "primary_priority_stability",
            84,
            0.88,
            autonomous_test=False,
            code_change=True,
        ))

    if not out:
        out.append(_proposal(
            "BASELINE-LEARN",
            "Seguir acumulando resultados antes de modificar reglas",
            "aprendizaje",
            "No existe todavía evidencia suficiente de una falla sistemática; mantener política actual y ampliar muestra.",
            {"resolved_decisions": calibration.get("resolved_decisions"), "truth_score": truth.get("average_truth_score")},
            "resolved_decisions",
            48,
            0.82,
            autonomous_test=True,
        ))

    out.sort(key=lambda x: (_f(x.get("priority_score")), _f(x.get("evidence_confidence"))), reverse=True)
    return out[:MAX_PROPOSALS]


def _materialize(state: Dict[str, Any], proposals: List[Dict[str, Any]]) -> None:
    queue = list(state.get("operating_action_queue", []) or [])
    by_key = {str(x.get("key")): x for x in queue if x.get("key")}
    for row in proposals[:4]:
        key = f"self_improvement|{row.get('code')}"
        by_key[key] = {
            "key": key,
            "kind": "self_improvement",
            "title": str(row.get("title") or "Mejora interna"),
            "reason": str(row.get("reason") or ""),
            "impact": row.get("impact_score"),
            "urgency": row.get("priority_score"),
            "confidence": row.get("evidence_confidence"),
            "effort": 1.0 if row.get("autonomous_test_allowed") else 2.0,
            "risk": "low" if row.get("autonomous_test_allowed") else "medium",
            "autonomous": bool(row.get("autonomous_test_allowed")),
            "object_type": "company",
            "object_id": "LUMEN",
            "payload": dict(row),
            "priority_score": row.get("priority_score"),
            "created_at": utcnow(),
        }
    state["operating_action_queue"] = sorted(by_key.values(), key=lambda x: _f(x.get("priority_score")), reverse=True)[:120]


def self_improvement_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    proposals = _build_proposals(state)
    _materialize(state, proposals)
    primary = proposals[0] if proposals else None
    report = {
        "updated_at": utcnow(),
        "mode": "evidence_driven_self_improvement_lab",
        "primary_proposal": primary,
        "proposals": proposals,
        "autonomous_tests": sum(1 for x in proposals if x.get("autonomous_test_allowed")),
        "code_change_proposals": sum(1 for x in proposals if x.get("code_change_required")),
        "governance": {
            "self_change_rule": "LUMEN puede diagnosticar, proponer y probar cambios reversibles de baja autoridad; no puede autoeditar ni desplegar código de producción.",
            "evidence_rule": "No se cambia una regla por intuición: debe existir señal observable, métrica objetivo y condición de fracaso/reversión.",
            "safety_rule": "Ningún experimento puede ampliar autoridad financiera/contractual, caps, spam, engaño o acceso a datos no autorizados.",
        },
    }
    state["self_improvement_lab"] = report
    state.setdefault("self_improvement_history", []).append({
        "ts": report["updated_at"],
        "primary_code": (primary or {}).get("code"),
        "priority": (primary or {}).get("priority_score"),
        "proposal_count": len(proposals),
    })
    state["self_improvement_history"] = state["self_improvement_history"][-MAX_HISTORY:]

    if primary:
        record_decision(
            state,
            engine="Self-Improvement Lab",
            object_type="company",
            object_id="LUMEN",
            decision=f"improvement:{str(primary.get('code') or '').lower()}",
            reason=str(primary.get("reason") or primary.get("title") or "Mejora interna"),
            action="score_opportunity",
            confidence=max(0.45, min(0.98, _f(primary.get("evidence_confidence"), 0.7))),
            evidence_refs=[],
            allowed=True,
            requires_approval=bool(primary.get("code_change_required")),
        )
    return report
