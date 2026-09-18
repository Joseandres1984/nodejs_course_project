from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import Any, Dict, List


PUBLIC_BASE_URL = (os.getenv("LUMEN_PUBLIC_BASE_URL") or "https://lumen-web-production-5755.up.railway.app").strip().rstrip("/")
VERSION = "1.2-conversion-first-learning"
ZERO_LEAD_ROTATION_CLICKS = 8


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _token(seed: str) -> str:
    return hashlib.sha256(("LUMEN-ACQ|" + seed).encode("utf-8")).hexdigest()[:12].upper()


def _campaign_seed(audience: str) -> Dict[str, Any]:
    if audience == "buyer":
        return {
            "name": "Captación de compradores B2B",
            "goal": "qualified_buyer_lead",
            "headline": "¿Comprás para una empresa? LUMEN encuentra y compara proveedores por vos.",
            "body": "Contanos qué necesitás. LUMEN investiga alternativas, contrasta proveedores y ordena el proceso comercial para que llegues a una opción útil más rápido. El comprador contrata y paga directamente al proveedor.",
            "cta": "Buscar proveedores",
            "landing": "/join/buyer",
            "angles": [
                ("ahorro_tiempo", "Menos horas buscando. Más alternativas comparables.", "Decinos qué necesitás y LUMEN hace el trabajo de investigación comercial por vos."),
                ("confianza", "Compras B2B con más evidencia y menos ruido.", "LUMEN investiga proveedores y organiza la información antes de que tengas que decidir."),
                ("resultado", "Encontrá proveedores para una necesidad real, no una lista infinita.", "LUMEN parte de tu requerimiento y busca encaje comercial concreto."),
            ],
        }
    if audience == "supplier":
        return {
            "name": "Captación de proveedores",
            "goal": "qualified_supplier_lead",
            "headline": "¿Vendés B2B? LUMEN puede acercarte demanda calificada.",
            "body": "Sumá tu empresa a la red de proveedores de LUMEN. Investigamos necesidades compatibles, organizamos requerimientos y conectamos oportunidades donde tu oferta tenga sentido.",
            "cta": "Quiero recibir oportunidades",
            "landing": "/join/supplier",
            "angles": [
                ("demanda", "Tu equipo vende. LUMEN busca dónde puede encajar tu oferta.", "Ingresá a una red orientada a necesidades B2B reales y oportunidades compatibles."),
                ("eficiencia", "Más oportunidades útiles, menos prospección sin rumbo.", "LUMEN investiga demanda y prioriza encajes antes de acercar una oportunidad."),
                ("crecimiento", "Convertí tu catálogo en más conversaciones comerciales.", "Mostranos qué vendés y LUMEN buscará oportunidades compatibles dentro de sus límites comerciales."),
            ],
        }
    return {
        "name": "Captación de tiendas partner",
        "goal": "qualified_partner_store",
        "headline": "Tu catálogo puede vender más sin sumar otro equipo comercial.",
        "body": "LUMEN puede investigar tu catálogo, detectar compradores y derivar oportunidades identificadas. El comercio cobra y entrega; LUMEN monetiza únicamente una comisión o success fee acordado.",
        "cta": "Quiero ser partner",
        "landing": "/join/partner",
        "angles": [
            ("canal", "Sumá un canal comercial sin ceder el control de tu venta.", "Vos seguís cobrando y entregando. LUMEN trabaja para originar y atribuir oportunidades."),
            ("catalogo", "Tu catálogo ya existe. Hagamos que encuentre compradores.", "LUMEN estudia productos públicos y prepara oportunidades antes de proponer una relación comercial."),
            ("comision", "Más ventas con un modelo a comisión claramente atribuible.", "Cada derivación puede quedar identificada para que la relación comercial sea medible y transparente."),
        ],
    }


