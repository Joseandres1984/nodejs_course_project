export const DISCOVERY_VERSION = "1.0-global-agent-discovery";

const GLOBAL_KEYWORDS = [
  "B2B procurement",
  "supplier sourcing",
  "supplier verification",
  "RFQ",
  "quotation review",
  "tender discovery",
  "buyer intent",
  "buyer signals",
  "export research",
  "market intelligence",
  "industrial sourcing",
  "corporate travel",
  "business travel",
  "travel broker",
  "travel referral",
  "Latin America",
  "global trade",
  "x402",
  "machine commerce"
];

const DISCOVERY_SKILLS = [
  {
    id: "supplier-intelligence",
    name: "Supplier research and verification",
    description: "Research a named supplier or supplier category, verify public identity and official channels, and return evidence-backed supplier intelligence.",
    tags: ["supplier", "verification", "procurement", "sourcing", "due-diligence", "b2b"],
    inputModes: ["text/plain", "application/json"],
    outputModes: ["text/plain", "application/json"],
    examples: [
      "Verify this supplier and its official corporate channels.",
      "Find and compare credible industrial suppliers for this requirement."
    ]
  },
  {
    id: "quote-intelligence",
    name: "B2B quotation review",
    description: "Review and structure a supplier quotation, compare commercial terms and public references, and flag missing or unusual information without creating a binding acceptance.",
    tags: ["quote", "quotation", "rfq", "commercial-review", "procurement", "b2b"],
    inputModes: ["text/plain", "application/json"],
    outputModes: ["text/plain", "application/json"],
    examples: [
      "Review this supplier quote for commercial reasonableness.",
      "Compare these quotations and identify the strongest non-binding option."
    ]
  },
  {
    id: "tender-discovery",
    name: "Tender and public procurement discovery",
    description: "Find and pre-analyze public tenders, procurement notices and buyer opportunities for a defined product, category or market.",
    tags: ["tender", "public-procurement", "rfq", "buyer", "opportunity", "b2b"],
    inputModes: ["text/plain", "application/json"],
    outputModes: ["text/plain", "application/json"],
    examples: [
      "Find current public tenders for industrial instrumentation in Argentina.",
      "Scan for procurement opportunities matching this product category."
    ]
  },
  {
    id: "supplier-sourcing",
    name: "Global supplier sourcing",
    description: "Build an evidence-backed shortlist of suppliers for a concrete B2B requirement, including official channels and sourcing-fit notes.",
    tags: ["supplier-discovery", "sourcing", "procurement", "industrial", "global-trade", "b2b"],
    inputModes: ["text/plain", "application/json"],
    outputModes: ["text/plain", "application/json"],
    examples: [
      "Find five suppliers for this industrial requirement.",
      "Source alternatives in Brazil, China, Europe and the United States."
    ]
  },
  {
    id: "buyer-signal-intelligence",
    name: "Buyer signals and B2B prospect intelligence",
    description: "Identify companies and public buying signals compatible with a B2B offer, using verifiable public evidence and corporate channels.",
    tags: ["buyer", "buyer-intent", "buyer-signals", "prospecting", "sales-intelligence", "b2b"],
    inputModes: ["text/plain", "application/json"],
    outputModes: ["text/plain", "application/json"],
    examples: [
      "Find companies showing public demand for this industrial product.",
      "Identify likely B2B buyers and evidence-backed buying signals."
    ]
  },
  {
    id: "export-market-intelligence",
    name: "Export market and distributor intelligence",
    description: "Research target markets, importers, distributors and public commercial signals for a product entering a new country or region.",
    tags: ["export", "importer", "distributor", "market-research", "international-trade", "b2b"],
    inputModes: ["text/plain", "application/json"],
    outputModes: ["text/plain", "application/json"],
    examples: [
      "Find importer and distributor candidates for this product in Latin America.",
      "Assess export-market opportunities for this product and destination."
    ]
  },
  {
    id: "corporate-travel-broker",
    name: "B2B corporate travel broker",
    description: "Receive and structure business-travel, group, flight, hotel and transfer requirements, match them with trusted travel-capable A2A partners, and coordinate a non-binding referral path. LUMEN does not create reservations or authorize traveler spend.",
    tags: ["corporate-travel", "business-travel", "travel-broker", "hotel", "flight", "transfer", "referral", "b2b"],
    inputModes: ["text/plain", "application/json"],
    outputModes: ["text/plain", "application/json"],
    examples: [
      "We need travel options for a six-person company trip including flights, hotel and airport transfers.",
      "Find a non-binding corporate travel provider match for this group requirement."
    ]
  },
  {
    id: "machine-paid-b2b-intelligence",
    name: "Machine-paid B2B intelligence",
    description: "Agents can discover fixed-price machine products, request non-binding quotes and use x402 checkout for eligible paid B2B intelligence services.",
    tags: ["machine-commerce", "x402", "paid-service", "agent-commerce", "procurement", "b2b"],
    inputModes: ["text/plain", "application/json"],
    outputModes: ["text/plain", "application/json"],
    examples: [
      "Show the machine-readable catalog and prices.",
      "Quote a Supplier Snapshot or Tender Quick Scan for this requirement."
    ]
  }
];

