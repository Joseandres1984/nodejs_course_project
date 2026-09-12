from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


DEFAULT_POLICIES: Dict[str, Any] = {
    "min_company_share_pct": 8.0,
    "target_company_share_pct": 12.0,
    "risk_reserve_pct": 2.0,
    "max_auto_discount_pct": 5.0,
    "max_auto_deal_value_usd": 2500.0,
    "max_outbound_per_tick": 3,
    "require_verified_contact": True,
    "require_human_approval_for_contract": True,
    "require_human_approval_for_financial_commitment": True,
}


@dataclass
class DealEconomics:
    sale_price: float
    supplier_cost: float
    logistics_cost: float
    risk_reserve: float
    company_profit: float
    company_share_pct: float
    target_share_pct: float
    min_share_pct: float
    viable: bool
    gap_to_target: float

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        for key, value in list(result.items()):
            if isinstance(value, float):
                result[key] = round(value, 2)
        return result


def calculate_economics(
    sale_price: float,
    supplier_cost: float,
    logistics_cost: float,
    policies: Dict[str, Any],
) -> Dict[str, Any]:
    sale_price = max(0.0, float(sale_price))
    supplier_cost = max(0.0, float(supplier_cost))
    logistics_cost = max(0.0, float(logistics_cost))
    reserve_pct = float(policies.get("risk_reserve_pct", 2.0))
    min_share = float(policies.get("min_company_share_pct", 8.0))
    target_share = float(policies.get("target_company_share_pct", 12.0))
    risk_reserve = sale_price * reserve_pct / 100.0
    profit = sale_price - supplier_cost - logistics_cost - risk_reserve
    share_pct = (profit / sale_price * 100.0) if sale_price else 0.0
    target_profit = sale_price * target_share / 100.0
    return DealEconomics(
        sale_price=sale_price,
        supplier_cost=supplier_cost,
        logistics_cost=logistics_cost,
        risk_reserve=risk_reserve,
        company_profit=profit,
        company_share_pct=share_pct,
        target_share_pct=target_share,
        min_share_pct=min_share,
        viable=profit > 0 and share_pct >= min_share,
        gap_to_target=max(0.0, target_profit - profit),
    ).to_dict()


def ensure_commerce_state(state: Dict[str, Any]) -> None:
    state.setdefault("policies", dict(DEFAULT_POLICIES))
    for key, value in DEFAULT_POLICIES.items():
        state["policies"].setdefault(key, value)
    state.setdefault("conversations", [])
    state.setdefault("offers", [])
    state.setdefault("proposals", [])
    state.setdefault("negotiations", [])
    state.setdefault("approvals", [])
    state.setdefault("transactions", [])
    state.setdefault("revenue_ledger", [])
    state.setdefault("outbox", [])
    state.setdefault("inbox", [])


def _next_id(prefix: str, items: List[Dict[str, Any]]) -> str:
    return f"{prefix}-{len(items)+1:04d}"


def _log(state: Dict[str, Any], message: str) -> None:
    state.setdefault("activity", []).insert(0, {"ts": utcnow(), "msg": message})
    state["activity"] = state["activity"][:100]


def prepare_outreach(state: Dict[str, Any], deal: Dict[str, Any]) -> bool:
    ensure_commerce_state(state)
    if any(x.get("deal_id") == deal["id"] and x.get("kind") == "buyer_intro" for x in state["outbox"]):
        return False
    buyer = next((x for x in state.get("buyers", []) if x.get("name") == deal.get("buyer")), {})
    msg = {
        "id": _next_id("MSG", state["outbox"]),
        "deal_id": deal["id"],
        "kind": "buyer_intro",
        "counterparty": deal["buyer"],
        "channel": "email",
        "contact": buyer.get("email"),
        "contact_verified": bool(buyer.get("email_verified")),
        "subject": f"Consulta comercial — {deal.get('need','oportunidad B2B')}",
        "body": (
            f"Hola, estamos trabajando sobre una alternativa de abastecimiento para {deal.get('need','esta categoría')}. "
            "Quisiera validar especificación, volumen, plazo objetivo y condiciones comerciales para preparar una propuesta concreta."
        ),
        "status": "ready" if buyer.get("email") and buyer.get("email_verified") else "needs_verified_contact",
        "created_at": utcnow(),
    }
    state["outbox"].append(msg)
    state["conversations"].append({
        "id": _next_id("CONV", state["conversations"]),
        "deal_id": deal["id"],
        "counterparty": deal["buyer"],
        "direction": "outbound",
        "message_id": msg["id"],
        "status": msg["status"],
        "created_at": utcnow(),
    })
    deal["next_action"] = "Validar necesidad y condiciones con el comprador"
    _log(state, f"Relationship Engine preparó contacto para {deal['buyer']} en {deal['id']}.")
    return True


