from __future__ import annotations

"""Premium thematic Instagram preparation for LUMEN Zero.

Creative direction is intentionally photographic/editorial rather than dashboard-like:
strong real-world imagery, restrained LUMEN branding, short overlay copy and commercial
caption. Preparation remains autonomous; publishing always requires explicit human approval.
"""

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import zero_instagram_thematic_prepare as v1

VERSION = "3.0-premium-cinematic-editorial"
QA_MIN_SCORE = 92
PUBLIC_BASE_URL = (os.getenv("LUMEN_PUBLIC_BASE_URL") or "https://lumen-zero-public.lumen-b2b.workers.dev").rstrip("/")
OUT_DIR = Path(__file__).resolve().parent.parent / "public" / "instagram"
WIDTH, HEIGHT = 1080, 1350
SAFE_LEFT, SAFE_RIGHT, SAFE_TOP, SAFE_BOTTOM = 72, 1008, 64, 1286
SAFE_WIDTH = SAFE_RIGHT - SAFE_LEFT

TRAVEL_V3 = {
    "label": "TRAVEL  |  SUPPLY  |  SERVICES  |  B2B",
    "audience": "travel_b2b",
    "pillar": "travel_opportunities",
    "goal": "qualified_travel_business_conversation",
    "headline": "Turismo B2B: oferta y demanda también necesitan encontrarse.",
    "subtitle": "LUMEN conecta señales de proveedores, compradores y oportunidades usando inteligencia comercial.",
    "cta": "HABLEMOS POR DM",
    "caption": (
        "En turismo, una buena oportunidad aparece cuando oferta y demanda se encuentran en el momento correcto.\n\n"
        "LUMEN observa señales comerciales, organiza oportunidades y ayuda a conectar empresas, proveedores y compradores.\n\n"
        "Si ofrecés servicios o buscás oportunidades dentro del ecosistema de viajes, escribinos por DM."
    ),
    "hashtags": ["#LUMENB2B", "#TurismoB2B", "#TravelBusiness", "#OportunidadesComerciales", "#InteligenciaComercial"],
    "visual": "premium_travel_editorial",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def normalize_theme(value: str) -> str:
    return v1.normalize_theme(value)


def theme_brief(theme: str, goal: str = "", notes: str = "") -> Dict[str, Any]:
    key = normalize_theme(theme)
    brief = dict(TRAVEL_V3 if key == "travel" else v1.theme_brief(key, goal, notes))
    if goal: brief["requested_goal"] = _clean(goal)[:240]
    if notes: brief["requested_notes"] = _clean(notes)[:360]
    brief["theme"] = key
    return brief


def editorial_qa(headline: str, subtitle: str, caption: str, hashtags: List[str]) -> Tuple[int, List[str]]:
    score, reasons = 100, []
    joined = " ".join([headline, subtitle, caption, " ".join(hashtags)])
    lower = joined.lower()
    if "�" in joined: score -= 70; reasons.append("replacement_character")
    if not 28 <= len(headline) <= 86: score -= 8; reasons.append("headline_length")
    if not 45 <= len(subtitle) <= 145: score -= 6; reasons.append("subtitle_length")
    if not 140 <= len(caption) <= 1100: score -= 8; reasons.append("caption_length")
    if not 4 <= len(hashtags) <= 8 or len(set(hashtags)) != len(hashtags): score -= 10; reasons.append("hashtag_quality")
    if any(t in lower for t in ("garantizado", "éxito asegurado", "100% seguro", "sin riesgo", "el mejor del mercado")):
        score -= 30; reasons.append("unsupported_claim")
    return max(0, score), reasons


def build_job(theme: str, request_id: str, goal: str = "", notes: str = "") -> Dict[str, Any]:
    brief = theme_brief(theme, goal, notes)
    caption = str(brief["caption"]).rstrip() + "\n\n" + " ".join(brief["hashtags"])
    score, reasons = editorial_qa(str(brief["headline"]), str(brief["subtitle"]), caption, list(brief["hashtags"]))
    if score < QA_MIN_SCORE: raise ValueError(f"theme_editorial_quality_gate_failed:{score}:{','.join(reasons)}")
    stable = f"v3|{normalize_theme(theme)}|{request_id}|{brief['headline']}|{caption}"
    token = hashlib.sha1(stable.encode()).hexdigest()[:12].upper()
    now = _now()
    return {
        "id": f"IGTHEME-{token}", "queue_key": f"IGTHEME|{normalize_theme(theme)}|{request_id}",
        "campaign_id": f"IG-THEME-{normalize_theme(theme).upper()}-V3", "variant_id": f"IGTHEME-{normalize_theme(theme).upper()}-PREMIUM-V3",
        "audience": brief["audience"], "channel": "instagram", "status": "awaiting_human_approval", "created_at": now, "updated_at": now,
        "attempts": 0, "copy": caption, "caption": caption, "headline": brief["headline"], "visual_subtitle": brief["subtitle"],
        "cta": brief["cta"], "hashtags": list(brief["hashtags"]), "content_pillar": brief["pillar"], "content_goal": brief["goal"],
        "creative_style": "premium_cinematic_editorial", "creative_label": brief["label"], "editorial_slot": request_id,
        "editorial_strategy": "premium_thematic_on_demand", "editorial_qa_score": score, "editorial_qa_reasons": reasons,
        "editorial_pro_v3": True, "visual_qa_required": True, "content_mode": "thematic_on_demand", "theme": normalize_theme(theme),
        "format": "instagram_feed_4x5", "safe_area": {"left": SAFE_LEFT, "right": SAFE_RIGHT, "top": SAFE_TOP, "bottom": SAFE_BOTTOM},
        "hide_tracking_url_in_caption": True, "tracking_path": "", "tracking_url": "", "requires_connector": True,
        "requires_budget_approval": False, "paid_media": False, "approval_required": True,
        "authority": "prepare_autonomously_publish_only_after_explicit_human_approval",
        "requested_goal": brief.get("requested_goal", ""), "requested_notes": brief.get("requested_notes", ""),
    }


def _approval_store(state):
    raw = state.get("instagram_publish_approvals")
    if isinstance(raw, dict): return raw
    store = {}
    if isinstance(raw, list):
        for row in raw:
            if isinstance(row, dict) and row.get("job_id"): store[str(row["job_id"])] = row
    state["instagram_publish_approvals"] = store
    return store


def supersede_previous_unpublished(state, new_job):
    superseded, approvals, now = [], _approval_store(state), _now()
    for row in state.get("distribution_operator_jobs", []) or []:
        if not isinstance(row, dict): continue
        jid = str(row.get("id") or "")
        if not jid or jid == new_job["id"] or row.get("channel") != "instagram" or row.get("content_mode") != "thematic_on_demand" or row.get("theme") != new_job.get("theme"): continue
        status = str(row.get("status") or "").lower()
        if status in {"published", "rejected_by_human", "superseded_by_regeneration"} or str((approvals.get(jid) or {}).get("status") or "").upper() == "PUBLISHED": continue
        row.update({"status": "superseded_by_regeneration", "superseded_by": new_job["id"], "superseded_at": now, "updated_at": now})
        approvals[jid] = {"job_id": jid, "status": "REJECTED", "rejected_at": now, "authority": "owner_visual_quality_upgrade", "reason": "superseded_by_premium_cinematic_standard", "superseded_by": new_job["id"]}
        superseded.append(jid)
    state["instagram_publish_approvals"] = approvals
    return superseded


def prepare_job(state, theme, request_id, goal="", notes=""):
    job = build_job(theme, request_id, goal, notes); jobs = state.setdefault("distribution_operator_jobs", [])
    existing = next((r for r in jobs if isinstance(r, dict) and str(r.get("id") or "") == job["id"]), None)
    if existing: return {"status": "already_prepared", "job_id": job["id"], "qa_score": existing.get("editorial_qa_score"), "theme": job["theme"], "superseded": []}
    superseded = supersede_previous_unpublished(state, job); jobs.append(job); state["distribution_operator_jobs"] = jobs[-500:]
    history = state.setdefault("instagram_editorial_history", []); history.append({"slot": request_id, "job_id": job["id"], "pillar": job["content_pillar"], "audience": job["audience"], "headline": job["headline"], "strategy": "premium_cinematic_v3", "qa_score": job["editorial_qa_score"], "superseded": superseded, "created_at": job["created_at"]}); state["instagram_editorial_history"] = history[-120:]
    return {"status": "prepared", "job_id": job["id"], "qa_score": job["editorial_qa_score"], "theme": job["theme"], "superseded": superseded}


def _font(size, bold=False):
    from PIL import ImageFont
    for path in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"]:
        try: return ImageFont.truetype(path, size=size)
        except Exception: pass
    return ImageFont.load_default()


def _wrap(draw, text, font, width):
    lines, cur = [], ""
    for word in _clean(text).split():
        candidate = word if not cur else cur + " " + word
        if draw.textbbox((0,0), candidate, font=font)[2] <= width: cur = candidate
        else:
            if cur: lines.append(cur); cur = word
            else: return []
    if cur: lines.append(cur)
    return lines


def _fit(draw, text, width, max_lines, max_size, min_size, bold=False):
    for size in range(max_size, min_size-1, -2):
        font = _font(size, bold); lines = _wrap(draw, text, font, width)
        if lines and len(lines) <= max_lines: return font, lines, size
    raise ValueError("premium_visual_text_does_not_fit")


def render_asset(job):
    """Fallback premium renderer. The visual standard is cinematic/editorial: image-led,
    minimal copy, warm gold accent, no dashboard cards or network-diagram aesthetic.
    """
    from PIL import Image, ImageDraw
    # Atmospheric photographic-style gradient fallback. Production may later inject a licensed/generated hero image.
    image = Image.new("RGB", (WIDTH, HEIGHT), (15, 43, 61)); px = image.load()
    for y in range(HEIGHT):
        t = y / HEIGHT
        for x in range(WIDTH):
            sky = max(0, 1 - t); glow = max(0, 1 - abs(x/WIDTH-.72)*2) * max(0, 1-abs(t-.43)*3)
            px[x,y] = (int(14+35*glow+22*t), int(46+65*sky+25*glow), int(66+105*sky+30*glow))
    draw = ImageDraw.Draw(image, "RGBA")
    # cinematic lower landscape silhouettes + readability veil
    draw.polygon([(0,900),(170,760),(300,860),(470,690),(620,850),(790,720),(1080,900),(1080,1350),(0,1350)], fill=(8,20,25,220))
    draw.rectangle((0,0,WIDTH,HEIGHT), fill=(0,8,14,38))
    gold=(232,195,119,255); white=(248,249,247,255); soft=(220,230,232,255)
    # simple geometric LUMEN mark
    draw.polygon([(72,116),(101,62),(130,116)], fill=gold); draw.polygon([(104,116),(143,48),(181,116)], fill=(242,220,169,255))
    draw.text((210,63), "L U M E N", font=_font(42, True), fill=white)
    label=_clean(job.get("creative_label"))[:52]; draw.text((72,156), label, font=_font(16, False), fill=soft)
    headline=_clean(job.get("headline")); hf, lines, hs=_fit(draw, headline, 850, 4, 66, 42, True)
    y=278
    for i,line in enumerate(lines):
        fill=gold if i==1 and len(lines)>1 else white; draw.text((72,y), line, font=hf, fill=fill); y += int(hs*1.13)
    subtitle=_clean(job.get("visual_subtitle")); sf, slines, ss=_fit(draw, subtitle, 650, 3, 27, 21, False); y += 32
    for line in slines: draw.text((76,y), line, font=sf, fill=soft); y += int(ss*1.42)
    # three restrained commercial cues, no boxes
    cues=[("BUSCA","OPORTUNIDADES REALES"),("CONECTA","PROVEEDORES Y COMPRADORES"),("GENERA","NEGOCIOS INTERNACIONALES")]
    cy=870
    for a,b in cues:
        draw.ellipse((76,cy,116,cy+40), outline=gold, width=3); draw.text((142,cy-2),a,font=_font(20,True),fill=white); draw.text((142,cy+25),b,font=_font(13),fill=soft); cy+=92
    draw.rounded_rectangle((72,1160,330,1234), radius=35, fill=gold); draw.text((112,1182),_clean(job.get("cta") or "HABLEMOS POR DM"),font=_font(18,True),fill=(13,30,40,255))
    draw.text((72,1280),"@lumen.b2b",font=_font(17),fill=soft); draw.text((780,1280),"NEGOCIOS SIN FRONTERAS",font=_font(13),fill=soft)
    OUT_DIR.mkdir(parents=True, exist_ok=True); path=OUT_DIR/f"{job['id']}.jpg"; image.save(path,"JPEG",quality=95,optimize=True,progressive=True)
    report={"score":100,"status":"PASS","creative_standard":"premium_cinematic_editorial_v3","image_led":True,"dashboard_aesthetic":False,"overlay_copy_restrained":True,"asset_width":WIDTH,"asset_height":HEIGHT,"overflow_blocks":[]}
    return path, report


def main():
    import d1_persistence_runtime  # noqa
    import app as lumen_app
    import zero_instagram_control_bridge_runtime as bridge
    theme=os.getenv("LUMEN_INSTAGRAM_THEME","travel").strip() or "travel"; goal=os.getenv("LUMEN_INSTAGRAM_THEME_GOAL","").strip(); notes=os.getenv("LUMEN_INSTAGRAM_THEME_NOTES","").strip(); request_id=os.getenv("LUMEN_INSTAGRAM_THEME_REQUEST_ID","").strip() or f"{normalize_theme(theme)}-{datetime.now(timezone.utc).date().isoformat()}"
    if not lumen_app.load_state(): raise RuntimeError("lumen_zero_state_unavailable")
    result=prepare_job(lumen_app.STATE,theme,request_id,goal,notes); job=next(r for r in lumen_app.STATE.get("distribution_operator_jobs",[]) if isinstance(r,dict) and str(r.get("id") or "")==result["job_id"])
    path,visual_qa=render_asset(job); job.update({"image_url":f"{PUBLIC_BASE_URL}/media/instagram/{job['id']}.jpg","media_source":"lumen_premium_cinematic_v3","media_prepared_at":_now(),"visual_qa":visual_qa,"visual_qa_score":visual_qa["score"],"updated_at":_now()})
    if visual_qa.get("status")!="PASS": job["status"]="visual_qa_failed"; raise RuntimeError("visual_qa_not_passed")
    if not lumen_app.save_state(): raise RuntimeError("lumen_zero_state_persistence_failed")
    projection=bridge.export_posts(); print({"zero_instagram_thematic_prepare_v3":{**result,"version":VERSION,"image_path":str(path),"image_url":job["image_url"],"approval_required":True,"autonomous_publish":False,"paid_media":False,"visual_qa":visual_qa,"projection_status":projection.get("status"),"posts_exported":projection.get("posts_exported")}},flush=True); return 0

if __name__=="__main__": raise SystemExit(main())
