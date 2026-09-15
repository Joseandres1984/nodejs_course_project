from __future__ import annotations

import hashlib
import html
import io
import os
import secrets
import textwrap
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from PIL import Image, ImageDraw, ImageFont

import distribution_operator
import social_distribution
from app import STATE, auth, load_state, save_state
from outbound_web import app


VERSION = "1.0-human-approved-instagram-publishing"
PUBLIC_BASE_URL = (os.getenv("LUMEN_PUBLIC_BASE_URL") or "https://lumen-web-production-5755.up.railway.app").strip().rstrip("/")
APPROVAL_TTL_HOURS = max(1, min(72, int(os.getenv("LUMEN_INSTAGRAM_APPROVAL_TTL_HOURS", "24"))))
MAX_PUBLISH_ATTEMPTS = max(1, min(5, int(os.getenv("LUMEN_INSTAGRAM_PUBLISH_MAX_ATTEMPTS", "3"))))

# social_distribution historically used the Meta-wide graph variable while the direct Instagram
# connector already uses LUMEN_INSTAGRAM_* credentials. Accept the Instagram-specific version name
# as a safe compatibility alias without copying or exposing any secret.
if not social_distribution.META_GRAPH_VERSION:
    social_distribution.META_GRAPH_VERSION = (
        os.getenv("LUMEN_INSTAGRAM_GRAPH_VERSION", "").strip()
        or os.getenv("LUMEN_META_GRAPH_VERSION", "").strip()
        or "v26.0"
    )

_ORIGINAL_DISPATCH_SOCIAL = social_distribution.dispatch_social
_ORIGINAL_DISTRIBUTION_TICK = distribution_operator.distribution_operator_tick


def utcnow_dt() -> datetime:
    return datetime.now(timezone.utc)