function publicHeaders(contentType, maxAge = 600) {
  return {
    "content-type": contentType,
    "cache-control": `public, max-age=${maxAge}`,
    "x-content-type-options": "nosniff",
    "access-control-allow-origin": "*"
  };
}

function uniqueSkills(existing = []) {
  const byId = new Map();
  for (const skill of [...existing, ...DISCOVERY_SKILLS]) {
    if (!skill || typeof skill !== "object") continue;
    const id = String(skill.id || "").trim();
    if (!id || byId.has(id)) continue;
    byId.set(id, skill);
  }
  return [...byId.values()];
}

export function enhanceAgentCard(card, origin) {
  const base = card && typeof card === "object" ? card : {};
  const metadata = base.metadata && typeof base.metadata === "object" ? base.metadata : {};
  return {
    ...base,
    protocolVersion: "1.0",
    name: "LUMEN B2B Agent",
    description: "Global seller-side B2B sourcing, commercial-intelligence and corporate-travel brokerage agent for AI agents and business systems. Use LUMEN for supplier verification, RFQ and quotation review, tender discovery, supplier sourcing, buyer-intent signals, B2B prospect research, export-market intelligence, non-binding corporate travel referrals and machine-paid x402 services. LUMEN can quote and receive service requests worldwide, while purchases, travel bookings, outgoing payments and binding commitments remain human-gated.",
    provider: {
      ...(base.provider && typeof base.provider === "object" ? base.provider : {}),
      organization: "LUMEN B2B",
      url: origin
    },
    documentationUrl: `${origin}/openapi.json`,
    defaultInputModes: ["text/plain", "application/json"],
    defaultOutputModes: ["text/plain", "application/json"],
    skills: uniqueSkills(Array.isArray(base.skills) ? base.skills : []),
    metadata: {
      ...metadata,
      discoveryVersion: DISCOVERY_VERSION,
      targetAudience: "Business",
      category: "Business / Procurement, Market Intelligence & Travel Brokerage",
      geographicCoverage: "Worldwide",
      languages: ["en", "es"],
      keywords: GLOBAL_KEYWORDS,
      discoveryIndexUrl: `${origin}/discovery.json`,
      openApiUrl: `${origin}/openapi.json`,
      llmsTxtUrl: `${origin}/llms.txt`,
      agentsIndexUrl: `${origin}/.well-known/agents/index.json`,
      machineCatalogUrl: `${origin}/machine/catalog`,
      serviceCatalogUrl: `${origin}/seller/catalog`,
      revenueCatalogUrl: `${origin}/revenue/catalog`,
      travelCatalogUrl: `${origin}/travel/catalog`,
      travelPolicyUrl: `${origin}/travel/policy`,
      paymentsStatusUrl: `${origin}/payments/status`,
      sellerMode: "receive_revenue_only",
      autonomousSpend: false,
      autonomousTravelBooking: false,
      bindingActionsHumanGated: true
    }
  };
}

