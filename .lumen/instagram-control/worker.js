const USER = "socio";
const RECOVERY_IDS = ["DIST-3ADEE9154FA8","DIST-90AC7FE4D0F0","DIST-C9C06F669D70"];

function text(body, status = 200, extra = {}) {
  return new Response(body, { status, headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store", "x-content-type-options": "nosniff", ...extra } });
}
function esc(value) {
  return String(value ?? "").replace(/[&<>\"']/g, (ch) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'\"':"&quot;","'":"&#39;"}[ch]));
}
function constantTimeEqual(a, b) {
  a=String(a||""); b=String(b||""); if(a.length!==b.length) return false; let diff=0;
  for(let i=0;i<a.length;i++) diff|=a.charCodeAt(i)^b.charCodeAt(i); return diff===0;
}
function unauthorized() {
  return text("Authentication required", 401, { "www-authenticate": 'Basic realm="LUMEN Instagram Control", charset="UTF-8"' });
}
function authorized(request, env) {
  const password=String(env.LUMEN_DASHBOARD_PASSWORD||"");
  if(!password) return false;
  const header=request.headers.get("authorization")||"";
  if(!header.startsWith("Basic ")) return false;
  try {
    const decoded=atob(header.slice(6));
    const idx=decoded.indexOf(":");
    if(idx<0) return false;
    return constantTimeEqual(decoded.slice(0,idx), USER) && constantTimeEqual(decoded.slice(idx+1), password);
  } catch { return false; }
}
async function hmacToken(env, jobId, fingerprint, action) {
  const secret=String(env.LUMEN_DASHBOARD_PASSWORD||"");
  const key=await crypto.subtle.importKey("raw",new TextEncoder().encode(secret),{name:"HMAC",hash:"SHA-256"},false,["sign"]);
  const sig=await crypto.subtle.sign("HMAC",key,new TextEncoder().encode(`${jobId}|${fingerprint}|${action}`));
  return [...new Uint8Array(sig)].map((b)=>b.toString(16).padStart(2,"0")).join("");
}
async function ensureSchema(env) {
  await env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_instagram_control_posts (job_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, audience TEXT, campaign_id TEXT, caption TEXT, image_url TEXT, state_status TEXT, approval_status TEXT, last_error TEXT, created_at TEXT, updated_at TEXT NOT NULL)").run();
  await env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_instagram_control_commands (id TEXT PRIMARY KEY, job_id TEXT NOT NULL, fingerprint TEXT NOT NULL, action TEXT NOT NULL, created_at TEXT NOT NULL, processed INTEGER NOT NULL DEFAULT 0, processed_at TEXT, result TEXT)").run();
  await env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_instagram_control_commands_pending ON lumen_instagram_control_commands(processed, created_at)").run();
}
async function commandWriteCanary(env) {
  await ensureSchema(env);
  await env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_instagram_control_canary (id TEXT PRIMARY KEY, created_at TEXT NOT NULL)").run();
  const id=`canary-${crypto.randomUUID()}`;
  const createdAt=new Date().toISOString();
  let write=false, read=false, deleted=false;
  try {
    await env.DB.prepare("INSERT INTO lumen_instagram_control_canary(id,created_at) VALUES(?,?)").bind(id,createdAt).run();
    write=true;
    const row=await env.DB.prepare("SELECT id,created_at FROM lumen_instagram_control_canary WHERE id=? LIMIT 1").bind(id).first();
    read=Boolean(row && constantTimeEqual(String(row.id||""),id) && String(row.created_at||"")===createdAt);
  } finally {
    await env.DB.prepare("DELETE FROM lumen_instagram_control_canary WHERE id=?").bind(id).run();
    const left=await env.DB.prepare("SELECT id FROM lumen_instagram_control_canary WHERE id=? LIMIT 1").bind(id).first();
    deleted=!left;
  }
  return {ok:Boolean(write&&read&&deleted),service:"lumen-instagram-control",storage:"cloudflare-d1",d1_write:write,d1_read:read,d1_delete:deleted,command_queue_schema:true};
}
async function projectionDiagnostic(env) {
  await ensureSchema(env);
  const posts=await env.DB.prepare("SELECT job_id,fingerprint,state_status,approval_status,last_error,updated_at FROM lumen_instagram_control_posts WHERE job_id IN (?,?,?) ORDER BY job_id").bind(...RECOVERY_IDS).all();
  const commands=await env.DB.prepare("SELECT job_id,action,processed,result,created_at,processed_at FROM lumen_instagram_control_commands WHERE job_id IN (?,?,?) ORDER BY created_at DESC LIMIT 30").bind(...RECOVERY_IDS).all();
  return {
    ok:true,
    posts:(posts.results||[]).map((r)=>({
      job_id:String(r.job_id||""),
      fingerprint_prefix:String(r.fingerprint||"").slice(0,16),
      state_status:String(r.state_status||""),
      approval_status:String(r.approval_status||""),
      last_error:String(r.last_error||"").slice(0,160)||null,
      updated_at:String(r.updated_at||"")
    })),
    commands:(commands.results||[]).map((r)=>({
      job_id:String(r.job_id||""), action:String(r.action||""), processed:Number(r.processed||0), result:String(r.result||"")||null,
      created_at:String(r.created_at||""), processed_at:String(r.processed_at||"")||null
    }))
  };
}
function label(row) {
  if(String(row.state_status||"").toUpperCase()==="PUBLISHED" || String(row.approval_status||"").toUpperCase()==="PUBLISHED") return "Publicado";
  const a=String(row.approval_status||"").toUpperCase();
  if(a==="APPROVED") return "Aprobado · publicación pendiente";
  if(a==="APPROVED_WAITING_CONNECTOR") return "Aprobado · esperando conector";
  if(a==="APPROVED_RETRY") return "Aprobado · reintento pendiente";
  if(a==="REJECTED") return "Descartado";
  if(a==="EXPIRED") return "Aprobación vencida";
  if(a==="CONTENT_CHANGED") return "Contenido cambió";
  return "Listo para aprobación";
}
function page(rows, commands, result="") {
  const notice=result ? `<div class="notice">${esc(result)}</div>` : "";
  const cards=rows.map((row)=>{
    const done=["PUBLISHED","REJECTED"].includes(String(row.approval_status||"").toUpperCase()) || String(row.state_status||"").toUpperCase()==="PUBLISHED";
    return `<article class="card">
      <div class="preview">${row.image_url?`<img src="${esc(row.image_url)}" alt="Vista previa">`:`<div class="noimg">Sin vista previa</div>`}</div>
      <div class="body"><div class="meta">${esc(row.audience||"B2B")} · ${esc(row.campaign_id||"")}</div><h2>${esc(label(row))}</h2><pre>${esc(row.caption||"")}</pre>
      <div class="small">ID ${esc(row.job_id)} · actualizado ${esc(row.updated_at||"")}</div>
      ${row.last_error?`<div class="error">${esc(row.last_error)}</div>`:""}
      ${done?"":`<div class="actions">
        <form method="post" action="/command"><input type="hidden" name="job_id" value="${esc(row.job_id)}"><input type="hidden" name="fingerprint" value="${esc(row.fingerprint)}"><input type="hidden" name="action" value="approve"><input type="hidden" name="csrf" value="__APPROVE_${esc(row.job_id)}__"><button class="approve">APROBAR</button></form>
        <form method="post" action="/command"><input type="hidden" name="job_id" value="${esc(row.job_id)}"><input type="hidden" name="fingerprint" value="${esc(row.fingerprint)}"><input type="hidden" name="action" value="reject"><input type="hidden" name="csrf" value="__REJECT_${esc(row.job_id)}__"><button class="reject">DESCARTAR</button></form>
      </div>`}
      </div></article>`;
  }).join("") || `<div class="empty">No hay publicaciones preparadas todavía. El próximo ciclo de LUMEN actualizará esta pantalla.</div>`;
  const recent=commands.slice(0,8).map((c)=>`<tr><td>${esc(c.action)}</td><td>${esc(c.job_id)}</td><td>${c.processed?esc(c.result||"procesado"):"pendiente"}</td><td>${esc(c.created_at)}</td></tr>`).join("");
  return `<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LUMEN · Instagram Control</title><style>
:root{--bg:#061117;--panel:#0d1d26;--line:#24404c;--text:#edf5f7;--muted:#9fb2bb;--accent:#d8ff66;--danger:#ff8177}*{box-sizing:border-box}body{margin:0;background:linear-gradient(180deg,#061117,#08151c);color:var(--text);font-family:Inter,system-ui,-apple-system,Segoe UI,Arial,sans-serif;line-height:1.5}.wrap{max-width:1120px;margin:auto;padding:28px 20px 70px}.top{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:34px}.brand{font-weight:950;letter-spacing:.16em}.badge{border:1px solid var(--line);padding:7px 11px;border-radius:999px;color:var(--muted);font-size:12px}h1{font-size:clamp(34px,6vw,56px);line-height:1.02;margin:8px 0}.lead,.small{color:var(--muted)}.notice{background:#173622;border:1px solid #397752;padding:11px 14px;border-radius:12px;margin:18px 0}.card{display:grid;grid-template-columns:330px 1fr;gap:22px;background:var(--panel);border:1px solid var(--line);border-radius:20px;padding:18px;margin:18px 0}.preview img{width:100%;aspect-ratio:4/5;object-fit:cover;border-radius:14px;background:#071019}.noimg{aspect-ratio:4/5;display:grid;place-items:center;background:#071019;border-radius:14px;color:var(--muted)}.meta{color:var(--accent);font-size:12px;font-weight:900;text-transform:uppercase;letter-spacing:.08em}.body h2{margin:7px 0 12px}pre{white-space:pre-wrap;font:inherit;color:#d8e4e8}.actions{display:flex;gap:10px;margin-top:18px}.actions form{margin:0}button{border:0;border-radius:10px;padding:12px 16px;font-weight:950;cursor:pointer}.approve{background:var(--accent);color:#071019}.reject{background:#37191a;color:#ffd5d2;border:1px solid #713837}.error{background:#35181a;color:#ffc4bf;padding:10px;border-radius:10px;margin-top:12px}.history{margin-top:40px;background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:18px;overflow:auto}table{border-collapse:collapse;width:100%;min-width:620px}th,td{text-align:left;border-bottom:1px solid #ffffff12;padding:9px;font-size:13px}th{color:var(--muted)}.empty{background:var(--panel);border:1px dashed var(--line);border-radius:16px;padding:30px;color:var(--muted)}@media(max-width:760px){.card{grid-template-columns:1fr}.preview{max-width:390px}.actions{flex-wrap:wrap}}
</style></head><body><div class="wrap"><div class="top"><div class="brand">LUMEN</div><div class="badge">INSTAGRAM · CONTROL HUMANO</div></div><div class="meta">Canal operativo</div><h1>Publicaciones preparadas</h1><p class="lead">LUMEN puede investigar, diseñar y preparar contenido. Cada publicación normal sigue requiriendo tu aprobación explícita; la aprobación queda ligada al contenido exacto y vence en 24 horas.</p>${notice}${cards}<section class="history"><h2>Comandos recientes</h2><table><thead><tr><th>Acción</th><th>Publicación</th><th>Resultado</th><th>Fecha</th></tr></thead><tbody>${recent||'<tr><td colspan="4">Sin comandos todavía.</td></tr>'}</tbody></table></section></div></body></html>`;
}
async function renderConsole(env, result="") {
  await ensureSchema(env);
  const posts=await env.DB.prepare("SELECT job_id,fingerprint,audience,campaign_id,caption,image_url,state_status,approval_status,last_error,created_at,updated_at FROM lumen_instagram_control_posts ORDER BY updated_at DESC LIMIT 50").all();
  const commands=await env.DB.prepare("SELECT job_id,action,created_at,processed,result FROM lumen_instagram_control_commands ORDER BY created_at DESC LIMIT 20").all();
  let body=page(posts.results||[],commands.results||[],result);
  for(const row of posts.results||[]) {
    body=body.replace(`__APPROVE_${esc(row.job_id)}__`,await hmacToken(env,row.job_id,row.fingerprint,"approve"));
    body=body.replace(`__REJECT_${esc(row.job_id)}__`,await hmacToken(env,row.job_id,row.fingerprint,"reject"));
  }
  return new Response(body,{status:200,headers:{"content-type":"text/html; charset=utf-8","cache-control":"no-store","x-frame-options":"DENY","content-security-policy":"default-src 'self'; img-src 'self' https:; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'","referrer-policy":"no-referrer","x-content-type-options":"nosniff"}});
}
async function command(request, env) {
  const form=await request.formData();
  const jobId=String(form.get("job_id")||"").slice(0,200), fingerprint=String(form.get("fingerprint")||"").slice(0,128), action=String(form.get("action")||"").toLowerCase(), csrf=String(form.get("csrf")||"");
  if(!jobId || !fingerprint || !["approve","reject"].includes(action)) return text("invalid_command",400);
  const expected=await hmacToken(env,jobId,fingerprint,action);
  if(!constantTimeEqual(csrf,expected)) return text("invalid_csrf",403);
  await ensureSchema(env);
  const row=await env.DB.prepare("SELECT fingerprint FROM lumen_instagram_control_posts WHERE job_id=? LIMIT 1").bind(jobId).first();
  if(!row) return text("job_not_found",404);
  if(!constantTimeEqual(String(row.fingerprint||""),fingerprint)) return text("content_changed_reload",409);
  await env.DB.prepare("INSERT INTO lumen_instagram_control_commands(id,job_id,fingerprint,action,created_at,processed) VALUES(?,?,?,?,?,0)").bind(crypto.randomUUID(),jobId,fingerprint,action,new Date().toISOString()).run();
  return new Response(null,{status:303,headers:{location:`/?result=${encodeURIComponent(action==="approve"?"Aprobación registrada en D1. LUMEN la procesará en el próximo ciclo.":"Descarte registrado en D1. LUMEN lo procesará en el próximo ciclo.")}`}});
}
export default {
  async fetch(request, env) {
    if(!String(env.LUMEN_DASHBOARD_PASSWORD||"")) return text("control_not_configured",503);
    if(!authorized(request,env)) return unauthorized();
    const url=new URL(request.url);
    if(request.method==="GET" && url.pathname==="/health") return Response.json({ok:true,service:"lumen-instagram-control",auth:true,storage:"cloudflare-d1",version:"1.2-d1-projection-diagnostic"},{headers:{"cache-control":"no-store"}});
    if(request.method==="POST" && url.pathname==="/health/command-write") {
      try {
        const result=await commandWriteCanary(env);
        return Response.json(result,{status:result.ok?200:503,headers:{"cache-control":"no-store"}});
      } catch(err) {
        return Response.json({ok:false,service:"lumen-instagram-control",d1_write:false,d1_read:false,d1_delete:false,error:String(err?.name||"Error")},{status:503,headers:{"cache-control":"no-store"}});
      }
    }
    if(request.method==="GET" && url.pathname==="/health/projection") {
      try { return Response.json(await projectionDiagnostic(env),{headers:{"cache-control":"no-store"}}); }
      catch(err) { return Response.json({ok:false,error:String(err?.name||"Error")},{status:503,headers:{"cache-control":"no-store"}}); }
    }
    if(request.method==="GET" && url.pathname==="/") return renderConsole(env,url.searchParams.get("result")||"");
    if(request.method==="POST" && url.pathname==="/command") return command(request,env);
    return text("not_found",404);
  }
};
