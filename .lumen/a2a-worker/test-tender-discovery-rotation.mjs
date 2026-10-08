import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import { __test } from "./tender-supplier-match.js";

function dbAdapter(sqlite) {
  return {
    prepare(sql) {
      let stmt = null, args = [];
      return {
        bind(...values) { args=values; return this; },
        async run() { stmt ||= sqlite.prepare(sql); const result=stmt.run(...args); return {meta:{changes:Number(result.changes)}}; },
        async first() { stmt ||= sqlite.prepare(sql); return stmt.get(...args) || null; },
        async all() { stmt ||= sqlite.prepare(sql); return {results:stmt.all(...args)}; }
      };
    },
    async batch(statements) { const out=[]; for(const stmt of statements) out.push(await stmt.run()); return out; }
  };
}

const sqlite=new DatabaseSync(":memory:");
sqlite.exec(`
  CREATE TABLE lumen_opportunities (
    id TEXT PRIMARY KEY, source TEXT, remote_id TEXT, name TEXT, endpoint TEXT,
    description TEXT,score INTEGER,evidence TEXT,raw_json TEXT,updated_at TEXT
  );
`);
const env={DB:dbAdapter(sqlite)};
await __test.ensureSchema(env);
function tender(id,name,raw,updated="2026-10-08T14:00:00Z"){
  sqlite.prepare("INSERT INTO lumen_opportunities VALUES(?,?,?,?,?,?,?,?,?,?)")
    .run(id,"ted_eu_public_procurement",id,name,null,"Official tender for industrial control valves and software supply.",90,"https://ted.europa.eu/",JSON.stringify({deadline:raw}),updated);
}
tender("already-matched","Software and cybersecurity services","2099-12-31T12:00:00Z","2026-10-08T15:00:00Z");
tender("repeated","Software and security services","2099-12-31T12:00:00Z","2026-10-08T14:40:00Z");
tender("newest-untouched","Industrial control valves","2099-12-31T12:00:00Z","2026-10-08T14:30:00Z");
tender("older-untouched","Battery and electrical cables","2099-12-31T12:00:00Z","2026-10-08T13:30:00Z");
tender("expired","Old software support","2020-01-01T00:00:00Z","2026-10-08T16:00:00Z");
sqlite.prepare("INSERT INTO lumen_opportunities VALUES(?,?,?,?,?,?,?,?,?,?)").run("generic","uk_contracts_finder","generic","General office supply",null,"General administrative provisions",85,"https://example.org","{}","2026-10-08T16:00:00Z");
sqlite.prepare("INSERT INTO lumen_tender_supplier_matches VALUES(?,?,?,?,?,?,?,?,?,?)")
  .run("match1","2026-10-08T12:00:00Z","2026-10-08T12:00:00Z","already-matched","supplier-x","opp-match",82,'["software"]',"CREATED","test");
await __test.recordTenderDiscoveryAttempt(env,"repeated","software supplier vendor manufacturer provider");
await __test.recordTenderDiscoveryAttempt(env,"repeated","software supplier vendor manufacturer provider");

const first=await __test.selectNovelTenders(env);
assert.deepEqual(first.slice(0,4).map(x=>x.id),["newest-untouched","older-untouched","repeated","already-matched"],JSON.stringify(first));
assert.ok(first.every(x=>x.id!=="expired"&&x.id!=="generic"));

await __test.recordTenderDiscoveryAttempt(env,"newest-untouched","valve supplier vendor manufacturer provider");
const second=await __test.selectNovelTenders(env);
assert.deepEqual(second.slice(0,4).map(x=>x.id),["older-untouched","newest-untouched","repeated","already-matched"],JSON.stringify(second));
assert.equal(sqlite.prepare("SELECT probe_count FROM lumen_tender_discovery_coverage WHERE tender_opportunity_id='newest-untouched'").get().probe_count,1);
console.log("TENDER_DISCOVERY_ROTATION_OK: new exact-fit demand rotates ahead of re-probed and already-matched tenders; expired and generic filtered");
sqlite.close();
