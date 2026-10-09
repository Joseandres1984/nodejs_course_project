const VERSION = "1.0-commercial-response-qualification";

function json(data, status = 200) {
  return Response.json(data, { status, headers: { "cache-control":"no-store", "x-content-type-options":"nosniff", "access-control-allow-origin":"*" } });
}

function clean(value, limit = 8000) {
  return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit);
}

function authorized(request, env) {
  const configured = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500);
  const provided = clean(request.headers.get("x-lumen-admin"), 500);
  return Boolean(configured && provided && configured === provided);
}

function tokenSet(text) {
  return new Set(clean(text, 10000).toLowerCase().split(/[^a-z0-9]+/).filter(x => x.length >= 3));
}

function echoRatio(response, original) {
  const responseTokens = [...tokenSet(response)];
  const originalTokens = tokenSet(original);
  if (!responseTokens.length || !originalTokens.size) return 0;
  return responseTokens.filter(x => originalTokens.has(x)).length / responseTokens.length;
}

function hasAny(text, phrases) {
  return phrases.some(x => text.includes(x));
}

const REJECT = [
  "not interested","no thanks","no thank you","decline","do not contact","stop contacting","unsubscribe",
  "please stop","don't contact","dont contact","not looking","not buying","not needed"
];

// A courteous "not now" is still a decline, never a follow-up invitation.
// This generic training vocabulary intentionally contains no customer data.
const DEFERRED_DECLINE = [
  "preferimos no avanzar","preferimos no continuar","preferimos no seguir","por ahora no vamos a avanzar",
  "no vamos a avanzar","no avanzaremos por ahora","no estamos interesados","no estamos interesadas",
  "no nos interesa","no es el momento de avanzar","lo dejamos para mas adelante",
  "preferimos dejarlo para mas adelante","por el momento no avanzaremos",
  "we prefer not to proceed","we prefer not to move forward","not moving forward at this time",
  "not proceeding at this time","we will not proceed for now"
];
const SPANISH_INTEREST = ["nos resulta interesante","estamos interesados","estamos interesadas","nos interesa","me interesa","queremos conocer mas","nos gustaria conocer","nos gustaria entender"];
const SPANISH_QUESTION = ["cual es el precio","cuales son los precios","que precios manejan","que rangos manejan","tiene costo","cuanto cuesta","como funciona","como validan","podrian compartirnos","pueden compartirnos","cuales son las condiciones"];
function withoutAccents(value) { return value.normalize("NFD").replace(/[\u0300-\u036f]/g, ""); }

const NOT_RELEVANT = [
  "not relevant","wrong fit","not a fit","wrong agent","wrong contact","wrong person","outside our scope",
  "not applicable","not for us","doesn't apply","does not apply"
];

const TECH_ACK = [
  "accepted","received","queued","task created","acknowledged","message received","request received",
  "processing","submitted","created task","successfully received","accepted for processing"
];

const PURCHASE = [
  "send checkout","checkout link","payment link","where can i pay","how do i pay","ready to buy","ready to purchase",
  "would like to buy","would like to purchase","purchase this","buy this","let's proceed","lets proceed","go ahead",
  "proceed with","please proceed","send invoice","invoice me","take my payment","start the order","place the order"
];

const INTEREST = [
  "i am interested","i'm interested","we are interested","we're interested","interested in","sounds good","need this",
  "we need","i need","send details","please send details","send a quote","please quote","can we buy","can i buy",
  "this could help","this looks useful","this is useful","want to try","would like to try","tell me more"
];

const QUESTION = [
  "what is the price","what's the price","whats the price","how much","what does it include","what is included",
  "what's included","whats included","how does it work","how long does it take","what do you need from us",
  "what do you need from me","can you explain","could you explain","can you confirm","could you confirm",
  "what is the scope","what's the scope","whats the scope","do you support","can you provide","could you provide"
];

function result(responseClass, extra = {}) {
  const map = {
    PURCHASE_INTENT: { qualified:true, buyingIntent:true, stage:"NEGOTIATING", nextAction:"send_exact_checkout", rank:7 },
    COMMERCIAL_INTEREST: { qualified:true, buyingIntent:false, stage:"NEGOTIATING", nextAction:"clarify_scope_then_checkout", rank:6 },
    COMMERCIAL_QUESTION: { qualified:true, buyingIntent:false, stage:"NEGOTIATING", nextAction:"answer_question_and_advance", rank:5 },
    DECLINED: { qualified:false, buyingIntent:false, stage:"LOST", nextAction:"close_and_move_on", rank:1 },
    NOT_RELEVANT: { qualified:false, buyingIntent:false, stage:"LOST", nextAction:"close_and_move_on", rank:1 },
    TECHNICAL_ACK: { qualified:false, buyingIntent:false, stage:"RESPONDED", nextAction:"qualify_once_or_move_on", rank:2 },
    ECHO: { qualified:false, buyingIntent:false, stage:"RESPONDED", nextAction:"qualify_once_or_move_on", rank:2 },
    GENERIC_RESPONSE: { qualified:false, buyingIntent:false, stage:"RESPONDED", nextAction:"qualify_once_or_move_on", rank:3 },
    EMPTY: { qualified:false, buyingIntent:false, stage:null, nextAction:null, rank:0 }
  };
  return { responseClass, ...(map[responseClass] || map.GENERIC_RESPONSE), ...extra, version:VERSION };
}

