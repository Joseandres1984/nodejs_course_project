import assert from "node:assert/strict";
import {
  DISCOVERY_VERSION,
  agentsIndex,
  discoveryIndex,
  enhanceAgentCard,
  handleDiscovery,
  llmsText,
  openApiDocument,
  robotsText,
  sitemapXml
} from "./discovery.js";
import { REGISTRY_PACKAGE_NAME, applyRegistryIdentity } from "./worker-entry.js";

const origin = "https://lumen-zero-a2a.lumen-b2b.workers.dev";
const baseCard = {
  protocolVersion: "1.0",
  name: "LUMEN B2B Agent",
  description: "base",
  url: `${origin}/a2a/v1`,
  supportedInterfaces: [{ url: `${origin}/a2a/v1`, protocolBinding: "JSONRPC", protocolVersion: "1.0" }],
  provider: { organization: "LUMEN B2B", url: origin },
  capabilities: { streaming: false, pushNotifications: false },
  defaultInputModes: ["text/plain"],
  defaultOutputModes: ["text/plain"],
  skills: [{ id: "existing", name: "Existing skill", description: "existing", tags: ["existing"] }],
  metadata: { sellerMode: "receive_revenue_only", autonomousSpend: false }
};

const card = enhanceAgentCard(baseCard, origin);
assert.equal(card.protocolVersion, "1.0");
assert.equal(card.metadata.targetAudience, "Business");
assert.equal(card.metadata.geographicCoverage, "Worldwide");
assert.equal(card.metadata.autonomousSpend, false);
assert.equal(card.metadata.bindingActionsHumanGated, true);
assert.ok(card.description.toLowerCase().includes("supplier verification"));
assert.ok(card.description.toLowerCase().includes("worldwide"));
assert.ok(card.skills.some(x => x.id === "supplier-intelligence"));
assert.ok(card.skills.some(x => x.id === "tender-discovery"));
assert.ok(card.skills.some(x => x.id === "buyer-signal-intelligence"));
assert.ok(card.skills.some(x => x.id === "machine-paid-b2b-intelligence"));
assert.ok(card.skills.filter(x => x.id !== "existing").every(x => Array.isArray(x.examples) && x.examples.length >= 2));

const registryCard = applyRegistryIdentity(card);
assert.equal(REGISTRY_PACKAGE_NAME, "github.Joseandres1984.lumen_b2b_agent");
assert.equal(registryCard.package_name, REGISTRY_PACKAGE_NAME);
assert.equal(registryCard.metadata.registryPackageName, REGISTRY_PACKAGE_NAME);
assert.equal(registryCard.metadata.registryIdentityProvider, "github");
assert.equal(registryCard.metadata.registryOwner, "Joseandres1984");
assert.equal(registryCard.metadata.autonomousSpend, false);
assert.equal(registryCard.metadata.bindingActionsHumanGated, true);

const discovery = discoveryIndex(origin);
assert.equal(discovery.version, DISCOVERY_VERSION);
assert.equal(discovery.targetAudience, "Business");
assert.equal(discovery.geographicCoverage, "Worldwide");
assert.equal(discovery.commerce.machinePriceFloorUsd, 5);
assert.equal(discovery.safety.autonomousOutgoingSpend, false);
assert.ok(discovery.commonIntents.includes("find suppliers"));

const openapi = openApiDocument(origin);
assert.equal(openapi.openapi, "3.1.0");
assert.ok(openapi.paths["/a2a/v1"]?.post);
assert.ok(openapi.paths["/machine/catalog"]?.get);
assert.ok(openapi.paths["/.well-known/agent-card.json"]?.get);

const llms = llmsText(origin);
assert.ok(llms.includes(`${origin}/.well-known/agent-card.json`));
assert.ok(llms.includes("Machine products start at USD 5"));
assert.ok(llms.includes("x402"));

const robots = robotsText(origin);
assert.ok(robots.includes("User-agent: *"));
assert.ok(robots.includes(`${origin}/sitemap.xml`));

const sitemap = sitemapXml(origin);
assert.ok(sitemap.includes(`${origin}/openapi.json`));
assert.ok(sitemap.includes(`${origin}/machine/catalog`));

const index = agentsIndex(origin);
assert.equal(index.agents.length, 1);
assert.equal(index.agents[0].manifestUrl, `${origin}/.well-known/agent-card.json`);

const fakeWorker = {
  async fetch() {
    return Response.json(baseCard);
  }
};
const response = await handleDiscovery(new Request(`${origin}/.well-known/agent-card.json`), {}, {}, fakeWorker);
assert.equal(response.status, 200);
const liveCard = await response.json();
assert.equal(liveCard.metadata.discoveryVersion, DISCOVERY_VERSION);
assert.ok(liveCard.skills.some(x => x.id === "export-market-intelligence"));

const discoveryResponse = await handleDiscovery(new Request(`${origin}/discovery.json`), {}, {}, fakeWorker);
assert.equal(discoveryResponse.status, 200);
const discoveryBody = await discoveryResponse.json();
assert.equal(discoveryBody.commerce.sellerMode, "receive_revenue_only");

console.log("A2A_GLOBAL_DISCOVERY ok", {
  version: DISCOVERY_VERSION,
  skills: card.skills.length,
  targetAudience: card.metadata.targetAudience,
  geographicCoverage: card.metadata.geographicCoverage,
  registryPackageName: registryCard.package_name
});
