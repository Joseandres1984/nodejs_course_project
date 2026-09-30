const VERSION = "4.0-lumen-travel-complete-trip";
const DEFAULT_QUERY = "Rio de Janeiro";
const SOURCES = new Set(["web", "instagram", "organic", "direct"]);
const DESTINATIONS = [
  { code: "GIG", name: "Rio de Janeiro", emoji: "🌊", line: "Cristo Redentor, playas y experiencias cariocas" },
  { code: "CUN", name: "Cancún", emoji: "🏝️", line: "Caribe, cenotes y excursiones de día completo" },
  { code: "MAD", name: "Madrid", emoji: "🇪🇸", line: "Historia, gastronomía y escapadas cercanas" },
  { code: "BKK", name: "Bangkok", emoji: "🇹🇭", line: "Templos, mercados y cultura tailandesa" },
  { code: "SCL", name: "Santiago de Chile", emoji: "🏔️", line: "Cordillera, viñedos y aventuras" },
  { code: "LIM", name: "Lima", emoji: "🇵🇪", line: "Gastronomía, costa y patrimonio" },
  { code: "MVD", name: "Montevideo", emoji: "🇺🇾", line: "Rambla, cultura y escapadas" },
  { code: "GRU", name: "São Paulo", emoji: "🌆", line: "Cultura, sabores y experiencias urbanas" }
];

function clean(value, limit = 4000) { return String(value ?? "").trim().slice(0, limit); }
function esc(value) { return clean(value).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }
function num(value, fallback, min, max) { const n = Number(value); return Number.isFinite(n) ? Math.max(min, Math.min(max, Math.round(n))) : fallback; }
function sourceOf(url) { const source = clean(url.searchParams.get("source"), 40).toLowerCase(); return SOURCES.has(source) ? source : "web"; }
function safeHttps(value) { const raw = clean(value, 1800); if (!raw) return ""; try { const u = new URL(raw); return u.protocol === "https:" ? raw : ""; } catch { return ""; } }
function money(value, currency = "USD") { const n = Number(value); return Number.isFinite(n) ? `${currency} ${Math.round(n).toLocaleString("es-AR")}` : "—"; }
function publicJson(data, status = 200) { return Response.json(data, { status, headers: { "cache-control":"no-store", "access-control-allow-origin":"*", "x-content-type-options":"nosniff", "x-lumen-travel-storefront":VERSION } }); }
function destinationByCode(code) { return DESTINATIONS.find(x => x.code === clean(code, 8).toUpperCase()) || DESTINATIONS[0]; }
function destinationByName(name) { const q = clean(name, 180).toLowerCase(); return DESTINATIONS.find(x => q.includes(x.name.toLowerCase()) || x.name.toLowerCase().includes(q)) || DESTINATIONS[0]; }

async function recommend(env, text) {
  if (!env?.A2A || typeof env.A2A.fetch !== "function") throw new Error("travel_engine_unavailable");
  const url = new URL("https://a2a.internal/travel/affiliate/recommend");
  url.searchParams.set("text", `Quiero viajar a ${clean(text, 220)}`);
  const response = await env.A2A.fetch(new Request(url.toString(), { headers: { "user-agent":"LUMEN-Travel-Site/4.0" } }));
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data?.ok === false) throw new Error(clean(data?.error || `travel_engine_${response.status}`, 180));
  return data;
}

async function quoteCompleteTrip(env, input) {
  if (!env?.A2A || typeof env.A2A.fetch !== "function") throw new Error("travel_quote_unavailable");
  const response = await env.A2A.fetch(new Request("https://a2a.internal/travel/providers/quote", {
    method: "POST",
    headers: { "content-type":"application/json", "user-agent":"LUMEN-Travel-Site/4.0" },
    body: JSON.stringify(input)
  }));
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data?.ok === false) throw new Error(clean(data?.errors?.join(",") || data?.error || `travel_quote_${response.status}`, 180));
  return data;
}

function trackedPath(rec, plan, source) {
  const provider = clean(rec?.providerAffiliateUrl || rec?.productUrl || "", 3500);
  if (!provider) return "";
  const params = new URLSearchParams();
  params.set("url", provider); params.set("source", source);
  params.set("campaign", clean(plan?.clickTracking?.campaign || `lumen-${source}-travel`, 200));
  params.set("variant", clean(rec?.ctaVariant || plan?.clickTracking?.variant || "price_availability_v1", 120));
  params.set("preserve", "1");
  if (plan?.destination) params.set("destination", clean(plan.destination, 160));
  if (rec?.productCode) params.set("product_id", clean(rec.productCode, 180));
  return `/travel/go?${params.toString()}`;
}

