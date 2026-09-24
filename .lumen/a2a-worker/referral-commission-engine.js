const VERSION = "1.2-referral-commission-engine-final-value";
const DEFAULT_PROPOSED_RATE_PCT = 5;

function json(data, status = 200) {
  return Response.json(data, { status, headers: { "cache-control":"no-store", "x-content-type-options":"nosniff", "access-control-allow-origin":"*" } });
}
function clean(value, limit = 5000) { return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit); }
function num(value, fallback = 0) { const n = Number(value); return Number.isFinite(n) ? n : fallback; }
function authorized(request, env) {
  const configured = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500);
  const provided = clean(request.headers.get("x-lumen-admin"), 500);
  return Boolean(configured && provided && configured === provided);
}
async function bodyJson(request) { try { return await request.json(); } catch { return {}; } }
function commissionId(referralId) { return `COM-${clean(referralId, 80).replace(/[^A-Za-z0-9]/g, "").slice(-20).toUpperCase()}`; }
function checkoutUrl(env, referralId) {
  const base = clean(env?.X402_CHECKOUT_URL, 1000).replace(/\/+$/, "");
  return base ? `${base}/commission/${encodeURIComponent(referralId)}` : null;
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_referral_commissions (id TEXT PRIMARY KEY,referral_id TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,basis_type TEXT NOT NULL,deal_value_usd REAL,proposed_rate_pct REAL,proposed_amount_usd REAL,agreed_rate_pct REAL,agreed_amount_usd REAL,currency TEXT NOT NULL DEFAULT 'USD',status TEXT NOT NULL,agreement_source TEXT,agreement_evidence TEXT,agreement_at TEXT,completion_evidence TEXT,payment_due_at TEXT,checkout_url TEXT,settlement_event_id TEXT,settled_amount_usd REAL NOT NULL DEFAULT 0,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_referral_commissions_status ON lumen_referral_commissions(status,updated_at)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_revenue_events (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, event_type TEXT NOT NULL, source TEXT NOT NULL, item_id TEXT, amount_usd REAL, status TEXT NOT NULL, evidence TEXT, metadata TEXT)")
  ]);
  return true;
}

async function logReferralEvent(env, referralId, eventType, detail = "", amount = null, verified = false) {
  try {
    const id = `RFCE-${crypto.randomUUID().replaceAll("-", "").slice(0, 18).toUpperCase()}`;
    await env.DB.prepare("INSERT INTO lumen_referral_events(id,referral_id,created_at,event_type,detail,amount_usd,verified) VALUES(?,?,?,?,?,?,?)")
      .bind(id, referralId, new Date().toISOString(), clean(eventType, 100), clean(detail, 3000) || null, amount == null ? null : num(amount), verified ? 1 : 0).run();
  } catch {}
}

