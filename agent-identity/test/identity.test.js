import test from "node:test";
import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import { didFromPublicKey } from "../src/crypto/keys.js";
import { signedMessage, verifySignature, freshTimestamp, validNonce } from "../src/crypto/signatures.js";
import { computeReputation } from "../src/reputation/scoring.js";
import worker from "../src/index.js";

globalThis.crypto ??= webcrypto;
async function fixture() {
  const pair = await crypto.subtle.generateKey("Ed25519", true, ["sign", "verify"]);
  const publicKeyJwk = await crypto.subtle.exportKey("jwk", pair.publicKey);
  const did = await didFromPublicKey(publicKeyJwk);
  return { pair, publicKeyJwk, did };
}
function base64url(bytes) { return Buffer.from(bytes).toString("base64url"); }
async function signFixture(pair, message) {
  return base64url(await crypto.subtle.sign("Ed25519", pair.privateKey, new TextEncoder().encode(message)));
}
function envMock() {
  const ids = new Map(), nonces = new Set();
  const db = {
    prepare(sql) {
      return {
        bind(...args) {
          return {
            async first() {
              if (sql.startsWith("SELECT did, controller_did")) return ids.get(args[0]) ?? null;
              throw new Error("Unexpected SQL: " + sql);
            },
            async all() {
              if (sql.startsWith("SELECT protocol,event_type")) return { results: [] };
              return { results: [] };
            },
            async run() {
              if (sql.startsWith("INSERT OR IGNORE INTO request_nonces")) {
                const key = args[0] + "|" + args[1];
                if (nonces.has(key)) return { meta: { changes: 0 } };
                nonces.add(key); return { meta: { changes: 1 } };
              }
              if (sql.startsWith("INSERT OR IGNORE INTO agent_identities")) {
                if (ids.has(args[0])) return { meta: { changes: 0 } };
                ids.set(args[0], { did: args[0], controller_did: args[1], public_key: args[2],
                  created_at: args[4], updated_at: args[5], status: args[6], metadata: args[7] });
                return { meta: { changes: 1 } };
              }
              throw new Error("Unexpected SQL: " + sql);
            }
          };
        }
      };
    }
  };
  return { DB: db, IDENTITY_RATE_LIMITER: { limit: async () => ({ success: true }) } };
}

test("DID is deterministic, key-specific and rejects private JWKs", async () => {
  const a = await fixture(), b = await fixture();
  assert.match(a.did, /^did:agent:ed25519:[a-f0-9]{64}$/);
  assert.notEqual(a.did, b.did);
  assert.equal(a.did, await didFromPublicKey(a.publicKeyJwk));
  const privateJwk = await crypto.subtle.exportKey("jwk", a.pair.privateKey);
  await assert.rejects(didFromPublicKey(privateJwk));
});
test("signature binds payload; altered payload fails verification", async () => {
  const f = await fixture(), message = signedMessage("register", [f.did, f.did, f.publicKeyJwk.x, "LUMEN", "nonce", 1]);
  const sig = await signFixture(f.pair, message);
  assert.equal(await verifySignature(f.publicKeyJwk, message, sig), true);
  assert.equal(await verifySignature(f.publicKeyJwk, message + "!", sig), false);
  assert.equal(await verifySignature(f.publicKeyJwk, message, "!"), false);
});
test("timestamps and nonces enforce freshness and shape", () => {
  assert.equal(freshTimestamp(Date.now()), true);
  assert.equal(freshTimestamp(Date.now() + 3600000), false);
  assert.equal(freshTimestamp(Number.NaN), false);
  assert.equal(validNonce("0123456789012345678901"), true);
  assert.equal(validNonce("short"), false);
});
test("decay favors recent evidence and a single event does not imply perfect trust", () => {
  const now = Date.now();
  const old = computeReputation([{ protocol: "a2a", event_type: "positive", weight: 1, timestamp: now - 180 * 86400000 }], now);
  const recent = computeReputation([{ protocol: "a2a", event_type: "positive", weight: 1, timestamp: now }], now);
  assert.ok(recent.globalScore > old.globalScore);
  assert.ok(recent.globalScore < 100);
  assert.equal(computeReputation([], now).globalScore, 50);
});
test("self-registration requires a signed public-key-derived DID and blocks nonce replay", async () => {
  const f = await fixture(), env = envMock();
  const nonce = base64url(crypto.getRandomValues(new Uint8Array(24)));
  const timestamp = Date.now(), name = "LUMEN";
  const msg = signedMessage("register", [f.did, f.did, f.publicKeyJwk.x, name, nonce, timestamp]);
  const signature = await signFixture(f.pair, msg);
  const body = { did: f.did, controllerDid: f.did, publicKeyJwk: f.publicKeyJwk, metadata: { name },
    proof: { nonce, timestamp, signature } };
  const url = "https://identity.example/v1/identities";
  const request = () => new Request(url, { method: "POST", body: JSON.stringify(body) });
  let response = await worker.fetch(request(), env);
  assert.equal(response.status, 201);
  response = await worker.fetch(request(), env);
  assert.equal(response.status, 409);
  response = await worker.fetch(new Request("https://identity.example/v1/did/" + f.did), env);
  assert.equal(response.status, 200);
  const document = await response.json();
  assert.equal(document.id, f.did);
  assert.equal(document.verificationMethod[0].publicKeyJwk.x, f.publicKeyJwk.x);
  response = await worker.fetch(new Request("https://identity.example/v1/compatibility/x402/" + f.did), env);
  assert.equal((await response.json()).paymentVerified, false);
});
test("attestation is disabled without an admin secret", async () => {
  const env = envMock();
  const res = await worker.fetch(new Request("https://identity.example/v1/reputation/events",
    { method: "POST", body: "{}" }), env);
  assert.equal(res.status, 403);
});
test("write requests fail closed without rate limit binding", async () => {
  const f = await fixture(), env = envMock(); delete env.IDENTITY_RATE_LIMITER;
  const nonce = "012345678901234567890123", timestamp = Date.now();
  const signature = await signFixture(f.pair, signedMessage("register", [f.did, f.did, f.publicKeyJwk.x, "LUMEN", nonce, timestamp]));
  const res = await worker.fetch(new Request("https://identity.example/v1/identities", {
    method: "POST", body: JSON.stringify({ did: f.did, controllerDid: f.did, publicKeyJwk: f.publicKeyJwk, metadata: {name:"LUMEN"},
      proof: {nonce,timestamp,signature} })
  }), env);
  assert.equal(res.status, 503);
});
