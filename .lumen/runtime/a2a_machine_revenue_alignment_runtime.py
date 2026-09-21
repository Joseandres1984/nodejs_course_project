from __future__ import annotations

"""Align fixed-price A2A Machine Store requests with the canonical service CRM.

Public/human custom projects still require human price confirmation. Only requests created by the
trusted A2A bridge with a LUMEN-generated quote id and a known machine product/plan keep their
already-published non-binding catalog price automatically. This patch never marks a sale won,
never verifies a payment, and never grants outgoing-spend or binding authority.
"""

from typing import Any, Dict, List

import service_revenue_runtime as _service

VERSION = "1.0-a2a-machine-fixed-quote-alignment"
_ORIGINAL_BUILD_PIPELINE = _service._build_pipeline
_ORIGINAL_TICK = _service.service_revenue_tick


def _f(value: Any) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _machine_inquiries(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    for inquiry in state.get("service_inquiries", []) or []:
        if not isinstance(inquiry, dict):
            continue
        if str(inquiry.get("source") or "") != "a2a_machine_store":
            continue
        if str(inquiry.get("machine_item_type") or "") not in {"product", "plan"}:
            continue
        quote_id = str(inquiry.get("quote_id") or "")
        amount = _f(inquiry.get("quoted_amount_usd"))
        if not quote_id.startswith("A2AQ-") or amount <= 0:
            continue
        inquiry_id = str(inquiry.get("id") or "")
        if inquiry_id:
            result[inquiry_id] = inquiry
    return result


def _build_pipeline_with_machine_quotes(state: Dict[str, Any], opportunities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = list(_ORIGINAL_BUILD_PIPELINE(state, opportunities) or [])
    machine = _machine_inquiries(state)
    for row in rows:
        inquiry = machine.get(str(row.get("source_id") or ""))
        if not inquiry:
            continue
        amount = _f(inquiry.get("quoted_amount_usd"))
        billing = str(inquiry.get("billing") or "per_request")[:80]
        item_id = str(inquiry.get("machine_item_id") or "")[:100]
        quote_id = str(inquiry.get("quote_id") or "")[:120]
        row.update({
            "source": "a2a_machine_store",
            "machine_item_type": inquiry.get("machine_item_type"),
            "machine_item_id": item_id,
            "machine_product_id": inquiry.get("machine_product_id"),
            "recurring_plan_id": inquiry.get("recurring_plan_id"),
            "quoted_amount_usd": round(amount, 2),
            "quote_id": quote_id,
            "billing": billing,
            "price_status": "fixed_machine_catalog_quote_nonbinding",
            "price_requires_human_confirmation": False,
            "seller_mode": "receive_revenue_only",
        })
        proposal = row.get("proposal_draft") if isinstance(row.get("proposal_draft"), dict) else {}
        proposal.update({
            "price": f"USD {amount:g}" + (" / mes" if billing == "per_month" else ""),
            "price_source": "lumen_machine_store_catalog",
            "quote_id": quote_id,
            "machine_item_id": item_id,
            "billing": billing,
            "status": "prepared_nonbinding_fixed_price",
            "binding": False,
        })
        row["proposal_draft"] = proposal
        row["proposal_draft_status"] = "prepared_nonbinding_fixed_price"
        if row.get("account_id"):
            row["next_action"] = "Completar verificación comercial y preparar settlement; el precio de catálogo ya está fijado y no requiere recotización humana."
        else:
            row["next_action"] = "Verificar identidad de la contraparte; conservar el precio de catálogo sin recotización humana."
    return rows


def _tick_with_machine_alignment(state: Dict[str, Any]) -> Dict[str, Any]:
    summary = dict(_ORIGINAL_TICK(state) or {})
    machine_rows = [
        row for row in state.get("service_sales_pipeline", []) or []
        if isinstance(row, dict) and row.get("source") == "a2a_machine_store"
    ]
    fixed = [row for row in machine_rows if row.get("price_requires_human_confirmation") is False]
    summary["a2a_machine_store"] = {
        "status": "active",
        "pipeline_rows": len(machine_rows),
        "fixed_price_rows": len(fixed),
        "fixed_quote_without_human_repricing": True,
        "payment_verification_required": True,
        "binding_close_evidence_required": True,
        "autonomous_outgoing_spend": False,
    }
    summary["machine_price_autonomy"] = "catalog_fixed_price_nonbinding"
    state["service_revenue_runtime"] = summary
    return summary


_service._build_pipeline = _build_pipeline_with_machine_quotes
_service.service_revenue_tick = _tick_with_machine_alignment

print({
    "a2a_machine_revenue_alignment_runtime": {
        "version": VERSION,
        "status": "active",
        "machine_fixed_price_preserved": True,
        "human_repricing_required": False,
        "payment_verification_required": True,
        "binding_close_evidence_required": True,
        "autonomous_outgoing_spend": False,
    }
}, flush=True)
