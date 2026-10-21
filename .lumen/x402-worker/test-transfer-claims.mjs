// D1's PRIMARY KEY and UNIQUE constraints must arbitrate concurrent claims.
// This harness uses SQLite's real constraint engine (not a hand-written mock).
import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
const db=new DatabaseSync(":memory:");
db.exec("CREATE TABLE verified_transfers (transfer_key TEXT PRIMARY KEY, receipt_id TEXT NOT NULL UNIQUE, verified_at TEXT NOT NULL)");
const insert=db.prepare("INSERT INTO verified_transfers(transfer_key,receipt_id,verified_at) VALUES(?,?,?)");
const claim=async(key,id)=>{await Promise.resolve();try{insert.run(key,id,new Date().toISOString());return true;}catch{return false;}};
const attempts=await Promise.all(Array.from({length:20},(_,i)=>claim("0xabc:1","receipt-"+i)));
assert.equal(attempts.filter(Boolean).length,1,"only one receipt may claim one transfer");
assert.equal(db.prepare("SELECT COUNT(*) AS n FROM verified_transfers").get().n,1);
assert.equal(await claim("0xdef:2","receipt-0"),false,"a receipt cannot claim another transfer");
assert.equal(await claim("0xdef:2","receipt-new"),true,"different receipt and transfer succeeds");
assert.equal(db.prepare("SELECT COUNT(*) AS n FROM verified_transfers").get().n,2);
db.close();
console.log("SQLITE_TRANSFER_UNIQUENESS_TESTS_OK");
