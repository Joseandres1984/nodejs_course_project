import assert from "node:assert/strict";
import { declareDiscoveryExtension, bazaarResourceServerExtension } from "@x402/extensions/bazaar";

// Pure metadata-only regression: not a wallet, not a signed payment, not a
// request to the facilitator.
const ext = declareDiscoveryExtension({
  input: {},
  inputSchema:{type:"object",properties:{},required:[],additionalProperties:false},
  output:{
    example:{ok:true,productId:"MP-SUPPLIER-SNAPSHOT",amountUsd:1,status:"settlement_before_response"},
    schema:{type:"object",properties:{ok:{type:"boolean"},productId:{type:"string"},amountUsd:{type:"number"},status:{type:"string"}}}
  }
});
assert.ok(ext.bazaar,"Bazaar extension must be emitted");
assert.ok(ext.bazaar.info?.input,"Bazaar input example must be declared");
assert.ok(ext.bazaar.info?.output,"Bazaar output example must be declared");
assert.ok(ext.bazaar.schema?.properties?.input,"Bazaar input JSON schema must be declared");
assert.ok(ext.bazaar.schema?.properties?.output,"Bazaar output JSON schema must be declared");
assert.ok(bazaarResourceServerExtension,"Bazaar resource server extension must be available");
console.log("LUMEN_X402_BAZAAR_SCHEMAS_COMPLIANT_NO_PAYMENT_OK");
