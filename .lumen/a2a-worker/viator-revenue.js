const VERSION = "1.1-viator-revenue-reconciliation";
const MAX_IMPORT_ROWS = 5000;
const VERIFIED_PAYOUT_STATUSES = new Set(["PAID", "COMPLETED", "SENT", "PROCESSED"]);

function clean(value, limit = 4000) {
  return String(value ?? "").trim().slice(0, limit);
}

function json(data, status = 200) {
  return Response.json(data, {
    status,
    headers: {
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      "access-control-allow-origin": "*",
      "access-control-allow-headers": "content-type,x-lumen-admin",
      "access-control-allow-methods": "GET,POST,OPTIONS"
    }
  });
}

function authorized(request, env) {
  const configured = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500);
  const provided = clean(request.headers.get("x-lumen-admin"), 500);
  return Boolean(configured && provided && configured === provided);
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_viator_performance (id TEXT PRIMARY KEY,row_key TEXT NOT NULL UNIQUE,report_date TEXT,period_start TEXT,period_end TEXT,campaign TEXT,source TEXT,sessions INTEGER NOT NULL DEFAULT 0,pageviews INTEGER NOT NULL DEFAULT 0,bookings INTEGER NOT NULL DEFAULT 0,booking_value REAL NOT NULL DEFAULT 0,commission_amount REAL NOT NULL DEFAULT 0,currency TEXT NOT NULL DEFAULT 'USD',booking_status TEXT,imported_at TEXT NOT NULL,raw_json TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_viator_perf_campaign ON lumen_viator_performance(campaign,report_date DESC)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_viator_perf_imported ON lumen_viator_performance(imported_at DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_viator_payouts (id TEXT PRIMARY KEY,row_key TEXT NOT NULL UNIQUE,payout_date TEXT,period_start TEXT,period_end TEXT,payout_reference TEXT,payout_status TEXT,payout_method TEXT,bookings INTEGER NOT NULL DEFAULT 0,commission_amount REAL NOT NULL DEFAULT 0,currency TEXT NOT NULL DEFAULT 'USD',source_reference TEXT,imported_at TEXT NOT NULL,raw_json TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_viator_payout_date ON lumen_viator_payouts(payout_date DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_viator_payout_settings (id TEXT PRIMARY KEY CHECK(id='primary'),configured INTEGER NOT NULL DEFAULT 0,method TEXT NOT NULL DEFAULT 'UNKNOWN',currency TEXT,confirmed_by_user INTEGER NOT NULL DEFAULT 0,updated_at TEXT NOT NULL)"),
    env.DB.prepare("INSERT OR IGNORE INTO lumen_viator_payout_settings(id,configured,method,currency,confirmed_by_user,updated_at) VALUES('primary',0,'UNKNOWN',NULL,0,datetime('now'))")
  ]);
  return true;
}

function normalizedHeader(value) {
  return clean(value, 200)
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

function parseCsv(text) {
  const source = String(text ?? "");
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;
  for (let i = 0; i < source.length; i += 1) {
    const ch = source[i];
    if (quoted) {
      if (ch === '"' && source[i + 1] === '"') { field += '"'; i += 1; }
      else if (ch === '"') quoted = false;
      else field += ch;
      continue;
    }
    if (ch === '"') quoted = true;
    else if (ch === ',') { row.push(field); field = ""; }
    else if (ch === '\n') { row.push(field.replace(/\r$/, "")); rows.push(row); row = []; field = ""; }
    else field += ch;
  }
  if (field.length || row.length) { row.push(field.replace(/\r$/, "")); rows.push(row); }
  const nonEmpty = rows.filter(r => r.some(v => clean(v, 1000) !== ""));
  if (nonEmpty.length < 2) return [];
  const headers = nonEmpty[0].map(normalizedHeader);
  return nonEmpty.slice(1).map(values => Object.fromEntries(headers.map((h, i) => [h || `column_${i + 1}`, values[i] ?? ""])));
}

function pick(row, aliases) {
  for (const alias of aliases) {
    const key = normalizedHeader(alias);
    if (row?.[key] !== undefined && clean(row[key], 2000) !== "") return row[key];
  }
  return "";
}

function amount(value) {
  let s = clean(value, 120).replace(/[^0-9,.-]/g, "");
  if (!s) return 0;
  const hasComma = s.includes(",");
  const hasDot = s.includes(".");
  if (hasComma && hasDot) {
    if (s.lastIndexOf(",") > s.lastIndexOf(".")) s = s.replace(/\./g, "").replace(",", ".");
    else s = s.replace(/,/g, "");
  } else if (hasComma) {
    const tail = s.length - s.lastIndexOf(",") - 1;
    s = tail === 2 ? s.replace(/\./g, "").replace(",", ".") : s.replace(/,/g, "");
  }
  const n = Number(s);
  return Number.isFinite(n) ? n : 0;
}

function integer(value) {
  return Math.max(0, Math.round(amount(value)));
}

function currencyFrom(row, fallback = "USD") {
  const explicit = clean(pick(row, ["currency", "currency code", "currencyCode", "payout currency", "payoutCurrency"]), 12).toUpperCase();
  if (explicit) return explicit;
  const joined = Object.values(row || {}).map(v => clean(v, 200)).join(" ").toUpperCase();
  const match = joined.match(/\b(USD|EUR|GBP|AUD|CAD|ARS|BRL|MXN)\b/);
  return match?.[1] || clean(fallback, 12).toUpperCase() || "USD";
}

function isoDate(value) {
  const s = clean(value, 80);
  if (!s) return null;
  const direct = new Date(s);
  if (!Number.isNaN(direct.getTime())) return direct.toISOString().slice(0, 10);
  const m = s.match(/^(\d{1,2})[\/-](\d{1,2})[\/-](\d{4})$/);
  if (!m) return null;
  const d = new Date(Date.UTC(Number(m[3]), Number(m[2]) - 1, Number(m[1])));
  return Number.isNaN(d.getTime()) ? null : d.toISOString().slice(0, 10);
}

async function stableKey(kind, row) {
  const encoded = new TextEncoder().encode(`${kind}:${JSON.stringify(row)}`);
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", encoded));
  return [...digest].map(b => b.toString(16).padStart(2, "0")).join("").slice(0, 40);
}

function performanceRow(raw, defaults = {}) {
  const row = Object.fromEntries(Object.entries(raw || {}).map(([k, v]) => [normalizedHeader(k), v]));
  return {
    reportDate: isoDate(pick(row, ["date", "report date", "reportDate", "booking date", "bookingDate", "travel date", "travelDate"])),
    periodStart: isoDate(defaults.periodStart || pick(row, ["period start", "periodStart", "start date", "startDate", "from"])),
    periodEnd: isoDate(defaults.periodEnd || pick(row, ["period end", "periodEnd", "end date", "endDate", "to"])),
    campaign: clean(pick(row, ["campaign", "campaign name", "campaignName", "campaign value", "campaignValue"]), 200),
    source: clean(pick(row, ["source", "traffic source", "trafficSource", "link source", "linkSource"]), 120),
    sessions: integer(pick(row, ["sessions", "visitors", "visits"])),
    pageviews: integer(pick(row, ["pageviews", "page views", "pageViews", "views"])),
    bookings: integer(pick(row, ["bookings", "booking count", "bookingCount", "orders"])),
    bookingValue: amount(pick(row, ["booking value", "bookingValue", "booking value usd", "gross booking value", "grossBookingValue", "sales"])),
    commissionAmount: amount(pick(row, ["commission", "gross commission", "grossCommission", "estimated commission", "estimatedCommission", "commission amount", "commissionAmount"])),
    currency: currencyFrom(row, defaults.currency),
    bookingStatus: clean(pick(row, ["booking status", "bookingStatus", "status"]), 80),
    raw: raw || {}
  };
}

function payoutRow(raw, defaults = {}) {
  const row = Object.fromEntries(Object.entries(raw || {}).map(([k, v]) => [normalizedHeader(k), v]));
  const explicitStatus = clean(pick(row, ["payout status", "payoutStatus", "payment status", "paymentStatus", "status"]), 80).toUpperCase();
  return {
    payoutDate: isoDate(pick(row, ["payout date", "payoutDate", "payment date", "paymentDate", "paid date", "paidDate", "date"])),
    periodStart: isoDate(defaults.periodStart || pick(row, ["period start", "periodStart", "start date", "startDate", "from"])),
    periodEnd: isoDate(defaults.periodEnd || pick(row, ["period end", "periodEnd", "end date", "endDate", "to"])),
    payoutReference: clean(pick(row, ["payout reference", "payoutReference", "payment reference", "paymentReference", "reference", "remittance id", "remittanceId"]), 200),
    payoutStatus: explicitStatus || (defaults.assumePaid === true ? "PAID" : "UNKNOWN"),
    payoutMethod: clean(pick(row, ["payout method", "payoutMethod", "payment method", "paymentMethod", "method"]), 80).toUpperCase(),
    bookings: integer(pick(row, ["bookings", "booking count", "bookingCount"])),
    commissionAmount: amount(pick(row, ["commission", "commission amount", "commissionAmount", "payout amount", "payoutAmount", "payment amount", "paymentAmount", "amount"])),
    currency: currencyFrom(row, defaults.currency),
    sourceReference: clean(pick(row, ["booking reference", "bookingReference", "source reference", "sourceReference", "booking id", "bookingId"]), 200),
    raw: raw || {}
  };
}

function importRowsFromPayload(payload) {
  const rows = Array.isArray(payload?.rows) ? payload.rows : parseCsv(payload?.csv || "");
  return rows.slice(0, MAX_IMPORT_ROWS);
}

async function importPerformance(env, payload) {
  await ensureSchema(env);
  const rows = importRowsFromPayload(payload);
  if (!rows.length) return { ok: false, error: "performance_rows_required" };
  let inserted = 0;
  let duplicates = 0;
  for (const raw of rows) {
    const item = performanceRow(raw, payload || {});
    const key = await stableKey("performance", item);
    const result = await env.DB.prepare("INSERT OR IGNORE INTO lumen_viator_performance(id,row_key,report_date,period_start,period_end,campaign,source,sessions,pageviews,bookings,booking_value,commission_amount,currency,booking_status,imported_at,raw_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
      .bind(`VPERF-${key.slice(0,24)}`, key, item.reportDate, item.periodStart, item.periodEnd, item.campaign, item.source, item.sessions, item.pageviews, item.bookings, item.bookingValue, item.commissionAmount, item.currency, item.bookingStatus, new Date().toISOString(), JSON.stringify(item.raw)).run();
    if (Number(result?.meta?.changes || 0) > 0) inserted += 1; else duplicates += 1;
  }
  return { ok: true, reportType: "performance", received: rows.length, inserted, duplicates, commissionClassification: "estimated_not_cash", version: VERSION };
}

async function importPayouts(env, payload) {
  await ensureSchema(env);
  const rows = importRowsFromPayload(payload);
  if (!rows.length) return { ok: false, error: "payout_rows_required" };
  let inserted = 0;
  let duplicates = 0;
  let verifiedRows = 0;
  for (const raw of rows) {
    const item = payoutRow(raw, payload || {});
    if (VERIFIED_PAYOUT_STATUSES.has(item.payoutStatus)) verifiedRows += 1;
    const key = await stableKey("payout", item);
    const result = await env.DB.prepare("INSERT OR IGNORE INTO lumen_viator_payouts(id,row_key,payout_date,period_start,period_end,payout_reference,payout_status,payout_method,bookings,commission_amount,currency,source_reference,imported_at,raw_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
      .bind(`VPAY-${key.slice(0,24)}`, key, item.payoutDate, item.periodStart, item.periodEnd, item.payoutReference, item.payoutStatus, item.payoutMethod, item.bookings, item.commissionAmount, item.currency, item.sourceReference, new Date().toISOString(), JSON.stringify(item.raw)).run();
    if (Number(result?.meta?.changes || 0) > 0) inserted += 1; else duplicates += 1;
  }
  return {
    ok: true,
    reportType: "payout",
    received: rows.length,
    inserted,
    duplicates,
    verifiedRows,
    verifiedRevenueStatuses: [...VERIFIED_PAYOUT_STATUSES],
    version: VERSION
  };
}

async function revenueStatus(env) {
  await ensureSchema(env);
  const [performance, payouts, settings] = await Promise.all([
    env.DB.prepare("SELECT currency,SUM(sessions) sessions,SUM(bookings) bookings,SUM(booking_value) booking_value,SUM(commission_amount) estimated_commission,MAX(imported_at) last_import FROM lumen_viator_performance GROUP BY currency ORDER BY currency").all(),
    env.DB.prepare("SELECT currency,SUM(bookings) bookings,SUM(commission_amount) paid_commission,MAX(payout_date) last_payout,MAX(imported_at) last_import FROM lumen_viator_payouts WHERE UPPER(COALESCE(payout_status,'UNKNOWN')) IN ('PAID','COMPLETED','SENT','PROCESSED') GROUP BY currency ORDER BY currency").all(),
    env.DB.prepare("SELECT configured,method,currency,confirmed_by_user,updated_at FROM lumen_viator_payout_settings WHERE id='primary'").first()
  ]);
  return {
    ok: true,
    version: VERSION,
    provider: "viator",
    reportingMode: "partner_platform_csv_reconciliation",
    performance: performance.results || [],
    payouts: payouts.results || [],
    payoutMethod: {
      configured: Boolean(settings?.configured),
      method: clean(settings?.method, 80) || "UNKNOWN",
      currency: clean(settings?.currency, 12) || null,
      confirmedByUser: Boolean(settings?.confirmed_by_user),
      updatedAt: settings?.updated_at || null,
      sensitiveDetailsStored: false
    },
    commissionPolicy: {
      estimatedPerformanceIsNotCash: true,
      verifiedPayoutStatuses: [...VERIFIED_PAYOUT_STATUSES],
      unknownOrPendingPayoutIsNotCash: true,
      autonomousSpendUsd: 0,
      bookingAuthority: false,
      paymentAuthority: false
    }
  };
}

export async function handleViatorRevenue(request, env) {
  const url = new URL(request.url);
  const paths = [
    "/viator/revenue/policy",
    "/viator/revenue/status",
    "/viator/revenue/import/performance",
    "/viator/revenue/import/payouts",
    "/viator/revenue/payout-method"
  ];
  if (!paths.includes(url.pathname)) return null;

  if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: {
    "access-control-allow-origin": "*",
    "access-control-allow-headers": "content-type,x-lumen-admin",
    "access-control-allow-methods": "GET,POST,OPTIONS"
  }});

  if (request.method === "GET" && url.pathname === "/viator/revenue/policy") {
    return json({
      ok: true,
      version: VERSION,
      provider: "viator",
      sourceOfTruth: {
        estimatedCommission: "Viator Partner Platform performance export",
        paidCommission: "Viator Finance payout export with verified paid status"
      },
      reportingApiAvailable: false,
      csvImportSupported: true,
      storesBankDetails: false,
      storesPayPalCredentials: false,
      verifiedPayoutStatuses: [...VERIFIED_PAYOUT_STATUSES],
      bookingAuthority: false,
      paymentAuthority: false,
      autonomousSpendUsd: 0
    });
  }

  if (!authorized(request, env)) return json({ ok: false, error: "unauthorized", version: VERSION }, 401);

  if (request.method === "GET" && url.pathname === "/viator/revenue/status") {
    return json(await revenueStatus(env));
  }

  let payload = {};
  if (request.method === "POST") {
    try { payload = await request.json(); } catch { return json({ ok: false, error: "valid_json_required", version: VERSION }, 400); }
  }

  if (request.method === "POST" && url.pathname === "/viator/revenue/import/performance") {
    const result = await importPerformance(env, payload);
    return json(result, result.ok ? 200 : 400);
  }

  if (request.method === "POST" && url.pathname === "/viator/revenue/import/payouts") {
    const result = await importPayouts(env, payload);
    return json(result, result.ok ? 200 : 400);
  }

  if (request.method === "POST" && url.pathname === "/viator/revenue/payout-method") {
    await ensureSchema(env);
    const method = clean(payload?.method, 40).toUpperCase();
    if (!["PAYPAL", "BANK", "UNKNOWN"].includes(method)) return json({ ok: false, error: "method_must_be_paypal_bank_or_unknown", version: VERSION }, 400);
    const configured = payload?.configured === true ? 1 : 0;
    const confirmed = payload?.confirmedByUser === true ? 1 : 0;
    const currency = clean(payload?.currency, 12).toUpperCase() || null;
    await env.DB.prepare("INSERT INTO lumen_viator_payout_settings(id,configured,method,currency,confirmed_by_user,updated_at) VALUES('primary',?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET configured=excluded.configured,method=excluded.method,currency=excluded.currency,confirmed_by_user=excluded.confirmed_by_user,updated_at=excluded.updated_at")
      .bind(configured, method, currency, confirmed, new Date().toISOString()).run();
    return json({ ok: true, payoutMethod: { configured: Boolean(configured), method, currency, confirmedByUser: Boolean(confirmed), sensitiveDetailsStored: false }, version: VERSION });
  }

  return json({ ok: false, error: "method_not_allowed", version: VERSION }, 405);
}
