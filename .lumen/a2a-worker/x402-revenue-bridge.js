const VERSION = "1.0-x402-revenue-bridge";

function json(data, status = 200) {
  return Response.json(data, { status, headers: { "cache-control": "no-store", "x-content-type-options": "nosniff", "access-control-allow-origin": "*" } });
}
function clean(value, limit = 5000) { return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit); }
function parseObject(value) {
  try { const x = typeof value === "string" ? JSON.parse(value || "{}") : (value || {}); return x && typeof x === "object" && !Array.isArray(x) ? x : {}; } catch { return {}; }
}
function authorized(request, env) {
  const configured = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500);
  const provided = clean(request.headers.get("x-lumen-admin"), 500);
  return Boolean(configured && provided && configured === provided);
}
async function sha256(text) {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(String(text)));
  return [...new Uint8Array(d)].map(b => b.toString(16).padStart(2, "0")).join("");
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_revenue_events (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, event_type TEXT NOT NULL, source TEXT NOT NULL, item_id TEXT, amount_usd REAL, status TEXT NOT NULL, evidence TEXT, metadata TEXT)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_x402_revenue_bridge (receipt_id TEXT PRIMARY KEY,revenue_event_id TEXT NOT NULL,created_at TEXT NOT NULL,proposal_id TEXT,opportunity_id TEXT,offer_id TEXT,amount_usd REAL NOT NULL,bridge_status TEXT NOT NULL,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_x402_revenue_bridge_event ON lumen_x402_revenue_bridge(revenue_event_id)")
  ]);
  return true;
}

async function safeFirst(env, sql, bind = []) {
  try { const s = env.DB.prepare(sql); return bind.length ? await s.bind(...bind).first() : await s.first(); } catch { return null; }
}
async function safeAll(env, sql, bind = []) {
  try { const s = env.DB.prepare(sql); const r = bind.length ? await s.bind(...bind).all() : await s.all(); return r.results || []; } catch { return []; }
}

function conversionIds(meta) {
  const root = parseObject(meta);
  const conversion = parseObject(root.conversion);
  return {
    proposalId: clean(conversion.session_id || conversion.conversion_session || root.proposalId || root.proposal_id, 180) || null,
    opportunityId: clean(conversion.event_id || conversion.conversion_event || root.opportunityId || root.opportunity_id, 180) || null,
    offerId: clean(conversion.campaign || root.offerId || root.offer_id, 180) || null
  };
}

async function resolveIds(env, receipt) {
  const ids = conversionIds(receipt.request_metadata);
  let proposal = null;
  if (ids.proposalId) proposal = await safeFirst(env, "SELECT proposal_id,opportunity_id,offer_id FROM lumen_proposal_drafts WHERE proposal_id=? LIMIT 1", [ids.proposalId]);
  const proposalId = proposal?.proposal_id || null;
  const opportunityId = proposal?.opportunity_id || ids.opportunityId || null;
  const offerId = proposal?.offer_id || ids.offerId || clean(receipt.product_id, 180) || null;
  return { proposalId, opportunityId, offerId };
}

export async function syncX402SettlementsToRevenue(env) {
  if (!(await ensureSchema(env))) return { ok: false, error: "persistence_unavailable", version: VERSION };
  const receipts = await safeAll(env, `SELECT r.id,r.created_at,r.product_id,r.amount_usd,r.status,r.request_metadata
    FROM lumen_x402_receipts r
    LEFT JOIN lumen_x402_revenue_bridge b ON b.receipt_id=r.id
    WHERE r.status='settled_verified' AND b.receipt_id IS NULL
    ORDER BY r.created_at ASC LIMIT 200`);
  const results = [];
  for (const receipt of receipts) {
    const meta = parseObject(receipt.request_metadata);
    if (meta?.settlement?.success !== true) continue;
    const ids = await resolveIds(env, receipt);
    const existing = await safeFirst(env, "SELECT id FROM lumen_revenue_events WHERE event_type='payment_settled' AND status='verified' AND evidence=? LIMIT 1", [`x402_receipt:${receipt.id}`]);
    const eventId = existing?.id || `REVT-X402-${(await sha256(receipt.id)).slice(0,16).toUpperCase()}`;
    const eventMeta = {
      receiptId: receipt.id,
      lumen: {
        proposalId: ids.proposalId,
        opportunityId: ids.opportunityId,
        offerId: ids.offerId
      },
      attribution: {
        rule: "settled_verified_x402_receipt_with_exact_conversion_identifiers",
        proposalExact: Boolean(ids.proposalId)
      }
    };
    if (!existing) {
      await env.DB.prepare("INSERT OR IGNORE INTO lumen_revenue_events(id,created_at,event_type,source,item_id,amount_usd,status,evidence,metadata) VALUES(?,?,'payment_settled','x402',?,?, 'verified',?,?)")
        .bind(eventId,receipt.created_at || new Date().toISOString(),ids.proposalId || ids.offerId || receipt.product_id || receipt.id,Math.max(0,Number(receipt.amount_usd || 0)),`x402_receipt:${receipt.id}`,JSON.stringify(eventMeta)).run();
    }
    await env.DB.prepare("INSERT OR IGNORE INTO lumen_x402_revenue_bridge(receipt_id,revenue_event_id,created_at,proposal_id,opportunity_id,offer_id,amount_usd,bridge_status,engine_version) VALUES(?,?,?,?,?,?,?,?,?)")
      .bind(receipt.id,eventId,new Date().toISOString(),ids.proposalId,ids.opportunityId,ids.offerId,Math.max(0,Number(receipt.amount_usd || 0)),ids.proposalId ? "ATTRIBUTABLE" : "SETTLED_UNLINKED_PROPOSAL",VERSION).run();
    results.push({ receiptId: receipt.id, revenueEventId: eventId, amountUsd: Number(receipt.amount_usd || 0), proposalId: ids.proposalId, opportunityId: ids.opportunityId, offerId: ids.offerId, status: ids.proposalId ? "ATTRIBUTABLE" : "SETTLED_UNLINKED_PROPOSAL" });
  }
  return { ok: true, version: VERSION, processed: results.length, attributable: results.filter(x => x.proposalId).length, results: results.slice(0,50), guardrails: { settledVerifiedOnly: true, noUnverifiedRevenue: true, autonomousSpend: false, bindingActionsHumanGated: true } };
}

async function statsData(env) {
  await ensureSchema(env);
  const row = await safeFirst(env, "SELECT COUNT(*) total,SUM(CASE WHEN bridge_status='ATTRIBUTABLE' THEN 1 ELSE 0 END) attributable,COALESCE(SUM(amount_usd),0) revenue FROM lumen_x402_revenue_bridge");
  return { bridgedSettlements: Number(row?.total || 0), attributableSettlements: Number(row?.attributable || 0), bridgedRevenueUsd: Number(row?.revenue || 0) };
}

export async function handleX402RevenueBridge(request, env) {
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/x402-revenue-bridge/policy") return json({ version: VERSION, truthRule: "only_settled_verified_x402_receipts_become_verified_revenue_events", exactProposalAttributionPreferred: true, autonomousSpend: false, bindingActionsHumanGated: true });
  if (request.method === "GET" && url.pathname === "/x402-revenue-bridge/stats") return json({ version: VERSION, ...await statsData(env) });
  if (request.method === "POST" && url.pathname === "/x402-revenue-bridge/sync") {
    if (!authorized(request, env)) return json({ ok: false, error: "admin_token_required" }, 403);
    return json(await syncX402SettlementsToRevenue(env), 202);
  }
  return null;
}
