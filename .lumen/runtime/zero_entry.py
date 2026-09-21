from __future__ import annotations

"""LUMEN Zero entrypoint.

Mirrors the production Railway worker bootstrap while replacing paid/credit-bound infrastructure
with the zero-cost D1 persistence and public Scout adapters.
"""

import os

# GitHub Actions expands missing optional repository secrets as empty strings. Production modules
# expect missing variables (so their own defaults apply), not values such as LUMEN_IMAP_PORT="".
# Normalize every empty LUMEN variable before importing any runtime module.
for _key in list(os.environ):
    if _key.startswith("LUMEN_") and not str(os.environ.get(_key) or "").strip():
        os.environ.pop(_key, None)

# Backward-compatibility: app.py uses LUMEN_LIVE_OUTBOUND while outbound_engine.py historically
# reads LUMEN_OUTBOUND_LIVE. Keep both in sync before either module is imported so one operator
# switch controls the whole outbound stack.
if "LUMEN_LIVE_OUTBOUND" in os.environ and "LUMEN_OUTBOUND_LIVE" not in os.environ:
    os.environ["LUMEN_OUTBOUND_LIVE"] = os.environ["LUMEN_LIVE_OUTBOUND"]

# Hard policy: this entrypoint is always zero-cost. Search has a conservative daily frontier so
# public providers are not hammered; existing evidence is reused by the normal LUMEN engines.
os.environ["LUMEN_ZERO_COST_MODE"] = "true"
os.environ["LUMEN_SCOUT_PROVIDER"] = "bing_rss_public"
os.environ["LUMEN_SCOUT_API_KEY"] = "zero-cost-no-secret-required"
os.environ.setdefault("LUMEN_SCOUT_MAX_QUERIES", "2")
os.environ.setdefault("LUMEN_SCOUT_DAILY_BUDGET", "24")
os.environ.setdefault("LUMEN_SCOUT_MAX_NEW_LEADS", "4")
os.environ.setdefault("LUMEN_PUBLIC_PROCUREMENT_MAX_QUERIES", "1")
os.environ.setdefault("LUMEN_PUBLIC_PROCUREMENT_DAILY_CAP", "8")
os.environ.setdefault("LUMEN_PARTNER_DAILY_SEARCH_CAP", "8")
os.environ.setdefault("LUMEN_DEEP_WORK_DAILY_SEARCH_CAP", "8")
os.environ.setdefault("LUMEN_OUTBOUND_MAX_NEW_PER_CYCLE", "3")
os.environ.setdefault("LUMEN_OUTBOUND_MAX_NEW_PER_DAY", "20")
os.environ.setdefault("LUMEN_OUTBOUND_MAX_FOLLOWUPS_PER_CYCLE", "4")
os.environ.setdefault("LUMEN_SOCIAL_CANARY_MAX_PER_CYCLE", "1")
os.environ.setdefault("LUMEN_SOCIAL_CANARY_MAX_PER_DAY", "4")
os.environ.setdefault("LUMEN_PUBLIC_BASE_URL", "https://lumen-zero-public.joseandresceol1-jac.workers.dev")
os.environ.setdefault("LUMEN_A2A_BASE_URL", "https://lumen-zero-a2a.joseandresceol1-jac.workers.dev")
os.environ.setdefault("LUMEN_COMMAND_CENTER_URL", "https://lumen-zero-dashboard.joseandresceol1-jac.workers.dev")
# Shadow intelligence only enriches already-permitted public catalog crawls; it adds no provider
# spend and cannot authorize outreach, payments or binding actions.
os.environ.setdefault("LUMEN_MARKET_INTELLIGENCE_SHADOW_ENABLED", "true")
os.environ.setdefault("PYTHONHASHSEED", "0")

# Install replacements before any production module captures app/scout/mail/watchdog/journal functions.
import d1_persistence_runtime  # noqa: F401,E402
import zero_cycle_journal_runtime  # noqa: F401,E402
# Signed Meta webhook payloads land in a dedicated D1 queue. Patch load_state now so every normal
# LUMEN Zero cycle can ingest them through the existing Instagram Operator before business logic.
import instagram_webhook_d1_bridge_runtime  # noqa: F401,E402
import zero_scout_runtime  # noqa: F401,E402
import zero_mail_runtime  # noqa: F401,E402
import zero_watchdog_runtime  # noqa: F401,E402
import zero_notification_runtime  # noqa: F401,E402
import zero_public_inquiry_bridge_runtime  # noqa: F401,E402
import zero_a2a_inbound_bridge_runtime  # noqa: F401,E402
# Install the editorial approval identity before importing the D1 control bridge. This makes the
# import hook deterministic under GitHub Actions instead of relying on Python's sitecustomize path.
# Transport-only URL/hosting changes can no longer invalidate a reviewed post, while any visible
# copy/media change still fails closed and requires a fresh human approval.
import instagram_approval_freeze_runtime  # noqa: F401,E402
import zero_instagram_control_bridge_runtime  # noqa: F401,E402

