from __future__ import annotations

"""LUMEN Instagram Pro Editorial v1.

Creates one high-quality weekday editorial post, adapts the content strategy to
conversion signals, keeps a bounded non-repetition memory, upgrades Instagram
captions and renders 4:5 professional visual assets. Publishing authority is not
changed: instagram_publish_control still requires one explicit human approval
for every immutable post.
"""

import hashlib
import math
import textwrap
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Tuple
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw

import acquisition_campaigns
import instagram_publish_control as ipc
import social_distribution


VERSION = "1.0-instagram-pro-editorial"
RENDER_VERSION = "2.0-pro-4x5"
AR_TZ = ZoneInfo("America/Argentina/Buenos_Aires")
MAX_HISTORY = 120
QA_MIN_SCORE = 90

BG_TOP = (5, 16, 22)
BG_BOTTOM = (10, 31, 39)
PANEL = (14, 36, 44)
PANEL_2 = (20, 48, 57)
BORDER = (42, 77, 88)
TEXT = (240, 247, 249)
MUTED = (166, 190, 199)
ACCENT = (215, 255, 100)
INK = (7, 16, 24)

_ORIGINAL_ACQUISITION_TICK = acquisition_campaigns.acquisition_campaign_tick
_ORIGINAL_TEXT = social_distribution._text
_ORIGINAL_FINGERPRINT = ipc._content_fingerprint
_ORIGINAL_ENSURE_MEDIA = ipc._ensure_media_url
_ORIGINAL_RENDER = ipc._render_job_jpeg


