import app from "./travel_revenue_panel_worker.js";

function n(v) { return Number(v || 0); }

async function safeRows(env, sql, binds = []) {
  try {
    let q = env.DB.prepare(sql);
    if (binds.length) q = q.bind(...binds);
    const result = await q.all();
    return result.results || [];
  } catch {
    return [];
  }
}

async function safeFirst(env, sql, binds = []) {
  try {
    let q = env.DB.prepare(sql);
    if (binds.length) q = q.bind(...binds);
    return await q.first();
  } catch {
    return null;
  }
}

async function conversionSnapshot(env) {
  const [state, totals, campaignBookings, campaignClicks, variantBookings, variantClicks, recent] = await Promise.all([
    safeFirst(env, "SELECT cursor,last_sync_at,last_success_at,last_error,events_seen,events_inserted,pages_seen,updated_at FROM lumen_viator_booking_sync_state WHERE id='primary'"),
    safeRows(env, "SELECT event_type,COUNT(*) total,SUM(CASE WHEN datetime(last_updated)>=datetime('now','-7 days') THEN 1 ELSE 0 END) last_7d,SUM(CASE WHEN event_type='CONFIRMATION' THEN total_price ELSE 0 END) value FROM lumen_viator_booking_events GROUP BY event_type"),
    safeRows(env, "SELECT COALESCE(NULLIF(campaign_value,''),'unattributed') campaign,SUM(CASE WHEN event_type='CONFIRMATION' THEN 1 ELSE 0 END) confirmations,SUM(CASE WHEN event_type IN ('CANCELLATION','CUSTOMER_CANCELLATION','REJECTION') THEN 1 ELSE 0 END) negative_events,SUM(CASE WHEN event_type='CONFIRMATION' THEN total_price ELSE 0 END) confirmed_value,MAX(currency) currency,MAX(last_updated) last_event FROM lumen_viator_booking_events GROUP BY COALESCE(NULLIF(campaign_value,''),'unattributed') ORDER BY confirmations DESC,confirmed_value DESC LIMIT 20"),
    safeRows(env, "SELECT COALESCE(NULLIF(campaign,''),'unattributed') campaign,COUNT(*) clicks FROM lumen_travel_events WHERE event_type='click' GROUP BY COALESCE(NULLIF(campaign,''),'unattributed')"),
    safeRows(env, "SELECT CASE WHEN campaign_value LIKE '%price_availability_v1%' THEN 'price_availability_v1' WHEN campaign_value LIKE '%dates_available_v1%' THEN 'dates_available_v1' ELSE 'other' END variant,SUM(CASE WHEN event_type='CONFIRMATION' THEN 1 ELSE 0 END) confirmations,SUM(CASE WHEN event_type IN ('CANCELLATION','CUSTOMER_CANCELLATION','REJECTION') THEN 1 ELSE 0 END) negative_events,SUM(CASE WHEN event_type='CONFIRMATION' THEN total_price ELSE 0 END) confirmed_value FROM lumen_viator_booking_events GROUP BY variant"),
    safeRows(env, "SELECT COALESCE(NULLIF(variant,''),'other') variant,COUNT(*) clicks FROM lumen_travel_events WHERE event_type='click' GROUP BY COALESCE(NULLIF(variant,''),'other')"),
    safeRows(env, "SELECT event_type,transaction_ref,product_code,campaign_value,travel_date,last_updated,total_price,currency FROM lumen_viator_booking_events ORDER BY datetime(last_updated) DESC LIMIT 15")
  ]);

  const byType = Object.fromEntries(totals.map(row => [String(row.event_type || ""), { total: n(row.total), last7d: n(row.last_7d), value: n(row.value) }]));
  const confirmations7d = n(byType.CONFIRMATION?.last7d);
  const negatives7d = n(byType.CANCELLATION?.last7d) + n(byType.CUSTOMER_CANCELLATION?.last7d) + n(byType.REJECTION?.last7d);
  const clicks7dRows = await safeRows(env, "SELECT COUNT(*) clicks FROM lumen_travel_events WHERE event_type='click' AND datetime(created_at)>=datetime('now','-7 days')");
  const clicks7d = n(clicks7dRows[0]?.clicks);
  const conversionRate7d = clicks7d > 0 ? Number(((confirmations7d / clicks7d) * 100).toFixed(2)) : null;

  const clickByCampaign = new Map(campaignClicks.map(row => [String(row.campaign), n(row.clicks)]));
  const campaigns = campaignBookings.map(row => {
    const clicks = clickByCampaign.get(String(row.campaign)) || 0;
    const confirmations = n(row.confirmations);
    return {
      campaign: String(row.campaign),
      confirmations,
      negativeEvents: n(row.negative_events),
      confirmedValue: n(row.confirmed_value),
      currency: String(row.currency || "—"),
      clicks,
      cvr: clicks > 0 ? Number(((confirmations / clicks) * 100).toFixed(2)) : null,
      lastEvent: row.last_event || null
    };
  });

  const clickByVariant = new Map(variantClicks.map(row => [String(row.variant), n(row.clicks)]));
  const variants = variantBookings.map(row => {
    const clicks = clickByVariant.get(String(row.variant)) || 0;
    const confirmations = n(row.confirmations);
    return {
      variant: String(row.variant),
      confirmations,
      negativeEvents: n(row.negative_events),
      confirmedValue: n(row.confirmed_value),
      clicks,
      cvr: clicks > 0 ? Number(((confirmations / clicks) * 100).toFixed(2)) : null
    };
  }).sort((a, b) => b.confirmations - a.confirmations || (b.cvr || 0) - (a.cvr || 0));

  const winner = variants.find(row => row.confirmations >= 3 && row.clicks >= 20) || null;

  return {
    mode: "viator_booking_api_conversion_attribution",
    sync: {
      lastSyncAt: state?.last_sync_at || null,
      lastSuccessAt: state?.last_success_at || null,
      lastError: state?.last_error || null,
      eventsSeen: n(state?.events_seen),
      eventsInserted: n(state?.events_inserted),
      pagesSeen: n(state?.pages_seen),
      cursorStored: Boolean(state?.cursor)
    },
    funnel: {
      clicks7d,
      confirmations7d,
      negativeEvents7d: negatives7d,
      conversionRate7d
    },
    campaigns,
    variants,
    winner,
    recent,
    policy: {
      minimumConfirmations: 3,
      minimumClicks: 20,
      explorationSharePct: winner ? 20 : 50,
      noFabricatedSignificance: true,
      commissionNotInferredFromBookings: true
    }
  };
}

