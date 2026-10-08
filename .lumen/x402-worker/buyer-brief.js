import { inspectUntrustedExternalText } from "../a2a-worker/untrusted-input-firewall.js";

// Buyers may add a *nonconfidential* brief to an x402 GET request. Query
// parameters are visible in URLs, logs, and browser history. Never accept
// wallet secrets, prompt commands or confidential records by this route.
const MAX_CHARS = 1200;
const MIN_CHARS = 12;
export const BUYER_BRIEF_POLICY = Object.freeze({
  minChars:MIN_CHARS,
  maxChars:MAX_CHARS,
  inputIsUntrustedData:true,
  firewall:"untrusted-input-firewall",
  acceptsConfidentialInput:false,
  settlementRequiredBeforeQueue:true,
  ownerApprovalRequiredBeforeSettlement:true
});
export function inspectBuyerBrief(raw,{optional=false}={}){
  if(raw===undefined||raw===null||raw===""){
    return optional?{ok:true,absent:true,text:null}:{ok:false,error:"brief_required"};
  }
  if(typeof raw!=="string")return {ok:false,error:"brief_must_be_text"};
  if(raw.length>MAX_CHARS*2)return {ok:false,error:"brief_too_long"};
  const normalized=raw.normalize("NFKC").replace(/\s+/g," ").trim();
  if(normalized.length<MIN_CHARS)return {ok:false,error:"brief_too_short"};
  if(normalized.length>MAX_CHARS)return {ok:false,error:"brief_too_long"};
  if(/[\x00-\x08\x0B\x0C\x0E-\x1F]/.test(raw))return {ok:false,error:"brief_control_characters"};
  // The shared LUMEN untrusted-input firewall is the mandatory gateway.
  // External content is never promoted to an instruction or system authority.
  const firewall=inspectUntrustedExternalText(normalized);
  if(!firewall.allowed)return {ok:false,error:"untrusted_input_firewall_rejected"};
  // GET query strings are not suitable for secrets, PII or signed documents.
  if(/\b(?:password|passphrase|api[_ -]?key|access[_ -]?token|private[_ -]?key|seed phrase|credit card|cvv|social security|passport number)\b/i.test(normalized))
    return {ok:false,error:"confidential_input_not_allowed_in_url"};
  if(/https?:\/\/[^\s/@]+:[^\s/@]+@/i.test(normalized))
    return {ok:false,error:"embedded_url_credentials_not_allowed"};
  return {ok:true,absent:false,text:normalized,untrustedData:true};
}
export function briefFromUrl(url){
  const u = url instanceof URL?url:new URL(url);
  const entries=u.searchParams.getAll("requirement");
  if(entries.length>1)return {ok:false,error:"duplicate_requirement"};
  return entries.length===0?{ok:true,absent:true,text:null}:inspectBuyerBrief(entries[0]);
}
