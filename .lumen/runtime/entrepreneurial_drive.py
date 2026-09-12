from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from autonomy_governor import record_decision


MAX_ACTIVE_MISSIONS = 5
STALE_PENALTY_START = 8
KILL_CANDIDATE_CYCLES = 20


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _ensure_state(state: Dict[str, Any]) -> Dict[str, Any]:
    memory = state.setdefault("entrepreneurial_memory", {})
    memory.setdefault("deal_progress", {})
    memory.setdefault("mission_history", [])
    memory.setdefault("cycles", 0)
    memory.setdefault("last_primary", None)
    memory.setdefault("primary_streak", 0)
    state.setdefault("autonomous_missions", [])
    return memory


def _progress_memory(state: Dict[str, Any], memory: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    progress = memory["deal_progress"]
    live_ids = set()
    tick = int(state.get("ticks") or 0)

    for deal in state.get("deals", []):
        deal_id = str(deal.get("id") or "")
        if not deal_id:
            continue
        live_ids.add(deal_id)
        stage = str(deal.get("stage") or "descubrimiento")
        expected_value = _f(deal.get("expected_value"))
        company_profit = _f(deal.get("company_profit"))
        rec = progress.setdefault(deal_id, {
            "stage": stage,
            "stagnant_cycles": 0,
            "last_progress_tick": tick,
            "best_expected_value": expected_value,
            "best_company_profit": company_profit,
        })
        if rec.get("stage") != stage:
            rec["stage"] = stage
            rec["stagnant_cycles"] = 0
            rec["last_progress_tick"] = tick
        else:
            rec["stagnant_cycles"] = int(rec.get("stagnant_cycles") or 0) + 1
        rec["best_expected_value"] = max(_f(rec.get("best_expected_value")), expected_value)
        rec["best_company_profit"] = max(_f(rec.get("best_company_profit")), company_profit)
        rec["updated_at"] = utcnow()

    # Keep a bounded amount of historical memory without losing recently disappeared deals.
    if len(progress) > 500:
        ordered = sorted(progress.items(), key=lambda kv: int(kv[1].get("last_progress_tick") or 0), reverse=True)
        memory["deal_progress"] = dict(ordered[:500])
        progress = memory["deal_progress"]
    return progress


def _primary_from_executive(state: Dict[str, Any]) -> Dict[str, Any]:
    executive = state.get("executive_plan", {}) or {}
    primary = executive.get("primary", {}) or {}
    code = str(primary.get("code") or "expand_market")
    mapping = {
        "supplier_gap": ("build_supply", "supplier", "Construir oferta verificable con proveedores sólidos"),
        "supplier_for_demand": ("build_supply_for_demand", "supplier", "Cubrir demanda ya detectada con proveedores verificables"),
        "buyer_gap": ("build_demand", "buyer", "Encontrar compradores con encaje para la oferta verificada"),
        "demand_gap": ("prove_demand", "buyer", "Convertir compradores plausibles en demanda respaldada por evidencia"),
        "requirement_gap": ("confirm_requirement", "buyer", "Transformar señales de mercado en requerimientos concretos"),
        "contact_gap": ("unlock_contacts", "balanced", "Conseguir canales corporativos verificables para avanzar conversaciones"),
        "margin_gap": ("protect_margin", "balanced", "Mejorar la economía de negocios por debajo del objetivo"),
        "approval_gap": ("package_approval", "balanced", "Preparar decisiones de cierre para autorización humana"),
        "expand_market": ("expand_market", "balanced", "Abrir nuevas categorías y cuentas con potencial económico"),
    }
    action, research_side, fallback_objective = mapping.get(code, mapping["expand_market"])
    return {
        "id": f"MISSION-{code.upper()}",
        "code": code,
        "action": action,
        "research_side": research_side,
        "objective": str(primary.get("objective") or fallback_objective),
        "reason": str(primary.get("reason") or "No hay un cuello de botella crítico; expandir con disciplina."),
        "priority": int(primary.get("priority") or 70),
        "autonomous": bool(primary.get("autonomous", True)),
        "source": "executive_plan",
    }


def _deal_priority(deal: Dict[str, Any], progress: Dict[str, Dict[str, Any]], target_share: float) -> float:
    deal_id = str(deal.get("id") or "")
    expected = max(0.0, _f(deal.get("expected_value")))
    close_prob = max(0.0, min(1.0, _f(deal.get("close_prob"))))
    profit = max(0.0, _f(deal.get("company_profit")))
    share = max(0.0, _f(deal.get("company_share_pct")))
    economics_bonus = min(35.0, profit / 250.0)
    probability_bonus = close_prob * 30.0
    value_bonus = min(45.0, expected / 1000.0)
    margin_bonus = min(20.0, share / max(1.0, target_share) * 20.0)
    stale = int(progress.get(deal_id, {}).get("stagnant_cycles") or 0)
    stale_penalty = max(0, stale - STALE_PENALTY_START) * 2.5
    stage = str(deal.get("stage") or "")
    stage_bonus = {
        "descubrimiento": 0,
        "contacto preparado": 4,
        "calificado": 8,
        "esperando oferta": 10,
        "propuesta": 14,
        "propuesta preparada": 18,
        "negociación": 24,
        "renegociación": 16,
        "listo para cerrar": 30,
        "autorizado para cierre": 32,
    }.get(stage, 0)
    return round(max(0.0, value_bonus + probability_bonus + economics_bonus + margin_bonus + stage_bonus - stale_penalty), 2)


def _deal_missions(state: Dict[str, Any], progress: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    target_share = _f(state.get("policies", {}).get("target_company_share_pct"), 12.0)
    missions: List[Dict[str, Any]] = []
    for deal in state.get("deals", []):
        if deal.get("stage") in {"cerrado", "cerrado (simulación)", "descartado", "cancelado"}:
            continue
        deal_id = str(deal.get("id") or "")
        if not deal_id:
            continue
        stage = str(deal.get("stage") or "descubrimiento")
        stagnant = int(progress.get(deal_id, {}).get("stagnant_cycles") or 0)
        score = _deal_priority(deal, progress, target_share)
        next_action = str(deal.get("next_action") or "Avanzar la oportunidad comercial")
        mission = {
            "id": f"MISSION-{deal_id}",
            "code": "advance_deal",
            "deal_id": deal_id,
            "action": "advance_deal",
            "research_side": "balanced",
            "objective": f"Avanzar {deal_id}: {deal.get('buyer','comprador')} ↔ {deal.get('supplier','proveedor')}",
            "reason": next_action,
            "priority": score,
            "expected_value_usd": round(_f(deal.get("expected_value")), 2),
            "company_profit_usd": round(_f(deal.get("company_profit")), 2),
            "stage": stage,
            "stagnant_cycles": stagnant,
            "kill_candidate": stagnant >= KILL_CANDIDATE_CYCLES and stage not in {"listo para cerrar", "autorizado para cierre"},
            "autonomous": stage not in {"listo para cerrar", "autorizado para cierre"},
            "source": "deal_portfolio",
        }
        missions.append(mission)
    return sorted(missions, key=lambda x: _f(x.get("priority")), reverse=True)


def _mission_history(memory: Dict[str, Any], primary: Dict[str, Any], tick: int) -> None:
    code = primary.get("code")
    if memory.get("last_primary") == code:
        memory["primary_streak"] = int(memory.get("primary_streak") or 0) + 1
    else:
        memory["last_primary"] = code
        memory["primary_streak"] = 1
        history = memory["mission_history"]
        history.append({
            "ts": utcnow(),
            "tick": tick,
            "code": code,
            "objective": primary.get("objective"),
            "reason": primary.get("reason"),
        })
        if len(history) > 250:
            del history[:-250]


def drive_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    memory = _ensure_state(state)
    memory["cycles"] = int(memory.get("cycles") or 0) + 1
    tick = int(state.get("ticks") or 0)
    progress = _progress_memory(state, memory)
    primary = _primary_from_executive(state)
    deal_missions = _deal_missions(state, progress)

    # 70/30 operating doctrine: exploit the best current deals while preserving a market-building mission.
    missions: List[Dict[str, Any]] = [primary]
    for mission in deal_missions:
        if len(missions) >= MAX_ACTIVE_MISSIONS:
            break
        if mission["id"] not in {m["id"] for m in missions}:
            missions.append(mission)

    total_expected = sum(_f(x.get("expected_value_usd")) for x in missions)
    total_profit = sum(_f(x.get("company_profit_usd")) for x in missions)
    stale_deals = sum(1 for x in deal_missions if int(x.get("stagnant_cycles") or 0) >= STALE_PENALTY_START)
    kill_candidates = sum(1 for x in deal_missions if x.get("kill_candidate"))

    _mission_history(memory, primary, tick)
    state["autonomous_missions"] = missions
    report = {
        "updated_at": utcnow(),
        "mode": "autonomous_b2b_entrepreneur",
        "primary": primary,
        "missions": missions,
        "active_missions": len(missions),
        "portfolio_expected_value_usd": round(total_expected, 2),
        "portfolio_company_profit_usd": round(total_profit, 2),
        "stale_deals": stale_deals,
        "kill_candidates": kill_candidates,
        "primary_streak_cycles": int(memory.get("primary_streak") or 0),
        "operating_doctrine": {
            "exploit_pct": 70,
            "explore_pct": 30,
            "rule": "perseguir valor esperado y margen sin sacrificar evidencia, reputación ni control humano de compromisos vinculantes",
            "stale_penalty_start_cycles": STALE_PENALTY_START,
            "kill_candidate_cycles": KILL_CANDIDATE_CYCLES,
        },
    }
    state["entrepreneurial_drive"] = report

    record_decision(
        state,
        engine="Entrepreneurial Drive",
        object_type="company",
        object_id="LUMEN",
        decision=str(primary.get("action")),
        reason=str(primary.get("reason")),
        action="score_opportunity",
        confidence=0.92,
        evidence_refs=[],
    )
    return report
