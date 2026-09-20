# LUMEN Zero

Zero-cost runtime path for LUMEN. The existing `lumen-deploy` branch remains the rollback baseline until an end-to-end D1 cycle is verified.

## Runtime

- Scheduler/compute: GitHub Actions (`.github/workflows/lumen-zero.yml` on the default branch)
- Business code: `lumen-zero` branch
- Persistence: Cloudflare D1 via `d1_persistence_runtime.py`
- Search discovery: public RSS provider via `zero_scout_runtime.py`; existing company verification and catalog crawler remain responsible for evidence validation
- Bootstrap: `zero_entry.py`, preserving the production Revenue OS bootstrap order

## Required GitHub Actions secrets

Only these three are mandatory for the business cycle to start:

- `LUMEN_D1_ACCOUNT_ID`
- `LUMEN_D1_DATABASE_ID`
- `LUMEN_D1_API_TOKEN` (Cloudflare token scoped to D1 read/write for the target account)

Communication secrets are optional and are already referenced by the workflow: Brevo/Resend, IMAP, Instagram, WhatsApp and Mercado Pago. If absent, their existing runtime gates keep those lanes unavailable.

## D1 schema

No manual schema creation is required. On first successful cycle the adapter creates `lumen_state_manifest` and `lumen_state_chunks`, then stores the existing LUMEN JSON state compressed with zlib, Base64 encoded and chunked. SHA-256 is verified on every load.

## Legacy-state rescue

If the old PostgreSQL/Supabase database can still be read once, run `migrate_postgres_state_to_d1.py` with `LEGACY_DATABASE_URL` plus the three D1 variables. It reads only `lumen_state/global` and writes that state to D1.

## Cost policy

`zero_entry.py` forces `LUMEN_ZERO_COST_MODE=true` and replaces paid search-provider access. Search/outbound caps are bounded so the system prioritizes evidence reuse and useful work instead of burning public-source capacity.
