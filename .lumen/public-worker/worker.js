const MAX_NEED = 1500;
const SERVICES = [
  { id: "SRV-QUOTECHECK", name: "Quote Check", desc: "Revisión y comparación estructurada de cotizaciones B2B." },
  { id: "SRV-SUPPLIERCHECK", name: "Supplier Check", desc: "Investigación y verificación comercial de proveedores." },
  { id: "SRV-EXPORT-SCOUT", name: "Export Scout", desc: "Búsqueda de mercados, importadores, distribuidores y compradores con evidencia pública." },
  { id: "SRV-TENDER-HUNTER", name: "Tender Hunter", desc: "Detección y preanálisis de oportunidades y licitaciones públicas relevantes." },
];
const SERVICE_IDS = new Set(SERVICES.map((x) => x.id));
const RAW_ASSET_BASE = "https://raw.githubusercontent.com/Joseandres1984/nodejs_course_project/lumen-zero/.lumen/public/instagram/";
const RAW_FALLBACK = "https://raw.githubusercontent.com/Joseandres1984/nodejs_course_project/main/.lumen/public/lumen-instagram-canary.jpg";

function esc(value) {
  return String(value ?? "").replace(/[&<>\"']/g, (ch) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'\"':"&quot;","'":"&#39;"}[ch]));
}
function clean(value, limit) { return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit); }
function html(body, status = 200) {
  return new Response(body, { status, headers: { "content-type":"text/html; charset=utf-8", "cache-control":"no-store", "x-content-type-options":"nosniff", "referrer-policy":"strict-origin-when-cross-origin" }});
}
function json(data, status = 200) {
  return Response.json(data, { status, headers: { "cache-control":"no-store", "x-content-type-options":"nosniff" }});
}
function redirect(location) { return new Response(null, { status: 303, headers: { location }}); }
function shell(title, content) {
  return `<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="LUMEN: inteligencia comercial B2B, sourcing, verificación y coordinación comercial."><title>${esc(title)}</title><style>
:root{--bg:#071019;--panel:#0d1822;--text:#edf6fb;--muted:#9eb1bd;--line:#1c3545;--accent:#d8ff66;--accent2:#8ed7ff}*{box-sizing:border-box}body{margin:0;background:linear-gradient(180deg,#061019,#09131c 55%,#071019);color:var(--text);font-family:Inter,system-ui,-apple-system,Segoe UI,Arial,sans-serif;line-height:1.55}a{color:inherit}.wrap{max-width:1120px;margin:auto;padding:0 22px}.nav{min-height:74px;display:flex;gap:18px;align-items:center;justify-content:space-between;border-bottom:1px solid #ffffff12}.brand{font-weight:950;letter-spacing:.2em}.links{display:flex;gap:16px;flex-wrap:wrap}.links a{text-decoration:none;color:var(--muted);font-weight:750}.hero{padding:76px 0 48px}.eyebrow{color:var(--accent);font-weight:900;text-transform:uppercase;letter-spacing:.12em;font-size:12px}h1{font-size:clamp(40px,7vw,70px);line-height:1.02;letter-spacing:-.045em;margin:12px 0 20px}h2{font-size:30px}.lead{font-size:19px;color:var(--muted);max-width:820px}.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}.card,.box{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:24px}.card h3{margin:0 0 8px}.card p,.small{color:var(--muted)}.section{padding:34px 0 58px}.cta,button{display:inline-block;background:var(--accent);color:#071019;text-decoration:none;font-weight:950;padding:13px 18px;border:0;border-radius:10px;cursor:pointer}.price{font-weight:950;color:var(--accent);font-size:22px}.notice{background:#123321;border:1px solid #34784f;padding:12px 14px;border-radius:12px;margin:0 0 18px}label{display:block;font-weight:800;margin:13px 0 6px}input,select,textarea{width:100%;background:#07151b;border:1px solid #294653;color:var(--text);border-radius:10px;padding:12px;font:inherit}textarea{min-height:140px}.hp{position:absolute;left:-9999px}.footer{border-top:1px solid #ffffff12;padding:28px 0 42px;color:#78909e;font-size:13px}@media(max-width:760px){.grid{grid-template-columns:1fr}.nav{align-items:flex-start;padding:18px 0}.links{justify-content:flex-end}}
</style></head><body><div class="wrap"><nav class="nav"><div class="brand">LUMEN</div><div class="links"><a href="/">Inicio</a><a href="/services">Servicios</a><a href="/intelligence">Intelligence</a><a href="/privacy">Privacidad</a></div></nav>${content}<footer class="footer">© 2026 LUMEN · Inteligencia comercial y sourcing B2B · Argentina</footer></div></body></html>`;
}
function home() {
  return shell("LUMEN | Inteligencia comercial B2B", `<main><section class="hero"><div class="eyebrow">Inteligencia comercial B2B · Argentina</div><h1>Conectamos demanda empresarial con oferta confiable.</h1><p class="lead">LUMEN investiga mercados, detecta oportunidades, identifica compradores y proveedores, organiza cotizaciones y coordina procesos comerciales con evidencia verificable.</p><p><a class="cta" href="/services">Ver servicios</a></p></section><section class="section"><div class="grid"><article class="card"><h3>Detectar</h3><p>Señales de demanda, oportunidades, mercados y necesidades reales.</p></article><article class="card"><h3>Validar</h3><p>Empresas, contactos corporativos y evidencia antes de avanzar.</p></article><article class="card"><h3>Comparar</h3><p>Alternativas de suministro, cotizaciones, condiciones y riesgo.</p></article><article class="card"><h3>Coordinar</h3><p>Outreach, seguimiento, negociación asistida y trazabilidad comercial.</p></article></div></section><section class="section"><div class="box"><h2>Operación con límites claros</h2><p class="small">LUMEN automatiza investigación, priorización y preparación comercial. Contratos vinculantes, movimientos de dinero y compromisos legales permanecen sujetos a autorización humana.</p></div></section></main>`);
}
function services(received=false) {
  const cards = SERVICES.map((s)=>`<article class="card"><div class="eyebrow">LUMEN Intelligence</div><h3>${esc(s.name)}</h3><div class="price">Desde USD 249</div><p>${esc(s.desc)}</p><p class="small">Paquete inicial de alcance acotado. Mercados, proveedores, segmentos o profundidad adicionales se cotizan antes de contratar.</p></article>`).join("");
  const options = SERVICES.map((s)=>`<option value="${s.id}">${esc(s.name)}</option>`).join("");
  return shell("LUMEN | Servicios", `<main><section class="hero"><div class="eyebrow">Servicios e intelligence</div><h1>Investigación comercial que termina en acción.</h1><p class="lead">Productos de entrada claros, alcance controlado y evidencia trazable. Enviar una consulta no crea un cargo ni un compromiso vinculante.</p></section>${received?'<div class="notice">Consulta recibida. LUMEN la incorporará al próximo ciclo comercial. No se realizó ningún cargo.</div>':''}<section class="grid">${cards}</section><section class="section"><div class="box"><div class="eyebrow">Consulta comercial</div><h2>Contanos qué necesitás</h2><form method="post" action="/api/services/inquiry"><label>Servicio</label><select name="service_id" required>${options}</select><label>Email de contacto</label><input type="email" name="email" maxlength="180" required autocomplete="email"><label>Qué necesitás</label><textarea name="need" maxlength="1500" minlength="12" required placeholder="Producto, mercado, proveedor, cotización u oportunidad que querés investigar."></textarea><label>Empresa <span class="small">(opcional)</span></label><input name="company" maxlength="180" autocomplete="organization"><label>Nombre <span class="small">(opcional)</span></label><input name="name" maxlength="120" autocomplete="name"><label class="hp">Sitio web<input name="website" tabindex="-1" autocomplete="off"></label><p><button type="submit">Preparar mi caso</button></p></form><p class="small">El precio y alcance final se confirman antes de contratar. LUMEN no realiza conversiones de moneda sin una fuente verificada.</p></div></section></main>`);
}
function intelligence() {
  return shell("LUMEN | Intelligence", `<main><section class="hero"><div class="eyebrow">LUMEN Intelligence</div><h1>Mercado → evidencia → empresa → oportunidad.</h1><p class="lead">Scout y los motores de inteligencia trabajan con fuentes públicas para descubrir, contrastar y priorizar señales comerciales. Una señal no se convierte en oportunidad ejecutable hasta superar los controles de calidad y verificación.</p></section><section class="grid"><article class="card"><h3>Scout / Radar</h3><p>Exploración de mercados, demanda pública, empresas y señales.</p></article><article class="card"><h3>Buyer & Supplier Intelligence</h3><p>Resolución de identidad, canales corporativos, capacidades y encaje.</p></article><article class="card"><h3>Deal & Quote Intelligence</h3><p>Requisitos, comparación de ofertas, márgenes y preparación de negociación.</p></article><article class="card"><h3>Learning Engine</h3><p>Aprendizaje a partir de resultados observados, sin convertir hipótesis en hechos.</p></article></section></main>`);
}
function privacy() {
  return shell("LUMEN | Privacidad", `<main><section class="hero"><div class="eyebrow">Privacidad</div><h1>Datos mínimos para una consulta B2B.</h1><p class="lead">El formulario solicita email, necesidad y opcionalmente nombre y empresa. Se usa para evaluar y responder la consulta comercial. No se crea un pago ni contrato al enviar el formulario.</p></section></main>`);
}
async function ensureSchema(env) {
  await env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_public_inquiries (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, service_id TEXT NOT NULL, email TEXT NOT NULL, company TEXT, name TEXT, need TEXT NOT NULL, source TEXT NOT NULL, processed INTEGER NOT NULL DEFAULT 0, processed_at TEXT)").run();
  await env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_public_inquiries_pending ON lumen_public_inquiries(processed, created_at)").run();
}
async function handleInquiry(request, env) {
  const form = await request.formData();
  if (clean(form.get("website"),200)) return redirect("/services?result=received");
  const serviceId=clean(form.get("service_id"),80), email=clean(form.get("email"),180).toLowerCase(), company=clean(form.get("company"),180), name=clean(form.get("name"),120), need=clean(form.get("need"),MAX_NEED);
  if (!SERVICE_IDS.has(serviceId) || need.length < 12 || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return html(shell("Solicitud inválida","<main><section class='hero'><h1>Revisá los datos.</h1><p class='lead'>Necesitamos un email válido y una descripción de al menos 12 caracteres.</p></section></main>"),400);
  await ensureSchema(env);
  const id = `INQ-${crypto.randomUUID()}`;
  await env.DB.prepare("INSERT INTO lumen_public_inquiries(id,created_at,service_id,email,company,name,need,source,processed) VALUES(?,?,?,?,?,?,?,?,0)").bind(id,new Date().toISOString(),serviceId,email,company,name,need,"lumen_zero_public_worker").run();
  return redirect("/services?result=received");
}
function safeAssetName(raw) { return String(raw||"").replace(/[^a-zA-Z0-9._-]/g,"_").slice(0,180); }
async function media(pathname) {
  const match = pathname.match(/^\/media\/instagram\/([^/]+)\.jpg$/);
  if (!match) return new Response("not_found",{status:404});
  const name=safeAssetName(decodeURIComponent(match[1]));
  let upstream=await fetch(RAW_ASSET_BASE+encodeURIComponent(name)+".jpg",{cf:{cacheTtl:300,cacheEverything:true}});
  if (!upstream.ok) upstream=await fetch(RAW_FALLBACK,{cf:{cacheTtl:300,cacheEverything:true}});
  if (!upstream.ok) return new Response("media_unavailable",{status:503});
  return new Response(upstream.body,{status:200,headers:{"content-type":"image/jpeg","cache-control":"public, max-age=300","x-content-type-options":"nosniff"}});
}
export default {
  async fetch(request, env) {
    const url=new URL(request.url);
    if (request.method==="GET" && url.pathname==="/health") return json({ok:true,service:"lumen-zero-public",storage:"cloudflare-d1",inquiry_capture:true,instagram_media:true});
    if (request.method==="GET" && url.pathname==="/") return html(home());
    if (request.method==="GET" && url.pathname==="/services") return html(services(url.searchParams.get("result")==="received"));
    if (request.method==="GET" && url.pathname==="/intelligence") return html(intelligence());
    if (request.method==="GET" && url.pathname==="/privacy") return html(privacy());
    if (request.method==="GET" && url.pathname.startsWith("/media/instagram/")) return media(url.pathname);
    if (request.method==="POST" && url.pathname==="/api/services/inquiry") return handleInquiry(request,env);
    if (request.method==="GET" && url.pathname==="/api/services/pricing") return json({currency:"USD",from_usd:249,pricing_mode:"launch_scope_controlled",services:SERVICES,binding:false,payment_created:false});
    return new Response("not_found",{status:404,headers:{"content-type":"text/plain; charset=utf-8"}});
  }
};
