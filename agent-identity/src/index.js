import { didFromPublicKey, publicJwk } from "./crypto/keys.js";
import { verifySignature, signedMessage, freshTimestamp, validNonce } from "./crypto/signatures.js";
import { computeReputation } from "./reputation/scoring.js";

const VALID_PROTOCOLS = new Set(["a2a", "mcp", "ucp", "x402"]);
const VALID_EVENTS = new Set(["positive", "negative", "neutral"]);
const DID_FORMAT = /^did:agent:ed25519:[0-9a-f]{64}$/;
const json = (body, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store",
    "x-content-type-options": "nosniff" }
});
class ApiError extends Error { constructor(status, message) { super(message); this.status = status; } }
function requireDid(did) {
  if (typeof did !== "string" || !DID_FORMAT.test(did)) throw new ApiError(400, "Invalid experimental DID");
  return did;
}
async function readBody(request) {
  const declared = Number(request.headers.get("content-length") ?? 0);
  if (declared > 16384) throw new ApiError(413, "Body too large");
  const raw = await request.text();
  if (raw.length > 16384) throw new ApiError(413, "Body too large");
  try { const value = JSON.parse(raw); if (!value || typeof value !== "object" || Array.isArray(value)) throw 0; return value; }
  catch { throw new ApiError(400, "Invalid JSON object"); }
}
function database(env) {
  if (!env.DB?.prepare) throw new ApiError(503, "D1 binding is not configured");
  return env.DB;
}
async function rateLimit(request, env, operation, subject = "unknown") {
  // Rate limiting is a guard, not an accounting or payment security mechanism.
  if (!env.IDENTITY_RATE_LIMITER?.limit) throw new ApiError(503, "Rate limiting is not configured");
  const client = request.headers.get("cf-connecting-ip") || "local";
  const result = await env.IDENTITY_RATE_LIMITER.limit({ key: operation + ":" + client + ":" + String(subject).slice(0, 90) });
  if (!result.success) throw new ApiError(429, "Rate limit exceeded");
}
async function activeIdentity(db, did) {
  return db.prepare("SELECT did, controller_did, public_key, status, metadata, created_at, updated_at FROM agent_identities WHERE did = ?")
    .bind(did).first();
}
function didDocument(row) {
  const key = JSON.parse(row.public_key);
  const vm = row.did + "#key-1";
  return { id: row.did, controller: row.controller_did,
    verificationMethod: [{ id: vm, type: "JsonWebKey2020", controller: row.did, publicKeyJwk: key }],
    authentication: [vm], assertionMethod: [vm],
    metadata: { ...JSON.parse(row.metadata), createdAt: row.created_at, updatedAt: row.updated_at } };
}
async function useNonce(db, did, nonce, timestamp) {
  const result = await db.prepare("INSERT OR IGNORE INTO request_nonces (did,nonce,expires_at) VALUES (?,?,?)")
    .bind(did, nonce, timestamp + 300000).run();
  if (result.meta?.changes !== 1) throw new ApiError(409, "Reused nonce");
}
async function scoreFor(db, did, now = Date.now()) {
  const records = await db.prepare("SELECT protocol,event_type,weight,timestamp FROM reputation_events WHERE did = ? ORDER BY timestamp DESC LIMIT 501")
    .bind(did).all();
  const events = records.results ?? [];
  if (events.length > 500) throw new ApiError(503, "Reputation history exceeds v1 processing limit");
  return computeReputation(events, now);
}
async function registerIdentity(request, env) {
  const db = database(env), body = await readBody(request);
  const { did, controllerDid, publicKeyJwk, metadata = {}, proof } = body;
  requireDid(did);
  if (controllerDid !== did) throw new ApiError(422, "Delegated controller is not supported in v1");
  if (!metadata || typeof metadata !== "object" || Array.isArray(metadata) ||
      typeof metadata.name !== "string" || metadata.name.length > 100 ||
      Object.keys(metadata).some(k => k !== "name")) throw new ApiError(422, "Only metadata.name is supported");
  let key;
  try { key = publicJwk(publicKeyJwk); if (await didFromPublicKey(key) !== did) throw new Error(); }
  catch { throw new ApiError(422, "DID does not match public key"); }
  if (!proof || !freshTimestamp(proof.timestamp) || !validNonce(proof.nonce)) throw new ApiError(422, "Invalid signed proof freshness or nonce");
  await rateLimit(request, env, "register", did);
  const message = signedMessage("register", [did, controllerDid, key.x, metadata.name, proof.nonce, proof.timestamp]);
  if (!await verifySignature(key, message, proof.signature)) throw new ApiError(401, "Invalid proof of key possession");
  await useNonce(db, did, proof.nonce, proof.timestamp);
  const now = Date.now();
  const inserted = await db.prepare(
    "INSERT OR IGNORE INTO agent_identities (did, controller_did, public_key, key_type, created_at, updated_at, status, metadata) VALUES (?,?,?,?,?,?,?,?)")
    .bind(did, controllerDid, JSON.stringify(key), "ed25519", now, now, "active", JSON.stringify(metadata)).run();
  if (inserted.meta?.changes !== 1) throw new ApiError(409, "DID is already registered");
  return json({ did, registered: true, proofOfPossession: true, protocolVerified: false }, 201);
}
async function addReputationEvent(request, env) {
  const db = database(env);
  const token = request.headers.get("authorization");
  if (!env.EVENT_ADMIN_TOKEN || token !== "Bearer " + env.EVENT_ADMIN_TOKEN) throw new ApiError(403, "Administrator attestation required");
  const e = await readBody(request);
  const { id, did, sourceDid, protocol, eventType, weight, evidenceRef, proof } = e;
  requireDid(did); requireDid(sourceDid);
  if (did === sourceDid || !VALID_PROTOCOLS.has(protocol) || !VALID_EVENTS.has(eventType) ||
      !Number.isFinite(weight) || weight <= 0 || weight > 1 ||
      typeof id !== "string" || !/^[a-zA-Z0-9_-]{16,100}$/.test(id) ||
      typeof evidenceRef !== "string" || evidenceRef.length < 8 || evidenceRef.length > 300)
    throw new ApiError(422, "Invalid event payload");
  // Financial reputation must wait for independent settlement verification.
  if (protocol === "x402" && eventType !== "neutral") throw new ApiError(422, "Payment evidence verification is not implemented");
  if (!proof || !freshTimestamp(proof.timestamp) || !validNonce(proof.nonce)) throw new ApiError(422, "Invalid signed proof");
  const trusted = String(env.TRUSTED_REPORTER_DIDS || "").split(",").map(s => s.trim()).filter(Boolean);
  if (!trusted.includes(sourceDid)) throw new ApiError(403, "Reporter is not allowlisted");
  await rateLimit(request, env, "attestation", sourceDid);
  const subject = await activeIdentity(db, did);
  const reporter = await activeIdentity(db, sourceDid);
  if (!subject || subject.status !== "active" || !reporter || reporter.status !== "active")
    throw new ApiError(422, "Both DIDs must be active");
  const message = signedMessage("reputation", [id, did, sourceDid, protocol, eventType, weight, evidenceRef, proof.nonce, proof.timestamp]);
  if (!await verifySignature(JSON.parse(reporter.public_key), message, proof.signature))
    throw new ApiError(401, "Invalid reporter signature");
  await useNonce(db, sourceDid, proof.nonce, proof.timestamp);
  const inserted = await db.prepare(
    "INSERT OR IGNORE INTO reputation_events (id,did,protocol,event_type,weight,description,metadata,source_did,signature,timestamp) VALUES (?,?,?,?,?,?,?,?,?,?)")
    .bind(id, did, protocol, eventType, weight, "Admin-attested event (not payment proof)", JSON.stringify({ evidenceRef }),
      sourceDid, proof.signature, proof.timestamp).run();
  if (inserted.meta?.changes !== 1) throw new ApiError(409, "Duplicate event id");
  return json({ id, recorded: true, paymentVerified: false }, 201);
}
async function publicDid(db, did) {
  requireDid(did);
  const row = await activeIdentity(db, did);
  if (!row || row.status !== "active") throw new ApiError(404, "Active DID not found");
  return row;
}
async function handle(request, env) {
  const url = new URL(request.url), path = url.pathname;
  if (request.method === "GET" && path === "/health")
    return json({ service: "lumen-agent-identity", status: "alive", databaseChecked: false });
  if (request.method === "POST" && path === "/v1/identities") return registerIdentity(request, env);
  if (request.method === "POST" && path === "/v1/reputation/events") return addReputationEvent(request, env);
  if (request.method !== "GET") return json({ error: "Not found" }, 404);
  const match = path.match(/^\/v1\/(did|reputation|compatibility\/ucp|compatibility\/x402)\/(.+)$/);
  if (!match) return json({ error: "Not found" }, 404);
  let did;
  try { did = decodeURIComponent(match[2]); } catch { throw new ApiError(400, "Invalid DID encoding"); }
  const db = database(env), row = await publicDid(db, did);
  if (match[1] === "did") return json(didDocument(row));
  const reputation = await scoreFor(db, did);
  if (match[1] === "reputation") return json({ did, ...reputation, evidence: "admin-attested, not payment-confirmed" });
  const document = didDocument(row);
  if (match[1] === "compatibility/ucp")
    return json({ identityExtension: { did, publicKeyJwk: document.verificationMethod[0].publicKeyJwk, reputation },
      isUcpMerchantProfile: false, note: "Not a UCP checkout, merchant credential, or profile" });
  return json({ did, publicKeyJwk: document.verificationMethod[0].publicKeyJwk,
    reputation, identityVerified: true, paymentVerified: false,
    note: "Informational x402 identity extension; no verification or settlement performed" });
}
export default {
  async fetch(request, env) {
    try { return await handle(request, env); }
    catch (e) {
      if (e instanceof ApiError) return json({ error: e.message }, e.status);
      console.error("identity_error", e?.name || "Error");
      return json({ error: "Internal error" }, 500);
    }
  },
  async scheduled(_event, env) {
    const db = database(env), now = Date.now();
    let after = "";
    // Bounded pages avoid loading the entire identity table into one Worker request.
    while (true) {
      const page = await db.prepare("SELECT did FROM agent_identities WHERE did > ? ORDER BY did LIMIT 50").bind(after).all();
      const rows = page.results ?? [];
      for (const row of rows) {
        try {
          const score = await scoreFor(db, row.did, now);
          await db.prepare(`INSERT INTO reputation_scores
            (did,global_score,protocol_scores,category_scores,total_interactions,success_rate,last_computed,decay_factor)
            VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(did) DO UPDATE SET
            global_score=excluded.global_score,protocol_scores=excluded.protocol_scores,
            total_interactions=excluded.total_interactions,success_rate=excluded.success_rate,
            last_computed=excluded.last_computed,decay_factor=excluded.decay_factor`)
            .bind(row.did, score.globalScore, JSON.stringify(score.protocolScores), "{}", score.totalInteractions,
              score.successRate, now, score.decayFactor).run();
        } catch (e) { console.error("reputation_recompute_failed", row.did, e?.name || "Error"); }
      }
      if (rows.length < 50) break;
      after = rows[rows.length - 1].did;
    }
    await db.prepare("DELETE FROM request_nonces WHERE expires_at < ?").bind(now - 300000).run();
  }
};
