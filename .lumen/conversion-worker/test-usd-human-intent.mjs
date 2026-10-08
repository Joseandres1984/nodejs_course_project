import assert from "node:assert/strict";
import worker from "./worker.js";

const entries = [];
const DB = {
  async batch(statements) {
    assert.ok(statements.length > 0);
    return statements.map(() => ({ success: true }));
  },
  prepare(sql) {
    const entry = { sql, args: [] };
    return {
      bind(...args) { entry.args = args; return this; },
      async run() { entries.push(entry); return { success: true }; },
      async first() { return null; },
      async all() { return { results: [] }; }
    };
  }
};
const env = { DB };
const base = "https://lumen-zero-conversion.lumen-b2b.workers.dev";

const offer = await worker.fetch(new Request(base + "/offer/sourcing-5"), env);
assert.equal(offer.status, 200);
const html = await offer.text();
assert.match(html, /Solicitar pago en USD \(sin compromiso\)/);
assert.match(html, /Pagar con USDC \(x402\)/);
assert.match(html, /no genera una factura automática, un cargo/);
assert.match(html, /USD 15/);

const send = async (next, email) => {
  const body = new URLSearchParams({
    email,
    company: "Sample Buyer Co",
    details: "Necesitamos 100 unidades de válvulas de acero inoxidable, entrega en Madrid.",
    next
  });
  return worker.fetch(new Request(base + "/intent/sourcing-5?src=regression", {
    method: "POST", body
  }), env);
};
const usd = await send("invoice_usd", "usd-buyer@example.org");
assert.equal(usd.status, 200);
const confirmed = await usd.text();
assert.match(confirmed, /Solicitud recibida/);
assert.match(confirmed, /Todavía no se realizó ningún pago/);
const inquiries = entries.filter(x => x.sql.includes("INSERT OR IGNORE INTO lumen_public_inquiries"));
assert.equal(inquiries.length, 1);
assert.equal(inquiries[0].args[3], "usd-buyer@example.org");
assert.match(inquiries[0].args[6], /solicita instrucciones de pago en USD/);
const events = entries.filter(x => x.sql.includes("INSERT INTO lumen_conversion_events"));
const usdEvents = events.filter(x => x.args[2] === "usd_payment_request");
assert.equal(usdEvents.length, 1);
assert.equal(JSON.parse(usdEvents[0].args[12]).charged, false);
assert.equal(JSON.parse(usdEvents[0].args[12]).invoiceCreated, false);
assert.equal(entries.some(x => /lumen_x402_receipts|payment_receipts/i.test(x.sql)), false);

const x402 = await send("checkout", "x402-buyer@example.org");
assert.equal(x402.status, 303);
assert.match(x402.headers.get("location") || "", /^\/go\/sourcing-5\?/);
assert.equal(entries.filter(x => x.sql.includes("INSERT OR IGNORE INTO lumen_public_inquiries")).length, 2);
const consult = await send("consult", "info-buyer@example.org");
assert.equal(consult.status, 200);
assert.match(await consult.text(), /Consulta recibida/);

const health = await worker.fetch(new Request(base + "/health"), env);
assert.equal(health.status, 200);
assert.equal((await health.json()).version, "1.4-international-buyer-sales");
console.log("USD_PAYMENT_REQUEST_REGRESSION_OK");
console.log("No charge, no payment instructions, no auto invoice, x402 path preserved, CRM inquiry stored");
