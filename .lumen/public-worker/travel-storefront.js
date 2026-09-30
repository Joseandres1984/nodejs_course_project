const VERSION = "4.0-lumen-travel-complete-trip";
const UI_REVISION = "4.4-continuation-page";
const DEFAULT_QUERY = "Rio de Janeiro";
const SOURCES = new Set(["web", "instagram", "organic", "direct"]);
const MONTHS = ["Enero","Febrero","Marzo","Abril","Mayo","Junio","Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"];
const DESTINATIONS = [
  { code:"GIG", name:"Rio de Janeiro", emoji:"🌊", line:"Cristo Redentor, playas y experiencias cariocas" },
  { code:"CUN", name:"Cancún", emoji:"🏝️", line:"Caribe, cenotes y excursiones de día completo" },
  { code:"MAD", name:"Madrid", emoji:"🇪🇸", line:"Historia, gastronomía y escapadas cercanas" },
  { code:"BKK", name:"Bangkok", emoji:"🇹🇭", line:"Templos, mercados y cultura tailandesa" },
  { code:"SCL", name:"Santiago de Chile", emoji:"🏔️", line:"Cordillera, viñedos y aventuras" },
  { code:"LIM", name:"Lima", emoji:"🇵🇪", line:"Gastronomía, costa y patrimonio" },
  { code:"MVD", name:"Montevideo", emoji:"🇺🇾", line:"Rambla, cultura y escapadas" },
  { code:"GRU", name:"São Paulo", emoji:"🌆", line:"Cultura, sabores y experiencias urbanas" }
];

function clean(value, limit = 4000) { return String(value ?? "").trim().slice(0, limit); }
function esc(value) { return clean(value).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }
function num(value, fallback, min, max) { const n = Number(value); return Number.isFinite(n) ? Math.max(min, Math.min(max, Math.round(n))) : fallback; }
function safeHttps(value) { const raw = clean(value, 2600); if (!raw) return ""; try { const u = new URL(raw); return u.protocol === "https:" ? raw : ""; } catch { return ""; } }
function sourceOf(url) { const source = clean(url.searchParams.get("source"), 40).toLowerCase(); return SOURCES.has(source) ? source : "web"; }
function destinationByCode(code) { return DESTINATIONS.find(x => x.code === clean(code, 8).toUpperCase()) || DESTINATIONS[0]; }
function destinationByName(name) { const q = clean(name, 180).toLowerCase(); return DESTINATIONS.find(x => q.includes(x.name.toLowerCase()) || x.name.toLowerCase().includes(q)) || DESTINATIONS[0]; }
function monthName(month) { return MONTHS[Math.max(1, Math.min(12, Number(month) || 1)) - 1]; }
function money(value, currency = "USD") { const n = Number(value); return Number.isFinite(n) ? `${currency} ${Math.round(n).toLocaleString("es-AR")}` : "—"; }
function publicJson(data, status = 200) { return Response.json(data, { status, headers:{"cache-control":"no-store","access-control-allow-origin":"*","x-content-type-options":"nosniff","x-lumen-travel-storefront":VERSION} }); }

async function recommend(env, text) {
  if (!env?.A2A || typeof env.A2A.fetch !== "function") throw new Error("travel_engine_unavailable");
  const url = new URL("https://a2a.internal/travel/affiliate/recommend");
  url.searchParams.set("text", `Quiero viajar a ${clean(text, 220)}`);
  const response = await env.A2A.fetch(new Request(url.toString(), { headers:{"user-agent":"LUMEN-Travel-Site/4.4"} }));
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data?.ok === false) throw new Error(clean(data?.error || `travel_engine_${response.status}`, 180));
  return data;
}

