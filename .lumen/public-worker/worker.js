const MAX_NEED = 1500;
const SERVICE_CONTRACT_VERSION = "2026-09-21-v1";
const SERVICES = [{"id":"SRV-QUOTECHECK","slug":"quotecheck-global","name":"LUMEN QuoteCheck Global","from_usd":59,"description":"Revisión estructurada de cotizaciones B2B para entender precio, condiciones, diferencias y señales que requieren atención.","scope":"Paquete inicial: hasta 3 cotizaciones comparables o 1 cotización contrastada con referencias públicas disponibles.","client_inputs":["Cotización o datos principales de la oferta","Producto/especificación y cantidad","Moneda, país, Incoterm y fecha si están disponibles"],"deliverables":["Tabla comparativa de precios y condiciones","Referencias públicas de mercado cuando existan","Desvíos, inconsistencias y preguntas para el proveedor","Conclusión ejecutiva de razonabilidad y próximos pasos"],"not_included":["Tasación o valuación certificada","Asesoramiento legal, tributario o contable","Garantía de que un precio sea el mejor disponible"],"desc":"Revisión estructurada de cotizaciones B2B para entender precio, condiciones, diferencias y señales que requieren atención."},{"id":"SRV-SUPPLIERCHECK","slug":"suppliercheck","name":"LUMEN SupplierCheck","from_usd":79,"description":"Investigación pública de un proveedor para verificar identidad, presencia comercial, encaje y señales de riesgo antes de avanzar.","scope":"Paquete inicial: 1 proveedor o entidad por análisis.","client_inputs":["Nombre legal/comercial o URL del proveedor","País y producto/servicio que ofrece","Qué decisión necesitás tomar"],"deliverables":["Identidad y canales oficiales encontrados","Actividad, presencia pública y señales comerciales","Encaje con el producto/servicio requerido","Alertas o inconsistencias observables","Fuentes utilizadas y conclusión de riesgo comercial"],"not_included":["Informe crediticio privado","Due diligence legal certificada","Inspección física o auditoría de fábrica","Garantía de solvencia o cumplimiento futuro"],"desc":"Investigación pública de un proveedor para verificar identidad, presencia comercial, encaje y señales de riesgo antes de avanzar."},{"id":"SRV-TENDER-HUNTER","slug":"tender-hunter-global","name":"LUMEN Tender Hunter Global","from_usd":99,"description":"Búsqueda y preanálisis de licitaciones u oportunidades públicas compatibles con lo que vende tu empresa.","scope":"Paquete inicial: hasta 10 oportunidades priorizadas dentro del mercado y criterios acordados.","client_inputs":["Qué producto o servicio ofrecés","Países/regiones y sectores objetivo","Palabras clave, códigos o exclusiones si las tenés"],"deliverables":["Shortlist priorizada de oportunidades","Organismo/comprador, fecha límite y enlace fuente","Resumen de requisitos visibles","Evaluación inicial de encaje","Próximos pasos recomendados"],"not_included":["Presentación de ofertas en nombre del cliente","Garantía de adjudicación","Asesoramiento jurídico sobre pliegos","Certificación de elegibilidad"],"desc":"Búsqueda y preanálisis de licitaciones u oportunidades públicas compatibles con lo que vende tu empresa."},{"id":"SRV-SOURCING-EXPRESS","slug":"sourcing-express","name":"LUMEN Sourcing Express","from_usd":149,"description":"Investigación de proveedores para una necesidad de compra concreta, con comparación y priorización.","scope":"Paquete inicial: hasta 10 candidatos investigados y hasta 5 priorizados para contacto.","client_inputs":["Producto y especificación técnica","Cantidad aproximada y país de entrega","Marcas, certificaciones, materiales o restricciones obligatorias"],"deliverables":["Shortlist de proveedores candidatos","Evidencia pública de capacidad y ubicación","Canales corporativos públicos cuando estén disponibles","Comparación de encaje y principales diferencias","Riesgos/gaps y recomendación de próximos contactos"],"not_included":["Compra o emisión de órdenes por cuenta del cliente","Inspección física","Garantía de stock o precio","Negociación vinculante sin autorización humana"],"desc":"Investigación de proveedores para una necesidad de compra concreta, con comparación y priorización."},{"id":"SRV-B2B-PROSPECTING","slug":"b2b-prospecting","name":"LUMEN Prospección B2B","from_usd":199,"description":"Investigación de empresas que podrían comprar una oferta B2B definida y priorización por señales públicas de encaje.","scope":"Paquete inicial: hasta 25 empresas objetivo priorizadas.","client_inputs":["Qué vendés y propuesta de valor","Tipo de cliente ideal","Geografía objetivo y exclusiones","Ticket, sector o tamaño de empresa si importa"],"deliverables":["Lista priorizada de empresas objetivo","Motivo de encaje para cada cuenta","Señales públicas de necesidad o actividad cuando existan","Canales corporativos públicos disponibles","Segmentación y sugerencia de enfoque comercial"],"not_included":["Garantía de respuesta o venta","Datos personales obtenidos por vías no públicas","Spam masivo","Compromisos comerciales en nombre del cliente"],"desc":"Investigación de empresas que podrían comprar una oferta B2B definida y priorización por señales públicas de encaje."},{"id":"SRV-EXPORT-SCOUT","slug":"export-scout","name":"LUMEN Export Scout","from_usd":249,"description":"Exploración inicial de mercados y compradores para una empresa que quiere evaluar oportunidades de exportación.","scope":"Paquete inicial: hasta 5 mercados evaluados con shortlist inicial de actores relevantes.","client_inputs":["Producto y país de origen","Capacidad, certificaciones y restricciones conocidas","Mercados de interés si ya existen","Tipo de comprador buscado"],"deliverables":["Priorización de mercados","Señales públicas de demanda y competencia","Importadores, distribuidores o compradores candidatos","Barreras y requisitos públicos visibles","Ruta inicial recomendada para profundizar"],"not_included":["Asesoramiento aduanero, legal o tributario","Clasificación arancelaria certificada","Garantía de acceso al mercado","Representación comercial vinculante"],"desc":"Exploración inicial de mercados y compradores para una empresa que quiere evaluar oportunidades de exportación."}];
const SERVICE_IDS = new Set(SERVICES.map((x) => x.id));
const RAW_ASSET_BASE = "https://raw.githubusercontent.com/Joseandres1984/nodejs_course_project/lumen-zero/.lumen/public/instagram/";
const RAW_FALLBACK = "https://raw.githubusercontent.com/Joseandres1984/nodejs_course_project/main/.lumen/public/lumen-instagram-canary.jpg";

