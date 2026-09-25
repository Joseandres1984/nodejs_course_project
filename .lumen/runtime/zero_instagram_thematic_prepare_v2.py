from __future__ import annotations

"""Pixel-safe thematic Instagram preparation for LUMEN Zero.

V2 fixes visual overflow by measuring rendered text in pixels, auto-fitting
headlines/subtitles, enforcing a strict safe area, and refusing to export any
asset that fails visual QA. It also supersedes/rejects earlier unpublished
on-demand variants of the same theme when the owner explicitly requests a
regeneration.

It never auto-approves or auto-publishes a post and never enables paid media.
"""

import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import zero_instagram_thematic_prepare as v1

VERSION = "2.0-zero-instagram-pixel-safe"
QA_MIN_SCORE = 92
PUBLIC_BASE_URL = (os.getenv("LUMEN_PUBLIC_BASE_URL") or "https://lumen-zero-public.lumen-b2b.workers.dev").rstrip("/")
OUT_DIR = Path(__file__).resolve().parent.parent / "public" / "instagram"

WIDTH = 1080
HEIGHT = 1350
SAFE_LEFT = 108
SAFE_RIGHT = 972
SAFE_TOP = 82
SAFE_BOTTOM = 1268
SAFE_WIDTH = SAFE_RIGHT - SAFE_LEFT

