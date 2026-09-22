from __future__ import annotations

"""LUMEN Zero Acquisition Sprint v1.

Concentrates zero-cost commercial attention on the three lowest-friction entry products
(Supplier Snapshot, Quote Sanity Check and Tender Quick Scan), converts already-observed
real market evidence into traceable acquisition briefs, and routes at most one current
brief into the existing governed distribution pipeline per acquisition cycle.

This module does not search more, spend money, buy media, widen outbound caps, accept
binding terms or move funds. It only reuses evidence and execution gates that already
exist in LUMEN Zero.
"""

import hashlib
import os
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import acquisition_campaigns as acquisition
import autonomous_director_runtime as director

VERSION = "1.0-acquisition-sprint"
SPRINT_ID = "ACQ-SPRINT-FIRST-CASH-V1"
CONVERSION_BASE_URL = (
    os.getenv("LUMEN_CONVERSION_BASE_URL")
    or "https://lumen-zero-conversion.lumen-b2b.workers.dev"
).strip().rstrip("/")
MAX_BRIEFS_PER_CYCLE = 3
MAX_BRIEF_HISTORY = 120
MAX_DIRECTOR_PRIORITY = 99

FOCUS_PRODUCTS: Dict[str, Dict[str, Any]] = {
    "supplier-snapshot": {
        "name": "Supplier Snapshot",
        "price_usd": 5,
        "audience": "buyer",
        "roles": ["buyer_hunter", "market_manager", "revops"],
    },
    "quote-sanity": {
        "name": "Quote Sanity Check",
        "price_usd": 7,
        "audience": "buyer",
        "roles": ["buyer_hunter", "market_manager", "revops"],
    },
    "tender-scan": {
        "name": "Tender Quick Scan",
        "price_usd": 9,
        "audience": "supplier",
        "roles": ["supplier_hunter", "market_manager", "revops"],
    },
}

_QUOTE_TERMS = (
    "cotizacion", "cotización", "quotation", "quote", "rfq",
    "request for quotation", "solicitud de oferta", "concurso de precios",
)
_TENDER_TERMS = (
    "licitacion", "licitación", "tender", "procurement", "pliego",
    "presentar oferta", "recepcion de ofertas", "recepción de ofertas",
)
_EXCLUDED_SOURCES = {
    "demo", "simulation", "simulated", "technical-canary", "technical_canary",
    "canary", "test", "fixture",
}

