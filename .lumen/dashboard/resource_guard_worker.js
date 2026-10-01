import app from "./teaching_mode_worker.js";

const USER_DEFAULT = "socio";

function constantTimeEqual(a, b) {
  a = String(a || "");
  b = String(b || "");
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function authOK(request, env) {
  const password = String(env.LUMEN_DASHBOARD_PASSWORD || "");
  if (!password) return null;
  const header = request.headers.get("Authorization") || "";
  if (!header.startsWith("Basic ")) return false;
  try {
    const decoded = atob(header.slice(6));
    const i = decoded.indexOf(":");
    if (i < 0) return false;
    return constantTimeEqual(decoded.slice(0, i), String(env.LUMEN_DASHBOARD_USER || USER_DEFAULT))
      && constantTimeEqual(decoded.slice(i + 1), password);
  } catch {
    return false;
  }
}

function unauthorized() {
  return new Response("LUMEN · acceso restringido", {
    status: 401,
    headers: {
      "WWW-Authenticate": 'Basic realm="LUMEN Centro de Comando", charset="UTF-8"',
      "Cache-Control": "no-store",
    },
  });
}

function locked() {
  return new Response("LUMEN dashboard todavía no tiene contraseña configurada.", {
    status: 503,
    headers: { "Cache-Control": "no-store" },
  });
}

function protect(request, env) {
  const auth = authOK(request, env);
  if (auth === null) return locked();
  if (!auth) return unauthorized();
  return null;
}

function esc(value) {
  return String(value ?? "").replace(/[&<>\"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

async function hmacHex(secret, value) {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(String(secret || "")),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(value));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function ensureSchema(env) {
  await env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_instagram_control_posts (job_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, audience TEXT, campaign_id TEXT, caption TEXT, image_url TEXT, state_status TEXT, approval_status TEXT, last_error TEXT, created_at TEXT, updated_at TEXT NOT NULL)").run();
  await env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_instagram_control_commands (id TEXT PRIMARY KEY, job_id TEXT NOT NULL, fingerprint TEXT NOT NULL, action TEXT NOT NULL, created_at TEXT NOT NULL, processed INTEGER NOT NULL DEFAULT 0, processed_at TEXT, result TEXT)").run();
  await env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_instagram_control_commands_pending ON lumen_instagram_control_commands(processed,created_at)").run();
  await env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_instagram_control_commands_identity ON lumen_instagram_control_commands(job_id,fingerprint,action,processed)").run();
}

function label(row) {
  const state = String(row.state_status || "").toUpperCase();
  const approval = String(row.approval_status || "").toUpperCase();
  if (state === "PUBLISHED" || approval === "PUBLISHED") return "Publicado";
  if (approval === "APPROVED") return "Aprobado · publicación en curso";
  if (approval === "APPROVED_WAITING_CONNECTOR") return "Aprobado · esperando conector";
  if (approval === "APPROVED_RETRY") return "Aprobado · reintento automático";
  if (approval === "DUPLICATE_BLOCKED_REMOTE" || approval === "DUPLICATE_BLOCKED") return "Bloqueado · contenido duplicado";
  if (approval === "REJECTED") return "Descartado";
  if (approval === "EXPIRED") return "Aprobación vencida";
  return "Listo para aprobación";
}

async function renderInstagramControl(request, env) {
  const denied = protect(request, env);
  if (denied) return denied;
  await ensureSchema(env);
  const [postsResult, commandsResult] = await Promise.all([
    env.DB.prepare("SELECT job_id,fingerprint,audience,campaign_id,caption,image_url,state_status,approval_status,last_error,created_at,updated_at FROM lumen_instagram_control_posts ORDER BY updated_at DESC LIMIT 30").all(),
    env.DB.prepare("SELECT id,job_id,action,created_at,processed,processed_at,result FROM lumen_instagram_control_commands ORDER BY created_at DESC LIMIT 20").all(),
  ]);
  const posts = postsResult.results || [];
  const commands = commandsResult.results || [];
  const secret = String(env.LUMEN_DASHBOARD_PASSWORD || "");
  const cards = [];
  for (const row of posts) {
    const state = String(row.state_status || "").toUpperCase();
    const approval = String(row.approval_status || "").toUpperCase();
    const done = state === "PUBLISHED" || ["PUBLISHED", "REJECTED", "DUPLICATE_BLOCKED_REMOTE", "DUPLICATE_BLOCKED"].includes(approval);
    const approveToken = await hmacHex(secret, `${row.job_id}|${row.fingerprint}|approve`);
    const rejectToken = await hmacHex(secret, `${row.job_id}|${row.fingerprint}|reject`);
    cards.push(`<article class="post"><div class="preview">${row.image_url ? `<img src="${esc(row.image_url)}" alt="Vista previa">` : `<div class="noimg">Sin vista previa</div>`}</div><div><div class="meta">${esc(row.audience || "B2B")} · ${esc(row.campaign_id || "")}</div><h2>${esc(label(row))}</h2><pre>${esc(row.caption || "")}</pre><div class="small">${esc(row.job_id)} · ${esc(row.updated_at || "")}</div>${row.last_error ? `<div class="error">${esc(row.last_error)}</div>` : ""}${done ? "" : `<div class="actions"><form method="post" action="/instagram/command"><input type="hidden" name="job_id" value="${esc(row.job_id)}"><input type="hidden" name="fingerprint" value="${esc(row.fingerprint)}"><input type="hidden" name="action" value="approve"><input type="hidden" name="token" value="${approveToken}"><button class="approve">APROBAR</button></form><form method="post" action="/instagram/command"><input type="hidden" name="job_id" value="${esc(row.job_id)}"><input type="hidden" name="fingerprint" value="${esc(row.fingerprint)}"><input type="hidden" name="action" value="reject"><input type="hidden" name="token" value="${rejectToken}"><button class="reject">DESCARTAR</button></form></div>`}</div></article>`);
  }
  const commandRows = commands.map((row) => `<tr><td>${esc(row.action)}</td><td>${esc(row.job_id)}</td><td>${row.processed ? esc(row.result || "procesado") : "pendiente"}</td><td>${esc(row.created_at || "")}</td></tr>`).join("");
  const result = new URL(request.url).searchParams.get("result") || "";
  const html = `<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#061019"><title>LUMEN · Instagram</title><style>:root{color-scheme:dark;--bg:#061019;--panel:#0c1821;--line:#1d3847;--text:#eef5f7;--muted:#8fa7b3;--lime:#d9ff65;--good:#9de8c5;--bad:#ff9992}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 100% 0,#12303d 0,#061019 38%) fixed;color:var(--text);font:14px Inter,system-ui,-apple-system,Segoe UI,Arial,sans-serif}.wrap{max-width:1250px;margin:auto;padding:18px}.top{display:flex;justify-content:space-between;align-items:center;gap:12px}.brand{font-size:32px;font-weight:950;letter-spacing:.14em}.sub,.small{color:var(--muted)}.links{display:flex;gap:8px;flex-wrap:wrap}.btn{border:1px solid #2c5264;background:#0c1d27;color:#d9edf5;border-radius:10px;padding:9px 11px;text-decoration:none;font-weight:850}.active{background:var(--lime);color:#061019;border-color:var(--lime)}.notice{margin:16px 0;padding:11px 13px;background:#123621;border:1px solid #397752;border-radius:11px;color:var(--good)}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:18px}.k{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:13px}.kl{font-size:10px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);font-weight:900}.kv{font-size:22px;font-weight:950;margin-top:6px}.post{display:grid;grid-template-columns:260px 1fr;gap:16px;margin:12px 0;background:linear-gradient(180deg,#0e1b24,#09151d);border:1px solid var(--line);border-radius:16px;padding:15px}.preview img{width:100%;aspect-ratio:4/5;object-fit:cover;border-radius:12px;background:#061019}.noimg{width:100%;aspect-ratio:4/5;display:grid;place-items:center;border-radius:12px;background:#071019;color:var(--muted)}.meta{color:var(--lime);font-size:11px;font-weight:900;text-transform:uppercase;letter-spacing:.08em}.post h2{margin:7px 0 10px}.post pre{font:inherit;white-space:pre-wrap;max-height:250px;overflow:auto;color:#dce8ec}.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:13px}.actions form{margin:0}.actions button{border:0;border-radius:9px;padding:10px 14px;font-weight:950;cursor:pointer}.approve{background:var(--lime);color:#061019}.reject{background:#35191c;color:#ffd2ce;border:1px solid #6d383d!important}.error{margin-top:10px;padding:9px;border-radius:9px;background:#35191c;color:#ffc4be}.history{margin-top:18px;background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:15px;overflow:auto}table{width:100%;border-collapse:collapse;min-width:650px}th,td{text-align:left;padding:9px 7px;border-bottom:1px solid #17303e}th{font-size:10px;text-transform:uppercase;color:#7694a4}@media(max-width:760px){.grid{grid-template-columns:1fr}.post{grid-template-columns:1fr}.preview{max-width:360px}.top{align-items:flex-start;flex-direction:column}}</style></head><body><main class="wrap"><header class="top"><div><div class="brand">LUMEN</div><div class="sub">Instagram · control liviano e idempotente</div></div><nav class="links"><a class="btn" href="/?tab=overview">Centro completo</a><a class="btn" href="https://www.instagram.com/lumen.b2b/" target="_blank" rel="noreferrer">Instagram ↗</a><a class="btn active" href="/?tab=instagram">Actualizar</a></nav></header>${result ? `<div class="notice">${esc(result)}</div>` : ""}<section class="grid"><div class="k"><div class="kl">Publicaciones</div><div class="kv">${posts.length}</div></div><div class="k"><div class="kl">Comandos pendientes</div><div class="kv">${commands.filter((x) => !Number(x.processed || 0)).length}</div></div><div class="k"><div class="kl">Modo</div><div class="kv">D1 directo</div></div></section><section>${cards.join("") || `<div class="history">No hay publicaciones preparadas.</div>`}</section><section class="history"><h2>Comandos recientes</h2><table><thead><tr><th>Acción</th><th>Publicación</th><th>Estado</th><th>Fecha</th></tr></thead><tbody>${commandRows || `<tr><td colspan="4">Sin comandos.</td></tr>`}</tbody></table></section></main></body></html>`;
  return new Response(html, {
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store, no-cache, must-revalidate",
      "X-Frame-Options": "DENY",
      "X-Content-Type-Options": "nosniff",
      "Referrer-Policy": "no-referrer",
      "Content-Security-Policy": "default-src 'self'; img-src 'self' https:; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
      "X-LUMEN-Resource-Guard": "instagram-fast-path-v1",
    },
  });
}

async function handleInstagramCommand(request, env) {
  const denied = protect(request, env);
  if (denied) return denied;
  const form = await request.formData();
  const jobId = String(form.get("job_id") || "").slice(0, 220);
  const fingerprint = String(form.get("fingerprint") || "").slice(0, 128);
  const action = String(form.get("action") || "").toLowerCase();
  const token = String(form.get("token") || "");
  if (!jobId || !fingerprint || !["approve", "reject"].includes(action)) return new Response("invalid_command", { status:400 });
  const expected = await hmacHex(String(env.LUMEN_DASHBOARD_PASSWORD || ""), `${jobId}|${fingerprint}|${action}`);
  if (!constantTimeEqual(token, expected)) return new Response("invalid_command_token", { status:403 });
  await ensureSchema(env);
  const current = await env.DB.prepare("SELECT fingerprint,state_status,approval_status FROM lumen_instagram_control_posts WHERE job_id=? LIMIT 1").bind(jobId).first();
  if (!current) return new Response("post_not_found", { status:404 });
  if (!constantTimeEqual(String(current.fingerprint || ""), fingerprint)) return new Response("content_changed_reload", { status:409 });
  if (String(current.state_status || "").toUpperCase() === "PUBLISHED") {
    return new Response(null, { status:303, headers:{ Location:`/?tab=instagram&result=${encodeURIComponent("La publicación ya estaba publicada.")}` } });
  }
  const activeApprovals = new Set(["APPROVED", "APPROVED_WAITING_CONNECTOR", "APPROVED_RETRY"]);
  if (action === "approve" && activeApprovals.has(String(current.approval_status || "").toUpperCase())) {
    return new Response(null, { status:303, headers:{ Location:`/?tab=instagram&result=${encodeURIComponent("La aprobación ya estaba activa. No se creó un duplicado.")}` } });
  }
  const duplicate = await env.DB.prepare("SELECT id FROM lumen_instagram_control_commands WHERE job_id=? AND fingerprint=? AND action=? AND processed=0 ORDER BY created_at DESC LIMIT 1").bind(jobId, fingerprint, action).first();
  if (duplicate) {
    return new Response(null, { status:303, headers:{ Location:`/?tab=instagram&result=${encodeURIComponent("Ese comando ya estaba pendiente. No se creó un duplicado.")}` } });
  }
  await env.DB.prepare("INSERT INTO lumen_instagram_control_commands(id,job_id,fingerprint,action,created_at,processed) VALUES(?,?,?,?,?,0)").bind(crypto.randomUUID(), jobId, fingerprint, action, new Date().toISOString()).run();
  const message = action === "approve"
    ? "Aprobación registrada una sola vez. El publicador autónomo la procesará en el próximo ciclo de hasta 5 minutos."
    : "Descarte registrado una sola vez. LUMEN lo procesará en el próximo ciclo.";
  return new Response(null, { status:303, headers:{ Location:`/?tab=instagram&result=${encodeURIComponent(message)}` } });
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (request.method === "POST" && url.pathname === "/instagram/command") {
      return handleInstagramCommand(request, env);
    }
    if (request.method === "GET" && (url.pathname === "/instagram-control" || (url.pathname === "/" && url.searchParams.get("tab") === "instagram"))) {
      return renderInstagramControl(request, env);
    }
    return app.fetch(request, env, ctx);
  },
};
