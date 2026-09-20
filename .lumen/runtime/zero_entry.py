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
os.environ.setdefault("PYTHONHASHSEED", "0")

# Install replacements before any production module captures app/scout/mail functions.
import d1_persistence_runtime  # noqa: F401,E402
import zero_scout_runtime  # noqa: F401,E402
import zero_mail_runtime  # noqa: F401,E402

# Preserve the exact non-persistence production bootstrap order previously used by Railway.
import search_budget_atomic_runtime  # noqa: F401,E402
# PostgreSQL-backed atomic claims fail closed once Railway/Postgres is gone. LUMEN Zero serializes
# production runs in GitHub Actions and persists the same counters in D1, so patch the claim layer
# without changing the existing hard daily cap or any verification/outreach gate.
import zero_search_budget_runtime  # noqa: F401,E402
import company_verification_scheduler_runtime  # noqa: F401,E402
import company_identity_quality_runtime  # noqa: F401,E402
import executive_secretary_log_bridge  # noqa: F401,E402
import revenue_os_v3_runtime  # noqa: F401,E402
import revenue_os_v31_alignment_runtime  # noqa: F401,E402
import communication_greeting_fix_runtime  # noqa: F401,E402

# worker_entry executes the complete production cycle at import time, matching the Railway start.
import worker_entry  # noqa: F401,E402
