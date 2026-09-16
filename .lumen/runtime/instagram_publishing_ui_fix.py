from __future__ import annotations

"""Professional approval cockpit for LUMEN Instagram publishing.

The publishing backend remains owned by instagram_publish_control. This module replaces only the
GET dashboard so editorial intent, QA, expired approvals and 4:5 previews are clear before the
human authorizes one immutable publication.
"""

from typing import Any

from fastapi import Depends, HTTPException, Query
from fastapi.responses import HTMLResponse

import instagram_publish_control as ipc

VERSION = "1.1-instagram-pro-publishing-ui"


def _remove_old_dashboard_route() -> None:
    kept = []
    for route in list(ipc.app.router.routes):
        path = getattr(route, "path", None)
        methods = set(getattr(route, "methods", set()) or set())
        endpoint = getattr(route, "endpoint", None)
        if path == "/instagram/publishing" and "GET" in methods and getattr(endpoint, "__name__", "") in {"instagram_publishing_dashboard", "instagram_publishing_dashboard_fixed"}:
            continue
        kept.append(route)
    ipc.app.router.routes[:] = kept


def _action_label(status: str) -> str:
    return {
        "EXPIRED": "RENOVAR APROBACIÓN Y PUBLICAR",
        "CONTENT_CHANGED": "APROBAR NUEVA VERSIÓN Y PUBLICAR",
        "REJECTED": "VOLVER A APROBAR Y PUBLICAR",
        "APPROVED_WAITING_CONNECTOR": "REINTENTAR PUBLICACIÓN",
        "APPROVED_RETRY": "REINTENTAR PUBLICACIÓN",
        "APPROVED_DAILY_CAP": "REINTENTAR PUBLICACIÓN",
    }.get(status, "APROBAR Y PUBLICAR")


def _can_approve(status: str, receipt: Any) -> bool:
    if receipt:
        return False
    return status != "MAX_ATTEMPTS_REACHED"


def _chip(text: str, kind: str = "") -> str:
    if not text:
        return ""
    return f"<span class='chip {ipc._esc(kind)}'>{ipc._esc(text)}</span>"


_remove_old_dashboard_route()


