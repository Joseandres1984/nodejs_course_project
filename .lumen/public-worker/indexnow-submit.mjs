import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { ARTICLES, INDEXNOW_KEY } from "./discover.js";

const BASE = (process.env.LUMEN_PUBLIC_BASE_URL || "https://lumen-zero-public.lumen-b2b.workers.dev").replace(/\/+$/, "");
const endpoint = process.env.INDEXNOW_ENDPOINT || "https://api.indexnow.org/indexnow";

function bySlug(rows=[]) {
  return new Map(rows.map(row => [String(row.slug || ""), row]).filter(([slug]) => slug));
}

async function previousArticles() {
  try {
    const raw = execFileSync("git", ["show", "HEAD^:.lumen/public-worker/discover.js"], {
      cwd: new URL("../..", import.meta.url),
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"]
    });
    const path = "/tmp/lumen-discover-previous.mjs";
    writeFileSync(path, raw, "utf8");
    const mod = await import(pathToFileURL(path).href + "?v=" + Date.now());
    return Array.isArray(mod.ARTICLES) ? mod.ARTICLES : [];
  } catch {
    return [];
  }
}

const previous = await previousArticles();
const before = bySlug(previous);
const after = bySlug(ARTICLES);
const changed = [];
for (const [slug, row] of after) {
  const old = before.get(slug);
  if (!old || JSON.stringify(old) !== JSON.stringify(row)) changed.push(slug);
}
const removed = [...before.keys()].filter(slug => !after.has(slug));

if (!previous.length) {
  changed.splice(0, changed.length, ...ARTICLES.map(a => a.slug));
}

const urls = [...new Set([
  ...(changed.length || removed.length ? [BASE + "/discover", BASE + "/sitemap.xml", BASE + "/discover/feed.xml"] : []),
  ...changed.map(slug => BASE + "/discover/" + encodeURIComponent(slug)),
  ...removed.map(slug => BASE + "/discover/" + encodeURIComponent(slug))
])];

if (!urls.length) {
  console.log(JSON.stringify({ok:true,status:"INDEXNOW_NO_DISCOVER_CHANGES",submitted:0}));
  process.exit(0);
}

const keyLocation = `${BASE}/${INDEXNOW_KEY}.txt`;
const payload = {
  host: new URL(BASE).host,
  key: INDEXNOW_KEY,
  keyLocation,
  urlList: urls
};

if (process.env.INDEXNOW_DRY_RUN === "true") {
  console.log(JSON.stringify({ok:true,status:"INDEXNOW_DRY_RUN",submitted:urls.length,keyLocation,urls}));
  process.exit(0);
}

const response = await fetch(endpoint, {
  method:"POST",
  headers:{"content-type":"application/json; charset=utf-8","user-agent":"LUMEN-Discover-IndexNow/1.0"},
  body:JSON.stringify(payload)
});
const body = await response.text();
const accepted = response.status === 200 || response.status === 202;
console.log(JSON.stringify({ok:accepted,status:response.status,submitted:urls.length,keyLocation,urls,response:body.slice(0,500)}));
if (!accepted) process.exitCode = 2;