async function quoteCompleteTrip(env, input) {
  if (!env?.A2A || typeof env.A2A.fetch !== "function") throw new Error("travel_quote_unavailable");
  const response = await env.A2A.fetch(new Request("https://a2a.internal/travel/providers/quote", {
    method:"POST",
    headers:{"content-type":"application/json","user-agent":"LUMEN-Travel-Site/4.4"},
    body:JSON.stringify(input)
  }));
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data?.ok === false) throw new Error(clean(data?.errors?.join(",") || data?.error || `travel_quote_${response.status}`, 180));
  return data;
}

function trackedPath(rec, plan, source) {
  const provider = clean(rec?.providerAffiliateUrl || rec?.productUrl || rec?.affiliateUrl || "", 3500);
  if (!provider) return "";
  const params = new URLSearchParams();
  params.set("url", provider);
  params.set("source", source);
  params.set("campaign", clean(plan?.clickTracking?.campaign || `lumen-${source}-travel`, 200));
  params.set("variant", clean(rec?.ctaVariant || plan?.clickTracking?.variant || "price_availability_v1", 120));
  params.set("preserve", rec?.productSpecific === true ? "1" : "0");
  if (plan?.destination) params.set("destination", clean(plan.destination, 160));
  if (rec?.productCode) params.set("product_id", clean(rec.productCode, 180));
  return `/travel/go?${params.toString()}`;
}

function titleOf(rec, index) { return clean(rec?.title || rec?.name || rec?.productTitle || rec?.label || rec?.searchQuery || `Experiencia ${index + 1}`, 240); }
function priceOf(rec) { const value = rec?.fromPrice ?? rec?.priceFrom ?? rec?.price ?? rec?.pricing?.summary?.fromPrice; const currency = rec?.currency || rec?.pricing?.currency || "USD"; return Number.isFinite(Number(value)) ? `${esc(currency)} ${Number(value).toFixed(0)}` : "Consultar"; }
function imageOf(rec) { return safeHttps(rec?.imageUrl || rec?.image?.url || rec?.images?.[0]?.url || ""); }
function ratingOf(rec) { const value = rec?.rating ?? rec?.reviews?.combinedAverageRating ?? rec?.reviews?.averageRating; const count = rec?.reviewCount ?? rec?.reviews?.totalReviews; return value ? `★ ${esc(value)}${count ? ` (${esc(count)})` : ""}` : "Selección LUMEN"; }

function experienceCards(plan, source) {
  const rows = (Array.isArray(plan?.recommendations) ? plan.recommendations : []).filter(x => x?.productSpecific === true && clean(x?.providerAffiliateUrl || x?.productUrl || x?.affiliateUrl, 3500));
  if (!rows.length) {
    const generic = Array.isArray(plan?.recommendations) ? plan.recommendations[0] : null;
    const href = generic ? trackedPath(generic, plan, source) : "";
    return `<div class="fallback"><div><div class="eyebrow">Experiencias opcionales</div><h3>No cargaron productos concretos todavía.</h3><p>Tu viaje puede continuar igual. LUMEN no inventa fotos ni precios.</p></div>${href ? `<a class="btn secondary" href="${esc(href)}" rel="nofollow sponsored">Explorar Viator →</a>` : ""}</div>`;
  }
  return `<div class="grid">${rows.slice(0,6).map((rec,index) => { const href=trackedPath(rec,plan,source); const image=imageOf(rec); return `<article class="card">${image ? `<img class="photo" src="${esc(image)}" alt="${esc(titleOf(rec,index))}" loading="lazy">` : ""}<div class="card-body"><small>${ratingOf(rec)}</small><h3>${esc(titleOf(rec,index))}</h3><div class="card-foot"><strong>${priceOf(rec)}</strong><a class="btn" href="${esc(href)}" rel="nofollow sponsored">Ver disponibilidad →</a></div></div></article>`; }).join("")}</div>`;
}