def request_supplier_offer(state: Dict[str, Any], deal: Dict[str, Any]) -> bool:
    ensure_commerce_state(state)
    if any(x.get("deal_id") == deal["id"] and x.get("kind") == "supplier_rfq" for x in state["outbox"]):
        return False
    supplier = next((x for x in state.get("suppliers", []) if x.get("name") == deal.get("supplier")), {})
    msg = {
        "id": _next_id("MSG", state["outbox"]),
        "deal_id": deal["id"],
        "kind": "supplier_rfq",
        "counterparty": deal["supplier"],
        "channel": "email",
        "contact": supplier.get("email"),
        "contact_verified": bool(supplier.get("email_verified")),
        "subject": f"Solicitud de oferta — {deal.get('need','material industrial')}",
        "body": (
            f"Solicitamos cotización para {deal.get('need','el requerimiento indicado')}. "
            "Agradecemos precio, validez, plazo de entrega, forma de pago, garantía, origen y documentación técnica disponible."
        ),
        "status": "ready" if supplier.get("email") and supplier.get("email_verified") else "needs_verified_contact",
        "created_at": utcnow(),
    }
    state["outbox"].append(msg)
    deal["next_action"] = "Obtener oferta formal del proveedor"
    _log(state, f"RFQ Engine preparó una solicitud de oferta para {deal['supplier']} en {deal['id']}.")
    return True


def synthesize_demo_offer(state: Dict[str, Any], deal: Dict[str, Any]) -> bool:
    ensure_commerce_state(state)
    if any(o.get("deal_id") == deal["id"] for o in state["offers"]):
        return False
    pipeline = float(deal.get("pipeline") or deal.get("sale_price") or 0)
    supplier_cost = round(pipeline * 0.72, 2)
    offer = {
        "id": _next_id("OFFER", state["offers"]),
        "deal_id": deal["id"],
        "supplier": deal["supplier"],
        "amount": supplier_cost,
        "currency": "USD",
        "lead_days": 15,
        "payment_terms": "30 días",
        "source": "demo/simulación",
        "verified": False,
        "created_at": utcnow(),
    }
    state["offers"].append(offer)
    _log(state, f"Quote Engine incorporó {offer['id']} para {deal['id']} por USD {supplier_cost:,.0f} (simulación).")
    return True


def build_proposal(state: Dict[str, Any], deal: Dict[str, Any]) -> bool:
    ensure_commerce_state(state)
    if any(p.get("deal_id") == deal["id"] for p in state["proposals"]):
        return False
    offer = next((o for o in state["offers"] if o.get("deal_id") == deal["id"]), None)
    if not offer:
        return False
    policies = state["policies"]
    supplier_cost = float(offer["amount"])
    target_share = float(policies.get("target_company_share_pct", 12.0)) / 100.0
    reserve = float(policies.get("risk_reserve_pct", 2.0)) / 100.0
    logistics = max(150.0, supplier_cost * 0.035)
    denominator = max(0.25, 1.0 - target_share - reserve)
    sale_price = round((supplier_cost + logistics) / denominator, 2)
    economics = calculate_economics(sale_price, supplier_cost, logistics, policies)
    proposal = {
        "id": _next_id("PROP", state["proposals"]),
        "deal_id": deal["id"],
        "buyer": deal["buyer"],
        "supplier": deal["supplier"],
        "sale_price": sale_price,
        "currency": "USD",
        "valid_days": 10,
        "economics": economics,
        "status": "draft",
        "created_at": utcnow(),
    }
    state["proposals"].append(proposal)
    deal["sale_price"] = sale_price
    deal["supplier_cost"] = supplier_cost
    deal["logistics_cost"] = round(logistics, 2)
    deal["economics"] = economics
    deal["company_profit"] = economics["company_profit"]
    deal["company_share_pct"] = economics["company_share_pct"]
    deal["next_action"] = "Presentar propuesta comercial al comprador"
    _log(state, f"Proposal Engine creó {proposal['id']} para {deal['buyer']}; participación estimada nuestra {economics['company_share_pct']:.1f}%.")
    return True


def negotiate(state: Dict[str, Any], deal: Dict[str, Any]) -> bool:
    ensure_commerce_state(state)
    econ = deal.get("economics")
    if not econ:
        return False
    policies = state["policies"]
    action = "hold"
    old_supplier = float(deal.get("supplier_cost", 0))
    old_sale = float(deal.get("sale_price", 0))
    logistics = float(deal.get("logistics_cost", 0))

    if not econ.get("viable") or float(econ.get("company_share_pct", 0)) < float(policies.get("target_company_share_pct", 12)):
        # First lever: improve supplier cost by a bounded 3% counteroffer.
        new_supplier = round(old_supplier * 0.97, 2)
        new_econ = calculate_economics(old_sale, new_supplier, logistics, policies)
        deal["supplier_cost"] = new_supplier
        deal["economics"] = new_econ
        deal["company_profit"] = new_econ["company_profit"]
        deal["company_share_pct"] = new_econ["company_share_pct"]
        action = "supplier_counteroffer_3pct"
        _log(state, f"Negotiator propuso mejorar 3% el costo de {deal['supplier']} para proteger nuestra participación en {deal['id']}.")
    else:
        action = "economics_acceptable"
        _log(state, f"Negotiator validó la economía de {deal['id']}: {econ['company_share_pct']:.1f}% queda para nosotros antes de impuestos/overhead corporativo.")

    state["negotiations"].append({
        "id": _next_id("NEG", state["negotiations"]),
        "deal_id": deal["id"],
        "action": action,
        "sale_price": deal.get("sale_price"),
        "supplier_cost": deal.get("supplier_cost"),
        "company_share_pct": deal.get("company_share_pct"),
        "created_at": utcnow(),
    })
    return True


