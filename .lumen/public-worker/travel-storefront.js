const VERSION = "3.0-lumen-travel-marketplace";
const DEFAULT_QUERY = "Rio de Janeiro";
const SOURCES = new Set(["web", "instagram", "organic", "direct"]);
const FEATURED_DESTINATIONS = [
  { name: "Rio de Janeiro", emoji: "🌊", line: "Cristo Redentor, playas y experiencias cariocas" },
  { name: "Cancún", emoji: "🏝️", line: "Caribe, cenotes y excursiones de día completo" },
  { name: "Madrid", emoji: "🇪🇸", line: "Historia, gastronomía y escapadas cercanas" },
  { name: "Bangkok", emoji: "🇹🇭", line: "Templos, mercados y cultura tailandesa" },
  { name: "Santiago de Chile", emoji: "🏔️", line: "Cordillera, viñedos y aventuras" },
  { name: "Lima", emoji: "🇵🇪", line: "Gastronomía, costa y patrimonio" },
  { name: "Montevideo", emoji: "🇺🇾", line: "Rambla, cultura y escapadas" },
  { name: "São Paulo", emoji: "🌆", line: "Cultura, sabores y experiencias urbanas" }
];

function clean(value, limit = 4000) {
  return String(value ?? "").trim().slice(0, limit);
}

