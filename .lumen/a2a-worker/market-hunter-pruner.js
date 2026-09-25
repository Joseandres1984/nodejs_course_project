const VERSION = "1.0-market-hunter-pruner";
const MAX_DEACTIVATIONS_PER_CYCLE = 2;
const MIN_ACTIVE_STRATEGIES = 8;
const PROTECTED_SEEDS = new Set([
  "MH-SUPPLIER-VERIFY",
  "MH-RFQ-PRICE",
  "MH-TENDER-BID",
  "MH-SOURCING",
  "MH-BUYER-INTENT",
  "MH-EXPORT",
  "MH-X402-COMMERCE",
  "MH-VENDOR-COMPARE"
]);

function json(data, status = 200) {
  return Response.json(data, { status, headers: { "cache-control":"no-store", "x-content-type-options":"nosniff", "access-control-allow-origin":"*" } });
}
function clean(value, limit = 1000) { return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit); }
function num(value, fallback = 0) { const n = Number(value); return Number.isFinite(n) ? n : fallback; }
function authorized(request, env) {
  const configured = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500);
  const provided = clean(request.headers.get("x-lumen-admin"), 500);
  return Boolean(configured && provided && configured === provided);
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_market_hunter_pruning_events (id TEXT PRIMARY KEY,created_at TEXT NOT NULL,strategy_id TEXT NOT NULL,action TEXT NOT NULL,reason TEXT NOT NULL,before_json TEXT,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_market_hunter_pruning_events_created ON lumen_market_hunter_pruning_events(created_at DESC)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_market_hunter_pruning_events_strategy ON lumen_market_hunter_pruning_events(strategy_id,created_at DESC)")
  ]);
  return true;
}

async function all(env, sql, binds = []) {
  try { const q = env.DB.prepare(sql); const r = binds.length ? await q.bind(...binds).all() : await q.all(); return r.results || []; } catch { return []; }
}
async function first(env, sql, binds = []) {
  try { const q = env.DB.prepare(sql); return binds.length ? await q.bind(...binds).first() : await q.first(); } catch { return null; }
}

function pruneReason(row) {
  const id = clean(row?.id, 120);
  if (!id || PROTECTED_SEEDS.has(id)) return null;
  const runs = num(row?.runs);
  const noSignalRuns = num(row?.no_signal_runs);
  const actionable = num(row?.actionable);
  const proposals = num(row?.proposals);
  const qualified = num(row?.qualified_responses);
  const settlements = num(row?.settlements);
  const score = num(row?.score, 50);

  if (settlements > 0 || qualified > 0) return null;
  if (runs >= 5 && noSignalRuns >= 4 && actionable === 0 && proposals === 0) {
    return "repeated_zero_signal_without_downstream_progress";
  }
  if (runs >= 8 && actionable === 0 && proposals === 0 && score < 32) {
    return "extended_low_value_search_lane";
  }
  return null;
}

async function recordEvent(env, strategy, action, reason) {
  const now = new Date().toISOString();
  const id = `MHP-${crypto.randomUUID().replaceAll("-", "").slice(0, 16).toUpperCase()}`;
  await env.DB.prepare("INSERT INTO lumen_market_hunter_pruning_events(id,created_at,strategy_id,action,reason,before_json,engine_version) VALUES(?,?,?,?,?,?,?)")
    .bind(id, now, strategy.id, action, reason, JSON.stringify({
      active:num(strategy.active), runs:num(strategy.runs), discoveries:num(strategy.discoveries), actionable:num(strategy.actionable), proposals:num(strategy.proposals), qualifiedResponses:num(strategy.qualified_responses), settlements:num(strategy.settlements), revenueUsd:num(strategy.revenue_usd), score:num(strategy.score), noSignalRuns:num(strategy.no_signal_runs), generation:num(strategy.generation)
    }).slice(0,4000), VERSION).run();
}