def evaluate_close(state: Dict[str, Any], deal: Dict[str, Any]) -> bool:
    ensure_commerce_state(state)
    econ = deal.get("economics")
    if not econ or not econ.get("viable"):
        deal["stage"] = "renegociación"
        deal["next_action"] = "Mejorar costo/precio o descartar la operación"
        return False
    if any(a.get("deal_id") == deal["id"] and a.get("kind") == "close_deal" for a in state["approvals"]):
        return False
    sale = float(econ.get("sale_price", 0))
    require_approval = bool(state["policies"].get("require_human_approval_for_contract", True)) or sale > float(state["policies"].get("max_auto_deal_value_usd", 2500))
    approval = {
        "id": _next_id("APP", state["approvals"]),
        "deal_id": deal["id"],
        "kind": "close_deal",
        "status": "pending" if require_approval else "auto_authorized",
        "reason": "Compromiso contractual/financiero" if require_approval else "Dentro de política de autonomía",
        "company_profit": econ.get("company_profit"),
        "company_share_pct": econ.get("company_share_pct"),
        "created_at": utcnow(),
    }
    state["approvals"].append(approval)
    deal["stage"] = "listo para cerrar" if require_approval else "autorizado para cierre"
    deal["next_action"] = "Aprobación de cierre" if require_approval else "Ejecutar cierre según política"
    _log(state, f"Closer dejó {deal['id']} listo para cierre; participación nuestra estimada USD {float(econ.get('company_profit',0)):,.0f} ({float(econ.get('company_share_pct',0)):.1f}%).")
    return True


def commerce_tick(state: Dict[str, Any]) -> Dict[str, int]:
    """Advance a bounded number of commercial actions per autonomous tick."""
    ensure_commerce_state(state)
    stats = {"outreach": 0, "rfq": 0, "offers": 0, "proposals": 0, "negotiations": 0, "close_ready": 0}
    deals = sorted(state.get("deals", []), key=lambda d: float(d.get("expected_value", 0)), reverse=True)
    for deal in deals[: max(1, int(state["policies"].get("max_outbound_per_tick", 3)))]:
        stage = deal.get("stage", "descubrimiento")
        if stage == "descubrimiento":
            if prepare_outreach(state, deal): stats["outreach"] += 1
            deal["stage"] = "calificado"
            continue
        if stage == "calificado":
            if request_supplier_offer(state, deal): stats["rfq"] += 1
            if synthesize_demo_offer(state, deal): stats["offers"] += 1
            deal["stage"] = "propuesta"
            continue
        if stage == "propuesta":
            if build_proposal(state, deal): stats["proposals"] += 1
            deal["stage"] = "negociación"
            continue
        if stage in {"negociación", "renegociación"}:
            if negotiate(state, deal): stats["negotiations"] += 1
            if deal.get("economics", {}).get("viable"):
                if evaluate_close(state, deal): stats["close_ready"] += 1
            continue
    return stats


def approve_and_close(state: Dict[str, Any], approval_id: str) -> Dict[str, Any]:
    ensure_commerce_state(state)
    approval = next((a for a in state["approvals"] if a.get("id") == approval_id), None)
    if not approval:
        raise ValueError("Aprobación inexistente")
    if approval.get("status") not in {"pending", "auto_authorized"}:
        raise ValueError("La aprobación ya fue procesada")
    deal = next((d for d in state.get("deals", []) if d.get("id") == approval.get("deal_id")), None)
    if not deal or not deal.get("economics", {}).get("viable"):
        raise ValueError("El deal no es económicamente viable")
    approval["status"] = "approved"
    approval["approved_at"] = utcnow()
    txn = {
        "id": _next_id("TXN", state["transactions"]),
        "deal_id": deal["id"],
        "buyer": deal["buyer"],
        "supplier": deal["supplier"],
        "sale_price": deal["economics"]["sale_price"],
        "supplier_cost": deal["economics"]["supplier_cost"],
        "company_profit": deal["economics"]["company_profit"],
        "company_share_pct": deal["economics"]["company_share_pct"],
        "status": "closed_simulated",
        "financial_commitment_executed": False,
        "created_at": utcnow(),
    }
    state["transactions"].append(txn)
    state["revenue_ledger"].append({
        "id": _next_id("REV", state["revenue_ledger"]),
        "transaction_id": txn["id"],
        "amount": txn["company_profit"],
        "currency": "USD",
        "status": "expected",
        "created_at": utcnow(),
    })
    deal["stage"] = "cerrado (simulación)"
    deal["next_action"] = "Seguimiento de entrega, cobro y expansión de cuenta"
    _log(state, f"Closer registró {txn['id']} para {deal['id']}; compromiso financiero real sigue deshabilitado.")
    return txn