// Canonical campaign tokens generated by acquisition_campaigns.py.
// Keeping these routes alive on the zero-cost public Worker preserves links already sent by email.
const CAMPAIGNS = {
  D1A6FA819E21: { audience: "buyer", angle: "Menos horas buscando. Más alternativas comparables.", service_id: "SRV-SOURCING-EXPRESS" },
  "8BBD48E8D6F2": { audience: "buyer", angle: "Compras B2B con más evidencia y menos ruido.", service_id: "SRV-SOURCING-EXPRESS" },
  "3D0AB3D607FA": { audience: "buyer", angle: "Encontrá proveedores para una necesidad real, no una lista infinita.", service_id: "SRV-SOURCING-EXPRESS" },
  "4F11F08D4303": { audience: "supplier", angle: "Tu equipo vende. LUMEN busca dónde puede encajar tu oferta.", service_id: "SRV-B2B-PROSPECTING" },
  "8BAEC030C8EC": { audience: "supplier", angle: "Más oportunidades útiles, menos prospección sin rumbo.", service_id: "SRV-B2B-PROSPECTING" },
  C07A7EFE0AE1: { audience: "supplier", angle: "Convertí tu catálogo en más conversaciones comerciales.", service_id: "SRV-B2B-PROSPECTING" },
  E5656C82B22F: { audience: "partner", angle: "Sumá un canal comercial sin ceder el control de tu venta.", service_id: "SRV-B2B-PROSPECTING" },
  EF282AF21B40: { audience: "partner", angle: "Tu catálogo ya existe. Hagamos que encuentre compradores.", service_id: "SRV-B2B-PROSPECTING" },
  "17EFB11F1312": { audience: "partner", angle: "Más ventas con un modelo a comisión claramente atribuible.", service_id: "SRV-B2B-PROSPECTING" },
};

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
function redirect(location, status = 303) { return new Response(null, { status, headers: { location }}); }
function shell(title, content) {
  return `<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="LUMEN: inteligencia comercial B2B, sourcing, verificación y coordinación comercial."><title>${esc(title)}</title><style>
:root{--bg:#071019;--panel:#0d1822;--text:#edf6fb;--muted:#9eb1bd;--line:#1c3545;--accent:#d8ff66;--accent2:#8ed7ff}*{box-sizing:border-box}body{margin:0;background:linear-gradient(180deg,#061019,#09131c 55%,#071019);color:var(--text);font-family:Inter,system-ui,-apple-system,Segoe UI,Arial,sans-serif;line-height:1.55}a{color:inherit}.wrap{max-width:1120px;margin:auto;padding:0 22px}.nav{min-height:74px;display:flex;gap:18px;align-items:center;justify-content:space-between;border-bottom:1px solid #ffffff12}.brand{font-weight:950;letter-spacing:.2em}.links{display:flex;gap:16px;flex-wrap:wrap}.links a{text-decoration:none;color:var(--muted);font-weight:750}.hero{padding:76px 0 48px}.eyebrow{color:var(--accent);font-weight:900;text-transform:uppercase;letter-spacing:.12em;font-size:12px}h1{font-size:clamp(40px,7vw,70px);line-height:1.02;letter-spacing:-.045em;margin:12px 0 20px}h2{font-size:30px}.lead{font-size:19px;color:var(--muted);max-width:820px}.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}.card,.box{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:24px}.card h3{margin:0 0 8px}.card p,.small{color:var(--muted)}.section{padding:34px 0 58px}.cta,button{display:inline-block;background:var(--accent);color:#071019;text-decoration:none;font-weight:950;padding:13px 18px;border:0;border-radius:10px;cursor:pointer}.price{font-weight:950;color:var(--accent);font-size:22px}.notice{background:#123321;border:1px solid #34784f;padding:12px 14px;border-radius:12px;margin:0 0 18px}.error{background:#3a1818;border:1px solid #7c3b3b;padding:12px 14px;border-radius:12px;margin:0 0 18px}label{display:block;font-weight:800;margin:13px 0 6px}input,select,textarea{width:100%;background:#07151b;border:1px solid #294653;color:var(--text);border-radius:10px;padding:12px;font:inherit}textarea{min-height:140px}.hp{position:absolute;left:-9999px}.footer{border-top:1px solid #ffffff12;padding:28px 0 42px;color:#78909e;font-size:13px}@media(max-width:760px){.grid{grid-template-columns:1fr}.nav{align-items:flex-start;padding:18px 0}.links{justify-content:flex-end}}
</style></head><body><div class="wrap"><nav class="nav"><div class="brand">LUMEN</div><div class="links"><a href="/">Inicio</a><a href="/services">Servicios</a><a href="/intelligence">Intelligence</a><a href="/privacy">Privacidad</a></div></nav>${content}<footer class="footer">© 2026 LUMEN · Inteligencia comercial y sourcing B2B · Argentina</footer></div></body></html>`;
}
function home() {
  return shell("LUMEN | Inteligencia comercial B2B", `<main><section class="hero"><div class="eyebrow">Inteligencia comercial B2B · Argentina</div><h1>Conectamos demanda empresarial con oferta confiable.</h1><p class="lead">LUMEN investiga mercados, detecta oportunidades, identifica compradores y proveedores, organiza cotizaciones y coordina procesos comerciales con evidencia verificable.</p><p><a class="cta" href="/services">Ver servicios</a></p></section><section class="section"><div class="grid"><article class="card"><h3>Detectar</h3><p>Señales de demanda, oportunidades, mercados y necesidades reales.</p></article><article class="card"><h3>Validar</h3><p>Empresas, contactos corporativos y evidencia antes de avanzar.</p></article><article class="card"><h3>Comparar</h3><p>Alternativas de suministro, cotizaciones, condiciones y riesgo.</p></article><article class="card"><h3>Coordinar</h3><p>Outreach, seguimiento, negociación asistida y trazabilidad comercial.</p></article></div></section><section class="section"><div class="box"><h2>Operación con límites claros</h2><p class="small">LUMEN automatiza investigación, priorización y preparación comercial. Contratos vinculantes, movimientos de dinero y compromisos legales permanecen sujetos a autorización humana.</p></div></section></main>`);
}
function services(received=false, selectedService="") {
  const selected = SERVICE_IDS.has(selectedService) ? selectedService : "";
  const list = (items) => `<ul>${items.map((x)=>`<li>${esc(x)}</li>`).join("")}</ul>`;
  const cards = SERVICES.map((s)=>`<article class="card"><div class="eyebrow">Servicio completo</div><h3>${esc(s.name)}</h3><div class="price">Desde USD ${s.from_usd}</div><p>${esc(s.desc)}</p><p><b>Alcance inicial</b><br><span class="small">${esc(s.scope)}</span></p><p><b>Qué necesitás enviarnos</b></p>${list(s.client_inputs)}<p><b>Qué entregamos</b></p>${list(s.deliverables)}<p><b>No incluye</b></p>${list(s.not_included)}<p><a class="cta" href="/services?service=${encodeURIComponent(s.id)}#case">Preparar este caso</a></p></article>`).join("");
  const options = SERVICES.map((s)=>`<option value="${s.id}" ${selected===s.id?"selected":""}>${esc(s.name)} · desde USD ${s.from_usd}</option>`).join("");
  return shell("LUMEN | Servicios", `<main><section class="hero"><div class="eyebrow">Servicios completos</div><h1>Qué hacemos, qué necesitamos y qué recibís.</h1><p class="lead">Cada servicio tiene un alcance explícito. Primero recibimos el caso, confirmamos que podemos ejecutarlo y definimos alcance; recién después corresponde contratar y pagar. No vendemos resultados garantizados ni certificaciones que no podemos emitir.</p></section>${received?'<div class="notice">Consulta recibida. El caso quedó registrado para evaluación. No se realizó ningún cargo.</div>':""}<section class="grid">${cards}</section><section class="section" id="case"><div class="box"><div class="eyebrow">Preparar el caso</div><h2>Decinos exactamente qué necesitás</h2><form method="post" action="/api/services/inquiry"><label>Servicio</label><select name="service_id" required>${options}</select><label>Email de contacto</label><input type="email" name="email" maxlength="180" required autocomplete="email"><label>Requerimiento principal</label><textarea name="need" maxlength="1200" minlength="12" required placeholder="Explicá la decisión que necesitás tomar y los datos principales del caso."></textarea><label>País / mercado / zona <span class="small">(si aplica)</span></label><input name="geography" maxlength="180" placeholder="Ej.: Argentina, Brasil, Unión Europea"><label>Links o referencias <span class="small">(opcional)</span></label><textarea name="links" maxlength="600" placeholder="URLs de proveedor, producto, licitación o documentación pública."></textarea><label>Fecha objetivo <span class="small">(opcional)</span></label><input name="deadline" maxlength="80" placeholder="Ej.: antes del 30/09"><label>Empresa <span class="small">(opcional)</span></label><input name="company" maxlength="180" autocomplete="organization"><label>Nombre <span class="small">(opcional)</span></label><input name="name" maxlength="120" autocomplete="name"><label class="hp">Sitio web<input name="website" tabindex="-1" autocomplete="off"></label><p><button type="submit">Enviar caso para evaluación</button></p></form><p class="small">Este formulario no genera un cobro. Si el caso requiere archivos que no pueden pegarse como texto o enlace, coordinaremos su recepción antes de iniciar el trabajo.</p></div></section></main>`);
}
function intelligence() {
  return shell("LUMEN | Intelligence", `<main><section class="hero"><div class="eyebrow">LUMEN Intelligence</div><h1>Mercado → evidencia → empresa → oportunidad.</h1><p class="lead">Scout y los motores de inteligencia trabajan con fuentes públicas para descubrir, contrastar y priorizar señales comerciales. Una señal no se convierte en oportunidad ejecutable hasta superar los controles de calidad y verificación.</p></section><section class="grid"><article class="card"><h3>Scout / Radar</h3><p>Exploración de mercados, demanda pública, empresas y señales.</p></article><article class="card"><h3>Buyer & Supplier Intelligence</h3><p>Resolución de identidad, canales corporativos, capacidades y encaje.</p></article><article class="card"><h3>Deal & Quote Intelligence</h3><p>Requisitos, comparación de ofertas, márgenes y preparación de negociación.</p></article><article class="card"><h3>Learning Engine</h3><p>Aprendizaje a partir de resultados observados, sin convertir hipótesis en hechos.</p></article></section></main>`);
}
function privacy() {
  return shell("LUMEN | Privacidad", `<main><section class="hero"><div class="eyebrow">Privacidad</div><h1>Datos mínimos para una consulta B2B.</h1><p class="lead">El formulario solicita email, necesidad y opcionalmente nombre y empresa. Se usa para evaluar y responder la consulta comercial. No se crea un pago ni contrato al enviar el formulario.</p></section></main>`);
}
function campaignLanding(audience, token, received=false, error="") {
  const config = CAMPAIGNS[token] || { audience };
  const copy = audience === "supplier"
    ? { title:"Sumate a la red de proveedores de LUMEN", lead:"Contanos qué vende tu empresa. LUMEN evalúa el encaje y sólo acerca oportunidades cuando existe una necesidad B2B compatible.", label:"¿Qué productos o servicios ofrecés?", placeholder:"Ej.: logística internacional, despachos, válvulas industriales, instrumentación...", button:"Analizar mi oportunidad" }
    : audience === "partner"
      ? { title:"Convertí tu catálogo en un canal de oportunidades", lead:"LUMEN puede investigar tu catálogo y detectar oportunidades atribuibles sin quitarte el control de la venta.", label:"¿Qué vendés y qué tipo de partnership te interesa?", placeholder:"Ej.: tenemos un catálogo online y buscamos ventas B2B...", button:"Analizar partnership" }
      : { title:"Decinos qué necesitás. LUMEN investiga alternativas.", lead:"Compartí una necesidad de compra, producto o cotización y LUMEN organiza la investigación comercial sobre evidencia verificable.", label:"¿Qué necesitás comprar o revisar?", placeholder:"Ej.: necesito comparar proveedores para 20 sensores de nivel...", button:"Buscar proveedores" };
  const notice = received ? '<div class="notice"><b>Listo.</b> Recibimos la información y quedó registrada para evaluación comercial.</div>' : '';
  const err = error ? `<div class="error">${esc(error)}</div>` : '';
  return shell(`LUMEN | ${copy.title}`, `<main><section class="hero"><div class="eyebrow">LUMEN B2B</div><h1>${esc(copy.title)}</h1><p class="lead">${esc(copy.lead)}</p>${config.angle?`<p class="small">${esc(config.angle)}</p>`:""}</section><section class="section"><div class="box">${notice}${err}<form method="post" action="/join/${esc(audience)}"><input type="hidden" name="c" value="${esc(token)}"><label>Email de contacto</label><input name="email" type="email" maxlength="180" required autocomplete="email"><label>${esc(copy.label)}</label><textarea name="details" maxlength="1500" minlength="8" required placeholder="${esc(copy.placeholder)}"></textarea><label>Empresa <span class="small">(opcional)</span></label><input name="company" maxlength="180" autocomplete="organization"><label class="hp">Sitio web<input name="website_check" tabindex="-1" autocomplete="off"></label><p><button type="submit">${esc(copy.button)}</button></p></form><p class="small">Enviar esta información no crea una compra, contrato ni cargo.</p></div></section></main>`);
}

