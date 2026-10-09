const SERVICE = "lumen-zero-conversion";
const VERSION = "1.4-international-buyer-sales";
const X402_BASE = "https://lumen-zero-x402.lumen-b2b.workers.dev";

const PRODUCT_CONTRACT_VERSION = "2026-09-21-v1";
const PRODUCTS = {"supplier-snapshot":{"id":"MP-SUPPLIER-SNAPSHOT","name":"Supplier Snapshot","price_usd":5,"service_id":"SRV-SUPPLIERCHECK","promise":"Validación rápida de un proveedor con señales públicas para decidir si vale la pena profundizar.","requires":["Nombre o URL del proveedor","País y producto/servicio ofrecido","Qué querés verificar"],"deliverables":["Resumen de identidad y presencia pública","Señales comerciales y alertas visibles","Conclusión breve y próximo paso sugerido"],"not_included":["Informe crediticio","Due diligence legal","Inspección física"],"details_placeholder":"Proveedor/URL, país, producto y qué querés verificar."},"quote-sanity":{"id":"MP-QUOTE-SANITY","name":"Quote Sanity Check","price_usd":7,"service_id":"SRV-QUOTECHECK","promise":"Chequeo rápido de coherencia de una cotización para detectar desvíos o puntos que merecen revisión.","requires":["Precio y condiciones de la cotización","Producto/especificación y cantidad","Moneda y país si se conocen"],"deliverables":["Chequeo de coherencia","Principales alertas o preguntas","Referencias públicas rápidas cuando existan"],"not_included":["Valuación certificada","Garantía de mejor precio"],"details_placeholder":"Pegá los datos de la cotización: producto, especificación, cantidad, precio, moneda y condiciones."},"tender-scan":{"id":"MP-TENDER-SCAN","name":"Tender Quick Scan","price_usd":9,"service_id":"SRV-TENDER-HUNTER","promise":"Escaneo breve de oportunidades públicas de licitación compatibles con una oferta definida.","requires":["Qué vendés","País/región objetivo","Sector o palabras clave"],"deliverables":["Hasta 5 oportunidades/señales relevantes","Fecha, comprador y enlace público","Comentario breve de encaje"],"not_included":["Presentación de oferta","Garantía de adjudicación"],"details_placeholder":"Qué vendés, mercados/sectores objetivo y palabras clave."},"sourcing-5":{"id":"MP-SOURCING-5","name":"Supplier Shortlist 5","price_usd":15,"service_id":"SRV-SOURCING-EXPRESS","promise":"Shortlist de hasta cinco proveedores candidatos para una necesidad concreta.","requires":["Producto y especificación","Cantidad aproximada","País de entrega y restricciones"],"deliverables":["Hasta 5 proveedores candidatos","Links y evidencia pública de encaje","Observaciones para priorizar contactos"],"not_included":["Garantía de stock/precio","Compra o negociación vinculante"],"details_placeholder":"Producto, especificación, cantidad, país de entrega y requisitos obligatorios."},"buyer-signals":{"id":"MP-BUYER-SIGNALS","name":"Buyer Signal Scan","price_usd":19,"service_id":"SRV-B2B-PROSPECTING","promise":"Búsqueda rápida de señales públicas de empresas que podrían comprar una oferta B2B definida.","requires":["Qué vendés","Cliente ideal","Geografía objetivo"],"deliverables":["Hasta 10 empresas/señales candidatas","Motivo de encaje","Canal corporativo público cuando esté disponible"],"not_included":["Garantía de respuesta o venta","Datos personales obtenidos por vías no públicas"],"details_placeholder":"Qué vendés, quién debería comprarlo y en qué mercado querés buscar."},"export-pulse":{"id":"MP-EXPORT-PULSE","name":"Export Market Pulse","price_usd":25,"service_id":"SRV-EXPORT-SCOUT","promise":"Pulso rápido para explorar mercados y señales públicas antes de invertir en una investigación exportadora completa.","requires":["Producto","País de origen","Mercados de interés o tipo de comprador"],"deliverables":["Hasta 3 mercados/señales priorizadas","Actores comerciales públicos relevantes","Barreras visibles y próximo paso"],"not_included":["Asesoramiento aduanero/legal","Garantía de acceso al mercado"],"details_placeholder":"Producto, país de origen, capacidad/certificaciones y mercados o compradores de interés."}};

