import test from "node:test";
import assert from "node:assert/strict";
import app from "../src/worker.mjs";
import { validateLead, qualifyLead } from "../src/qualification.mjs";

const sample = { name: "María López", email: "maria@example.com", area: "Zárate",
  budget: 600000, operation: "alquilar", propertyType: "departamento",
  timeframe: "urgente", consent: true, website: "" };
const request = (path, method = "GET", body, headers = {}) =>
  new Request("https://demo.example" + path, { method, headers, ...(body !== undefined ? { body: JSON.stringify(body) } : {}) });
class FakeD1 {
  constructor() { this.leads = []; this.hits = 0; this.notice = "not_configured"; }
  prepare(sql) {
    const db = this;
    return { bind(...args) {
      return {
        async run() {
          if (sql.startsWith("INSERT INTO rate_limit")) db.hits++;
          if (sql.startsWith("INSERT INTO leads")) db.leads.push({
            id: args[0], created_at: args[1], name: args[2], email: args[3], area: args[4],
            budget_ars: args[5], operation: args[6], property_type: args[7], timeframe: args[8],
            priority: args[9], notification_status: "not_configured"
          });
          if (sql.startsWith("UPDATE leads")) db.notice = args[0];
          if (sql.startsWith("DELETE FROM leads WHERE id")) db.leads = db.leads.filter(l => l.id !== args[0]);
          return { success: true };
        },
        async first() { return { hits: db.hits }; },
        async all() { return { results: db.leads }; }
      };
    }};
  }
}
const liveEnv = () => ({ SUBMISSIONS_ENABLED: "true", PRIVACY_EMAIL: "privacy@example.com",
  LEADFLOW_ADMIN_TOKEN: "A".repeat(40), LEADFLOW_RATE_SALT: "B".repeat(40),
  LEADFLOW_DB: new FakeD1() });
test("homepage contains form and explicit demo notice", async () => {
 const res = await app.fetch(request("/"), {});
 assert.equal(res.status, 200);
 assert.match(await res.text(), /Simular con datos ficticios/);
 assert.match(res.headers.get("content-security-policy"), /script-src 'self'/);
});
test("demo never saves leads without configuration", async () => {
 const r = await app.fetch(request("/api/status"), {});
 assert.equal((await r.json()).submissionsEnabled, false);
 const post = await app.fetch(request("/api/leads", "POST", sample, {"content-type":"application/json"}), {});
 assert.equal(post.status, 503);
});
test("health endpoint works and has no customer data", async () => {
 const res = await app.fetch(request("/health"), {});
 assert.deepEqual(await res.json(), { ok:true, service:"lumen-leadflow" });
});
test("qualification is deterministic and does not imply inventory", () => {
 assert.equal(qualifyLead(sample).priority, "alta");
 assert.equal(qualifyLead({...sample,timeframe:"explorando"}).priority, "exploratoria");
 assert.match(qualifyLead(sample).warning, /no confirma disponibilidad/);
});
test("rejects missing consent and invalid email", () => {
 assert.match(validateLead({...sample, consent:false}).error, /consentimiento/);
 assert.match(validateLead({...sample, email:"bad"}).error, /correo/);
});
test("records a consented lead and keeps it behind admin auth", async () => {
 const env = liveEnv();
 const post = await app.fetch(request("/api/leads", "POST", sample, {"content-type":"application/json"}), env);
 assert.equal(post.status, 201);
 const record = await post.json();
 assert.equal(record.saved, true);
 assert.equal(record.notification, "not_configured");
 assert.equal(env.LEADFLOW_DB.leads.length, 1);
 const denied = await app.fetch(request("/api/admin/leads"), env);
 assert.equal(denied.status, 401);
 const allowed = await app.fetch(request("/api/admin/leads", "GET", undefined,
   {authorization:"Bearer "+env.LEADFLOW_ADMIN_TOKEN}), env);
 assert.equal((await allowed.json()).leads.length, 1);
});
test("wrong origin is blocked and honeypot is ignored", async () => {
 const env = liveEnv();
 const foreign = await app.fetch(request("/api/leads", "POST", sample,
   {"content-type":"application/json",origin:"https://other.example"}), env);
 assert.equal(foreign.status, 403);
 const trap = await app.fetch(request("/api/leads", "POST", {...sample,website:"spam"},
   {"content-type":"application/json"}), env);
 assert.equal(trap.status, 202);
 assert.equal(env.LEADFLOW_DB.leads.length, 0);
});
test("rate limiter blocks the 11th request per hour", async () => {
 const env = liveEnv();
 for (let i=0;i<10;i++) assert.equal((await app.fetch(request("/api/leads", "POST", sample,
   {"content-type":"application/json"}), env)).status, 201);
 assert.equal((await app.fetch(request("/api/leads", "POST", sample,
   {"content-type":"application/json"}), env)).status, 429);
 assert.equal(env.LEADFLOW_DB.leads.length, 10);
});
test("admin can delete one lead with authorization", async () => {
 const env=liveEnv();
 const made=await app.fetch(request("/api/leads","POST",sample,{"content-type":"application/json"}),env);
 const {id}=await made.json();
 const deleted=await app.fetch(request("/api/admin/leads/"+id,"DELETE",undefined,
   {authorization:"Bearer "+env.LEADFLOW_ADMIN_TOKEN}),env);
 assert.equal(deleted.status,200);
 assert.equal(env.LEADFLOW_DB.leads.length,0);
});
