const VERSION = "1.0-travelpayouts-finance-truth";
const FINANCE_BASE = "https://api.travelpayouts.com/finance/v2";
const SYNC_MIN_INTERVAL_MS = 55 * 60 * 1000;
const LOOKBACK_DAYS = 365;
const PAGE_SIZE = 300;
const MAX_PAGES = 4;

function clean(value, limit = 4000) {
  return String(value ?? "").trim().replace(/[\r\n\t]+/g, " ").slice(0, limit);
}
function num(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
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
function iso(value, fallback = new Date().toISOString()) {
  const raw = clean(value, 100);
  if (!raw) return fallback;
  const normalized = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(raw) ? `${raw.replace(" ", "T")}Z` : raw;
  const t = Date.parse(normalized);
  return Number.isFinite(t) ? new Date(t).toISOString() : fallback;
}
function dateOnly(date) {
  return date.toISOString().slice(0, 10);
}
async function sha256(text) {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(String(text)));
  return [...new Uint8Array(d)].map(b => b.toString(16).padStart(2, "0")).join("");
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_revenue_events (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, event_type TEXT NOT NULL, source TEXT NOT NULL, item_id TEXT, amount_usd REAL, status TEXT NOT NULL, evidence TEXT, metadata TEXT)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_travelpayouts_rewards (action_id TEXT PRIMARY KEY,campaign_id INTEGER,action_state TEXT NOT NULL,price_usd REAL NOT NULL DEFAULT 0,profit_usd REAL NOT NULL DEFAULT 0,description TEXT,booked_at TEXT,provider_updated_at TEXT,revenue_event_id TEXT NOT NULL,imported_at TEXT NOT NULL,raw_json TEXT NOT NULL,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_travelpayouts_rewards_updated ON lumen_travelpayouts_rewards(provider_updated_at DESC)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_travelpayouts_rewards_campaign ON lumen_travelpayouts_rewards(campaign_id,profit_usd DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_travelpayouts_payouts (payment_uuid TEXT PRIMARY KEY,paid_at TEXT NOT NULL,amount REAL NOT NULL,currency TEXT NOT NULL,payment_info_id TEXT,comment TEXT,payout_event_id TEXT NOT NULL,imported_at TEXT NOT NULL,raw_json TEXT NOT NULL,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_travelpayouts_finance_state (id TEXT PRIMARY KEY CHECK(id='primary'),last_sync_at TEXT,last_success_at TEXT,last_error TEXT,actions_seen INTEGER NOT NULL DEFAULT 0,rewards_inserted INTEGER NOT NULL DEFAULT 0,payouts_seen INTEGER NOT NULL DEFAULT 0,payouts_inserted INTEGER NOT NULL DEFAULT 0,updated_at TEXT NOT NULL)"),
    env.DB.prepare("INSERT OR IGNORE INTO lumen_travelpayouts_finance_state(id,last_sync_at,last_success_at,last_error,actions_seen,rewards_inserted,payouts_seen,payouts_inserted,updated_at) VALUES('primary',NULL,NULL,NULL,0,0,0,0,datetime('now'))")
  ]);
  return true;
}

async function state(env) {
  await ensureSchema(env);
  return env.DB.prepare("SELECT * FROM lumen_travelpayouts_finance_state WHERE id='primary'").first();
}
function due(current, force = false) {
  if (force) return true;
  if (!current?.last_success_at) return true;
  const t = Date.parse(current.last_success_at);
  return !Number.isFinite(t) || Date.now() - t >= SYNC_MIN_INTERVAL_MS;
}

async function financeGet(token, path, params = {}) {
  const url = new URL(`${FINANCE_BASE}/${path}`);
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, String(value));
  }
  const response = await fetch(url.toString(), {
    headers: { accept: "application/json", "X-Access-Token": token }
  });
  const text = await response.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = null; }
  if (!response.ok) {
    const error = new Error(`travelpayouts_finance_http_${response.status}`);
    error.details = { status: response.status, body: clean(text, 500) };
    throw error;
  }
  return data;
}

