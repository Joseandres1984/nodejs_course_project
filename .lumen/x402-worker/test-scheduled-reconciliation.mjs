import assert from "node:assert/strict";
import worker from "./entry.js";

const rows = [
  {id:"missing-facilitator",request_metadata:JSON.stringify({settlement:{transaction:"0x"+"a".repeat(64)}})},
  {id:"missing-hash",request_metadata:JSON.stringify({settlement:{facilitatorReportedSuccess:true,transaction:"not-a-hash"}})},
  {id:"invalid-json",request_metadata:"{"}
];
const queries=[];
const env={
  LUMEN_RECONCILE_TOKEN:"t".repeat(40),
  DB:{prepare(sql){queries.push(sql);return {all:async()=>({results:rows})};}}
};
const tasks=[];
await worker.scheduled({cron:"*/15 * * * *"},env,{waitUntil:p=>tasks.push(p)});
assert.equal(tasks.length,1);
await Promise.all(tasks);
assert.equal(queries.length,1);
assert.match(queries[0],/status='awaiting_independent_verification'/);
assert.match(queries[0],/LIMIT 10/);
assert.ok(!queries.some(q=>/UPDATE|INSERT|DELETE/.test(q)));
const noDb=[];
await worker.scheduled({}, {LUMEN_RECONCILE_TOKEN:"t".repeat(40)}, {waitUntil:p=>noDb.push(p)});
await Promise.all(noDb);
console.log("X402_SCHEDULED_RECONCILIATION_FAIL_CLOSED_OK");