function titleOf(rec, index) { return clean(rec?.title || rec?.name || rec?.productTitle || `Experiencia ${index + 1}`, 240); }
function priceOf(rec) { const value = rec?.fromPrice ?? rec?.priceFrom ?? rec?.price ?? rec?.pricing?.summary?.fromPrice; const currency = rec?.currency || rec?.pricing?.currency || "USD"; return Number.isFinite(Number(value)) ? `${esc(currency)} ${Number(value).toFixed(0)}` : "Consultar"; }
function imageOf(rec) { return safeHttps(rec?.imageUrl || rec?.image?.url || rec?.images?.[0]?.url || ""); }
function ratingOf(rec) { const value = rec?.rating ?? rec?.reviews?.combinedAverageRating ?? rec?.reviews?.averageRating; const count = rec?.reviewCount ?? rec?.reviews?.totalReviews; return value ? `★ ${esc(value)}${count ? ` (${esc(count)})` : ""}` : "Selección LUMEN"; }

function experienceCards(plan, source) {
  const list = Array.isArray(plan?.recommendations) ? plan.recommendations : [];
  if (!list.length) return `<div class="empty">Todavía no encontramos experiencias concretas para este destino.</div>`;
  return list.slice(0, 6).map((rec, index) => {
    const href = trackedPath(rec, plan, source); const image = imageOf(rec);
    return `<article class="card"><div class="photo">${image ? `<img src="${esc(image)}" alt="${esc(titleOf(rec,index))}" loading="lazy" referrerpolicy="no-referrer">` : `<span>✦</span>`}</div><div class="card-body"><small>${ratingOf(rec)}</small><h3>${esc(titleOf(rec,index))}</h3><div class="card-foot"><div><span>Desde</span><strong>${priceOf(rec)}</strong></div>${href ? `<a class="btn" href="${esc(href)}" rel="nofollow sponsored">Ver disponibilidad →</a>` : ""}</div></div></article>`;
  }).join("");
}

function quoteMap(packageQuote) {
  const map = new Map();
  for (const quote of Array.isArray(packageQuote?.quotes) ? packageQuote.quotes : []) map.set(clean(quote?.component, 40), quote);
  return map;
}

function componentCard(icon, title, quote, note) {
  const amount = money(quote?.amountUSD, quote?.currency || "USD");
  const source = clean(quote?.providerName || "LUMEN estimate", 120);
  const mode = clean(quote?.providerMode || "ESTIMATED", 80).replaceAll("_", " ");
  return `<article class="trip-component"><div class="component-icon">${icon}</div><div><small>${esc(mode)}</small><h3>${esc(title)}</h3><strong>${esc(amount)}</strong><p>${esc(note)}</p><span>Fuente: ${esc(source)}</span></div></article>`;
}

function destinationTiles(source) {
  return DESTINATIONS.map(d => `<a class="destination-tile" href="/travel?q=${encodeURIComponent(d.name)}&source=${encodeURIComponent(source)}"><b>${d.emoji}</b><span><strong>${esc(d.name)}</strong><small>${esc(d.line)}</small></span><i>›</i></a>`).join("");
}

function nav(source, active = "experiences") {
  return `<div class="topbar"><div class="shell nav"><a class="brand" href="/travel?source=${esc(source)}"><span class="brand-mark">L</span><span>LUMEN<small>TRAVEL</small></span></a><div class="tabs"><a class="${active === "experiences" ? "active" : ""}" href="/travel?source=${esc(source)}">Experiencias</a><a class="${active === "package" ? "active" : ""}" href="/travel/package?source=${esc(source)}">Armá tu viaje</a></div><span class="partner">Afiliados + estimaciones transparentes</span></div></div>`;
}