function quoteMap(packageQuote) { const map = new Map(); for (const q of Array.isArray(packageQuote?.quotes) ? packageQuote.quotes : []) map.set(clean(q?.component,40),q); return map; }
function quoteAmount(quote) { return Number(quote?.amountUSD || 0); }
function monthOptions(selected) { return MONTHS.map((name,i)=>`<option value="${i+1}" ${i+1===selected?"selected":""}>${name}</option>`).join(""); }
function dayOptions(selected) { return Array.from({length:29},(_,i)=>i+2).map(v=>`<option value="${v}" ${v===selected?"selected":""}>${v} días</option>`).join(""); }
function passengerOptions(selected) { return Array.from({length:8},(_,i)=>i+1).map(v=>`<option value="${v}" ${v===selected?"selected":""}>${v} ${v===1?"pasajero":"pasajeros"}</option>`).join(""); }
function experienceOptions(include) { return `<option value="0" ${include?"":"selected"}>No</option><option value="1" ${include?"selected":""}>Sí</option>`; }

function nav(source, active="package") {
  return `<div class="topbar"><div class="shell nav"><a class="brand" href="/travel?source=${esc(source)}"><span class="mark">L</span><span>LUMEN<small>TRAVEL</small></span></a><div class="tabs"><a class="${active==="experiences"?"active":""}" href="/travel?source=${esc(source)}">Experiencias</a><a class="${active==="package"?"active":""}" href="/travel/package?source=${esc(source)}">Armá tu viaje</a></div></div></div>`;
}