# Capture the Experiment Engine wrappers installed immediately before this module in worker_entry.
_ORIGINAL_ACQUISITION_TICK = acquisition.acquisition_campaign_tick
_ORIGINAL_DIRECTOR_TICK = director.director_tick
_ORIGINAL_CHANNEL_PAYLOADS = acquisition._channel_payloads


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _d(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _l(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clean(value: Any, limit: int = 300) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _norm(value: Any) -> str:
    return _clean(value, 3000).lower()


def _source_is_real(row: Dict[str, Any]) -> bool:
    source = _norm(row.get("source") or row.get("market_source") or row.get("demand_source_kind"))
    if source in _EXCLUDED_SOURCES or any(token in source for token in ("technical-canary", "simulation", "simulated")):
        return False
    if row.get("technical_canary") or row.get("simulation") or row.get("simulated") or row.get("probe"):
        return False
    return True


def _row_text(row: Dict[str, Any]) -> str:
    keys = (
        "title", "name", "company_name", "name_hint", "category", "need", "details",
        "snippet", "description", "demand_source_kind", "qualification_reasons",
    )
    parts: List[str] = []
    for key in keys:
        value = row.get(key)
        if isinstance(value, list):
            parts.extend(_clean(x, 500) for x in value)
        elif value not in (None, ""):
            parts.append(_clean(value, 900))
    return _norm(" ".join(parts))


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _brief_id(seed: str) -> str:
    digest = hashlib.sha256(("LUMEN-ACQ-SPRINT|" + seed).encode("utf-8")).hexdigest()[:18].upper()
    return "ASB-" + digest


def _lead_lookup(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        str(row.get("id") or ""): row
        for row in _l(state.get("research_leads"))
        if isinstance(row, dict) and row.get("id")
    }


def _buyer_candidates(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    leads = _lead_lookup(state)
    rows: List[Dict[str, Any]] = []
    for account in _l(state.get("candidate_accounts")):
        if not isinstance(account, dict) or str(account.get("type") or "") != "buyer":
            continue
        if not account.get("verified_company") or not _source_is_real(account):
            continue
        has_demand = bool(
            account.get("demand_signal")
            or account.get("public_demand_hint")
            or account.get("direct_inbound_demand")
            or account.get("high_intent_public_demand")
        )
        if not has_demand:
            continue
        lead = leads.get(str(account.get("source_lead_id") or ""), {})
        if lead and not _source_is_real(lead):
            continue
        text = _row_text(account) + " " + _row_text(lead)
        product_slug = "quote-sanity" if _contains_any(text, _QUOTE_TERMS) else "supplier-snapshot"
        score = (
            100 if account.get("direct_inbound_demand") else
            94 if account.get("high_intent_public_demand") else
            86 if account.get("demand_signal") else 78
        )
        score += min(5, max(0, _i(account.get("demand_discovery_score"))) // 20)
        evidence_url = _clean(
            lead.get("url")
            or account.get("demand_discovery_url")
            or account.get("website")
            or account.get("domain"),
            500,
        )
        source_id = str(lead.get("id") or account.get("id") or "")
        seed = f"buyer|{account.get('id')}|{source_id}|{product_slug}"
        rows.append({
            "id": _brief_id(seed),
            "product_slug": product_slug,
            "audience": "buyer",
            "market_evidence_account_id": account.get("id"),
            "market_evidence_source_id": source_id,
            "market_evidence_url": evidence_url or None,
            "market_evidence_kind": "direct_inbound" if account.get("direct_inbound_demand") else "verified_public_demand",
            "evidence_score": min(100, score),
            "contact_ready": bool(account.get("verified_contact")),
            "evidence_summary": _clean(text, 500),
        })
    return rows


def _tender_candidates(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for lead in _l(state.get("research_leads")):
        if not isinstance(lead, dict) or not lead.get("id") or not _source_is_real(lead):
            continue
        if not (lead.get("public_demand_hint") or lead.get("demand_signal")):
            continue
        url = _clean(lead.get("url"), 500)
        if not url:
            continue
        text = _row_text(lead)
        if not _contains_any(text, _TENDER_TERMS):
            continue
        score = max(75, min(100, _i(lead.get("demand_score"), 75)))
        seed = f"tender|{lead.get('id')}|tender-scan"
        rows.append({
            "id": _brief_id(seed),
            "product_slug": "tender-scan",
            "audience": "supplier",
            "market_evidence_account_id": None,
            "market_evidence_source_id": str(lead.get("id") or ""),
            "market_evidence_url": url,
            "market_evidence_kind": "public_tender_or_procurement_signal",
            "evidence_score": score,
            "contact_ready": False,
            "evidence_summary": _clean(text, 500),
        })
    return rows


def _ranked_candidates(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = _buyer_candidates(state) + _tender_candidates(state)
    rows.sort(
        key=lambda row: (
            _i(row.get("evidence_score")),
            1 if row.get("contact_ready") else 0,
            str(row.get("id") or ""),
        ),
        reverse=True,
    )
    # Product diversity first, then fill remaining capacity by evidence strength.
    picked: List[Dict[str, Any]] = []
    used_products: set[str] = set()
    for row in rows:
        slug = str(row.get("product_slug") or "")
        if slug in used_products:
            continue
        picked.append(row)
        used_products.add(slug)
        if len(picked) >= MAX_BRIEFS_PER_CYCLE:
            return picked
    for row in rows:
        if row in picked:
            continue
        picked.append(row)
        if len(picked) >= MAX_BRIEFS_PER_CYCLE:
            break
    return picked


def _current_experiment(state: Dict[str, Any]) -> Dict[str, Any]:
    return _d(_d(state.get("experiment_engine")).get("current_experiment"))


def _tracking_url(brief: Dict[str, Any], experiment: Dict[str, Any]) -> str:
    slug = str(brief.get("product_slug") or "")
    creative = _clean(experiment.get("variant_id"), 120) or str(brief.get("id") or "")
    params = urllib.parse.urlencode({
        "src": "lumen-acquisition-sprint",
        "medium": "email_b2b",
        "campaign": SPRINT_ID,
        "creative": creative,
        "offer": str(brief.get("id") or ""),
    })
    return f"{CONVERSION_BASE_URL}/offer/{urllib.parse.quote(slug)}?{params}"


def _catalog_url(campaign: Dict[str, Any], variant: Dict[str, Any], channel: str) -> str:
    params = urllib.parse.urlencode({
        "src": "lumen-organic-acquisition",
        "medium": channel,
        "campaign": _clean(campaign.get("id"), 120),
        "creative": _clean(variant.get("id"), 120),
    })
    return f"{CONVERSION_BASE_URL}/catalog?{params}"


def _conversion_channel_payloads(campaign: Dict[str, Any], variant: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Keep legacy campaign semantics but move every newly refreshed link onto Cloudflare Conversion."""
    base = [dict(row) for row in (_ORIGINAL_CHANNEL_PAYLOADS(campaign, variant) or [])]
    headline = _clean(variant.get("headline") or campaign.get("headline"), 220)
    body = _clean(variant.get("body") or campaign.get("body"), 1200)
    cta = _clean(variant.get("cta") or campaign.get("cta") or "Ver servicios", 100)
    for payload in base:
        channel = str(payload.get("channel") or "owned_market")
        link = _catalog_url(campaign, variant, channel)
        payload["tracking_path"] = "/catalog"
        payload["tracking_url"] = link
        payload["public_base_url"] = CONVERSION_BASE_URL
        if channel == "email_b2b":
            payload["subject"] = headline[:120]
            payload["copy"] = f"{body}\n\n{cta}: {link}"
        elif channel == "instagram":
            payload["copy"] = f"{headline}\n{body}\n\n{cta} → {link}\n#B2B #Compras #Proveedores"
        else:
            payload["copy"] = f"{headline}\n\n{body}\n\n{cta}: {link}"
    return base


def _product_message(brief: Dict[str, Any], experiment: Dict[str, Any]) -> Dict[str, Any]:
    slug = str(brief.get("product_slug") or "")
    product = FOCUS_PRODUCTS[slug]
    link = _tracking_url(brief, experiment)
    if slug == "quote-sanity":
        subject = "Chequeo rápido de cotización B2B · USD 7"
        body = (
            "Si estás comparando o por recibir cotizaciones, LUMEN puede hacer un chequeo rápido de coherencia "
            "sobre precio, especificación, cantidad, moneda y condiciones. Es un análisis orientativo con evidencia pública, "
            "sin prometer mejor precio ni reemplazar una valuación certificada."
        )
    elif slug == "tender-scan":
        subject = "Tender Quick Scan · oportunidades públicas B2B · USD 9"
        body = (
            "Si vendés B2B y querés detectar oportunidades públicas sin dedicar horas a recorrer portales, LUMEN puede "
            "hacer un escaneo breve y entregar hasta 5 señales relevantes con comprador, fecha y enlace público. "
            "No incluye presentación de oferta ni garantía de adjudicación."
        )
    else:
        subject = "Chequeo rápido de proveedor B2B · USD 5"
        body = (
            "Si estás evaluando un proveedor, LUMEN puede hacer una validación rápida de identidad, presencia pública, "
            "señales comerciales y alertas visibles para ayudarte a decidir si vale la pena profundizar. "
            "No reemplaza due diligence legal, informe crediticio ni inspección física."
        )
    return {
        "channel": "email_b2b",
        "subject": subject,
        "copy": f"{body}\n\n{product['name']} · USD {product['price_usd']}: {link}",
        "tracking_path": f"/offer/{slug}",
        "tracking_url": link,
        "public_base_url": CONVERSION_BASE_URL,
        "requires_authorized_connector": False,
        "requires_human_budget_approval": False,
        "policy": "verified_business_contacts_only_opt_out_respected",
        "product_slug": slug,
        "sprint_brief_id": brief.get("id"),
    }


def _campaign_variant_for_audience(state: Dict[str, Any], audience: str) -> tuple[Dict[str, Any], Dict[str, Any]]:
    campaigns = [
        row for row in _l(state.get("acquisition_campaigns"))
        if isinstance(row, dict) and row.get("status") == "active" and str(row.get("audience") or "") == audience
    ]
    if not campaigns:
        return {}, {}
    campaign = campaigns[0]
    champion_id = str(campaign.get("champion_variant_id") or "")
    variants = [row for row in _l(campaign.get("variants")) if isinstance(row, dict)]
    variant = next((row for row in variants if str(row.get("id") or "") == champion_id), variants[0] if variants else {})
    return campaign, variant


def _queue_brief(state: Dict[str, Any], brief: Dict[str, Any], experiment: Dict[str, Any]) -> Dict[str, Any]:
    queue = state.setdefault("acquisition_distribution_queue", [])
    audience = str(brief.get("audience") or "buyer")
    dispatch = _d(experiment.get("dispatch"))
    experiment_key = str(dispatch.get("key") or "")
    experiment_audience = str(experiment.get("audience") or "")
    payload = _product_message(brief, experiment)

    # Best path: reuse the current Experiment Engine email canary when its audience matches.
    if experiment_key and experiment_audience == audience:
        item = next((row for row in queue if isinstance(row, dict) and str(row.get("key") or "") == experiment_key), None)
        if item is not None:
            item["payload"] = payload
            item["audience"] = audience
            item["acquisition_sprint_id"] = SPRINT_ID
            item["sprint_brief_id"] = brief.get("id")
            item["product_slug"] = brief.get("product_slug")
            item["updated_at"] = _now()
            experiment["sprint_brief_id"] = brief.get("id")
            experiment["product_slug"] = brief.get("product_slug")
            experiment["tracking_url"] = payload["tracking_url"]
            experiment["dispatch"]["acquisition_sprint_id"] = SPRINT_ID
            experiment["dispatch"]["sprint_brief_id"] = brief.get("id")
            experiment["dispatch"]["product_slug"] = brief.get("product_slug")
            return {"queued": True, "mode": "experiment_dispatch_reused", "key": experiment_key, "channel": "email_b2b"}

    # Fallback keeps the same governed distribution pipeline and its existing caps/quality gates.
    campaign, variant = _campaign_variant_for_audience(state, audience)
    if not campaign or not variant:
        return {"queued": False, "mode": "waiting_for_audience_campaign", "channel": "email_b2b"}
    key = f"SPRINT|{brief['id']}|{variant.get('id')}|email_b2b"
    existing = next((row for row in queue if isinstance(row, dict) and str(row.get("key") or "") == key), None)
    if existing is None:
        queue.append({
            "key": key,
            "campaign_id": campaign.get("id"),
            "variant_id": variant.get("id"),
            "audience": audience,
            "channel": "email_b2b",
            "payload": payload,
            "status": "ready_owned_or_existing_channel",
            "experiment_id": experiment.get("id"),
            "acquisition_sprint_id": SPRINT_ID,
            "sprint_brief_id": brief.get("id"),
            "product_slug": brief.get("product_slug"),
            "created_at": _now(),
            "updated_at": _now(),
        })
    else:
        existing.update({"payload": payload, "product_slug": brief.get("product_slug"), "updated_at": _now()})
    state["acquisition_distribution_queue"] = queue[-300:]
    return {"queued": True, "mode": "governed_sprint_dispatch", "key": key, "channel": "email_b2b"}


def _merge_briefs(state: Dict[str, Any], candidates: List[Dict[str, Any]], experiment: Dict[str, Any]) -> List[Dict[str, Any]]:
    previous = [row for row in _l(state.get("acquisition_sprint_briefs")) if isinstance(row, dict)]
    by_id = {str(row.get("id") or ""): dict(row) for row in previous if row.get("id")}
    for candidate in candidates:
        bid = str(candidate.get("id") or "")
        old = by_id.get(bid, {})
        row = dict(old)
        row.update(candidate)
        row["created_at"] = old.get("created_at") or _now()
        row["last_seen_at"] = _now()
        row["product"] = FOCUS_PRODUCTS[str(candidate.get("product_slug"))]["name"]
        row["price_usd"] = FOCUS_PRODUCTS[str(candidate.get("product_slug"))]["price_usd"]
        row["campaign"] = SPRINT_ID
        row["source"] = "lumen-acquisition-sprint"
        row["medium"] = "email_b2b"
        row["experiment_id"] = experiment.get("id")
        row["experiment_variant_id"] = experiment.get("variant_id")
        row["tracking_url"] = _tracking_url(row, experiment)
        row["status"] = old.get("status") or "prepared_from_real_evidence"
        row["spend_usd"] = 0
        row["binding"] = False
        by_id[bid] = row
    merged = list(by_id.values())
    merged.sort(key=lambda row: (str(row.get("last_seen_at") or ""), _i(row.get("evidence_score"))), reverse=True)
    state["acquisition_sprint_briefs"] = merged[:MAX_BRIEF_HISTORY]
    return state["acquisition_sprint_briefs"]


def acquisition_sprint_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    candidates = _ranked_candidates(state)
    experiment = _current_experiment(state)
    briefs = _merge_briefs(state, candidates, experiment)
    current_ids = {str(row.get("id") or "") for row in candidates}
    current = [row for row in briefs if str(row.get("id") or "") in current_ids]
    dispatch = {"queued": False, "mode": "waiting_for_real_evidence", "channel": "email_b2b"}
    selected: Optional[Dict[str, Any]] = current[0] if current else None
    if selected is not None:
        dispatch = _queue_brief(state, selected, experiment)
        selected["dispatch"] = dict(dispatch)
        selected["status"] = "queued_governed_distribution" if dispatch.get("queued") else "prepared_from_real_evidence"

    cognitive = _d(state.get("cognitive_director_learning"))
    top_product = _d(cognitive.get("top_product"))
    focus_winner = str(top_product.get("product_slug") or "")
    if focus_winner not in FOCUS_PRODUCTS:
        focus_winner = ""
    report = {
        "version": VERSION,
        "status": "active" if current else "waiting_for_real_market_evidence",
        "updated_at": _now(),
        "sprint_id": SPRINT_ID,
        "objective": "first real lead -> first checkout -> first settled payment -> repeat",
        "focus_products": [
            {"slug": slug, "name": row["name"], "price_usd": row["price_usd"]}
            for slug, row in FOCUS_PRODUCTS.items()
        ],
        "briefs_created_or_refreshed_this_cycle": len(current),
        "briefs_total": len(briefs),
        "current_brief_ids": [row.get("id") for row in current],
        "selected_brief_id": selected.get("id") if selected else None,
        "selected_product_slug": selected.get("product_slug") if selected else None,
        "dispatch": dispatch,
        "experiment_id": experiment.get("id"),
        "experiment_mode": experiment.get("mode"),
        "experiment_variant_id": experiment.get("variant_id"),
        "cognitive_focus_winner": focus_winner or None,
        "conversion_base_url": CONVERSION_BASE_URL,
        "attribution": {
            "source": "lumen-acquisition-sprint",
            "medium": "email_b2b",
            "campaign": SPRINT_ID,
            "offer_id": selected.get("id") if selected else None,
            "downstream_brief_id_rule": "conversion lead id is created only after requirements are submitted and is then propagated to x402",
        },
        "guardrails": {
            "monetary_budget_usd": 0,
            "paid_media": False,
            "search_budget_increased": False,
            "outbound_caps_increased": False,
            "binding_authority_changed": False,
            "autonomous_purchase": False,
            "governed_distribution_only": True,
            "technical_canaries_excluded": True,
        },
    }
    state["acquisition_sprint"] = report
    return report


def acquisition_tick_with_sprint(state: Dict[str, Any]) -> Dict[str, Any]:
    report = dict(_ORIGINAL_ACQUISITION_TICK(state) or {})
    sprint = acquisition_sprint_tick(state)
    report["acquisition_sprint"] = {
        "version": VERSION,
        "status": sprint.get("status"),
        "sprint_id": SPRINT_ID,
        "selected_brief_id": sprint.get("selected_brief_id"),
        "selected_product_slug": sprint.get("selected_product_slug"),
        "dispatch": sprint.get("dispatch"),
        "briefs_total": sprint.get("briefs_total"),
        "monetary_budget_usd": 0,
    }
    report["public_base_url"] = CONVERSION_BASE_URL
    return report


def _sprint_task(sprint: Dict[str, Any]) -> Dict[str, Any]:
    slug = str(sprint.get("selected_product_slug") or "")
    product = FOCUS_PRODUCTS.get(slug)
    dispatch = _d(sprint.get("dispatch"))
    if product:
        action = (
            f"Concentrar Buyer Hunter/Market Manager en {product['name']} (USD {product['price_usd']}) "
            "usando evidencia real ya observada y el canal orgánico gobernado; medir qualified intent, checkout y settlement."
        )
        roles = list(product["roles"])
        priority = 98 if dispatch.get("queued") else 93
    else:
        action = (
            "Buscar dentro de la evidencia real ya disponible el próximo caso vendible para Supplier Snapshot, Quote Sanity "
            "o Tender Scan; no fabricar demanda ni ampliar presupuesto de búsqueda."
        )
        roles = ["buyer_hunter", "market_manager", "research_analyst", "revops"]
        priority = 88
    return {
        "id": "DIR-ACQUISITION-SPRINT",
        "title": "Acquisition Sprint v1 · first cash",
        "priority": min(MAX_DIRECTOR_PRIORITY, priority),
        "roles": roles,
        "action": action,
        "success_metric": "qualified_intent_then_checkout_then_verified_settlement",
        "mode": "zero_cost_first_cash_acquisition",
        "autonomous": True,
        "spend_usd": 0,
        "binding": False,
        "sprint_id": SPRINT_ID,
        "sprint_brief_id": sprint.get("selected_brief_id"),
        "product_slug": slug or None,
        "hard_bottleneck_override": False,
    }


def director_tick_with_acquisition_sprint(state: Dict[str, Any], adaptive_report: Dict[str, Any] | None = None) -> Dict[str, Any]:
    report = dict(_ORIGINAL_DIRECTOR_TICK(state, adaptive_report) or {})
    sprint = _d(state.get("acquisition_sprint"))
    task = _sprint_task(sprint)
    plan = [
        dict(row) for row in _l(report.get("plan"))
        if isinstance(row, dict) and row.get("id") != "DIR-ACQUISITION-SPRINT"
    ]
    plan.append(task)
    plan.sort(key=lambda row: _i(row.get("priority")), reverse=True)
    report["plan"] = plan[: int(getattr(director, "MAX_PLAN", 6))]

    boosts = {str(k): min(director.ROLE_BOOST_CAP, max(0.0, _f(v))) for k, v in _d(report.get("role_boosts")).items()}
    for role in task.get("roles", []):
        amount = 0.10 if sprint.get("selected_product_slug") else 0.06
        boosts[role] = round(min(director.ROLE_BOOST_CAP, max(_f(boosts.get(role)), amount)), 4)
    report["role_boosts"] = boosts
    report["acquisition_sprint"] = {
        "version": VERSION,
        "status": sprint.get("status") or "not_initialized",
        "sprint_id": SPRINT_ID,
        "selected_brief_id": sprint.get("selected_brief_id"),
        "selected_product_slug": sprint.get("selected_product_slug"),
        "dispatch": sprint.get("dispatch"),
        "hard_bottleneck_preserved": True,
        "monetary_budget_usd": 0,
    }
    authority = dict(_d(report.get("authority")))
    authority.update({
        "acquisition_sprint_authority": "reversible_zero_cost_commercial_attention_only",
        "acquisition_sprint_monetary_budget_usd": 0,
        "acquisition_sprint_paid_media": False,
        "acquisition_sprint_search_budget_increased": False,
        "acquisition_sprint_outbound_caps_increased": False,
        "acquisition_sprint_binding_authority_changed": False,
        "acquisition_sprint_hard_bottleneck_override": False,
    })
    report["authority"] = authority
    state["autonomous_director"] = report
    return report


# Replace stale Railway acquisition links with the live Cloudflare Conversion surface before any
# acquisition cycle runs. The original channel/connector permissions are preserved unchanged.
acquisition.PUBLIC_BASE_URL = CONVERSION_BASE_URL
acquisition._channel_payloads = _conversion_channel_payloads

# Install after Experiment Engine so one commercial decision can be converted into a product-specific,
# traceable, zero-cost first-cash brief without bypassing the existing distribution/Director gates.
acquisition.acquisition_campaign_tick = acquisition_tick_with_sprint
director.director_tick = director_tick_with_acquisition_sprint

print({
    "acquisition_sprint_runtime": {
        "version": VERSION,
        "status": "installed",
        "sprint_id": SPRINT_ID,
        "focus_products": list(FOCUS_PRODUCTS),
        "conversion_base_url": CONVERSION_BASE_URL,
        "monetary_budget_usd": 0,
        "paid_media": False,
        "search_budget_increased": False,
        "outbound_caps_increased": False,
        "binding_authority_changed": False,
        "autonomous_purchase": False,
    }
}, flush=True)
