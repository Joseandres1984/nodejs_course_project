from __future__ import annotations

import runpy

import search_budget_governor  # noqa: F401
import search_budget_atomic_runtime  # noqa: F401
import growth_prospector  # noqa: F401
import demand_hunter_runtime  # noqa: F401
import supreme_autonomy_runtime  # noqa: F401
import public_procurement_runtime  # noqa: F401
import adaptive_procurement_runtime  # noqa: F401
import operational_health_runtime  # noqa: F401
import https_mail_transport  # noqa: F401
import gmail_sent_runtime  # noqa: F401
import market_intelligence_runtime  # noqa: F401
import continuous_learning_compat_runtime  # noqa: F401
import adaptive_search_budget_runtime  # noqa: F401
import search_budget_reconciliation_runtime  # noqa: F401
import shared_search_cap_runtime  # noqa: F401
import external_exploration_runtime  # noqa: F401
import external_exploration_learning_runtime  # noqa: F401
import prospect_throughput_runtime  # noqa: F401
import canonical_revenue_truth_runtime  # noqa: F401
import revenue_allocator_runtime  # noqa: F401
import revenue_execution_bridge_runtime  # noqa: F401
import quote_accelerator_runtime  # noqa: F401
import commercial_learning_v2_runtime  # noqa: F401
import commercial_learning_v2_log_runtime  # noqa: F401
import conversion_sprint_runtime  # noqa: F401
import autonomy_core_runtime  # noqa: F401
import autonomy_core_bridge_runtime  # noqa: F401
import mission_team_runtime  # noqa: F401
import conversion_unblock_runtime  # noqa: F401
import casework_hygiene_runtime  # noqa: F401
import adaptive_operator_runtime  # noqa: F401
import commercial_truth_repair_runtime  # noqa: F401
import procurement_document_enrichment_runtime  # noqa: F401
import procurement_lineage_runtime  # noqa: F401
import external_market_truth_runtime  # noqa: F401
import service_revenue_runtime  # noqa: F401
import canonical_priority_cleanup  # noqa: F401
import instagram_graph_transport_runtime  # noqa: F401
import instagram_publish_control  # noqa: F401
import instagram_pro_editorial_runtime  # noqa: F401
import instagram_art_direction_runtime  # noqa: F401
import instagram_editorial_learning_runtime  # noqa: F401
import instagram_service_offers_runtime  # noqa: F401
import whatsapp_resilience_runtime  # noqa: F401

runpy.run_module("worker_journal", run_name="__main__")

try:
    from app import STATE, load_state, save_state

    if load_state():
        service_revenue = service_revenue_runtime.service_revenue_tick(STATE)
        service_revenue["persisted"] = bool(save_state())
        print({
            "service_revenue_runtime": {
                "version": service_revenue.get("version"),
                "status": service_revenue.get("status"),
                "mode": service_revenue.get("mode"),
                "active_services": service_revenue.get("active_services"),
                "prepared_service_opportunities": service_revenue.get("prepared_service_opportunities"),
                "service_inquiries": service_revenue.get("service_inquiries"),
                "realized_service_revenue_usd": service_revenue.get("realized_service_revenue_usd"),
                "commission_business_preserved": service_revenue.get("commission_business_preserved"),
                "persisted": service_revenue.get("persisted"),
            }
        }, flush=True)
except Exception as exc:
    print({"service_revenue_runtime": {"status": "degraded_fail_open", "error": f"{type(exc).__name__}: {str(exc)[:260]}"}}, flush=True)