export async function planReferralCommissions(env) {
  if (!(await ensureSchema(env))) return { ok:false, error:"persistence_unavailable", version:VERSION };
  let rows = [];
  try {
    const result = await env.DB.prepare("SELECT id,direction,estimated_value_usd,commission_status,status FROM lumen_referrals WHERE commission_status IN ('NOT_CONFIGURED','BASIS_REQUIRED') AND status NOT IN ('BLOCKED_TRUST','SETTLED') ORDER BY updated_at DESC LIMIT 120").all();
    rows = result.results || [];
  } catch {
    return { ok:false, error:"referral_table_not_ready", version:VERSION };
  }

  const now = new Date().toISOString();
  const planned = [];
  for (const ref of rows) {
    const dealValue = Math.max(0, num(ref.estimated_value_usd));
    const proposedAmount = dealValue > 0 ? Math.round((dealValue * DEFAULT_PROPOSED_RATE_PCT / 100) * 100) / 100 : null;
    const status = "PROPOSAL_READY";
    const id = commissionId(ref.id);
    await env.DB.prepare("INSERT INTO lumen_referral_commissions(id,referral_id,created_at,updated_at,basis_type,deal_value_usd,proposed_rate_pct,proposed_amount_usd,status,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(referral_id) DO UPDATE SET updated_at=excluded.updated_at,deal_value_usd=COALESCE(excluded.deal_value_usd,lumen_referral_commissions.deal_value_usd),proposed_rate_pct=excluded.proposed_rate_pct,proposed_amount_usd=excluded.proposed_amount_usd,status=CASE WHEN lumen_referral_commissions.status='BASIS_REQUIRED' THEN 'PROPOSAL_READY' ELSE lumen_referral_commissions.status END,engine_version=excluded.engine_version")
      .bind(id, ref.id, now, now, "SUCCESS_FEE_PERCENT", dealValue || null, DEFAULT_PROPOSED_RATE_PCT, proposedAmount, status, VERSION).run();
    await env.DB.prepare("UPDATE lumen_referrals SET commission_status='PROPOSAL_READY',updated_at=? WHERE id=? AND commission_status IN ('NOT_CONFIGURED','BASIS_REQUIRED')")
      .bind(now, ref.id).run();
    await logReferralEvent(env, ref.id, "COMMISSION_CASE_PLANNED", `status=PROPOSAL_READY;internal_proposed_rate_pct=${DEFAULT_PROPOSED_RATE_PCT};final_value_required_only_on_close=true;non_binding=true`, proposedAmount, false);
    planned.push({ referralId:ref.id, commissionId:id, status:"PROPOSAL_READY", dealValueUsd:dealValue || null, proposedRatePct:DEFAULT_PROPOSED_RATE_PCT, proposedAmountUsd:proposedAmount });
  }
  return { ok:true, version:VERSION, planned:planned.length, cases:planned.slice(0,50), guardrails:{ proposalIsInternalOnly:true, counterpartyNotContacted:true, agreementRequiredBeforePayment:true, estimatedDealValueNotRequiredForPercentageProposal:true, finalDealValueRequiredBeforePaymentDue:true, autonomousSpend:false, automaticContract:false } };
}

