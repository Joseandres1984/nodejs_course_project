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

# Run the complete Meta-LUMEN + production worker first.
import worker_meta  # noqa: F401,E402

from app import STATE, load_state
from cycle_journal import record_cycle


# Persist one compact, queryable audit row only after the business cycle completed.
# The journal uses its own Postgres table so the global LUMEN state does not grow without bound.
load_state()
journal = record_cycle(STATE, source="worker_complete")
print({"cycle_journal": {k: v for k, v in journal.items() if k != "entry"}}, flush=True)