# Fold public Worker inquiries into the canonical service pipeline before the commercial cycle.
try:
    zero_public_inquiry_bridge_runtime.ingest_pending()
except Exception as exc:
    print({"zero_public_inquiry_bridge": {"status": "degraded_fail_open", "error": f"{type(exc).__name__}: {str(exc)[:300]}"}}, flush=True)

# Fold public A2A messages into the canonical research/verification pipeline. External-agent claims
# remain untrusted until the normal company/evidence gates verify them.
try:
    zero_a2a_inbound_bridge_runtime.ingest_pending()
except Exception as exc:
    print({"zero_a2a_inbound_bridge": {"status": "degraded_fail_open", "error": f"{type(exc).__name__}: {str(exc)[:300]}"}}, flush=True)

# Apply authenticated Instagram approve/reject commands before the production publishing control
# is imported. Every command is revalidated against the current immutable editorial fingerprint.
try:
    zero_instagram_control_bridge_runtime.consume_commands()
except Exception as exc:
    print({"zero_instagram_control_consume": {"status": "degraded_fail_open", "error": f"{type(exc).__name__}: {str(exc)[:300]}"}}, flush=True)

# One-time repair for the three exact posts José already approved in the Cloudflare console on
# 2026-09-21. The recovery module is fail-closed: exact IDs + processed explicit approvals + current
# editorial fingerprints only, no rejected/published override and no authority for future posts.
try:
    zero_instagram_control_bridge_runtime.recover_explicit_approvals_once()
except Exception as exc:
    print({"zero_instagram_approval_recovery": {"status": "degraded_fail_closed", "error": f"{type(exc).__name__}: {str(exc)[:300]}", "future_posts_authorized": False}}, flush=True)

# Preserve the exact non-persistence production bootstrap order previously used by Railway.
import search_budget_atomic_runtime  # noqa: F401,E402
# PostgreSQL-backed atomic claims fail closed once Railway/Postgres is gone. LUMEN Zero serializes
# production runs in GitHub Actions and persists the same counters in D1, so patch the claim layer
# without changing the existing hard daily cap or any verification/outreach gate.
import zero_search_budget_runtime  # noqa: F401,E402
# Public RSS discovery can surface forums/classifieds. Install a source-quality gate before any
# production layer captures Deep Work/Partner Network functions; rejected sources remain auditable
# but cannot become counterparties or consume commercial execution capacity.
import zero_discovery_quality_runtime  # noqa: F401,E402

# First-cash demand priority: reserve the beginning of each zero-cost cycle for one official/public
# procurement query before broader demand modules can consume the shared daily pool. The shared hard
# cap remains unchanged and the local public-procurement daily cap still applies. Disable a second
# procurement pass inside this same process so MAX_QUERIES_PER_TICK is preserved exactly.
try:
    import app as _lumen_pre  # noqa: E402
    import adaptive_search_budget_runtime as _adaptive_budget  # noqa: E402
    import public_procurement_hunter as _public_procurement  # noqa: E402
    if _lumen_pre.load_state():
        _adaptive_budget.apply_adaptive_search_budget(_lumen_pre.STATE)
        _pre_stats = _public_procurement.public_procurement_tick(_lumen_pre.STATE)
        _lumen_pre.STATE["zero_first_cash_procurement"] = {**dict(_pre_stats or {}), "pre_worker_priority": True}
        _lumen_pre.save_state()
        _public_procurement.MAX_QUERIES_PER_TICK = 0
        print({"zero_first_cash_procurement": _lumen_pre.STATE.get("zero_first_cash_procurement")}, flush=True)
except Exception as exc:
    print({"zero_first_cash_procurement": {"status": "degraded_fail_open", "error": f"{type(exc).__name__}: {str(exc)[:300]}"}}, flush=True)

# Railway history stays isolated in D1. This bridge processes only a tiny bounded batch each cycle,
# collects fresh same-domain public evidence, preserves legacy opt-outs/cooldowns, and may create a
# current candidate only after fresh category + role evidence. It never sets verified_company,
# verified_contact or outbound eligibility; the existing current gates below remain authoritative.
import legacy_reverification_runtime  # noqa: F401,E402
try:
    legacy_reverification_runtime.run_once()
except Exception as exc:
    print({"legacy_reverification_runtime": {"status": "degraded_fail_closed", "error": f"{type(exc).__name__}: {str(exc)[:300]}", "bridge_sets_verified_company": False, "bridge_sets_verified_contact": False, "bridge_sets_outbound_safe": False}}, flush=True)

