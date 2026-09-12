from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from autonomy_governor import record_decision

MIN_ENGINE_SAMPLE = 5
MAX_OUTCOMES = 500


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _deal_index(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(x.get("id")): x for x in state.get("deals", []) or [] if x.get("id")}


def _transaction_deals(state: Dict[str, Any]) -> set[str]:
    good = {"closed", "paid", "settled", "completed", "delivered", "invoiced"}
    return {
        str(x.get("deal_id")) for x in state.get("transactions", []) or []
        if x.get("deal_id") and str(x.get("status") or "") in good
    }


def _terminal_negative(stage: Any) -> bool:
    value = str(stage or "").strip().lower()
    return value in {"lost", "rejected", "cancelled", "canceled", "parked", "archivado", "descartado", "no_go", "closed_lost"}


def _resolve_decision(state: Dict[str, Any], entry: Dict[str, Any], deals: Dict[str, Dict[str, Any]], tx_deals: set[str]) -> Tuple[bool, int | None, str]:
    object_type = str(entry.get("object_type") or "")
    object_id = str(entry.get("object_id") or "")
    decision = str(entry.get("decision") or "")
    if object_type == "deal":
        deal = deals.get(object_id, {})
        if object_id in tx_deals:
            return True, 1, "real_transaction_observed"
        if deal and _terminal_negative(deal.get("stage")):
            return True, 0, "deal_terminal_negative"
        if decision.startswith("truth:"):
            klass = str(deal.get("data_truth_class") or "")
            if klass:
                positive = int(("critical_refresh" not in decision and klass in {"CURRENT", "PARTIAL"}) or ("critical_refresh" in decision and klass == "CRITICAL_REFRESH"))
                return True, positive, "truth_state_observed"
        return False, None, "deal_not_resolved"
    if object_type == "transaction":
        txn = next((x for x in state.get("transactions", []) or [] if str(x.get("id") or "") == object_id), {})
        status = str(txn.get("status") or "")
        if status in {"paid", "settled", "completed", "closed", "delivered", "invoiced"}:
            return True, 1, "transaction_positive"
        if status in {"refunded", "cancelled", "canceled", "disputed", "failed"}:
            return True, 0, "transaction_negative"
        return False, None, "transaction_open"
    if object_type == "venture":
        venture = next((x for x in (state.get("venture_builder", {}) or {}).get("ventures", []) or [] if str(x.get("id") or "") == object_id), {})
        stage = str(venture.get("stage") or "")
        if _f(venture.get("realized_profit_usd")) > 0 or stage == "SCALE_CANDIDATE":
            return True, 1, "venture_positive"
        if stage in {"KILL", "KILL_CANDIDATE", "PAUSE", "PAUSE_CANDIDATE"}:
            return True, 0, "venture_negative"
        return False, None, "venture_open"
    return False, None, "unsupported_object_type"


def _bucket(conf: float) -> str:
    lower = int(max(0, min(9, conf * 10))) * 10
    upper = min(100, lower + 10)
    return f"{lower:02d}-{upper:02d}"