const STYLES = `
*{box-sizing:border-box}body{margin:0;font-family:Inter,system-ui,-apple-system,sans-serif;color:#1d2227;background:#fff}.shell{max-width:1160px;margin:auto;padding:0 20px}.topbar{border-bottom:1px solid #e7e7e7;background:#fff;position:sticky;top:0;z-index:20}.nav{height:70px;display:flex;align-items:center;gap:24px}.brand{display:flex;align-items:center;gap:9px;font-weight:900;text-decoration:none;color:#111;font-size:20px}.mark{width:34px;height:34px;border-radius:10px;background:#0f6b66;color:#fff;display:grid;place-items:center}.brand small{display:block;font-size:8px;letter-spacing:.2em;color:#777}.tabs{display:flex;gap:5px;margin-left:auto}.tabs a{text-decoration:none;color:#596068;padding:9px 11px;border-radius:9px;font-weight:700;font-size:13px}.tabs a.active{background:#eef7f5;color:#0f6b66}.hero{background:linear-gradient(180deg,#f2faf8,#fff);border-bottom:1px solid #eee}.hero-in{padding:44px 0}.eyebrow{font-size:11px;letter-spacing:.13em;text-transform:uppercase;color:#0f6b66;font-weight:900}.hero h1{font-size:clamp(38px,6vw,62px);line-height:1;letter-spacing:-.05em;margin:10px 0 15px}.hero h1 em{font-style:normal;color:#d94e42}.hero p,.muted-text{color:#677078;line-height:1.55}.section{padding:36px 0}.builder-wrap{background:#f5faf9;border:1px solid #d8e7e4;border-radius:16px;padding:22px}.builder{display:grid;grid-template-columns:1fr 1.25fr .75fr 1fr .85fr .9fr .8fr auto;gap:9px;align-items:end}.builder label{font-size:11px;font-weight:800;color:#5d666d}.builder label span{display:block;margin-bottom:6px}.builder input,.builder select,.builder button{width:100%;min-height:48px;border:1px solid #d4d4d4;border-radius:9px;padding:12px;background:#fff;font:inherit}.builder button,.btn{border:0;background:#d94e42;color:#fff;font-weight:800;text-decoration:none;padding:13px 16px;border-radius:9px;display:inline-flex;align-items:center;justify-content:center;cursor:pointer}.btn.secondary{background:#0f6b66}.btn.ghost{background:#fff;color:#0f6b66;border:1px solid #b9cfcb}.result-head{margin-top:24px;border:1px solid #e0e6e4;border-radius:14px;padding:20px}.result-head h2{font-size:29px;margin:5px 0 10px}.pills{display:flex;gap:8px;flex-wrap:wrap}.pill{background:#edf6f4;color:#0f6b66;border-radius:999px;padding:7px 10px;font-size:11px;font-weight:800}.summary{display:grid;grid-template-columns:1fr 320px;gap:16px;margin-top:16px}.components{display:grid;gap:11px}.component,.step{border:1px solid #e0e0e0;border-radius:13px;padding:18px;background:#fff}.component h3,.step h3{margin:4px 0}.component strong{font-size:22px}.component small{color:#0f6b66;font-weight:900}.component p,.step p{font-size:12px;line-height:1.5;color:#687078}.component a,.step a{font-size:12px;font-weight:800;color:#0f6b66;text-decoration:none}.total{background:#172321;color:#fff;border-radius:15px;padding:22px;height:max-content}.total h2{font-size:34px;margin:7px 0}.total p{color:#c8d2cf;font-size:12px;line-height:1.5}.total .btn{width:100%;margin-top:8px}.choice{margin-top:18px;background:#f5faf9;border:1px solid #d8e7e4;border-radius:14px;padding:19px;display:flex;align-items:center;justify-content:space-between;gap:18px}.choice-actions{display:flex;gap:8px;flex-wrap:wrap}.continue-hero{border:1px solid #dce8e5;background:#f5faf9;border-radius:16px;padding:24px}.continue-hero h2{font-size:32px;margin:5px 0 8px}.next{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:18px}.step-number{width:34px;height:34px;border-radius:50%;background:#0f6b66;color:#fff;display:grid;place-items:center;font-weight:900;margin-bottom:10px}.status{display:inline-block;margin-top:8px;border-radius:999px;padding:6px 9px;font-size:10px;font-weight:900}.status.ready{background:#ddf7ee;color:#0b6754}.status.pending{background:#fff0d7;color:#755414}.actions{display:flex;gap:9px;flex-wrap:wrap;margin-top:18px}.notice,.disclosure,.fallback{margin-top:16px;padding:15px;border-radius:11px;background:#fff8e8;border:1px solid #ead9a9;color:#5c5543;font-size:12px;line-height:1.5}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}.card{border:1px solid #ddd;border-radius:13px;overflow:hidden}.photo{width:100%;height:200px;object-fit:cover;background:#eef3f2}.card-body{padding:15px}.card-body h3{font-size:16px}.card-foot{border-top:1px solid #eee;padding-top:12px;display:flex;justify-content:space-between;align-items:center;gap:8px}.footer{border-top:1px solid #eee;padding:25px 20px 35px;color:#777;font-size:11px;display:flex;justify-content:space-between;gap:20px;flex-wrap:wrap}
@media(max-width:1050px){.builder{grid-template-columns:repeat(4,1fr)}}@media(max-width:820px){.builder{grid-template-columns:repeat(2,1fr)}.summary,.next{grid-template-columns:1fr}.grid{grid-template-columns:repeat(2,1fr)}}@media(max-width:620px){.shell{padding:0 15px}.builder,.grid{grid-template-columns:1fr}.choice{flex-direction:column;align-items:stretch}.choice-actions{flex-direction:column}.choice-actions .btn,.actions .btn{width:100%}.hero h1{font-size:40px}.tabs a{font-size:11px;padding:8px}}
`;

function componentCard(title, quote, note, actionLabel) {
  const affiliate = safeHttps(quote?.affiliateUrl);
  return `<article class="component"><small>${esc(clean(quote?.providerMode || "ESTIMATED",80).replaceAll("_"," "))}</small><h3>${esc(title)}</h3><strong>${money(quote?.amountUSD, quote?.currency || "USD")}</strong><p>${esc(note)}</p><span class="muted-text">Fuente: ${esc(quote?.providerName || "LUMEN estimate")}</span>${affiliate ? `<div><a href="${esc(affiliate)}" rel="nofollow sponsored">${esc(actionLabel)} →</a></div>` : ""}</article>`;
}