const CONVERSION_SECTION = `<div class="grid g4 section"><div class="card"><div class="klabel">Reservas API 7 días</div><div class="kpi good" id="travelApiBookings7">–</div></div><div class="card"><div class="klabel">Conversión clic → reserva</div><div class="kpi blue" id="travelApiCvr7">–</div></div><div class="card"><div class="klabel">Cancel./rechazos 7 días</div><div class="kpi" id="travelApiNegative7">–</div></div><div class="card"><div class="klabel">Sync Viator</div><div class="kpi" id="travelApiSync">–</div></div></div><div class="grid g2 section"><div class="card"><h2>Conversión por campaña</h2><div id="travelConversionCampaigns"></div></div><div class="card"><h2>Optimización CTA</h2><div id="travelConversionVariants"></div></div></div>`;

const CONVERSION_RENDER_JS = `function renderTravelConversion(t){
  const c=t?.conversion||{};
  const f=c.funnel||{};
  const s=c.sync||{};
  $('travelApiBookings7').textContent=num(f.confirmations7d||0).toLocaleString('es-AR');
  $('travelApiCvr7').textContent=f.conversionRate7d==null?'—':num(f.conversionRate7d).toLocaleString('es-AR',{maximumFractionDigits:2})+'%';
  $('travelApiNegative7').textContent=num(f.negativeEvents7d||0).toLocaleString('es-AR');
  $('travelApiSync').textContent=s.lastSuccessAt?'OK':'PEND.';
  $('travelConversionCampaigns').innerHTML=table([['Campaña',x=>esc(x.campaign)],['Clics',x=>num(x.clicks)],['Reservas',x=>num(x.confirmations)],['CVR',x=>x.cvr==null?'—':num(x.cvr).toFixed(2)+'%'],['Valor',x=>esc(x.currency||'')+' '+num(x.confirmedValue).toLocaleString('es-AR',{maximumFractionDigits:2})]],c.campaigns||[]);
  const winner=c.winner;
  const winnerNote=winner?'<p class="note"><strong>Ganador con evidencia:</strong> '+esc(winner.variant)+' · exploración '+num(c.policy?.explorationSharePct||20)+'%.</p>':'<p class="note">Todavía no hay muestra suficiente para declarar un CTA ganador. LUMEN mantiene exploración 50/50 hasta reunir evidencia mínima.</p>';
  $('travelConversionVariants').innerHTML=table([['CTA',x=>esc(x.variant)],['Clics',x=>num(x.clicks)],['Reservas',x=>num(x.confirmations)],['CVR',x=>x.cvr==null?'—':num(x.cvr).toFixed(2)+'%'],['Negativos',x=>num(x.negativeEvents)]],c.variants||[])+winnerNote+'<p class="note">Una reserva confirmada no se registra como comisión cobrada. El efectivo sigue dependiendo del payout verificado de Viator.</p>';
}`;

function injectConversionUI(html) {
  if (!html.includes('id="travelApiBookings7"')) {
    const marker = '<div class="grid g2 section"><div class="card"><h2>Comisiones Viator</h2>';
    if (html.includes(marker)) html = html.replace(marker, `${CONVERSION_SECTION}${marker}`);
  }
  if (!html.includes('function renderTravelConversion(t)')) {
    const marker = 'function renderTravelRevenue(t){';
    if (html.includes(marker)) html = html.replace(marker, `${CONVERSION_RENDER_JS}\nfunction renderTravelRevenue(t){\n  renderTravelConversion(t);`);
  }
  return html;
}

export default {
  async fetch(request, env, ctx) {
    const response = await app.fetch(request, env, ctx);
    const url = new URL(request.url);

    if (request.method === "GET" && url.pathname === "/api/data" && response.ok && String(response.headers.get("content-type") || "").includes("application/json")) {
      try {
        const data = await response.json();
        data.travel = data.travel || {};
        data.travel.conversion = await conversionSnapshot(env);
        const headers = new Headers(response.headers);
        headers.delete("content-length");
        headers.set("cache-control", "no-store");
        headers.set("x-lumen-travel-conversion", "v2");
        return Response.json(data, { status: response.status, headers });
      } catch {
        return response;
      }
    }

    const isHtml = request.method === "GET"
      && response.ok
      && ["/", "/index.html", "/full", "/secretaria", "/secretaria/"].includes(url.pathname)
      && String(response.headers.get("content-type") || "").includes("text/html");
    if (!isHtml) return response;

    let html = await response.text();
    html = injectConversionUI(html);
    const headers = new Headers(response.headers);
    headers.delete("content-length");
    headers.set("cache-control", "no-store, no-cache, must-revalidate");
    headers.set("x-lumen-travel-conversion-panel", "v2");
    return new Response(html, { status: response.status, statusText: response.statusText, headers });
  }
};