export async function recordCommissionAgreement(env, body = {}) {
  if (!(await ensureSchema(env))) return { ok:false, error:"persistence_unavailable", version:VERSION };
  const referralId = clean(body.referralId || body.referral_id, 100);
  const evidence = clean(body.agreementEvidence || body.agreement_evidence, 4000);
  const source = clean(body.agreementSource || body.agreement_source || "explicit_counterparty_acceptance", 120);
  const dealValue = Math.max(0, num(body.dealValueUsd || body.deal_value_usd));
  const rate = Math.max(0, num(body.agreedRatePct || body.agreed_rate_pct));
  let amount = Math.max(0, num(body.agreedAmountUsd || body.agreed_amount_usd));
  if (!referralId) return { ok:false, error:"referral_id_required", version:VERSION };
  if (evidence.length < 8) return { ok:false, error:"explicit_agreement_evidence_required", version:VERSION };
  if (!(rate > 0) && !(amount > 0)) return { ok:false, error:"agreed_commission_rate_or_amount_required", version:VERSION };
  if (rate > 50) return { ok:false, error:"agreed_rate_out_of_policy_range", version:VERSION };

  if (rate > 0) amount = 0;

  const referral = await env.DB.prepare("SELECT id FROM lumen_referrals WHERE id=? LIMIT 1").bind(referralId).first();
  if (!referral) return { ok:false, error:"referral_not_found", version:VERSION };
  const existing = await env.DB.prepare("SELECT * FROM lumen_referral_commissions WHERE referral_id=? LIMIT 1").bind(referralId).first();
  const now = new Date().toISOString();
  const id = existing?.id || commissionId(referralId);
  const basis = rate > 0 ? "SUCCESS_FEE_PERCENT" : "FIXED_SUCCESS_FEE";
  if (existing) {
    await env.DB.prepare("UPDATE lumen_referral_commissions SET updated_at=?,basis_type=?,deal_value_usd=?,agreed_rate_pct=?,agreed_amount_usd=?,status='AGREED_PENDING_CLOSE',agreement_source=?,agreement_evidence=?,agreement_at=?,engine_version=? WHERE referral_id=?")
      .bind(now,basis,dealValue || existing.deal_value_usd || null,rate || null,amount || null,source,evidence,now,VERSION,referralId).run();
  } else {
    await env.DB.prepare("INSERT INTO lumen_referral_commissions(id,referral_id,created_at,updated_at,basis_type,deal_value_usd,proposed_rate_pct,proposed_amount_usd,agreed_rate_pct,agreed_amount_usd,currency,status,agreement_source,agreement_evidence,agreement_at,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,'USD','AGREED_PENDING_CLOSE',?,?,?,?)")
      .bind(id,referralId,now,now,basis,dealValue || null,null,null,rate || null,amount || null,source,evidence,now,VERSION).run();
  }
  await env.DB.prepare("UPDATE lumen_referrals SET commission_status='AGREED_PENDING_CLOSE',updated_at=? WHERE id=?").bind(now,referralId).run();
  await logReferralEvent(env, referralId, "COMMISSION_AGREED", `rate_pct=${rate || "fixed"};fixed_amount_usd=${amount || "pending_final_deal_value"};source=${source};automatic_contract=false`, amount || null, false);
  return { ok:true, version:VERSION, referralId, commissionId:id, status:"AGREED_PENDING_CLOSE", agreedAmountUsd:amount || null, agreedRatePct:rate || null, paymentDue:false, checkoutUrl:null, guardrails:{ explicitAgreementEvidenceRequired:true, percentageFeeUsesFinalDealValue:true, noRevenueRecognizedYet:true, autonomousSpend:false, automaticContract:false } };
}

export async function markCommissionDue(env, body = {}) {
  if (!(await ensureSchema(env))) return { ok:false, error:"persistence_unavailable", version:VERSION };
  const referralId = clean(body.referralId || body.referral_id, 100);
  const completionEvidence = clean(body.completionEvidence || body.completion_evidence, 4000);
  const finalDealValue = Math.max(0, num(body.finalDealValueUsd || body.final_deal_value_usd));
  if (!referralId) return { ok:false, error:"referral_id_required", version:VERSION };
  if (completionEvidence.length < 8) return { ok:false, error:"deal_completion_evidence_required", version:VERSION };
  const row = await env.DB.prepare("SELECT * FROM lumen_referral_commissions WHERE referral_id=? LIMIT 1").bind(referralId).first();
  if (!row) return { ok:false, error:"commission_case_not_found", version:VERSION };
  if (row.status === "SETTLED") return { ok:true, version:VERSION, referralId, status:"SETTLED", duplicateSafe:true };
  if (row.status === "PAYMENT_DUE") return { ok:true, version:VERSION, referralId, commissionId:row.id, status:"PAYMENT_DUE", amountUsd:num(row.agreed_amount_usd), checkoutUrl:row.checkout_url, duplicateSafe:true };
  if (row.status !== "AGREED_PENDING_CLOSE") return { ok:false, error:"commission_must_be_agreed_before_becoming_due", currentStatus:row.status, version:VERSION };

  const rate = Math.max(0, num(row.agreed_rate_pct));
  let amount = Math.max(0, num(row.agreed_amount_usd));
  let payableDealValue = Math.max(0, finalDealValue || num(row.deal_value_usd));
  if (rate > 0) {
    if (!(finalDealValue > 0)) return { ok:false, error:"final_deal_value_required_for_percentage_commission", agreedRatePct:rate, version:VERSION };
    payableDealValue = finalDealValue;
    amount = Math.round((payableDealValue * rate / 100) * 100) / 100;
  }
  if (!(amount > 0)) return { ok:false, error:"agreed_amount_missing", version:VERSION };

  const now = new Date().toISOString();
  const checkout = checkoutUrl(env, referralId);
  if (!checkout) return { ok:false, error:"x402_checkout_base_not_configured", version:VERSION };
  await env.DB.prepare("UPDATE lumen_referral_commissions SET status='PAYMENT_DUE',deal_value_usd=?,agreed_amount_usd=?,completion_evidence=?,payment_due_at=?,checkout_url=?,updated_at=?,engine_version=? WHERE referral_id=?")
    .bind(payableDealValue || null,amount,completionEvidence,now,checkout,now,VERSION,referralId).run();
  await env.DB.prepare("UPDATE lumen_referrals SET commission_status='PAYMENT_DUE',estimated_value_usd=?,updated_at=? WHERE id=?").bind(payableDealValue || 0,now,referralId).run();
  await logReferralEvent(env, referralId, "COMMISSION_PAYMENT_DUE", `final_deal_value_usd=${payableDealValue};agreed_rate_pct=${rate || "fixed"};agreed_amount_usd=${amount};checkout_ready=true`, amount, false);
  return { ok:true, version:VERSION, referralId, commissionId:row.id, status:"PAYMENT_DUE", finalDealValueUsd:payableDealValue, agreedRatePct:rate || null, amountUsd:amount, checkoutUrl:checkout, guardrails:{ completionEvidenceRequired:true, exactAgreedAmount:true, finalDealValueRequiredForPercentageFee:true, revenueRecognizedOnlyAfterVerifiedSettlement:true, autonomousSpend:false } };
}