async function ensureSchema(env) {
  await env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_public_inquiries (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, service_id TEXT NOT NULL, email TEXT NOT NULL, company TEXT, name TEXT, need TEXT NOT NULL, source TEXT NOT NULL, processed INTEGER NOT NULL DEFAULT 0, processed_at TEXT)").run();
  await env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_public_inquiries_pending ON lumen_public_inquiries(processed, created_at)").run();
}
async function saveInquiry(env, {serviceId,email,company,name,need,source}) {
  await ensureSchema(env);
  const id = `INQ-${crypto.randomUUID()}`;
  await env.DB.prepare("INSERT INTO lumen_public_inquiries(id,created_at,service_id,email,company,name,need,source,processed) VALUES(?,?,?,?,?,?,?,?,0)").bind(id,new Date().toISOString(),serviceId,email,company,name,need,source).run();
  return id;
}
async function handleInquiry(request, env) {
  const form = await request.formData();
  if (clean(form.get("website"),200)) return redirect("/services?result=received");
  const serviceId=clean(form.get("service_id"),80), email=clean(form.get("email"),180).toLowerCase(), company=clean(form.get("company"),180), name=clean(form.get("name"),120), need=clean(form.get("need"),1200);
  const geography=clean(form.get("geography"),180), links=clean(form.get("links"),600), deadline=clean(form.get("deadline"),80);
  if (!SERVICE_IDS.has(serviceId) || need.length < 12 || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return html(shell("Solicitud inválida","<main><section class='hero'><h1>Revisá los datos.</h1><p class='lead'>Necesitamos un email válido, un servicio y una descripción clara del requerimiento.</p></section></main>"),400);
  const compiled=clean([`[REQUERIMIENTO] ${need}`,geography?`[GEOGRAFIA] ${geography}`:"",links?`[REFERENCIAS] ${links}`:"",deadline?`[FECHA OBJETIVO] ${deadline}`:""].filter(Boolean).join(" | "),MAX_NEED);
  await saveInquiry(env,{serviceId,email,company,name,need:compiled,source:"lumen_zero_public_worker"});
  return redirect(`/services?result=received&service=${encodeURIComponent(serviceId)}#case`);
}
async function handleCampaignSubmit(request, env, audience) {
  const form = await request.formData();
  const token = clean(form.get("c"), 40).toUpperCase();
  const cfg = CAMPAIGNS[token];
  if (!cfg || cfg.audience !== audience) return new Response("campaign_not_available",{status:404});
  if (clean(form.get("website_check"),200)) return redirect(`/join/${audience}?c=${encodeURIComponent(token)}&result=received`);
  const email = clean(form.get("email"),180).toLowerCase();
  const company = clean(form.get("company"),180);
  const details = clean(form.get("details"),MAX_NEED);
  if (details.length < 8 || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return html(campaignLanding(audience,token,false,"Completá un email válido y una descripción breve."),400);
  const prefix = audience === "supplier" ? "Red de proveedores B2B" : audience === "partner" ? "Partnership B2B" : "Necesidad de compra B2B";
  await saveInquiry(env,{serviceId:cfg.service_id,email,company,name:"",need:`[${prefix}] ${details}`,source:`lumen_campaign_${audience}_${token}`});
  return redirect(`/join/${audience}?c=${encodeURIComponent(token)}&result=received`);
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
    const method=request.method;
    if (method==="GET" && url.pathname==="/health") return json({ok:true,service:"lumen-zero-public",storage:"cloudflare-d1",inquiry_capture:true,campaign_routes:true,campaign_tokens:Object.keys(CAMPAIGNS).length,instagram_media:true,services:SERVICES.length});
    if (method==="GET" && url.pathname==="/") return html(home());
    if (method==="GET" && url.pathname==="/services") return html(services(url.searchParams.get("result")==="received", clean(url.searchParams.get("service"),80)));
    if (method==="GET" && url.pathname==="/intelligence") return html(intelligence());
    if (method==="GET" && url.pathname==="/privacy") return html(privacy());
    if (method==="GET" && url.pathname.startsWith("/media/instagram/")) return media(url.pathname);
    if (method==="GET" && url.pathname.startsWith("/c/")) {
      const token=clean(url.pathname.split("/").pop(),40).toUpperCase();
      const cfg=CAMPAIGNS[token];
      if (!cfg) return new Response("campaign_not_available",{status:404});
      return redirect(`/join/${cfg.audience}?c=${encodeURIComponent(token)}`,302);
    }
    const joinMatch=url.pathname.match(/^\/join\/(buyer|supplier|partner)$/);
    if (joinMatch && method==="GET") {
      const audience=joinMatch[1], token=clean(url.searchParams.get("c"),40).toUpperCase(), cfg=CAMPAIGNS[token];
      if (!cfg || cfg.audience!==audience) return new Response("campaign_not_available",{status:404});
      return html(campaignLanding(audience,token,url.searchParams.get("result")==="received"));
    }
    if (joinMatch && method==="POST") return handleCampaignSubmit(request,env,joinMatch[1]);
    if (method==="POST" && url.pathname==="/api/services/inquiry") return handleInquiry(request,env);
    if (method==="GET" && url.pathname==="/api/services/catalog") return json({ok:true,contract_version:SERVICE_CONTRACT_VERSION,currency:"USD",services:SERVICES,payment_created:false});
    if (method==="GET" && url.pathname==="/api/services/pricing") return json({currency:"USD",from_usd:59,pricing_mode:"launch_scope_controlled",services:SERVICES,binding:false,payment_created:false});
    return new Response("not_found",{status:404,headers:{"content-type":"text/plain; charset=utf-8"}});
  }
};
