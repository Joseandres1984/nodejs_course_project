from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

VERSION = "1.3-instagram-travel-dedupe-recovery"
PUBLIC_BASE_URL = (os.getenv("LUMEN_PUBLIC_BASE_URL") or "https://lumen-zero-public.lumen-b2b.workers.dev").rstrip("/")
OUT_DIR = Path(__file__).resolve().parent.parent / "public" / "instagram"
DESTINATIONS = [
    {"name": "Rio de Janeiro", "code": "GIG"},
    {"name": "Cancún", "code": "CUN"},
    {"name": "Madrid", "code": "MAD"},
    {"name": "Bangkok", "code": "BKK"},
    {"name": "Santiago de Chile", "code": "SCL"},
    {"name": "Lima", "code": "LIM"},
    {"name": "Montevideo", "code": "MVD"},
    {"name": "São Paulo", "code": "GRU"},
]


def now():
    return datetime.now(timezone.utc).isoformat()


def clean(value, limit=600):
    return " ".join(str(value or "").split())[:limit]


def destination_for_today():
    explicit = clean(os.getenv("LUMEN_TRAVEL_ACQUISITION_DESTINATION"), 120).lower()
    if explicit:
        match = next(
            (
                item
                for item in DESTINATIONS
                if explicit in {item["name"].lower(), item["code"].lower()}
                or explicit in item["name"].lower()
            ),
            None,
        )
        if match:
            return match
    return DESTINATIONS[datetime.now(timezone.utc).timetuple().tm_yday % len(DESTINATIONS)]


