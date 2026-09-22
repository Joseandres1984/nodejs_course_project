const A2A_INTERNAL = "https://a2a.internal";

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
}

function clean(value, limit = 1200) {
  return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit);
}

function money(value) {
  const n = Number(value || 0);
  return Number.isFinite(n) ? n.toLocaleString("en-US", {maximumFractionDigits: 0}) : "0";
}

function redirect(location, status = 303) {
  return new Response(null, {status, headers: {location, "cache-control":"no-store"}});
}

function html(body, status = 200) {
  return new Response(body, {
    status,
    headers: {
      "content-type":"text/html; charset=utf-8",
      "cache-control":"no-store",
      "x-content-type-options":"nosniff",
      "referrer-policy":"strict-origin-when-cross-origin",
      "content-security-policy":"default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
    }
  });
}

async function getCatalog(binding, origin) {
  if (!binding || typeof binding.fetch !== "function") throw new Error("catalog_binding_unavailable");
  const response = await binding.fetch(new Request(`${A2A_INTERNAL}/revenue/catalog`, {
    method:"GET",
    headers:{"accept":"application/json","x-lumen-public-origin":origin,"user-agent":"LUMEN-Public-Revenue/1.0"}
  }));
  if (!response.ok) throw new Error(`catalog_upstream_${response.status}`);
  const data = await response.json();
  if (!data || data.version !== "1.0-revenue-expansion" || !data.sourcing_success || !Array.isArray(data.subscriptions) || !Array.isArray(data.machine_offers)) {
    throw new Error("catalog_schema_invalid");
  }
  return data;
}

function catalogFallback() {
  return {
    name:"LUMEN Revenue Expansion",
    version:"unavailable",
    currency:"USD",
    sourcing_success:null,
    subscriptions:[],
    machine_offers:[]
  };
}