@ipc.app.get("/instagram/publishing", response_class=HTMLResponse, include_in_schema=False)
def instagram_publishing_dashboard_fixed(
    result: str = Query(""),
    _=Depends(ipc.auth),
):
    if not ipc.load_state():
        raise HTTPException(status_code=503, detail="state_unavailable")

    changed = False
    jobs = [
        row for row in ipc.STATE.get("distribution_operator_jobs", []) or []
        if isinstance(row, dict) and str(row.get("channel") or "") == "instagram"
    ]
    jobs.sort(key=lambda row: str(row.get("editorial_slot") or row.get("updated_at") or row.get("created_at") or ""), reverse=True)

    for job in jobs:
        changed = ipc._ensure_media_url(job) or changed
        changed = ipc._ensure_nonce(job) or changed
        ipc._approval_valid(ipc.STATE, job)
    if changed:
        ipc.save_state()

    connector_ready = ipc._instagram_connector_ready()
    cards: list[str] = []
    for job in jobs:
        job_id = str(job.get("id") or "")
        receipt = ipc._receipt_for_job(ipc.STATE, job_id)
        approval = ipc._approval_store(ipc.STATE).get(job_id) or {}
        approval_status = str(approval.get("status") or "")
        status_label = ipc._status_for_job(ipc.STATE, job)
        last_error = str(approval.get("last_error") or job.get("last_error") or "").strip()
        fingerprint = ipc._content_fingerprint(job)[:16]
        image_url = str(job.get("image_url") or "")
        joiner = "&" if "?" in image_url else "?"
        preview_url = f"{image_url}{joiner}preview={fingerprint}" if image_url else ""

        controls = ""
        if _can_approve(approval_status, receipt):
            label = _action_label(approval_status)
            controls = f"""
            <div class='actions'>
              <form method='post' action='/api/instagram/publishing/{ipc._esc(job_id)}/approve'>
                <input type='hidden' name='nonce' value='{ipc._esc(job.get('publish_nonce'))}'>
                <button class='publish' type='submit'>{ipc._esc(label)}</button>
              </form>
              <form method='post' action='/api/instagram/publishing/{ipc._esc(job_id)}/reject'>
                <input type='hidden' name='nonce' value='{ipc._esc(job.get('publish_nonce'))}'>
                <button class='reject' type='submit'>Descartar</button>
              </form>
            </div>"""
        elif approval_status == "MAX_ATTEMPTS_REACHED" and not receipt:
            controls = "<div class='review'>Revisión requerida: se alcanzó el máximo de intentos. LUMEN no volverá a publicar esta pieza hasta corregir la causa.</div>"

        state_class = "published" if receipt else "expired" if approval_status in {"EXPIRED", "CONTENT_CHANGED"} else "errorstate" if approval_status == "MAX_ATTEMPTS_REACHED" else "ready"
        pillar = str(job.get("content_pillar") or "").replace("_", " ").upper()
        strategy = str(job.get("editorial_strategy") or "").replace("_", " ")
        qa = job.get("editorial_qa_score")
        format_name = str(job.get("format") or "").replace("instagram_feed_", "feed ")
        chips = "".join([
            _chip(pillar),
            _chip(f"QA {qa}/100", "good") if qa is not None else "",
            _chip(format_name.upper()),
            _chip(strategy.upper()) if strategy else "",
        ])
        editorial_note = ""
        if job.get("editorial_pro_v1"):
            editorial_note = (
                "<div class='editorial-note'><strong>Sistema Pro:</strong> pieza preparada con pilar editorial, "
                "caption estructurado, hashtags contextuales, control anti-repetición y QA previo.</div>"
            )

        cards.append(f"""
        <article class='post {state_class}'>
          <div class='visual'><img src='{ipc._esc(preview_url)}' alt='Vista previa LUMEN'><div class='chips'>{chips}</div></div>
          <div class='content'>
            <div class='meta'>{ipc._esc(job.get('creative_label') or job.get('audience') or 'B2B')} · {ipc._esc(job.get('editorial_slot') or job.get('campaign_id'))}</div>
            <h2>{ipc._esc(status_label)}</h2>
            {editorial_note}
            <div class='caption-title'>CAPTION FINAL</div>
            <pre>{ipc._esc(ipc.social_distribution._text(job))}</pre>
            <div class='small'>ID: {ipc._esc(job_id)} · La aprobación dura {ipc.APPROVAL_TTL_HOURS} h y queda ligada exactamente a este contenido y diseño.</div>
            {f"<div class='error'>{ipc._esc(last_error)}</div>" if last_error else ""}
            {controls}
          </div>
        </article>""")

    rows = "".join(cards) or "<div class='empty'>Todavía no hay publicaciones de Instagram preparadas.</div>"
    connector_text = "CONECTOR LISTO" if connector_ready else "CONECTOR PENDIENTE"
    banner = ""
    if result:
        result_label = {
            "PUBLISHED": "Publicación confirmada por Instagram.",
            "REJECTED": "Publicación descartada.",
        }.get(result, f"Resultado de publicación: {result}")
        banner = f"<div class='result'>{ipc._esc(result_label)}</div>"

    system = ipc.STATE.get("instagram_editorial_system", {}) or {}
    today = system.get("today", {}) or {}
    system_line = ""
    if system:
        system_line = f"<div class='system-line'>Sistema Pro activo · calendario: 5 días hábiles · hoy: {ipc._esc(today.get('status') or 'activo')} · publicación externa: siempre con aprobación humana</div>"

    return HTMLResponse(f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>LUMEN · Publicaciones Instagram</title>
<style>
body{{font-family:Arial,sans-serif;background:#061117;color:#e8f0f4;margin:0}}main{{max-width:1180px;margin:auto;padding:22px}}a{{color:#d7ff64}}.hero{{background:#0b1d25;border:1px solid #23404b;border-radius:20px;padding:20px;margin-bottom:16px}}.state{{font-weight:900;color:{'#d7ff64' if connector_ready else '#ffcc66'}}}.system-line{{margin-top:10px;padding:10px 12px;background:#07151b;border-radius:10px;color:#b8cbd3;font-size:13px}}.post{{display:grid;grid-template-columns:minmax(280px,410px) 1fr;gap:22px;background:#0b1d25;border:1px solid #23404b;border-radius:20px;padding:18px;margin:16px 0}}.post.expired{{border-color:#8b6b22}}.post.errorstate{{border-color:#91434d}}.post.published{{border-color:#3f7d54}}.visual img{{width:100%;aspect-ratio:4/5;object-fit:cover;border-radius:16px;background:#071018;box-shadow:0 12px 36px rgba(0,0,0,.22)}}h1,h2{{margin:.3em 0}}pre{{white-space:pre-wrap;font-family:Arial,sans-serif;line-height:1.55;background:#07151b;border-radius:12px;padding:15px;color:#dbe8ed;border:1px solid #17313a}}.meta,.small{{color:#9fb2bb;font-size:12px}}.caption-title{{font-size:11px;letter-spacing:.14em;color:#d7ff64;font-weight:900;margin:14px 0 6px}}.editorial-note{{margin:12px 0;padding:11px 12px;border-left:3px solid #d7ff64;background:#07151b;color:#b9cbd2;font-size:13px}}.chips{{display:flex;gap:6px;flex-wrap:wrap;margin-top:9px}}.chip{{display:inline-block;padding:6px 8px;border-radius:999px;background:#17313a;color:#b8cbd3;font-size:10px;font-weight:800;letter-spacing:.04em}}.chip.good{{background:#1d3d2a;color:#c8f5d6}}.actions{{display:flex;gap:10px;flex-wrap:wrap;margin-top:16px}}form{{margin:0}}button{{border:0;border-radius:11px;padding:13px 17px;font-weight:900;cursor:pointer}}.publish{{background:#d7ff64;color:#071018}}.reject{{background:#263b44;color:#e8f0f4}}.error,.review{{margin-top:10px;padding:10px;border-radius:10px;background:#3a1e22;color:#ffc6cc;font-size:12px}}.result{{padding:12px 14px;border-radius:12px;background:#123321;border:1px solid #34784f;margin-bottom:14px}}.empty{{padding:24px;background:#0b1d25;border-radius:18px}}@media(max-width:780px){{.post{{grid-template-columns:1fr}}main{{padding:14px}}}}
</style></head><body><main>
<p><a href='/command-center'>← Command Center</a> · <a href='/instagram'>Instagram Operator</a></p>
<section class='hero'><h1>Instagram · Publicaciones Pro</h1><p>LUMEN genera concepto, diseño, caption y hashtags, pasa un control de calidad y te presenta la pieza terminada. <strong>No publica por sí solo.</strong></p><p class='state'>{connector_text}</p>{system_line}<div class='small'>Una aprobación autoriza únicamente la pieza mostrada. Si cambia el copy, el diseño o la versión del renderer, la aprobación se invalida.</div></section>
{banner}{rows}
</main></body></html>""")


print({"instagram_publishing_ui_fix": {"version": VERSION, "status": "active", "expired_approval_distinct": True, "preview_cache_busting": True, "pro_editorial_metadata": True, "preview_format": "4:5"}}, flush=True)