TRAVEL_V2 = {
    "label": "VIAJES / TURISMO",
    "audience": "travel_b2b",
    "pillar": "travel_opportunities",
    "goal": "qualified_travel_business_conversation",
    "headline": "El sector viajes también genera oportunidades comerciales.",
    "subtitle": "Agencias, alojamientos, experiencias y traslados forman un ecosistema con señales de demanda y oferta.",
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
    "visual": "travel_network_v2",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def normalize_theme(value: str) -> str:
    return v1.normalize_theme(value)


def theme_brief(theme: str, goal: str = "", notes: str = "") -> Dict[str, Any]:
    key = normalize_theme(theme)
    brief = dict(TRAVEL_V2 if key == "travel" else v1.theme_brief(key, goal, notes))
    if goal:
        brief["requested_goal"] = _clean(goal)[:240]
    if notes:
        brief["requested_notes"] = _clean(notes)[:360]
    brief["theme"] = key
    return brief


def editorial_qa(headline: str, subtitle: str, caption: str, hashtags: List[str]) -> Tuple[int, List[str]]:
    score = 100
    reasons: List[str] = []
    joined = " ".join([headline, subtitle, caption, " ".join(hashtags)])
    lower = joined.lower()
    if "�" in joined:
        score -= 70
        reasons.append("replacement_character")
    if not 28 <= len(headline) <= 82:
        score -= 8
        reasons.append("headline_length")
    if not 60 <= len(subtitle) <= 150:
        score -= 6
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
    score, reasons = editorial_qa(str(brief["headline"]), str(brief["subtitle"]), caption, list(brief["hashtags"]))
    if score < QA_MIN_SCORE:
        raise ValueError(f"theme_editorial_quality_gate_failed:{score}:{','.join(reasons)}")
    stable = f"v2|{normalize_theme(theme)}|{request_id}|{brief['headline']}|{caption}"
    token = hashlib.sha1(stable.encode("utf-8")).hexdigest()[:12].upper()
    job_id = f"IGTHEME-{token}"
    now = _now()
    return {
        "id": job_id,
        "queue_key": f"IGTHEME|{normalize_theme(theme)}|{request_id}",
        "campaign_id": f"IG-THEME-{normalize_theme(theme).upper()}-V2",
        "variant_id": f"IGTHEME-{normalize_theme(theme).upper()}-PIXELSAFE-V2",
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
        "creative_style": "pixel_safe_travel_network" if brief.get("visual") == "travel_network_v2" else "pixel_safe_evidence_grid",
        "creative_label": brief["label"],
        "editorial_slot": request_id,
        "editorial_strategy": "thematic_on_demand",
        "editorial_qa_score": score,
        "editorial_qa_reasons": reasons,
        "editorial_pro_v2": True,
        "visual_qa_required": True,
        "content_mode": "thematic_on_demand",
        "theme": normalize_theme(theme),
        "format": "instagram_feed_4x5",
        "safe_area": {"left": SAFE_LEFT, "right": SAFE_RIGHT, "top": SAFE_TOP, "bottom": SAFE_BOTTOM},
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


def _approval_store(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    raw = state.get("instagram_publish_approvals")
    if isinstance(raw, dict):
        return raw
    store: Dict[str, Dict[str, Any]] = {}
    if isinstance(raw, list):
        for row in raw:
            if isinstance(row, dict) and row.get("job_id"):
                store[str(row["job_id"])] = row
    state["instagram_publish_approvals"] = store
    return store


def supersede_previous_unpublished(state: Dict[str, Any], new_job: Dict[str, Any]) -> List[str]:
    """Honor the owner's explicit rejection of the flawed current variant."""
    superseded: List[str] = []
    approvals = _approval_store(state)
    now = _now()
    for row in state.get("distribution_operator_jobs", []) or []:
        if not isinstance(row, dict):
            continue
        jid = str(row.get("id") or "")
        if not jid or jid == new_job["id"]:
            continue
        if str(row.get("channel") or "") != "instagram":
            continue
        if str(row.get("content_mode") or "") != "thematic_on_demand":
            continue
        if str(row.get("theme") or "") != str(new_job.get("theme") or ""):
            continue
        status = str(row.get("status") or "").lower()
        approval_status = str((approvals.get(jid) or {}).get("status") or "").upper()
        if status in {"published", "rejected_by_human", "superseded_by_regeneration"} or approval_status == "PUBLISHED":
            continue
        row["status"] = "superseded_by_regeneration"
        row["superseded_by"] = new_job["id"]
        row["superseded_at"] = now
        row["updated_at"] = now
        approvals[jid] = {
            "job_id": jid,
            "status": "REJECTED",
            "rejected_at": now,
            "authority": "explicit_owner_rejection_visual_regeneration",
            "reason": "visual_overflow_and_layout_quality_rejected_by_owner",
            "superseded_by": new_job["id"],
        }
        superseded.append(jid)
    state["instagram_publish_approvals"] = approvals
    return superseded


def prepare_job(state: Dict[str, Any], theme: str, request_id: str, goal: str = "", notes: str = "") -> Dict[str, Any]:
    job = build_job(theme, request_id, goal, notes)
    jobs = state.setdefault("distribution_operator_jobs", [])
    existing = next((row for row in jobs if isinstance(row, dict) and str(row.get("id") or "") == job["id"]), None)
    if existing:
        return {
            "status": "already_prepared",
            "job_id": job["id"],
            "qa_score": existing.get("editorial_qa_score"),
            "theme": job["theme"],
            "superseded": [],
        }
    superseded = supersede_previous_unpublished(state, job)
    jobs.append(job)
    state["distribution_operator_jobs"] = jobs[-500:]
    history = state.setdefault("instagram_editorial_history", [])
    history.append({
        "slot": request_id,
        "job_id": job["id"],
        "pillar": job["content_pillar"],
        "audience": job["audience"],
        "headline": job["headline"],
        "strategy": "thematic_on_demand_pixel_safe_v2",
        "qa_score": job["editorial_qa_score"],
        "superseded": superseded,
        "created_at": job["created_at"],
    })
    state["instagram_editorial_history"] = history[-120:]
    return {
        "status": "prepared",
        "job_id": job["id"],
        "qa_score": job["editorial_qa_score"],
        "theme": job["theme"],
        "superseded": superseded,
    }


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


def _text_width(draw, text: str, font) -> int:
    box = draw.textbbox((0, 0), text, font=font)
    return int(box[2] - box[0])


def _wrap_pixels(draw, text: str, font, max_width: int) -> List[str]:
    words = _clean(text).split(" ")
    lines: List[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if _text_width(draw, candidate, font) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = word
        else:
            return []
    if current:
        lines.append(current)
    return lines


def _fit_multiline(draw, text: str, max_width: int, max_lines: int, max_size: int, min_size: int, bold: bool = False):
    for size in range(max_size, min_size - 1, -2):
        font = _font(size, bold)
        lines = _wrap_pixels(draw, text, font, max_width)
        if lines and len(lines) <= max_lines and all(_text_width(draw, line, font) <= max_width for line in lines):
            return font, lines, size
    raise ValueError(f"visual_text_does_not_fit:{_clean(text)[:120]}")


def _bbox_inside(draw, xy: Tuple[int, int], text: str, font, left: int, top: int, right: int, bottom: int) -> bool:
    box = draw.textbbox(xy, text, font=font)
    return box[0] >= left and box[1] >= top and box[2] <= right and box[3] <= bottom


def render_asset(job: Dict[str, Any]) -> Tuple[Path, Dict[str, Any]]:
    from PIL import Image, ImageDraw

    bg = (5, 16, 22)
    panel = (9, 27, 35)
    panel2 = (11, 34, 42)
    text = (240, 247, 249)
    muted = (160, 184, 194)
    accent = (215, 255, 100)
    line = (42, 75, 87)

    image = Image.new("RGB", (WIDTH, HEIGHT), bg)
    draw = ImageDraw.Draw(image)

    # Premium but restrained background treatment.
    draw.ellipse((720, -210, 1260, 350), fill=(10, 31, 39))
    draw.ellipse((-240, 1040, 280, 1540), fill=(8, 28, 36))
    draw.rounded_rectangle((64, 52, 1016, 1298), radius=46, fill=panel, outline=line, width=2)
    draw.rounded_rectangle((86, 70, 994, 1278), radius=36, outline=(20, 53, 63), width=1)

    blocks: List[Tuple[str, Tuple[int, int], str, Any, int, int, int, int]] = []

    # Brand row.
    draw.ellipse((SAFE_LEFT, 94, SAFE_LEFT + 20, 114), fill=accent)
    brand_font = _font(31, True)
    brand_xy = (SAFE_LEFT + 42, 82)
    draw.text(brand_xy, "LUMEN", font=brand_font, fill=text)
    blocks.append(("brand", brand_xy, "LUMEN", brand_font, SAFE_LEFT, SAFE_TOP, SAFE_RIGHT, 150))
    b2b_font = _font(15, True)
    b2b_xy = (SAFE_LEFT + 169, 96)
    draw.text(b2b_xy, "B2B", font=b2b_font, fill=muted)
    blocks.append(("b2b", b2b_xy, "B2B", b2b_font, SAFE_LEFT, SAFE_TOP, SAFE_RIGHT, 150))
    draw.line((SAFE_LEFT, 150, SAFE_RIGHT, 150), fill=line, width=2)

    # Category label.
    label = _clean(job.get("creative_label") or "INTELIGENCIA COMERCIAL").upper()[:42]
    label_font = _font(20, True)
    label_xy = (SAFE_LEFT, 184)
    draw.text(label_xy, label, font=label_font, fill=accent)
    blocks.append(("label", label_xy, label, label_font, SAFE_LEFT, 170, SAFE_RIGHT, 225))

    # Headline: pixel-measured and max 3 lines.
    headline = _clean(job.get("headline"))
    title_font, title_lines, title_size = _fit_multiline(draw, headline, SAFE_WIDTH, 3, 64, 42, True)
    title_y = 232
    title_gap = int(title_size * 1.16)
    for idx, line_text in enumerate(title_lines):
        xy = (SAFE_LEFT, title_y + idx * title_gap)
        draw.text(xy, line_text, font=title_font, fill=text)
        blocks.append((f"headline_{idx}", xy, line_text, title_font, SAFE_LEFT, 220, SAFE_RIGHT, 480))
    title_bottom = title_y + len(title_lines) * title_gap

    # Subtitle: pixel-measured and max 3 lines.
    subtitle = _clean(job.get("visual_subtitle"))
    subtitle_font, subtitle_lines, subtitle_size = _fit_multiline(draw, subtitle, SAFE_WIDTH, 3, 29, 22, False)
    subtitle_y = title_bottom + 28
    subtitle_gap = int(subtitle_size * 1.45)
    for idx, line_text in enumerate(subtitle_lines):
        xy = (SAFE_LEFT, subtitle_y + idx * subtitle_gap)
        draw.text(xy, line_text, font=subtitle_font, fill=muted)
        blocks.append((f"subtitle_{idx}", xy, line_text, subtitle_font, SAFE_LEFT, 350, SAFE_RIGHT, 620))
    subtitle_bottom = subtitle_y + len(subtitle_lines) * subtitle_gap

    # Travel network graphic gets its own clear zone.
    visual_top = max(650, subtitle_bottom + 54)
    visual_bottom = 1025
    if visual_top > 735:
        raise ValueError(f"visual_layout_too_dense:visual_top={visual_top}")

    theme = str(job.get("theme") or "")
    if theme in {"travel", "import_export"}:
        route_y = visual_top + 150
        nodes = [
            (SAFE_LEFT + 70, route_y + 42),
            (SAFE_LEFT + 300, route_y - 70),
            (SAFE_LEFT + 545, route_y + 20),
            (SAFE_RIGHT - 52, route_y - 94),
        ]
        for a, b in zip(nodes, nodes[1:]):
            draw.line((a[0], a[1], b[0], b[1]), fill=line, width=4)
        for idx, (x, yy) in enumerate(nodes):
            r = 15 if idx not in {1, 2} else 20
            draw.ellipse((x-r, yy-r, x+r, yy+r), fill=accent if idx == 2 else panel2, outline=accent, width=3)
        draw.arc((SAFE_LEFT + 120, visual_top - 12, SAFE_RIGHT - 180, visual_top + 300), start=202, end=340, fill=accent, width=4)
        px, py = SAFE_LEFT + 555, visual_top + 35
        draw.polygon([(px, py), (px+54, py+11), (px+17, py+24), (px+8, py+55), (px-4, py+54), (px-2, py+23), (px-34, py+26)], fill=accent)
    else:
        x0, yy = SAFE_LEFT, visual_top + 110
        for idx, word in enumerate(("SEÑAL", "EVIDENCIA", "ENCAJE")):
            x = x0 + idx * 285
            draw.ellipse((x, yy, x+64, yy+64), outline=accent, width=3)
            draw.text((x+82, yy+17), word, font=_font(20, True), fill=text)
            if idx < 2:
                draw.line((x+192, yy+32, x+270, yy+32), fill=line, width=3)

    signal_text = "SEÑAL  →  ENCAJE  →  OPORTUNIDAD"
    signal_font, signal_lines, _ = _fit_multiline(draw, signal_text, SAFE_WIDTH, 1, 29, 20, True)
    signal_xy = (SAFE_LEFT, 1074)
    draw.text(signal_xy, signal_lines[0], font=signal_font, fill=text)
    blocks.append(("signal", signal_xy, signal_lines[0], signal_font, SAFE_LEFT, 1050, SAFE_RIGHT, 1135))

    # CTA/footer zone.
    draw.line((SAFE_LEFT, 1168, SAFE_RIGHT, 1168), fill=line, width=2)
    cta = _clean(job.get("cta") or "HABLEMOS POR DM").upper()[:56]
    cta_font, cta_lines, _ = _fit_multiline(draw, cta, SAFE_WIDTH, 1, 25, 20, True)
    cta_xy = (SAFE_LEFT, 1199)
    draw.text(cta_xy, cta_lines[0], font=cta_font, fill=accent)
    blocks.append(("cta", cta_xy, cta_lines[0], cta_font, SAFE_LEFT, 1185, SAFE_RIGHT, 1245))

    footer = "@lumen.b2b · Inteligencia comercial"
    footer_font = _font(17)
    footer_xy = (SAFE_LEFT, 1243)
    draw.text(footer_xy, footer, font=footer_font, fill=muted)
    blocks.append(("footer", footer_xy, footer, footer_font, SAFE_LEFT, 1235, SAFE_RIGHT, SAFE_BOTTOM))

    # Strict visual QA: every tracked text block must live inside its assigned box.
    failures: List[str] = []
    for name, xy, value, font, left, top, right, bottom in blocks:
        if not _bbox_inside(draw, xy, value, font, left, top, right, bottom):
            failures.append(name)
    if failures:
        raise ValueError("visual_quality_gate_failed:" + ",".join(failures))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{job['id']}.jpg"
    image.save(path, "JPEG", quality=95, optimize=True, progressive=True)

    report = {
        "score": 100,
        "status": "PASS",
        "safe_area": {"left": SAFE_LEFT, "right": SAFE_RIGHT, "top": SAFE_TOP, "bottom": SAFE_BOTTOM},
        "headline_lines": len(title_lines),
        "headline_font_px": title_size,
        "subtitle_lines": len(subtitle_lines),
        "subtitle_font_px": subtitle_size,
        "overflow_blocks": [],
        "asset_width": WIDTH,
        "asset_height": HEIGHT,
    }
    return path, report


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

    path, visual_qa = render_asset(job)
    job["image_url"] = f"{PUBLIC_BASE_URL}/media/instagram/{job['id']}.jpg"
    job["media_source"] = "lumen_zero_thematic_pixel_safe_v2"
    job["media_prepared_at"] = _now()
    job["visual_qa"] = visual_qa
    job["visual_qa_score"] = visual_qa["score"]
    job["updated_at"] = _now()

    if visual_qa.get("status") != "PASS" or int(visual_qa.get("score") or 0) < 100:
        job["status"] = "visual_qa_failed"
        raise RuntimeError("visual_qa_not_passed")

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
        "visual_qa": visual_qa,
        "projection_status": projection.get("status"),
        "posts_exported": projection.get("posts_exported"),
    }
    print({"zero_instagram_thematic_prepare_v2": output}, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
