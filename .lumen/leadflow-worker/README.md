# LUMEN LeadFlow AI — independent MVP

Status: functional demo code, not a live deployment. No customer data storage, WhatsApp, email, AI inference, autonomous outreach, payments or revenue in this version.

## What is built
- Responsive Spanish landing page for an inmobiliaria offer.
- Interactive rental-search form using fictional details, without name, email or telephone.
- POST /api/demo returns a deterministic follow-up priority (high, medium, exploratory), explanation and suggested action.
- GET /health states demo_only and no verified revenue.
- POST /api/leads always returns HTTP 503. It is intentionally impossible to collect real leads at this stage.
- No changes to production x402, A2A, public Worker, Travel or Instagram.

## Verify
Run from repository root using Node 20+:
  node --check .lumen/leadflow-worker/worker.mjs
  node --check .lumen/leadflow-worker/core.mjs
  node --check .lumen/leadflow-worker/public/app.js
  node --test .lumen/leadflow-worker/test/leadflow.test.mjs

Run a local visual preview from .lumen/leadflow-worker:
  npx wrangler@4 dev

Example test payload for POST /api/demo with JSON content type:
  {"zona":"Zárate","presupuesto":600000,"ambientes":2,"urgencia":"este_mes"}

## Commercial scope
Proposed starter pricing: USD 390 one-time setup and USD 99 monthly maintenance, exclusive of third-party tools and messaging. These are *offers*, not verified sales or profit.

## Safe activation checklist (separate future change)
1. Choose the first client or pilot and document real deliverables.
2. Add explicit privacy notice, informed opt-in, lawful messaging and clear deletion/retention policy.
3. Provision a separate Cloudflare D1 database, not the existing lumen-zero database.
4. Build a real intake endpoint guarded by Turnstile and rate limiting, with authenticated per-client data access and tested deletion.
5. Add a human-reviewed notification channel and traceable consent, then staging tests.
6. Verify security, cost ceiling, monitoring and rollback before deploying to a public production URL.
7. Do not announce success until a paying client, actual money receipt and verified lead conversion evidence exist.

No Railway. No subscription purchases. No automatic deploy. No mass outreach.
