import assert from "node:assert/strict";
import {
  APPROVAL_POLICY, plausibleX402Signature, sameApprovalScope, approvalMaySettle,
  preflightX402Settlement, finalizeX402Settlement, handleApprovalManagement
} from "./settlement-approval.js";

// No live blockchain signatures, transfers or facilitator calls: a D1 stub
// verifies the full server-side authorization state machine.
class D1 {
  constructor() { this.tickets=new Map();this.byFingerprint=new Map();this.commissions=new Map(); }
  prepare(sql) {
    const db=this;
    return {
      bind(...args){this.args=args;return this;},
      async run(){
        const a=this.args||[];
        if(sql.startsWith("CREATE "))return {meta:{changes:0}};
        if(sql.includes("INSERT OR IGNORE INTO lumen_x402_human_approvals")){
          const [id,created,updated,path,product,amount,network,payTo,fingerprint,expires]=a;
          if(db.byFingerprint.has(fingerprint))return {meta:{changes:0}};
          db.tickets.set(id,{id,created_at:created,updated_at:updated,status:"PENDING",request_path:path,product_name:product,amount_usd:amount,network,pay_to:payTo,request_fingerprint:fingerprint,expires_at:expires,approved_at:null,consumed_at:null});
          db.byFingerprint.set(fingerprint,id);
          return {meta:{changes:1}};
        }
        if(sql.includes("SET status='IN_FLIGHT'")){
          const [consumed,updated,fingerprint,id,now]=a;
          const r=db.tickets.get(id);
          if(!r||r.status!=="APPROVED"||r.expires_at<=now)return {meta:{changes:0}};
          const other=db.byFingerprint.get(fingerprint);
          if(other&&other!==id)throw Error("unique_fingerprint");
          db.byFingerprint.delete(r.request_fingerprint);
          db.byFingerprint.set(fingerprint,id);
          Object.assign(r,{status:"IN_FLIGHT",consumed_at:consumed,updated_at:updated,request_fingerprint:fingerprint});
          return {meta:{changes:1}};
        }
        if(sql.includes("status=?,approved_at=?,expires_at=?")){
          const [status,approved,expires,updated,id,now]=a;const r=db.tickets.get(id);
          if(!r||r.status!=="PENDING"||r.expires_at<=now)return {meta:{changes:0}};
          Object.assign(r,{status,approved_at:approved,expires_at:expires,updated_at:updated});
          return {meta:{changes:1}};
        }
        if(sql.includes("settlement_transaction=?")){
          const [status,tx,failure,updated,id]=a;const r=db.tickets.get(id);
          if(!r||r.status!=="IN_FLIGHT")return {meta:{changes:0}};
          Object.assign(r,{status,settlement_transaction:tx,failure_code:failure,updated_at:updated});
          return {meta:{changes:1}};
        }
        throw Error("unhandled D1 run SQL "+sql);
      },
      async first(){
        const a=this.args||[];
        if(sql.includes("COUNT(*) AS n FROM lumen_x402_human_approvals"))return {n:db.tickets.size};
        if(sql.includes("FROM lumen_referral_commissions"))return db.commissions.get(a[0])||null;
        if(sql.includes("WHERE request_fingerprint=?"))return db.tickets.get(db.byFingerprint.get(a[0]))||null;
        if(sql.includes("FROM lumen_x402_human_approvals WHERE id=?"))return db.tickets.get(a[0])||null;
        throw Error("unhandled D1 first SQL "+sql);
      },
      async all(){
        if(sql.includes("FROM lumen_x402_human_approvals WHERE status='PENDING'"))return {results:[...db.tickets.values()].filter(x=>x.status==="PENDING"&&x.expires_at>(this.args||[])[0])};
        throw Error("unhandled D1 all SQL "+sql);
      }
    };
  }
}
const secret="manual-approval-only-aaaaaaaaaaaaaaaaaaaa";
const db=new D1(),env={DB:db,X402_HUMAN_APPROVAL_TOKEN:secret,X402_PAY_TO:"0x04285DE6A083CEb28fb0C254a2ed0F5fdB2eeD28",X402_NETWORK:"eip155:8453"};
const p={ "supplier-snapshot":{name:"Supplier Snapshot",price_usd:1}, "tender-hot-lead":{name:"Tender Hot Lead",price_usd:1}};
const base="https://seller.example.test";
const signature=(s)=>Buffer.from(JSON.stringify({x402Version:2,payload:{signature:s,authorization:{from:"0xtest"}}})).toString("base64");
const req=(path,s,approvalId)=>new Request(base+path,{headers:{...(s?{"payment-signature":s}:{}),...(approvalId?{"x-lumen-approval-id":approvalId}:{})}});
const owner=(path,method="GET",token=secret)=>new Request(base+path,{method,headers:{"x-lumen-approval-token":token}});
async function checkResponse(resp,code){
  assert.equal(resp.status,code);
  return resp.json();
}
assert.equal(APPROVAL_POLICY.defaultDeny,true);
assert.equal(APPROVAL_POLICY.oneTime,true);
assert.equal(APPROVAL_POLICY.automaticApproval,false);
assert.equal(plausibleX402Signature("garbage"),false);
assert.equal(plausibleX402Signature(signature("abc")),true);

let start=await preflightX402Settlement(req("/buy/supplier-snapshot"),env,p);
assert.equal(start.response,null,"unsigned request must continue to official 402");
let invalid=await preflightX402Settlement(req("/buy/supplier-snapshot","not_x402_signature"),env,p);
await checkResponse(invalid.response,400);