function esc(value) {
  return clean(value, 4000).replace(/[&<>"']/g, char => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  }[char]));
}

function money(value, currency = "USD") {
  if (value == null || value === "") return "";
  if (typeof value === "object") {
    const amount = value.amount ?? value.value ?? value.price ?? value.recommendedRetailPrice;
    const code = value.currency ?? value.currencyCode ?? currency;
    return amount != null ? `${esc(code)} ${esc(amount)}`.trim() : "";
  }
  const numeric = Number(value);
  return Number.isFinite(numeric) ? `${esc(currency)} ${numeric.toFixed(2)}` : esc(value);
}

function sourceOf(url) {
  const source = clean(url.searchParams.get("source"), 40).toLowerCase();
  return SOURCES.has(source) ? source : "web";
}

function publicJson(data, status = 200) {
  return Response.json(data, {
    status,
    headers: {
      "cache-control": "no-store",
      "access-control-allow-origin": "*",
      "x-content-type-options": "nosniff",
      "x-lumen-travel-storefront": VERSION
    }
  });
}

function safeImage(value) {
  const raw = clean(value, 1600);
  if (!raw) return "";
  try {
    const url = new URL(raw);
    return url.protocol === "https:" ? raw : "";
  } catch {
    return "";
  }
}

function durationLabel(minutes) {
  const numeric = Number(minutes);
  if (!Number.isFinite(numeric) || numeric <= 0) return "";
  if (numeric < 60) return `${Math.round(numeric)} min`;
  const hours = Math.floor(numeric / 60);
  const mins = Math.round(numeric % 60);
  return mins ? `${hours} h ${mins} min` : `${hours} h`;
}

function flagLabel(flag) {
  const labels = {
    FREE_CANCELLATION: "Cancelación gratuita",
    SKIP_THE_LINE: "Entrada rápida",
    PRIVATE_TOUR: "Tour privado",
    LIKELY_TO_SELL_OUT: "Alta demanda",
    INSTANT_CONFIRMATION: "Confirmación inmediata"
  };
  return labels[clean(flag, 80).toUpperCase()] || "";
}

async function recommend(env, text) {
  if (!env?.A2A || typeof env.A2A.fetch !== "function") throw new Error("travel_engine_unavailable");
  const url = new URL("https://a2a.internal/travel/affiliate/recommend");
  url.searchParams.set("text", `Quiero viajar a ${clean(text, 220)}`);
  const response = await env.A2A.fetch(new Request(url.toString(), {
    headers: { "user-agent": "LUMEN-Travel-Site/3.0" }
  }));
  const raw = await response.text();
  let data = {};
  try {
    data = JSON.parse(raw);
  } catch {
    throw new Error("travel_engine_invalid_response");
  }
  if (!response.ok || data?.ok === false) {
    throw new Error(clean(data?.error || `travel_engine_${response.status}`, 180));
  }
  return data;
}

function trackedPath(rec, plan, source) {
  const provider = clean(rec?.providerAffiliateUrl || rec?.productUrl || "", 3500);
  if (!provider) return "";
  const params = new URLSearchParams();
  params.set("url", provider);
  params.set("source", source);
  params.set("campaign", clean(plan?.clickTracking?.campaign || `lumen-${source}-travel`, 200));
  params.set("variant", clean(rec?.ctaVariant || plan?.clickTracking?.variant || "price_availability_v1", 120));
  params.set("preserve", "1");
  if (plan?.destination) params.set("destination", clean(plan.destination, 160));
  if (rec?.productCode) params.set("product_id", clean(rec.productCode, 180));
  return `/travel/go?${params.toString()}`;
}

function titleOf(rec, index) {
  return clean(rec?.title || rec?.name || rec?.productTitle || `Experiencia ${index + 1}`, 240);
}

function ratingParts(rec) {
  const value = rec?.rating ?? rec?.reviews?.combinedAverageRating ?? rec?.reviews?.averageRating;
  const count = rec?.reviewCount ?? rec?.reviews?.totalReviews;
  return {
    value: value ? clean(value, 20) : "",
    count: count ? clean(count, 30) : ""
  };
}

function priceOf(rec) {
  return money(
    rec?.fromPrice ?? rec?.priceFrom ?? rec?.price ?? rec?.pricing?.summary?.fromPrice ?? rec?.pricing?.fromPrice,
    rec?.currency || rec?.pricing?.currency || "USD"
  );
}

function durationOf(rec) {
  return durationLabel(rec?.durationMinutes) || clean(rec?.durationLabel || "", 80);
}

function imageOf(rec) {
  return safeImage(rec?.imageUrl || rec?.image?.url || rec?.images?.[0]?.url || "");
}

function descriptionOf(rec) {
  const description = clean(rec?.description || "", 260);
  return description || "Consultá disponibilidad, condiciones y precio final en Viator.";
}

function badgesOf(rec) {
  const flags = Array.isArray(rec?.flags) ? rec.flags : [];
  return flags.map(flagLabel).filter(Boolean).slice(0, 2);
}

function destinationTiles(source) {
  return FEATURED_DESTINATIONS.map(destination => `
    <a class="destination-tile" href="/travel?q=${encodeURIComponent(destination.name)}&source=${encodeURIComponent(source)}">
      <div class="destination-icon">${destination.emoji}</div>
      <div class="destination-copy">
        <strong>${esc(destination.name)}</strong>
        <span>${esc(destination.line)}</span>
      </div>
      <span class="chevron">›</span>
    </a>`).join("");
}

function cards(plan, source) {
  const list = Array.isArray(plan?.recommendations) ? plan.recommendations : [];
  if (!list.length) {
    return `<div class="empty"><h2>No encontramos experiencias todavía</h2><p>Probá con otro destino o una búsqueda más concreta.</p></div>`;
  }

  return list.slice(0, 6).map((rec, index) => {
    const href = trackedPath(rec, plan, source);
    const image = imageOf(rec);
    const rating = ratingParts(rec);
    const price = priceOf(rec);
    const duration = durationOf(rec);
    const badges = badgesOf(rec);
    const label = clean(rec?.ctaLabel || plan?.clickTracking?.ctaLabel || "Ver disponibilidad", 80);
    return `<article class="experience-card">
      <div class="media ${image ? "" : "media-fallback"}">
        ${image ? `<img src="${esc(image)}" alt="${esc(titleOf(rec, index))}" loading="lazy" referrerpolicy="no-referrer">` : `<span class="fallback-mark">✦</span>`}
        ${badges[0] ? `<span class="media-badge">${esc(badges[0])}</span>` : ""}
      </div>
      <div class="card-body">
        <div class="meta-row">
          <div class="rating-line">${rating.value ? `<span class="star">★</span><strong>${esc(rating.value)}</strong>${rating.count ? `<span>(${esc(rating.count)})</span>` : ""}` : `<span class="curated">Selección LUMEN</span>`}</div>
          ${duration ? `<span class="duration">${esc(duration)}</span>` : ""}
        </div>
        <h3>${esc(titleOf(rec, index))}</h3>
        <p>${esc(descriptionOf(rec))}</p>
        <div class="card-footer">
          <div class="price-block">
            ${price ? `<small>Desde</small><strong>${price}</strong><span>por persona*</span>` : `<small>Precio disponible</small><strong>Consultar</strong>`}
          </div>
          ${href ? `<a class="cta" href="${esc(href)}" rel="nofollow sponsored"><span>${esc(label)}</span><b>→</b></a>` : ""}
        </div>
      </div>
    </article>`;
  }).join("");
}

function page(plan, q, source, error = "") {
  const destination = clean(plan?.destination || q, 160);
  const count = Array.isArray(plan?.recommendations) ? plan.recommendations.length : 0;
  const best = plan?.recommendations?.[0];
  const bestImage = imageOf(best || {});

  return `<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="theme-color" content="#ffffff">
  <title>LUMEN Travel | Experiencias en ${esc(destination)}</title>
  <meta name="description" content="Descubrí tours, actividades y experiencias para ${esc(destination)} con LUMEN Travel.">
  <meta property="og:title" content="LUMEN Travel | Experiencias para tu próximo viaje">
  <meta property="og:description" content="Encontrá actividades, tours y experiencias seleccionadas y consultá disponibilidad en Viator.">
  ${bestImage ? `<meta property="og:image" content="${esc(bestImage)}">` : ""}
  <style>
    *{box-sizing:border-box}
    html{scroll-behavior:smooth}
    body{margin:0;background:#fff;color:#1f2328;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;-webkit-font-smoothing:antialiased}
    a{color:inherit}
    .shell{max-width:1220px;margin:0 auto;padding:0 24px}
    .topbar{border-bottom:1px solid #e7e7e7;background:#fff;position:sticky;top:0;z-index:30}
    .nav{height:72px;display:flex;align-items:center;justify-content:space-between;gap:18px}
    .brand{display:flex;align-items:center;gap:10px;font-weight:900;letter-spacing:-.02em;text-decoration:none;font-size:21px}
    .brand-mark{width:30px;height:30px;border-radius:9px;background:#0f6b66;color:#fff;display:grid;place-items:center;font-size:16px;box-shadow:0 4px 12px rgba(15,107,102,.18)}
    .brand span:last-child small{display:block;font-size:9px;letter-spacing:.2em;color:#7c8187;margin-top:-2px}
    .partner{font-size:12px;color:#555b61;border:1px solid #dedede;padding:8px 11px;border-radius:999px;background:#fafafa}
    .hero{background:linear-gradient(180deg,#f8fbfa 0%,#fff 100%);border-bottom:1px solid #ededed}
    .hero-inner{padding:58px 0 48px}
    .eyebrow{font-size:12px;letter-spacing:.12em;text-transform:uppercase;font-weight:800;color:#0f6b66;margin-bottom:12px}
    .hero h1{font-size:clamp(40px,6vw,68px);letter-spacing:-.055em;line-height:.98;margin:0;max-width:860px;color:#16191d}
    .hero h1 em{font-style:normal;color:#d94e42}
    .hero-copy{font-size:18px;line-height:1.6;color:#575e66;max-width:720px;margin:20px 0 0}
    .search-wrap{margin-top:30px;max-width:920px}
    .search{display:flex;align-items:center;background:#fff;border:1px solid #cfcfcf;border-radius:12px;padding:7px 7px 7px 15px;box-shadow:0 8px 28px rgba(27,31,35,.08)}
    .search-icon{font-size:20px;margin-right:8px;color:#565d64}
    .search input{flex:1;min-width:0;border:0;outline:0;background:transparent;font-size:16px;color:#1f2328;padding:14px 8px}
    .search input::placeholder{color:#8a9096}
    .search button,.cta{border:0;background:#d94e42;color:#fff;font-weight:800;border-radius:9px;padding:15px 21px;text-decoration:none;cursor:pointer;transition:.15s ease}
    .search button:hover,.cta:hover{background:#c84439;transform:translateY(-1px)}
    .trust-strip{display:flex;gap:20px;flex-wrap:wrap;margin-top:17px;color:#60666c;font-size:12px}
    .trust-strip span{display:flex;align-items:center;gap:6px}
    .trust-strip span:before{content:"✓";width:18px;height:18px;border-radius:50%;display:grid;place-items:center;background:#e7f4f1;color:#0f6b66;font-weight:900;font-size:11px}
    .section{padding:46px 0}
    .section-head{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;margin-bottom:22px}
    .section-head h2{font-size:30px;letter-spacing:-.035em;margin:0 0 5px;color:#1a1d21}
    .section-head p{margin:0;color:#666c72;font-size:14px;max-width:560px;line-height:1.5}
    .destinations{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
    .destination-tile{display:flex;align-items:center;gap:13px;text-decoration:none;border:1px solid #dedede;border-radius:12px;padding:17px;background:#fff;min-height:100px;transition:.16s ease}
    .destination-tile:hover{border-color:#9faaa8;box-shadow:0 6px 22px rgba(0,0,0,.06);transform:translateY(-2px)}
    .destination-icon{font-size:27px}
    .destination-copy{min-width:0}
    .destination-copy strong{display:block;font-size:15px;margin-bottom:5px;color:#25292d}
    .destination-copy span{font-size:12px;color:#747a80;line-height:1.35;display:block}
    .chevron{margin-left:auto;font-size:24px;color:#8b9196}
    .results-section{background:#fafafa;border-top:1px solid #ececec;border-bottom:1px solid #ececec}
    .result-bar{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;margin-bottom:22px}
    .result-bar h2{margin:0;font-size:30px;letter-spacing:-.035em}
    .result-bar .sub{color:#71777c;font-size:13px;margin-top:6px}
    .provider-note{font-size:12px;color:#61676d;background:#fff;border:1px solid #ddd;border-radius:999px;padding:8px 12px;white-space:nowrap}
    .grid{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}
    .experience-card{background:#fff;border:1px solid #dedede;border-radius:14px;overflow:hidden;display:flex;flex-direction:column;min-height:100%;transition:.18s ease}
    .experience-card:hover{box-shadow:0 10px 30px rgba(0,0,0,.08);transform:translateY(-2px)}
    .media{position:relative;height:215px;background:#edf2f1;overflow:hidden}
    .media img{width:100%;height:100%;object-fit:cover;display:block;transition:.3s ease}
    .experience-card:hover .media img{transform:scale(1.025)}
    .media-fallback{display:grid;place-items:center;background:linear-gradient(135deg,#e6f3f0,#f5f8f7)}
    .fallback-mark{font-size:38px;color:#0f6b66}
    .media-badge{position:absolute;top:12px;left:12px;background:#fff;color:#24282c;border-radius:6px;padding:7px 9px;font-size:11px;font-weight:800;box-shadow:0 3px 12px rgba(0,0,0,.12)}
    .card-body{padding:17px;display:flex;flex-direction:column;flex:1}
    .meta-row{display:flex;justify-content:space-between;align-items:center;gap:10px;font-size:12px;color:#6c7278}
    .rating-line{display:flex;align-items:center;gap:4px;min-height:20px}
    .rating-line strong{color:#25292d}
    .star{color:#f0a500;font-size:14px}
    .curated{font-weight:700;color:#0f6b66}
    .duration{white-space:nowrap}
    .card-body h3{font-size:17px;line-height:1.3;letter-spacing:-.01em;margin:10px 0 8px;color:#202428}
    .card-body p{font-size:13px;line-height:1.48;color:#6c7278;margin:0 0 14px;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
    .card-footer{margin-top:auto;border-top:1px solid #ededed;padding-top:14px;display:flex;align-items:flex-end;justify-content:space-between;gap:12px}
    .price-block{display:flex;flex-direction:column;min-width:95px}
    .price-block small{font-size:11px;color:#777d82}
    .price-block strong{font-size:18px;color:#1e2226;line-height:1.2;margin:2px 0}
    .price-block span{font-size:10px;color:#8a9095}
    .cta{display:flex;align-items:center;justify-content:center;gap:9px;padding:12px 13px;font-size:12px;text-align:center}
    .cta b{font-size:15px}
    .handoff{display:grid;grid-template-columns:1.1fr .9fr;gap:20px;padding:46px 0}
    .handoff-main{background:#f7faf9;border:1px solid #dfe7e5;border-radius:14px;padding:28px}
    .handoff-main h3{font-size:24px;margin:0 0 10px;letter-spacing:-.025em}
    .handoff-main p{margin:0;color:#62696f;line-height:1.6;font-size:14px}
    .handoff-steps{display:grid;gap:10px}
    .handoff-steps div{border:1px solid #e0e0e0;border-radius:12px;padding:16px;background:#fff;display:flex;gap:12px;align-items:flex-start}
    .handoff-steps b{width:25px;height:25px;border-radius:50%;background:#0f6b66;color:#fff;display:grid;place-items:center;font-size:11px;flex:0 0 auto}
    .handoff-steps strong{display:block;font-size:13px;margin-bottom:3px}
    .handoff-steps span{font-size:12px;color:#72787e;line-height:1.4}
    .disclosure{margin:0 0 48px;padding:18px 20px;border-radius:12px;background:#fff8e8;border:1px solid #eddcae;color:#625a45;font-size:12px;line-height:1.6}
    .disclosure strong{color:#3e392c}
    .empty,.error{background:#fff;border:1px solid #ddd;border-radius:12px;padding:28px}
    .error{border-color:#ebc4c1;background:#fff7f6;color:#7a302a}
    .footer{border-top:1px solid #e8e8e8;padding:26px 0 34px;color:#73797e;font-size:12px;display:flex;justify-content:space-between;gap:18px;flex-wrap:wrap}
    @media(max-width:980px){.destinations{grid-template-columns:repeat(2,1fr)}.grid{grid-template-columns:repeat(2,1fr)}.handoff{grid-template-columns:1fr}}
    @media(max-width:680px){.shell{padding:0 16px}.nav{height:64px}.partner{display:none}.hero-inner{padding:42px 0 38px}.hero h1{font-size:43px}.hero-copy{font-size:16px}.search{flex-wrap:wrap;padding:8px}.search-icon{display:none}.search input{width:100%;flex-basis:100%}.search button{width:100%}.section{padding:36px 0}.section-head,.result-bar{align-items:flex-start;flex-direction:column}.destinations,.grid{grid-template-columns:1fr}.media{height:225px}.provider-note{white-space:normal}.card-footer{align-items:stretch;flex-direction:column}.cta{width:100%}}
  </style>
</head>
<body>
  <div class="topbar">
    <div class="shell">
      <nav class="nav">
        <a class="brand" href="/travel?source=${esc(source)}" aria-label="LUMEN Travel">
          <span class="brand-mark">L</span>
          <span>LUMEN<small>TRAVEL</small></span>
        </a>
        <span class="partner">Experiencias disponibles mediante Viator</span>
      </nav>
    </div>
  </div>

  <header class="hero">
    <div class="shell hero-inner">
      <div class="eyebrow">Experiencias para tu próximo viaje</div>
      <h1>Encontrá algo que realmente <em>valga el viaje.</em></h1>
      <p class="hero-copy">LUMEN selecciona tours, actividades y experiencias para tu destino. Explorás acá y, cuando elegís una opción, continuás en Viator para ver disponibilidad, condiciones y precio final.</p>
      <div class="search-wrap">
        <form class="search" method="get" action="/travel">
          <input type="hidden" name="source" value="${esc(source)}">
          <span class="search-icon">⌕</span>
          <input name="q" value="${esc(q)}" placeholder="¿A dónde querés viajar? Ej: Cancún, Madrid, Bangkok…" aria-label="Destino">
          <button type="submit">Buscar experiencias</button>
        </form>
        <div class="trust-strip">
          <span>Sin costo extra por usar LUMEN</span>
          <span>Precio final confirmado en Viator</span>
          <span>Enlaces de afiliado identificados</span>
        </div>
      </div>
    </div>
  </header>

  <main>
    <section class="section">
      <div class="shell">
        <div class="section-head">
          <div>
            <div class="eyebrow">Destinos destacados</div>
            <h2>¿Necesitás inspiración?</h2>
          </div>
          <p>Entrá a un destino destacado o buscá cualquier ciudad. LUMEN consulta las experiencias disponibles y prioriza opciones concretas.</p>
        </div>
        <div class="destinations">${destinationTiles(source)}</div>
      </div>
    </section>

    <section class="section results-section" id="experiencias">
      <div class="shell">
        <div class="result-bar">
          <div>
            <div class="eyebrow">Experiencias seleccionadas</div>
            <h2>${error ? "Explorá experiencias" : `${count} opciones en ${esc(destination)}`}</h2>
            <div class="sub">Compará rating, duración y precio antes de continuar al proveedor.</div>
          </div>
          <span class="provider-note">Disponibilidad y reserva final en Viator</span>
        </div>
        ${error ? `<div class="error">${esc(error)}</div>` : `<div class="grid">${cards(plan, source)}</div>`}
      </div>
    </section>

    <section class="shell handoff" aria-label="Cómo funciona la reserva">
      <div class="handoff-main">
        <div class="eyebrow">Transición simple</div>
        <h3>LUMEN te ayuda a elegir. Viator completa la reserva.</h3>
        <p>Mantenemos una experiencia visual clara y consistente para que el paso al proveedor sea natural. Antes de salir de LUMEN sabés qué experiencia elegiste, qué precio orientativo viste y que la operación final se completa en Viator.</p>
      </div>
      <div class="handoff-steps">
        <div><b>1</b><span><strong>Elegí una experiencia</strong>Revisá fotos, rating, duración y precio desde LUMEN.</span></div>
        <div><b>2</b><span><strong>Verificá disponibilidad</strong>El botón te lleva al producto correspondiente en Viator.</span></div>
        <div><b>3</b><span><strong>Reservá con el proveedor</strong>Viator gestiona disponibilidad, cobro, condiciones y confirmación.</span></div>
      </div>
    </section>

    <div class="shell">
      <div class="disclosure"><strong>Transparencia de afiliados:</strong> LUMEN Travel utiliza enlaces de afiliado. Si reservás a través de uno de ellos, LUMEN puede recibir una comisión sin costo adicional para vos. LUMEN no realiza reservas, no procesa pagos y no almacena datos de pago. Las condiciones, cancelaciones y el servicio contratado son gestionados por Viator y sus proveedores.</div>
      <footer class="footer"><span>© LUMEN Travel · Experiencias para viajar mejor</span><span>Fuente de tráfico: ${esc(source)} · Sin gasto publicitario autónomo</span></footer>
    </div>
  </main>
</body>
</html>`;
}

export async function handleTravelStorefront(request, env) {
  const url = new URL(request.url);
  const path = url.pathname.replace(/\/+$/g, "") || "/";
  if (!["/travel", "/travel.json", "/travel/go"].includes(path)) return null;
  if (request.method !== "GET") return publicJson({ ok: false, error: "method_not_allowed", version: VERSION }, 405);

  const source = sourceOf(url);

  if (path === "/travel/go") {
    if (!env?.A2A || typeof env.A2A.fetch !== "function") {
      return publicJson({ ok: false, error: "travel_redirect_unavailable", version: VERSION }, 503);
    }
    const target = new URL("https://a2a.internal/go/viator");
    for (const [key, value] of url.searchParams.entries()) target.searchParams.append(key, value);
    target.searchParams.set("source", source);
    const upstream = await env.A2A.fetch(new Request(target.toString(), {
      method: "GET",
      redirect: "manual",
      headers: { "user-agent": "LUMEN-Travel-Site/3.0" }
    }));
    const headers = new Headers(upstream.headers);
    headers.set("cache-control", "no-store");
    headers.set("x-lumen-travel-source", source);
    return new Response(upstream.body, { status: upstream.status, headers });
  }

  const q = clean(url.searchParams.get("q") || DEFAULT_QUERY, 220);
  try {
    const plan = await recommend(env, q);
    if (path === "/travel.json") {
      return publicJson({
        ok: true,
        version: VERSION,
        source,
        query: q,
        featuredDestinations: FEATURED_DESTINATIONS.map(item => item.name),
        affiliateDisclosure: true,
        bookingAuthority: false,
        paymentAuthority: false,
        autonomousSpendUsd: 0,
        plan
      });
    }
    return new Response(page(plan, q, source), {
      headers: {
        "content-type": "text/html; charset=utf-8",
        "cache-control": "no-store",
        "x-content-type-options": "nosniff",
        "x-lumen-travel-storefront": VERSION
      }
    });
  } catch (error) {
    const message = "No pudimos cargar las experiencias en este momento. Probá nuevamente o buscá otro destino.";
    if (path === "/travel.json") {
      return publicJson({
        ok: false,
        version: VERSION,
        error: clean(error?.message || error, 180),
        bookingAuthority: false,
        paymentAuthority: false,
        autonomousSpendUsd: 0
      }, 503);
    }
    return new Response(page({}, q, source, message), {
      status: 503,
      headers: {
        "content-type": "text/html; charset=utf-8",
        "cache-control": "no-store",
        "x-content-type-options": "nosniff"
      }
    });
  }
}