def _ensure_campaigns(state: Dict[str, Any]) -> int:
    campaigns = state.setdefault("acquisition_campaigns", [])
    existing = {str(x.get("audience") or ""): x for x in campaigns}
    created = 0
    for audience in ("buyer", "supplier", "partner"):
        if audience in existing:
            continue
        seed = _campaign_seed(audience)
        cid = "ACQ-" + audience.upper()
        variants = []
        for idx, (angle, headline, body) in enumerate(seed["angles"], 1):
            vid = f"{cid}-V{idx}"
            token = _token(vid)
            variants.append({
                "id": vid,
                "token": token,
                "angle": angle,
                "headline": headline,
                "body": body,
                "cta": seed["cta"],
                "tracking_path": f"/c/{token}",
                "status": "testing",
                "created_at": utcnow(),
            })
        campaigns.append({
            "id": cid,
            "audience": audience,
            "name": seed["name"],
            "goal": seed["goal"],
            "headline": seed["headline"],
            "body": seed["body"],
            "cta": seed["cta"],
            "landing_path": seed["landing"],
            "status": "active",
            "variants": variants,
            "champion_variant_id": variants[0]["id"],
            "created_at": utcnow(),
            "updated_at": utcnow(),
        })
        created += 1
    return created


def _performance(state: Dict[str, Any], campaign: Dict[str, Any], variant: Dict[str, Any]) -> Dict[str, Any]:
    events = state.get("acquisition_events", []) or []
    leads = state.get("acquisition_leads", []) or []
    clicks = sum(1 for x in events if x.get("event") == "click" and x.get("variant_id") == variant.get("id"))
    visits = sum(1 for x in events if x.get("event") == "landing_view" and x.get("variant_id") == variant.get("id"))
    submissions = sum(1 for x in leads if x.get("variant_id") == variant.get("id"))
    verified = 0
    lead_ids = {str(x.get("research_lead_id") or "") for x in leads if x.get("variant_id") == variant.get("id")}
    for account in state.get("candidate_accounts", []) or []:
        if str(account.get("source_lead_id") or "") in lead_ids and account.get("verified_company"):
            verified += 1
    conversion = submissions / max(1, clicks)

    # Revenue learning must reward commercial signal, not curiosity. A click is useful as
    # exposure evidence, but repeated zero-lead clicks become negative evidence.
    if submissions > 0:
        score = submissions * 35 + verified * 45 + conversion * 100 + min(clicks, 10) * 0.15
    else:
        score = min(clicks, 3) * 0.1 - max(0, clicks - 3) * 2.0

    return {
        "clicks": clicks,
        "landing_views": visits,
        "submissions": submissions,
        "verified_companies": verified,
        "click_to_lead_rate": round(conversion, 4),
        "score": round(score, 2),
        "zero_lead_negative_evidence": bool(clicks >= ZERO_LEAD_ROTATION_CLICKS and submissions == 0),
    }


def _choose_champion(campaign: Dict[str, Any]) -> Dict[str, Any] | None:
    variants = [x for x in campaign.get("variants", []) or [] if isinstance(x, dict)]
    if not variants:
        return None

    current_id = str(campaign.get("champion_variant_id") or "")
    current = next((x for x in variants if str(x.get("id") or "") == current_id), variants[0])
    converting = [x for x in variants if int((x.get("performance") or {}).get("submissions") or 0) > 0]
    if converting:
        return max(converting, key=lambda x: float((x.get("performance") or {}).get("score") or 0.0))

    current_perf = current.get("performance", {}) or {}
    if int(current_perf.get("clicks") or 0) < ZERO_LEAD_ROTATION_CLICKS:
        return current

    # No variant has converted yet and the current champion has enough negative evidence.
    # Explore the least-exposed non-exhausted alternative instead of rewarding more clicks.
    alternatives = [x for x in variants if str(x.get("id") or "") != str(current.get("id") or "") and x.get("status") != "needs_rotation"]
    if not alternatives:
        alternatives = [x for x in variants if str(x.get("id") or "") != str(current.get("id") or "")]
    if not alternatives:
        return current
    return min(alternatives, key=lambda x: int((x.get("performance") or {}).get("clicks") or 0))