async function upsertReward(env, raw) {
  const actionId = clean(raw?.action_id, 240);
  const state = clean(raw?.action_state, 40).toLowerCase();
  const profitUsd = Math.max(0, num(raw?.profit));
  if (!actionId || state !== "paid" || profitUsd <= 0) return { accepted: false, inserted: false };

  const campaignId = Number.isFinite(Number(raw?.campaign_id)) ? Number(raw.campaign_id) : null;
  const now = new Date().toISOString();
  const providerUpdatedAt = iso(raw?.updated_at || raw?.booked_at, now);
  const bookedAt = raw?.booked_at ? iso(raw.booked_at, providerUpdatedAt) : null;
  const eventId = `REVT-TP-${(await sha256(actionId)).slice(0, 18).toUpperCase()}`;
  const metadata = {
    provider: "travelpayouts",
    affiliateActionId: actionId,
    campaignId,
    bookedAt,
    providerUpdatedAt,
    description: clean(raw?.description, 500) || null,
    accountingSemantics: "confirmed_affiliate_reward_not_bank_payout",
    doubleCountProtection: "bank_payout_is_tracked_separately_and_not_added_to_realized_revenue",
    autonomousSpend: false,
    bindingActionsHumanGated: true
  };

  const existing = await env.DB.prepare("SELECT action_id FROM lumen_travelpayouts_rewards WHERE action_id=? LIMIT 1").bind(actionId).first();
  await env.DB.prepare("INSERT INTO lumen_travelpayouts_rewards(action_id,campaign_id,action_state,price_usd,profit_usd,description,booked_at,provider_updated_at,revenue_event_id,imported_at,raw_json,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(action_id) DO UPDATE SET campaign_id=excluded.campaign_id,action_state=excluded.action_state,price_usd=excluded.price_usd,profit_usd=excluded.profit_usd,description=excluded.description,booked_at=excluded.booked_at,provider_updated_at=excluded.provider_updated_at,raw_json=excluded.raw_json,engine_version=excluded.engine_version")
    .bind(actionId,campaignId,state,Math.max(0,num(raw?.price)),profitUsd,clean(raw?.description,1000)||null,bookedAt,providerUpdatedAt,eventId,now,JSON.stringify(raw||{}),VERSION).run();

  await env.DB.prepare("INSERT INTO lumen_revenue_events(id,created_at,event_type,source,item_id,amount_usd,status,evidence,metadata) VALUES(?,?,'affiliate_reward_confirmed','travelpayouts',?,?,'verified',?,?) ON CONFLICT(id) DO UPDATE SET created_at=excluded.created_at,amount_usd=excluded.amount_usd,status=excluded.status,evidence=excluded.evidence,metadata=excluded.metadata")
    .bind(eventId,providerUpdatedAt,`TP-ACTION:${actionId}`,profitUsd,`travelpayouts_paid_action:${actionId}`,JSON.stringify(metadata)).run();

  return { accepted: true, inserted: !existing, actionId, campaignId, profitUsd, eventId, providerUpdatedAt };
}