function clean(value, limit=180) {
  return String(value ?? "").trim().replace(/\s+/g," ").slice(0,limit);
}
function html(value) {
  return String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
}
function cookieValue(req, name) {
  const raw = req.headers.get("cookie") || "";
  for (const part of raw.split(";")) {
    const [k,...rest] = part.trim().split("=");
    if (k === name) return decodeURIComponent(rest.join("="));
  }
  return "";
}
function attribution(url) {
  const q = url.searchParams;
  return {
    source: clean(q.get("src") || "direct", 80),
    medium: clean(q.get("medium") || "web", 80),
    campaign: clean(q.get("campaign") || "", 120),
    creative: clean(q.get("creative") || "", 120),
    offer: clean(q.get("offer") || "", 120),
    lang: q.get("lang") === "en" ? "en" : "es",
    technical_canary: ["1","true","yes"].includes(String(q.get("technical_canary") || "").toLowerCase()) ? 1 : 0,
  };
}
async function ensureSchema(env) {
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_conversion_events (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, event_type TEXT NOT NULL, session_id TEXT NOT NULL, product_id TEXT, product_slug TEXT, source TEXT NOT NULL, medium TEXT NOT NULL, campaign TEXT, creative TEXT, offer_id TEXT, technical_canary INTEGER NOT NULL DEFAULT 0, metadata TEXT)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_conversion_events_type_created ON lumen_conversion_events(event_type,created_at)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_conversion_events_product_created ON lumen_conversion_events(product_id,created_at)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_conversion_leads (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, session_id TEXT NOT NULL, product_id TEXT NOT NULL, product_slug TEXT NOT NULL, email TEXT NOT NULL, company TEXT, details TEXT, source TEXT NOT NULL, medium TEXT NOT NULL, campaign TEXT, creative TEXT, status TEXT NOT NULL DEFAULT 'new', technical_canary INTEGER NOT NULL DEFAULT 0)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_conversion_leads_status_created ON lumen_conversion_leads(status,created_at)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_public_inquiries (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, service_id TEXT NOT NULL, email TEXT NOT NULL, company TEXT, name TEXT, need TEXT NOT NULL, source TEXT NOT NULL, processed INTEGER NOT NULL DEFAULT 0, processed_at TEXT)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_public_inquiries_pending ON lumen_public_inquiries(processed,created_at)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_sales_inbox_alerts (lead_id TEXT PRIMARY KEY, notified_at TEXT NOT NULL, channel TEXT NOT NULL)"),
  ]);
}
async function recordEvent(env, eventType, sessionId, slug, attr, metadata={}) {
  await ensureSchema(env);
  const p = PRODUCTS[slug] || null;
  const id = `CE-${crypto.randomUUID().replaceAll("-","").slice(0,20).toUpperCase()}`;
  await env.DB.prepare("INSERT INTO lumen_conversion_events (id,created_at,event_type,session_id,product_id,product_slug,source,medium,campaign,creative,offer_id,technical_canary,metadata) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)")
    .bind(id,new Date().toISOString(),eventType,sessionId,p?.id || null,slug || null,attr.source,attr.medium,attr.campaign,attr.creative,attr.offer,attr.technical_canary,JSON.stringify(metadata)).run();
  return id;
}
async function syncLeadToCrm(env, {leadId, p, slug, email, company, details, attr}) {
  if (attr.technical_canary) return {synced:false,reason:"technical_canary"};
  const inquiryId = `INQ-CONV-${leadId.replace(/^CL-/,"")}`;
  const need = clean(details,1800) || `Interés comercial en ${p.name} (USD ${p.price_usd}). Solicitud originada en LUMEN Conversion Loop.`;
  const sourceBits = ["lumen_conversion", attr.source, attr.medium, attr.campaign].filter(Boolean).map(x=>clean(x,50));
  const source = clean(sourceBits.join("_"),180);
  await env.DB.prepare("INSERT OR IGNORE INTO lumen_public_inquiries(id,created_at,service_id,email,company,name,need,source,processed) VALUES(?,?,?,?,?,?,?,?,0)")
    .bind(inquiryId,new Date().toISOString(),p.service_id,email,company,"",need,source).run();
  await env.DB.prepare("UPDATE lumen_conversion_leads SET status='crm_synced' WHERE id=?").bind(leadId).run();
  return {synced:true,inquiry_id:inquiryId,service_id:p.service_id,product_slug:slug};
}
function adminAuthorized(req, env) {
  const expected = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500);
  const provided = clean(req.headers.get("x-lumen-admin"), 500);
  return Boolean(expected && provided && expected === provided);
}
async function nextUsdOwnerAlert(env) {
  await ensureSchema(env);
  return env.DB.prepare(`SELECT l.id AS lead_id,l.created_at,l.email,l.company,l.details,l.product_id,l.product_slug,
    e.created_at AS requested_at FROM lumen_conversion_events e
    JOIN lumen_conversion_leads l ON json_extract(e.metadata,'$.lead_id')=l.id
    LEFT JOIN lumen_sales_inbox_alerts a ON a.lead_id=l.id
    WHERE e.event_type='usd_payment_request' AND e.technical_canary=0 AND l.technical_canary=0 AND a.lead_id IS NULL
    ORDER BY e.created_at ASC LIMIT 1`).first();
}
function ownerJson(data, status=200) {
  return Response.json(data,{status,headers:{"cache-control":"no-store","x-content-type-options":"nosniff"}});
}
function session(req) {
  return clean(cookieValue(req,"lumen_sid"),80) || `SID-${crypto.randomUUID().replaceAll("-","").slice(0,20).toUpperCase()}`;
}
function withSession(headers, sid) {
  headers.set("set-cookie",`lumen_sid=${encodeURIComponent(sid)}; Path=/; Max-Age=2592000; HttpOnly; Secure; SameSite=Lax`);
  return headers;
}
function qs(attr) {
  const u = new URLSearchParams();
  if (attr.source) u.set("src",attr.source);
  if (attr.medium) u.set("medium",attr.medium);
  if (attr.campaign) u.set("campaign",attr.campaign);
  if (attr.creative) u.set("creative",attr.creative);
  if (attr.offer) u.set("offer",attr.offer);
  if (attr.lang==="en") u.set("lang","en");
  if (attr.technical_canary) u.set("technical_canary","1");
  return u.toString();
}
function page(title, body, lang="es") {
  return `<!doctype html><html lang="${lang === "en" ? "en" : "es"}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="${lang === "en" ? "B2B sourcing, supplier research, quote review and market intelligence with clear USD pricing. Request a scoped report without crypto." : "LUMEN inteligencia comercial B2B y búsqueda de proveedores."}"><title>${html(title)} · LUMEN</title><style>
  :root{font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#f5f7fb;background:#080b12}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 80% 0,#15233f 0,transparent 36%),#080b12;color:#f5f7fb}.wrap{max-width:920px;margin:auto;padding:28px 20px 64px}.brand{font-size:14px;letter-spacing:.18em;font-weight:800;color:#a8b7d8;margin-bottom:54px}.card{background:rgba(17,23,36,.88);border:1px solid #27334b;border-radius:24px;padding:clamp(24px,5vw,48px);box-shadow:0 28px 90px rgba(0,0,0,.28)}h1{font-size:clamp(38px,7vw,72px);line-height:.98;margin:0 0 22px;letter-spacing:-.045em}.sub{font-size:19px;line-height:1.55;color:#bdc7d9;max-width:720px}.price{font-size:30px;font-weight:800;margin:30px 0 22px}.btn{display:inline-block;background:#f5f7fb;color:#0b1020;text-decoration:none;border:0;border-radius:999px;padding:15px 22px;font-weight:800;cursor:pointer}.secondary{background:transparent;color:#dfe6f3;border:1px solid #44516a}.actions{display:flex;gap:12px;flex-wrap:wrap;margin-top:26px}.truth{margin-top:34px;padding-top:22px;border-top:1px solid #27334b;color:#8f9bb1;font-size:13px;line-height:1.6}form{margin-top:24px;display:grid;gap:12px}input,textarea{width:100%;border-radius:12px;border:1px solid #33405a;background:#0c111c;color:#fff;padding:13px 14px;font:inherit}textarea{min-height:110px;resize:vertical}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px}.product{padding:22px;border:1px solid #27334b;border-radius:18px;background:#0d121d}.product h2{margin:0 0 9px}.product p{color:#aeb9cd;min-height:70px}.product .price{font-size:22px;margin:14px 0}</style></head><body><div class="wrap"><div class="brand">LUMEN · B2B INTELLIGENCE</div>${body}</div></body></html>`;
}
function offerHtml(slug, p, attr) {
  const query = qs(attr);
  const intent = `/intent/${encodeURIComponent(slug)}${query?`?${query}`:""}`;
  const li = (items) => `<ul>${items.map((x)=>`<li>${html(x)}</li>`).join("")}</ul>`;
  return page(p.name,`<main class="card"><div style="color:#8ea1c7;font-weight:700;margin-bottom:14px">MICROSERVICIO · ALCANCE DEFINIDO</div><h1>${html(p.name)}</h1><p class="sub">${html(p.promise)}</p><div class="price">USD ${p.price_usd}</div><h2>Qué necesitamos</h2>${li(p.requires)}<h2>Qué recibís</h2>${li(p.deliverables)}<h2>No incluye</h2>${li(p.not_included)}<div id="consulta" style="margin-top:28px"><h2>Contanos qué necesitás</h2><p class="sub">Para clientes internacionales podés solicitar una forma de pago en USD sin criptomonedas. LUMEN deberá verificar el medio y confirmar las instrucciones antes de cobrar. El pago x402 con USDC continúa disponible.</p><form method="post" action="${html(intent)}"><input name="email" type="email" required maxlength="180" placeholder="Email para recibir el resultado"><input name="company" maxlength="180" placeholder="Empresa (opcional)"><textarea name="details" maxlength="1800" minlength="8" required placeholder="${html(p.details_placeholder)}"></textarea><div class="actions"><button class="btn" type="submit" name="next" value="invoice_usd">Solicitar pago en USD (sin compromiso)</button><button class="btn secondary" type="submit" name="next" value="checkout">Pagar con USDC (x402)</button><button class="btn secondary" type="submit" name="next" value="consult">Sólo consultar</button></div></form></div><div class="truth">Solicitar cobro en USD no genera una factura automática, un cargo ni una reserva confirmada. Los medios internacionales se validan antes de facilitar instrucciones de pago. El checkout con USDC usa x402 sobre Base. Sólo los pagos confirmados se registran como ingreso.</div></main>`);
}
const PRODUCT_EN = {"supplier-snapshot":{"intro":"Check public supplier identity, official channels, and visible commercial signals before deciding whether to proceed.","inputs":["Supplier name or website","Country and product category","What should be checked"],"output":["Public identity and website signals","Visible risks and questions","Concise recommendation with source links"],"excludes":["Credit report","Legal certification","Physical factory inspection"],"placeholder":"Supplier name or URL, country, product, and what you need verified."},"quote-sanity":{"intro":"Spot inconsistencies in a supplier quote and identify price or commercial terms that deserve a closer look.","inputs":["Quotation price and terms","Item specification and quantity","Currency and market"],"output":["Price and terms sanity check","Key concerns and follow-up questions","Public reference signals when available"],"excludes":["Certified valuation","Guaranteed best market price"],"placeholder":"Describe the offer, price, quantity, specifications and commercial conditions."},"tender-scan":{"intro":"Find relevant public tender signals for a specific company, product or service.","inputs":["What you sell","Target region or country","Sector and search terms"],"output":["Up to 5 potential public tender matches","Official notice and visible deadline","Brief fit assessment"],"excludes":["Submitting tenders on your behalf","Guarantee of contract award"],"placeholder":"What you sell, target regions, and keywords."},"sourcing-5":{"intro":"A focused shortlist of up to five potential suppliers for your exact product requirements.","inputs":["Product and required specifications","Approximate quantity","Delivery country and mandatory constraints"],"output":["Up to five supplier candidates","Official websites and public evidence links","Fit gaps and suggested next contacts"],"excludes":["Guaranteed prices or current stock","Purchase orders or binding negotiations","Physical factory audits"],"placeholder":"Product, technical specifications, expected quantity, delivery country, and required certifications."},"buyer-signals":{"intro":"Find public signals of companies that could plausibly need your B2B product or service.","inputs":["What your business sells","Ideal customer profile","Target geography"],"output":["Up to ten publicly evidenced buyer candidates","Reason each might be relevant","Public corporate channels where available"],"excludes":["Guaranteed buyer interest","Private personal contact databases","Automated mass outreach"],"placeholder":"Your product, ideal buyer type, countries and exclusions."},"export-pulse":{"intro":"Explore export markets and publicly observable demand signals before committing to a larger research project.","inputs":["Product and country of origin","Target destinations or buyer types","Known capacity or certifications"],"output":["Up to three priority market signals","Visible sector actors and public sources","Risks and recommended next research step"],"excludes":["Legal or customs advice","Guaranteed market access"],"placeholder":"Product, origin country, capacity, and target markets."}};
function englishOfferHtml(slug, p, attr) {
  const info = PRODUCT_EN[slug];
  const query = qs({...attr,lang:"en"});
  const formAction = "/intent/"+encodeURIComponent(slug)+(query?"?"+query:"");
  const li = items => "<ul>"+items.map(x=>"<li>"+html(x)+"</li>").join("")+"</ul>";
  const content = '<main class="card"><div style="color:#8ea1c7;font-weight:700;margin-bottom:14px">B2B RESEARCH · FIXED SCOPE · REMOTE DELIVERY</div>'
   +'<h1>'+html(p.name)+'</h1><p class="sub">'+html(info.intro)+'</p><div class="price">USD '+p.price_usd+' / report</div>'
   +'<h2>What we need</h2>'+li(info.inputs)+'<h2>What you receive</h2>'+li(info.output)+'<h2>Not included</h2>'+li(info.excludes)
   +'<div id="request" style="margin-top:28px"><h2>Describe your requirement</h2>'
   +'<p class="sub">Request USD payment arrangements without cryptocurrency. We will confirm the scope and a supported payment method before any invoice or charge. USDC/x402 is also available.</p>'
   +'<form method="post" action="'+html(formAction)+'">'
   +'<input name="email" type="email" required maxlength="180" autocomplete="email" placeholder="Your business email">'
   +'<input name="company" maxlength="180" autocomplete="organization" placeholder="Company (optional)">'
   +'<textarea name="details" maxlength="1800" minlength="8" required placeholder="'+html(info.placeholder)+'"></textarea>'
   +'<div class="actions"><button class="btn" type="submit" name="next" value="invoice_usd">Request USD payment details (no charge)</button>'
   +'<button class="btn secondary" type="submit" name="next" value="consult">Ask a question first</button>'
   +'<button class="btn secondary" type="submit" name="next" value="checkout">Pay with USDC (x402)</button></div></form></div>'
   +'<div class="truth">Submitting this form does not create an invoice, contract or payment. Supplier suitability is assessed from verifiable public evidence; no guaranteed stock, pricing or commercial response. Revenue is recognized only after payment is independently confirmed.</div>'
   +'<div class="actions"><a class="btn secondary" href="/en">All services</a><a class="btn secondary" href="/offer/'+slug+'">Español</a></div></main>';
  return page(p.name, content, "en");
}
function englishCatalogHtml(attr) {
  const cards = Object.entries(PRODUCTS).map(([slug,p])=>{
    const q=qs({...attr,lang:"en",campaign:attr.campaign||"english-"+slug});
    return '<article class="product"><h2>'+html(p.name)+'</h2><p>'+html(PRODUCT_EN[slug].intro)+'</p><div class="price">USD '+p.price_usd+'</div><a class="btn" href="/en/offer/'+slug+(q?'?'+q:'')+'">See scope & request quote</a></article>';
  }).join('');
  return page('B2B research and supplier sourcing in USD','<main><h1>Find better suppliers. Check quotes. Move faster.</h1><p class="sub">Scope-first remote B2B research with documented public evidence. Simple fixed USD prices, no credit card or cryptocurrency required just to request an invoice. We confirm delivery scope and payment route before any commitment.</p><div class="grid" style="margin-top:34px">'+cards+'</div><div class="truth">No autonomous purchasing. No guaranteed supplier stock or prices. No charges from submitting a request. Human approval for binding commercial commitments.</div><div class="actions"><a class="btn secondary" href="/catalog">Ver catálogo en español</a></div></main>', 'en');
}
function industrialQuoteAuditHtml(attr, lang="en") {
  // A narrow, source-evidenced demonstration. Reuse the existing validated
  // quote-sanity intake; this path does not issue an invoice or collect payment.
  const en = lang === "en";
  const tracking = qs({...attr,source:attr.source||"industrial-quote-audit",campaign:attr.campaign||"industrial-first-cash-pilot",lang:en?"en":"es"});
  const intent = "/intent/quote-sanity" + (tracking?"?"+tracking:"");
  const title = en ? "Industrial Supplier Quote Review" : "Revisión de cotizaciones industriales";
  const intro = en
    ? "Before approving an industrial purchase, check the part number, specification, quantity, quoted price and missing commercial terms."
    : "Antes de aprobar una compra industrial, revisá marca, modelo, especificaciones, cantidad, precio y condiciones faltantes.";
  const sample = en
    ? ["Specification requires stainless steel AISI 316; quotation states AISI 304 — verify or reject the substitution.","Quoted part number is missing; ask for manufacturer and exact model before comparing prices.","Delivery time is unspecified — request a written lead time and validity date."]
    : ["La especificación exige acero AISI 316; la oferta indica AISI 304 — verificar o rechazar la sustitución.","No se identifica código de parte; pedir fabricante y modelo exacto antes de comparar precios.","No figura plazo de entrega; solicitarlo por escrito junto con la vigencia de la oferta."];
  const li=sample.map(x=>"<li>"+html(x)+"</li>").join("");
  const content='<main class="card">'
    +'<div style="color:#a8b7d8;font-weight:800;letter-spacing:.12em">'+(en?"PROCUREMENT · RFQ · TECHNICAL COMPLIANCE":"COMPRAS · RFQ · CUMPLIMIENTO TÉCNICO")+'</div>'
    +'<h1>'+html(title)+'</h1><p class="sub">'+html(intro)+'</p>'
    +'<div class="price">USD 7 '+(en?"/ scoped review":"/ revisión acotada")+'</div>'
    +'<h2>'+(en?"Illustrative findings":"Ejemplo ilustrativo de observaciones")+'</h2>'
    +'<p>'+(en?"Fictional example — not a review of a real supplier:":"Ejemplo ficticio — no corresponde a una oferta real:")+'</p><ul>'+li+'</ul>'
    +'<h2>'+(en?"You receive":"Qué recibís")+'</h2><p class="sub">'+(en
      ?"A concise review with specification mismatches, commercial gaps, questions for the supplier and source-backed public price signals when available. No fabricated market prices or verified-stock claims."
      :"Un informe breve con incompatibilidades técnicas, condiciones comerciales faltantes, consultas al proveedor y referencias públicas de precio cuando existan. Sin precios ni disponibilidad inventados.")+'</p>'
    +'<h2>'+(en?"Submit one quotation for review":"Enviá una cotización para revisar")+'</h2>'
    +'<p class="sub">'+(en?"Include product, brand/model, quantity, unit price, currency, delivery country and offered terms. Do not include confidential or restricted technical data.":"Indicá producto, marca/modelo, cantidad, precio, moneda, país de entrega y condiciones. No incluyas información técnica confidencial o restringida.")+'</p>'
    +'<form method="post" action="'+html(intent)+'">'
    +'<input name="email" type="email" maxlength="180" autocomplete="email" required placeholder="'+(en?"Business email":"Correo comercial")+'">'
    +'<input name="company" maxlength="180" autocomplete="organization" placeholder="'+(en?"Company (optional)":"Empresa (opcional)")+'">'
    +'<textarea name="details" maxlength="1800" minlength="8" required placeholder="'+(en?"Product, exact specification, manufacturer/part number, quoted quantity and price, country and terms":"Producto, especificación, fabricante/código, cantidad y precio cotizados, país y condiciones")+'"></textarea>'
    +'<div class="actions"><button class="btn" type="submit" name="next" value="invoice_usd">'+(en?"Request review & USD payment options":"Solicitar revisión y opciones de pago USD")+'</button>'
    +'<button class="btn secondary" type="submit" name="next" value="consult">'+(en?"Ask before buying":"Consultar antes de comprar")+'</button>'
    +'<button class="btn secondary" type="submit" name="next" value="checkout">'+(en?"USDC / x402 checkout":"Pagar USDC / x402")+'</button></div></form>'
    +'<div class="truth">'+(en
      ?"This request does not create a charge or binding order. Scope, capability and payment method are confirmed before work. Public price checks are indicative, not a certified valuation; no guarantee of a best price, supplier response or purchase outcome. Only provider-verified settlement counts as revenue."
      :"La solicitud no crea un cargo ni una orden vinculante. Se confirma alcance, capacidad y medio de pago antes de trabajar. Las referencias públicas son orientativas, no tasación certificada; no garantizamos mejor precio ni resultados de compra. Sólo se registra ingreso tras verificar el cobro.")+'</div>'
    +'<div class="actions"><a class="btn secondary" href="'+(en?"/en":"/catalog")+'">'+(en?"Other services":"Otros servicios")+'</a><a class="btn secondary" href="'+(en?"/industrial-rfq":"/en/industrial-rfq")+'">'+(en?"Español":"English")+'</a></div>'
    +'</main>';
  return page(title,content,en?"en":"es");
}

