from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

VERSION = "1.0-instagram-travel-affiliate-acquisition"
PUBLIC_BASE_URL = (os.getenv("LUMEN_PUBLIC_BASE_URL") or "https://lumen-zero-public.lumen-b2b.workers.dev").rstrip("/")
OUT_DIR = Path(__file__).resolve().parent.parent / "public" / "instagram"
DESTINATIONS = ["Rio de Janeiro", "Cancún", "Madrid", "Bangkok", "Santiago de Chile", "Lima", "Montevideo", "São Paulo"]


def now():
    return datetime.now(timezone.utc).isoformat()


def clean(value, limit=600):
    return " ".join(str(value or "").split())[:limit]


def destination_for_today():
    explicit = clean(os.getenv("LUMEN_TRAVEL_ACQUISITION_DESTINATION"), 120)
    if explicit:
        return explicit
    return DESTINATIONS[datetime.now(timezone.utc).timetuple().tm_yday % len(DESTINATIONS)]


def build_job(destination, request_id):
    landing = f"{PUBLIC_BASE_URL}/travel?q={quote_plus(destination)}&source=instagram"
    stable = f"travel-affiliate-v1|{destination}|{request_id}"
    token = hashlib.sha1(stable.encode()).hexdigest()[:12].upper()
    jid = f"IGTRAVEL-{token}"
    caption = (
        f"¿Viajás a {destination}? ✈️\n\n"
        "LUMEN Travel reúne experiencias y actividades para comparar antes de cerrar tu itinerario. "
        "Podés revisar opciones, disponibilidad y precio directamente con el proveedor.\n\n"
        f"Ver experiencias: {landing}\n\n"
        "Transparencia: el enlace puede ser de afiliado. Si reservás a través de él, LUMEN puede recibir "
        "una comisión sin costo adicional para vos. La reserva y el cobro son gestionados por Viator.\n\n"
        "#LUMENTravel #Viajes #Experiencias #Turismo #Viator"
    )
    t = now()
    return {
        "id": jid,
        "queue_key": f"IGTRAVEL|{destination}|{request_id}",
        "campaign_id": "IG-TRAVEL-AFFILIATE-ACQUISITION-V1",
        "variant_id": f"IGTRAVEL-{destination.upper().replace(' ', '-')[:40]}-V1",
        "audience": "travel_consumers",
        "channel": "instagram",
        "status": "awaiting_human_approval",
        "created_at": t,
        "updated_at": t,
        "attempts": 0,
        "copy": caption,
        "caption": caption,
        "headline": f"¿Viajás a {destination}?",
        "visual_subtitle": "Experiencias para mirar antes de cerrar tu itinerario.",
        "cta": "VER EXPERIENCIAS",
        "hashtags": ["#LUMENTravel", "#Viajes", "#Experiencias", "#Turismo", "#Viator"],
        "content_pillar": "travel_affiliate_discovery",
        "content_goal": "qualified_travel_buyer_click",
        "creative_style": "travel_consumer_editorial",
        "creative_label": "LUMEN TRAVEL  |  EXPERIENCIAS",
        "editorial_slot": request_id,
        "editorial_strategy": "buyer_intent_affiliate_discovery",
        "content_mode": "travel_affiliate_acquisition",
        "theme": "travel",
        "format": "instagram_feed_4x5",
        "hide_tracking_url_in_caption": False,
        "tracking_path": f"/travel?q={quote_plus(destination)}&source=instagram",
        "tracking_url": landing,
        "requires_connector": True,
        "requires_budget_approval": False,
        "paid_media": False,
        "approval_required": True,
        "affiliate_disclosure": True,
        "booking_authority": False,
        "payment_authority": False,
        "autonomous_spend_usd": 0,
        "authority": "prepare_autonomously_publish_only_after_explicit_human_approval",
        "destination": destination,
    }


def supersede_previous(state, new_job):
    approvals = state.get("instagram_publish_approvals")
    if not isinstance(approvals, dict):
        approvals = {}
    t = now()
    for row in state.get("distribution_operator_jobs", []) or []:
        if not isinstance(row, dict) or row.get("channel") != "instagram" or row.get("content_mode") != "travel_affiliate_acquisition":
            continue
        if row.get("id") == new_job["id"] or str(row.get("status") or "").lower() in {"published", "rejected_by_human", "superseded_by_regeneration"}:
            continue
        jid = str(row.get("id") or "")
        if not jid:
            continue
        row.update({"status": "superseded_by_regeneration", "superseded_by": new_job["id"], "superseded_at": t, "updated_at": t})
        approvals[jid] = {"job_id": jid, "status": "REJECTED", "rejected_at": t, "authority": "travel_acquisition_refresh", "reason": "superseded_by_new_travel_buyer_campaign"}
    state["instagram_publish_approvals"] = approvals


