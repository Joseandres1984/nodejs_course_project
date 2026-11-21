import {build} from "esbuild";
import {readFileSync} from "node:fs";
import {fileURLToPath} from "node:url";
const here = new URL(".", import.meta.url);
let local = {};
try {
  local = Object.fromEntries(readFileSync(new URL(".env.local", here), "utf8").split(/\r?\n/).filter(line => line && !line.startsWith("#")).map(line => {
    const i = line.indexOf("="); return [line.slice(0, i), line.slice(i + 1)];
  }));
} catch { /* CI can supply the environment directly. */ }
const token = process.env.LUMEN_POSTHOG_TOKEN || local.LUMEN_POSTHOG_TOKEN;
const host = process.env.LUMEN_POSTHOG_HOST || local.LUMEN_POSTHOG_HOST;
if (!token || !host) throw new Error("Provide LUMEN_POSTHOG_TOKEN and LUMEN_POSTHOG_HOST in the build environment.");
if (!/^phc_[a-zA-Z0-9_]+$/.test(token)) throw new Error("Only a public project token is allowed in the browser bundle.");
if (new URL(host).protocol !== "https:") throw new Error("Analytics host must use HTTPS.");
await build({
  entryPoints: [fileURLToPath(new URL("analytics.mjs", here))],
  outfile: fileURLToPath(new URL("../../lumen-store/landing.js", here)),
  bundle: true, minify: true, format: "iife", target: ["es2020"], legalComments: "eof",
  define: {"process.env.LUMEN_POSTHOG_TOKEN": JSON.stringify(token), "process.env.LUMEN_POSTHOG_HOST": JSON.stringify(host)},
});
console.log("Built static analytics bundle with public deployment configuration.");
