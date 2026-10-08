import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import { __test, handleSourceIntelligence } from "./source-intelligence.js";

const release={
  ocid:"ocds-test-uk-01",
  tender:{title:"UK electrical cables RFQ",description:"Electrical cables for maintenance",tenderPeriod:{endDate:"2099-10-01T12:00:00Z"}},
  buyer:{id:"public-buyer-1",name:"Verified Council Buyer"},
  parties:[{id:"public-buyer-1",name:"Verified Council Buyer",roles:["buyer"],
    contactPoint:{name:"Purchasing office",email:"procurement@council.example",url:"https://council.example/procurement"},
    address:{countryName:"GB"}}],
  uri:"https://www.contractsfinder.service.gov.uk/notice/123"
};
const buyer=__test.normalizeUkRelease(release);
assert.equal(buyer.demandSignal,1,"UK procurement must retain SQL numeric buying evidence");
assert.equal(buyer.endpoint,null,"public notice URL is not A2A");
assert.equal(buyer.raw.buyerEmail,"procurement@council.example");
assert.equal(buyer.raw.buyerWebsite,"https://council.example/procurement");
assert.equal(buyer.raw.contactSource,"official_uk_contracts_finder");

const award={
  "publication-number":"666555-2026",
  "notice-title":"Award: industrial control valves and instrumentation",
  "winner-name":["Industrial Valves Ltd"],
  "winner-internet-address":["https://industrialvalves.example/"],
  "winner-touchpoint-email":["bids@industrialvalves.example"]
};
const valid=__test.normalizeTedAward(award);
assert.equal(valid.supplierName,"Industrial Valves Ltd");
assert.equal(valid.supplierDomain,"industrialvalves.example");
assert.equal(valid.emailDomainVerified,true);
assert.equal(valid.supplierEmail,"bids@industrialvalves.example");
assert.match(valid.evidenceUrl,/ted.europa.eu\/en\/notice/);
assert.equal(__test.normalizeTedAward({...award,"winner-name":["Vendor A","Vendor B"]}),null,"multiple winners need association");
assert.equal(__test.normalizeTedAward({...award,"winner-internet-address":["http://unsafe.example"]}),null,"non HTTPS website");
const mismatched=__test.normalizeTedAward({...award,"winner-touchpoint-email":["bids@unrelated.example"]});
assert.equal(mismatched.supplierEmail,null);
assert.equal(mismatched.emailDomainVerified,false);
assert.equal(__test.normalizeTedAward({...award,"winner-touchpoint-email":["person@gmail.com"]}).emailDomainVerified,false);
assert.equal(__test.domainMatches("procurement.council.example","council.example"),true);

const sqlite=new DatabaseSync(":memory:");
const adapter={
  prepare(sql){
    let stmt,args=[];
    return {
      bind(...v){args=v;return this},
      async run(){stmt ||= sqlite.prepare(sql);const z=stmt.run(...args);return{meta:{changes:Number(z.changes)}}},
      async first(){stmt ||= sqlite.prepare(sql);return stmt.get(...args)||null},
      async all(){stmt ||= sqlite.prepare(sql);return{results:stmt.all(...args)}}
    };
  },
  async batch(stmts){const results=[];for(const q of stmts)results.push(await q.run());return results}
};
const env={DB:adapter,OPPORTUNITY_ADMIN_TOKEN:"test-admin-key"};
const originalFetch=globalThis.fetch;let queries=0;
globalThis.fetch=async (_url,opts)=>{
  queries++;
  assert.equal(opts.method,"POST");
  const payload=JSON.parse(opts.body);
  assert.ok(payload.fields.includes("winner-name"));
  if(payload.page===1) return Response.json({notices:[award,...Array.from({length:79},(_,i)=>({"publication-number":"generic-"+i}))]});
  if(payload.page===2) return Response.json({notices:[{...award,"publication-number":"666557-2026","winner-name":["Second Valve Supplier"],"winner-internet-address":["https://secondvalves.example"],"winner-touchpoint-email":["bids@secondvalves.example"]},...Array.from({length:79},(_,i)=>({"publication-number":"generic-b-"+i}))]});
  return Response.json({notices:[{...award,"publication-number":"666556-2026","winner-name":["Company Without Site"],"winner-internet-address":[]}]});
};
try{
  const request=()=>new Request("https://worker.example/source-intelligence/supplier-refresh",{method:"POST",headers:{"x-lumen-admin":"test-admin-key"}});
  const first=await (await handleSourceIntelligence(request(),env)).json();
  assert.equal(first.ok,true,JSON.stringify(first));
  assert.equal(first.newAwards,2);
  assert.equal(first.pagesFetched,3);
  assert.equal(first.scannedNotices,161);
  assert.equal(first.verifiedEmailDomains,2);
  const repeat=await (await handleSourceIntelligence(request(),env)).json();
  assert.equal(repeat.skipped,true,"six-hour cooldown avoids repeat API calls");
  assert.equal(queries,3);
  const inventory=await (await handleSourceIntelligence(new Request("https://worker.example/source-intelligence/suppliers?limit=5",{headers:{"x-lumen-admin":"test-admin-key"}}),env)).json();
  assert.equal(inventory.distinctSupplierDomains,2);
  assert.equal(inventory.candidates[0].requiresHumanApproval,true);
  assert.equal(inventory.candidates[0].commercialInterestVerified,false);
  const anonymous=await handleSourceIntelligence(new Request("https://worker.example/source-intelligence/suppliers"),env);
  assert.equal(anonymous.status,403);
  console.log("OFFICIAL_PROCUREMENT_NETWORK_OK: UK public buyer contact recovered; one official award supplier inventoried; mismatched/freemail rejected; approval protected; zero outbound sends");
} finally{
  globalThis.fetch=originalFetch;
  sqlite.close();
}