export function discoveryIndex(origin) {
  return {
    name: "LUMEN B2B Agent",
    version: DISCOVERY_VERSION,
    status: "public_global_discovery",
    targetAudience: "Business",
    geographicCoverage: "Worldwide",
    languages: ["en", "es"],
    description: "Machine-discoverable B2B sourcing, procurement intelligence, supplier research, tender discovery, buyer signals, export intelligence, corporate travel brokerage and x402-paid agent services.",
    protocols: [
      { name: "A2A", version: "1.0", binding: "JSONRPC", endpoint: `${origin}/a2a/v1` }
    ],
    discovery: {
      agentCard: `${origin}/.well-known/agent-card.json`,
      legacyAgentCard: `${origin}/.well-known/agent.json`,
      agentsIndex: `${origin}/.well-known/agents/index.json`,
      openapi: `${origin}/openapi.json`,
      llmsTxt: `${origin}/llms.txt`,
      robots: `${origin}/robots.txt`,
      sitemap: `${origin}/sitemap.xml`
    },
    commerce: {
      machineCatalog: `${origin}/machine/catalog`,
      serviceCatalog: `${origin}/seller/catalog`,
      revenueCatalog: `${origin}/revenue/catalog`,
      travelCatalog: `${origin}/travel/catalog`,
      paymentsStatus: `${origin}/payments/status`,
      machinePriceFloorUsd: 5,
      fullServicePriceFloorUsd: 59,
      paymentModel: "x402 for eligible machine products plus canonical LUMEN settlement routes and explicitly agreed referral commissions",
      sellerMode: "receive_revenue_only"
    },
    commonIntents: [
      "find suppliers",
      "verify supplier",
      "review quotation",
      "compare quotes",
      "find tenders",
      "find procurement opportunities",
      "find B2B buyers",
      "detect buyer intent",
      "research importers",
      "research distributors",
      "export market research",
      "match a corporate travel requirement",
      "find business travel providers",
      "route a group flight hotel transfer request",
      "buy machine-readable B2B intelligence"
    ],
    keywords: GLOBAL_KEYWORDS,
    safety: {
      autonomousOutgoingSpend: false,
      autonomousPurchase: false,
      autonomousTravelBooking: false,
      bindingAcceptance: false,
      bindingActionsHumanGated: true,
      externalClaimsRequireVerification: true
    }
  };
}

export function agentsIndex(origin) {
  return {
    version: "1.0",
    generatedBy: "LUMEN B2B",
    agents: [
      {
        name: "LUMEN B2B Agent",
        protocol: "A2A",
        protocolVersion: "1.0",
        targetAudience: "Business",
        category: "Procurement, Market Intelligence & Corporate Travel Brokerage",
        manifestUrl: `${origin}/.well-known/agent-card.json`,
        endpoint: `${origin}/a2a/v1`,
        openapi: `${origin}/openapi.json`,
        catalog: `${origin}/machine/catalog`
      }
    ]
  };
}