function page(catalog, origin, {selected="", sent=false, error=""}={}) {
  const sourcing = catalog.sourcing_success;
  const subscriptions = catalog.subscriptions || [];
  const machines = catalog.machine_offers || [];
  const validIds = new Set([sourcing?.id, ...subscriptions.map(x=>x.id), ...machines.map(x=>x.id)].filter(Boolean));
  const selectedId = validIds.has(selected) ? selected : (subscriptions[0]?.id || sourcing?.id || "");
  const options = [
    ...(sourcing ? [{id:sourcing.id,name:sourcing.name}] : []),
    ...subscriptions.map(x=>({id:x.id,name:x.name})),
    ...machines.map(x=>({id:x.id,name:`${x.name} · API`}))
  ].map(x=>`<option value="${esc(x.id)}"${x.id===selectedId?" selected":""}>${esc(x.name)}</option>`).join("");

  const planCards = subscriptions.map((p, i)=>`<article class="plan ${i===1?"featured":""}">
    ${i===1?'<div class="badge">Más elegido</div>':''}
    <div class="kicker">Suscripción mensual</div>
    <h3>${esc(p.name)}</h3>
    <div class="price"><span>USD</span> ${money(p.price_usd)}<small>/mes</small></div>
    <p>${esc(p.description)}</p>
    <a class="button ${i===1?"primary":"secondary"}" href="/catalogo?offer=${encodeURIComponent(p.id)}#solicitud">Solicitar este plan</a>
  </article>`).join("");

  const machineCards = machines.map((p)=>`<article class="machine-card">
    <div><div class="machine-name">${esc(p.name)}</div><div class="machine-id">${esc(p.id)}</div></div>
    <div class="machine-price">USD ${money(p.price_usd)} <span>/ consulta</span></div>
  </article>`).join("");

  const successPct = sourcing?.success_fee_pct || {};
  const successBlock = sourcing ? `<section class="success-card" id="sourcing-success">
    <div class="success-copy">
      <div class="kicker">Resultado primero</div>
      <h2>${esc(sourcing.name)}</h2>
      <p>Nos contás una necesidad B2B concreta. LUMEN investiga, verifica y compara proveedores. El marco de success fee sólo aplica si la operación se completa y se confirma.</p>
      <div class="chips"><span>USD 0 de anticipo</span><span>Demanda verificable</span><span>Sin compra autónoma</span></div>
    </div>
    <div class="success-number"><small>Success fee objetivo</small><strong>${money(successPct.target)}%</strong><span>rango ${money(successPct.min)}–${money(successPct.max)}%</span><a class="button primary" href="/catalogo?offer=${encodeURIComponent(sourcing.id)}#solicitud">Presentar necesidad</a></div>
  </section>` : "";

  const status = sent
    ? '<div class="alert success">Solicitud recibida. LUMEN la registró para verificar alcance y encaje. No se generó ningún cargo.</div>'
    : error
      ? `<div class="alert error">No pudimos registrar la solicitud (${esc(error)}). Podés volver a intentarlo sin que se haya generado ningún cargo.</div>`
      : "";

  const unavailable = catalog.version === "unavailable"
    ? '<div class="alert error">El catálogo comercial está temporalmente sin conexión. Los formularios permanecen deshabilitados hasta recuperar la fuente canónica.</div>'
    : "";

  return `<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="Catálogo comercial de LUMEN: sourcing por éxito, radar de licitaciones, señales de compra y servicios de inteligencia B2B."><title>Catálogo | LUMEN B2B</title><style>
:root{--bg:#061019;--bg2:#091722;--panel:#0c1a25;--panel2:#102331;--text:#f3f8fb;--muted:#9db0bc;--line:#1c394a;--acid:#d9ff67;--cyan:#8edcff;--soft:#122431;--danger:#ff9b9b}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:radial-gradient(circle at 82% 8%,#15374a66,transparent 31%),radial-gradient(circle at 10% 35%,#24411c33,transparent 27%),linear-gradient(180deg,var(--bg),var(--bg2) 54%,var(--bg));color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;line-height:1.55}a{color:inherit}.wrap{max-width:1180px;margin:auto;padding:0 24px}.nav{height:76px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #ffffff12}.brand{font-weight:950;letter-spacing:.22em;font-size:16px;text-decoration:none}.navlinks{display:flex;gap:22px;align-items:center}.navlinks a{font-size:14px;text-decoration:none;color:var(--muted);font-weight:760}.navlinks a.active{color:var(--text)}.navlinks .nav-cta{border:1px solid #385466;border-radius:10px;padding:9px 13px;color:var(--text)}.hero{padding:86px 0 56px;display:grid;grid-template-columns:1.35fr .65fr;gap:46px;align-items:end}.kicker{color:var(--acid);font-size:12px;font-weight:900;letter-spacing:.14em;text-transform:uppercase}.hero h1{font-size:clamp(46px,7vw,78px);line-height:.98;letter-spacing:-.05em;margin:13px 0 24px;max-width:900px}.hero p{font-size:20px;color:var(--muted);max-width:780px;margin:0}.hero-aside{border-left:1px solid var(--line);padding-left:28px;color:var(--muted)}.hero-aside strong{display:block;color:var(--text);font-size:17px;margin-bottom:8px}.section{padding:42px 0 70px}.section-head{display:flex;justify-content:space-between;gap:24px;align-items:end;margin-bottom:24px}.section-head h2,.success-card h2{font-size:clamp(31px,4vw,46px);line-height:1.05;letter-spacing:-.035em;margin:8px 0 0}.section-head p{max-width:560px;color:var(--muted);margin:0}.success-card{display:grid;grid-template-columns:1.4fr .6fr;gap:32px;padding:34px;border:1px solid #54702c;border-radius:24px;background:linear-gradient(135deg,#102519,#0d1c26 62%);box-shadow:0 24px 70px #0005}.success-copy p{color:#b5c5bd;font-size:18px;max-width:700px}.chips{display:flex;gap:8px;flex-wrap:wrap;margin-top:20px}.chips span{border:1px solid #44602e;background:#14291b;border-radius:999px;padding:7px 10px;font-size:12px;font-weight:800;color:#dfffa0}.success-number{display:flex;flex-direction:column;align-items:flex-start;justify-content:center;border-left:1px solid #37522c;padding-left:30px}.success-number small{color:var(--muted);font-weight:800}.success-number strong{font-size:68px;line-height:1;color:var(--acid);letter-spacing:-.05em;margin:8px 0 2px}.success-number>span{color:var(--muted);margin-bottom:20px}.plans{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.plan{position:relative;border:1px solid var(--line);border-radius:20px;padding:25px;background:linear-gradient(180deg,var(--panel2),var(--panel));min-height:330px;display:flex;flex-direction:column}.plan.featured{border-color:#6d8f34;box-shadow:0 0 0 1px #d9ff6730 inset}.badge{position:absolute;top:14px;right:14px;background:var(--acid);color:#081117;font-size:10px;text-transform:uppercase;letter-spacing:.08em;font-weight:950;padding:5px 8px;border-radius:999px}.plan h3{font-size:22px;margin:9px 0 13px}.price{font-size:39px;font-weight:950;letter-spacing:-.04em}.price>span{font-size:12px;color:var(--muted);letter-spacing:.04em}.price small{font-size:13px;color:var(--muted);font-weight:700;letter-spacing:0}.plan p{color:var(--muted);font-size:14px;flex:1}.button{display:inline-flex;justify-content:center;align-items:center;text-decoration:none;border-radius:11px;padding:12px 15px;font-weight:900;font-size:14px}.button.primary{background:var(--acid);color:#071019}.button.secondary{border:1px solid #365365;background:#0a1923;color:var(--text)}.machine-shell{display:grid;grid-template-columns:.75fr 1.25fr;gap:28px;background:#081720;border:1px solid var(--line);border-radius:22px;padding:30px}.machine-intro p{color:var(--muted)}.machine-intro .button{margin-top:8px}.machines{display:grid;grid-template-columns:repeat(2,1fr);gap:9px}.machine-card{display:flex;justify-content:space-between;gap:16px;align-items:center;border:1px solid #1b394a;background:#0e202c;border-radius:13px;padding:15px}.machine-name{font-weight:850}.machine-id{font-size:10px;color:#6f8a9b;margin-top:3px}.machine-price{font-weight:950;color:var(--cyan);white-space:nowrap}.machine-price span{display:block;text-align:right;color:var(--muted);font-size:10px;font-weight:600}.steps{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.step{border-top:1px solid var(--line);padding:20px 6px 0}.step-number{color:var(--cyan);font-size:12px;font-weight:950}.step h3{margin:8px 0}.step p{color:var(--muted)}.request-grid{display:grid;grid-template-columns:.75fr 1.25fr;gap:34px}.request-copy p{color:var(--muted)}.truth{font-size:13px;border-left:3px solid var(--acid);padding-left:13px;color:#b8c6ce;margin-top:22px}.form{background:var(--panel);border:1px solid var(--line);border-radius:20px;padding:26px}.alert{padding:13px 15px;border-radius:11px;margin-bottom:16px;font-size:14px}.alert.success{background:#12331f;border:1px solid #38734d;color:#d7ffe4}.alert.error{background:#35181b;border:1px solid #713b40;color:#ffd7da}label{display:block;font-size:12px;font-weight:900;color:#c4d1d8;margin:14px 0 6px;text-transform:uppercase;letter-spacing:.05em}input,select,textarea{width:100%;border:1px solid #29495c;background:#07151e;color:var(--text);font:inherit;border-radius:10px;padding:12px 13px;outline:none}input:focus,select:focus,textarea:focus{border-color:var(--cyan)}textarea{min-height:150px;resize:vertical}.two{display:grid;grid-template-columns:1fr 1fr;gap:12px}.help{font-size:12px;color:#738b99;margin-top:9px}.hp{position:absolute;left:-10000px}.footer{border-top:1px solid #ffffff12;padding:30px 0 42px;color:#718894;font-size:12px;display:flex;justify-content:space-between;gap:20px}.footer a{text-decoration:none;color:#8fa5b1}@media(max-width:980px){.plans{grid-template-columns:repeat(2,1fr)}.hero,.success-card,.machine-shell,.request-grid{grid-template-columns:1fr}.success-number{border-left:0;border-top:1px solid #37522c;padding:24px 0 0}.hero-aside{border-left:0;padding-left:0}.machines{grid-template-columns:1fr}}@media(max-width:640px){.wrap{padding:0 17px}.nav{height:auto;padding:18px 0;align-items:flex-start}.navlinks{gap:11px;flex-wrap:wrap;justify-content:flex-end}.navlinks a{font-size:12px}.hero{padding-top:55px}.plans,.steps,.two{grid-template-columns:1fr}.section{padding-bottom:52px}.machine-card{align-items:flex-start}.footer{flex-direction:column}.success-number strong{font-size:58px}}
</style></head><body><div class="wrap"><nav class="nav"><a class="brand" href="/">LUMEN</a><div class="navlinks"><a href="/">Inicio</a><a href="/services">Servicios</a><a class="active" href="/catalogo">Catálogo</a><a href="/store">Intelligence</a><a class="nav-cta" href="#solicitud">Hablar con LUMEN</a></div></nav>
<main><section class="hero"><div><div class="kicker">Revenue Expansion · catálogo público</div><h1>Inteligencia B2B que se puede contratar.</h1><p>Encontrá proveedores, monitoreá compras públicas, detectá señales de demanda o consumí inteligencia por consulta. Un solo sistema, con evidencia y límites comerciales claros.</p></div><aside class="hero-aside"><strong>Catálogo conectado en vivo</strong>Esta página se alimenta del mismo Revenue Catalog que usan LUMEN y otros agentes. La vidriera humana y la API comparten una única fuente de verdad.</aside></section>
${unavailable}${successBlock}
<section class="section" id="planes"><div class="section-head"><div><div class="kicker">Ingreso recurrente</div><h2>Radar e inteligencia mensual</h2></div><p>Planes para empresas que necesitan señales útiles de mercado de forma continua, sin revisar fuentes manualmente todos los días.</p></div><div class="plans">${planCards || '<div class="alert error">Planes temporalmente no disponibles.</div>'}</div></section>
<section class="section"><div class="machine-shell"><div class="machine-intro"><div class="kicker">Machine Store · 24/7</div><h2>Inteligencia por consulta</h2><p>Servicios de bajo ticket preparados para agentes, automatizaciones y compradores que necesitan una respuesta puntual. Los pagos se procesan por el checkout x402 existente.</p><a class="button secondary" href="/store">Abrir Machine Store</a></div><div class="machines">${machineCards || '<div class="alert error">Machine Store temporalmente sin catálogo.</div>'}</div></div></section>
<section class="section"><div class="section-head"><div><div class="kicker">Cómo funciona</div><h2>De necesidad a evidencia.</h2></div></div><div class="steps"><article class="step"><div class="step-number">01 · CONTEXTO</div><h3>Contás qué necesitás</h3><p>Producto, mercado, categoría o decisión. Cuanto más concreto el objetivo, mejor el análisis.</p></article><article class="step"><div class="step-number">02 · INVESTIGACIÓN</div><h3>LUMEN verifica</h3><p>Busca evidencia pública, compara alternativas y separa señales verificables de ruido.</p></article><article class="step"><div class="step-number">03 · DECISIÓN</div><h3>Recibís una salida accionable</h3><p>Shortlist, radar, señales o análisis. Los compromisos vinculantes y pagos permanecen controlados.</p></article></div></section>
<section class="section request-grid" id="solicitud"><div class="request-copy"><div class="kicker">Empezar</div><h2>Presentá tu caso.</h2><p>No hace falta comprar nada para enviarlo. LUMEN primero registra y verifica el alcance. La solicitud no acepta contratos, no crea órdenes y no genera cargos automáticamente.</p><div class="truth"><strong>Regla de verdad:</strong> una consulta o cotización no es una venta. LUMEN sólo registra ingresos realizados cuando existe evidencia verificable de pago liquidado o de la transacción completada correspondiente.</div></div><form class="form" method="post" action="/catalogo/request">${status}<label for="offer_id">Qué te interesa</label><select id="offer_id" name="offer_id" required>${options}</select><div class="two"><div><label for="company">Empresa</label><input id="company" name="company" maxlength="240" autocomplete="organization" placeholder="Nombre de la empresa"></div><div><label for="contact">Contacto</label><input id="contact" name="contact" maxlength="300" autocomplete="email" placeholder="Email o canal corporativo" required></div></div><div class="two"><div><label for="category">Categoría / industria</label><input id="category" name="category" maxlength="240" placeholder="Ej. instrumentación industrial"></div><div><label for="website">Web</label><input id="website" name="website" maxlength="300" inputmode="url" placeholder="https://..."></div></div><label for="details">Qué necesitás resolver</label><textarea id="details" name="details" maxlength="4000" required placeholder="Contanos el producto, alcance, mercado, cantidad, fechas o decisión que querés tomar."></textarea><label class="hp" for="website_confirm">Dejar vacío</label><input class="hp" id="website_confirm" name="website_confirm" tabindex="-1" autocomplete="off"><button class="button primary" type="submit"${catalog.version==="unavailable"?" disabled":""}>Enviar solicitud</button><div class="help">Al enviar, se crea una consulta no verificada. No se genera ningún cargo ni compromiso vinculante.</div></form></section></main>
<footer class="footer"><span>© 2026 LUMEN · Inteligencia comercial y sourcing B2B</span><span><a href="/privacy">Privacidad</a> · <a href="/services">Servicios</a> · <a href="/store">Machine Store</a></span></footer></div></body></html>`;
}

