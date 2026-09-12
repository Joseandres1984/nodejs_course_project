from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict

from autonomy_governor import record_decision
from mail_connector import connector_status as mail_status
from scout_connector import status as scout_status
from payment_rails import runtime_rails, public_rail

STAGES = ("PRELAUNCH", "CANARY", "LIMITED_LIVE", "GOVERNED_LIVE", "HOLD")
CANARY_CAP = 1
LIMITED_CAP = 2
MAX_GOVERNED_CAP = 3
CANARY_MIN_STABLE_CYCLES = 8
CANARY_MIN_SENT = 3
FULL_MIN_STABLE_CYCLES = 24
FULL_MIN_SENT = 10


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "si", "sí", "on"}


def _memory(state: Dict[str, Any]) -> Dict[str, Any]:
    memory = state.setdefault("go_live_memory", {})
    memory.setdefault("stage", "PRELAUNCH")
    memory.setdefault("cycles", 0)
    memory.setdefault("stable_cycles", 0)
    memory.setdefault("sent_total", 0)
    memory.setdefault("failed_total", 0)
    memory.setdefault("blocked_total", 0)
    memory.setdefault("stage_history", [])
    memory.setdefault("baseline_outbound_cap", max(1, _i((state.get("policies", {}) or {}).get("max_outbound_per_tick"), 3)))
    return memory


def _rails_summary() -> Dict[str, Any]:
    rails = runtime_rails()
    public = [public_rail(x) for x in rails.values()]
    domestic = [x for x in public if x.get("scope") == "domestic" and x.get("verified")]
    international = [x for x in public if str(x.get("scope") or "").startswith("international") and x.get("verified")]
    return {
        "verified_domestic": len(domestic),
        "verified_international": len(international),
        "any_verified": bool(domestic or international),
        "domestic_labels": [x.get("label") for x in domestic],
        "international_labels": [x.get("label") for x in international],
    }


def _infra(state: Dict[str, Any], db_status: Dict[str, Any], live_requested: bool) -> Dict[str, Any]:
    mail = mail_status()
    scout = scout_status()
    rails = _rails_summary()
    quality = state.get("quality_gate_stats", {}) or {}
    ops = state.get("autonomous_coo", {}) or state.get("operations_control", {}) or (state.get("connector_telemetry", {}) or {}).get("autonomous_coo", {}) or {}
    truth = state.get("data_truth_engine", {}) or {}
    blockers = []
    warnings = []

    if not db_status.get("connected"):
        blockers.append("persistencia_postgresql_no_disponible")
    if not scout.get("configured"):
        blockers.append("scout_web_no_configurado")
    if not mail.get("smtp_configured"):
        blockers.append("smtp_no_configurado")
    if not mail.get("imap_configured"):
        blockers.append("imap_no_configurado")
    if not mail.get("disclose_automation"):
        warnings.append("divulgacion_de_asistencia_automatizada_desactivada")

    health = _f(ops.get("health_score"), 100.0)
    failed = len((ops.get("engine_health", {}) or {}).get("failed_now", []) or [])
    circuits = len((ops.get("engine_health", {}) or {}).get("circuits_open", []) or [])
    if failed or circuits or health < 70:
        blockers.append("salud_operativa_insuficiente")

    if _i(truth.get("critical_refresh")) > 0:
        warnings.append("hay_deals_con_evidencia_critica_a_refrescar")
    if not rails.get("any_verified"):
        warnings.append("ningun_medio_de_cobro_verificado_aun")
    if not live_requested:
        warnings.append("salida_real_no_habilitada_en_runtime")

    return {
        "postgres": bool(db_status.get("connected")),
        "scout": bool(scout.get("configured")),
        "smtp": bool(mail.get("smtp_configured")),
        "imap": bool(mail.get("imap_configured")),
        "automation_disclosure": bool(mail.get("disclose_automation")),
        "operations_health_score": health,
        "quality_last_cycle": quality,
        "payment_rails": rails,
        "blockers": blockers,
        "warnings": warnings,
        "acquisition_ready": not blockers,
        "monetization_ready": bool(rails.get("any_verified")),
    }