export async function syncReferralCommissionSettlements(env) {
  if (!(await ensureSchema(env))) return { ok:false, error:"persistence_unavailable", version:VERSION };
  const result = await env.DB.prepare("SELECT * FROM lumen_referral_commissions WHERE status='PAYMENT_DUE' ORDER BY updated_at ASC LIMIT 150").all();
  const settled = [];
  const mismatches = [];
  for (const row of result.results || []) {
    const expected = Math.max(0, num(row.agreed_amount_usd));
    if (!(expected > 0)) continue;
    let event = null;
    try {
      event = await env.DB.prepare("SELECT id,amount_usd,evidence,metadata,created_at FROM lumen_revenue_events WHERE event_type='payment_settled' AND source='x402' AND status='verified' AND item_id=? AND ABS(amount_usd-?)<=0.01 ORDER BY created_at ASC LIMIT 1")
        .bind(row.referral_id,expected).first();
    } catch {}
    if (!event) {
      try {
        const mismatch = await env.DB.prepare("SELECT id,amount_usd FROM lumen_revenue_events WHERE event_type='payment_settled' AND source='x402' AND status='verified' AND item_id=? ORDER BY created_at ASC LIMIT 1").bind(row.referral_id).first();
        if (mismatch) mismatches.push({ referralId:row.referral_id, revenueEventId:mismatch.id, expectedAmountUsd:expected, paidAmountUsd:Math.max(0,num(mismatch.amount_usd)) });
      } catch {}
      continue;
    }
    const paid = Math.max(0, num(event.amount_usd));
    const now = new Date().toISOString();
    await env.DB.prepare("UPDATE lumen_referral_commissions SET status='SETTLED',settlement_event_id=?,settled_amount_usd=?,updated_at=?,engine_version=? WHERE referral_id=?")
      .bind(event.id,paid,now,VERSION,row.referral_id).run();
    await env.DB.prepare("UPDATE lumen_referrals SET status='SETTLED',commission_status='SETTLED',settled_revenue_usd=?,settlement_event_id=?,updated_at=? WHERE id=?")
      .bind(paid,event.id,now,row.referral_id).run();
    await logReferralEvent(env, row.referral_id, "COMMISSION_SETTLEMENT_VERIFIED", clean(event.evidence, 1000), paid, true);
    settled.push({ referralId:row.referral_id, commissionId:row.id, revenueEventId:event.id, settledAmountUsd:paid });
  }
  return { ok:true, version:VERSION, settled:settled.length, mismatches:mismatches.length, mismatchResults:mismatches.slice(0,25), results:settled, guardrails:{ verifiedPaymentEventRequired:true, x402SettlementRequired:true, exactAmountRequired:true, underpaymentsNotRecognizedAsFullSettlement:true, overpaymentsNotAutoReconciled:true, autonomousSpend:false } };
}