def _channel_payloads(campaign: Dict[str, Any], variant: Dict[str, Any]) -> List[Dict[str, Any]]:
    tracking_path = str(variant["tracking_path"])
    link = PUBLIC_BASE_URL + tracking_path
    headline = variant["headline"]
    body = variant["body"]
    cta = variant["cta"]
    common = {"tracking_path": tracking_path, "tracking_url": link, "public_base_url": PUBLIC_BASE_URL}
    return [
        {**common, "channel": "linkedin_company", "copy": f"{headline}\n\n{body}\n\n{cta}: {link}", "requires_authorized_connector": True},
        {**common, "channel": "instagram", "copy": f"{headline}\n{body}\n\n{cta} → {link}\n#B2B #Compras #Proveedores", "requires_authorized_connector": True},
        {**common, "channel": "facebook", "copy": f"{headline}\n\n{body}\n\n{cta}: {link}", "requires_authorized_connector": True},
        {**common, "channel": "email_b2b", "subject": headline[:120], "copy": f"{body}\n\n{cta}: {link}", "requires_authorized_connector": False, "policy": "verified_business_contacts_only_opt_out_respected"},
        {**common, "channel": "owned_market", "copy": headline, "requires_authorized_connector": False, "policy": "owned_channel"},
        {**common, "channel": "paid_ads", "copy": f"{headline} {body}", "requires_authorized_connector": True, "requires_human_budget_approval": True},
    ]


def acquisition_campaign_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    created = _ensure_campaigns(state)
    queue = state.setdefault("acquisition_distribution_queue", [])
    queued_keys = {str(x.get("key") or "") for x in queue}
    total_clicks = total_leads = 0
    optimized = 0
    zero_lead_rotations = 0

    for campaign in state.get("acquisition_campaigns", []) or []:
        previous_champion_id = str(campaign.get("champion_variant_id") or "")
        for variant in campaign.get("variants", []) or []:
            perf = _performance(state, campaign, variant)
            variant["performance"] = perf
            total_clicks += int(perf["clicks"])
            total_leads += int(perf["submissions"])
            if perf["clicks"] >= ZERO_LEAD_ROTATION_CLICKS and perf["submissions"] == 0:
                variant["status"] = "needs_rotation"
            elif variant.get("status") == "needs_rotation" and perf["submissions"] > 0:
                variant["status"] = "testing"

        champion = _choose_champion(campaign)
        if champion:
            new_champion_id = str(champion.get("id") or "")
            if previous_champion_id != new_champion_id:
                campaign["champion_variant_id"] = new_champion_id
                optimized += 1
                previous = next((x for x in campaign.get("variants", []) or [] if str(x.get("id") or "") == previous_champion_id), {})
                if previous and int((previous.get("performance") or {}).get("submissions") or 0) == 0:
                    zero_lead_rotations += 1
            campaign["updated_at"] = utcnow()
            for payload in _channel_payloads(campaign, champion):
                key = f"{campaign['id']}|{champion['id']}|{payload['channel']}"
                if key in queued_keys:
                    existing = next((x for x in queue if str(x.get("key") or "") == key), None)
                    if existing:
                        existing["payload"] = payload
                        existing["updated_at"] = utcnow()
                    continue
                queue.append({
                    "key": key,
                    "campaign_id": campaign["id"],
                    "variant_id": champion["id"],
                    "audience": campaign["audience"],
                    "channel": payload["channel"],
                    "payload": payload,
                    "status": "ready_for_authorized_connector" if payload.get("requires_authorized_connector") else "ready_owned_or_existing_channel",
                    "created_at": utcnow(),
                    "updated_at": utcnow(),
                })
                queued_keys.add(key)

    state["acquisition_distribution_queue"] = queue[-300:]
    report = {
        "version": VERSION,
        "updated_at": utcnow(),
        "campaigns_active": len([x for x in state.get("acquisition_campaigns", []) or [] if x.get("status") == "active"]),
        "campaigns_created": created,
        "variants_total": sum(len(x.get("variants", []) or []) for x in state.get("acquisition_campaigns", []) or []),
        "clicks": total_clicks,
        "leads": total_leads,
        "click_to_lead_rate": round(total_leads / max(1, total_clicks), 4),
        "champion_changes": optimized,
        "zero_lead_rotations": zero_lead_rotations,
        "zero_lead_rotation_threshold_clicks": ZERO_LEAD_ROTATION_CLICKS,
        "distribution_queue": len(state.get("acquisition_distribution_queue", []) or []),
        "public_base_url": PUBLIC_BASE_URL,
        "paid_media_policy": "human_approval_required_for_budget_or_spend",
        "organic_policy": "autonomous_only_on_owned_or_pre-authorized_connectors",
        "learning_loop": "qualified_leads_and_verified_companies_over_raw_click_volume",
    }
    state["acquisition_engine"] = report
    return report
