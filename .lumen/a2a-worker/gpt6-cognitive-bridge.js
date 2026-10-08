// Optional OpenAI Responses adapter for LUMEN's economic brain.
// No AI spend or external disclosure unless both opt-in switches and a capped budget are present.
export const GPT6_BRIDGE_POLICY=Object.freeze({
  version:"1.0-explicit-opt-in",
  strategyModel:"gpt-6.1-sol",
  triageModel:"gpt-6-luna",
  api:"responses",
  enabledByDefault:false,
  approvedApiSpendByDefault:false,
  maxRequestInputChars:16000,
  maxOutputTokens:2400,
  maxReservedUsdPerCall:0.15,
  maxConfiguredMonthlyCapUsd:10,
  sendsMessages:false,
  purchases:false,
  modifiesPrices:false,
  approvesContracts:false,
  verifiedRevenueOnly:true,
  bindingActionsHumanGated:true
});
function enabled(env){
  return env?.LUMEN_GPT6_ENABLE==="true" &&
    env?.LUMEN_GPT6_SPEND_APPROVED==="true" &&
    Boolean(env?.OPENAI_API_KEY) &&
    Number(env?.LUMEN_GPT6_MONTHLY_CAP_USD)>0 &&
    Number(env?.LUMEN_GPT6_MONTHLY_CAP_USD)<=GPT6_BRIDGE_POLICY.maxConfiguredMonthlyCapUsd;
}
export function getGpt6BridgeStatus(env={}){
  return {
    ...GPT6_BRIDGE_POLICY,
    configured:Boolean(env?.OPENAI_API_KEY),
    enabled:enabled(env),
    monthlyCapUsd:enabled(env)?Number(env.LUMEN_GPT6_MONTHLY_CAP_USD):0
  };
}
async function reserveCall(env){
  if(!env.DB) throw Error("gpt6_budget_db_required");
  const now=new Date().toISOString(),period=now.slice(0,7);
  const capCents=Math.floor(Number(env.LUMEN_GPT6_MONTHLY_CAP_USD)*100);
  const reserveCents=15;
  if(capCents<reserveCents)throw Error("gpt6_budget_below_minimum_reservation");
  await env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_gpt6_api_reservations (period TEXT PRIMARY KEY,reserved_cents INTEGER NOT NULL DEFAULT 0,calls INTEGER NOT NULL DEFAULT 0,updated_at TEXT NOT NULL)").run();
  await env.DB.prepare("INSERT OR IGNORE INTO lumen_gpt6_api_reservations(period,updated_at) VALUES(?,?)").bind(period,now).run();
  const result=await env.DB.prepare("UPDATE lumen_gpt6_api_reservations SET reserved_cents=reserved_cents+?,calls=calls+1,updated_at=? WHERE period=? AND reserved_cents+?<=?").bind(reserveCents,now,period,reserveCents,capCents).run();
  if(Number(result?.meta?.changes)!==1)throw Error("gpt6_monthly_approved_cap_exhausted");
}
function outputText(payload){
  if(typeof payload?.output_text==="string")return payload.output_text;
  return (payload?.output||[]).flatMap(item=>(item?.content||[])
    .filter(part=>part?.type==="output_text"&&typeof part?.text==="string")
    .map(part=>part.text)).join("\n");
}
export async function invokeGpt6(env,{role="strategy",instructions="",input=""}={}){
  if(!enabled(env))return null;
  if(!["strategy","triage"].includes(role))throw Error("gpt6_unsupported_role");
  const prompt=String(instructions).slice(0,5000);
  const data=String(input).slice(0,11000);
  if(!prompt||!data)throw Error("gpt6_missing_input");
  await reserveCall(env);
  const model=role==="triage"?GPT6_BRIDGE_POLICY.triageModel:GPT6_BRIDGE_POLICY.strategyModel;
  const body={
    model,
    instructions:prompt,
    input:data,
    reasoning:{effort:role==="triage"?"low":"medium"},
    max_output_tokens:GPT6_BRIDGE_POLICY.maxOutputTokens,
    store:false,
    tools:[]
  };
  const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),20000);
  try{
    const response=await fetch("https://api.openai.com/v1/responses",{
      method:"POST",
      headers:{"authorization":`Bearer ${env.OPENAI_API_KEY}`,"content-type":"application/json"},
      body:JSON.stringify(body),
      signal:controller.signal
    });
    if(!response.ok)throw Error(`gpt6_response_http_${response.status}`);
    const answer=await response.json();
    const text=outputText(answer);
    if(!text)throw Error("gpt6_empty_output");
    return {response:text,model,provider:"openai",approvedCapped:true};
  } finally {clearTimeout(timeout);}
}
