from __future__ import annotations

"""Prepare an on-demand Instagram theme inside LUMEN Zero.

This module writes a normal Instagram job into canonical D1-backed LUMEN state,
renders a public 4:5 JPEG into .lumen/public/instagram, and exports the exact job
to the existing Cloudflare/D1 approval console.

It never creates an approval, never publishes, never buys media, and never widens
the existing human gate.
"""

import hashlib
import os
import re
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

VERSION = "1.0-zero-instagram-thematic"
QA_MIN_SCORE = 90
PUBLIC_BASE_URL = (os.getenv("LUMEN_PUBLIC_BASE_URL") or "https://lumen-zero-public.lumen-b2b.workers.dev").rstrip("/")
OUT_DIR = Path(__file__).resolve().parent.parent / "public" / "instagram"

THEMES: Dict[str, Dict[str, Any]] = {
    "travel": {
        "label": "VIAJES / TURISMO",
        "audience": "travel_b2b",
        "pillar": "travel_opportunities",
        "goal": "qualified_travel_business_conversation",
        "headline": "El sector viajes también está lleno de oportunidades comerciales.",
        "subtitle": "Agencias, alojamientos, experiencias, traslados y operadores generan conexiones comerciales que pueden investigarse con más contexto.",
        "cta": "HABLEMOS POR DM",
        "caption": (
            "El mundo del turismo mueve mucho más que reservas: conecta agencias, alojamientos, "
            "experiencias, traslados, operadores y proveedores especializados.\n\n"
            "LUMEN investiga señales de mercado, detecta oportunidades comerciales y ayuda a ordenar "
            "alternativas dentro del ecosistema de viajes.\n\n"
            "Si trabajás en turismo o tenés un servicio vinculado al sector, escribinos por DM."
        ),
        "hashtags": [
            "#LUMENB2B", "#Turismo", "#Viajes", "#TravelBusiness",
            "#AgenciasDeViajes", "#OportunidadesComerciales", "#InteligenciaComercial",
        ],
        "visual": "travel_network",
    },
    "technology": {
        "label": "TECNOLOGÍA",
        "audience": "technology_b2b",
        "pillar": "technology_opportunities",
        "goal": "qualified_technology_business_conversation",
        "headline": "La tecnología abre oportunidades cuando la señal correcta encuentra demanda.",
        "subtitle": "LUMEN organiza señales, proveedores y necesidades para detectar encajes comerciales con más contexto.",
        "cta": "CONTANOS QUÉ OFRECÉS",
        "caption": (
            "Tecnología B2B no es solo producto: también es integración, servicio, distribución y demanda.\n\n"
            "LUMEN investiga señales públicas y organiza oportunidades para acercar oferta y necesidad con trazabilidad.\n\n"
            "Si tu empresa vende tecnología o servicios tecnológicos, escribinos por DM."
        ),
        "hashtags": ["#LUMENB2B", "#Tecnologia", "#NegociosB2B", "#Innovacion", "#VentasB2B", "#OportunidadesComerciales"],
        "visual": "network",
    },
    "construction": {
        "label": "CONSTRUCCIÓN",
        "audience": "construction_b2b",
        "pillar": "construction_opportunities",
        "goal": "qualified_construction_business_conversation",
        "headline": "Construcción también es una red de demanda, proveedores y oportunidades.",
        "subtitle": "Materiales, servicios, contratistas y abastecimiento pueden compararse y conectarse con mejor evidencia.",
        "cta": "HABLEMOS POR DM",
        "caption": (
            "Cada proyecto de construcción activa necesidades de materiales, servicios, logística y proveedores.\n\n"
            "LUMEN puede investigar el mercado, ordenar alternativas y detectar oportunidades comerciales alrededor de esas necesidades.\n\n"
            "Si trabajás en construcción o abastecimiento, escribinos por DM."
        ),
        "hashtags": ["#LUMENB2B", "#Construccion", "#Proveedores", "#Abastecimiento", "#NegociosB2B", "#OportunidadesComerciales"],
        "visual": "network",
    },
    "industry": {
        "label": "INDUSTRIA",
        "audience": "industry_b2b",
        "pillar": "industry_opportunities",
        "goal": "qualified_industry_business_conversation",
        "headline": "En industria, una necesidad concreta puede convertirse en una oportunidad comercial.",
        "subtitle": "Equipos, repuestos, servicios y proveedores: LUMEN organiza evidencia para encontrar mejores encajes B2B.",
        "cta": "CONTANOS QUÉ NECESITÁS",
        "caption": (
            "En industria, cada requerimiento puede abrir una cadena de alternativas, proveedores y decisiones.\n\n"
            "LUMEN investiga señales, compara opciones y organiza evidencia para convertir necesidades concretas en oportunidades B2B.\n\n"
            "Si comprás o vendés para industria, escribinos por DM."
        ),
        "hashtags": ["#LUMENB2B", "#Industria", "#ComprasIndustriales", "#Proveedores", "#Sourcing", "#OportunidadesComerciales"],
        "visual": "network",
    },
    "import_export": {
        "label": "COMERCIO EXTERIOR",
        "audience": "trade_b2b",
        "pillar": "trade_opportunities",
        "goal": "qualified_trade_business_conversation",
        "headline": "Importar y exportar empieza por encontrar el encaje comercial correcto.",
        "subtitle": "Mercados, compradores, distribuidores y proveedores pueden investigarse antes de convertir una señal en una conversación.",
        "cta": "EXPLORÁ TU OPORTUNIDAD",
        "caption": (
            "Comercio exterior empieza mucho antes de una operación: empieza con mercado, demanda, proveedores y evidencia.\n\n"
            "LUMEN investiga señales públicas y organiza oportunidades para explorar encajes comerciales internacionales con más contexto.\n\n"
            "Si buscás importar, exportar o encontrar nuevos mercados, escribinos por DM."
        ),
        "hashtags": ["#LUMENB2B", "#ComercioExterior", "#Importacion", "#Exportacion", "#NegociosB2B", "#InteligenciaComercial"],
        "visual": "travel_network",
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(value: str, limit: int = 80) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return (text or "theme")[:limit]


def normalize_theme(value: str) -> str:
    key = _slug(value or "travel").replace("-", "_")
    aliases = {
        "viajes": "travel",
        "viaje": "travel",
        "turismo": "travel",
        "travel_tourism": "travel",
        "tech": "technology",
        "tecnologia": "technology",
        "construccion": "construction",
        "industria": "industry",
        "importacion_exportacion": "import_export",
        "import_export": "import_export",
        "comercio_exterior": "import_export",
    }
    return aliases.get(key, key)


def _generic_brief(theme: str, goal: str = "", notes: str = "") -> Dict[str, Any]:
    visible = " ".join(re.split(r"[_-]+", theme)).strip().title() or "Negocios B2B"
    goal_text = " ".join(str(goal or "").split())[:180]
    notes_text = " ".join(str(notes or "").split())[:220]
    subtitle = (
        f"LUMEN investiga señales, oferta y demanda alrededor de {visible} para ordenar oportunidades comerciales con más contexto."
    )
    if goal_text:
        subtitle = f"{subtitle} Objetivo: {goal_text}."
    caption = (
        f"{visible} también puede leerse como una red de necesidades, proveedores y oportunidades.\n\n"
        f"LUMEN investiga señales públicas, organiza alternativas y ayuda a detectar encajes comerciales con trazabilidad.\n\n"
        f"Si trabajás en {visible.lower()} y querés explorar oportunidades B2B, escribinos por DM."
    )
    if notes_text:
        caption += f"\n\nEnfoque: {notes_text}."
    return {
        "label": visible.upper()[:42],
        "audience": "b2b",
        "pillar": f"theme_{_slug(theme, 42).replace('-', '_')}",
        "goal": goal_text or "qualified_business_conversation",
        "headline": f"{visible}: señales que pueden convertirse en oportunidades comerciales.",
        "subtitle": subtitle[:260],
        "cta": "HABLEMOS POR DM",
        "caption": caption[:1000],
        "hashtags": ["#LUMENB2B", "#NegociosB2B", "#OportunidadesComerciales", "#InteligenciaComercial", "#VentasB2B"],
        "visual": "network",
    }


def theme_brief(theme: str, goal: str = "", notes: str = "") -> Dict[str, Any]:
    key = normalize_theme(theme)
    brief = dict(THEMES.get(key) or _generic_brief(key, goal, notes))
    if goal:
        brief["requested_goal"] = " ".join(str(goal).split())[:240]
    if notes:
        brief["requested_notes"] = " ".join(str(notes).split())[:360]
    brief["theme"] = key
    return brief


def qa_piece(headline: str, subtitle: str, caption: str, hashtags: List[str]) -> Tuple[int, List[str]]:
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
    if any(token in lower for token in ("garantizado", "éxito asegurado", "100% seguro", "sin riesgo", "el mejor del mercado")):
        score -= 30
        reasons.append("unsupported_claim")
    return max(0, score), reasons


def build_job(theme: str, request_id: str, goal: str = "", notes: str = "") -> Dict[str, Any]:
    brief = theme_brief(theme, goal, notes)
    caption = str(brief["caption"]).rstrip() + "\n\n" + " ".join(brief["hashtags"])
    score, reasons = qa_piece(str(brief["headline"]), str(brief["subtitle"]), caption, list(brief["hashtags"]))
    if score < QA_MIN_SCORE:
        raise ValueError(f"theme_quality_gate_failed:{score}:{','.join(reasons)}")
    stable = f"{normalize_theme(theme)}|{request_id}|{brief['headline']}|{caption}"
    token = hashlib.sha1(stable.encode("utf-8")).hexdigest()[:12].upper()
    job_id = f"IGTHEME-{token}"
    now = _now()
    return {
        "id": job_id,
        "queue_key": f"IGTHEME|{normalize_theme(theme)}|{request_id}",
        "campaign_id": f"IG-THEME-{normalize_theme(theme).upper()}",
        "variant_id": f"IGTHEME-{normalize_theme(theme).upper()}-V1",
        "audience": brief["audience"],
        "channel": "instagram",
        "status": "awaiting_human_approval",
        "created_at": now,
        "updated_at": now,
        "attempts": 0,
        "copy": caption,
        "caption": caption,
        "headline": brief["headline"],
        "visual_subtitle": brief["subtitle"],
        "cta": brief["cta"],
        "hashtags": list(brief["hashtags"]),
        "content_pillar": brief["pillar"],
        "content_goal": brief["goal"],
        "creative_style": "matching_network" if brief["visual"] == "travel_network" else "evidence_grid",
        "creative_label": brief["label"],
        "editorial_slot": request_id,
        "editorial_strategy": "thematic_on_demand",
        "editorial_qa_score": score,
        "editorial_qa_reasons": reasons,
        "editorial_pro_v1": True,
        "content_mode": "thematic_on_demand",
        "theme": normalize_theme(theme),
        "format": "instagram_feed_4x5",
        "hide_tracking_url_in_caption": True,
        "tracking_path": "",
        "tracking_url": "",
        "requires_connector": True,
        "requires_budget_approval": False,
        "paid_media": False,
        "approval_required": True,
        "authority": "prepare_autonomously_publish_only_after_explicit_human_approval",
        "requested_goal": brief.get("requested_goal", ""),
        "requested_notes": brief.get("requested_notes", ""),
    }


def prepare_job(state: Dict[str, Any], theme: str, request_id: str, goal: str = "", notes: str = "") -> Dict[str, Any]:
    job = build_job(theme, request_id, goal, notes)
    jobs = state.setdefault("distribution_operator_jobs", [])
    existing = next((row for row in jobs if isinstance(row, dict) and str(row.get("id") or "") == job["id"]), None)
    if existing:
        return {"status": "already_prepared", "job_id": job["id"], "qa_score": existing.get("editorial_qa_score"), "theme": job["theme"]}
    jobs.append(job)
    state["distribution_operator_jobs"] = jobs[-500:]
    history = state.setdefault("instagram_editorial_history", [])
    history.append({
        "slot": request_id,
        "job_id": job["id"],
        "pillar": job["content_pillar"],
        "audience": job["audience"],
        "headline": job["headline"],
        "strategy": "thematic_on_demand",
        "qa_score": job["editorial_qa_score"],
        "created_at": job["created_at"],
    })
    state["instagram_editorial_history"] = history[-120:]
    return {"status": "prepared", "job_id": job["id"], "qa_score": job["editorial_qa_score"], "theme": job["theme"]}


def _font(size: int, bold: bool = False):
    from PIL import ImageFont
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def render_asset(job: Dict[str, Any]) -> Path:
    from PIL import Image, ImageDraw

    width, height = 1080, 1350
    bg = (5, 16, 22)
    panel = (10, 30, 38)
    text = (240, 247, 249)
    muted = (164, 188, 198)
    accent = (215, 255, 100)
    line = (43, 78, 90)

    image = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(image)
    draw.ellipse((690, -130, 1260, 440), fill=(12, 34, 40))
    draw.ellipse((-280, 930, 360, 1570), fill=(9, 29, 37))
    draw.rounded_rectangle((60, 60, 1020, 1290), radius=52, fill=panel, outline=line, width=2)

    draw.ellipse((94, 90, 116, 112), fill=accent)
    draw.text((138, 80), "LUMEN", font=_font(34, True), fill=text)
    draw.text((268, 92), "B2B", font=_font(17, True), fill=muted)
    draw.line((94, 142, 986, 142), fill=line, width=2)

    label = str(job.get("creative_label") or "INTELIGENCIA COMERCIAL").upper()
    draw.text((94, 180), label[:42], font=_font(21, True), fill=accent)

    headline = " ".join(str(job.get("headline") or "").split())
    title_font = _font(67 if len(headline) < 72 else 58, True)
    lines = textwrap.wrap(headline, width=27)[:4]
    y = 232
    for line_text in lines:
        draw.text((94, y), line_text, font=title_font, fill=text)
        y += 76

    subtitle = " ".join(str(job.get("visual_subtitle") or "").split())
    y += 20
    for line_text in textwrap.wrap(subtitle, width=52)[:3]:
        draw.text((96, y), line_text, font=_font(27), fill=muted)
        y += 39

    visual_top = max(720, y + 60)
    theme = str(job.get("theme") or "")
    if theme in {"travel", "import_export"}:
        nodes = [(190, visual_top + 145), (470, visual_top + 55), (760, visual_top + 190), (905, visual_top + 45)]
        for a, b in zip(nodes, nodes[1:]):
            draw.line((a[0], a[1], b[0], b[1]), fill=line, width=4)
        for idx, (x, yy) in enumerate(nodes):
            r = 16 if idx not in {1, 2} else 22
            draw.ellipse((x-r, yy-r, x+r, yy+r), fill=accent if idx == 2 else panel, outline=accent, width=3)
        draw.arc((235, visual_top - 25, 865, visual_top + 330), start=200, end=338, fill=accent, width=4)
        px, py = 690, visual_top + 64
        draw.polygon([(px, py), (px+58, py+12), (px+18, py+26), (px+8, py+60), (px-4, py+58), (px-2, py+24), (px-38, py+28)], fill=accent)
        draw.text((96, visual_top + 310), "SEÑAL  →  ENCAJE  →  OPORTUNIDAD", font=_font(30, True), fill=text)
    else:
        x0, yy = 96, visual_top + 70
        for idx, word in enumerate(("SEÑAL", "EVIDENCIA", "ENCAJE")):
            x = x0 + idx * 300
            draw.ellipse((x, yy, x+72, yy+72), outline=accent, width=3)
            draw.text((x+94, yy+20), word, font=_font(23, True), fill=text)
            if idx < 2:
                draw.line((x+210, yy+36, x+290, yy+36), fill=line, width=3)

    draw.line((94, 1190, 986, 1190), fill=line, width=2)
    draw.text((94, 1220), str(job.get("cta") or "HABLEMOS POR DM").upper()[:56], font=_font(24, True), fill=accent)
    draw.text((94, 1263), "@lumen.b2b · Inteligencia comercial", font=_font(18), fill=muted)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{job['id']}.jpg"
    image.save(path, "JPEG", quality=94, optimize=True, progressive=True)
    return path


def main() -> int:
    import d1_persistence_runtime  # noqa: F401
    import app as lumen_app
    import zero_instagram_control_bridge_runtime as bridge

    theme = os.getenv("LUMEN_INSTAGRAM_THEME", "travel").strip() or "travel"
    goal = os.getenv("LUMEN_INSTAGRAM_THEME_GOAL", "").strip()
    notes = os.getenv("LUMEN_INSTAGRAM_THEME_NOTES", "").strip()
    request_id = os.getenv("LUMEN_INSTAGRAM_THEME_REQUEST_ID", "").strip()
    if not request_id:
        request_id = f"{normalize_theme(theme)}-{datetime.now(timezone.utc).date().isoformat()}"

    if not lumen_app.load_state():
        raise RuntimeError("lumen_zero_state_unavailable")

    result = prepare_job(lumen_app.STATE, theme, request_id, goal, notes)
    job = next(
        row for row in lumen_app.STATE.get("distribution_operator_jobs", [])
        if isinstance(row, dict) and str(row.get("id") or "") == result["job_id"]
    )

    path = render_asset(job)
    job["image_url"] = f"{PUBLIC_BASE_URL}/media/instagram/{job['id']}.jpg"
    job["media_source"] = "lumen_zero_thematic_asset_v1"
    job["media_prepared_at"] = _now()
    job["updated_at"] = _now()

    if not lumen_app.save_state():
        raise RuntimeError("lumen_zero_state_persistence_failed")

    projection = bridge.export_posts()
    output = {
        "version": VERSION,
        **result,
        "image_path": str(path),
        "image_url": job["image_url"],
        "approval_required": True,
        "autonomous_publish": False,
        "paid_media": False,
        "projection_status": projection.get("status"),
        "posts_exported": projection.get("posts_exported"),
    }
    print({"zero_instagram_thematic_prepare": output}, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
