# LUMEN Agent Identity (experimental, isolated)

A bounded, proof-of-possession identity and attested-reputation sidecar for Cloudflare Workers + D1. This is **not** a payment processor or a public-standard DID method implementation.

## Delivered scope
- Self-certifying internal `did:agent:ed25519:<sha256-of-public-key-bytes>` identifiers; Ed25519 public-key proof verified with Web Crypto, private keys never received or stored.
- `POST /v1/identities`: register an active DID once, requiring a fresh signed request and a unique nonce. Self controller only; signed fields include DID, controller, public key, name, nonce, timestamp.
- `GET /v1/did/:did`: resolve an existing active identity (not a business/legal identity guarantee).
- `GET /v1/reputation/:did`: calculate current internal score (neutral prior 50, 90-day half-life).
- `POST /v1/reputation/events`: only admin-token-authorized, allowlisted, signed reporter attestations; rejects x402 positive/negative events until there is an independently validated settlement ingestion path.
- `GET /v1/compatibility/{ucp,x402}/:did`: informational identity extensions only, **not** full UCP compliance, payment proofs, payment obligations or settlements.
- Daily cron recalculates small-history scores and expires nonces. Bounded per-DID event read (500); oversize history fails closed.
- Unit/security tests and independent CI. No production LUMEN Worker code, financial permissions, or communication flows modified.

## Design boundaries
**No transactions, payment headers, payment-signature acceptance, settlement calls, or spending.**
UCP profiles must follow official `/.well-known/ucp` capability discovery and cannot be claimed from an identity lookup alone. x402 v2 uses official `PAYMENT-REQUIRED`, `PAYMENT-SIGNATURE`, facilitator verification/settlement and independent confirmation; this project deliberately does not implement those payments.
The DID namespace here is experimental and local, not globally specified; do not advertise cross-vendor DID interoperability.

## Provisioning (manual, not executed in this PR)
1. Create an **isolated** Cloudflare D1 database: `npx wrangler d1 create agent-identity-db`.
2. Replace `REPLACE_WITH_REAL_D1_DATABASE_ID` in `wrangler.toml` with its actual ID.
3. Apply schema in isolated environment: `npx wrangler d1 execute agent-identity-db --file=./schema.sql --remote` from this directory.
4. Create a long random `EVENT_ADMIN_TOKEN` with `npx wrangler secret put EVENT_ADMIN_TOKEN`; **do not commit secrets**.
5. Only after independently verifying the issuer's control of its public key, set a list of permitted reporter DIDs in `TRUSTED_REPORTER_DIDS`; empty by default.
6. `node --test` locally, then `npx wrangler deploy` only after configuring real account bindings and reviewing deployment permissions.
7. Test actual DID registration and `GET /v1/did/<did>` using a new keypair generated and kept outside the Worker.

The provided URL `agent-identity.your-subdomain.workers.dev` and the DID `did:agent:abcdef123456` are **examples**, not live infrastructure.

### Registration signature format
Use a 32-byte Ed25519 public JWK: `{kty:"OKP", crv:"Ed25519", x:"<base64url>"}`.
Compute DID as `did:agent:ed25519:` + lowercase hex SHA-256 of the decoded 32 public key bytes.
Generate a cryptographically random `nonce` (base64url, 22-128 characters) and a `timestamp` (Unix milliseconds, within +/- 5 minutes).
Sign the UTF-8 bytes of:

```js
JSON.stringify(["LUMEN_AGENT_IDENTITY_V1", "register", did, did, publicKeyJwk.x, metadata.name, nonce, timestamp])
```

The proof's `signature` is base64url Ed25519. HTTP request:

```json
{
  "did": "<derived-did>",
  "controllerDid": "<same-derived-did>",
  "publicKeyJwk": {"kty":"OKP","crv":"Ed25519","x":"<base64url>"},
  "metadata": {"name":"LUMEN"},
  "proof": {"nonce":"<random-base64url>", "timestamp": 0, "signature":"<base64url-signature>"}
}
```

Reputation event signatures follow `signedMessage("reputation", [id,did,sourceDid,protocol,eventType,weight,evidenceRef,nonce,timestamp])` and require both the admin secret and a trusted reporter DID. These are **admin attestations**, not independently validated financial facts.

## Security notes and remaining blockers
- The Cloudflare Worker Rate Limiting API is not a global exact counter; use Cloudflare WAF/rules for broader abuse protections. Writes fail closed if the binding is absent.
- Admin tokens require Cloudflare Secrets; production hardening should use stronger service-to-service authentication, issuer credentials, key revocation/recovery and independent audits.
- Signed, allowlisted reputation assertions still require manual evidence review; they are not proofs of merchant legitimacy.
- Scoring requires a durable event verification pipeline, stronger anti-Sybil measures, pagination/batching beyond 500 events, and data retention rules before public ratings.
- Full UCP, MCP and A2A adapters, DID method publication, ZK, and x402 facilitator settlement verification are **deferred**, not implemented here.
- Never allow registration alone to set `protocol_registrations.verified=1`. All new registrations start unverified.

## Local checks
```bash
cd agent-identity
node --test
```
CI also checks schema idempotency with SQLite. Production deployment and live Cloudflare credentials are not part of this PR.