import company_verification_scheduler_runtime  # noqa: F401,E402
import company_identity_quality_runtime  # noqa: F401,E402
import executive_secretary_log_bridge  # noqa: F401,E402
import revenue_os_v3_runtime  # noqa: F401,E402
import revenue_os_v31_alignment_runtime  # noqa: F401,E402
# Revenue OS alignment above runs during bootstrap. Re-evaluate the same strict gates when outbound
# actually executes so companies verified later in this cycle can receive the relevant paid-service
# offer instead of falling back to a generic introduction. Caps, cooldowns and verification stay intact.
import service_revenue_live_alignment_runtime  # noqa: F401,E402
import communication_greeting_fix_runtime  # noqa: F401,E402

# Development-mode Instagram apps cannot reliably receive public webhooks without Meta business
# verification. Poll the authorized account read-only each cycle as the zero-cost inbox fallback;
# messages are deduplicated and passed through the same Instagram Operator as signed webhooks.
try:
    import instagram_conversation_poller  # noqa: E402
    instagram_conversation_poller.poll_once()
except Exception as exc:
    print({"instagram_conversation_poller": {"status": "degraded_fail_open", "error": f"{type(exc).__name__}: {str(exc)[:300]}"}}, flush=True)

# Load and patch the Instagram publish control before worker_entry can import/use it. The previous
# lazy hook could only patch it after the outer worker import returned, which let the legacy
# fingerprint invalidate editorial-v2 approvals during startup. Fail closed here: publication must
# never proceed through an unpatched approval validator.
try:
    import instagram_publish_control  # noqa: F401,E402
    instagram_approval_freeze_runtime._patch_publish_control(instagram_publish_control)
    import instagram_approval_finalize_runtime  # noqa: F401,E402
    _instagram_finalize = instagram_approval_finalize_runtime.run_once()
    if str((_instagram_finalize or {}).get("status") or "").startswith("degraded"):
        raise RuntimeError(str((_instagram_finalize or {}).get("last_error") or "instagram_approval_finalize_failed"))
except Exception as exc:
    print({"instagram_approval_pre_worker_gate": {"status": "failed_closed", "error": f"{type(exc).__name__}: {str(exc)[:300]}", "future_posts_authorized": False}}, flush=True)
    raise

# Before spending another public-search query, re-evaluate exact buyer-bound evidence already in D1.
# This uses zero searches and may only promote a verified buyer when the existing 75-point demand
# threshold, strong-intent language, public URL and exact account lineage all remain satisfied.
try:
    import demand_inventory_reuse_runtime  # noqa: F401,E402
    demand_inventory_reuse_runtime.run_once()
except Exception as exc:
    print({"demand_inventory_reuse": {"status": "degraded_fail_closed", "error": f"{type(exc).__name__}: {str(exc)[:300]}", "searches_used": 0, "outbound_gate_relaxed": False}}, flush=True)

# Install the last revenue-lane guard after Conversion Autonomy has installed its normal hysteresis.
# A verified-buyer / zero-demand gap is an upstream prerequisite and may preempt stale lane memory;
# no search, evidence, outbound or binding-action gate is relaxed by this guard.
import revenue_lane_upstream_guard_runtime  # noqa: F401,E402

# worker_entry executes the complete production cycle at import time, matching the Railway start.
import worker_entry  # noqa: F401,E402

# Run the zero-cost owner-alert route once after the complete business cycle. This explicit pass is
# intentional: legacy modules may capture the original WhatsApp router before the adapter is loaded.
# Stable event keys plus owner_email_sent_at keep the fallback idempotent.
try:
    import app as lumen_app  # noqa: E402
    owner_notifications = zero_notification_runtime.zero_notification_router_tick(lumen_app.STATE)
    lumen_app.STATE["zero_owner_notifications"] = owner_notifications.get("owner_email_fallback", {})
    owner_persisted = lumen_app.save_state()
    print({"zero_owner_notifications": {**(owner_notifications.get("owner_email_fallback", {}) or {}), "persisted": bool(owner_persisted)}}, flush=True)
except Exception as exc:
    print({"zero_owner_notifications": {"status": "degraded_fail_open", "error": f"{type(exc).__name__}: {str(exc)[:300]}"}}, flush=True)

# Export the final post projection after the cycle so the secure Cloudflare console always shows
# the canonical approval/publication state rather than a stale pre-cycle snapshot.
try:
    zero_instagram_control_bridge_runtime.export_posts()
except Exception as exc:
    print({"zero_instagram_control_export": {"status": "degraded_fail_open", "error": f"{type(exc).__name__}: {str(exc)[:300]}"}}, flush=True)

# Last writer of every successful Zero cycle: reconcile cumulative business truth from primary D1
# evidence after all connectors and publishing have finished. Raw per-cycle module snapshots stay
# intact for diagnostics; the canonical projection is what dashboards/executive summaries should use.
try:
    import operational_truth_auditor_runtime  # noqa: F401,E402
    operational_truth_auditor_runtime.run_once()
except Exception as exc:
    print({"operational_truth_auditor": {"status": "degraded_fail_closed", "error": f"{type(exc).__name__}: {str(exc)[:300]}", "canonical_projection_written": False}}, flush=True)