def _stage_cap(stage: str, baseline: int) -> int:
    if stage == "CANARY":
        return min(CANARY_CAP, baseline)
    if stage == "LIMITED_LIVE":
        return min(LIMITED_CAP, baseline)
    if stage == "GOVERNED_LIVE":
        return min(MAX_GOVERNED_CAP, baseline)
    return 0


def _set_stage(memory: Dict[str, Any], new_stage: str, reason: str) -> None:
    old = str(memory.get("stage") or "PRELAUNCH")
    if new_stage == old:
        return
    memory.setdefault("stage_history", []).append({"ts": utcnow(), "from": old, "to": new_stage, "reason": reason})
    memory["stage_history"] = memory["stage_history"][-80:]
    memory["stage"] = new_stage
    memory["stable_cycles"] = 0


def go_live_tick(state: Dict[str, Any], db_status: Dict[str, Any], live_requested: bool) -> Dict[str, Any]:
    memory = _memory(state)
    infra = _infra(state, db_status, live_requested)
    baseline = max(1, _i(memory.get("baseline_outbound_cap"), 3))
    auto_promote = _truthy(os.getenv("LUMEN_LAUNCH_AUTOPROMOTE", "true"))
    requested_mode = str(os.getenv("LUMEN_LAUNCH_MODE", "canary") or "canary").strip().lower()
    stage = str(memory.get("stage") or "PRELAUNCH")

    if infra["blockers"]:
        _set_stage(memory, "HOLD", "Infraestructura crítica no apta: " + ", ".join(infra["blockers"]))
    elif not live_requested:
        _set_stage(memory, "PRELAUNCH", "La salida real todavía no fue habilitada en runtime.")
    elif stage in {"PRELAUNCH", "HOLD"}:
        _set_stage(memory, "CANARY", "Infraestructura crítica lista y salida real solicitada; iniciar validación canaria.")
    elif auto_promote and requested_mode != "canary":
        if stage == "CANARY" and _i(memory.get("stable_cycles")) >= CANARY_MIN_STABLE_CYCLES and _i(memory.get("sent_total")) >= CANARY_MIN_SENT:
            _set_stage(memory, "LIMITED_LIVE", "Canario acumuló muestra estable suficiente.")
        elif stage == "LIMITED_LIVE" and _i(memory.get("stable_cycles")) >= FULL_MIN_STABLE_CYCLES and _i(memory.get("sent_total")) >= FULL_MIN_SENT:
            _set_stage(memory, "GOVERNED_LIVE", "Operación limitada acumuló estabilidad suficiente para modo gobernado.")

    stage = str(memory.get("stage") or "PRELAUNCH")
    cap = _stage_cap(stage, baseline)
    state.setdefault("policies", {})["max_outbound_per_tick"] = cap if cap > 0 else baseline
    outbound_allowed = bool(live_requested and infra["acquisition_ready"] and stage in {"CANARY", "LIMITED_LIVE", "GOVERNED_LIVE"})

    launch_status = "LISTO PARA ADQUISICIÓN" if infra["acquisition_ready"] else "BLOQUEADO"
    if infra["acquisition_ready"] and not infra["monetization_ready"]:
        launch_status = "ADQUISICIÓN LISTA · COBRO PENDIENTE"
    elif infra["acquisition_ready"] and infra["monetization_ready"]:
        launch_status = "VENTA Y COBRO LISTOS"

    report = {
        "updated_at": utcnow(),
        "stage": stage,
        "launch_status": launch_status,
        "live_outbound_requested": bool(live_requested),
        "outbound_allowed": outbound_allowed,
        "effective_outbound_cap": cap,
        "baseline_outbound_cap": baseline,
        "auto_promote": auto_promote,
        "requested_mode": requested_mode,
        "infra": infra,
        "memory": {
            "cycles": _i(memory.get("cycles")),
            "stable_cycles": _i(memory.get("stable_cycles")),
            "sent_total": _i(memory.get("sent_total")),
            "failed_total": _i(memory.get("failed_total")),
            "blocked_total": _i(memory.get("blocked_total")),
            "stage_history": list(memory.get("stage_history", []))[-12:],
        },
        "promotion_rules": {
            "canary_to_limited": {"stable_cycles": CANARY_MIN_STABLE_CYCLES, "sent_total": CANARY_MIN_SENT},
            "limited_to_governed": {"stable_cycles": FULL_MIN_STABLE_CYCLES, "sent_total": FULL_MIN_SENT},
            "canary_cap": CANARY_CAP,
            "limited_cap": LIMITED_CAP,
            "governed_cap": min(MAX_GOVERNED_CAP, baseline),
        },
        "governance": {
            "launch_rule": "La salida real se habilita por etapas y puede retroceder automáticamente ante fallas.",
            "monetization_rule": "Adquisición puede operar sin un rail de cobro listo; cierre cobrable sigue bloqueado hasta tener instrucciones verificadas.",
            "authority_rule": "El lanzamiento nunca elimina aprobación humana para contratos, pagos, órdenes o términos vinculantes.",
        },
    }
    state["go_live_orchestrator"] = report
    state["go_live_outbound_allowed"] = outbound_allowed
    state["go_live_effective_cap"] = cap

    record_decision(
        state,
        engine="Go-Live Orchestrator",
        object_type="company",
        object_id="LUMEN",
        decision=f"launch_stage:{stage.lower()}",
        reason=f"{launch_status}; outbound={outbound_allowed}; cap={cap}; blockers={', '.join(infra['blockers']) or 'ninguno'}.",
        action="score_opportunity",
        confidence=0.99,
        evidence_refs=[],
        allowed=outbound_allowed or not live_requested,
        requires_approval=False,
    )
    return report


