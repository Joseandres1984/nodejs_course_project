const VERSION = "1.0-demand-first";

function clean(v, n = 4000) { return String(v ?? "").trim().replace(/\s+/g, " ").slice(0, n); }
function num(v, d = 0) { const n = Number(v); return Number.isFinite(n) ? n : d; }
function clamp(v, lo = 0, hi = 100) { return Math.max(lo, Math.min(hi, num(v))); }
function json(data, status = 200) { return Response.json(data, { status, headers: { "cache-control":"no-store", "access-control-allow-origin":"*" } }); }
function authorized(request, env) {
  const configured = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500);
  const provided = clean(request.headers.get("x-lumen-admin"), 500);
  return Boolean(configured && provided && configured === provided);
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_demand_first_scores (opportunity_id TEXT PRIMARY KEY, score INTEGER NOT NULL, evidence_class TEXT NOT NULL, demand_verified INTEGER NOT NULL DEFAULT 0, reasons_json TEXT NOT NULL, scored_at TEXT NOT NULL, engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_demand_first_rank ON lumen_demand_first_scores(demand_verified DESC,score DESC,scored_at DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_demand_first_runs (id TEXT PRIMARY KEY,started_at TEXT NOT NULL,finished_at TEXT,status TEXT NOT NULL,reviewed INTEGER NOT NULL DEFAULT 0,verified INTEGER NOT NULL DEFAULT 0,high_intent INTEGER NOT NULL DEFAULT 0,engine_version TEXT NOT NULL)")
  ]);
  return true;
}

function scoreRow(row) {
  const text = clean(`${row.name || ""} ${row.description || ""} ${row.tags_json || ""} ${row.evidence || ""} ${row.raw_json || ""}`, 20000).toLowerCase();
  let score = 0;
  const reasons = [];
  const explicit = ["request for quote","rfq","request a quote","seeking supplier","looking for supplier","need supplier","need a supplier","looking to buy","want to buy","purchase order","procurement notice","invitation to bid","tender","quantity","budget"];
  const intent = ["buy","buying","buyer","procure","procurement","purchase","quote","quotation","source","sourcing","supplier","vendor","deadline","delivery"];
  const weak = ["market intelligence","research","directory","catalog","general information"];
  const explicitHits = explicit.filter(x => text.includes(x));
  const intentHits = intent.filter(x => text.includes(x));
  const weakHits = weak.filter(x => text.includes(x));
  if (explicitHits.length) { score += Math.min(60, 30 + explicitHits.length * 10); reasons.push(`explicit_intent:${explicitHits.slice(0,4).join("|")}`); }
  if (intentHits.length) { score += Math.min(25, intentHits.length * 4); reasons.push(`commercial_terms:${intentHits.length}`); }
  if (num(row.demand_signal) > 0) { score += 10; reasons.push("upstream_demand_signal"); }
  if (num(row.score) >= 75) { score += 5; reasons.push("upstream_high_fit"); }
  if (clean(row.endpoint,500)) { score += 5; reasons.push("reachable_counterparty"); }
  if (weakHits.length && !explicitHits.length) { score -= Math.min(20, weakHits.length * 7); reasons.push("weak_generic_signal"); }
  score = Math.round(clamp(score));
  const demandVerified = explicitHits.length > 0 && score >= 55 ? 1 : 0;
  const evidenceClass = demandVerified ? "VERIFIED_DEMAND" : score >= 45 ? "HIGH_INTENT" : score >= 25 ? "POSSIBLE_INTENT" : "NO_DEMAND_EVIDENCE";
  return { score, demandVerified, evidenceClass, reasons };
}

