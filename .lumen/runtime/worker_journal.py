from __future__ import annotations

# Expand the retail radar before Meta-LUMEN imports the production worker. This patch adds
# Tiendanube, major Argentine retailers, brand stores and independent e-commerce corroboration
# while preserving the existing public-search, budget and commission-only guardrails.
import retail_market_expansion  # noqa: F401,E402

# Harden SMTP/IMAP transport and bounded retry of governed email canaries before the production
# worker imports Mail Connector functions. This keeps all existing communication/quality gates.
import mail_resilience  # noqa: F401,E402

# Railway can block SMTP egress on non-Pro plans. Install an HTTPS transactional-mail fallback
# (Resend/Brevo) and a circuit-breaker so a blocked SMTP network never stalls the business cycle.
import https_mail_transport  # noqa: F401,E402

# Install verified social-distribution connectors before Meta-LUMEN imports the distribution
# operator. External social jobs remain pending until an authorized account/token is configured.
import social_distribution  # noqa: F401,E402

# Install the governed B2B Outbound Engine before worker.py captures Commercial Execution.
# New outreach is still forced through Communication Director, Quality Gate, COO and mail gates.
import outbound_engine  # noqa: F401,E402

# A resend.dev sender proves the API integration but is sandbox-only. This fail-closed gate keeps
# prospect outreach prepared until a custom Resend domain has been verified and configured.
import outbound_domain_gate  # noqa: F401,E402

# Recover a previously failed message only when the HTTPS provider is ready and the exact message
# had already passed Communication Director + Quality Gate. This fixes transport deadlocks without
# widening targeting, opt-out, risk, contract, payment or publication authority.
import outbound_recovery_runtime  # noqa: F401,E402

# Run the complete Meta-LUMEN + production worker first.
import worker_meta  # noqa: F401,E402

from app import STATE, load_state, save_state
from autonomy_operating_system import autonomy_tick
from cycle_journal import record_cycle
from executive_secretary import secretary_tick
from external_market_readiness import external_market_readiness_tick
from first_cash_mode import first_cash_tick
from notification_router import notification_router_tick


# After the business cycle, collapse demand/opportunity/deal evidence into one canonical state machine.
# Each case gets exactly one stage, one next action and one owner. Non-binding work stays autonomous;
# binding close/payment/contract authority remains human-gated.
load_state()
autonomy = autonomy_tick(STATE)

# Until LUMEN records a real realized profit, bias the unified queue toward the shortest credible path
# to cash. This does not widen contract/payment/order authority and does not fabricate economic values.
first_cash = first_cash_tick(STATE, autonomy)

# Audit whether LUMEN is merely online or can actually reach the external market. The audit exposes
# exact blockers (transport/live/eligibility) and creates a high-severity internal event on change.
external_readiness = external_market_readiness_tick(STATE)

# Continuous Revenue Drive is called explicitly here instead of relying on an import-time wrapper.
# This makes the revenue fallback deterministic: every completed worker cycle refreshes a ranked,
# non-binding next-action queue even when fresh search budget is exhausted.
from continuous_revenue_drive_runtime import continuous_revenue_drive_tick  # noqa: E402
continuous_revenue = continuous_revenue_drive_tick(STATE)

# Build the executive-secretary brief from the now-unified, cash-prioritized and continuous-revenue
# state so the daily brief reflects the same priorities the autonomous operating system will carry.
secretary = secretary_tick(STATE)

# Route only evidence-backed IMPORTANT/CRITICAL events through the already configured WhatsApp channel.
# INFO remains dashboard-only. The router deduplicates stable events and never changes commercial,
# contractual, payment or publication authority.
notifications = notification_router_tick(STATE)

persisted = bool(save_state())
secretary["persisted"] = persisted
autonomy["persisted"] = persisted
first_cash["persisted"] = persisted
external_readiness["persisted"] = persisted
continuous_revenue["persisted"] = persisted
notifications["persisted"] = persisted

