import assert from "node:assert/strict";
import { GPT6_BRIDGE_POLICY, getGpt6BridgeStatus, invokeGpt6 } from "./gpt6-cognitive-bridge.js";

assert.equal(GPT6_BRIDGE_POLICY.strategyModel,"gpt-6.1-sol");
assert.equal(GPT6_BRIDGE_POLICY.triageModel,"gpt-6-luna");
assert.equal(GPT6_BRIDGE_POLICY.enabledByDefault,false);
assert.equal(GPT6_BRIDGE_POLICY.sendsMessages,false);
assert.equal(GPT6_BRIDGE_POLICY.verifiedRevenueOnly,true);
assert.equal(getGpt6BridgeStatus({}).enabled,false);
assert.equal(getGpt6BridgeStatus({OPENAI_API_KEY:"test",LUMEN_GPT6_ENABLE:"true"}).enabled,false);
let fetchCount=0;const originalFetch=globalThis.fetch;
globalThis.fetch=async()=>{fetchCount++;throw Error("unexpected network");};
try{
 assert.equal(await invokeGpt6({OPENAI_API_KEY:"test",LUMEN_GPT6_ENABLE:"true",LUMEN_GPT6_MONTHLY_CAP_USD:"1"},{role:"strategy",instructions:"test",input:"test"}),null);
 assert.equal(fetchCount,0);
} finally {globalThis.fetch=originalFetch;}

let reservations=0,request=null;
const db={
 prepare(sql){
  if(sql.startsWith("CREATE TABLE"))return {run:async()=>({success:true})};
  if(sql.startsWith("INSERT OR IGNORE"))return {bind(){return {run:async()=>({success:true})}}};
  if(sql.startsWith("UPDATE lumen_gpt6_api_reservations"))return {bind(...values){
    assert.equal(values[0],15);
    assert.equal(values[4],100);
    return {run:async()=>{reservations++;return {meta:{changes:1}}}};
  }};
  throw Error("unexpected SQL");
 }
};
const enabled={DB:db,OPENAI_API_KEY:"test-secret",LUMEN_GPT6_ENABLE:"true",LUMEN_GPT6_SPEND_APPROVED:"true",LUMEN_GPT6_MONTHLY_CAP_USD:"1"};
assert.equal(getGpt6BridgeStatus(enabled).enabled,true);
globalThis.fetch=async(_url, options)=>{
 fetchCount++;
 request=JSON.parse(options.body);
 assert.equal(_url,"https://api.openai.com/v1/responses");
 assert.equal(request.store,false);
 assert.deepEqual(request.tools,[]);
 return {ok:true,json:async()=>({output:[{content:[{type:"output_text",text:'{"hypotheses":[]}'}]}]})};
};
try{
 const result=await invokeGpt6(enabled,{role:"strategy",instructions:"Generate safe ideas",input:"No personal details"});
 assert.equal(result.model,"gpt-6.1-sol");
 assert.equal(result.response,'{"hypotheses":[]}');
 assert.equal(request.model,"gpt-6.1-sol");
 const luna=await invokeGpt6(enabled,{role:"triage",instructions:"Classify",input:"public tender"});
 assert.equal(luna.model,"gpt-6-luna");
 assert.equal(reservations,2);
 assert.equal(request.model,"gpt-6-luna");
} finally {globalThis.fetch=originalFetch;}
console.log("GPT6_DEFAULT_OFF_AND_CAPPED_ADAPTER_OK");
