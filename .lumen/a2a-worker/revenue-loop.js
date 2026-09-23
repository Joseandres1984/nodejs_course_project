const VERSION = "1.0-revenue-loop";

function json(data, status = 200) {
  return Response.json(data, { status, headers: { "cache-control": "no-store", "x-content-type-options": "nosniff", "access-control-allow-origin": "*" } });
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_revenue_events (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, event_type TEXT NOT NULL, source TEXT NOT NULL, item_id TEXT, amount_usd REAL, status TEXT NOT NULL, evidence TEXT, metadata TEXT)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_revenue_events_type ON lumen_revenue_events(event_type,created_at)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_revenue_actions (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, action_type TEXT NOT NULL, priority INTEGER NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL, metadata TEXT)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_revenue_actions_status ON lumen_revenue_actions(status,priority,created_at)")
  ]);
  return true;
}

async function scalar(env, sql) {
  try { const row = await env.DB.prepare(sql).first(); return Number(row?.n || 0); } catch { return 0; }
}

async function snapshot(env) {
  await ensureSchema(env);
  const [inquiries, quotes, orders, inbound, events] = await Promise.all([
    scalar(env, "SELECT COUNT(*) AS n FROM lumen_revenue_inquiries"),
    scalar(env, "SELECT COUNT(*) AS n FROM lumen_a2a_quotes"),
    scalar(env, "SELECT COUNT(*) AS n FROM lumen_machine_orders"),
    scalar(env, "SELECT COUNT(*) AS n FROM lumen_a2a_inbound WHERE binding_intent=0"),
    scalar(env, "SELECT COUNT(*) AS n FROM lumen_revenue_events")
  ]);
  const settled = await scalar(env, "SELECT COUNT(*) AS n FROM lumen_revenue_events WHERE event_type='payment_settled' AND status='verified'");
  let realized = 0;
  try { const row = await env.DB.prepare("SELECT COALESCE(SUM(amount_usd),0) AS n FROM lumen_revenue_events WHERE event_type='payment_settled' AND status='verified'").first(); realized = Number(row?.n || 0); } catch {}
  const bottleneck = settled > 0 ? "scale_winners" : orders > 0 ? "settlement_and_delivery" : (quotes > 0 || inquiries > 0 || inbound > 0) ? "conversion" : "demand_generation";
  return { version: VERSION, funnel: { inbound, inquiries, quotes, orders, verifiedSettlements: settled, revenueEvents: events, realizedRevenueUsd: realized }, bottleneck };
}

function recommendation(s) {
  if (s.bottleneck === "demand_generation") return { action: "find_verified_buyer_demand", priority: 100, reason: "No commercial demand has entered the revenue funnel yet.", preferredOffers: ["MP-BUYER-SIGNALS","MP-TENDER-SCAN","MP-SOURCING-5"] };
  if (s.bottleneck === "conversion") return { action: "convert_existing_interest", priority: 95, reason: "Interest exists but has not become an order. Prioritize concrete scope, checkout route and non-binding follow-up.", preferredOffers: ["MP-SUPPLIER-SNAPSHOT","MP-QUOTE-SANITY","MP-TENDER-SCAN"] };
  if (s.bottleneck === "settlement_and_delivery") return { action: "verify_settlement_then_deliver", priority: 100, reason: "Orders exist. Do not count revenue or release paid work until canonical settlement is verified.", preferredOffers: [] };
  return { action: "scale_verified_winners", priority: 90, reason: "At least one verified settlement exists. Increase discovery for the best converting offer while preserving evidence and quality gates.", preferredOffers: [] };
}

async function recordEvent(request, env) {
  let body; try { body = await request.json(); } catch { return json({ok:false,error:"invalid_json"},400); }
  const allowed = new Set(["opportunity_verified","quote_created","order_received","payment_settled","delivery_released","conversion_lost"]);
  const eventType = String(body?.event_type || "").trim();
  if (!allowed.has(eventType)) return json({ok:false,error:"unsupported_event_type"},400);
  if (eventType === "payment_settled" && body?.status !== "verified") return json({ok:false,error:"settlement_must_be_verified"},400);
  await ensureSchema(env);
  const id = `REVT-${crypto.randomUUID().replaceAll("-","").slice(0,12).toUpperCase()}`;
  await env.DB.prepare("INSERT INTO lumen_revenue_events(id,created_at,event_type,source,item_id,amount_usd,status,evidence,metadata) VALUES(?,?,?,?,?,?,?,?,?)")
    .bind(id,new Date().toISOString(),eventType,String(body?.source||"unknown").slice(0,100),String(body?.item_id||"").slice(0,100),Number(body?.amount_usd||0),String(body?.status||"observed").slice(0,50),String(body?.evidence||"").slice(0,2000),JSON.stringify(body?.metadata||{})).run();
  return json({ok:true,event_id:id,event_type:eventType,counts_as_realized_revenue:eventType==="payment_settled"&&body?.status==="verified"},202);
}

export async function handleRevenueLoop(request, env) {
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/revenue/loop") {
    const s = await snapshot(env); return json({...s,recommendation:recommendation(s),guardrails:{autonomousOutgoingSpend:false,bindingActionsHumanGated:true,verifiedSettlementRequiredForRevenue:true,verifiedSettlementRequiredBeforePaidDelivery:true}});
  }
  if (request.method === "GET" && url.pathname === "/revenue/next-action") {
    const s = await snapshot(env); return json({version:VERSION,bottleneck:s.bottleneck,nextAction:recommendation(s),funnel:s.funnel});
  }
  if (request.method === "POST" && url.pathname === "/revenue/event") return recordEvent(request,env);
  return null;
}