export async function runDemandFirst(env) {
  if (!(await ensureSchema(env))) return { ok:false, error:"persistence_unavailable", version:VERSION };
  const startedAt = new Date().toISOString();
  const runId = `DF-${crypto.randomUUID().replaceAll("-","").slice(0,14).toUpperCase()}`;
  await env.DB.prepare("INSERT INTO lumen_demand_first_runs(id,started_at,status,engine_version) VALUES(?,?,?,?)").bind(runId,startedAt,"running",VERSION).run();
  let rows = [];
  try {
    const r = await env.DB.prepare("SELECT id,name,endpoint,description,tags_json,score,demand_signal,evidence,raw_json,status FROM lumen_opportunities WHERE status NOT IN ('rejected','closed','lost') ORDER BY updated_at DESC LIMIT 250").all();
    rows = r.results || [];
  } catch (e) {
    await env.DB.prepare("UPDATE lumen_demand_first_runs SET finished_at=?,status=? WHERE id=?").bind(new Date().toISOString(),"source_unavailable",runId).run();
    return { ok:false, version:VERSION, runId, error:"opportunity_source_unavailable" };
  }
  let verified = 0, highIntent = 0;
  const ranked = [];
  for (const row of rows) {
    const s = scoreRow(row);
    if (s.demandVerified) verified++;
    if (s.score >= 45) highIntent++;
    await env.DB.prepare("INSERT INTO lumen_demand_first_scores(opportunity_id,score,evidence_class,demand_verified,reasons_json,scored_at,engine_version) VALUES(?,?,?,?,?,?,?) ON CONFLICT(opportunity_id) DO UPDATE SET score=excluded.score,evidence_class=excluded.evidence_class,demand_verified=excluded.demand_verified,reasons_json=excluded.reasons_json,scored_at=excluded.scored_at,engine_version=excluded.engine_version")
      .bind(row.id,s.score,s.evidenceClass,s.demandVerified,JSON.stringify(s.reasons),new Date().toISOString(),VERSION).run();
    ranked.push({ opportunityId:row.id, name:row.name, score:s.score, demandVerified:Boolean(s.demandVerified), evidenceClass:s.evidenceClass, reasons:s.reasons });
  }
  ranked.sort((a,b)=>Number(b.demandVerified)-Number(a.demandVerified) || b.score-a.score);
  await env.DB.prepare("UPDATE lumen_demand_first_runs SET finished_at=?,status='complete',reviewed=?,verified=?,high_intent=? WHERE id=?")
    .bind(new Date().toISOString(),rows.length,verified,highIntent,runId).run();
  return { ok:true, version:VERSION, runId, reviewed:rows.length, verifiedDemand:verified, highIntent, top:ranked.slice(0,20), policy:{ demandBeforeGenericLead:true, explicitEvidenceRequiredForVerifiedDemand:true, inferredDemandForbidden:true, autonomousSpend:false, bindingActionsHumanGated:true } };
}

export async function demandFirstState(env) {
  if (!(await ensureSchema(env))) return { ok:false, error:"persistence_unavailable", version:VERSION };
  const totals = await env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN demand_verified=1 THEN 1 ELSE 0 END) verified,SUM(CASE WHEN score>=45 THEN 1 ELSE 0 END) high_intent FROM lumen_demand_first_scores").first();
  const top = await env.DB.prepare("SELECT s.opportunity_id,s.score,s.evidence_class,s.demand_verified,s.reasons_json,o.name,o.endpoint,o.status FROM lumen_demand_first_scores s LEFT JOIN lumen_opportunities o ON o.id=s.opportunity_id ORDER BY s.demand_verified DESC,s.score DESC,s.scored_at DESC LIMIT 20").all();
  return { ok:true, version:VERSION, totals:{ scored:num(totals?.total), verifiedDemand:num(totals?.verified), highIntent:num(totals?.high_intent) }, top:(top.results || []).map(x=>({ ...x, demand_verified:Boolean(x.demand_verified), reasons:(()=>{try{return JSON.parse(x.reasons_json||"[]")}catch{return[]}})() })) };
}

export async function handleDemandFirst(request, env) {
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/demand-first/state") return json(await demandFirstState(env));
  if (request.method === "GET" && url.pathname === "/demand-first/policy") return json({ version:VERSION, objective:"verified_demand_before_generic_prospecting", truthRule:"verified demand requires explicit observed purchase/procurement/RFQ/tender/supplier-seeking evidence; never infer need from company identity alone", autonomousSpend:false, bindingActionsHumanGated:true });
  if (request.method === "POST" && url.pathname === "/demand-first/run") {
    if (!authorized(request, env)) return json({ ok:false, error:"admin_token_required" },403);
    return json(await runDemandFirst(env),202);
  }
  return null;
}
