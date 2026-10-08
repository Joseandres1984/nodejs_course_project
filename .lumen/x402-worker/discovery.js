// x402 buyer discovery is READ ONLY. This file derives every advertised
// offer from the exact catalog used by the paid middleware, without purchases.
const BASE_NETWORK = "eip155:8453";
const PAY_TO = "0x04285DE6A083CEb28fb0C254a2ed0F5fdB2eeD28";
function originOnly(value) {
  const u=new URL(value);
  if(u.protocol!=="https:")throw new Error("https_origin_required");
  return u.origin;
}
function offers(products,origin){
  const host=originOnly(origin);
  return Object.entries(products).map(([slug,p])=>({
    slug,
    name:p.name,
    productId:p.id,
    serviceId:p.service_id,
    amountUsd:Number(p.price_usd),
    amountUsdcAtomic:String(Math.round(Number(p.price_usd)*1_000_000)),
    url:host+"/buy/"+slug
  }));
}
export function buildWellKnownX402(products,origin){
  return {
    version:1,
    resources:offers(products,origin).map(o=>o.url),
    instructions:"LUMEN seller-side x402 Base USDC endpoints. Initial unauthenticated GET returns HTTP 402. A signed authorization is held for explicit owner approval before facilitator settlement. Owner permission is individual and cannot be bypassed. See /openapi.json and /approvals/policy.",
    ownerApprovalRequired:true,
    ownerApprovalUrl:originOnly(origin)+"/approvals",
    network:BASE_NETWORK
  };
}
export function buildDiscoveryOpenApi(products,origin){
  const host=originOnly(origin);
  const paths={};
  for(const p of offers(products,host)){
    paths["/buy/"+p.slug]={
      get:{
        operationId:"buy_"+p.slug.replaceAll("-","_"),
        security:[],
        summary:p.name+" | x402 | $"+p.amountUsd.toFixed(2)+" USDC",
        description:"Paid B2B research request. Send unsigned GET to inspect the official HTTP 402 quote. To settle, buyer sends a valid x402 signed payment authorization; an exact-scope human approval by the LUMEN owner is required before the facilitator can execute. The owner approval request may yield 409; after owner approval retry with x-lumen-approval-id and a fresh signed x402 authorization. No automatic or self-approved charge. Paid requests queue research for later delivery; the 200 response is not the finished research report.",
        tags:["B2B sourcing","x402","agent services"],
        "x-payment-info":{
          protocols:[{x402:{}}],
          price:{mode:"fixed",currency:"USD",amount:p.amountUsd.toFixed(2)},
          network:BASE_NETWORK,
          asset:"USDC",
          payTo:PAY_TO,
          recipientApprovalRequired:true,
          productId:p.productId,
          serviceId:p.serviceId
        },
        parameters:[
          {name:"requirement",in:"query",required:false,description:"Nonconfidential buyer task description (12-1200 chars); reviewed through the untrusted-input-firewall and queued only after verified payment. Never include passwords or private company data in URLs.",schema:{type:"string",minLength:12,maxLength:1200}},
          {name:"payment-signature",in:"header",required:false,description:"Official x402 payment signature on a paid retry",schema:{type:"string"}},
          {name:"x-lumen-approval-id",in:"header",required:false,description:"Owner-approved one-use ticket for retry after HTTP 409",schema:{type:"string"}}
        ],
        responses:{
          "200":{description:"Payment settled with receipt; fulfillment may remain queued.",content:{"application/json":{schema:{type:"object"}}}},
          "402":{description:"Official x402 Payment Required; includes machine-readable payment terms."},
          "409":{description:"Owner approval pending or denied; settlement has NOT been attempted."},
          "503":{description:"Facilitator unavailable; fail closed."}
        }
      }
    };
  }
  return {
    openapi:"3.1.0",
    info:{title:"LUMEN B2B x402 Pay-per-Request Services",version:"1.0.1",description:"Real B2B sourcing and procurement research. Seven paid endpoints on Base mainnet. Payment settlement requires individual human approval by LUMEN. No autonomous purchases.",contact:{url:host+"/catalog"},"x-guidance":"Choose a B2B service and inspect its unsigned GET HTTP 402 challenge. A signed authorization requires separate one-use human owner approval before settlement. Pending requests return 409 with approvalRequestId and are not paid. After the owner approves the exact request, the buyer retries with a fresh signed authorization and the x-lumen-approval-id header. HTTP 200 is a paid receipt for queued research, not an instantly delivered report."},
    servers:[{url:host}],
    paths,
    "x-payment-policy":{
      network:BASE_NETWORK,currency:"USDC",recipient:PAY_TO,
      facilitator:"https://facilitator.xpay.sh",
      ownerApprovalRequired:true,settlementRequiresValidBuyerSignature:true,
      noAutonomousApproval:true
    }
  };
}
export function buildDiscoveryLlmsTxt(products,origin){
  const host=originOnly(origin);
  const lines=[
    "# LUMEN B2B Agent — x402 paid procurement research",
    "LUMEN provides machine-readable B2B supplier snapshots, quotation sanity checks, tender intelligence, sourcing shortlists, buyer signals, and export-market research.",
    "Catalog: "+host+"/catalog",
    "OpenAPI: "+host+"/openapi.json",
    "x402 fan-out: "+host+"/.well-known/x402",
    "Approval policy: "+host+"/approvals/policy",
    "Network: Base mainnet (eip155:8453); asset: USDC",
    "All charges require an individual manual LUMEN owner approval. No payment is executed when approval is pending.",
    "Start with an unsigned GET to the paid URL for the official HTTP 402 challenge. The buyer must provide a signed payment payload. If an approval is pending the response is HTTP 409 with an approvalRequestId. The owner approves the exact request separately. The buyer must retry with a fresh signed payment and x-lumen-approval-id. This is not an instant unattended checkout.",
    "A verified payment with a valid nonconfidential ?requirement=... brief automatically queues the research task; no second redeem call is required. Without a brief, the buyer may POST /redeem after payment. URL query strings are public; do not send secrets, customer records or private business data.",
    "",
    "## Fixed-price endpoints"
  ];
  for(const p of offers(products,host))lines.push("- "+p.name+" — USD "+p.amountUsd.toFixed(2)+" — "+p.url);
  return lines.join("\n")+"\n";
}
