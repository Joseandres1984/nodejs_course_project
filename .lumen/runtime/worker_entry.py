from __future__ import annotations

import runpy

# Install the shared search-budget split before other modules import Scout constants.
import search_budget_governor  # noqa: F401
# Make provider-budget reservations transactional across concurrent processes. Fail closed if
# PostgreSQL cannot confirm a claim, so the hard daily cap cannot be overspent by a race.
import search_budget_atomic_runtime  # noqa: F401

# Existing prospecting and demand-intelligence upgrades.
import growth_prospector  # noqa: F401 - prospecting patches are applied on import
import demand_hunter_runtime  # noqa: F401 - demand-first scoring/prioritization patches
import supreme_autonomy_runtime  # noqa: F401
import public_procurement_runtime  # noqa: F401
import adaptive_procurement_runtime  # noqa: F401
import operational_health_runtime  # noqa: F401
import https_mail_transport  # noqa: F401
import gmail_sent_runtime  # noqa: F401
import market_intelligence_runtime  # noqa: F401
import continuous_learning_compat_runtime  # noqa: F401

# Revenue Execution v2: adaptive budget with one shared hard provider cap.
import adaptive_search_budget_runtime  # noqa: F401
# Persisted state is reloaded several times during a worker cycle. Reconcile legacy search counters
# after every load, using the active adaptive split, without reopening the provider budget.
import search_budget_reconciliation_runtime  # noqa: F401
import shared_search_cap_runtime  # noqa: F401

# Single commercial source of truth. This installs the Autonomy OS filter before allocator/bridge
# wrappers are imported, so raw legacy deals cannot create false closing priority.
import canonical_revenue_truth_runtime  # noqa: F401

import revenue_allocator_runtime  # noqa: F401
import revenue_execution_bridge_runtime  # noqa: F401
import quote_accelerator_runtime  # noqa: F401
import commercial_learning_v2_runtime  # noqa: F401
import commercial_learning_v2_log_runtime  # noqa: F401

# Conversion Sprint tightens OFERTA truth, shifts attention toward requirement/RFQ/quote conversion,
# and forces experiment rotation after repeated same-lane failures without widening authority.
import conversion_sprint_runtime  # noqa: F401

# Autonomy Core gives the workforce a shared goal/lesson/help blackboard, outcome-based experience
# memory, bounded skill learning and research-gap missions. It only reallocates reversible attention
# and public research; binding, financial, legal, connector and deployment authority stay human-gated.
import autonomy_core_runtime  # noqa: F401
# Close the learning loop after each completed continuous-learning phase so fresh outcomes become
# experience, lessons, peer briefings and next-cycle research missions before state persistence.
import autonomy_core_bridge_runtime  # noqa: F401

# Temporary cross-functional Mission Teams form around the strongest canonical objectives, share
# evidence through explicit handoffs, prioritize related professional cases, request peer help and
# research automatically, and teach successful handoff patterns back into the shared playbook.
import mission_team_runtime  # noqa: F401

# Conversion unblocker preserves evidence gates but removes avoidable commercial deadlocks:
# research-source accounts, over-strict pre-RFQ requirements, one-shot buyer outreach, and stalled
# mission-team attention when a case is waiting on an external response.
import conversion_unblock_runtime  # noqa: F401

# Deep Work must spend capacity on real commercial entities. Historical search/social/job-platform
# cases stay auditable as evidence, but no longer consume active professional or mission-team slots.
import casework_hygiene_runtime  # noqa: F401

# Adaptive Operator measures verified commercial progress, tests reversible strategies, learns
# strategy yield, rotates repeatedly stagnant opportunities and switches to offline evidence reuse
# when search budget is exhausted. It cannot widen binding/spend/deployment authority.
import adaptive_operator_runtime  # noqa: F401

# Repair conversion truth: reuse only exact current official procurement evidence for RFQ fields,
# strongly demote stale procurement hits, and count outbound as genuine only after provider acceptance.
import commercial_truth_repair_runtime  # noqa: F401

# When a current official procurement URL is already known, inspect a tiny bounded number of those
# public documents directly to extract exact missing RFQ fields without spending search-provider quota.
import procurement_document_enrichment_runtime  # noqa: F401

# Preserve exact evidence provenance through lead -> buyer account -> opportunity before enrichment,
# avoiding category-only inference and allowing the RFQ bridge to find the correct official document.
import procurement_lineage_runtime  # noqa: F401

# Keep the external-readiness dashboard on the same truth standard: provider acceptance and verified
# delivery are separate, and raw legacy `sent` rows cannot make market reach look healthier than it is.
import external_market_truth_runtime  # noqa: F401

# Final cleanup before Executive Secretary: preserve legacy deals for audit, but suppress any
# Safe Close / data-truth / first-cash queue item that still points to a quarantined deal.
import canonical_priority_cleanup  # noqa: F401

# The professional account is authorized with Instagram Login credentials; use
# graph.instagram.com for media container creation and publication.
import instagram_graph_transport_runtime  # noqa: F401

# Instagram content may be prepared autonomously, but one immutable post can be published only
# after explicit human approval. The control also prepares a public JPEG asset for Meta to fetch.
import instagram_publish_control  # noqa: F401

# Harden WhatsApp delivery before worker_journal imports notification_router. Failures keep
# their Meta error code/message (without secrets), use bounded retries, and never resend email.
import whatsapp_resilience_runtime  # noqa: F401

runpy.run_module("worker_journal", run_name="__main__")
