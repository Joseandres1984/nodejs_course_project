import { fromBase64url, publicKeyBytes, publicJwk } from "./keys.js";

export function signedMessage(purpose, fields) {
  return JSON.stringify(["LUMEN_AGENT_IDENTITY_V1", purpose, ...fields]);
}

export function freshTimestamp(value, now = Date.now()) {
  return Number.isSafeInteger(value) && Math.abs(now - value) <= 5 * 60 * 1000;
}

export function validNonce(value) {
  return typeof value === "string" && /^[a-zA-Z0-9_-]{22,128}$/.test(value);
}

export async function verifySignature(jwk, message, signature) {
  try {
    publicKeyBytes(jwk);
    const bytes = fromBase64url(signature);
    if (bytes.length !== 64) return false;
    const key = await crypto.subtle.importKey("jwk", publicJwk(jwk), { name: "Ed25519" }, false, ["verify"]);
    return await crypto.subtle.verify({ name: "Ed25519" }, key, bytes, new TextEncoder().encode(message));
  } catch {
    return false;
  }
}