export async function pruneMarketHunterStrategies(env) {
  if (!(await ensureSchema(env))) return { ok:false, error:"persistence_unavailable", version:VERSION };
  const strategies = await all(env, "SELECT id,query,offer_id,parent_id,generation,active,runs,discoveries,actionable,proposals,qualified_responses,settlements,revenue_usd,score,evidence_level,no_signal_runs,last_run_at,last_reason FROM lumen_market_hunter_strategies ORDER BY active DESC,score ASC,runs DESC,id");
  if (!strategies.length) return { ok:true, version:VERSION, deactivated:[], reactivated:[], reason:"no_strategies_initialized" };

  let activeCount = strategies.filter(x => num(x.active) === 1).length;
  const candidates = strategies
    .filter(x => num(x.active) === 1)
    .map(x => ({ row:x, reason:pruneReason(x) }))
    .filter(x => x.reason)
    .sort((a,b) => num(a.row.score)-num(b.row.score) || num(b.row.no_signal_runs)-num(a.row.no_signal_runs) || num(b.row.runs)-num(a.row.runs));

  const deactivated = [];
  for (const candidate of candidates) {
    if (deactivated.length >= MAX_DEACTIVATIONS_PER_CYCLE) break;
    if (activeCount <= MIN_ACTIVE_STRATEGIES) break;
    await recordEvent(env, candidate.row, "DEACTIVATE", candidate.reason);
    await env.DB.prepare("UPDATE lumen_market_hunter_strategies SET active=0,updated_at=?,last_reason=?,engine_version=? WHERE id=? AND active=1")
      .bind(new Date().toISOString(), `pruned:${candidate.reason}`, VERSION, candidate.row.id).run();
    deactivated.push({ strategyId:candidate.row.id, query:candidate.row.query, score:num(candidate.row.score), runs:num(candidate.row.runs), noSignalRuns:num(candidate.row.no_signal_runs), reason:candidate.reason });
    activeCount -= 1;
  }

  const reactivated = [];
  if (activeCount < MIN_ACTIVE_STRATEGIES) {
    const inactive = strategies
      .filter(x => num(x.active) === 0)
      .sort((a,b) => num(b.settlements)-num(a.settlements) || num(b.qualified_responses)-num(a.qualified_responses) || num(b.actionable)-num(a.actionable) || num(b.score)-num(a.score));
    for (const row of inactive) {
      if (activeCount >= MIN_ACTIVE_STRATEGIES) break;
      await recordEvent(env, row, "REACTIVATE", "minimum_exploration_capacity_guard");
      await env.DB.prepare("UPDATE lumen_market_hunter_strategies SET active=1,updated_at=?,no_signal_runs=0,last_reason=?,engine_version=? WHERE id=? AND active=0")
        .bind(new Date().toISOString(), "reactivated:minimum_exploration_capacity_guard", VERSION, row.id).run();
      reactivated.push({ strategyId:row.id, query:row.query, previousScore:num(row.score), reason:"minimum_exploration_capacity_guard" });
      activeCount += 1;
    }
  }

  return {
    ok:true,
    version:VERSION,
    activeStrategiesAfter:activeCount,
    deactivated,
    reactivated,
    guardrails:{
      protectedSeedStrategies:PROTECTED_SEEDS.size,
      seedStrategiesCanBeAutoPruned:false,
      maxDeactivationsPerCycle:MAX_DEACTIVATIONS_PER_CYCLE,
      minimumActiveStrategies:MIN_ACTIVE_STRATEGIES,
      verifiedRevenueStrategyCanBeAutoPruned:false,
      qualifiedResponseStrategyCanBeAutoPruned:false,
      createsExternalMessages:false,
      autonomousSpend:false,
      autonomousPurchase:false,
      autonomousContract:false,
      bindingActionsHumanGated:true
    }
  };
}

async function state(env) {
  await ensureSchema(env);
  const counts = await first(env, "SELECT COUNT(*) total,SUM(CASE WHEN active=1 THEN 1 ELSE 0 END) active,SUM(CASE WHEN active=0 THEN 1 ELSE 0 END) inactive FROM lumen_market_hunter_strategies");
  const recent = await all(env, "SELECT created_at,strategy_id,action,reason FROM lumen_market_hunter_pruning_events ORDER BY created_at DESC LIMIT 20");
  return {
    version:VERSION,
    totalStrategies:num(counts?.total),
    activeStrategies:num(counts?.active),
    inactiveStrategies:num(counts?.inactive),
    recentEvents:recent,
    policy:{ maxDeactivationsPerCycle:MAX_DEACTIVATIONS_PER_CYCLE, minimumActiveStrategies:MIN_ACTIVE_STRATEGIES, protectedSeedStrategies:PROTECTED_SEEDS.size }
  };
}

export async function handleMarketHunterPruner(request, env) {
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/market-hunter/pruning/policy") return json({
    version:VERSION,
    objective:"stop_repeating_search_lanes_that_show_no_downstream_economic_progress_and_reallocate_attention_to_exploration",
    pruneRule:"only_non_seed_strategies_with_repeated_zero_signal_or_extended_low_value_performance",
    protectedEvidence:["qualified_commercial_response","verified_settlement","verified_revenue"],
    seedStrategiesCanBeAutoPruned:false,
    maxDeactivationsPerCycle:MAX_DEACTIVATIONS_PER_CYCLE,
    minimumActiveStrategies:MIN_ACTIVE_STRATEGIES,
    createsExternalMessages:false,
    autonomousSpend:false,
    autonomousPurchase:false,
    autonomousContract:false,
    bindingActionsHumanGated:true
  });
  if (request.method === "GET" && url.pathname === "/market-hunter/pruning/state") return json(await state(env));
  if (request.method === "POST" && url.pathname === "/market-hunter/pruning/run") {
    if (!authorized(request, env)) return json({ ok:false, error:"admin_token_required" },403);
    return json(await pruneMarketHunterStrategies(env),202);
  }
  return null;
}
