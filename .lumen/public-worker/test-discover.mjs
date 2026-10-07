import assert from "node:assert/strict";
import { ARTICLES, handleDiscover } from "./discover.js";

assert.equal(ARTICLES.length, 12);
assert.equal(new Set(ARTICLES.map(a => a.slug)).size, ARTICLES.length);
assert.ok(ARTICLES.every(a => a.title && a.description && a.intro && a.sections.length >= 4));

async function check(path, expected) {
  const response = handleDiscover(new Request(`https://lumen.example${path}`));
  assert.ok(response instanceof Response, `missing response for ${path}`);
  assert.equal(response.status, 200);
  const text = await response.text();
  for (const token of expected) assert.ok(text.includes(token), `${path} missing ${token}`);
}

await check("/discover", ["LUMEN Discover","Menos impulso. Más criterio.","sponsored nofollow noopener"]);
await check("/discover/comparar-precios-online-sin-falsas-ofertas", ["Cómo comparar precios online","Cómo trabajamos"]);
await check("/sitemap.xml", ["/discover/comparar-precios-online-sin-falsas-ofertas","/discover/privacidad-y-seguridad-al-comprar-online","/discover/como-detectar-descuentos-reales"]);
await check("/robots.txt", ["User-agent: *","Sitemap: https://lumen.example/sitemap.xml"]);

const missing = handleDiscover(new Request("https://lumen.example/discover/no-existe"));
assert.equal(missing.status, 404);

console.log("LUMEN_DISCOVER_CONTENT_AND_ROUTING_OK");