async function upsertPayout(env, raw) {
  const paymentUuid = clean(raw?.payment_uuid, 240);
  const currency = clean(raw?.currency, 12).toLowerCase();
  const amount = Math.max(0, num(raw?.amount));
  if (!paymentUuid || !currency || amount <= 0) return { accepted: false, inserted: false };

  const now = new Date().toISOString();
  const paidAt = iso(raw?.paid_at, now);
  const eventId = `REVT-TP-PAYOUT-${(await sha256(paymentUuid)).slice(0, 16).toUpperCase()}`;
  const existing = await env.DB.prepare("SELECT payment_uuid FROM lumen_travelpayouts_payouts WHERE payment_uuid=? LIMIT 1").bind(paymentUuid).first();

  await env.DB.prepare("INSERT INTO lumen_travelpayouts_payouts(payment_uuid,paid_at,amount,currency,payment_info_id,comment,payout_event_id,imported_at,raw_json,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(payment_uuid) DO UPDATE SET paid_at=excluded.paid_at,amount=excluded.amount,currency=excluded.currency,payment_info_id=excluded.payment_info_id,comment=excluded.comment,raw_json=excluded.raw_json,engine_version=excluded.engine_version")
    .bind(paymentUuid,paidAt,amount,currency,clean(raw?.payment_info_id,120)||null,clean(raw?.comment,500)||null,eventId,now,JSON.stringify(raw||{}),VERSION).run();

  const metadata = {
    provider: "travelpayouts",
    paymentUuid,
    originalAmount: amount,
    originalCurrency: currency,
    accountingSemantics: "cash_payout_observation_not_additional_revenue",
    excludedFromRealizedRevenueToPreventDoubleCounting: true,
    autonomousSpend: false
  };
  await env.DB.prepare("INSERT INTO lumen_revenue_events(id,created_at,event_type,source,item_id,amount_usd,status,evidence,metadata) VALUES(?,?,'affiliate_payout_received','travelpayouts',?,?,'verified',?,?) ON CONFLICT(id) DO UPDATE SET created_at=excluded.created_at,amount_usd=excluded.amount_usd,status=excluded.status,evidence=excluded.evidence,metadata=excluded.metadata")
    .bind(eventId,paidAt,`TP-PAYOUT:${paymentUuid}`,currency==="usd"?amount:null,`travelpayouts_payout:${paymentUuid}`,JSON.stringify(metadata)).run();

  return { accepted: true, inserted: !existing, paymentUuid, amount, currency, eventId, paidAt };
}

export async function syncTravelpayoutsFinance(env, options = {}) {
  if (!(await ensureSchema(env))) return { ok:false, error:"persistence_unavailable", version:VERSION };
  const token = clean(env?.TRAVELPAYOUTS_API_TOKEN, 500);
  const current = await state(env);
  if (!token) return { ok:false, skipped:true, reason:"travelpayouts_api_token_not_configured", version:VERSION };
  if (!due(current, options.force === true)) return { ok:true, skipped:true, reason:"hourly_cadence_not_due", version:VERSION, lastSuccessAt:current?.last_success_at||null };

  const startedAt = new Date().toISOString();
  await env.DB.prepare("UPDATE lumen_travelpayouts_finance_state SET last_sync_at=?,last_error=NULL,updated_at=? WHERE id='primary'").bind(startedAt,startedAt).run();

  let actionsSeen = 0;
  let rewardsInserted = 0;
  let payoutsSeen = 0;
  let payoutsInserted = 0;
  const rewardSample = [];
  const payoutSample = [];
  try {
    const until = clean(options.until, 20) || dateOnly(new Date());
    const defaultFrom = dateOnly(new Date(Date.now() - LOOKBACK_DAYS * 86400000));
    const requestedFrom = clean(options.from, 20) || defaultFrom;
    const from = requestedFrom <= until ? requestedFrom : until;
    const maxPages = Math.max(1, Math.min(Number(options.maxPages || MAX_PAGES), 10));
    let offset = 0;
    for (let page = 0; page < maxPages; page += 1) {
      const payload = await financeGet(token, "get_user_actions_affecting_balance", {
        currency: "usd",
        action_state: "paid",
        from,
        until,
        limit: PAGE_SIZE,
        offset
      });
      const rows = Array.isArray(payload?.actions) ? payload.actions : [];
      for (const raw of rows) {
        actionsSeen += 1;
        const result = await upsertReward(env, raw);
        if (result.inserted) rewardsInserted += 1;
        if (result.accepted && rewardSample.length < 20) rewardSample.push(result);
      }
      offset += rows.length;
      const total = Math.max(0, num(payload?.count));
      if (rows.length < PAGE_SIZE || (total > 0 && offset >= total) || rows.length === 0) break;
    }

    const payouts = await financeGet(token, "get_user_payments");
    const payoutRows = Array.isArray(payouts) ? payouts : (Array.isArray(payouts?.payments) ? payouts.payments : []);
    for (const raw of payoutRows.slice(0, 1000)) {
      payoutsSeen += 1;
      const result = await upsertPayout(env, raw);
      if (result.inserted) payoutsInserted += 1;
      if (result.accepted && payoutSample.length < 20) payoutSample.push(result);
    }

    const completedAt = new Date().toISOString();
    await env.DB.prepare("UPDATE lumen_travelpayouts_finance_state SET last_success_at=?,last_error=NULL,actions_seen=actions_seen+?,rewards_inserted=rewards_inserted+?,payouts_seen=payouts_seen+?,payouts_inserted=payouts_inserted+?,updated_at=? WHERE id='primary'")
      .bind(completedAt,actionsSeen,rewardsInserted,payoutsSeen,payoutsInserted,completedAt).run();

    return {
      ok:true,
      version:VERSION,
      actionsSeen,
      rewardsInserted,
      payoutsSeen,
      payoutsInserted,
      rewardSample,
      payoutSample,
      queryWindow:{from,until},
      truth:{
        confirmedAffiliateRewardEvent:"affiliate_reward_confirmed",
        bankPayoutEvent:"affiliate_payout_received",
        bankPayoutExcludedFromRealizedRevenue:true,
        source:"travelpayouts_finance_v2"
      },
      guardrails:{autonomousSpendUsd:0,bindingActionsHumanGated:true,secretsReturned:false}
    };
  } catch (error) {
    const failedAt = new Date().toISOString();
    await env.DB.prepare("UPDATE lumen_travelpayouts_finance_state SET last_error=?,updated_at=? WHERE id='primary'")
      .bind(clean(error?.message||error,300),failedAt).run();
    return {
      ok:false,
      version:VERSION,
      error:clean(error?.message||error,240),
      upstream:error?.details||null,
      guardrails:{autonomousSpendUsd:0,bindingActionsHumanGated:true,secretsReturned:false}
    };
  }
}