const STYLES = `
*{box-sizing:border-box}body{margin:0;background:#fff;color:#1d2227;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.shell{max-width:1200px;margin:auto;padding:0 22px}.topbar{border-bottom:1px solid #e8e8e8;background:#fff;position:sticky;top:0;z-index:20}.nav{height:70px;display:flex;align-items:center;gap:26px}.brand{display:flex;align-items:center;gap:9px;font-weight:900;text-decoration:none;font-size:20px}.brand-mark{width:30px;height:30px;border-radius:9px;background:#0f6b66;color:#fff;display:grid;place-items:center}.brand small{display:block;font-size:8px;letter-spacing:.22em;color:#747a80}.tabs{display:flex;gap:4px;margin-left:10px}.tabs a{text-decoration:none;padding:10px 12px;border-radius:8px;color:#596068;font-size:13px;font-weight:700}.tabs a.active,.tabs a:hover{background:#f1f7f6;color:#0f6b66}.partner{margin-left:auto;font-size:11px;color:#656b71}.hero{background:linear-gradient(180deg,#f4faf8,#fff);border-bottom:1px solid #eee}.hero-in{padding:54px 0}.eyebrow{text-transform:uppercase;letter-spacing:.12em;color:#0f6b66;font-size:11px;font-weight:900}.hero h1{font-size:clamp(39px,6vw,66px);line-height:1;letter-spacing:-.05em;margin:10px 0 16px;max-width:880px}.hero h1 em{font-style:normal;color:#d94e42}.hero p{max-width:760px;color:#5c636a;font-size:17px;line-height:1.6}.search{display:flex;gap:8px;margin-top:26px;max-width:860px;background:#fff;border:1px solid #d5d5d5;border-radius:12px;padding:8px;box-shadow:0 8px 28px rgba(0,0,0,.07)}.search input,.builder input,.builder select{border:1px solid #d7d7d7;border-radius:9px;padding:13px 12px;background:#fff;font:inherit}.search input{flex:1;border:0;outline:0}.btn,.search button,.builder button{border:0;background:#d94e42;color:#fff;border-radius:9px;padding:13px 16px;font-weight:800;text-decoration:none;cursor:pointer}.btn:hover,.search button:hover,.builder button:hover{background:#c74338}.section{padding:42px 0}.section-head{display:flex;justify-content:space-between;gap:20px;align-items:end;margin-bottom:20px}.section-head h2{font-size:30px;margin:4px 0;letter-spacing:-.03em}.section-head p{max-width:570px;color:#687078;font-size:13px;line-height:1.55}.destinations{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.destination-tile{border:1px solid #e0e0e0;border-radius:12px;padding:16px;display:flex;align-items:center;gap:12px;text-decoration:none}.destination-tile:hover{box-shadow:0 8px 24px rgba(0,0,0,.06)}.destination-tile b{font-size:25px}.destination-tile span{min-width:0}.destination-tile strong,.destination-tile small{display:block}.destination-tile small{margin-top:4px;color:#777;font-size:11px;line-height:1.35}.destination-tile i{margin-left:auto;font-style:normal;font-size:22px;color:#999}.muted{background:#fafafa;border-top:1px solid #eee;border-bottom:1px solid #eee}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:17px}.card{border:1px solid #ddd;border-radius:13px;overflow:hidden;background:#fff}.photo{height:205px;background:#edf3f1;display:grid;place-items:center;color:#0f6b66;font-size:30px}.photo img{width:100%;height:100%;object-fit:cover}.card-body{padding:16px}.card-body small{color:#666}.card-body h3{font-size:16px;line-height:1.35;min-height:44px}.card-foot{border-top:1px solid #eee;padding-top:13px;display:flex;align-items:end;justify-content:space-between;gap:12px}.card-foot span,.trip-component span{display:block;font-size:10px;color:#777}.card-foot strong{display:block;font-size:18px}.builder-wrap{background:#f5faf9;border:1px solid #dce9e6;border-radius:16px;padding:24px}.builder{display:grid;grid-template-columns:1.15fr 1.3fr .7fr .7fr .7fr .8fr;gap:10px;align-items:end}.builder label{font-size:11px;font-weight:800;color:#5e666d}.builder label span{display:block;margin-bottom:6px}.builder input,.builder select{width:100%}.package-summary{margin-top:28px;display:grid;grid-template-columns:1fr 320px;gap:18px}.trip-components{display:grid;gap:12px}.trip-component{display:grid;grid-template-columns:54px 1fr;gap:14px;border:1px solid #e0e0e0;border-radius:13px;padding:18px;background:#fff}.component-icon{width:48px;height:48px;border-radius:12px;background:#eef7f5;display:grid;place-items:center;font-size:23px}.trip-component small{font-size:10px;color:#0f6b66;font-weight:900}.trip-component h3{margin:4px 0;font-size:17px}.trip-component strong{font-size:22px}.trip-component p{color:#666;margin:5px 0;font-size:12px}.total-card{border-radius:15px;background:#172321;color:#fff;padding:23px;height:max-content;position:sticky;top:90px}.total-card small{color:#aebdb9}.total-card h2{font-size:34px;margin:6px 0}.total-card p{font-size:12px;line-height:1.55;color:#c4cfcc}.budget-good{color:#9ff3d4}.budget-over{color:#ffb5ad}.notice{margin-top:16px;padding:14px;border-radius:10px;background:#fff8e8;border:1px solid #ead9a9;color:#5c5543;font-size:11px;line-height:1.5}.disclosure{margin:32px 0;padding:17px;border-radius:11px;background:#fff8e8;border:1px solid #ead9a9;color:#5c5543;font-size:11px;line-height:1.55}.empty,.error{border:1px solid #ddd;border-radius:12px;padding:22px;background:#fff}.error{border-color:#edc1bd;background:#fff7f6;color:#7b302a}.footer{border-top:1px solid #eee;padding:25px 0 35px;color:#777;font-size:11px;display:flex;justify-content:space-between;gap:20px;flex-wrap:wrap}
@media(max-width:980px){.destinations{grid-template-columns:repeat(2,1fr)}.grid{grid-template-columns:repeat(2,1fr)}.builder{grid-template-columns:repeat(2,1fr)}.package-summary{grid-template-columns:1fr}.total-card{position:static}}@media(max-width:680px){.shell{padding:0 15px}.partner{display:none}.tabs{margin-left:auto}.nav{gap:10px}.tabs a{font-size:11px;padding:8px}.hero-in{padding:38px 0}.hero h1{font-size:42px}.search{flex-direction:column}.destinations,.grid,.builder{grid-template-columns:1fr}.card-foot{flex-direction:column;align-items:stretch}.btn{text-align:center}}
`;

