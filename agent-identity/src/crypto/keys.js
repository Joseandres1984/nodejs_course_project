/**
 * Experimental LUMEN-local DID method, NOT a generally registered DID method.
 * DID is self-certifying: SHA-256 over the 32 raw public-key bytes.
 */
export function fromBase64url(value) {
  if (typeof value !== "string" || !/^[A-Za-z0-9_-]+$/.test(value)) {
    throw new Error("Invalid base64url");
  }
  const padded = value.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(value.length / 4) * 4, "=");
  return Uint8Array.from(atob(padded), char => char.charCodeAt(0));
}

export function publicKeyBytes(jwk) {
  if (!jwk || jwk.kty !== "OKP" || jwk.crv !== "Ed25519" || typeof jwk.x !== "string" || jwk.d !== undefined) {
    throw new Error("A public Ed25519 JWK is required");
  }
  const bytes = fromBase64url(jwk.x);
  if (bytes.length !== 32) throw new Error("Invalid Ed25519 public key length");
  return bytes;
}

export async function didFromPublicKey(jwk) {
  const bytes = publicKeyBytes(jwk);
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
  return "did:agent:ed25519:" + [...digest].map(b => b.toString(16).padStart(2, "0")).join("");
}

export function publicJwk(jwk) {
  publicKeyBytes(jwk);
  return { kty: "OKP", crv: "Ed25519", x: jwk.x };
}