async function statusData(env) {
  await ensureSchema(env);
  const current = await state(env);
  const rewards = await env.DB.prepare("SELECT COUNT(*) count,COALESCE(SUM(profit_usd),0) revenue_usd,MAX(provider_updated_at) latest FROM lumen_travelpayouts_rewards").first();
  const payouts = await env.DB.prepare("SELECT COUNT(*) count,COALESCE(SUM(CASE WHEN currency='usd' THEN amount ELSE 0 END),0) paid_usd,MAX(paid_at) latest FROM lumen_travelpayouts_payouts").first();
  return {
    ok:true,
    version:VERSION,
    configured:Boolean(clean(env?.TRAVELPAYOUTS_API_TOKEN,500)),
    mode:"finance-v2-verified-affiliate-reward-truth",
    rewards:{count:num(rewards?.count),confirmedRevenueUsd:num(rewards?.revenue_usd),latest:rewards?.latest||null},
    payouts:{count:num(payouts?.count),cashPaidUsd:num(payouts?.paid_usd),latest:payouts?.latest||null},
    sync:{lastSuccessAt:current?.last_success_at||null,lastError:current?.last_error||null},
    accounting:{confirmedRewardsCountAsRevenue:true,payoutsAreCashObservations:true,payoutsNotCountedAgainAsRevenue:true},
    secretsExposed:false,
    autonomousSpendUsd:0,
    bindingActionsHumanGated:true
  };
}

export async function handleTravelpayoutsFinance(request, env) {
  const url = new URL(request.url);
  const paths = ["/health/travelpayouts-finance","/travelpayouts/finance/status","/travelpayouts/finance/sync"];
  if (!paths.includes(url.pathname)) return null;
  if (request.method === "OPTIONS") return new Response(null,{status:204,headers:{"access-control-allow-origin":"*","access-control-allow-headers":"content-type,x-lumen-admin","access-control-allow-methods":"GET,POST,OPTIONS"}});
  if (request.method === "GET" && ["/health/travelpayouts-finance","/travelpayouts/finance/status"].includes(url.pathname)) return json(await statusData(env));
  if (request.method === "POST" && url.pathname === "/travelpayouts/finance/sync") {
    if (!authorized(request,env)) return json({ok:false,error:"admin_token_required"},403);
    return json(await syncTravelpayoutsFinance(env,{force:true}),202);
  }
  return json({ok:false,error:"method_not_allowed"},405);
}