function experiencesPage(plan, q, source, error = "") {
  const destination = clean(plan?.destination || q, 160); const count = Array.isArray(plan?.recommendations) ? plan.recommendations.length : 0;
  return `<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LUMEN Travel | Experiencias en ${esc(destination)}</title><style>${STYLES}</style></head><body>${nav(source,"experiences")}<header class="hero"><div class="shell hero-in"><div class="eyebrow">Experiencias para tu próximo viaje</div><h1>Encontrá algo que realmente <em>valga el viaje.</em></h1><p>LUMEN selecciona experiencias y te deriva al proveedor para confirmar disponibilidad, condiciones y precio final.</p><form class="search" method="get" action="/travel"><input type="hidden" name="source" value="${esc(source)}"><input name="q" value="${esc(q)}" placeholder="¿A dónde querés viajar?"><button>Buscar experiencias</button></form></div></header><main><section class="section"><div class="shell"><div class="section-head"><div><div class="eyebrow">Destinos destacados</div><h2>¿Necesitás inspiración?</h2></div><p>Explorá un destino o armá directamente un viaje completo con vuelo, alojamiento y actividades.</p></div><div class="destinations">${destinationTiles(source)}</div></div></section><section class="section muted"><div class="shell"><div class="section-head"><div><div class="eyebrow">Experiencias seleccionadas</div><h2>${error ? "Explorá experiencias" : `${count} opciones en ${esc(destination)}`}</h2></div><p>La reserva y el cobro final se realizan con Viator.</p></div>${error ? `<div class="error">${esc(error)}</div>` : `<div class="grid">${experienceCards(plan,source)}</div>`}</div></section><section class="section"><div class="shell"><div class="builder-wrap"><div class="eyebrow">Nuevo · LUMEN Travel v4</div><h2>¿Querés el viaje completo?</h2><p>Sumá vuelo, hotel estimado y experiencias en un único plan.</p><a class="btn" href="/travel/package?destination=${encodeURIComponent(destinationByName(destination).code)}&source=${encodeURIComponent(source)}">Armá tu viaje →</a></div><div class="disclosure"><strong>Transparencia:</strong> LUMEN Travel utiliza enlaces de afiliado. LUMEN no realiza reservas, no procesa pagos y no almacena datos de pago. Los precios mostrados pueden ser estimados y deben confirmarse con el proveedor.</div></div></section></main><div class="shell footer"><span>© LUMEN Travel</span><span>Fuente: ${esc(source)} · Gasto autónomo USD 0</span></div></body></html>`;
}

