const APP_ID = "43575";
const AUTHORIZE_URL = `https://www.tiendanube.com/apps/${APP_ID}/authorize`;
const TOKEN_URL = "https://www.tiendanube.com/apps/authorize/token";

function clean(value, limit = 3000) {
  return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit);
}

function bytesToBase64(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_tiendanube_connections (store_id TEXT PRIMARY KEY,status TEXT NOT NULL,scope TEXT,access_token_cipher TEXT NOT NULL,access_token_iv TEXT NOT NULL,installed_at TEXT NOT NULL,updated_at TEXT NOT NULL,last_verified_at TEXT,last_error TEXT,metadata_json TEXT)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_tiendanube_oauth_states (state TEXT PRIMARY KEY,created_at TEXT NOT NULL,expires_at TEXT NOT NULL,used_at TEXT)")
  ]);
  return true;
}

function randomState() {
  const bytes = crypto.getRandomValues(new Uint8Array(24));
  return [...bytes].map(b => b.toString(16).padStart(2, "0")).join("");
}

async function encryptionKey(env) {
  const secret = clean(env?.TIENDANUBE_CLIENT_SECRET, 1000);
  const admin = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 1000);
  if (!secret || !admin) throw new Error("missing_encryption_seed");
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(`${admin}:${secret}`));
  return crypto.subtle.importKey("raw", digest, { name: "AES-GCM" }, false, ["encrypt"]);
}

async function encryptToken(env, token) {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const key = await encryptionKey(env);
  const cipher = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, new TextEncoder().encode(token));
  return { cipher: bytesToBase64(new Uint8Array(cipher)), iv: bytesToBase64(iv) };
}

function htmlPage(title, body) {
  return new Response(`<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${title}</title></head><body style="font-family:system-ui;max-width:720px;margin:60px auto;padding:24px;line-height:1.45"><h1>${title}</h1>${body}</body></html>`, { headers: { "content-type": "text/html; charset=utf-8" } });
}

async function beginInstall(env) {
  if (!env?.TIENDANUBE_CLIENT_SECRET) {
    return htmlPage("LUMEN Commerce", "<p>Falta configurar de forma segura el Client Secret de Tiendanube. No pegues esa clave en una URL ni en el chat.</p>");
  }
  if (!env?.DB) return Response.json({ ok: false, error: "missing_db" }, { status: 503 });
  await ensureSchema(env);
  const state = randomState();
  const createdAt = new Date();
  const expiresAt = new Date(createdAt.getTime() + 10 * 60 * 1000);
  await env.DB.prepare("INSERT INTO lumen_tiendanube_oauth_states(state,created_at,expires_at) VALUES(?,?,?)")
    .bind(state, createdAt.toISOString(), expiresAt.toISOString()).run();
  return Response.redirect(`${AUTHORIZE_URL}?state=${encodeURIComponent(state)}`, 302);
}

async function completeInstall(url, env) {
  const code = clean(url.searchParams.get("code"), 1000);
  const state = clean(url.searchParams.get("state"), 500);
  const clientSecret = clean(env?.TIENDANUBE_CLIENT_SECRET, 1000);
  if (!clientSecret) return htmlPage("LUMEN Commerce", "<p>Falta configurar el Client Secret de Tiendanube.</p>");
  if (!code || !state) return Response.json({ ok: false, error: "missing_oauth_parameters" }, { status: 400 });
  if (!env?.DB) return Response.json({ ok: false, error: "missing_db" }, { status: 503 });
  await ensureSchema(env);
  const stateRow = await env.DB.prepare("SELECT * FROM lumen_tiendanube_oauth_states WHERE state=?").bind(state).first();
  if (!stateRow || stateRow.used_at || new Date(stateRow.expires_at).getTime() < Date.now()) {
    return Response.json({ ok: false, error: "invalid_or_expired_oauth_state" }, { status: 400 });
  }

  const response = await fetch(TOKEN_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ client_id: APP_ID, client_secret: clientSecret, grant_type: "authorization_code", code })
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || !data?.access_token || !data?.user_id) {
    return Response.json({ ok: false, error: `oauth_exchange_failed_${response.status}` }, { status: 400 });
  }

  const encrypted = await encryptToken(env, data.access_token);
  const now = new Date().toISOString();
  await env.DB.batch([
    env.DB.prepare("UPDATE lumen_tiendanube_oauth_states SET used_at=? WHERE state=?").bind(now, state),
    env.DB.prepare("INSERT INTO lumen_tiendanube_connections(store_id,status,scope,access_token_cipher,access_token_iv,installed_at,updated_at,metadata_json) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(store_id) DO UPDATE SET status='ACTIVE',scope=excluded.scope,access_token_cipher=excluded.access_token_cipher,access_token_iv=excluded.access_token_iv,updated_at=excluded.updated_at,last_error=NULL,metadata_json=excluded.metadata_json")
      .bind(String(data.user_id), "ACTIVE", clean(data.scope, 1000), encrypted.cipher, encrypted.iv, now, now, JSON.stringify({ version: "1.0-tiendanube-oneclick-install", appId: APP_ID, tokenType: data.token_type || "bearer" }))
  ]);

  return htmlPage("Tiendanube conectada a LUMEN", `<p>La tienda <strong>${String(data.user_id)}</strong> quedó autenticada correctamente.</p><p>Ya podés cerrar esta ventana.</p>`);
}

export async function handleTiendanubeInstall(request, env) {
  const url = new URL(request.url);
  if (url.pathname === "/tiendanube/install" && request.method === "GET") return beginInstall(env);
  if (url.pathname === "/tiendanube/oauth/callback" && request.method === "GET") return completeInstall(url, env);
  if (url.pathname === "/tiendanube/install/policy" && request.method === "GET") {
    return Response.json({
      ok: true,
      version: "1.0-tiendanube-oneclick-install",
      appId: APP_ID,
      oauth: "authorization_code",
      csrfStateRequired: true,
      tokenStoredEncrypted: true,
      clientSecretStoredInCode: false,
      autonomousPublishing: false,
      autonomousPurchasing: false,
      autonomousSpendUsd: 0
    });
  }
  return null;
}