async function statsData(env) {
  await ensureSchema(env);
  const row = await env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN status='BASIS_REQUIRED' THEN 1 ELSE 0 END) basis_required,SUM(CASE WHEN status='PROPOSAL_READY' THEN 1 ELSE 0 END) proposal_ready,SUM(CASE WHEN status='AGREED_PENDING_CLOSE' THEN 1 ELSE 0 END) agreed,SUM(CASE WHEN status='PAYMENT_DUE' THEN 1 ELSE 0 END) payment_due,SUM(CASE WHEN status='SETTLED' THEN 1 ELSE 0 END) settled,SUM(CASE WHEN status='CLOSED_LOST' THEN 1 ELSE 0 END) closed_lost,COALESCE(SUM(CASE WHEN status='PAYMENT_DUE' THEN agreed_amount_usd ELSE 0 END),0) outstanding,COALESCE(SUM(CASE WHEN status='SETTLED' THEN settled_amount_usd ELSE 0 END),0) realized FROM lumen_referral_commissions").first();
  return { total:Number(row?.total || 0), basisRequired:Number(row?.basis_required || 0), proposalReady:Number(row?.proposal_ready || 0), agreedPendingClose:Number(row?.agreed || 0), paymentDue:Number(row?.payment_due || 0), settled:Number(row?.settled || 0), closedLost:Number(row?.closed_lost || 0), outstandingCommissionUsd:Number(row?.outstanding || 0), realizedCommissionRevenueUsd:Number(row?.realized || 0) };
}

export async function handleReferralCommissionEngine(request, env) {
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/referrals/commissions/policy") return json({ version:VERSION, lifecycle:["PROPOSAL_READY","AGREED_PENDING_CLOSE","PAYMENT_DUE","SETTLED","CLOSED_LOST"], internalSuggestedRatePct:DEFAULT_PROPOSED_RATE_PCT, rule:"commission_is_never_revenue_until_verified_settlement", estimatedValueRequiredForProposal:false, finalDealValueRequiredForPercentageFee:true, percentageFeeUsesFinalDealValue:true, exactAmountCheckout:true, exactAmountSettlement:true, x402Settlement:true, automaticContract:false, automaticSpend:false, explicitCounterpartyAcceptanceRequired:true });
  if (request.method === "GET" && url.pathname === "/referrals/commissions/stats") return json({ version:VERSION, ...await statsData(env) });
  if (request.method === "POST" && url.pathname === "/referrals/commissions/plan") { if (!authorized(request,env)) return json({ok:false,error:"admin_token_required"},403); return json(await planReferralCommissions(env),202); }
  if (request.method === "POST" && url.pathname === "/referrals/commissions/agreement") { if (!authorized(request,env)) return json({ok:false,error:"admin_token_required"},403); const result=await recordCommissionAgreement(env,await bodyJson(request)); return json(result,result.ok?200:409); }
  if (request.method === "POST" && url.pathname === "/referrals/commissions/due") { if (!authorized(request,env)) return json({ok:false,error:"admin_token_required"},403); const result=await markCommissionDue(env,await bodyJson(request)); return json(result,result.ok?200:409); }
  if (request.method === "POST" && url.pathname === "/referrals/commissions/sync") { if (!authorized(request,env)) return json({ok:false,error:"admin_token_required"},403); return json(await syncReferralCommissionSettlements(env),202); }
  return null;
}