function packageForm(input, source) {
  const opts = DESTINATIONS.map(d => `<option value="${d.code}" ${d.code === input.destinationCode ? "selected" : ""}>${esc(d.name)}</option>`).join("");
  return `<form class="builder" method="get" action="/travel/package"><input type="hidden" name="source" value="${esc(source)}"><label><span>Origen</span><select name="origin"><option value="BUE">Buenos Aires</option></select></label><label><span>Destino</span><select name="destination">${opts}</select></label><label><span>Días</span><input type="number" min="1" max="30" name="duration" value="${input.durationDays}"></label><label><span>Mes</span><input type="number" min="1" max="12" name="month" value="${input.targetMonth}"></label><label><span>Viajeros</span><input type="number" min="1" max="8" name="travelers" value="${input.travelersCount}"></label><label><span>Presupuesto USD</span><input type="number" min="100" max="100000" name="budget" value="${input.budgetUSD}"></label><button type="submit">Armar viaje</button></form>`;
}

function packagePage(packageQuote, plan, input, source, error = "") {
  const destination = destinationByCode(input.destinationCode); const qmap = quoteMap(packageQuote); const flight = qmap.get("FLIGHT"); const hotel = qmap.get("ACCOMMODATION"); const activities = qmap.get("ACTIVITIES"); const total = Number(packageQuote?.totals?.quotedComponentsUSD || 0); const within = total > 0 && total <= input.budgetUSD; const diff = Math.abs(input.budgetUSD - total);
  return `<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LUMEN Travel | Viaje completo a ${esc(destination.name)}</title><style>${STYLES}</style></head><body>${nav(source,"package")}<header class="hero"><div class="shell hero-in"><div class="eyebrow">LUMEN Travel v4 · Viaje completo</div><h1>Armamos el viaje. Vos <em>elegís qué reservar.</em></h1><p>Combinamos vuelo, alojamiento y experiencias en un mismo presupuesto. LUMEN recomienda; cada proveedor confirma y cobra su servicio.</p></div></header><main><section class="section"><div class="shell"><div class="builder-wrap"><div class="section-head"><div><div class="eyebrow">Armá tu viaje</div><h2>${esc(destination.name)} · ${input.durationDays} días · ${input.travelersCount} viajero${input.travelersCount === 1 ? "" : "s"}</h2></div><p>Primera versión: vuelos con Aviasales/Travelpayouts cuando hay datos disponibles, alojamiento estimado y actividades Viator.</p></div>${packageForm(input,source)}</div>${error ? `<div class="error" style="margin-top:18px">${esc(error)}</div>` : `<div class="package-summary"><div class="trip-components">${componentCard("✈️","Vuelo",flight,"Precio orientativo para todos los viajeros. Se confirma con el proveedor antes de comprar.")}${componentCard("🏨","Alojamiento",hotel,"Estimación de alojamiento para la estadía. El partner hotelero afiliado es el próximo conector a incorporar.")}${componentCard("🎟️","Experiencias",activities,"Presupuesto orientativo de actividades. Abajo podés abrir experiencias concretas de Viator.")}</div><aside class="total-card"><small>Total orientativo de los componentes</small><h2>${money(total)}</h2><p>Presupuesto indicado: <strong>${money(input.budgetUSD)}</strong></p>${within ? `<p class="budget-good">✓ Queda un margen aproximado de ${money(diff)}.</p>` : `<p class="budget-over">${total ? `△ Supera el presupuesto por aproximadamente ${money(diff)}.` : "Todavía no pudimos calcular el total."}</p>`}<p>Este total no es una tarifa final ni una reserva. Cada servicio se confirma por separado.</p></aside></div>`}<div class="notice"><strong>Cómo monetiza LUMEN:</strong> cuando existe un enlace afiliado configurado, el usuario continúa al partner correspondiente. LUMEN puede recibir una comisión sin costo extra para el viajero. Nunca inventamos una comisión ni contamos una reserva como efectivo hasta tener confirmación del partner.</div></div></section><section class="section muted"><div class="shell"><div class="section-head"><div><div class="eyebrow">Actividades para sumar al viaje</div><h2>Experiencias en ${esc(destination.name)}</h2></div><p>Estas opciones mantienen el tracking de campaña y la atribución de Viator.</p></div>${plan ? `<div class="grid">${experienceCards(plan,source)}</div>` : `<div class="empty">No pudimos cargar experiencias en este momento.</div>`}</div></section><section class="section"><div class="shell"><div class="disclosure"><strong>Transparencia de afiliados:</strong> LUMEN Travel puede utilizar enlaces de afiliado de Viator y otros partners. Los importes pueden ser estimados o provenir de datos de mercado/catálogos. LUMEN no crea reservas, no procesa cargos, no almacena tarjetas o pasaportes y mantiene gasto autónomo en USD 0.</div></div></section></main><div class="shell footer"><span>© LUMEN Travel · Viajes armados por LUMEN</span><span>Reservas y pagos siempre con proveedores externos</span></div></body></html>`;
}