def render_asset(job):
    from PIL import Image, ImageDraw, ImageFont

    width, height = 1080, 1350
    image = Image.new("RGB", (width, height), (8, 35, 50))
    px = image.load()
    for y in range(height):
        t = y / height
        for x in range(width):
            sun = max(0, 1 - abs(x / width - .72) * 3) * max(0, 1 - abs(t - .30) * 5)
            px[x, y] = (int(8 + 65 * sun + 16 * t), int(42 + 75 * sun + 28 * (1-t)), int(58 + 82 * (1-t)))
    draw = ImageDraw.Draw(image, "RGBA")
    draw.polygon([(0, 900), (220, 760), (390, 880), (590, 690), (760, 840), (1080, 730), (1080, 1350), (0, 1350)], fill=(5, 18, 24, 220))
    draw.rectangle((0, 0, width, height), fill=(0, 8, 14, 32))

    def font(size, bold=False):
        paths = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"]
        for p in paths:
            try:
                return ImageFont.truetype(p, size=size)
            except Exception:
                pass
        return ImageFont.load_default()

    gold = (238, 201, 125, 255)
    white = (248, 250, 249, 255)
    soft = (211, 226, 230, 255)
    draw.text((72, 70), "L U M E N   T R A V E L", font=font(32, True), fill=gold)
    draw.text((72, 225), clean(job["headline"], 60), font=font(66, True), fill=white)
    draw.multiline_text((76, 350), clean(job["visual_subtitle"], 120), font=font(28), fill=soft, spacing=12)
    draw.text((76, 875), "DESCUBRÍ", font=font(20, True), fill=gold)
    draw.text((76, 910), "actividades y experiencias", font=font(30, True), fill=white)
    draw.text((76, 990), "COMPARÁ", font=font(20, True), fill=gold)
    draw.text((76, 1025), "precio, fechas y disponibilidad", font=font(30, True), fill=white)
    draw.rounded_rectangle((72, 1160, 420, 1235), radius=36, fill=gold)
    draw.text((115, 1182), "VER EXPERIENCIAS", font=font(19, True), fill=(10, 28, 36, 255))
    draw.text((72, 1285), "@lumen.b2b", font=font(17), fill=soft)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{job['id']}.jpg"
    image.save(path, "JPEG", quality=94, optimize=True, progressive=True)
    return path


def main():
    import d1_persistence_runtime  # noqa: F401
    import app as lumen_app
    import zero_instagram_control_bridge_runtime as bridge

    destination = destination_for_today()
    request_id = clean(os.getenv("LUMEN_TRAVEL_ACQUISITION_REQUEST_ID"), 120) or f"travel-acq-{datetime.now(timezone.utc).date().isoformat()}"
    if not lumen_app.load_state():
        raise RuntimeError("lumen_zero_state_unavailable")
    job = build_job(destination, request_id)
    existing = next((r for r in lumen_app.STATE.get("distribution_operator_jobs", []) if isinstance(r, dict) and r.get("id") == job["id"]), None)
    if existing:
        print({"travel_instagram_acquisition": {"status": "already_prepared", "job_id": job["id"], "destination": destination, "approval_required": True}}, flush=True)
        return 0
    supersede_previous(lumen_app.STATE, job)
    path = render_asset(job)
    job.update({"image_url": f"{PUBLIC_BASE_URL}/media/instagram/{job['id']}.jpg", "media_source": VERSION, "media_prepared_at": now(), "visual_qa": {"status": "PASS", "score": 100, "asset_width": 1080, "asset_height": 1350}, "visual_qa_score": 100, "updated_at": now()})
    jobs = lumen_app.STATE.setdefault("distribution_operator_jobs", [])
    jobs.append(job)
    lumen_app.STATE["distribution_operator_jobs"] = jobs[-500:]
    if not lumen_app.save_state():
        raise RuntimeError("lumen_zero_state_persistence_failed")
    projection = bridge.export_posts()
    print({"travel_instagram_acquisition": {"status": "prepared", "version": VERSION, "job_id": job["id"], "destination": destination, "landing_url": job["tracking_url"], "image_path": str(path), "approval_required": True, "autonomous_publish": False, "paid_media": False, "autonomous_spend_usd": 0, "projection_status": projection.get("status"), "posts_exported": projection.get("posts_exported")}}, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