def _now_local() -> datetime:
    return datetime.now(timezone.utc).astimezone(AR_TZ)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: Any, limit: int = 1200) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _history(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = state.get("instagram_editorial_history")
    if not isinstance(rows, list):
        rows = []
        state["instagram_editorial_history"] = rows
    return rows


def _campaign_for(state: Dict[str, Any], audience: str) -> Dict[str, Any]:
    fallback = "buyer" if audience in {"buyer", "b2b", "education"} else audience
    return next(
        (
            row for row in state.get("acquisition_campaigns", []) or []
            if str(row.get("audience") or "") == fallback
        ),
        {},
    )


def _campaign_signal(state: Dict[str, Any], audience: str) -> Dict[str, int]:
    campaign = _campaign_for(state, audience)
    clicks = leads = 0
    for variant in campaign.get("variants", []) or []:
        perf = variant.get("performance", {}) or {}
        clicks += int(perf.get("clicks") or 0)
        leads += int(perf.get("submissions") or 0)
    return {"clicks": clicks, "leads": leads}


def _strategy_for(state: Dict[str, Any], audience: str) -> str:
    signal = _campaign_signal(state, audience)
    if signal["leads"] > 0:
        return "reinforce_verified_winner"
    if signal["clicks"] >= 8 and signal["leads"] == 0:
        return "credibility_before_conversion"
    if signal["clicks"] == 0:
        return "clarity_and_relevance"
    return "balanced_growth"


def _weekday_brief(weekday: int, strategy: str) -> Dict[str, Any]:
    # Monday-Friday: buyer, authority, supplier, education, partner.
    briefs: Dict[int, Dict[str, Any]] = {
        0: {
            "audience": "buyer",
            "pillar": "buyer_value",
            "goal": "qualified_buyer_conversation",
            "style": "procurement_radar",
            "label": "PARA COMPRADORES",
            "headlines": [
                "Encontrá proveedores sin perder horas comparando a ciegas.",
                "Una compra B2B empieza mejor con alternativas comparables.",
                "Menos búsqueda. Más criterio para comprar B2B.",
            ],
            "subtitle": "LUMEN investiga el mercado, ordena alternativas y ayuda a convertir una necesidad concreta en opciones comparables.",
            "cta": "CONTANOS QUÉ NECESITÁS",
            "caption": (
                "Buscar proveedores no debería significar abrir veinte pestañas y terminar con más dudas.\n\n"
                "LUMEN investiga mercado, organiza alternativas y concentra la evidencia útil para que una necesidad B2B avance con más claridad.\n\n"
                "¿Estás buscando un proveedor o una alternativa concreta? Escribinos por DM."
            ),
            "hashtags": ["#LUMENB2B", "#ComprasB2B", "#Proveedores", "#ComprasIndustriales", "#Abastecimiento", "#InteligenciaComercial", "#Industria"],
        },
        1: {
            "audience": "b2b",
            "pillar": "authority",
            "goal": "brand_trust",
            "style": "evidence_grid",
            "label": "INTELIGENCIA COMERCIAL",
            "headlines": [
                "Decisiones B2B con evidencia, no con ruido.",
                "Investigar mejor también es vender y comprar mejor.",
                "La oportunidad importa. La evidencia que la sostiene, más.",
            ],
            "subtitle": "Señales, fuentes y contexto comercial reunidos para transformar información dispersa en decisiones más claras.",
            "cta": "CONOCÉ CÓMO TRABAJA LUMEN",
            "caption": (
                "En B2B, encontrar información es fácil. Separar una señal útil del ruido es lo difícil.\n\n"
                "LUMEN cruza fuentes públicas, organiza evidencia y prioriza oportunidades con trazabilidad antes de convertirlas en trabajo comercial.\n\n"
                "Menos acumulación de datos. Más criterio para decidir."
            ),
            "hashtags": ["#LUMENB2B", "#InteligenciaComercial", "#NegociosB2B", "#VentasB2B", "#Procurement", "#DesarrolloComercial", "#DatosParaDecidir"],
        },
        2: {
            "audience": "supplier",
            "pillar": "supplier_value",
            "goal": "qualified_supplier_conversation",
            "style": "matching_network",
            "label": "PARA PROVEEDORES",
            "headlines": [
                "Tu catálogo puede estar más cerca de una necesidad real.",
                "Más encaje comercial. Menos prospección sin rumbo.",
                "Que tu oferta aparezca donde realmente puede tener sentido.",
            ],
            "subtitle": "LUMEN investiga demanda, organiza requerimientos y busca coincidencias donde la oferta de un proveedor puede encajar.",
            "cta": "MOSTRANOS QUÉ VENDÉS",
            "caption": (
                "Vender B2B no es solamente contactar más empresas: es encontrar mejores coincidencias.\n\n"
                "LUMEN investiga señales de demanda y organiza oportunidades para acercar oferta y necesidad con más contexto comercial.\n\n"
                "¿Tu empresa vende productos o servicios B2B? Escribinos por DM y contanos qué ofrecés."
            ),
            "hashtags": ["#LUMENB2B", "#Proveedores", "#VentasB2B", "#OportunidadesComerciales", "#DesarrolloComercial", "#Industria", "#ProspeccionB2B"],
        },
        3: {
            "audience": "education",
            "pillar": "education",
            "goal": "useful_expertise",
            "style": "education_steps",
            "label": "CRITERIO B2B",
            "headlines": [
                "3 cosas que una compra B2B debería comparar antes de decidir.",
                "Comparar precio no alcanza: mirá estas 3 variables.",
                "Una buena comparación B2B necesita más que una cotización.",
            ],
            "subtitle": "Especificación técnica. Condiciones comerciales. Capacidad de entrega. Tres filtros simples para comparar con contexto.",
            "cta": "GUARDALO PARA TU PRÓXIMA COMPRA",
            "caption": (
                "Una cotización más barata no siempre es una mejor opción.\n\n"
                "Antes de decidir, compará al menos tres cosas:\n"
                "1. Especificación y equivalencias reales.\n"
                "2. Condiciones comerciales y documentación.\n"
                "3. Plazo, ubicación y capacidad de entrega.\n\n"
                "Ese orden evita comparar ofertas que en realidad no son equivalentes."
            ),
            "hashtags": ["#LUMENB2B", "#ComprasIndustriales", "#Procurement", "#Proveedores", "#GestionDeCompras", "#Industria", "#InteligenciaComercial"],
        },
        4: {
            "audience": "partner",
            "pillar": "partner_growth",
            "goal": "qualified_partner_conversation",
            "style": "partner_channel",
            "label": "PARA TIENDAS Y DISTRIBUIDORES",
            "headlines": [
                "Tu catálogo puede convertirse en un nuevo canal comercial B2B.",
                "Tu tienda ya tiene productos. El desafío es encontrar demanda compatible.",
                "Más alcance comercial sin perder el control de tu venta.",
            ],
            "subtitle": "LUMEN puede estudiar catálogos públicos, detectar encajes y preparar oportunidades sin intervenir en el cobro ni en la entrega.",
            "cta": "SUMÁ TU CATÁLOGO A LA CONVERSACIÓN",
            "caption": (
                "Un buen catálogo puede tener oportunidades fuera del tráfico que ya recibe una tienda.\n\n"
                "LUMEN investiga productos públicos, señales de demanda y posibles encajes comerciales para abrir conversaciones B2B con trazabilidad.\n\n"
                "Si sos distribuidor, mayorista o tienda especializada, escribinos por DM."
            ),
            "hashtags": ["#LUMENB2B", "#Distribuidores", "#Mayoristas", "#EcommerceB2B", "#CanalComercial", "#VentasB2B", "#OportunidadesComerciales"],
        },
    }
    brief = dict(briefs.get(weekday) or {})
    if not brief:
        return {}
    # Conversion signal changes the editorial emphasis without inventing a new claim.
    if strategy == "credibility_before_conversion" and brief["pillar"] in {"buyer_value", "supplier_value", "partner_growth"}:
        brief["label"] = "EVIDENCIA ANTES DE CONVERTIR"
        brief["subtitle"] = "Antes de una conversación comercial, LUMEN prioriza contexto, trazabilidad y encaje para reducir ruido y mejorar la calidad de la oportunidad."
    return brief


def _choose_headline(state: Dict[str, Any], slot: str, brief: Dict[str, Any], strategy: str) -> str:
    options = list(brief.get("headlines") or [])
    recent = {_clean(x.get("headline"), 180).lower() for x in _history(state)[-10:] if isinstance(x, dict)}
    candidates = [x for x in options if _clean(x, 180).lower() not in recent] or options
    if not candidates:
        return "Inteligencia comercial B2B con más criterio."
    idx = int(hashlib.sha1(f"{slot}|{strategy}|{brief.get('pillar')}".encode("utf-8")).hexdigest()[:8], 16) % len(candidates)
    return candidates[idx]


def _qa_piece(headline: str, subtitle: str, caption: str, hashtags: List[str], recent: Iterable[Dict[str, Any]]) -> Tuple[int, List[str]]:
    score = 100
    reasons: List[str] = []
    joined = " ".join([headline, subtitle, caption, " ".join(hashtags)])
    lower = joined.lower()
    if "�" in joined:
        score -= 70
        reasons.append("replacement_character")
    if not 28 <= len(headline) <= 95:
        score -= 10
        reasons.append("headline_length")
    if not 70 <= len(subtitle) <= 260:
        score -= 8
        reasons.append("subtitle_length")
    if not 140 <= len(caption) <= 1100:
        score -= 8
        reasons.append("caption_length")
    if not 5 <= len(hashtags) <= 9 or len(set(hashtags)) != len(hashtags):
        score -= 10
        reasons.append("hashtag_quality")
    forbidden = ["garantizado", "éxito asegurado", "100% seguro", "sin riesgo", "el mejor del mercado"]
    if any(token in lower for token in forbidden):
        score -= 30
        reasons.append("unsupported_claim")
    recent_headlines = {_clean(x.get("headline"), 180).lower() for x in list(recent)[-10:] if isinstance(x, dict)}
    if _clean(headline, 180).lower() in recent_headlines:
        score -= 18
        reasons.append("repeated_headline")
    return max(0, score), reasons


def _job_id(slot: str, pillar: str) -> str:
    token = hashlib.sha1(f"LUMEN-IGPRO|{slot}|{pillar}".encode("utf-8")).hexdigest()[:12].upper()
    return f"IGPRO-{token}"


def _editorial_job_for_today(state: Dict[str, Any]) -> Dict[str, Any]:
    now = _now_local()
    if now.weekday() >= 5:
        return {"status": "weekend_no_new_post", "slot": now.date().isoformat()}

    slot = now.date().isoformat()
    weekday = now.weekday()
    base_audience = {0: "buyer", 1: "b2b", 2: "supplier", 3: "education", 4: "partner"}[weekday]
    strategy = _strategy_for(state, base_audience)
    brief = _weekday_brief(weekday, strategy)
    if not brief:
        return {"status": "no_brief", "slot": slot}

    jid = _job_id(slot, str(brief["pillar"]))
    existing = next((x for x in state.get("distribution_operator_jobs", []) or [] if str(x.get("id") or "") == jid), None)
    if existing:
        return {
            "status": "already_prepared",
            "slot": slot,
            "job_id": jid,
            "pillar": existing.get("content_pillar"),
            "strategy": existing.get("editorial_strategy"),
            "qa_score": existing.get("editorial_qa_score"),
        }

    headline = _choose_headline(state, slot, brief, strategy)
    subtitle = str(brief["subtitle"])
    hashtags = list(brief["hashtags"])
    caption = str(brief["caption"]).rstrip() + "\n\n" + " ".join(hashtags)
    score, reasons = _qa_piece(headline, subtitle, caption, hashtags, _history(state))
    if score < QA_MIN_SCORE:
        state["instagram_editorial_last_block"] = {
            "slot": slot,
            "score": score,
            "reasons": reasons,
            "headline": headline,
            "blocked_at": _utcnow(),
        }
        return {"status": "blocked_by_quality", "slot": slot, "qa_score": score, "qa_reasons": reasons}

    campaign = _campaign_for(state, str(brief["audience"]))
    champion_id = str(campaign.get("champion_variant_id") or "")
    variant = next((x for x in campaign.get("variants", []) or [] if str(x.get("id") or "") == champion_id), {})
    tracking_path = str(variant.get("tracking_path") or campaign.get("landing_path") or "")
    tracking_url = ""
    if tracking_path.startswith("/c/"):
        tracking_url = acquisition_campaigns.PUBLIC_BASE_URL + tracking_path

    job = {
        "id": jid,
        "queue_key": f"IGPRO|{slot}|{brief['pillar']}",
        "campaign_id": str(campaign.get("id") or "IG-PRO"),
        "variant_id": champion_id or f"IGPRO-{weekday+1}",
        "audience": brief["audience"],
        "channel": "instagram",
        "status": "awaiting_human_approval",
        "created_at": _utcnow(),
        "updated_at": _utcnow(),
        "attempts": 0,
        "copy": caption,
        "caption": caption,
        "headline": headline,
        "visual_subtitle": subtitle,
        "cta": brief["cta"],
        "hashtags": hashtags,
        "content_pillar": brief["pillar"],
        "content_goal": brief["goal"],
        "creative_style": brief["style"],
        "creative_label": brief["label"],
        "editorial_slot": slot,
        "editorial_strategy": strategy,
        "editorial_qa_score": score,
        "editorial_qa_reasons": reasons,
        "editorial_pro_v1": True,
        "format": "instagram_feed_4x5",
        "hide_tracking_url_in_caption": True,
        "tracking_path": tracking_path,
        "tracking_url": tracking_url,
        "requires_connector": True,
        "requires_budget_approval": False,
        "authority": "prepare_autonomously_publish_only_after_explicit_human_approval",
    }
    state.setdefault("distribution_operator_jobs", []).append(job)
    state["distribution_operator_jobs"] = (state.get("distribution_operator_jobs", []) or [])[-500:]
    _history(state).append({
        "slot": slot,
        "job_id": jid,
        "pillar": brief["pillar"],
        "audience": brief["audience"],
        "headline": headline,
        "strategy": strategy,
        "qa_score": score,
        "created_at": _utcnow(),
    })
    state["instagram_editorial_history"] = _history(state)[-MAX_HISTORY:]
    return {"status": "prepared", "slot": slot, "job_id": jid, "pillar": brief["pillar"], "strategy": strategy, "qa_score": score}


def _learning_snapshot(state: Dict[str, Any]) -> Dict[str, Any]:
    pro_jobs = [x for x in state.get("distribution_operator_jobs", []) or [] if isinstance(x, dict) and x.get("editorial_pro_v1")]
    receipts = state.get("distribution_receipts", []) or []
    receipt_ids = {str(x.get("distribution_job_id") or "") for x in receipts if x.get("external_post_id") or x.get("external_url")}
    by_pillar: Dict[str, Dict[str, int]] = {}
    for job in pro_jobs:
        pillar = str(job.get("content_pillar") or "unknown")
        row = by_pillar.setdefault(pillar, {"prepared": 0, "published": 0})
        row["prepared"] += 1
        if str(job.get("id") or "") in receipt_ids:
            row["published"] += 1
    campaign_signals = {
        audience: _campaign_signal(state, audience)
        for audience in ("buyer", "supplier", "partner")
    }
    return {
        "prepared_total": len(pro_jobs),
        "published_total": sum(1 for x in pro_jobs if str(x.get("id") or "") in receipt_ids),
        "by_pillar": by_pillar,
        "campaign_conversion_signals": campaign_signals,
        "learning_scope": "campaign_clicks_and_leads_plus_editorial_publish_history; no invented engagement metrics",
    }


def instagram_editorial_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    result = _editorial_job_for_today(state)
    learning = _learning_snapshot(state)
    report = {
        "version": VERSION,
        "status": "active",
        "calendar": "one_professional_weekday_post",
        "format": "4:5",
        "human_approval_required": True,
        "quality_gate_min": QA_MIN_SCORE,
        "today": result,
        "learning": learning,
        "updated_at": _utcnow(),
    }
    state["instagram_editorial_system"] = report
    return report


def _acquisition_with_editorial(state: Dict[str, Any]) -> Dict[str, Any]:
    report = dict(_ORIGINAL_ACQUISITION_TICK(state) or {})
    report["instagram_editorial"] = instagram_editorial_tick(state)
    return report


acquisition_campaigns.acquisition_campaign_tick = _acquisition_with_editorial


def _professional_text(job: Dict[str, Any]) -> str:
    if str(job.get("channel") or "") != "instagram" or not job.get("editorial_pro_v1"):
        return _ORIGINAL_TEXT(job)
    raw = str(job.get("caption") or job.get("copy") or "").replace("\r\n", "\n").strip()
    # Preserve intentional Instagram paragraph breaks while removing trailing whitespace/noise.
    lines = [line.rstrip() for line in raw.split("\n")]
    out: List[str] = []
    blank = False
    for line in lines:
        if not line.strip():
            if not blank and out:
                out.append("")
            blank = True
        else:
            out.append(line.strip())
            blank = False
    text = "\n".join(out).strip()
    return text[:2200]


social_distribution._text = _professional_text
ipc.social_distribution._text = _professional_text


def _pro_fingerprint(job: Dict[str, Any]) -> str:
    base = _ORIGINAL_FINGERPRINT(job)
    extra = "|".join([
        RENDER_VERSION,
        str(job.get("headline") or ""),
        str(job.get("visual_subtitle") or ""),
        str(job.get("cta") or ""),
        str(job.get("content_pillar") or ""),
        str(job.get("creative_style") or ""),
        str(job.get("editorial_slot") or ""),
        str(job.get("editorial_qa_score") or ""),
    ])
    return hashlib.sha256(f"{base}|{extra}".encode("utf-8")).hexdigest()


ipc._content_fingerprint = _pro_fingerprint


def _ensure_pro_media(job: Dict[str, Any]) -> bool:
    if str(job.get("channel") or "") != "instagram":
        return False
    # Preserve a deliberate external creative asset. Generated LUMEN media always gets a fresh
    # render-version fingerprint so an old cached preview cannot be published after a design change.
    external = str(job.get("creative_asset_url") or "").strip()
    source = str(job.get("media_source") or "")
    if external and source != "lumen_generated_public_jpeg":
        return False
    desired = ipc._media_url(job)
    if str(job.get("image_url") or "") == desired and source == "lumen_generated_public_jpeg":
        return False
    job["image_url"] = desired
    job["media_source"] = "lumen_generated_public_jpeg"
    job["media_prepared_at"] = _utcnow()
    return True


ipc._ensure_media_url = _ensure_pro_media


def _gradient_image(width: int, height: int) -> Image.Image:
    image = Image.new("RGB", (width, height), BG_TOP)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        t = y / max(1, height - 1)
        color = tuple(int(BG_TOP[i] * (1 - t) + BG_BOTTOM[i] * t) for i in range(3))
        draw.line((0, y, width, y), fill=color)
    return image


def _wrap_pixels(draw: ImageDraw.ImageDraw, text: str, font: Any, max_width: int, max_lines: int) -> List[str]:
    words = _clean(text, 600).split()
    lines: List[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        width = draw.textbbox((0, 0), trial, font=font)[2]
        if width <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
            if len(lines) >= max_lines:
                break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and len(" ".join(lines)) < len(" ".join(words)):
        last = lines[-1]
        while last and draw.textbbox((0, 0), last + "…", font=font)[2] > max_width:
            last = last[:-1].rstrip()
        lines[-1] = last + "…"
    return lines


def _pill(draw: ImageDraw.ImageDraw, xy: Tuple[int, int, int, int], text: str, *, accent: bool = False, font_size: int = 24) -> None:
    fill = ACCENT if accent else PANEL_2
    color = INK if accent else MUTED
    draw.rounded_rectangle(xy, radius=28, fill=fill, outline=ACCENT if not accent else fill, width=2)
    font = ipc._font(font_size, True)
    bbox = draw.textbbox((0, 0), text, font=font)
    x = xy[0] + (xy[2] - xy[0] - (bbox[2] - bbox[0])) // 2
    y = xy[1] + (xy[3] - xy[1] - (bbox[3] - bbox[1])) // 2 - 2
    draw.text((x, y), text, font=font, fill=color)


def _draw_network(draw: ImageDraw.ImageDraw, center: Tuple[int, int], nodes: List[Tuple[int, int, str]]) -> None:
    cx, cy = center
    for x, y, label in nodes:
        draw.line((cx, cy, x, y), fill=BORDER, width=4)
        draw.ellipse((x - 48, y - 48, x + 48, y + 48), fill=PANEL_2, outline=ACCENT, width=3)
        short = label[:2].upper()
        f = ipc._font(22, True)
        box = draw.textbbox((0, 0), short, font=f)
        draw.text((x - (box[2]-box[0])//2, y - 14), short, font=f, fill=TEXT)
    draw.ellipse((cx - 76, cy - 76, cx + 76, cy + 76), fill=ACCENT)
    f = ipc._font(24, True)
    box = draw.textbbox((0, 0), "LUMEN", font=f)
    draw.text((cx - (box[2]-box[0])//2, cy - 15), "LUMEN", font=f, fill=INK)


def _draw_visual(draw: ImageDraw.ImageDraw, style: str, box: Tuple[int, int, int, int]) -> None:
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=38, fill=PANEL, outline=BORDER, width=2)
    if style == "procurement_radar":
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        for r in (90, 150, 210):
            draw.ellipse((cx-r, cy-r, cx+r, cy+r), outline=BORDER, width=2)
        _draw_network(draw, (cx, cy), [(cx-180, cy-80, "Proveedor"), (cx+170, cy-105, "Evidencia"), (cx+130, cy+150, "Opción")])
    elif style == "matching_network":
        cy = (y1 + y2) // 2
        _draw_network(draw, ((x1+x2)//2, cy), [(x1+145, cy, "Demanda"), (x2-145, cy, "Oferta"), ((x1+x2)//2, cy+155, "Encaje")])
    elif style == "education_steps":
        labels = [("01", "ESPECIFICACIÓN"), ("02", "CONDICIONES"), ("03", "ENTREGA")]
        row_h = 82
        start = y1 + 38
        for idx, (num, label) in enumerate(labels):
            yy = start + idx * 98
            draw.rounded_rectangle((x1+42, yy, x2-42, yy+row_h), radius=22, fill=PANEL_2, outline=BORDER, width=2)
            draw.ellipse((x1+62, yy+17, x1+110, yy+65), fill=ACCENT)
            draw.text((x1+73, yy+28), num, font=ipc._font(18, True), fill=INK)
            draw.text((x1+136, yy+25), label, font=ipc._font(28, True), fill=TEXT)
    elif style == "partner_channel":
        cy = (y1 + y2) // 2
        for x, title in [(x1+70, "CATÁLOGO"), ((x1+x2)//2-90, "LUMEN"), (x2-250, "DEMANDA")]:
            draw.rounded_rectangle((x, cy-70, x+180, cy+70), radius=26, fill=ACCENT if title == "LUMEN" else PANEL_2, outline=ACCENT if title != "LUMEN" else ACCENT, width=2)
            f = ipc._font(22, True)
            b = draw.textbbox((0,0), title, font=f)
            draw.text((x+90-(b[2]-b[0])//2, cy-14), title, font=f, fill=INK if title == "LUMEN" else TEXT)
        draw.line((x1+250, cy, (x1+x2)//2-100, cy), fill=ACCENT, width=5)
        draw.line(((x1+x2)//2+90, cy, x2-260, cy), fill=ACCENT, width=5)
    else:  # evidence_grid and safe fallback
        cards = [("01", "SEÑAL"), ("02", "FUENTE"), ("03", "DECISIÓN")]
        card_w = (x2 - x1 - 120) // 3
        for idx, (num, label) in enumerate(cards):
            xx = x1 + 30 + idx * (card_w + 30)
            draw.rounded_rectangle((xx, y1+54, xx+card_w, y2-54), radius=26, fill=PANEL_2, outline=BORDER, width=2)
            draw.text((xx+26, y1+82), num, font=ipc._font(22, True), fill=ACCENT)
            draw.text((xx+26, y1+132), label, font=ipc._font(24, True), fill=TEXT)
            for j, width_ratio in enumerate((0.78, 0.58, 0.68)):
                yy = y1 + 194 + j * 32
                draw.rounded_rectangle((xx+26, yy, xx+26+int((card_w-52)*width_ratio), yy+10), radius=5, fill=MUTED)


def _fallback_metadata(job: Dict[str, Any]) -> Dict[str, str]:
    audience = str(job.get("audience") or "b2b").lower()
    raw = " ".join(str(job.get("copy") or "").split())
    headline = str(job.get("headline") or (raw.split(". ", 1)[0] if raw else "Inteligencia comercial B2B con más criterio."))[:120]
    if audience == "supplier":
        style, label, cta = "matching_network", "PARA PROVEEDORES", "HABLEMOS POR DM"
    elif audience == "partner":
        style, label, cta = "partner_channel", "PARA TIENDAS Y DISTRIBUIDORES", "HABLEMOS POR DM"
    elif audience in {"buyer", "education"}:
        style, label, cta = "procurement_radar", "PARA COMPRADORES", "CONOCÉ LUMEN"
    else:
        style, label, cta = "evidence_grid", "INTELIGENCIA COMERCIAL", "CONOCÉ LUMEN"
    return {
        "headline": headline,
        "subtitle": str(job.get("visual_subtitle") or "LUMEN investiga, organiza evidencia y conecta oportunidades comerciales con más contexto."),
        "style": str(job.get("creative_style") or style),
        "label": str(job.get("creative_label") or label),
        "cta": str(job.get("cta") or cta),
    }


def _render_pro(job: Dict[str, Any]) -> bytes:
    width, height = 1080, 1350
    image = _gradient_image(width, height)
    draw = ImageDraw.Draw(image)
    # Subtle grid makes the design feel technical without becoming visually noisy.
    for x in range(0, width, 90):
        draw.line((x, 0, x, height), fill=(10, 31, 38), width=1)
    for y in range(0, height, 90):
        draw.line((0, y, width, y), fill=(10, 31, 38), width=1)

    draw.rounded_rectangle((46, 46, 1034, 1304), radius=52, fill=(7, 23, 30), outline=BORDER, width=2)
    meta = _fallback_metadata(job)

    # Brand signature.
    draw.ellipse((84, 82, 112, 110), fill=ACCENT)
    draw.text((132, 76), "LUMEN B2B", font=ipc._font(34, True), fill=TEXT)
    draw.text((784, 82), "INTELIGENCIA COMERCIAL", font=ipc._font(16, True), fill=MUTED)

    label = _clean(meta["label"], 44).upper()
    label_font = ipc._font(18, True)
    label_w = min(440, draw.textbbox((0, 0), label, font=label_font)[2] + 56)
    _pill(draw, (84, 150, 84+label_w, 208), label, accent=False, font_size=18)

    headline = _clean(meta["headline"], 130)
    title_font = ipc._font(58, True)
    lines = _wrap_pixels(draw, headline, title_font, 880, 4)
    y = 254
    for line in lines:
        draw.text((84, y), line, font=title_font, fill=TEXT)
        y += 72

    subtitle_font = ipc._font(27, False)
    subtitle_lines = _wrap_pixels(draw, _clean(meta["subtitle"], 320), subtitle_font, 875, 3)
    y = max(y + 18, 520)
    for line in subtitle_lines:
        draw.text((84, y), line, font=subtitle_font, fill=MUTED)
        y += 40

    _draw_visual(draw, meta["style"], (84, 710, 996, 1110))

    cta = _clean(meta["cta"], 54).upper()
    cta_font = ipc._font(20, True)
    cta_w = min(720, max(300, draw.textbbox((0, 0), cta, font=cta_font)[2] + 80))
    _pill(draw, (84, 1160, 84+cta_w, 1228), cta, accent=True, font_size=20)
    draw.text((84, 1260), "lumen.b2b  ·  compradores  ·  proveedores  ·  oportunidades", font=ipc._font(18, False), fill=MUTED)

    import io
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=94, optimize=True, progressive=True)
    return output.getvalue()


ipc._render_job_jpeg = _render_pro

print({
    "instagram_pro_editorial": {
        "version": VERSION,
        "status": "active",
        "format": "4:5",
        "weekday_posts": 5,
        "content_pillars": ["buyer_value", "authority", "supplier_value", "education", "partner_growth"],
        "qa_min_score": QA_MIN_SCORE,
        "caption_paragraphs_preserved": True,
        "dynamic_hashtags": True,
        "adaptive_strategy": True,
        "human_approval_required": True,
        "autonomous_publish": False,
    }
}, flush=True)
