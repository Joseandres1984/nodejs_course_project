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
import retail_consumer_goods_runtime  # noqa: F401
import continuous_learning_compat_runtime  # noqa: F401
import adaptive_search_budget_runtime  # noqa: F401
import search_budget_reconciliation_runtime  # noqa: F401
import shared_search_cap_runtime  # noqa: F401
import search_efficiency_runtime  # noqa: F401
import search_yield_runtime  # noqa: F401
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
import multicurrency_runtime  # noqa: F401

# Improve A2A candidate selection before the post-cycle agent-network tick runs.
# This preserves the original probe/handshake caps and all safety guardrails.
import agent_network_runtime  # noqa: F401
import agent_network_accelerator_runtime  # noqa: F401

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

# Expansion is intentionally post-cycle and fail-open: it consolidates persisted evidence,
# never authorizes spend/binding actions, and cannot take the normal worker down if it fails.
try:
    from app import STATE, load_state, save_state
    from expansion_revenue_runtime import expansion_revenue_tick

    if load_state():
        expansion = dict(expansion_revenue_tick(STATE) or {})
        loop = expansion.get("revenue_loop", {}) or {}
        metrics = loop.get("metrics", {}) or {}

        # Service revenue uses its own verified transaction ledger. Reconcile that parallel lane
        # after the service tick so the expansion dashboard counts only explicit won/paid truth.
        service_summary = STATE.get("service_revenue_runtime", {}) or {}
        service_won = max(0, int(service_summary.get("won") or 0))
        try:
            service_realized = max(0.0, float(service_summary.get("realized_service_revenue_usd") or 0.0))
        except (TypeError, ValueError):
            service_realized = 0.0
        metrics["sales_closed"] = max(0, int(metrics.get("sales_closed") or 0)) + service_won
        metrics["revenue_generated_usd"] = round(max(0.0, float(metrics.get("revenue_generated_usd") or 0.0)) + service_realized, 2)
        STATE["expansion_revenue_metrics"] = metrics
        if isinstance(STATE.get("expansion_revenue"), dict):
            STATE["expansion_revenue"]["metrics"] = metrics
        if isinstance(STATE.get("expansion_phase"), dict):
            revenue_loop = STATE["expansion_phase"].get("revenue_loop")
            if isinstance(revenue_loop, dict):
                revenue_loop["metrics"] = metrics

        expansion["persisted"] = bool(save_state())
        governance = expansion.get("search_governance", {}) or {}
        guardrails = expansion.get("guardrails", {}) or {}
        print({
            "expansion_revenue_runtime": {
                "version": expansion.get("version"),
                "status": expansion.get("status"),
                "companies_known": metrics.get("companies_known"),
                "catalogs_indexed": metrics.get("catalogs_indexed"),
                "products_known": metrics.get("products_known"),
                "needs_detected": metrics.get("needs_detected"),
                "opportunities_active": metrics.get("opportunities_active"),
                "buyers_contacted": metrics.get("buyers_contacted"),
                "suppliers_contacted": metrics.get("suppliers_contacted"),
                "replies": metrics.get("replies"),
                "negotiations": metrics.get("negotiations"),
                "proposals": metrics.get("proposals"),
                "margin_potential_usd": metrics.get("margin_potential_usd"),
                "sales_closed": metrics.get("sales_closed"),
                "revenue_generated_usd": metrics.get("revenue_generated_usd"),
                "daily_provider_cap": governance.get("daily_provider_cap"),
                "catalog_first_search_last": governance.get("catalog_first_search_last"),
                "paid_spend_authority_changed": guardrails.get("paid_spend_authority_changed"),
                "binding_authority_changed": guardrails.get("binding_authority_changed"),
                "autonomous_purchase": guardrails.get("autonomous_purchase"),
                "persisted": expansion.get("persisted"),
            }
        }, flush=True)
except Exception as exc:
    print({"expansion_revenue_runtime": {"status": "degraded_fail_open", "error": f"{type(exc).__name__}: {str(exc)[:260]}"}}, flush=True)

# Refresh payment routing and expose a truthful ARS/USD/EUR readiness matrix every cycle.
# This does not perform FX conversion, move funds or authorize any payment.
try:
    from app import STATE, load_state, save_state
    from payment_rails import payment_rails_tick

    if load_state():
        payment_rails = dict(payment_rails_tick(STATE) or {})
        multicurrency = dict(multicurrency_runtime.multicurrency_tick(STATE) or {})
        persisted = bool(save_state())
        matrix = multicurrency.get("currency_matrix", {}) or {}
        print({
            "multicurrency_runtime": {
                "version": multicurrency.get("version"),
                "status": multicurrency.get("status"),
                "supported_currencies": multicurrency.get("supported_currencies"),
                "ready_currencies": multicurrency.get("ready_currencies"),
                "setup_required_currencies": multicurrency.get("setup_required_currencies"),
                "ars_ready": bool((matrix.get("ARS") or {}).get("ready_to_collect")),
                "usd_ready": bool((matrix.get("USD") or {}).get("ready_to_collect")),
                "eur_ready": bool((matrix.get("EUR") or {}).get("ready_to_collect")),
                "ready_routes": payment_rails.get("ready_routes"),
                "setup_required_routes": payment_rails.get("setup_required"),
                "automatic_fx_conversion": False,
                "autonomous_payment": False,
                "persisted": persisted,
            }
        }, flush=True)
except Exception as exc:
    print({"multicurrency_runtime": {"status": "degraded_fail_open", "error": f"{type(exc).__name__}: {str(exc)[:260]}"}}, flush=True)

# Agent Network is intentionally bounded and fail-open. It probes only already verified supplier
# domains for public A2A Agent Cards, blocks private-network/cross-domain targets and sends at most
# one non-binding capability handshake per cycle. It cannot purchase, pay, contract or accept terms.
try:
    from app import STATE, load_state, save_state
    from agent_network_runtime import agent_network_tick

    if load_state():
        agent_network = dict(agent_network_tick(STATE) or {})
        agent_network["persisted"] = bool(save_state())
        print({
            "agent_network_runtime": {
                "version": agent_network.get("version"),
                "status": agent_network.get("status"),
                "mode": agent_network.get("mode"),
                "probes_this_tick": agent_network.get("probes_this_tick"),
                "registry_query": agent_network.get("registry_query"),
                "registry_status": agent_network.get("registry_status"),
                "registry_candidates_this_tick": agent_network.get("registry_candidates_this_tick"),
                "discovered_this_tick": agent_network.get("discovered_this_tick"),
                "handshakes_this_tick": agent_network.get("handshakes_this_tick"),
                "discovered_total": agent_network.get("discovered_total"),
                "handshakes_total": agent_network.get("handshakes_total"),
                "binding_actions_human_gated": (agent_network.get("guardrails") or {}).get("binding_actions_human_gated"),
                "persisted": agent_network.get("persisted"),
            }
        }, flush=True)
except Exception as exc:
    print({"agent_network_runtime": {"status": "degraded_fail_open", "error": f"{type(exc).__name__}: {str(exc)[:260]}"}}, flush=True)