def utcnow() -> str:
    return utcnow_dt().isoformat()


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _parse_dt(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


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


def _job_by_id(state: Dict[str, Any], job_id: str) -> Optional[Dict[str, Any]]:
    return next(
        (
            row for row in state.get("distribution_operator_jobs", []) or []
            if isinstance(row, dict) and str(row.get("id") or "") == str(job_id)
        ),
        None,
    )


def _content_fingerprint(job: Dict[str, Any]) -> str:
    parts = [
        str(job.get("id") or ""),
        str(job.get("campaign_id") or ""),
        str(job.get("variant_id") or ""),
        str(job.get("audience") or ""),
        str(job.get("copy") or ""),
        str(job.get("tracking_url") or ""),
        str(job.get("creative_asset_url") or ""),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _media_url(job: Dict[str, Any]) -> str:
    token = _content_fingerprint(job)[:16]
    return f"{PUBLIC_BASE_URL}/media/instagram/{job.get('id')}.jpg?v={token}"


def _ensure_media_url(job: Dict[str, Any]) -> bool:
    if str(job.get("channel") or "") != "instagram":
        return False
    if str(job.get("image_url") or job.get("creative_asset_url") or "").strip():
        return False
    job["image_url"] = _media_url(job)
    job["media_source"] = "lumen_generated_public_jpeg"
    job["media_prepared_at"] = utcnow()
    return True


def _ensure_nonce(job: Dict[str, Any]) -> bool:
    if str(job.get("publish_nonce") or "").strip():
        return False
    job["publish_nonce"] = secrets.token_urlsafe(24)
    return True


def _approval_valid(state: Dict[str, Any], job: Dict[str, Any]) -> bool:
    job_id = str(job.get("id") or "")
    row = _approval_store(state).get(job_id) or {}
    if row.get("status") == "PUBLISHED":
        return True
    if row.get("status") not in {"APPROVED", "APPROVED_WAITING_CONNECTOR", "APPROVED_RETRY"}:
        return False
    if str(row.get("content_fingerprint") or "") != _content_fingerprint(job):
        row["status"] = "CONTENT_CHANGED"
        row["invalidated_at"] = utcnow()
        return False
    expires = _parse_dt(row.get("expires_at"))
    if expires is None or utcnow_dt() >= expires:
        row["status"] = "EXPIRED"
        row["expired_at"] = utcnow()
        return False
    return True


def _receipt_for_job(state: Dict[str, Any], job_id: str) -> Optional[Dict[str, Any]]:
    return next(
        (
            row for row in state.get("distribution_receipts", []) or []
            if isinstance(row, dict)
            and str(row.get("distribution_job_id") or "") == str(job_id)
            and (row.get("external_post_id") or row.get("external_url"))
        ),
        None,
    )


def _append_audit(state: Dict[str, Any], row: Dict[str, Any]) -> None:
    audit = state.setdefault("instagram_publish_audit", [])
    audit.append({"ts": utcnow(), **row})
    state["instagram_publish_audit"] = audit[-500:]


def _instagram_connector_ready() -> bool:
    status = social_distribution.connector_status()
    return bool((status.get("instagram", {}) or {}).get("ready"))


def attempt_publish_approved(state: Dict[str, Any], job_id: str) -> Dict[str, Any]:
    job = _job_by_id(state, job_id)
    if not job or str(job.get("channel") or "") != "instagram":
        return {"ok": False, "status": "NOT_FOUND"}

    _ensure_media_url(job)
    approvals = _approval_store(state)
    approval = approvals.get(str(job_id)) or {}

    receipt = _receipt_for_job(state, job_id)
    if receipt:
        approval["status"] = "PUBLISHED"
        approval["published_at"] = receipt.get("published_at") or receipt.get("received_at") or utcnow()
        approval["external_post_id"] = receipt.get("external_post_id")
        approvals[str(job_id)] = approval
        job["status"] = "verified_published"
        return {"ok": True, "status": "PUBLISHED", "idempotent": True}

    if not _approval_valid(state, job):
        job["status"] = "awaiting_human_approval"
        return {"ok": False, "status": "AWAITING_HUMAN_APPROVAL"}

    attempts = int(approval.get("attempts") or 0)
    if attempts >= MAX_PUBLISH_ATTEMPTS:
        approval["status"] = "MAX_ATTEMPTS_REACHED"
        job["status"] = "approved_publish_failed"
        return {"ok": False, "status": "MAX_ATTEMPTS_REACHED"}

    status = social_distribution.connector_status()
    if not bool((status.get("instagram", {}) or {}).get("ready")):
        approval["status"] = "APPROVED_WAITING_CONNECTOR"
        approval["last_checked_at"] = utcnow()
        job["status"] = "approved_waiting_connector"
        return {"ok": False, "status": "APPROVED_WAITING_CONNECTOR"}

    image_url = str(job.get("image_url") or job.get("creative_asset_url") or "").strip()
    if not image_url.startswith("https://"):
        approval["status"] = "APPROVED_WAITING_MEDIA"
        job["status"] = "approved_waiting_media"
        return {"ok": False, "status": "APPROVED_WAITING_MEDIA"}

    # Keep the existing canary ceiling even for an explicitly approved publication.
    if social_distribution._daily_successes(state) >= social_distribution.MAX_PER_DAY:
        approval["status"] = "APPROVED_DAILY_CAP"
        job["status"] = "approved_daily_cap_reached"
        return {"ok": False, "status": "APPROVED_DAILY_CAP"}

    approval["attempts"] = attempts + 1
    approval["last_attempt_at"] = utcnow()
    job["last_attempt_at"] = utcnow()
    job["attempts"] = int(job.get("attempts") or 0) + 1

    try:
        result = social_distribution._publish(job, status)
        social_distribution._record_receipt(state, job, result)
        approval["status"] = "PUBLISHED"
        approval["published_at"] = utcnow()
        approval["provider"] = result.get("provider")
        approval["external_post_id"] = result.get("external_post_id")
        approval["external_url"] = result.get("external_url")
        approval["last_error"] = None
        _append_audit(
            state,
            {
                "status": "PUBLISHED",
                "job_id": job_id,
                "provider": result.get("provider"),
                "external_post_id": result.get("external_post_id"),
                "authority": "explicit_human_approval",
            },
        )
        return {"ok": True, "status": "PUBLISHED", "external_post_id": result.get("external_post_id")}
    except Exception as exc:
        safe_error = f"{type(exc).__name__}: {str(exc)[:400]}"
        approval["last_error"] = safe_error
        approval["status"] = "APPROVED_RETRY" if approval["attempts"] < MAX_PUBLISH_ATTEMPTS else "MAX_ATTEMPTS_REACHED"
        job["status"] = "approved_publish_failed"
        job["last_error"] = safe_error
        _append_audit(
            state,
            {
                "status": "PUBLISH_FAILED",
                "job_id": job_id,
                "attempt": approval["attempts"],
                "error": safe_error,
                "authority": "explicit_human_approval",
            },
        )
        return {"ok": False, "status": approval["status"], "error": safe_error}


def instagram_publish_control_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    jobs = [
        row for row in state.get("distribution_operator_jobs", []) or []
        if isinstance(row, dict) and str(row.get("channel") or "") == "instagram"
    ]
    prepared = approvals_valid = published = waiting_connector = attempted = 0
    for job in jobs:
        if _ensure_media_url(job):
            prepared += 1
        if _approval_valid(state, job):
            approvals_valid += 1
            before = int((_approval_store(state).get(str(job.get("id") or "")) or {}).get("attempts") or 0)
            result = attempt_publish_approved(state, str(job.get("id") or ""))
            after = int((_approval_store(state).get(str(job.get("id") or "")) or {}).get("attempts") or 0)
            if after > before:
                attempted += 1
            if result.get("status") == "PUBLISHED":
                published += 1
            elif result.get("status") == "APPROVED_WAITING_CONNECTOR":
                waiting_connector += 1
    snapshot = {
        "version": VERSION,
        "status": "active",
        "jobs_total": len(jobs),
        "media_prepared_this_tick": prepared,
        "valid_approvals": approvals_valid,
        "publish_attempts_this_tick": attempted,
        "published_total": sum(1 for job in jobs if _receipt_for_job(state, str(job.get("id") or ""))),
        "published_this_tick": published,
        "waiting_connector": waiting_connector,
        "connector_configured": _instagram_connector_ready(),
        "approval_required_per_post": True,
        "approval_ttl_hours": APPROVAL_TTL_HOURS,
        "max_attempts": MAX_PUBLISH_ATTEMPTS,
        "binding_rule": "LUMEN prepares; only an explicit human approval may authorize one immutable Instagram post",
        "updated_at": utcnow(),
    }
    state["instagram_publish_control"] = snapshot
    return snapshot


def _approval_gated_dispatch(state: Dict[str, Any]) -> Dict[str, Any]:
    # Mask every unapproved Instagram job from the legacy autonomous social dispatcher. This makes
    # the human-approval rule fail-closed even if LIVE_OUTBOUND or connector variables are enabled later.
    masked: list[tuple[Dict[str, Any], str]] = []
    for job in state.get("distribution_operator_jobs", []) or []:
        if not isinstance(job, dict) or str(job.get("channel") or "") != "instagram":
            continue
        if job.get("status") == "verified_published" or _receipt_for_job(state, str(job.get("id") or "")):
            continue
        _ensure_media_url(job)
        if not _approval_valid(state, job):
            masked.append((job, "instagram"))
            job["channel"] = "instagram_pending_human_approval"
    try:
        stats = dict(_ORIGINAL_DISPATCH_SOCIAL(state) or {})
    finally:
        for job, channel in masked:
            job["channel"] = channel
            if not _receipt_for_job(state, str(job.get("id") or "")):
                job["status"] = "awaiting_human_approval"
    stats["awaiting_human_approval"] = len(masked)
    stats["approval_required_per_instagram_post"] = True
    state["social_distribution"] = stats
    return stats


social_distribution.dispatch_social = _approval_gated_dispatch


def _distribution_tick_with_publish_control(state: Dict[str, Any], *args: Any, **kwargs: Any) -> Dict[str, Any]:
    report = dict(_ORIGINAL_DISTRIBUTION_TICK(state, *args, **kwargs) or {})
    control = instagram_publish_control_tick(state)
    report["instagram_publish_control"] = control
    state["distribution_operator"] = report
    return report


distribution_operator.distribution_operator_tick = _distribution_tick_with_publish_control


def _font(size: int, bold: bool = False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _render_job_jpeg(job: Dict[str, Any]) -> bytes:
    width = height = 1080
    image = Image.new("RGB", (width, height), (6, 17, 23))
    draw = ImageDraw.Draw(image)
    # Quiet LUMEN visual language: dark field, subtle geometric panels and one high-contrast accent.
    draw.rounded_rectangle((58, 58, 1022, 1022), radius=54, fill=(11, 29, 37), outline=(35, 64, 75), width=3)
    draw.rounded_rectangle((80, 80, 1000, 188), radius=32, fill=(215, 255, 100))
    draw.text((112, 108), "LUMEN B2B", font=_font(48, True), fill=(7, 16, 24))

    audience = str(job.get("audience") or "B2B").strip().upper()
    draw.text((92, 235), audience, font=_font(28, True), fill=(170, 191, 200))

    raw = " ".join(str(job.get("copy") or "").split())
    headline = raw.split(". ", 1)[0].strip() if raw else "Oportunidades B2B con más evidencia."
    headline = headline[:190]
    lines = textwrap.wrap(headline, width=28)[:5]
    y = 300
    title_font = _font(62, True)
    for line in lines:
        draw.text((92, y), line, font=title_font, fill=(238, 245, 248))
        y += 78

    body = "LUMEN investiga, compara y organiza oportunidades comerciales para compradores y proveedores."
    body_lines = textwrap.wrap(body, width=48)
    y = max(y + 36, 700)
    for line in body_lines[:4]:
        draw.text((92, y), line, font=_font(34), fill=(183, 203, 211))
        y += 48

    draw.text((92, 952), "lumen.b2b", font=_font(30, True), fill=(215, 255, 100))
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=92, optimize=True, progressive=True)
    return output.getvalue()


@app.get("/media/instagram/{job_id}.jpg", include_in_schema=False)
def instagram_public_media(job_id: str):
    if not load_state():
        raise HTTPException(status_code=503, detail="state_unavailable")
    job = _job_by_id(STATE, job_id)
    if not job or str(job.get("channel") or "") != "instagram":
        raise HTTPException(status_code=404, detail="media_not_found")
    content = _render_job_jpeg(job)
    return Response(
        content=content,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=300", "X-Lumen-Media": "instagram-prepared"},
    )


@app.get("/health/instagram/publishing", include_in_schema=False)
def instagram_publishing_health():
    loaded = load_state()
    if loaded:
        changed = False
        for job in STATE.get("distribution_operator_jobs", []) or []:
            if isinstance(job, dict) and str(job.get("channel") or "") == "instagram":
                changed = _ensure_media_url(job) or changed
        if changed:
            save_state()
    control = dict(STATE.get("instagram_publish_control", {}) or {})
    jobs = [
        row for row in STATE.get("distribution_operator_jobs", []) or []
        if isinstance(row, dict) and str(row.get("channel") or "") == "instagram"
    ]
    approvals = _approval_store(STATE)
    return {
        "ok": bool(loaded),
        "version": VERSION,
        "connector_configured": _instagram_connector_ready(),
        "prepared_jobs": len(jobs),
        "pending_human_approval": sum(1 for job in jobs if not _approval_valid(STATE, job) and not _receipt_for_job(STATE, str(job.get("id") or ""))),
        "valid_approvals": sum(1 for job in jobs if _approval_valid(STATE, job)),
        "published": sum(1 for job in jobs if _receipt_for_job(STATE, str(job.get("id") or ""))),
        "approval_records": len(approvals),
        "approval_required_per_post": True,
        "approval_ttl_hours": APPROVAL_TTL_HOURS,
        "last_tick": control.get("updated_at"),
    }


def _status_for_job(state: Dict[str, Any], job: Dict[str, Any]) -> str:
    if _receipt_for_job(state, str(job.get("id") or "")):
        return "Publicado y verificado"
    approval = _approval_store(state).get(str(job.get("id") or "")) or {}
    status = str(approval.get("status") or "")
    labels = {
        "APPROVED": "Aprobado · listo para publicar",
        "APPROVED_WAITING_CONNECTOR": "Aprobado · esperando conector Meta",
        "APPROVED_RETRY": "Aprobado · reintento pendiente",
        "APPROVED_DAILY_CAP": "Aprobado · cupo diario alcanzado",
        "PUBLISHED": "Publicado y verificado",
        "REJECTED": "Descartado",
        "EXPIRED": "Aprobación vencida",
        "CONTENT_CHANGED": "Contenido cambió · requiere nueva aprobación",
        "MAX_ATTEMPTS_REACHED": "Publicación falló · requiere revisión",
    }
    if status in labels:
        return labels[status]
    return "Listo para tu aprobación" if _instagram_connector_ready() else "Preparado · falta autorización final de Meta"


@app.get("/instagram/publishing", response_class=HTMLResponse, include_in_schema=False)
def instagram_publishing_dashboard(_=Depends(auth)):
    if not load_state():
        raise HTTPException(status_code=503, detail="state_unavailable")
    changed = False
    jobs = [
        row for row in STATE.get("distribution_operator_jobs", []) or []
        if isinstance(row, dict) and str(row.get("channel") or "") == "instagram"
    ]
    jobs.sort(key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""), reverse=True)
    for job in jobs:
        changed = _ensure_media_url(job) or changed
        changed = _ensure_nonce(job) or changed
    if changed:
        save_state()

    connector_ready = _instagram_connector_ready()
    cards = []
    for job in jobs:
        job_id = str(job.get("id") or "")
        receipt = _receipt_for_job(STATE, job_id)
        approval = _approval_store(STATE).get(job_id) or {}
        can_approve = not receipt
        last_error = str(approval.get("last_error") or job.get("last_error") or "").strip()
        controls = ""
        if can_approve:
            controls = f"""
            <div class='actions'>
              <form method='post' action='/api/instagram/publishing/{_esc(job_id)}/approve'>
                <input type='hidden' name='nonce' value='{_esc(job.get('publish_nonce'))}'>
                <button class='publish' type='submit'>APROBAR Y PUBLICAR</button>
              </form>
              <form method='post' action='/api/instagram/publishing/{_esc(job_id)}/reject'>
                <input type='hidden' name='nonce' value='{_esc(job.get('publish_nonce'))}'>
                <button class='reject' type='submit'>Descartar</button>
              </form>
            </div>"""
        cards.append(f"""
        <article class='post'>
          <img src='{_esc(job.get('image_url'))}' alt='Vista previa LUMEN'>
          <div class='content'>
            <div class='meta'>{_esc(job.get('audience') or 'B2B')} · {_esc(job.get('campaign_id'))}</div>
            <h2>{_esc(_status_for_job(STATE, job))}</h2>
            <pre>{_esc(social_distribution._text(job))}</pre>
            <div class='small'>ID: {_esc(job_id)} · Aprobación válida por {APPROVAL_TTL_HOURS} h y ligada exactamente a este contenido.</div>
            {f"<div class='error'>{_esc(last_error)}</div>" if last_error else ""}
            {controls}
          </div>
        </article>""")

    rows = "".join(cards) or "<div class='empty'>Todavía no hay publicaciones de Instagram preparadas.</div>"
    connector_text = "CONECTOR LISTO" if connector_ready else "CONECTOR PENDIENTE"
    return HTMLResponse(f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>LUMEN · Publicaciones Instagram</title>
<style>
body{{font-family:Arial,sans-serif;background:#061117;color:#e8f0f4;margin:0}}main{{max-width:1100px;margin:auto;padding:22px}}a{{color:#d7ff64}}.hero{{background:#0b1d25;border:1px solid #23404b;border-radius:18px;padding:18px;margin-bottom:16px}}.state{{font-weight:900;color:{'#d7ff64' if connector_ready else '#ffcc66'}}}.post{{display:grid;grid-template-columns:minmax(230px,360px) 1fr;gap:18px;background:#0b1d25;border:1px solid #23404b;border-radius:18px;padding:16px;margin:14px 0}}.post img{{width:100%;aspect-ratio:1/1;object-fit:cover;border-radius:14px;background:#071018}}h1,h2{{margin:.3em 0}}pre{{white-space:pre-wrap;font-family:Arial,sans-serif;line-height:1.45;background:#07151b;border-radius:12px;padding:14px;color:#dbe8ed}}.meta,.small{{color:#9fb2bb;font-size:12px}}.actions{{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px}}form{{margin:0}}button{{border:0;border-radius:10px;padding:12px 16px;font-weight:900;cursor:pointer}}.publish{{background:#d7ff64;color:#071018}}.reject{{background:#263b44;color:#e8f0f4}}.error{{margin-top:10px;padding:10px;border-radius:10px;background:#3a1e22;color:#ffc6cc;font-size:12px}}.empty{{padding:24px;background:#0b1d25;border-radius:18px}}@media(max-width:760px){{.post{{grid-template-columns:1fr}}}}
</style></head><body><main>
<p><a href='/command-center'>← Command Center</a> · <a href='/instagram'>Instagram Operator</a></p>
<section class='hero'><h1>Instagram · Publicaciones</h1><p>LUMEN prepara el contenido y la imagen. <strong>No publica por sí solo.</strong> Cada post necesita tu orden explícita.</p><p class='state'>{connector_text}</p><div class='small'>Una aprobación autoriza únicamente el contenido mostrado; si cambia el copy o el activo, la aprobación se invalida. Sin gastos publicitarios.</div></section>
{rows}
</main></body></html>""")


@app.post("/api/instagram/publishing/{job_id}/approve", include_in_schema=False)
def approve_instagram_publish(job_id: str, nonce: str = Form(...), _=Depends(auth)):
    if not load_state():
        raise HTTPException(status_code=503, detail="state_unavailable")
    job = _job_by_id(STATE, job_id)
    if not job or str(job.get("channel") or "") != "instagram":
        raise HTTPException(status_code=404, detail="job_not_found")
    expected = str(job.get("publish_nonce") or "")
    if not expected or not secrets.compare_digest(expected, str(nonce or "")):
        raise HTTPException(status_code=409, detail="approval_token_invalid_or_already_used")

    _ensure_media_url(job)
    now = utcnow_dt()
    approval = {
        "job_id": job_id,
        "status": "APPROVED",
        "approved_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=APPROVAL_TTL_HOURS)).isoformat(),
        "approved_by": "authenticated_human_operator",
        "content_fingerprint": _content_fingerprint(job),
        "attempts": 0,
        "last_error": None,
        "authority": "single_post_explicit_human_approval",
    }
    _approval_store(STATE)[job_id] = approval
    job["publish_nonce"] = secrets.token_urlsafe(24)
    job["status"] = "approved"
    _append_audit(STATE, {"status": "APPROVED", "job_id": job_id, "authority": "explicit_human_approval"})
    save_state()

    result = attempt_publish_approved(STATE, job_id)
    save_state()
    code = str(result.get("status") or "UNKNOWN")
    return RedirectResponse(url=f"/instagram/publishing?result={code}", status_code=303)


@app.post("/api/instagram/publishing/{job_id}/reject", include_in_schema=False)
def reject_instagram_publish(job_id: str, nonce: str = Form(...), _=Depends(auth)):
    if not load_state():
        raise HTTPException(status_code=503, detail="state_unavailable")
    job = _job_by_id(STATE, job_id)
    if not job or str(job.get("channel") or "") != "instagram":
        raise HTTPException(status_code=404, detail="job_not_found")
    expected = str(job.get("publish_nonce") or "")
    if not expected or not secrets.compare_digest(expected, str(nonce or "")):
        raise HTTPException(status_code=409, detail="approval_token_invalid_or_already_used")
    _approval_store(STATE)[job_id] = {
        "job_id": job_id,
        "status": "REJECTED",
        "rejected_at": utcnow(),
        "content_fingerprint": _content_fingerprint(job),
        "authority": "explicit_human_rejection",
    }
    job["publish_nonce"] = secrets.token_urlsafe(24)
    job["status"] = "rejected_by_human"
    _append_audit(STATE, {"status": "REJECTED", "job_id": job_id, "authority": "explicit_human_rejection"})
    save_state()
    return RedirectResponse(url="/instagram/publishing?result=REJECTED", status_code=303)


print(
    {
        "instagram_publish_control": {
            "version": VERSION,
            "status": "installed",
            "approval_required_per_post": True,
            "approval_ttl_hours": APPROVAL_TTL_HOURS,
            "max_publish_attempts": MAX_PUBLISH_ATTEMPTS,
            "connector_configured": _instagram_connector_ready(),
            "media_renderer": "public_jpeg",
            "autonomous_publish": False,
        }
    },
    flush=True,
)
