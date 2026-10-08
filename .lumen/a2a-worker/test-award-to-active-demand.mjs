import assert from "node:assert/strict";
import {DatabaseSync} from "node:sqlite";
import {__test,handleSourceIntelligence} from "./source-intelligence.js";

const future="2099-10-20T12:00:00Z",past="2020-10-20T12:00:00Z";
const award=(name,title,domain,id)=>({
 supplier_name:name,supplier_domain:domain,supplier_website:"https://"+domain+"/",
 award_title:title,evidence_url:"https://ted.europa.eu/en/notice/-/detail/"+id
});
const tender=(id,title,deadline=future,source="ted_eu_public_procurement",contact=false)=>({
 id,source,name:title,raw_json:JSON.stringify({deadline,buyer:"Official buyer",
 buyerEmail:contact?"bids@authority.example":null,buyerWebsite:contact?"https://authority.example":null}),
 evidence:"https://ted.europa.eu/en/notice/-/detail/2026-"+id
});
const cleaning=award("Facilities Ltd","Czechia – Cleaning services – office corridor sanitation","cleaners.example","award-clean");
const travel=award("Travel Agency Ltd","Czechia – Travel agency and similar services – ministry travel","travel.example","award-travel");
const cleanOpen=tender("open-clean","Germany – Cleaning services – municipal building interior",future,"ted_eu_public_procurement",true);
const travelOpen=tender("open-travel","Poland – Travel agency and similar services – public-sector airline booking");
const expired=tender("closed-clean","Austria – Cleaning services – expired",past);
const unrelated=tender("open-software","Romania – Software development services – hosting support");
const nondeadline=tender("no-deadline","Germany – Cleaning services – without a bid deadline","");
const securityAward=award("Physical Guards Ltd","Netherlands – Security services – physical guarding","guards.example","award-security");
const cyberTender=tender("cyber","Denmark – Cyber security services – software analysis");
const trueMatch=__test.officialTenderAwardFit(cleaning,cleanOpen);
assert.ok(trueMatch);
assert.equal(trueMatch.evidenceTier,"CATEGORY_EVIDENCE");
assert.equal(trueMatch.verifiedBuyerDomainContact,true);
assert.equal(trueMatch.outreachPermitted,false);
assert.equal(trueMatch.commercialInterestVerified,false);
assert.equal(trueMatch.requiresHumanReview,true);
assert.equal(__test.officialTenderAwardFit(travel,travelOpen)?.evidenceTier,"CATEGORY_EVIDENCE");
assert.equal(__test.officialTenderAwardFit(cleaning,expired),null);
assert.equal(__test.officialTenderAwardFit(cleaning,unrelated),null);
assert.equal(__test.officialTenderAwardFit(cleaning,nondeadline),null);
assert.equal(__test.officialTenderAwardFit(securityAward,cyberTender),null,"security-only similarities are not proven matches");
const soilCleaning=award("Soil Treatment Company","Netherlands – Cleaning and treatment of soil – industrial remediation","soil.example","award-soil");
const sewageCleaning=award("Water Utility Ltd","Slovenia – Sewage, refuse, cleaning and environmental services – wastewater","water.example","award-sewage");
const buildingCleaning=tender("berlin-cleaning","Germany – Building-cleaning services – public building interiors");
const busTransport=tender("bus-transport","Finland – Public road transport services – scheduled bus operations");
assert.equal(__test.officialTenderAwardFit(cleaning,buildingCleaning)?.evidenceTier,"CATEGORY_EVIDENCE","equivalent building cleaning and general cleaning categories need manual shortlist");
assert.equal(__test.officialTenderAwardFit(soilCleaning,buildingCleaning),null,"soil remediation is not building cleaning");
assert.equal(__test.officialTenderAwardFit(sewageCleaning,buildingCleaning),null,"sewage sanitation is not building cleaning");
assert.equal(__test.officialTenderAwardFit(travel,busTransport),null,"travel agency is not road passenger transport");

assert.equal(__test.officialTenderAwardFit({...cleaning,supplier_website:"http://unsafe.example/"},cleanOpen),null);

const sqlite=new DatabaseSync(":memory:");
const DB={
 prepare(sql){let stmt,args=[];return {
   bind(...values){args=values;return this},
   async run(){stmt ||= sqlite.prepare(sql);const x=stmt.run(...args);return{meta:{changes:Number(x.changes)}}},
   async first(){stmt ||= sqlite.prepare(sql);return stmt.get(...args)||null},
   async all(){stmt ||= sqlite.prepare(sql);return{results:stmt.all(...args)}}
 }},
 async batch(queries){const out=[];for(const q of queries)out.push(await q.run());return out}
};
const env={DB,OPPORTUNITY_ADMIN_TOKEN:"test-secret"};
sqlite.exec(`CREATE TABLE lumen_opportunities(
 id TEXT PRIMARY KEY,source TEXT,remote_id TEXT,name TEXT,raw_json TEXT,evidence TEXT,demand_signal INTEGER,updated_at TEXT)`);
// Pure research matches: no external network calls, no outreach draft table,
// and no payments table in the test database.
const unauth=await handleSourceIntelligence(new Request("https://worker.example/source-intelligence/award-demand-matches"),env);
assert.equal(unauth.status,403);
const auth={headers:{"x-lumen-admin":"test-secret"}};
const empty=await(await handleSourceIntelligence(new Request("https://worker.example/source-intelligence/award-demand-matches",auth),env)).json();
assert.equal(empty.candidatesForHumanReview,0);

const now=new Date().toISOString();
for(const a of [cleaning,travel,securityAward]){
 sqlite.prepare("INSERT INTO lumen_official_award_suppliers(award_notice_id,supplier_name,supplier_website,supplier_domain,supplier_email,domain_verified,award_title,evidence_url,first_seen_at,last_seen_at) VALUES(?,?,?,?,?,?,?,?,?,?)")
 .run(a.evidence_url.split("/").at(-1),a.supplier_name,a.supplier_website,a.supplier_domain,null,0,a.award_title,a.evidence_url,now,now);
}
for(const t of [cleanOpen,travelOpen,expired,unrelated,nondeadline,cyberTender]){
 sqlite.prepare("INSERT INTO lumen_opportunities VALUES(?,?,?,?,?,?,?,?)").run(t.id,t.source,t.id,t.name,t.raw_json,t.evidence,1,now);
}
const response=await handleSourceIntelligence(new Request("https://worker.example/source-intelligence/award-demand-matches?limit=3",auth),env);
assert.equal(response.status,200);
const data=await response.json();
assert.equal(data.ok,true);
assert.equal(data.candidatesForHumanReview,2,JSON.stringify(data));
assert.equal(data.strongerCategoryEvidence,2);
assert.equal(data.weakerCategoryOverlap,0);
assert.equal(data.candidates.length,2);
assert.ok(data.candidates.every(c=>c.outreachPermitted===false));
assert.equal(data.policy.createsExternalMessages,false);
assert.equal(data.policy.procurementDemandIsNotLumenServiceDemand,true);
console.log("AWARD_TO_ACTIVE_DEMAND_OK: 2 verified category evidence pairings; expired/unknown/non-matching demand excluded; protected read-only; no outreach or payments");
sqlite.close();