export function classifyCommercialResponse(responseText, originalMessage = "") {
  const raw = clean(responseText, 8000);
  const t = raw.toLowerCase();
  const normalized = withoutAccents(t);
  if (!t) return result("EMPTY", { reason:"no_response_text", echoRatio:0 });

  if (hasAny(t, REJECT)) return result("DECLINED", { reason:"explicit_decline", echoRatio:0 });
  if (hasAny(normalized, DEFERRED_DECLINE)) return result("DECLINED", { reason:"explicit_deferred_decline", echoRatio:0 });
  if (hasAny(t, NOT_RELEVANT)) return result("NOT_RELEVANT", { reason:"explicit_not_relevant", echoRatio:0 });

  const ratio = echoRatio(raw, originalMessage);
  if (originalMessage && raw.length >= 80 && ratio >= 0.72) {
    return result("ECHO", { reason:"high_overlap_with_outbound_message", echoRatio:Number(ratio.toFixed(3)) });
  }

  const purchase = hasAny(t, PURCHASE);
  if (purchase) return result("PURCHASE_INTENT", { reason:"explicit_purchase_or_payment_language", echoRatio:Number(ratio.toFixed(3)) });

  const explicitCommercialQuestion = hasAny(t, QUESTION) || hasAny(normalized, SPANISH_QUESTION);
  const genericQuestion = t.includes("?") || /^(how|what|which|when|where|who|can|could|would|do|does|is|are)\b/.test(t);
  const interest = hasAny(t, INTEREST) || hasAny(normalized, SPANISH_INTEREST);

  if (interest && genericQuestion) return result("COMMERCIAL_QUESTION", { reason:"commercial_interest_with_question", echoRatio:Number(ratio.toFixed(3)) });
  if (interest) return result("COMMERCIAL_INTEREST", { reason:"explicit_interest_language", echoRatio:Number(ratio.toFixed(3)) });
  if (explicitCommercialQuestion) return result("COMMERCIAL_QUESTION", { reason:"commercial_question_signal", echoRatio:Number(ratio.toFixed(3)) });
  if (genericQuestion) return result("GENERIC_RESPONSE", { reason:"question_without_commercial_context", echoRatio:Number(ratio.toFixed(3)) });

  const compact = t.replace(/[.!]+$/g, "").trim();
  if (["yes","yes please","interested","proceed","go ahead"].includes(compact)) {
    return result(compact === "proceed" || compact === "go ahead" ? "PURCHASE_INTENT" : "COMMERCIAL_INTEREST", { reason:"compact_positive_reply", echoRatio:Number(ratio.toFixed(3)) });
  }

  const ackOnly = hasAny(t, TECH_ACK) && raw.length <= 260;
  if (ackOnly) return result("TECHNICAL_ACK", { reason:"transport_or_task_acknowledgement", echoRatio:Number(ratio.toFixed(3)) });

  return result("GENERIC_RESPONSE", { reason:"response_without_commercial_intent_signal", echoRatio:Number(ratio.toFixed(3)) });
}

export function pipelineStageForClassification(classification) {
  return classification?.stage || null;
}

export async function handleResponseQualification(request, env) {
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/response-qualification/policy") {
    return json({
      version:VERSION,
      classes:["TECHNICAL_ACK","ECHO","GENERIC_RESPONSE","COMMERCIAL_QUESTION","COMMERCIAL_INTEREST","PURCHASE_INTENT","DECLINED","NOT_RELEVANT"],
      qualifiedCommercialClasses:["COMMERCIAL_QUESTION","COMMERCIAL_INTEREST","PURCHASE_INTENT"],
      checkoutEligibleClasses:["PURCHASE_INTENT","COMMERCIAL_INTEREST"],
      deferredDeclineStopsFollowups:true,
      spanishCommercialFeedbackSupported:true,
      rawResponseIsNotCommercialIntent:true,
      technicalAckIsNotIntent:true,
      echoIsNotIntent:true,
      genericResponseIsNotIntent:true,
      addsExternalMessages:false,
      autonomousSpend:false,
      autonomousContract:false,
      bindingActionsHumanGated:true
    });
  }
  if (request.method === "POST" && url.pathname === "/response-qualification/classify") {
    if (!authorized(request, env)) return json({ ok:false, error:"admin_token_required" },403);
    let body = {}; try { body = await request.json(); } catch {}
    return json({ ok:true, classification:classifyCommercialResponse(body?.responseText, body?.originalMessage) },200);
  }
  return null;
}