print({
    "autonomy_operating_system": {
        "status": autonomy.get("status"),
        "cases_total": autonomy.get("cases_total"),
        "stage_counts": autonomy.get("stage_counts"),
        "human_decisions": autonomy.get("human_decisions_count"),
        "events_created": autonomy.get("events_created"),
        "actions_injected": autonomy.get("actions_injected"),
        "category_order": autonomy.get("procurement_category_order"),
        "persisted": autonomy.get("persisted"),
    }
}, flush=True)

print({
    "first_cash_mode": {
        "status": first_cash.get("status"),
        "objective": first_cash.get("objective"),
        "realized_profit_detected": first_cash.get("realized_profit_detected"),
        "actions_injected": first_cash.get("actions_injected"),
        "top_cash_cases": [
            {
                "id": x.get("id"),
                "stage": x.get("stage"),
                "score": x.get("first_cash_score"),
                "owner": x.get("owner"),
                "next_action": x.get("next_action"),
            }
            for x in (first_cash.get("top_cash_cases") or [])[:3]
        ],
        "persisted": first_cash.get("persisted"),
    }
}, flush=True)

print({
    "external_market_readiness": {
        "status": external_readiness.get("status"),
        "primary_blocker": external_readiness.get("primary_blocker"),
        "mail_transport_ready": external_readiness.get("mail_transport_ready"),
        "mail_provider": external_readiness.get("mail_provider"),
        "outbound_live": external_readiness.get("outbound_live"),
        "eligible_external_prospects": external_readiness.get("eligible_external_prospects"),
        "ineligibility_reasons": external_readiness.get("ineligibility_reasons"),
        "outbox_ready": external_readiness.get("outbox_ready"),
        "outbox_sent_or_delivered": external_readiness.get("outbox_sent_or_delivered"),
        "outbox_failed": external_readiness.get("outbox_failed"),
        "social_jobs_awaiting_authorized_connector": external_readiness.get("social_jobs_awaiting_authorized_connector"),
        "persisted": external_readiness.get("persisted"),
    }
}, flush=True)

print({
    "continuous_revenue_drive": {
        "status": continuous_revenue.get("status"),
        "mode": continuous_revenue.get("mode"),
        "objective": continuous_revenue.get("objective"),
        "never_idle": continuous_revenue.get("never_idle"),
        "search_budget_exhausted": continuous_revenue.get("search_budget_exhausted"),
        "search_remaining": continuous_revenue.get("search_remaining"),
        "primary_lane": continuous_revenue.get("primary_lane"),
        "primary_action": continuous_revenue.get("primary_action"),
        "primary_success_metric": continuous_revenue.get("primary_success_metric"),
        "queue_size": len(continuous_revenue.get("priority_queue") or []),
        "persisted": continuous_revenue.get("persisted"),
    }
}, flush=True)

print({
    "executive_secretary": {
        "status": secretary.get("status"),
        "news": len(secretary.get("news", []) or []),
        "new_news": sum(1 for x in secretary.get("news", []) or [] if x.get("new_since_last_brief")),
        "pending": len(secretary.get("pending", []) or []),
        "decisions": len(secretary.get("decisions", []) or []),
        "admin_attention": len(secretary.get("admin_attention", []) or []),
        "persisted": secretary.get("persisted"),
    }
}, flush=True)

print({
    "notification_router": {
        "channel": notifications.get("channel"),
        "delivery_ready": (notifications.get("status") or {}).get("delivery_ready"),
        "queued_for_whatsapp": notifications.get("queued_for_whatsapp"),
        "sent_this_tick": notifications.get("sent_this_tick"),
        "failed_this_tick": notifications.get("failed_this_tick"),
        "sent_total": notifications.get("sent_total"),
        "persisted": notifications.get("persisted"),
    }
}, flush=True)

# Persist one compact, queryable audit row only after the business cycle, autonomy OS, first-cash mode,
# external-readiness audit, continuous revenue drive, secretarial brief and notification routing completed.
# The journal uses its own Postgres table so global state stays bounded.
journal = record_cycle(STATE, source="worker_complete")
print({"cycle_journal": {k: v for k, v in journal.items() if k != "entry"}}, flush=True)