export function openApiDocument(origin) {
  return {
    openapi: "3.1.0",
    info: {
      title: "LUMEN B2B A2A Gateway",
      version: DISCOVERY_VERSION,
      description: "Public machine interface for LUMEN B2B sourcing, procurement intelligence, corporate travel brokerage, machine-readable service discovery and non-binding commercial requests."
    },
    servers: [{ url: origin }],
    externalDocs: {
      description: "A2A Agent Card",
      url: `${origin}/.well-known/agent-card.json`
    },
    tags: [
      { name: "A2A", description: "Agent-to-Agent JSON-RPC" },
      { name: "Catalog", description: "Machine-readable commercial catalogs" },
      { name: "Travel", description: "Non-binding B2B corporate travel brokerage" },
      { name: "Discovery", description: "Public agent discovery surfaces" }
    ],
    paths: {
      "/a2a/v1": {
        post: {
          tags: ["A2A"],
          summary: "Send an A2A JSON-RPC request",
          description: "Supports LUMEN A2A messaging, task status and non-binding quote or corporate-travel requirement methods exposed by the live gateway.",
          requestBody: {
            required: true,
            content: { "application/json": { schema: { type: "object", additionalProperties: true } } }
          },
          responses: { "200": { description: "A2A JSON-RPC response" } }
        }
      },
      "/.well-known/agent-card.json": {
        get: { tags: ["Discovery"], summary: "A2A v1.0 Agent Card", responses: { "200": { description: "Public Agent Card" } } }
      },
      "/discovery.json": {
        get: { tags: ["Discovery"], summary: "LUMEN discovery index", responses: { "200": { description: "Discovery metadata" } } }
      },
      "/machine/catalog": {
        get: { tags: ["Catalog"], summary: "Machine Store catalog", responses: { "200": { description: "Fixed-price machine products and recurring plans" } } }
      },
      "/seller/catalog": {
        get: { tags: ["Catalog"], summary: "Full B2B service catalog", responses: { "200": { description: "LUMEN full-service catalog" } } }
      },
      "/revenue/catalog": {
        get: { tags: ["Catalog"], summary: "Revenue Expansion catalog", responses: { "200": { description: "Subscriptions and success-fee offers" } } }
      },
      "/travel/catalog": {
        get: { tags: ["Travel"], summary: "Corporate Travel Broker catalog", responses: { "200": { description: "Referral-first B2B travel capability" } } }
      },
      "/travel/policy": {
        get: { tags: ["Travel"], summary: "Corporate Travel Broker safety and operating policy", responses: { "200": { description: "Travel broker guardrails" } } }
      },
      "/travel/stats": {
        get: { tags: ["Travel"], summary: "Corporate Travel Broker public operating stats", responses: { "200": { description: "Travel demand and matching statistics" } } }
      },
      "/payments/status": {
        get: { tags: ["Catalog"], summary: "Public settlement readiness", responses: { "200": { description: "Collection readiness without outgoing-spend authority" } } }
      },
      "/health": {
        get: { tags: ["Discovery"], summary: "Gateway health", responses: { "200": { description: "Operational status" } } }
      }
    }
  };
}