function experiencesPage(plan, q, source, error="") {
  const destination = clean(plan?.destination || q,160);
  return `<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LUMEN Travel | Experiencias</title><style>${STYLES}</style></head><body>${nav(source,"experiences")}<header class="hero"><div class="shell hero-in"><div class="eyebrow">Experiencias opcionales</div><h1>Sumá algo que <em>valga el viaje.</em></h1><p>Podés explorar experiencias de Viator o armar primero tu viaje base.</p></div></header><main><section class="section"><div class="shell">${error ? `<div class="notice">${esc(error)}</div>` : experienceCards(plan,source)}<div class="actions"><a class="btn secondary" href="/travel/package?destination=${encodeURIComponent(destinationByName(destination).code)}&source=${encodeURIComponent(source)}">Armá tu viaje →</a></div><div class="disclosure"><strong>Transparencia:</strong> LUMEN Travel puede usar enlaces de afiliado. LUMEN no realiza reservas ni procesa pagos.</div></div></section></main><div class="shell footer"><span>© LUMEN Travel</span><span>Gasto autónomo USD 0</span></div></body></html>`;
}

function packageInput(url) {
  const fallbackMonth = ((new Date().getUTCMonth()+2)%12)+1;
  const built = url.searchParams.get("built") === "1" || url.searchParams.has("budget");
  return { originCode:"BUE", destinationCode:destinationByCode(url.searchParams.get("destination")||"GIG").code, durationDays:num(url.searchParams.get("duration"),7,2,30), targetMonth:num(url.searchParams.get("month"),fallbackMonth,1,12), travelersCount:num(url.searchParams.get("travelers"),2,1,8), budgetUSD:num(url.searchParams.get("budget"),2500,100,100000), includeExperiences:url.searchParams.get("experiences") === "1", built };
}

function tripParams(input, source, experiences="0") {
  return new URLSearchParams({source,built:"1",destination:input.destinationCode,duration:String(input.durationDays),month:String(input.targetMonth),travelers:String(input.travelersCount),budget:String(input.budgetUSD),experiences});
}
function packageHref(input,source,experiences="0",anchor="") { return `/travel/package?${tripParams(input,source,experiences).toString()}${anchor}`; }
function continueHref(input,source) { return `/travel/package/continue?${tripParams(input,source,"0").toString()}`; }

function packageForm(input, source) {
  const dest = DESTINATIONS.map(d=>`<option value="${d.code}" ${d.code===input.destinationCode?"selected":""}>${esc(d.name)}</option>`).join("");
  return `<form class="builder" method="get" action="/travel/package#resultado"><input type="hidden" name="source" value="${esc(source)}"><input type="hidden" name="built" value="1"><label><span>Origen</span><select name="origin"><option value="BUE">Buenos Aires</option></select></label><label><span>Destino</span><select name="destination">${dest}</select></label><label><span>Días</span><select name="duration">${dayOptions(input.durationDays)}</select></label><label><span>Mes</span><select name="month">${monthOptions(input.targetMonth)}</select></label><label><span>Pasajeros</span><select name="travelers">${passengerOptions(input.travelersCount)}</select></label><label><span>Presupuesto USD</span><input type="number" min="100" max="100000" name="budget" value="${input.budgetUSD}"></label><label><span>Experiencias</span><select name="experiences">${experienceOptions(input.includeExperiences)}</select></label><button type="submit">Armar viaje</button></form>`;
}

