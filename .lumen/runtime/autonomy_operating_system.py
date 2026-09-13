from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Tuple


VERSION = "1.0-autonomy-operating-system"
STAGES = ("DEMANDA", "COMPRADOR", "REQUISITOS", "PROVEEDORES", "COTIZACION", "OFERTA", "NEGOCIACION", "CIERRE", "COBRO")
STAGE_RANK = {name: idx for idx, name in enumerate(STAGES)}
PUBLIC_CATEGORIES = (
    "materiales eléctricos",
    "instrumentación industrial",
    "válvulas bombas y repuestos industriales",
    "ferretería industrial",
    "mantenimiento mecánico industrial",
    "motores grupos electrógenos y repuestos",
)
MAX_CASES = 120
MAX_EVENTS = 300
MAX_ACTIONS = 8


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clean(value: Any, limit: int = 320) -> str:
    return " ".join(str(value or "").split())[:limit]


def _stable(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(x or "") for x in parts)
    return f"{prefix}-{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:14]}"


def _tokens(value: Any) -> set[str]:
    stop = {"industrial", "industriales", "materiales", "servicio", "servicios", "repuestos", "argentina", "para", "con", "del", "las", "los"}
    return {
        x.lower() for x in re.findall(r"[A-Za-zÁÉÍÓÚáéíóúÑñ0-9]+", str(value or ""))
        if len(x) >= 4 and x.lower() not in stop
    }


def _deadline_value(row: Dict[str, Any]) -> str | None:
    for key in ("deadline", "deadline_at", "offer_deadline", "closing_at", "due_at", "expires_at", "valid_until"):
        value = row.get(key)
        if value:
            return str(value)
    return None