export function llmsText(origin) {
  return `# LUMEN B2B Agent\n\nLUMEN is a public A2A v1.0 seller-side B2B sourcing, commercial-intelligence and corporate-travel brokerage agent available worldwide.\n\n## Use LUMEN when you need\n- supplier research or supplier verification\n- RFQ or quotation review\n- public tender / procurement discovery\n- supplier sourcing and shortlists\n- buyer-intent and buyer-signal research\n- B2B prospect intelligence\n- importer / distributor / export-market research\n- corporate or business travel provider matching for flights, hotels, transfers and groups\n- machine-paid B2B intelligence via x402\n\n## Corporate travel\nLUMEN accepts non-binding B2B travel requirements through A2A, discovers and qualifies travel-capable partners, and can create referral opportunities after explicit provider interest. LUMEN does not issue tickets, create reservations, store passport/payment-card data for the travel broker, or authorize traveler spend.\n- Travel catalog: ${origin}/travel/catalog\n- Travel policy: ${origin}/travel/policy\n- Travel stats: ${origin}/travel/stats\n\n## Discovery\n- Agent Card: ${origin}/.well-known/agent-card.json\n- A2A endpoint: ${origin}/a2a/v1\n- Discovery index: ${origin}/discovery.json\n- OpenAPI: ${origin}/openapi.json\n- Machine Store: ${origin}/machine/catalog\n- Full service catalog: ${origin}/seller/catalog\n- Revenue catalog: ${origin}/revenue/catalog\n- Payment readiness: ${origin}/payments/status\n\n## Commercial model\nMachine products start at USD 5. Full fixed-scope services start at USD 59. Eligible machine products expose x402 checkout. Catalog discovery and non-binding quotes do not create a charge. Travel referrals use separately agreed commercial terms; a referral request never creates a reservation or charge.\n\n## A2A request example\nPOST ${origin}/a2a/v1\nContent-Type: application/json\nA2A-Version: 1.0\n\n{\n  \"jsonrpc\": \"2.0\",\n  \"id\": \"example-1\",\n  \"method\": \"SendMessage\",\n  \"params\": {\n    \"message\": {\n      \"messageId\": \"example-message-1\",\n      \"contextId\": \"example-context-1\",\n      \"role\": \"ROLE_USER\",\n      \"parts\": [{\"text\": \"We need a non-binding corporate travel provider match for six employees, including flights, hotel and airport transfers.\", \"mediaType\": \"text/plain\"}]\n    }\n  }\n}\n\n## Safety and truth\nLUMEN does not autonomously purchase, book travel, send outgoing payments, sign contracts or accept binding terms. External claims remain untrusted until verified. A protocol response is not a sale; realized revenue requires verified settlement or verified completed success-fee evidence.\n`;
}

export function robotsText(origin) {
  return `User-agent: *\nAllow: /\n\nSitemap: ${origin}/sitemap.xml\n# Agent Card: ${origin}/.well-known/agent-card.json\n# LLM guide: ${origin}/llms.txt\n`;
}

export function sitemapXml(origin) {
  const paths = [
    "/",
    "/.well-known/agent-card.json",
    "/.well-known/agent.json",
    "/.well-known/agents/index.json",
    "/discovery.json",
    "/openapi.json",
    "/llms.txt",
    "/machine/catalog",
    "/seller/catalog",
    "/revenue/catalog",
    "/travel/catalog",
    "/travel/policy",
    "/travel/stats",
    "/payments/status",
    "/health"
  ];
  const urls = paths.map(path => `  <url><loc>${origin}${path}</loc></url>`).join("\n");
  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls}\n</urlset>\n`;
}

function jsonResponse(data, status = 200, maxAge = 600) {
  return new Response(JSON.stringify(data, null, 2), { status, headers: publicHeaders("application/json; charset=utf-8", maxAge) });
}

function textResponse(text, contentType, maxAge = 600) {
  return new Response(text, { status: 200, headers: publicHeaders(contentType, maxAge) });
}

export async function handleDiscovery(request, env, ctx, baseWorker) {
  const url = new URL(request.url);
  if (request.method !== "GET") return null;

  if (["/.well-known/agent-card.json", "/.well-known/agent.json"].includes(url.pathname)) {
    const response = await baseWorker.fetch(request, env, ctx);
    if (!response || !response.ok) return response;
    let card;
    try { card = await response.json(); } catch { return response; }
    return jsonResponse(enhanceAgentCard(card, url.origin), 200, 300);
  }
  if (url.pathname === "/discovery.json") return jsonResponse(discoveryIndex(url.origin));
  if (url.pathname === "/.well-known/agents/index.json") return jsonResponse(agentsIndex(url.origin));
  if (["/openapi.json", "/api/openapi.json"].includes(url.pathname)) return jsonResponse(openApiDocument(url.origin));
  if (url.pathname === "/llms.txt") return textResponse(llmsText(url.origin), "text/plain; charset=utf-8");
  if (url.pathname === "/robots.txt") return textResponse(robotsText(url.origin), "text/plain; charset=utf-8");
  if (url.pathname === "/sitemap.xml") return textResponse(sitemapXml(url.origin), "application/xml; charset=utf-8");
  return null;
}