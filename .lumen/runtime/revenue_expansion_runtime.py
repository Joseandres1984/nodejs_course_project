from __future__ import annotations

"""LUMEN Revenue Expansion v1.

Adds three zero-cost monetization lanes on top of existing LUMEN capabilities:
1) Sourcing Success: success-fee sourcing preparation for verified buyer demand.
2) Tender / Buyer Intent subscriptions: recurring intelligence products.
3) Agent APIs: fixed-price machine-readable services for external agents.

This runtime never creates binding commitments, spends money, changes payment authority,
lowers evidence gates, or fabricates commercial outcomes. It only materializes catalog,
pricing, positioning, and nonbinding execution priorities for capabilities LUMEN already has.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List

VERSION = "1.0-revenue-expansion"

SOURCING_SUCCESS = {
    "id": "REV-SOURCING-SUCCESS",
    "name": "LUMEN Sourcing Success",
    "type": "success_fee_service",
    "status": "active",
    "customer_pays_upfront_usd": 0,
    "success_fee_pct": {"min": 4.0, "target": 6.0, "max": 8.0},
    "fee_basis": "verified_completed_transaction_value",
    "requires_verified_demand": True,
    "requires_human_binding_acceptance": True,
    "autonomous_discount": False,
    "autonomous_contract": False,
    "autonomous_payment": False,
    "promise": "LUMEN busca, verifica y compara proveedores; la comisión aplica solo si el cliente concreta la operación.",
}

SUBSCRIPTIONS = [
    {
        "id": "REV-TENDER-RADAR-BASIC",
        "name": "LUMEN Tender Radar Basic",
        "type": "subscription",
        "price_usd_month": 29,
        "deliverable": "alertas filtradas de licitaciones y compras públicas compatibles",
        "binding_purchase_requires_human": True,
    },
    {
        "id": "REV-TENDER-RADAR-PRO",
        "name": "LUMEN Tender Radar Pro",
        "type": "subscription",
        "price_usd_month": 79,
        "deliverable": "alertas + análisis de comprador, encaje y prioridad comercial",
        "binding_purchase_requires_human": True,
    },
    {
        "id": "REV-TENDER-RADAR-PLUS",
        "name": "LUMEN Tender Radar + RFQ",
        "type": "subscription",
        "price_usd_month": 199,
        "deliverable": "alertas + análisis + preparación no vinculante de RFQ",
        "binding_purchase_requires_human": True,
    },
    {
        "id": "REV-BUYER-INTENT-FEED",
        "name": "LUMEN Buyer Intent Feed",
        "type": "subscription",
        "price_usd_month": 99,
        "deliverable": "feed de empresas con señales verificables de compra por categoría",
        "truth_rule": "only_verified_public_demand_signals",
        "binding_purchase_requires_human": True,
    },
]

AGENT_APIS = [
    {"id": "A2A-COMPANY-VERIFY", "name": "Company Verify", "unit_price_usd": 0.02, "unit": "call"},
    {"id": "A2A-SUPPLIER-CHECK", "name": "Supplier Check", "unit_price_usd": 0.10, "unit": "call"},
    {"id": "A2A-QUOTE-CHECK", "name": "Quote Check", "unit_price_usd": 0.25, "unit": "call"},
    {"id": "A2A-SOURCING-SHORTLIST", "name": "Sourcing Shortlist", "unit_price_usd": 2.00, "unit": "request"},
    {"id": "A2A-TENDER-MATCH", "name": "Tender Match", "unit_price_usd": 0.50, "unit": "call"},
]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _existing_revenue(state: Dict[str, Any]) -> float:
    values = []
    for key in ("realized_revenue_usd", "realized_service_revenue_usd"):
        values.append(_f(state.get(key)))
    for node_key in ("service_revenue_runtime", "service_growth_pipeline", "intelligence_revenue_engine"):
        node = state.get(node_key)
        if isinstance(node, dict):
            values.append(_f(node.get("realized_revenue_usd") or node.get("realized_service_revenue_usd")))
    return max(values or [0.0])


def _counts(state: Dict[str, Any]) -> Dict[str, int]:
    truth = state.get("operational_truth_auditor") if isinstance(state.get("operational_truth_auditor"), dict) else {}
    counts = truth.get("counts") if isinstance(truth.get("counts"), dict) else {}
    return {
        "verified_buyers": _i(counts.get("verified_buyers") or state.get("verified_buyer_count")),
        "buyers_with_verified_demand": _i(counts.get("buyers_with_verified_demand")),
        "verified_suppliers": _i(counts.get("verified_suppliers") or state.get("verified_supplier_count")),
        "verified_contacts": _i(counts.get("verified_commercial_contacts") or state.get("verified_corporate_contact_count")),
        "canonical_opportunities": _i(counts.get("canonical_opportunities")),
    }


def _lane_priority(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    counts = _counts(state)
    revenue = _existing_revenue(state)
    lanes: List[Dict[str, Any]] = []

    # Recurring intelligence can be sold before a principal transaction exists,
    # but content must still be evidence-backed. It is therefore the fastest new lane.
    lanes.append({
        "lane": "subscriptions",
        "priority": 96 if revenue <= 0 else 82,
        "reason": "recurring_revenue_using_existing_research_and_verified_public_evidence",
        "next_action": "surface_tender_radar_and_buyer_intent_offers_to_verified_service_fit_accounts",
    })

    if counts["buyers_with_verified_demand"] > 0:
        sourcing_priority = 100
        reason = "verified_buyer_demand_exists_success_fee_can_attach_to_real_transaction"
    else:
        sourcing_priority = 88
        reason = "prepare_success_fee_lane_but_do_not_sell_as_transaction_ready_until_demand_is_verified"
    lanes.append({
        "lane": "sourcing_success",
        "priority": sourcing_priority,
        "reason": reason,
        "next_action": "attach_success_fee_offer_only_to_canonical_verified_demand_cases",
    })

    lanes.append({
        "lane": "agent_apis",
        "priority": 72,
        "reason": "machine_readable_catalog_can_accumulate_24x7_pay_per_call_demand_without_paid_spend",
        "next_action": "publish_fixed_price_nonbinding_machine_catalog_and_track_paid_settlement_separately",
    })

    lanes.sort(key=lambda row: -_i(row.get("priority")))
    return lanes


def build_catalog() -> Dict[str, Any]:
    return {
        "version": VERSION,
        "sourcing_success": dict(SOURCING_SUCCESS),
        "subscriptions": [dict(row) for row in SUBSCRIPTIONS],
        "agent_apis": [dict(row) for row in AGENT_APIS],
        "currency": "USD",
        "pricing_status": "launch_validation",
        "price_changes_require_human_review": True,
        "paid_media_spend": False,
        "autonomous_outgoing_spend": False,
        "binding_authority_changed": False,
    }


def run_once(state: Dict[str, Any]) -> Dict[str, Any]:
    report = {
        "version": VERSION,
        "status": "active",
        "updated_at": _now(),
        "catalog": build_catalog(),
        "lane_priority": _lane_priority(state),
        "counts": _counts(state),
        "realized_revenue_truth_usd": _existing_revenue(state),
        "monetary_budget_usd": 0,
        "search_cap_changed": False,
        "outbound_caps_changed": False,
        "evidence_thresholds_changed": False,
        "autonomous_discount": False,
        "autonomous_contract": False,
        "autonomous_payment": False,
        "binding_authority_changed": False,
        "truth_rule": "catalog_or_prepared_offer_is_not_sale; only_settled_payment_is_realized_revenue",
    }
    state["revenue_expansion"] = report
    return report


print({
    "revenue_expansion_runtime": {
        "version": VERSION,
        "status": "installed",
        "lanes": ["sourcing_success", "subscriptions", "agent_apis"],
        "monetary_budget_usd": 0,
        "search_cap_changed": False,
        "outbound_caps_changed": False,
        "binding_authority_changed": False,
    }
}, flush=True)