def _days_to_deadline(value: str | None) -> float | None:
    if not value:
        return None
    text = str(value).strip()
    candidates = [text.replace("Z", "+00:00")]
    try:
        dt = datetime.fromisoformat(candidates[0])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (dt.astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds() / 86400.0
    except Exception:
        pass
    match = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", text)
    if match:
        try:
            dt = datetime(int(match.group(3)), int(match.group(2)), int(match.group(1)), tzinfo=timezone.utc)
            return (dt - datetime.now(timezone.utc)).total_seconds() / 86400.0
        except Exception:
            return None
    return None


def _stage_from_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    if any(x in text for x in ("paid", "cobro", "received", "commission_received", "conciliad", "settled")):
        return "COBRO"
    if any(x in text for x in ("close", "cierre", "approval", "aprob", "ready_to_close", "preclose")):
        return "CIERRE"
    if any(x in text for x in ("negoti", "negoci")):
        return "NEGOCIACION"
    if any(x in text for x in ("proposal", "propuesta", "offer_sent", "oferta enviada", "sent_to_buyer")):
        return "OFERTA"
    if any(x in text for x in ("quote", "cotiz", "offer_received")):
        return "COTIZACION"
    if any(x in text for x in ("supplier", "proveedor", "rfq")):
        return "PROVEEDORES"
    if any(x in text for x in ("requirement", "requisito", "pliego", "scope")):
        return "REQUISITOS"
    if any(x in text for x in ("buyer", "comprador", "verified_company", "identity_resolved")):
        return "COMPRADOR"
    return "DEMANDA"


def _max_stage(*values: str) -> str:
    return max((x for x in values if x in STAGE_RANK), key=lambda x: STAGE_RANK[x], default="DEMANDA")


def _evidence_stage(state: Dict[str, Any], source: Dict[str, Any], source_type: str) -> str:
    stage = _stage_from_text(source.get("stage") or source.get("status") or source.get("next_action"))
    source_id = str(source.get("id") or "")
    deal_id = str(source.get("deal_id") or (source_id if source_type == "deal" else ""))
    opportunity_id = str(source.get("opportunity_id") or (source_id if source_type == "opportunity" else ""))

    if any(source.get(k) for k in ("buyer_account_id", "buyer_id", "buyer", "buyer_identity", "buyer_company")):
        stage = _max_stage(stage, "COMPRADOR")
    if any(source.get(k) for k in ("requirement", "requirement_spec", "technical_scope", "pliego_url", "document_id")):
        stage = _max_stage(stage, "REQUISITOS")
    if any(source.get(k) for k in ("supplier_account_id", "supplier_id", "supplier", "supplier_matches")):
        stage = _max_stage(stage, "PROVEEDORES")

    offers = state.get("offers", []) or []
    if any(
        str(x.get("deal_id") or "") == deal_id or str(x.get("opportunity_id") or "") == opportunity_id
        for x in offers if deal_id or opportunity_id
    ):
        stage = _max_stage(stage, "COTIZACION")

    outbox = state.get("outbox", []) or []
    if any(
        (str(x.get("deal_id") or "") == deal_id or str(x.get("opportunity_id") or "") == opportunity_id)
        and str(x.get("status") or "") in {"sent", "delivered", "ready"}
        and str(x.get("kind") or "") not in {"supplier_rfq", "quote_clarification"}
        for x in outbox if deal_id or opportunity_id
    ):
        stage = _max_stage(stage, "OFERTA")

    approvals = state.get("approvals", []) or []
    if any(str(x.get("deal_id") or "") == deal_id and x.get("status") == "pending" for x in approvals if deal_id):
        stage = _max_stage(stage, "CIERRE")

    settlements = state.get("commission_settlement_cases", []) or []
    if any(
        str(x.get("deal_id") or x.get("transaction_id") or "") == deal_id
        and str(x.get("status") or "") in {"RECEIVED", "PARTIAL_RECEIVED", "PAID", "SETTLED"}
        for x in settlements if deal_id
    ):
        stage = "COBRO"
    return stage


def _next_action(stage: str, human_required: bool = False) -> str:
    if human_required:
        return "Presentar a José el paquete de cierre con evidencia, términos y riesgos para decisión final"
    return {
        "DEMANDA": "Resolver identidad del comprador y validar que la necesidad siga abierta",
        "COMPRADOR": "Extraer requisitos, cantidades, plazos, documentación y condiciones del requerimiento",
        "REQUISITOS": "Seleccionar y verificar hasta 3 proveedores aptos para cotizar",
        "PROVEEDORES": "Solicitar cotizaciones comparables a proveedores verificados",
        "COTIZACION": "Normalizar y comparar cotizaciones; calcular economía y alternativa recomendada",
        "OFERTA": "Dar seguimiento a la propuesta y capturar objeciones o señales de compra",
        "NEGOCIACION": "Negociar precio, plazo y pago dentro de límites no vinculantes",
        "CIERRE": "Completar controles de pre-cierre y preparar decisión humana sólo si es vinculante",
        "COBRO": "Conciliar pago/comisión, registrar resultado y alimentar aprendizaje económico",
    }.get(stage, "Validar evidencia y definir la siguiente acción")


def _human_required(state: Dict[str, Any], source: Dict[str, Any], stage: str, source_type: str) -> bool:
    source_id = str(source.get("id") or "")
    deal_id = str(source.get("deal_id") or (source_id if source_type == "deal" else ""))
    if stage != "CIERRE":
        return False
    for approval in state.get("approvals", []) or []:
        if str(approval.get("deal_id") or "") == deal_id and approval.get("status") == "pending":
            return True
    return bool(source.get("binding_action_required") or source.get("human_decision_required"))


def _economic_fields(source: Dict[str, Any]) -> Dict[str, Any]:
    currency = str(source.get("currency") or source.get("quote_currency") or source.get("sale_currency") or "").upper()
    amount = next((source.get(k) for k in ("amount", "sale_price", "expected_value", "estimated_value", "budget", "budget_amount") if source.get(k) not in (None, "")), None)
    profit = next((source.get(k) for k in ("company_profit", "expected_company_profit", "expected_profit", "risk_adjusted_expected_profit") if source.get(k) not in (None, "")), None)
    return {
        "currency": currency or None,
        "amount": _f(amount) if amount not in (None, "") else None,
        "expected_profit": _f(profit) if profit not in (None, "") else None,
    }


def _priority(source: Dict[str, Any], stage: str, economics: Dict[str, Any]) -> float:
    base = max(_f(source.get("score")), _f(source.get("portfolio_priority_score")), 45.0)
    base += STAGE_RANK.get(stage, 0) * 4.5
    days = _days_to_deadline(_deadline_value(source))
    if days is not None:
        if days < 0:
            base -= 30
        elif days <= 2:
            base += 24
        elif days <= 7:
            base += 16
        elif days <= 14:
            base += 8
    amount = economics.get("amount")
    if amount and amount > 0:
        base += min(15.0, max(2.0, math.log10(max(10.0, amount)) * 1.8))
    if economics.get("expected_profit") and economics["expected_profit"] > 0:
        base += 10
    return round(max(0.0, min(100.0, base)), 1)


def _case(state: Dict[str, Any], row: Dict[str, Any], source_type: str) -> Dict[str, Any]:
    source_id = str(row.get("id") or row.get("key") or row.get("url") or _stable("SRC", row.get("title"), row.get("category")))
    stage = _evidence_stage(state, row, source_type)
    human = _human_required(state, row, stage, source_type)
    economics = _economic_fields(row)
    category = _clean(row.get("category") or row.get("need") or row.get("title") or "oportunidad B2B", 160)
    buyer = _clean(row.get("buyer") or row.get("buyer_company") or row.get("company_name") or row.get("buyer_identity"), 180)
    return {
        "id": _stable("CASE", source_type, source_id),
        "source_type": source_type,
        "source_id": source_id,
        "category": category,
        "buyer": buyer or None,
        "title": _clean(row.get("title") or row.get("need") or category, 220),
        "stage": stage,
        "stage_rank": STAGE_RANK.get(stage, 0),
        "next_action": _next_action(stage, human),
        "owner": "José" if human else "LUMEN",
        "human_required": human,
        "deadline": _deadline_value(row),
        "priority": _priority(row, stage, economics),
        "economics": economics,
        "url": row.get("url") or row.get("source_url"),
        "status": row.get("status"),
        "updated_at": utcnow(),
    }


def _canonical_cases(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Tuple[str, Dict[str, Any]]] = []
    rows.extend(("public_demand", x) for x in state.get("unlinked_demand_signals", []) or [])
    rows.extend(("opportunity", x) for x in state.get("market_opportunities", []) or [])
    rows.extend(("deal", x) for x in state.get("deals", []) or [])
    cases = [_case(state, row, kind) for kind, row in rows if isinstance(row, dict)]
    # Deduplicate exact source cases and keep the strongest version.
    by_id: Dict[str, Dict[str, Any]] = {}
    for case in cases:
        old = by_id.get(case["id"])
        if old is None or (case["stage_rank"], case["priority"]) > (old["stage_rank"], old["priority"]):
            by_id[case["id"]] = case
    return sorted(by_id.values(), key=lambda x: (x["priority"], x["stage_rank"]), reverse=True)[:MAX_CASES]


def _category_weights(cases: List[Dict[str, Any]]) -> Dict[str, float]:
    weights: Dict[str, float] = {}
    for category in PUBLIC_CATEGORIES:
        cat_tokens = _tokens(category)
        relevant = [c for c in cases if cat_tokens & _tokens(c.get("category"))]
        if not relevant:
            weights[category] = 1.0
            continue
        progress = sum(c["stage_rank"] for c in relevant) / max(1, len(relevant))
        high_priority = sum(1 for c in relevant if c["priority"] >= 75)
        cash = sum(1 for c in relevant if c["stage"] == "COBRO")
        close = sum(1 for c in relevant if c["stage"] in {"CIERRE", "COBRO"})
        raw = 0.75 + progress * 0.12 + min(0.45, high_priority * 0.08) + close * 0.20 + cash * 0.35
        weights[category] = round(max(0.65, min(2.25, raw)), 2)
    return weights


def _events(state: Dict[str, Any], cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    memory = state.setdefault("autonomy_os_memory", {})
    previous = dict(memory.get("case_stages", {}) or {})
    events = list(state.get("autonomy_event_queue", []) or [])
    known = {str(x.get("key") or "") for x in events}
    created: List[Dict[str, Any]] = []
    current: Dict[str, str] = {}
    for case in cases:
        case_id = str(case["id"])
        stage = str(case["stage"])
        current[case_id] = stage
        old = previous.get(case_id)
        if old == stage:
            continue
        kind = "case_discovered" if old is None else "stage_advanced"
        key = f"{kind}|{case_id}|{old or 'NEW'}|{stage}"
        if key in known:
            continue
        event = {
            "id": _stable("EVT", key),
            "key": key,
            "kind": kind,
            "case_id": case_id,
            "from_stage": old,
            "to_stage": stage,
            "priority": case.get("priority"),
            "next_action": case.get("next_action"),
            "owner": case.get("owner"),
            "status": "open",
            "created_at": utcnow(),
        }
        events.append(event)
        created.append(event)
        known.add(key)
    state["autonomy_event_queue"] = events[-MAX_EVENTS:]
    memory["case_stages"] = current
    memory["last_event_build_at"] = utcnow()
    return created


def _merge_action_queue(state: Dict[str, Any], cases: List[Dict[str, Any]]) -> int:
    existing = [x for x in state.get("operating_action_queue", []) or [] if not str(x.get("key") or "").startswith("autonomy_case|")]
    canonical = []
    for case in cases[:MAX_ACTIONS]:
        canonical.append({
            "key": f"autonomy_case|{case['id']}",
            "kind": "canonical_next_action",
            "title": f"{case['stage']}: {case['title']}",
            "reason": case["next_action"],
            "impact": case["priority"],
            "urgency": case["priority"],
            "confidence": 0.82 if case["stage_rank"] >= 2 else 0.68,
            "effort": 1.0,
            "risk": "high" if case["human_required"] else "low",
            "autonomous": not case["human_required"],
            "object_type": "autonomy_case",
            "object_id": case["id"],
            "priority_score": case["priority"],
            "payload": {
                "stage": case["stage"],
                "source_type": case["source_type"],
                "source_id": case["source_id"],
                "category": case["category"],
                "deadline": case["deadline"],
                "next_action": case["next_action"],
            },
            "created_at": utcnow(),
        })
    merged = existing + canonical
    merged.sort(key=lambda x: _f(x.get("priority_score")), reverse=True)
    state["operating_action_queue"] = merged[:120]
    return len(canonical)


def build_autonomy_snapshot(state: Dict[str, Any], *, mutate: bool = False) -> Dict[str, Any]:
    cases = _canonical_cases(state)
    weights = _category_weights(cases)
    events = _events(state, cases) if mutate else []
    actions_added = _merge_action_queue(state, cases) if mutate else 0
    stage_counts = {stage: sum(1 for c in cases if c["stage"] == stage) for stage in STAGES}
    human = [c for c in cases if c["human_required"]]
    top = cases[:MAX_ACTIONS]
    ordered_categories = [x[0] for x in sorted(weights.items(), key=lambda item: item[1], reverse=True)]
    snapshot = {
        "version": VERSION,
        "updated_at": utcnow(),
        "status": "active",
        "cases_total": len(cases),
        "stage_counts": stage_counts,
        "top_actions": top,
        "primary_action": top[0] if top else None,
        "human_decisions": human[:6],
        "human_decisions_count": len(human),
        "events_created": len(events),
        "actions_injected": actions_added,
        "procurement_category_weights": weights,
        "procurement_category_order": ordered_categories,
        "policy": {
            "single_next_action_per_case": True,
            "binding_actions_require_human": True,
            "payments_contracts_orders_require_human": True,
            "nonbinding_research_followup_autonomous": True,
            "economic_learning": "stage progression + priority + realized close/cash evidence",
        },
    }
    if mutate:
        state["autonomy_operating_system"] = snapshot
        state["autonomy_cases"] = cases
    return snapshot


def autonomy_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    return build_autonomy_snapshot(state, mutate=True)
