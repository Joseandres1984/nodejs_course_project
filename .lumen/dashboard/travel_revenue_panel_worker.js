import app from "./network_panel_hydration_worker.js";

function n(v) { return Number(v || 0); }
function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, (m) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[m]));
}

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

async function revenueSnapshot(env) {
  const [performance, payouts, settings, campaignPerformance, recentPayouts, recentPerformance] = await Promise.all([
    safeRows(env, "SELECT currency,SUM(sessions) sessions,SUM(pageviews) pageviews,SUM(bookings) bookings,SUM(booking_value) booking_value,SUM(commission_amount) estimated_commission,MAX(imported_at) last_import FROM lumen_viator_performance GROUP BY currency ORDER BY currency"),
    safeRows(env, "SELECT currency,SUM(bookings) bookings,SUM(commission_amount) paid_commission,MAX(payout_date) last_payout,MAX(imported_at) last_import FROM lumen_viator_payouts WHERE UPPER(COALESCE(payout_status,'PAID')) NOT IN ('CANCELLED','CANCELED','FAILED','REJECTED') GROUP BY currency ORDER BY currency"),
    safeFirst(env, "SELECT configured,method,currency,confirmed_by_user,updated_at FROM lumen_viator_payout_settings WHERE id='primary'"),
    safeRows(env, "SELECT COALESCE(NULLIF(campaign,''),'sin campaña') campaign,currency,SUM(sessions) sessions,SUM(bookings) bookings,SUM(booking_value) booking_value,SUM(commission_amount) estimated_commission FROM lumen_viator_performance GROUP BY COALESCE(NULLIF(campaign,''),'sin campaña'),currency ORDER BY estimated_commission DESC,bookings DESC LIMIT 12"),
    safeRows(env, "SELECT payout_date,payout_reference,payout_status,payout_method,bookings,commission_amount,currency,source_reference,imported_at FROM lumen_viator_payouts ORDER BY COALESCE(payout_date,imported_at) DESC LIMIT 12"),
    safeRows(env, "SELECT report_date,campaign,source,sessions,bookings,booking_value,commission_amount,currency,booking_status,imported_at FROM lumen_viator_performance ORDER BY COALESCE(report_date,imported_at) DESC LIMIT 12")
  ]);

  const estimatedByCurrency = performance.map(row => ({
    currency: String(row.currency || "USD"),
    sessions: n(row.sessions),
    pageviews: n(row.pageviews),
    bookings: n(row.bookings),
    bookingValue: n(row.booking_value),
    estimatedCommission: n(row.estimated_commission),
    lastImport: row.last_import || null
  }));
  const paidByCurrency = payouts.map(row => ({
    currency: String(row.currency || "USD"),
    bookings: n(row.bookings),
    paidCommission: n(row.paid_commission),
    lastPayout: row.last_payout || null,
    lastImport: row.last_import || null
  }));
  const estimatedBookings = estimatedByCurrency.reduce((sum, row) => sum + n(row.bookings), 0);
  const paidBookings = paidByCurrency.reduce((sum, row) => sum + n(row.bookings), 0);

  return {
    mode: "viator_partner_platform_csv_reconciliation",
    performanceImported: estimatedByCurrency.length > 0,
    payoutsImported: paidByCurrency.length > 0,
    estimatedByCurrency,
    paidByCurrency,
    estimatedBookings,
    paidBookings,
    payoutMethod: {
      configured: Boolean(settings?.configured),
      method: String(settings?.method || "UNKNOWN"),
      currency: settings?.currency ? String(settings.currency) : null,
      confirmedByUser: Boolean(settings?.confirmed_by_user),
      updatedAt: settings?.updated_at || null,
      sensitiveDetailsStored: false
    },
    campaignPerformance: campaignPerformance.map(row => ({
      campaign: String(row.campaign || "sin campaña"),
      currency: String(row.currency || "USD"),
      sessions: n(row.sessions),
      bookings: n(row.bookings),
      bookingValue: n(row.booking_value),
      estimatedCommission: n(row.estimated_commission)
    })),
    recentPayouts,
    recentPerformance,
    accountingRules: {
      estimatedIsCash: false,
      payoutsAreVerifiedRevenue: true,
      cancelledOrFailedPayoutsExcluded: true
    }
  };
}

