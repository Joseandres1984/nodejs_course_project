const VERSION = "1.0-travel-buyer-storefront";
const DEFAULT_QUERY = "Rio de Janeiro";
const SOURCES = new Set(["web","instagram","organic","direct"]);

function clean(v,n=4000){return String(v??"").trim().slice(0,n);}
function esc(v){return clean(v,4000).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function money(v){if(v==null||v==="")return"";if(typeof v==="object"){const a=v.amount??v.value??v.price??v.recommendedRetailPrice;const c=v.currency??v.currencyCode??"";return a!=null?`${esc(c)} ${esc(a)}`.trim():"";}return esc(v);}
function sourceOf(url){const s=clean(url.searchParams.get("source"),40).toLowerCase();return SOURCES.has(s)?s:"web";}
function publicJson(data,status=200){return Response.json(data,{status,headers:{"cache-control":"no-store","access-control-allow-origin":"*","x-content-type-options":"nosniff","x-lumen-travel-storefront":VERSION}});}

async function recommend(env,text){
  if(!env?.A2A||typeof env.A2A.fetch!=="function")throw new Error("travel_engine_unavailable");
  const u=new URL("https://a2a.internal/travel/affiliate/recommend");u.searchParams.set("text",text);
  const r=await env.A2A.fetch(new Request(u.toString(),{headers:{"user-agent":"LUMEN-Travel-Storefront/1.0"}}));
  const body=await r.text();let data={};try{data=JSON.parse(body);}catch{throw new Error("travel_engine_invalid_response");}
  if(!r.ok||data?.ok===false)throw new Error(clean(data?.error||`travel_engine_${r.status}`,180));
  return data;
}

function trackedPath(rec,plan,source){
  const provider=clean(rec?.providerAffiliateUrl||rec?.productUrl||"",3500);if(!provider)return"";
  const p=new URLSearchParams();p.set("url",provider);p.set("source",source);p.set("campaign",clean(plan?.clickTracking?.campaign||`lumen-${source}-travel`,200));p.set("variant",clean(rec?.ctaVariant||plan?.clickTracking?.variant||"price_availability_v1",120));p.set("preserve","1");if(plan?.destination)p.set("destination",clean(plan.destination,160));if(rec?.productCode)p.set("product_id",clean(rec.productCode,180));return `/travel/go?${p.toString()}`;
}
function titleOf(r,i){return clean(r?.title||r?.name||r?.productTitle||`Experiencia ${i+1}`,240);}
function ratingOf(r){const value=r?.rating??r?.reviews?.combinedAverageRating??r?.reviews?.averageRating;const count=r?.reviewCount??r?.reviews?.totalReviews;return value?`★ ${esc(value)}${count?` · ${esc(count)} reseñas`:""}`:"";}
function priceOf(r){return money(r?.priceFrom??r?.price??r?.pricing?.summary?.fromPrice??r?.pricing?.fromPrice);}
function durationOf(r){const d=r?.duration??r?.itinerary?.duration??r?.durationLabel;return d?esc(typeof d==="string"?d:JSON.stringify(d)):"";}

function cards(plan,source){
  const list=Array.isArray(plan?.recommendations)?plan.recommendations:[];
  if(!list.length)return `<div class="empty"><h2>No encontramos experiencias todavía</h2><p>Probá con otro destino o una consulta más concreta.</p></div>`;
  return list.slice(0,6).map((r,i)=>{const href=trackedPath(r,plan,source);const meta=[ratingOf(r),priceOf(r),durationOf(r)].filter(Boolean).join(" · ");const label=clean(r?.ctaLabel||plan?.clickTracking?.ctaLabel||"Ver precio y disponibilidad",80);return `<article class="card"><div class="tag">Experiencia seleccionada</div><h2>${esc(titleOf(r,i))}</h2>${meta?`<div class="meta">${meta}</div>`:""}<p>Consultá disponibilidad, condiciones y precio final directamente en Viator.</p>${href?`<a class="cta" href="${esc(href)}" rel="nofollow sponsored">${esc(label)} →</a>`:""}</article>`;}).join("");
}

function page(plan,q,source,error=""){
  const destination=clean(plan?.destination||q,160);const count=Array.isArray(plan?.recommendations)?plan.recommendations.length:0;
  return `<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Experiencias en ${esc(destination)} | LUMEN Travel</title><meta name="description" content="Descubrí experiencias y actividades para tu próximo viaje con LUMEN Travel."><style>*{box-sizing:border-box}body{margin:0;background:#07131b;color:#eef5f7;font-family:Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif}a{color:inherit}.wrap{max-width:1120px;margin:auto;padding:28px 20px 70px}.nav{display:flex;justify-content:space-between;align-items:center;margin-bottom:52px}.brand{font-weight:800;letter-spacing:.18em}.pill{font-size:12px;color:#9fc1ca;border:1px solid #254451;padding:8px 12px;border-radius:999px}.hero{max-width:790px;margin-bottom:30px}.eyebrow{color:#efc878;text-transform:uppercase;font-size:12px;font-weight:800;letter-spacing:.16em}.hero h1{font-size:clamp(38px,7vw,72px);line-height:.98;margin:14px 0}.hero p{font-size:18px;color:#b8ced5;line-height:1.6}.search{display:flex;gap:10px;background:#0d202a;padding:10px;border:1px solid #1f3d49;border-radius:18px;max-width:780px;margin:30px 0 18px}.search input{flex:1;background:transparent;border:0;color:#fff;font-size:17px;padding:13px;outline:none}.search button,.cta{border:0;background:#efc878;color:#11202a;font-weight:800;border-radius:12px;padding:14px 18px;text-decoration:none;display:inline-block}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-top:30px}.card,.empty{background:linear-gradient(145deg,#0d202a,#0a1820);border:1px solid #1e3b46;border-radius:20px;padding:24px;min-height:260px}.card h2{font-size:21px;line-height:1.25;margin:14px 0}.card p{color:#a9c1c9;line-height:1.5}.tag{font-size:11px;text-transform:uppercase;letter-spacing:.12em;color:#efc878}.meta{font-size:13px;color:#c9d9de;min-height:21px}.cta{margin-top:12px}.disclosure{margin-top:34px;padding:18px 20px;border-radius:14px;background:#0d202a;color:#9fb6be;font-size:13px;line-height:1.5}.status{color:#efc878;font-size:13px}.error{background:#371a1a;border:1px solid #693535;padding:14px 16px;border-radius:12px;color:#ffd7d7}.foot{margin-top:42px;color:#6e8b95;font-size:12px}@media(max-width:800px){.grid{grid-template-columns:1fr}.search{flex-direction:column}.nav{margin-bottom:35px}.card{min-height:0}}</style></head><body><main class="wrap"><nav class="nav"><div class="brand">LUMEN TRAVEL</div><div class="pill">Experiencias · Viator</div></nav><section class="hero"><div class="eyebrow">Elegí mejor tu viaje</div><h1>Encontrá experiencias que valgan el viaje.</h1><p>Buscamos opciones concretas para tu destino y te llevamos directo a disponibilidad y precio del proveedor.</p></section><form class="search" method="get" action="/travel"><input type="hidden" name="source" value="${esc(source)}"><input name="q" value="${esc(q)}" placeholder="Ej: Cancún, Madrid, Bangkok…" aria-label="Destino"><button type="submit">Buscar experiencias</button></form><div class="status">${error?"":`${count} opciones para ${esc(destination)}`}</div>${error?`<div class="error">${esc(error)}</div>`:`<section class="grid">${cards(plan,source)}</section>`}<div class="disclosure"><strong>Transparencia:</strong> esta página usa enlaces de afiliado. Si reservás a través de ellos, LUMEN puede recibir una comisión sin costo adicional para vos. La reserva, el cobro, las condiciones y el servicio son gestionados por Viator y sus proveedores.</div><div class="foot">LUMEN no realiza reservas ni cargos por tu cuenta · Fuente de tráfico: ${esc(source)}</div></main></body></html>`;
}

export async function handleTravelStorefront(request,env){
  const url=new URL(request.url);const path=url.pathname.replace(/\/+$/g,"")||"/";if(!["/travel","/travel.json","/travel/go"].includes(path))return null;
  if(request.method!=="GET")return publicJson({ok:false,error:"method_not_allowed",version:VERSION},405);
  const source=sourceOf(url);
  if(path==="/travel/go"){
    if(!env?.A2A||typeof env.A2A.fetch!=="function")return publicJson({ok:false,error:"travel_redirect_unavailable",version:VERSION},503);
    const target=new URL("https://a2a.internal/go/viator");for(const [k,v] of url.searchParams.entries())target.searchParams.append(k,v);target.searchParams.set("source",source);
    const upstream=await env.A2A.fetch(new Request(target.toString(),{method:"GET",redirect:"manual",headers:{"user-agent":"LUMEN-Travel-Storefront/1.0"}}));
    const headers=new Headers(upstream.headers);headers.set("cache-control","no-store");headers.set("x-lumen-travel-source",source);return new Response(upstream.body,{status:upstream.status,headers});
  }
  const q=clean(url.searchParams.get("q")||DEFAULT_QUERY,220);
  try{const plan=await recommend(env,q);if(path==="/travel.json")return publicJson({ok:true,version:VERSION,source,query:q,affiliateDisclosure:true,bookingAuthority:false,paymentAuthority:false,plan});return new Response(page(plan,q,source),{headers:{"content-type":"text/html; charset=utf-8","cache-control":"no-store","x-content-type-options":"nosniff","x-lumen-travel-storefront":VERSION}});}catch(error){const message="No pudimos cargar las experiencias en este momento. Probá nuevamente o buscá otro destino.";if(path==="/travel.json")return publicJson({ok:false,version:VERSION,error:clean(error?.message||error,180),bookingAuthority:false,paymentAuthority:false},503);return new Response(page({},q,source,message),{status:503,headers:{"content-type":"text/html; charset=utf-8","cache-control":"no-store","x-content-type-options":"nosniff"}});}
}