function packageResults(packageQuote,input,source) {
  const destination = destinationByCode(input.destinationCode); const qmap=quoteMap(packageQuote); const flight=qmap.get("FLIGHT"); const hotel=qmap.get("ACCOMMODATION"); const activities=qmap.get("ACTIVITIES"); const base=quoteAmount(flight)+quoteAmount(hotel); const optional=quoteAmount(activities); const diff=Math.abs(input.budgetUSD-base); const within=base>0&&base<=input.budgetUSD;
  const yesHref = input.includeExperiences ? "#experiencias" : packageHref(input,source,"1","#experiencias");
  return `<div id="resultado"><div class="result-head"><div class="eyebrow">Tu viaje ya está armado</div><h2>${esc(destination.name)} · ${esc(monthName(input.targetMonth))}</h2><div class="pills"><span class="pill">${input.durationDays} días</span><span class="pill">${input.travelersCount} ${input.travelersCount===1?"pasajero":"pasajeros"}</span><span class="pill">Presupuesto ${money(input.budgetUSD)}</span><span class="pill">Experiencias: ${input.includeExperiences?"Sí":"No"}</span></div></div><div class="summary"><div class="components">${componentCard("✈️ Vuelo",flight,"Precio orientativo para todos los pasajeros. Se confirma con el proveedor.","Ver vuelo")}${componentCard("🏨 Alojamiento",hotel,"Estimación para la estadía. Se confirma con el partner hotelero.","Ver hotel")}</div><aside class="total"><small>Paquete base · vuelo + alojamiento</small><h2>${money(base)}</h2><p>Presupuesto: ${money(input.budgetUSD)}</p>${within?`<p>✓ Margen aproximado ${money(diff)}</p>`:`<p>${base?`△ Supera el presupuesto por ${money(diff)}`:"Todavía no pudimos calcular el total base."}</p>`}<a class="btn" href="${esc(continueHref(input,source))}">Continuar con este viaje →</a></aside></div><div class="choice"><div><div class="eyebrow">Experiencias · opcional</div><h3>¿Querés sumar experiencias?</h3><p class="muted-text">Estimación opcional: ${money(optional)}. Podés decir que no y seguir directamente al próximo paso del viaje.</p></div><div class="choice-actions"><a class="btn secondary" href="${esc(yesHref)}">Sí, sumar experiencias</a><a class="btn ghost" href="${esc(continueHref(input,source))}">No, seguir con mi viaje →</a></div></div></div>`;
}

function packagePage(packageQuote,plan,input,source,error="") {
  const destination=destinationByCode(input.destinationCode); const show=input.built||Boolean(error);
  return `<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LUMEN Travel | Armá tu viaje</title><style>${STYLES}</style></head><body>${nav(source,"package")}<header class="hero"><div class="shell hero-in"><div class="eyebrow">LUMEN Travel · Viaje completo</div><h1>Armamos el viaje. Vos <em>decidís qué sumar.</em></h1><p>Vuelo + alojamiento forman el viaje base. Las experiencias son opcionales.</p></div></header><main><section class="section"><div class="shell"><div class="builder-wrap"><div class="eyebrow">Armá tu viaje</div><h2>${esc(destination.name)} · ${input.durationDays} días · ${input.travelersCount} ${input.travelersCount===1?"pasajero":"pasajeros"}</h2>${packageForm(input,source)}</div>${show?(error?`<div class="notice">${esc(error)}</div>`:packageResults(packageQuote,input,source)):""}</div></section>${show&&!error&&input.includeExperiences?`<section class="section" id="experiencias"><div class="shell"><div class="eyebrow">Extra opcional</div><h2>Experiencias en ${esc(destination.name)}</h2>${plan?experienceCards(plan,source):`<div class="notice">No pudimos cargar experiencias. Tu viaje base sigue disponible.</div>`}</div></section>`:""}<section class="section"><div class="shell"><div class="disclosure"><strong>Transparencia de afiliados:</strong> LUMEN Travel puede utilizar enlaces de afiliado de Viator y otros partners. LUMEN no crea reservas, no procesa cargos, no almacena tarjetas o pasaportes y mantiene gasto autónomo en USD 0.</div></div></section></main><div class="shell footer"><span>© LUMEN Travel · ${UI_REVISION}</span><span>Reservas y pagos siempre con proveedores externos</span></div></body></html>`;
}