const REVENUE_SECTION = `<div class="grid g2 section"><div class="card"><h2>Comisiones Viator</h2><div id="travelRevenueTotals"></div></div><div class="card"><h2>Cobro</h2><div id="travelPayoutStatus"></div></div></div><div class="grid g2 section"><div class="card"><h2>Rendimiento por campaña</h2><div id="travelRevenueCampaigns"></div></div><div class="card"><h2>Payouts confirmados</h2><div id="travelRevenuePayouts"></div></div></div>`;

const REVENUE_RENDER_JS = `function renderTravelRevenue(t){
  const r=t?.revenue||{};
  const moneyRows=(rows,key)=>{const x=Array.isArray(rows)?rows:[];return x.length?x.map(v=>esc(v.currency||'USD')+' '+num(v[key]||0).toLocaleString('es-AR',{minimumFractionDigits:2,maximumFractionDigits:2})).join(' · '):'—';};
  const estimated=moneyRows(r.estimatedByCurrency,'estimatedCommission');
  const paid=moneyRows(r.paidByCurrency,'paidCommission');
  const value=moneyRows(r.estimatedByCurrency,'bookingValue');
  const payout=r.payoutMethod||{};
  $('travelRevenueTotals').innerHTML=line('Reservas reportadas',num(r.estimatedBookings||0))+line('Valor de reservas',value)+line('Comisión estimada',estimated)+line('Pagado por Viator','<strong class="good">'+paid+'</strong>')+'<p class="note">La comisión estimada no se trata como efectivo. Sólo los payouts importados desde Finance cuentan como ingreso cobrado.</p>';
  $('travelPayoutStatus').innerHTML=line('Método',payout.configured?'<span class="chip ok">'+esc(payout.method||'CONFIGURADO')+'</span>':'<span class="chip no">PENDIENTE</span>')+line('Confirmación',payout.confirmedByUser?'<span class="chip ok">CONFIRMADO</span>':'<span class="chip">NO CONFIRMADO</span>')+line('Moneda',esc(payout.currency||'—'))+line('Reservas pagadas',num(r.paidBookings||0))+line('Datos bancarios almacenados','NO');
  $('travelRevenueCampaigns').innerHTML=table([['Campaña',x=>esc(x.campaign)],['Sesiones',x=>num(x.sessions)],['Reservas',x=>num(x.bookings)],['Valor',x=>esc(x.currency)+' '+num(x.bookingValue).toLocaleString('es-AR',{maximumFractionDigits:2})],['Comisión est.',x=>esc(x.currency)+' '+num(x.estimatedCommission).toLocaleString('es-AR',{maximumFractionDigits:2})]],r.campaignPerformance||[]);
  $('travelRevenuePayouts').innerHTML=table([['Fecha',x=>esc(x.payout_date||'—')],['Estado',x=>esc(x.payout_status||'—')],['Método',x=>esc(x.payout_method||'—')],['Importe',x=>esc(x.currency||'USD')+' '+num(x.commission_amount).toLocaleString('es-AR',{minimumFractionDigits:2,maximumFractionDigits:2})]],r.recentPayouts||[]);
}`;

function injectRevenueUI(html) {
  if (!html.includes('id="travelRevenueTotals"')) {
    const marker = '<div class="grid g2 section"><div class="card"><h2>Top destinos</h2>';
    if (html.includes(marker)) html = html.replace(marker, `${REVENUE_SECTION}${marker}`);
  }
  if (!html.includes('function renderTravelRevenue(t)')) {
    const marker = 'function renderTravel(t){';
    if (html.includes(marker)) html = html.replace(marker, `${REVENUE_RENDER_JS}\nfunction renderTravel(t){\n  renderTravelRevenue(t);`);
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
        data.travel.revenue = await revenueSnapshot(env);
        const headers = new Headers(response.headers);
        headers.delete("content-length");
        headers.set("cache-control", "no-store");
        headers.set("x-lumen-travel-revenue", "v1");
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
    html = injectRevenueUI(html);
    const headers = new Headers(response.headers);
    headers.delete("content-length");
    headers.set("cache-control", "no-store, no-cache, must-revalidate");
    headers.set("x-lumen-travel-revenue-panel", "v1");
    return new Response(html, { status: response.status, statusText: response.statusText, headers });
  }
};