def go_live_post_cycle(state: Dict[str, Any], outbound: Dict[str, Any], coo: Dict[str, Any], quality: Dict[str, Any]) -> Dict[str, Any]:
    memory = _memory(state)
    memory["cycles"] = _i(memory.get("cycles")) + 1
    sent = _i(outbound.get("sent"))
    failed = _i(outbound.get("failed"))
    blocked = _i(outbound.get("blocked")) + _i(quality.get("blocked"))
    reviewed = _i(quality.get("reviewed"))
    incidents = _i((state.get("deal_safeguards_report", {}) or {}).get("open_incidents"))
    health = _f(coo.get("health_score"), 100.0)
    coo_blockers = list((coo.get("operational_guard", {}) or {}).get("blockers", []) or [])
    quality_block_rate = blocked / max(1, reviewed) if reviewed else 0.0

    stable = failed == 0 and health >= 80 and not coo_blockers and incidents == 0 and (reviewed == 0 or quality_block_rate <= 0.50)
    if stable:
        memory["stable_cycles"] = _i(memory.get("stable_cycles")) + 1
    else:
        memory["stable_cycles"] = 0
    memory["sent_total"] = _i(memory.get("sent_total")) + sent
    memory["failed_total"] = _i(memory.get("failed_total")) + failed
    memory["blocked_total"] = _i(memory.get("blocked_total")) + blocked
    memory["last_cycle"] = {
        "ts": utcnow(), "sent": sent, "failed": failed, "blocked": blocked, "reviewed": reviewed,
        "quality_block_rate": round(quality_block_rate, 3), "health_score": health, "incidents": incidents, "stable": stable,
    }

    stage = str(memory.get("stage") or "PRELAUNCH")
    if stage in {"GOVERNED_LIVE", "LIMITED_LIVE"} and (failed >= 2 or health < 70 or coo_blockers):
        _set_stage(memory, "CANARY", "Rollback automático por degradación operativa/salida.")
    elif stage == "CANARY" and (failed >= 2 or health < 60):
        _set_stage(memory, "HOLD", "Canario detenido por fallas relevantes.")

    state["go_live_memory"] = memory
    report = state.get("go_live_orchestrator", {}) or {}
    report["post_cycle"] = dict(memory.get("last_cycle") or {})
    report["stage"] = memory.get("stage")
    report["memory"] = {
        "cycles": memory.get("cycles"), "stable_cycles": memory.get("stable_cycles"), "sent_total": memory.get("sent_total"),
        "failed_total": memory.get("failed_total"), "blocked_total": memory.get("blocked_total"), "stage_history": list(memory.get("stage_history", []))[-12:],
    }
    state["go_live_orchestrator"] = report
    return report