function continuationStep(number,title,quote,readyText,pendingText,buttonLabel) {
  const url=safeHttps(quote?.affiliateUrl); return `<article class="step"><div class="step-number">${number}</div><div class="eyebrow">Paso ${number}</div><h3>${esc(title)}</h3><strong>${money(quote?.amountUSD,quote?.currency||"USD")}</strong><p>${url?esc(readyText):esc(pendingText)}</p>${url?`<a class="btn secondary" href="${esc(url)}" rel="nofollow sponsored">${esc(buttonLabel)} →</a><div><span class="status ready">LISTO PARA CONTINUAR</span></div>`:`<span class="status pending">ENLACE DEL PARTNER PENDIENTE</span>`}</article>`; }

function continuationPage(packageQuote,input,source,error="") {
  const destination=destinationByCode(input.destinationCode); const qmap=quoteMap(packageQuote); const flight=qmap.get("FLIGHT"); const hotel=qmap.get("ACCOMMODATION"); const base=quoteAmount(flight)+quoteAmount(hotel);
  return `<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LUMEN Travel | Continuar viaje</title><style>${STYLES}</style></head><body>${nav(source,"package")}<header class="hero"><div class="shell hero-in"><div class="eyebrow">LUMEN Travel · Continuación</div><h1>Tu viaje base está <em>confirmado.</em></h1><p>Elegiste continuar sin experiencias. Ahora seguimos con vuelo y alojamiento.</p></div></header><main><section class="section"><div class="shell">${error?`<div class="notice">${esc(error)}</div>`:`<div class="continue-hero"><div class="eyebrow">Viaje base</div><h2>${esc(destination.name)} · ${esc(monthName(input.targetMonth))}</h2><div class="pills"><span class="pill">${input.durationDays} días</span><span class="pill">${input.travelersCount} ${input.travelersCount===1?"pasajero":"pasajeros"}</span><span class="pill">Experiencias: No</span><span class="pill">Total estimado ${money(base)}</span></div></div><div class="next">${continuationStep(1,"Elegí tu vuelo",flight,"Abrí el proveedor para revisar horarios, tarifa final y condiciones.","LUMEN ya calculó una referencia de vuelo, pero todavía no recibió un enlace afiliado utilizable para esta búsqueda.","Ver vuelos")}${continuationStep(2,"Elegí tu alojamiento",hotel,"Abrí el partner hotelero para confirmar disponibilidad y precio final.","El alojamiento todavía funciona como estimación. Falta conectar el partner hotelero real para poder continuar a una reserva.","Ver hoteles")}</div><div class="actions"><a class="btn ghost" href="${esc(packageHref(input,source,"0","#resultado"))}">← Volver y editar viaje</a><a class="btn secondary" href="${esc(packageHref(input,source,"1","#experiencias"))}">Agregar experiencias opcionales</a></div><div class="notice"><strong>Qué significa esta pantalla:</strong> el botón “No, seguir con mi viaje” ya no es un ancla. Ahora abre esta etapa real de continuación. Si algún botón de proveedor todavía no aparece, LUMEN muestra exactamente la integración pendiente.</div>`}<div class="disclosure"><strong>Transparencia:</strong> LUMEN no reserva ni cobra. Los pagos y reservas se completan siempre en el proveedor externo.</div></div></section></main><div class="shell footer"><span>© LUMEN Travel · ${UI_REVISION}</span><span>bookingAuthority=false · paymentAuthority=false · autonomousSpendUsd=0</span></div></body></html>`;
}

