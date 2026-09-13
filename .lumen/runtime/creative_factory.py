from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List


FORMATS = (
    {"id": "linkedin_landscape", "channel": "linkedin_company", "label": "LinkedIn", "width": 1200, "height": 627},
    {"id": "instagram_square", "channel": "instagram", "label": "Instagram post", "width": 1080, "height": 1080},
    {"id": "instagram_story", "channel": "instagram", "label": "Story / Reel cover", "width": 1080, "height": 1920},
    {"id": "facebook_feed", "channel": "facebook", "label": "Facebook", "width": 1200, "height": 1500},
)


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _clean(value: Any, limit: int = 1200) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _asset_id(campaign_id: str, variant_id: str, format_id: str) -> str:
    raw = f"{campaign_id}|{variant_id}|{format_id}"
    return "CRV-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14].upper()


def _audience_label(audience: str) -> str:
    return {"buyer": "COMPRADORES B2B", "supplier": "PROVEEDORES B2B", "partner": "TIENDAS PARTNER"}.get(audience, "RED LUMEN")


def _credibility_line(audience: str) -> str:
    if audience == "buyer":
        return "Investigación comercial + proveedores comparables + conversación guiada"
    if audience == "supplier":
        return "Demanda investigada + encaje comercial + oportunidades trazables"
    return "Derivación atribuible + venta directa de la tienda + comisión acordada"


def _visual_direction(audience: str, angle: str, fmt: Dict[str, Any]) -> Dict[str, Any]:
    portrait = int(fmt.get("height") or 0) > int(fmt.get("width") or 0)
    if audience == "buyer":
        motif = "Mapa visual de alternativas convergiendo hacia una decisión clara; estética tecnológica B2B, sin stock ficticio ni logos de terceros."
    elif audience == "supplier":
        motif = "Pipeline comercial limpio con una empresa/proveedor conectado a oportunidades calificadas; sensación de crecimiento profesional y control."
    else:
        motif = "Catálogo digital conectado a compradores mediante una ruta de atribución; la tienda permanece dueña del cobro y la entrega."
    return {
        "composition": "vertical_hook_first" if portrait else "split_value_proposition",
        "motif": motif,
        "tone": "premium, sobrio, tecnológico, confiable, B2B, alta legibilidad móvil",
        "hierarchy": ["audience_eyebrow", "headline", "single_value_proof", "cta"],
        "background": "dark_navy_depth",
        "accent": "electric_lime_and_ice_blue",
        "avoid": ["claims_no_verificados", "precios_no_confirmados", "stock_ficticio", "logos_ajenos_sin_permiso", "texto_excesivo"],
        "angle": angle,
    }


def _quality_score(asset: Dict[str, Any]) -> float:
    score = 100.0
    headline = str(asset.get("headline") or "")
    body = str(asset.get("body") or "")
    cta = str(asset.get("cta") or "")
    if len(headline) > 90:
        score -= 12
    if len(body) > 320:
        score -= 10
    if not cta:
        score -= 25
    if not asset.get("tracking_path"):
        score -= 20
    if not asset.get("credibility_line"):
        score -= 10
    return round(max(0.0, score), 1)


def _copy_variant(campaign: Dict[str, Any], variant: Dict[str, Any], fmt: Dict[str, Any]) -> Dict[str, Any]:
    audience = str(campaign.get("audience") or "")
    headline = _clean(variant.get("headline") or campaign.get("headline"), 120)
    body = _clean(variant.get("body") or campaign.get("body"), 420)
    cta = _clean(variant.get("cta") or campaign.get("cta"), 80)
    tracking_path = _clean(variant.get("tracking_path"), 180)
    if fmt.get("id") == "instagram_story":
        body = body[:180]
    return {
        "eyebrow": _audience_label(audience),
        "headline": headline,
        "body": body,
        "credibility_line": _credibility_line(audience),
        "cta": cta,
        "tracking_path": tracking_path,
        "alt_text": _clean(f"Pieza publicitaria LUMEN para {audience}: {headline}", 220),
    }


def creative_factory_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    campaigns = [x for x in state.get("acquisition_campaigns", []) or [] if x.get("status") == "active"]
    assets = state.setdefault("creative_assets", [])
    by_id = {str(x.get("id") or ""): x for x in assets}
    created = updated = 0

    for campaign in campaigns:
        variants = list(campaign.get("variants", []) or [])
        if not variants:
            continue
        champion_id = str(campaign.get("champion_variant_id") or variants[0].get("id") or "")
        for variant in variants:
            vid = str(variant.get("id") or "")
            # Keep challenger assets too, but prioritize the champion for distribution.
            for fmt in FORMATS:
                aid = _asset_id(str(campaign.get("id") or ""), vid, str(fmt["id"]))
                copy = _copy_variant(campaign, variant, fmt)
                row = {
                    "id": aid,
                    "campaign_id": campaign.get("id"),
                    "variant_id": vid,
                    "audience": campaign.get("audience"),
                    "angle": variant.get("angle"),
                    "format_id": fmt["id"],
                    "format_label": fmt["label"],
                    "channel": fmt["channel"],
                    "width": fmt["width"],
                    "height": fmt["height"],
                    **copy,
                    "visual_direction": _visual_direction(str(campaign.get("audience") or ""), str(variant.get("angle") or ""), fmt),
                    "is_champion": vid == champion_id,
                    "distribution_priority": "primary" if vid == champion_id else "experiment",
                    "status": "render_ready",
                    "render_backend": "lumen_html_preview",
                    "canva_handoff": {
                        "ready": True,
                        "design_type": "your_story" if fmt["id"] == "instagram_story" else "instagram_post" if fmt["id"] == "instagram_square" else "facebook_post",
                        "requires_connected_design_action": True,
                    },
                    "updated_at": utcnow(),
                }
                row["quality_score"] = _quality_score(row)
                existing = by_id.get(aid)
                if existing:
                    created_at = existing.get("created_at") or utcnow()
                    existing.update(row)
                    existing["created_at"] = created_at
                    updated += 1
                else:
                    row["created_at"] = utcnow()
                    assets.append(row)
                    by_id[aid] = row
                    created += 1

    assets.sort(key=lambda x: (not bool(x.get("is_champion")), -float(x.get("quality_score") or 0), str(x.get("id") or "")))
    state["creative_assets"] = assets[-500:]
    report = {
        "version": "1.0-creative-factory",
        "updated_at": utcnow(),
        "campaigns_processed": len(campaigns),
        "assets_total": len(state.get("creative_assets", []) or []),
        "assets_created": created,
        "assets_updated": updated,
        "champion_assets": sum(1 for x in state.get("creative_assets", []) or [] if x.get("is_champion")),
        "render_ready": sum(1 for x in state.get("creative_assets", []) or [] if x.get("status") == "render_ready"),
        "quality_avg": round(sum(float(x.get("quality_score") or 0) for x in state.get("creative_assets", []) or []) / max(1, len(state.get("creative_assets", []) or [])), 1),
        "policy": "original_lumen_creative_no_unverified_claims_no_external_logo_reuse",
    }
    state["creative_factory"] = report
    return report