async function forwardInquiry(request, binding, origin) {
  if (!binding || typeof binding.fetch !== "function") return {ok:false,error:"catalog_binding_unavailable"};
  let form;
  try { form = await request.formData(); } catch (_) { return {ok:false,error:"invalid_form"}; }
  if (clean(form.get("website_confirm"), 80)) return {ok:true,bot:true,offerId:""};
  const payload = {
    offer_id: clean(form.get("offer_id"), 100),
    company: clean(form.get("company"), 240),
    contact: clean(form.get("contact"), 300),
    category: clean(form.get("category"), 240),
    website: clean(form.get("website"), 300),
    details: clean(form.get("details"), 4000)
  };
  if (!payload.offer_id || !payload.contact || !payload.details) return {ok:false,error:"missing_required_fields",offerId:payload.offer_id};
  const upstream = await binding.fetch(new Request(`${A2A_INTERNAL}/revenue/request`, {
    method:"POST",
    headers:{"content-type":"application/json","accept":"application/json","x-lumen-public-origin":origin,"user-agent":"LUMEN-Public-Revenue/1.0"},
    body:JSON.stringify(payload)
  }));
  let data = {};
  try { data = await upstream.json(); } catch (_) {}
  if (!upstream.ok || data?.ok !== true) return {ok:false,error:clean(data?.error || `upstream_${upstream.status}`, 120),offerId:payload.offer_id};
  return {ok:true,offerId:payload.offer_id,inquiryId:clean(data?.inquiry_id,120)};
}