export async function handleTravelStorefront(request, env) {
  const url=new URL(request.url); const path=url.pathname.replace(/\/+$/g,"")||"/"; const allowed=["/travel","/travel.json","/travel/go","/travel/package","/travel/package.json","/travel/package/continue","/travel/package/continue.json"]; if(!allowed.includes(path)) return null; if(request.method!=="GET") return publicJson({ok:false,error:"method_not_allowed",version:VERSION},405); const source=sourceOf(url);
  if(path==="/travel/go"){ if(!env?.A2A||typeof env.A2A.fetch!=="function") return publicJson({ok:false,error:"travel_redirect_unavailable",version:VERSION},503); const target=new URL("https://a2a.internal/go/viator"); for(const [k,v] of url.searchParams.entries()) target.searchParams.append(k,v); target.searchParams.set("source",source); const upstream=await env.A2A.fetch(new Request(target.toString(),{method:"GET",redirect:"manual",headers:{"user-agent":"LUMEN-Travel-Site/4.4"}})); const headers=new Headers(upstream.headers); headers.set("cache-control","no-store"); headers.set("x-lumen-travel-source",source); return new Response(upstream.body,{status:upstream.status,headers}); }
  if(path.startsWith("/travel/package")){
    const input=packageInput(url); const destination=destinationByCode(input.destinationCode);
    try { const packageQuote=await quoteCompleteTrip(env,{originCode:input.originCode,destinationCode:input.destinationCode,durationDays:input.durationDays,targetMonth:input.targetMonth,travelersCount:input.travelersCount});
      if(path==="/travel/package/continue.json") return publicJson({ok:true,version:VERSION,uiRevision:UI_REVISION,mode:"complete_trip_continuation",source,input:{...input,includeExperiences:false},affiliateDisclosure:true,bookingAuthority:false,paymentAuthority:false,autonomousSpendUsd:0,packageQuote});
      if(path==="/travel/package/continue") return new Response(continuationPage(packageQuote,{...input,includeExperiences:false},source),{headers:{"content-type":"text/html; charset=utf-8","cache-control":"no-store","x-content-type-options":"nosniff","x-lumen-travel-storefront":VERSION}});
      const plan=input.includeExperiences?await recommend(env,destination.name).catch(()=>null):null;
      if(path==="/travel/package.json") return publicJson({ok:true,version:VERSION,uiRevision:UI_REVISION,mode:"complete_trip",source,input,experiencesOptional:true,experiencesIncluded:input.includeExperiences,affiliateDisclosure:true,bookingAuthority:false,paymentAuthority:false,autonomousSpendUsd:0,packageQuote,experiencePlan:plan});
      return new Response(packagePage(packageQuote,plan,input,source),{headers:{"content-type":"text/html; charset=utf-8","cache-control":"no-store","x-content-type-options":"nosniff","x-lumen-travel-storefront":VERSION}});
    } catch(error){ if(path.endsWith(".json")) return publicJson({ok:false,version:VERSION,error:clean(error?.message||error,180),bookingAuthority:false,paymentAuthority:false,autonomousSpendUsd:0},503); const page=path==="/travel/package/continue"?continuationPage({},input,source,"No pudimos cargar la continuación del viaje en este momento."):packagePage({},null,input,source,"No pudimos armar el viaje completo en este momento. Probá nuevamente."); return new Response(page,{status:503,headers:{"content-type":"text/html; charset=utf-8","cache-control":"no-store"}}); }
  }
  const q=clean(url.searchParams.get("q")||DEFAULT_QUERY,220); try { const plan=await recommend(env,q); if(path==="/travel.json") return publicJson({ok:true,version:VERSION,uiRevision:UI_REVISION,source,query:q,completeTripBuilder:true,experiencesOptional:true,affiliateDisclosure:true,bookingAuthority:false,paymentAuthority:false,autonomousSpendUsd:0,plan}); return new Response(experiencesPage(plan,q,source),{headers:{"content-type":"text/html; charset=utf-8","cache-control":"no-store","x-content-type-options":"nosniff","x-lumen-travel-storefront":VERSION}}); } catch(error){ if(path==="/travel.json") return publicJson({ok:false,version:VERSION,error:clean(error?.message||error,180),bookingAuthority:false,paymentAuthority:false,autonomousSpendUsd:0},503); return new Response(experiencesPage({},q,source,"No pudimos cargar las experiencias en este momento. Probá nuevamente."),{status:503,headers:{"content-type":"text/html; charset=utf-8","cache-control":"no-store"}}); }
}
