import assert from "node:assert/strict";
import {DatabaseSync} from "node:sqlite";
const db=new DatabaseSync(":memory:");
db.exec("CREATE TABLE receipts(id TEXT PRIMARY KEY,status TEXT NOT NULL,pay_to TEXT NOT NULL,amount_usd REAL NOT NULL,request_metadata TEXT); CREATE TABLE claims(transfer_key TEXT PRIMARY KEY,receipt_id TEXT NOT NULL UNIQUE,verified_at TEXT NOT NULL)");
const claim=db.prepare("INSERT INTO claims(transfer_key,receipt_id,verified_at) SELECT ?,id,? FROM receipts WHERE id=? AND status='awaiting_independent_verification' AND lower(pay_to)=? AND amount_usd=?");
const settle=db.prepare("UPDATE receipts SET status='settled_verified',request_metadata=? WHERE id=? AND status='awaiting_independent_verification' AND lower(pay_to)=? AND amount_usd=? AND EXISTS(SELECT 1 FROM claims WHERE transfer_key=? AND receipt_id=?)");
const payTo="0x"+"a".repeat(40);
function insert(id,status="awaiting_independent_verification",amount=5){db.prepare("INSERT INTO receipts(id,status,pay_to,amount_usd) VALUES(?,?,?,?)").run(id,status,payTo,amount)}
function reconcile(id,key,amount=5){try{db.exec("BEGIN");const a=claim.run(key,"now",id,payTo,amount);const b=settle.run('{"settlement":{"independentlyVerified":true}}',id,payTo,amount,key,id);if(a.changes!==1||b.changes!==1){db.exec("ROLLBACK");return false}db.exec("COMMIT");return true}catch{db.exec("ROLLBACK");return false}}
insert("r1");insert("r2");insert("already","settled_verified");
assert.equal(reconcile("already","tx:1"),false);
assert.equal(reconcile("r1","tx:1",7),false);
assert.equal(reconcile("r1","tx:1"),true);
assert.equal(reconcile("r1","tx:2"),false);
assert.equal(reconcile("r2","tx:1"),false);
assert.equal(reconcile("r2","tx:2"),true);
assert.equal(db.prepare("SELECT COUNT(*) AS n FROM claims").get().n,2);
assert.equal(db.prepare("SELECT COUNT(*) AS n FROM receipts WHERE status='settled_verified'").get().n,3);
insert("r3");
db.exec("CREATE TRIGGER fail_settlement BEFORE UPDATE ON receipts WHEN NEW.id='r3' BEGIN SELECT RAISE(ABORT,'injected failure'); END");
assert.equal(reconcile("r3","tx:3"),false);
assert.equal(db.prepare("SELECT COUNT(*) AS n FROM claims WHERE transfer_key='tx:3'").get().n,0,"claim rolled back with failed settlement");
assert.equal(db.prepare("SELECT status FROM receipts WHERE id='r3'").get().status,"awaiting_independent_verification");
db.close();console.log("RECONCILIATION_ATOMICITY_TESTS_OK");