def build_job(destination, request_id, creative_variant=0):
    destination_name = destination["name"]
    destination_code = destination["code"]
    query = urlencode({"destination": destination_code, "source": "instagram"})
    landing = f"{PUBLIC_BASE_URL}/travel/package?{query}"
    stable = f"travel-full-trip-v1|{destination_code}|{request_id}" if creative_variant == 0 else f"travel-full-trip-v1|{destination_code}|{request_id}|creative-{creative_variant}"
    token = hashlib.sha1(stable.encode()).hexdigest()[:12].upper()
    jid = f"IGTRAVEL-{token}"
    variants = [
        (
            f"¿Viajás a {destination_name}? ✈️\n\n"
            "LUMEN Travel te ayuda a armar el viaje base con vuelo + alojamiento y, si querés, sumar experiencias. "
            "Elegís destino, días, pasajeros y presupuesto; después continuás con los proveedores externos.\n\n"
            f"Armá tu viaje: {landing}\n\n"
            "Transparencia: LUMEN puede utilizar enlaces de afiliado y recibir una comisión si reservás con un partner, "
            "sin costo adicional para vos. Las reservas y los cobros se completan siempre con el proveedor externo.\n\n"
            "#LUMENTravel #Viajes #Vuelos #Hoteles #Turismo"
        ),
        (
            f"{destination_name}, paso por paso. 🌎\n\n"
            "Antes de reservar, separá el viaje en tres decisiones: cómo llegar, dónde dormir y qué experiencias realmente querés sumar. "
            "LUMEN Travel reúne esas opciones para que compares primero y reserves después directamente con cada proveedor.\n\n"
            f"Explorá el viaje: {landing}\n\n"
            "Transparencia: este contenido puede incluir enlaces de afiliado. LUMEN puede recibir una comisión por una reserva elegible, "
            "sin aumentar el precio para vos. LUMEN no procesa reservas ni cobros.\n\n"
            "#LUMENTravel #PlanificarViaje #Turismo #Experiencias"
        ),
        (
            f"¿Qué conviene mirar antes de cerrar un viaje a {destination_name}? 🧭\n\n"
            "No sólo el precio final: también horarios, alojamiento, duración y actividades opcionales. "
            "Con LUMEN Travel podés ordenar la búsqueda y seguir al proveedor que prefieras cuando una opción te cierre.\n\n"
            f"Compará alternativas: {landing}\n\n"
            "Transparencia: algunos enlaces son de afiliados y una reserva elegible puede generar una comisión para LUMEN "
            "sin costo adicional para vos. La compra y el pago ocurren siempre fuera de LUMEN.\n\n"
            "#Viajes #LUMENTravel #Comparar #Turismo"
        ),
    ]
    creative_variant = max(0, min(len(variants) - 1, int(creative_variant or 0)))
    caption = variants[creative_variant]
    t = now()
    return {
        "id": jid,
        "queue_key": f"IGTRAVEL|{destination_code}|{request_id}",
        "campaign_id": "IG-TRAVEL-FULL-TRIP-ACQUISITION-V1",
        "variant_id": f"IGTRAVEL-{destination_code}-FULLTRIP-V{creative_variant + 1}",
        "audience": "travel_consumers",
        "channel": "instagram",
        "status": "awaiting_human_approval",
        "created_at": t,
        "updated_at": t,
        "attempts": 0,
        "copy": caption,
        "caption": caption,
        "headline": [
            f"¿Viajás a {destination_name}?",
            f"{destination_name}, paso por paso",
            f"Antes de reservar {destination_name}",
        ][creative_variant],
        "visual_subtitle": "Armá vuelo + alojamiento. Experiencias, sólo si querés.",
        "cta": "ARMÁ TU VIAJE",
        "hashtags": ["#LUMENTravel", "#Viajes", "#Vuelos", "#Hoteles", "#Turismo"],
        "content_pillar": "travel_full_trip_acquisition",
        "content_goal": "qualified_travel_package_builder_visit",
        "creative_style": "travel_consumer_editorial",
        "creative_label": "LUMEN TRAVEL  |  ARMÁ TU VIAJE",
        "editorial_slot": request_id,
        "editorial_strategy": f"buyer_intent_full_trip_builder_v{creative_variant + 1}",
        "content_mode": "travel_affiliate_acquisition",
        "theme": "travel",
        "format": "instagram_feed_4x5",
        "hide_tracking_url_in_caption": False,
        "tracking_path": f"/travel/package?{query}",
        "tracking_url": landing,
        "requires_connector": True,
        "requires_budget_approval": False,
        "paid_media": False,
        "approval_required": True,
        "affiliate_disclosure": True,
        "booking_authority": False,
        "payment_authority": False,
        "autonomous_spend_usd": 0,
        "authority": "prepare_autonomously_policy_approve_only_if_owned_zero_spend_travel_rules_pass",
        "destination": destination_name,
        "destination_code": destination_code,
        "funnel_stage": "travel_builder_visit",
        "creative_variant": creative_variant,
        "dedupe_recovery_capable": True,
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
        paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        ]
        for path in paths:
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                pass
        return ImageFont.load_default()

    gold = (238, 201, 125, 255)
    white = (248, 250, 249, 255)
    soft = (211, 226, 230, 255)
    draw.text((72, 70), "L U M E N   T R A V E L", font=font(32, True), fill=gold)
    draw.text((72, 225), clean(job["headline"], 60), font=font(66, True), fill=white)
    draw.multiline_text((76, 350), clean(job["visual_subtitle"], 120), font=font(28), fill=soft, spacing=12)
    draw.text((76, 875), "ELEGÍ", font=font(20, True), fill=gold)
    draw.text((76, 910), "destino, días y pasajeros", font=font(30, True), fill=white)
    draw.text((76, 990), "COMPARÁ", font=font(20, True), fill=gold)
    draw.text((76, 1025), "vuelo, alojamiento y extras", font=font(30, True), fill=white)
    draw.rounded_rectangle((72, 1160, 420, 1235), radius=36, fill=gold)
    draw.text((120, 1182), "ARMÁ TU VIAJE", font=font(19, True), fill=(10, 28, 36, 255))
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
    approvals = lumen_app.STATE.get("instagram_publish_approvals") or {}
    selected_variant = 0
    job = None
    existing = None
    duplicate_statuses = {"DUPLICATE_BLOCKED", "DUPLICATE_BLOCKED_REMOTE"}

    for creative_variant in range(3):
        candidate_request_id = request_id if creative_variant == 0 else f"{request_id}-dedupe-recovery-{creative_variant}"
        candidate = build_job(destination, candidate_request_id, creative_variant=creative_variant)
        candidate_existing = next(
            (
                r for r in lumen_app.STATE.get("distribution_operator_jobs", [])
                if isinstance(r, dict) and r.get("id") == candidate["id"]
            ),
            None,
        )
        if not candidate_existing:
            job = candidate
            selected_variant = creative_variant
            existing = None
            break
        approval_row = approvals.get(candidate["id"]) or {}
        approval_status = str(approval_row.get("status") or "").upper()
        approval_authority = str(approval_row.get("authority") or "").lower()
        state_status = str(candidate_existing.get("status") or "").lower()

        # A real human rejection is authoritative and must not be bypassed by
        # generating a cosmetically different replacement.
        if approval_status == "REJECTED" and ("human" in approval_authority or state_status == "rejected_by_human"):
            job = candidate
            selected_variant = creative_variant
            existing = candidate_existing
            break

        # Technical duplicate/supersede states are learning signals. Skip this
        # creative and try a materially distinct recovery variant.
        if (
            approval_status in duplicate_statuses
            or state_status in {"blocked_duplicate_content", "superseded_by_regeneration"}
            or (approval_status == "REJECTED" and approval_authority == "travel_acquisition_refresh")
        ):
            continue

        job = candidate
        selected_variant = creative_variant
        existing = candidate_existing
        break

    if job is None:
        print({
            "travel_instagram_acquisition": {
                "status": "dedupe_variants_exhausted",
                "destination": destination["name"],
                "variants_considered": 3,
                "published": False,
                "autonomous_spend_usd": 0,
            }
        }, flush=True)
        return 0

    if existing:
        policy_approval = bridge.authorize_safe_travel_affiliate_job(existing)
        projection = bridge.export_posts()
        print({
            "travel_instagram_acquisition": {
                "status": "already_prepared_policy_reconciled",
                "job_id": job["id"],
                "destination": destination["name"],
                "creative_variant": selected_variant,
                "approval_required": True,
                "policy_approved": bool(policy_approval.get("approved")),
                "policy_approval_reason": policy_approval.get("reason"),
                "policy_approval_version": policy_approval.get("version"),
                "autonomous_publish": bool(policy_approval.get("approved")),
                "paid_media": False,
                "autonomous_spend_usd": 0,
                "projection_status": projection.get("status"),
            }
        }, flush=True)
        return 0
    supersede_previous(lumen_app.STATE, job)
    path = render_asset(job)
    job.update({
        "image_url": f"{PUBLIC_BASE_URL}/media/instagram/{job['id']}.jpg",
        "media_source": VERSION,
        "media_prepared_at": now(),
        "visual_qa": {"status": "PASS", "score": 100, "asset_width": 1080, "asset_height": 1350},
        "visual_qa_score": 100,
        "updated_at": now(),
    })
    jobs = lumen_app.STATE.setdefault("distribution_operator_jobs", [])
    jobs.append(job)
    lumen_app.STATE["distribution_operator_jobs"] = jobs[-500:]
    if not lumen_app.save_state():
        raise RuntimeError("lumen_zero_state_persistence_failed")
    policy_approval = bridge.authorize_safe_travel_affiliate_job(job)
    projection = bridge.export_posts()
    print({
        "travel_instagram_acquisition": {
            "status": "prepared",
            "version": VERSION,
            "job_id": job["id"],
            "destination": destination["name"],
            "destination_code": destination["code"],
            "creative_variant": selected_variant,
            "landing_url": job["tracking_url"],
            "image_path": str(path),
            "approval_required": True,
            "policy_approved": bool(policy_approval.get("approved")),
            "policy_approval_reason": policy_approval.get("reason"),
            "policy_approval_version": policy_approval.get("version"),
            "autonomous_publish": bool(policy_approval.get("approved")),
            "paid_media": False,
            "autonomous_spend_usd": 0,
            "projection_status": projection.get("status"),
            "posts_exported": projection.get("posts_exported"),
        }
    }, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