def decision_calibration_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    deals = _deal_index(state)
    tx_deals = _transaction_deals(state)
    resolved: List[Dict[str, Any]] = []
    for entry in (state.get("decision_ledger", []) or [])[-MAX_OUTCOMES:]:
        confidence = entry.get("confidence")
        if confidence in (None, ""):
            continue
        conf = max(0.0, min(1.0, _f(confidence)))
        ok, outcome, resolution = _resolve_decision(state, entry, deals, tx_deals)
        if not ok or outcome is None:
            continue
        resolved.append({
            "decision_id": entry.get("id"),
            "engine": str(entry.get("engine") or "Unknown"),
            "decision": entry.get("decision"),
            "confidence": conf,
            "outcome": int(outcome),
            "resolution": resolution,
            "bucket": _bucket(conf),
        })

    engine_rows: List[Dict[str, Any]] = []
    multipliers: Dict[str, float] = {}
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in resolved:
        grouped[row["engine"]].append(row)
    for engine, rows in grouped.items():
        n = len(rows)
        avg_conf = sum(_f(x.get("confidence")) for x in rows) / max(1, n)
        hit = sum(int(x.get("outcome", 0)) for x in rows) / max(1, n)
        brier = sum((_f(x.get("confidence")) - int(x.get("outcome", 0))) ** 2 for x in rows) / max(1, n)
        gap = avg_conf - hit
        if n < MIN_ENGINE_SAMPLE:
            multiplier = 1.0
            status = "INSUFFICIENT_SAMPLE"
        elif gap > 0.20:
            multiplier = 0.72
            status = "OVERCONFIDENT"
        elif gap > 0.10:
            multiplier = 0.85
            status = "SLIGHTLY_OVERCONFIDENT"
        elif gap < -0.18:
            multiplier = 1.05
            status = "UNDERCONFIDENT"
        else:
            multiplier = 1.0
            status = "CALIBRATED"
        multipliers[engine] = multiplier
        engine_rows.append({
            "engine": engine,
            "resolved_decisions": n,
            "average_confidence": round(avg_conf, 3),
            "observed_success_rate": round(hit, 3),
            "calibration_gap": round(gap, 3),
            "brier_score": round(brier, 4),
            "status": status,
            "confidence_multiplier": multiplier,
        })

    buckets: List[Dict[str, Any]] = []
    by_bucket: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in resolved:
        by_bucket[row["bucket"]].append(row)
    for name, rows in sorted(by_bucket.items()):
        avg_conf = sum(_f(x.get("confidence")) for x in rows) / len(rows)
        hit = sum(int(x.get("outcome", 0)) for x in rows) / len(rows)
        buckets.append({"bucket": name, "n": len(rows), "average_confidence": round(avg_conf, 3), "observed_success_rate": round(hit, 3), "gap": round(avg_conf-hit, 3)})

    overall_brier = sum((_f(x.get("confidence")) - int(x.get("outcome", 0))) ** 2 for x in resolved) / len(resolved) if resolved else None
    engine_rows.sort(key=lambda x: (x["status"] in {"OVERCONFIDENT", "SLIGHTLY_OVERCONFIDENT"}, x["resolved_decisions"]), reverse=True)
    report = {
        "updated_at": utcnow(),
        "mode": "continuous_decision_calibration",
        "resolved_decisions": len(resolved),
        "overall_brier_score": round(overall_brier, 4) if overall_brier is not None else None,
        "engine_profiles": engine_rows,
        "confidence_multipliers": multipliers,
        "confidence_buckets": buckets,
        "outcomes": resolved[-120:],
        "governance": {
            "calibration_rule": "Confianza declarada se compara con resultados observados; no se premia seguridad verbal sin precisión histórica.",
            "sample_rule": f"No se modifica confianza de un motor hasta tener al menos {MIN_ENGINE_SAMPLE} decisiones resueltas.",
            "authority_rule": "La calibración ajusta prioridad/confianza, no amplía autoridad contractual o financiera.",
        },
    }
    state["decision_calibration"] = report
    state["engine_confidence_multiplier"] = multipliers

    over = next((x for x in engine_rows if x.get("status") == "OVERCONFIDENT"), None)
    if over:
        record_decision(
            state,
            engine="Decision Calibration Engine",
            object_type="company",
            object_id="LUMEN",
            decision="calibration:reduce_overconfidence",
            reason=f"{over.get('engine')} muestra gap {over.get('calibration_gap')} con n={over.get('resolved_decisions')}; aplicar multiplicador {over.get('confidence_multiplier')} a prioridades futuras.",
            action="score_opportunity",
            confidence=0.96,
            evidence_refs=[],
            allowed=True,
            requires_approval=False,
        )
    return report