const signed=signature("first-buyer");
let pending=await preflightX402Settlement(req("/buy/supplier-snapshot",signed),env,p);
let body=await checkResponse(pending.response,409);
assert.equal(body.error,"awaiting_owner_approval");
assert.equal(body.ownerApprovalRequired,true);
assert.equal(db.tickets.size,1);
const ticket=body.approvalRequestId;
assert.equal(db.tickets.get(ticket).status,"PENDING");

let repeat=await preflightX402Settlement(req("/buy/supplier-snapshot",signed),env,p);
assert.equal((await repeat.response.json()).approvalRequestId,ticket,"idempotent registration");
assert.equal(db.tickets.size,1);
let attemptBeforeOwner=await preflightX402Settlement(req("/buy/supplier-snapshot",signature("fresh"),ticket),env,p);
await checkResponse(attemptBeforeOwner.response,409);
assert.equal(db.tickets.get(ticket).status,"PENDING");

const wrong=await handleApprovalManagement(owner("/approvals/"+ticket+"/approve","POST","wrong"),env);
await checkResponse(wrong,403);
assert.equal(db.tickets.get(ticket).status,"PENDING");
const missing=await handleApprovalManagement(owner("/approvals/"+ticket+"/approve","POST",""),{DB:db});
await checkResponse(missing,403);
assert.equal(db.tickets.get(ticket).status,"PENDING");
const listed=await checkResponse(await handleApprovalManagement(owner("/approvals/pending"),env),200);
assert.equal(listed.pending.length,1);
assert.equal(listed.pending[0].amountUsd,1);

let result=await checkResponse(await handleApprovalManagement(owner("/approvals/"+ticket+"/approve","POST"),env),200);
assert.equal(result.ownerAction,"APPROVED_ONCE");
assert.equal(result.settlementExecuted,false);
await checkResponse(await handleApprovalManagement(owner("/approvals/"+ticket+"/approve","POST"),env),409);

const scope={path:"/buy/supplier-snapshot",amountUsd:1,network:"eip155:8453",payTo:env.X402_PAY_TO};
assert.equal(approvalMaySettle(db.tickets.get(ticket),scope),true);
assert.equal(sameApprovalScope(db.tickets.get(ticket),{...scope,amountUsd:7}),false);
const wrongPath=await preflightX402Settlement(req("/buy/tender-hot-lead",signature("other-product"),ticket),env,p);
await checkResponse(wrongPath.response,409);
assert.equal(db.tickets.get(ticket).status,"APPROVED","scope mismatch never consumes approval");

const claimed=await preflightX402Settlement(req("/buy/supplier-snapshot",signature("fresh-after-owner"),ticket),env,p);
assert.equal(claimed.response,null);
assert.equal(claimed.claimedId,ticket);
assert.equal(db.tickets.get(ticket).status,"IN_FLIGHT");
const replay=await preflightX402Settlement(req("/buy/supplier-snapshot",signature("replay"),ticket),env,p);
await checkResponse(replay.response,409);
await finalizeX402Settlement(env,ticket,new Response("payment rejected",{status:402}));
assert.equal(db.tickets.get(ticket).status,"REVIEW_REQUIRED");
const postFailure=await preflightX402Settlement(req("/buy/supplier-snapshot",signature("replay"),ticket),env,p);
await checkResponse(postFailure.response,409);

// Independently approved second request can become SETTLED exactly once.
const p2=await preflightX402Settlement(req("/buy/tender-hot-lead",signature("buyer2")),env,p);
const t2=(await p2.response.json()).approvalRequestId;
await checkResponse(await handleApprovalManagement(owner("/approvals/"+t2+"/approve","POST"),env),200);
const a2=await preflightX402Settlement(req("/buy/tender-hot-lead",signature("buyer2"),t2),env,p);
assert.equal(a2.claimedId,t2);
const paymentResponse=Buffer.from(JSON.stringify({success:true,transaction:"0xverified"})).toString("base64");
await finalizeX402Settlement(env,t2,new Response("ok",{status:200,headers:{"payment-response":paymentResponse}}));
assert.equal(db.tickets.get(t2).status,"SETTLED");
assert.equal(db.tickets.get(t2).settlement_transaction,"0xverified");
await checkResponse((await preflightX402Settlement(req("/buy/tender-hot-lead",signature("buyer2"),t2),env,p)).response,409);

// Separate commission checkout is covered by identical owner approval.
db.commissions.set("REF-1",{status:"PAYMENT_DUE",agreed_amount_usd:14});
const commission=await preflightX402Settlement(req("/commission/REF-1",signature("commission")),env,p);
const cId=(await commission.response.json()).approvalRequestId;
const cRow=db.tickets.get(cId);
assert.equal(cRow.amount_usd,14);
assert.equal(cRow.request_path,"/commission/REF-1");
await checkResponse(await handleApprovalManagement(owner("/approvals/"+cId+"/reject","POST"),env),200);
await checkResponse((await preflightX402Settlement(req("/commission/REF-1",signature("commission"),cId),env,p)).response,409);
assert.equal(db.tickets.get(cId).status,"REJECTED");

console.log("X402_HUMAN_APPROVAL_FAIL_CLOSED_ONE_SHOT_AND_COMMISSION_OK");