function catalogHtml(attr) {
  const cards = Object.entries(PRODUCTS).map(([slug,p]) => {
    const q = qs({...attr, campaign:attr.campaign || `catalog-${slug}`});
    return `<article class="product"><h2>${html(p.name)}</h2><p>${html(p.promise)}</p><div class="price">USD ${p.price_usd}</div><a class="btn" href="/offer/${slug}${q?`?${q}`:""}">Ver oferta</a></article>`;
  }).join("");
  return page("Catálogo",`<main><h1>Servicios que empiezan en minutos.</h1><p class="sub">Microproductos B2B de bajo costo para convertir una necesidad concreta en una próxima acción verificable.</p><div class="grid" style="margin-top:34px">${cards}</div></main>`);
}
async function stats(env) {
  await ensureSchema(env);
  const counts = await env.DB.prepare("SELECT event_type, COUNT(*) AS n FROM lumen_conversion_events WHERE technical_canary=0 GROUP BY event_type").all();
  const products = await env.DB.prepare("SELECT product_id, product_slug, event_type, COUNT(*) AS n FROM lumen_conversion_events WHERE technical_canary=0 GROUP BY product_id,product_slug,event_type ORDER BY product_slug,event_type").all();
  const leads = await env.DB.prepare("SELECT COUNT(*) AS n FROM lumen_conversion_leads WHERE technical_canary=0").first();
  const crm = await env.DB.prepare("SELECT COUNT(*) AS n FROM lumen_conversion_leads WHERE technical_canary=0 AND status='crm_synced'").first();
  let settled = { orders:0, realizedRevenueUsd:0, byProduct:[] };
  try {
    const total = await env.DB.prepare("SELECT COUNT(*) AS n, COALESCE(SUM(amount_usd),0) AS usd FROM lumen_x402_receipts WHERE status='settled_verified'").first();
    const by = await env.DB.prepare("SELECT product_id, COUNT(*) AS orders, COALESCE(SUM(amount_usd),0) AS usd FROM lumen_x402_receipts WHERE status='settled_verified' GROUP BY product_id ORDER BY product_id").all();
    settled = {orders:Number(total?.n || 0),realizedRevenueUsd:Number(total?.usd || 0),byProduct:by.results || []};
  } catch (_) {}
  return {
    ok:true, service:SERVICE, version:VERSION,
    funnel:Object.fromEntries((counts.results || []).map(r=>[r.event_type,Number(r.n || 0)])),
    qualifiedLeads:Number(leads?.n || 0),
    crmSyncedLeads:Number(crm?.n || 0),
    productEvents:products.results || [],
    settlement:settled,
    attributionTruth:{
      preCheckoutBySource:true,
      settlementByProduct:true,
      exactSourceToSettlement:false,
      reason:"x402 receipt ledger does not yet persist conversion session/campaign correlation",
    },
    crmTruth:{qualifiedIntentCreatesCanonicalInquiry:true,technicalCanariesExcluded:true},
    revenueRule:"Only x402 receipts with status settled_verified count as realized revenue",
  };
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/,"") || "/";
    const attr = attribution(url);
    if (path === "/en" || path.startsWith("/en/")) attr.lang = "en";
    const sid = session(request);
    const headers = withSession(new Headers({"cache-control":"no-store","x-content-type-options":"nosniff"}),sid);
    try {
      if (request.method === "GET" && path === "/health") {
        await ensureSchema(env);
        return Response.json({ok:true,service:SERVICE,version:VERSION,x402:X402_BASE,paidSpend:false,crmBridge:true,productContractVersion:PRODUCT_CONTRACT_VERSION,requirementsBeforeHumanCheckout:true,briefLinkedCheckout:true},{headers});
      }
      if (request.method === "GET" && (path === "/industrial-rfq" || path === "/en/industrial-rfq")) {
        const language=path.startsWith("/en/")?"en":"es";
        await recordEvent(env,"visit",sid,"quote-sanity",{...attr,source:attr.source||"industrial-quote-audit",campaign:attr.campaign||"industrial-first-cash-pilot"},{path,landing:"industrial-rfq",paid:false});
        headers.set("content-type","text/html; charset=utf-8");
        return new Response(industrialQuoteAuditHtml(attr,language),{status:200,headers});
      }
      if (request.method === "GET" && (path === "/en" || path === "/en/catalog")) {
        await recordEvent(env,"catalog_visit",sid,null,attr);
        headers.set("content-type","text/html; charset=utf-8");
        return new Response(englishCatalogHtml(attr),{status:200,headers});
      }
      if (request.method === "GET" && (path === "/" || path === "/catalog")) {
        if (path === "/catalog") await recordEvent(env,"catalog_visit",sid,null,attr);
        headers.set("content-type","text/html; charset=utf-8");
        return new Response(catalogHtml(attr),{status:200,headers});
      }
      if (request.method === "GET" && path === "/catalog.json") {
        return Response.json({ok:true,products:Object.entries(PRODUCTS).map(([slug,p])=>({...p,slug,offerUrl:`${url.origin}/offer/${slug}`,checkoutUrl:`${X402_BASE}/buy/${slug}`})),paidMediaSpend:false,crmBridge:true},{headers});
      }
      if (request.method === "GET" && path === "/stats") {
        return Response.json(await stats(env),{headers});
      }
      if (path === "/sales/pending-usd" && request.method === "GET") {
        if (!adminAuthorized(request,env)) return ownerJson({ok:false,error:"admin_token_required"},403);
        const lead=await nextUsdOwnerAlert(env);
        return ownerJson({ok:true,pending:Boolean(lead),lead:lead || null,chargeCreated:false,ownerOnly:true});
      }
      if (path === "/sales/ack-usd-alert" && request.method === "POST") {
        if (!adminAuthorized(request,env)) return ownerJson({ok:false,error:"admin_token_required"},403);
        let body; try { body=await request.json(); } catch { return ownerJson({ok:false,error:"invalid_json"},400); }
        const leadId=clean(body?.lead_id,80);
        if (!/^CL-[A-F0-9]{20}$/.test(leadId)) return ownerJson({ok:false,error:"invalid_lead_id"},400);
        await ensureSchema(env);
        const result=await env.DB.prepare(`INSERT OR IGNORE INTO lumen_sales_inbox_alerts(lead_id,notified_at,channel)
          SELECT ?,?,'owner_smtp' WHERE EXISTS
          (SELECT 1 FROM lumen_conversion_events e WHERE e.event_type='usd_payment_request'
            AND e.technical_canary=0 AND json_extract(e.metadata,'$.lead_id')=?)`)
          .bind(leadId,new Date().toISOString(),leadId).run();
        return ownerJson({ok:true,acknowledged:Boolean(result?.meta?.changes || result?.changes),leadId,notAPayment:true});
      }
      const offerMatch = path.match(/^\/(?:en\/)?offer\/([a-z0-9-]+)$/);
      if (request.method === "GET" && offerMatch) {
        const slug = offerMatch[1]; const p = PRODUCTS[slug];
        if (!p) return new Response("Not found",{status:404,headers});
        await recordEvent(env,"visit",sid,slug,attr,{path});
        headers.set("content-type","text/html; charset=utf-8");
        return new Response(attr.lang === "en" ? englishOfferHtml(slug,p,attr) : offerHtml(slug,p,attr),{status:200,headers});
      }
      const goMatch = path.match(/^\/go\/([a-z0-9-]+)$/);
      if (request.method === "GET" && goMatch) {
        const slug=goMatch[1]; const p=PRODUCTS[slug];
        if (!p) return new Response("Not found",{status:404,headers});
        await ensureSchema(env);
        const requestedBriefId=clean(url.searchParams.get("brief_id"),80);
        let brief=null;
        if (!attr.technical_canary) {
          brief=requestedBriefId
            ? await env.DB.prepare("SELECT id,email,company,details FROM lumen_conversion_leads WHERE id=? AND session_id=? AND product_slug=? AND technical_canary=0 AND LENGTH(TRIM(COALESCE(details,'')))>=8 LIMIT 1").bind(requestedBriefId,sid,slug).first()
            : await env.DB.prepare("SELECT id,email,company,details FROM lumen_conversion_leads WHERE session_id=? AND product_slug=? AND technical_canary=0 AND LENGTH(TRIM(COALESCE(details,'')))>=8 ORDER BY created_at DESC LIMIT 1").bind(sid,slug).first();
          if (!brief) { const q=qs(attr); headers.set("location",`/offer/${slug}${q?`?${q}`:""}`); return new Response(null,{status:303,headers}); }
        }
        const briefId=clean(brief?.id || requestedBriefId,80);
        const eventId=await recordEvent(env,"checkout_started",sid,slug,attr,{destination:`${X402_BASE}/buy/${slug}`,requirementsCaptured:true,brief_id:briefId});
        const target=new URL(`${X402_BASE}/buy/${slug}`);
        target.searchParams.set("conversion_event",eventId);
        target.searchParams.set("conversion_session",sid);
        if (briefId) target.searchParams.set("brief_id",briefId);
        if (attr.campaign) target.searchParams.set("campaign",attr.campaign);
        if (attr.source) target.searchParams.set("source",attr.source);
        if (attr.medium) target.searchParams.set("medium",attr.medium);
        if (attr.creative) target.searchParams.set("creative",attr.creative);
        headers.set("location",target.toString());
        return new Response(null,{status:302,headers});
      }
      const intentMatch = path.match(/^\/intent\/([a-z0-9-]+)$/);
      if (request.method === "POST" && intentMatch) {
        const slug=intentMatch[1]; const p=PRODUCTS[slug];
        if (!p) return new Response("Not found",{status:404,headers});
        const form=await request.formData();
        const email=clean(form.get("email"),180).toLowerCase();
        const company=clean(form.get("company"),180);
        const details=clean(form.get("details"),1800);
        const requestedNext=clean(form.get("next"),20);
        const next=["checkout","consult","invoice_usd"].includes(requestedNext) ? requestedNext : "consult";
        const paymentPreference=next === "invoice_usd" ? "USD_MANUAL_REVIEW" : next === "checkout" ? "X402_USDC" : "CONTACT_ONLY";
        if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || details.length < 8) return new Response("Necesitamos un email válido y un requerimiento claro.",{status:400,headers});
        await ensureSchema(env);
        const leadId=`CL-${crypto.randomUUID().replaceAll("-","").slice(0,20).toUpperCase()}`;
        await env.DB.prepare("INSERT INTO lumen_conversion_leads (id,created_at,session_id,product_id,product_slug,email,company,details,source,medium,campaign,creative,status,technical_canary) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
          .bind(leadId,new Date().toISOString(),sid,p.id,slug,email,company,details,attr.source,attr.medium,attr.campaign,attr.creative,"new",attr.technical_canary).run();
        const crmDetails=next === "invoice_usd" ? `${details}\n[El comprador solicita instrucciones de pago en USD. Revisar disponibilidad y confirmar el medio antes de enviar enlace o factura. Ningún pago realizado.]` : details;
        const crm=await syncLeadToCrm(env,{leadId,p,slug,email,company,details:crmDetails,attr});
        await recordEvent(env,"qualified_intent",sid,slug,attr,{lead_id:leadId,crm,next,paymentPreference});
        const qparams=new URLSearchParams(qs(attr));
        qparams.set("brief_id",leadId);
        const go=`/go/${slug}?${qparams.toString()}`;
        if (next === "checkout") { await recordEvent(env,"requirements_captured",sid,slug,attr,{lead_id:leadId,brief_id:leadId}); headers.set("location",go); return new Response(null,{status:303,headers}); }
        if (next === "invoice_usd") {
          await recordEvent(env,"usd_payment_request",sid,slug,attr,{lead_id:leadId,paymentPreference,charged:false,invoiceCreated:false});
          headers.set("content-type","text/html; charset=utf-8");
          const thankYou = attr.lang === "en" ? `<main class="card"><h1>Request received</h1><p class="sub">We recorded your ${html(p.name)} research request and preference for USD billing. Reference: ${html(leadId)}. We must confirm the scope, availability, and supported payment method before issuing any invoice or payment instructions. No payment has been made.</p><div class="actions"><a class="btn secondary" href="/en">All services</a></div></main>` : `<main class="card"><h1>Solicitud recibida</h1><p class="sub">LUMEN registró el requerimiento de ${html(p.name)} y tu preferencia por pagar en USD. Referencia: ${html(leadId)}. El equipo debe comprobar el medio de cobro internacional y acordar los detalles antes de facilitar instrucciones o generar una factura. Todavía no se realizó ningún pago.</p><div class="actions"><a class="btn secondary" href="/catalog">Volver al catálogo</a></div></main>`;
          return new Response(page(attr.lang === "en" ? "USD payment request received" : "Solicitud de pago USD registrada",thankYou,attr.lang),{status:200,headers});
        }
        headers.set("content-type","text/html; charset=utf-8");
        const consultBody=attr.lang === "en" ? `<main class="card"><h1>Question received</h1><p class="sub">LUMEN saved your request for ${html(p.name)}. No charge was created.</p><div class="actions"><a class="btn secondary" href="/en">Back to services</a></div></main>` : `<main class="card"><h1>Consulta recibida.</h1><p class="sub">LUMEN guardó el requerimiento de ${html(p.name)}. No se realizó ningún cargo.</p><div class="actions"><a class="btn" href="${html(go)}">Continuar al pago · USD ${p.price_usd}</a><a class="btn secondary" href="/catalog">Ver catálogo</a></div></main>`;
        return new Response(page(attr.lang === "en" ? "Question received" : "Consulta recibida",consultBody,attr.lang),{status:200,headers});
      }
      return new Response("Not found",{status:404,headers});
    } catch (error) {
      return Response.json({ok:false,error:"conversion_worker_error",detail:clean(error?.message,300)},{status:500,headers});
    }
  }
};