export async function handleRevenueStorefront(request, env) {
  const url = new URL(request.url);
  const path = url.pathname.replace(/\/+$/, "") || "/";
  const origin = url.origin;

  if (request.method === "GET" && ["/catalogo","/soluciones","/planes","/revenue"].includes(path)) {
    let catalog;
    let failure = "";
    try { catalog = await getCatalog(env.A2A, origin); }
    catch (error) { catalog = catalogFallback(); failure = clean(error?.message || error, 120); }
    const selected = clean(url.searchParams.get("offer"), 100);
    const sent = url.searchParams.get("sent") === "1";
    const error = clean(url.searchParams.get("error") || failure, 120);
    return html(page(catalog, origin, {selected,sent,error}), failure ? 503 : 200);
  }

  if (request.method === "GET" && path === "/catalogo.json") {
    try {
      const catalog = await getCatalog(env.A2A, origin);
      return Response.json(catalog, {headers:{"cache-control":"public, max-age=60","x-content-type-options":"nosniff"}});
    } catch (error) {
      return Response.json({ok:false,error:clean(error?.message || error,120)}, {status:503,headers:{"cache-control":"no-store"}});
    }
  }

  if (request.method === "POST" && path === "/catalogo/request") {
    const result = await forwardInquiry(request, env.A2A, origin);
    if (result.ok) {
      const qs = new URLSearchParams({sent:"1"});
      if (result.offerId) qs.set("offer", result.offerId);
      return redirect(`/catalogo?${qs.toString()}#solicitud`);
    }
    const qs = new URLSearchParams({error:result.error || "request_failed"});
    if (result.offerId) qs.set("offer", result.offerId);
    return redirect(`/catalogo?${qs.toString()}#solicitud`);
  }

  return null;
}