function packageInput(url) {
  const fallbackMonth = ((new Date().getUTCMonth() + 2) % 12) + 1;
  return { originCode: "BUE", destinationCode: destinationByCode(url.searchParams.get("destination") || "GIG").code, durationDays: num(url.searchParams.get("duration"),7,2,30), targetMonth: num(url.searchParams.get("month"),fallbackMonth,1,12), travelersCount: num(url.searchParams.get("travelers"),2,1,8), budgetUSD: num(url.searchParams.get("budget"),2500,100,100000) };
}

export async function handleTravelStorefront(request, env) {
  const url = new URL(request.url); const path = url.pathname.replace(/\/+$/g, "") || "/";
  const allowed = ["/travel","/travel.json","/travel/go","/travel/package","/travel/package.json"];
  if (!allowed.includes(path)) return null;
  if (request.method !== "GET") return publicJson({ ok:false,error:"method_not_allowed",version:VERSION },405);
  const source = sourceOf(url);

  if (path === "/travel/go") {
    if (!env?.A2A || typeof env.A2A.fetch !== "function") return publicJson({ ok:false,error:"travel_redirect_unavailable",version:VERSION },503);
    const target = new URL("https://a2a.internal/go/viator");
    for (const [key,value] of url.searchParams.entries()) target.searchParams.append(key,value);
    target.searchParams.set("source",source);
    const upstream = await env.A2A.fetch(new Request(target.toString(), { method:"GET",redirect:"manual",headers:{"user-agent":"LUMEN-Travel-Site/4.0"} }));
    const headers = new Headers(upstream.headers); headers.set("cache-control","no-store"); headers.set("x-lumen-travel-source",source);
    return new Response(upstream.body,{status:upstream.status,headers});
  }

  if (path.startsWith("/travel/package")) {
    const input = packageInput(url); const destination = destinationByCode(input.destinationCode);
    try {
      const [packageQuote,plan] = await Promise.all([
        quoteCompleteTrip(env,{originCode:input.originCode,destinationCode:input.destinationCode,durationDays:input.durationDays,targetMonth:input.targetMonth,travelersCount:input.travelersCount}),
        recommend(env,destination.name).catch(() => null)
      ]);
      if (path === "/travel/package.json") return publicJson({ ok:true,version:VERSION,mode:"complete_trip",source,input,affiliateDisclosure:true,bookingAuthority:false,paymentAuthority:false,autonomousSpendUsd:0,packageQuote,experiencePlan:plan });
      return new Response(packagePage(packageQuote,plan,input,source),{headers:{"content-type":"text/html; charset=utf-8","cache-control":"no-store","x-content-type-options":"nosniff","x-lumen-travel-storefront":VERSION}});
    } catch (error) {
      if (path === "/travel/package.json") return publicJson({ok:false,version:VERSION,error:clean(error?.message||error,180),bookingAuthority:false,paymentAuthority:false,autonomousSpendUsd:0},503);
      return new Response(packagePage({},null,input,source,"No pudimos armar el viaje completo en este momento. Probá nuevamente."),{status:503,headers:{"content-type":"text/html; charset=utf-8","cache-control":"no-store"}});
    }
  }

  const q = clean(url.searchParams.get("q") || DEFAULT_QUERY,220);
  try {
    const plan = await recommend(env,q);
    if (path === "/travel.json") return publicJson({ok:true,version:VERSION,source,query:q,featuredDestinations:DESTINATIONS.map(x=>x.name),completeTripBuilder:true,affiliateDisclosure:true,bookingAuthority:false,paymentAuthority:false,autonomousSpendUsd:0,plan});
    return new Response(experiencesPage(plan,q,source),{headers:{"content-type":"text/html; charset=utf-8","cache-control":"no-store","x-content-type-options":"nosniff","x-lumen-travel-storefront":VERSION}});
  } catch (error) {
    if (path === "/travel.json") return publicJson({ok:false,version:VERSION,error:clean(error?.message||error,180),bookingAuthority:false,paymentAuthority:false,autonomousSpendUsd:0},503);
    return new Response(experiencesPage({},q,source,"No pudimos cargar las experiencias en este momento. Probá nuevamente."),{status:503,headers:{"content-type":"text/html; charset=utf-8","cache-control":"no-store"}});
  }
}
