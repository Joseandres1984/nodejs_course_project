from __future__ import annotations

"""LUMEN on-demand thematic Instagram preparation.

Owner-requested themes are converted into the same immutable Instagram jobs used by
LUMEN's professional editorial system. Preparation is autonomous; publication is
still fail-closed behind instagram_publish_control's explicit human approval gate.
"""

import hashlib
import html
import re
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from app import STATE, auth, load_state, save_state
from outbound_web import app
import instagram_publish_control as ipc
import instagram_pro_editorial_runtime as pro


VERSION = "1.0-instagram-thematic-on-demand"
MAX_THEMATIC_HISTORY = 120


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: Any, limit: int = 500) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _slug(value: str) -> str:
    text = _clean(value.lower(), 80)
    text = re.sub(r"[^a-z0-9áéíóúüñ]+", "-", text, flags=re.I).strip("-")
    return text or "tema"


def _theme_library() -> Dict[str, Dict[str, Any]]:
    return {
        "travel": {
            "label": "VIAJES / TURISMO",
            "headline": "El sector viajes también está lleno de oportunidades comerciales.",
            "subtitle": "Agencias, alojamientos, experiencias, traslados y proveedores turísticos generan conexiones que pueden convertirse en oportunidades B2B.",
            "caption": (
                "El mundo del turismo mueve mucho más que reservas: conecta agencias, alojamientos, experiencias, traslados, operadores y proveedores especializados.\n\n"
                "LUMEN puede investigar señales de mercado, detectar oportunidades comerciales y ayudar a ordenar alternativas dentro del ecosistema de viajes.\n\n"
                "Si trabajás en turismo o tenés un servicio vinculado al sector, escribinos por DM."
            ),
            "hashtags": ["#LUMENB2B", "#Turismo", "#Viajes", "#TravelBusiness", "#AgenciasDeViajes", "#OportunidadesComerciales", "#InteligenciaComercial"],
            "audience": "b2b",
            "pillar": "thematic_travel",
            "goal": "qualified_travel_business_conversation",
            "style": "matching_network",
            "cta": "HABLEMOS POR DM",
        },
        "technology": {
            "label": "TECNOLOGÍA / AUTOMATIZACIÓN",
            "headline": "La tecnología crea oportunidades cuando resuelve una necesidad real.",
            "subtitle": "Software, automatización, integraciones y servicios tecnológicos pueden encontrar mejor encaje cuando la demanda está bien definida.",
            "caption": (
                "La tecnología B2B no se trata solo de sumar herramientas. El valor aparece cuando una solución encaja con una necesidad concreta.\n\n"
                "LUMEN investiga señales públicas, organiza alternativas y ayuda a detectar oportunidades comerciales con más contexto.\n\n"
                "Si ofrecés tecnología, software o automatización para empresas, escribinos por DM."
            ),
            "hashtags": ["#LUMENB2B", "#Tecnologia", "#Automatizacion", "#SoftwareB2B", "#OportunidadesComerciales", "#VentasB2B", "#InteligenciaComercial"],
            "audience": "supplier",
            "pillar": "thematic_technology",
            "goal": "qualified_technology_business_conversation",
            "style": "evidence_grid",
            "cta": "CONTANOS QUÉ OFRECÉS",
        },
        "construction": {
            "label": "CONSTRUCCIÓN",
            "headline": "En construcción, una necesidad concreta puede abrir una cadena de oportunidades.",
            "subtitle": "Materiales, equipamiento, servicios y proveedores especializados pueden conectarse mejor cuando el requerimiento está claro.",
            "caption": (
                "Cada proyecto de construcción combina materiales, equipos, servicios y tiempos de entrega. Ahí aparecen múltiples oportunidades comerciales.\n\n"
                "LUMEN puede investigar alternativas, organizar proveedores y detectar señales de demanda con trazabilidad.\n\n"
                "Si tu empresa trabaja para el sector construcción, escribinos por DM."
            ),
            "hashtags": ["#LUMENB2B", "#Construccion", "#Proveedores", "#Materiales", "#Industria", "#OportunidadesComerciales", "#InteligenciaComercial"],
            "audience": "supplier",
            "pillar": "thematic_construction",
            "goal": "qualified_construction_business_conversation",
            "style": "matching_network",
            "cta": "MOSTRANOS QUÉ VENDÉS",
        },
        "industry": {
            "label": "INDUSTRIA",
            "headline": "La industria necesita proveedores que encajen con requerimientos reales.",
            "subtitle": "Equipos, repuestos, servicios y capacidades técnicas ganan valor cuando se comparan con contexto y evidencia.",
            "caption": (
                "Una necesidad industrial rara vez se resuelve mirando solo un precio. Especificación, plazo, capacidad y documentación también importan.\n\n"
                "LUMEN investiga mercado, organiza alternativas y busca encajes comerciales con más contexto.\n\n"
                "Si vendés productos o servicios para industria, escribinos por DM."
            ),
            "hashtags": ["#LUMENB2B", "#Industria", "#ProveedoresIndustriales", "#ComprasIndustriales", "#VentasB2B", "#OportunidadesComerciales", "#InteligenciaComercial"],
            "audience": "supplier",
            "pillar": "thematic_industry",
            "goal": "qualified_industry_business_conversation",
            "style": "procurement_radar",
            "cta": "HABLEMOS POR DM",
        },
        "import_export": {
            "label": "IMPORTACIÓN / EXPORTACIÓN",
            "headline": "Comercio exterior: más mercado también significa más variables para comparar.",
            "subtitle": "Proveedores, distribuidores, logística y condiciones comerciales necesitan contexto antes de convertirse en una oportunidad real.",
            "caption": (
                "Buscar oportunidades internacionales requiere más que encontrar un proveedor o un comprador. Hay que entender encaje, condiciones, logística y evidencia.\n\n"
                "LUMEN puede investigar señales públicas y organizar alternativas para abrir conversaciones comerciales con más criterio.\n\n"
                "Si trabajás en importación, exportación o distribución internacional, escribinos por DM."
            ),
            "hashtags": ["#LUMENB2B", "#ComercioExterior", "#Importacion", "#Exportacion", "#Distribucion", "#OportunidadesComerciales", "#InteligenciaComercial"],
            "audience": "partner",
            "pillar": "thematic_import_export",
            "goal": "qualified_trade_business_conversation",
            "style": "partner_channel",
            "cta": "ABRAMOS UNA CONVERSACIÓN",
        },
    }


def _custom_theme(theme: str) -> Dict[str, Any]:
    label = _clean(theme, 60).upper() or "NUEVO MERCADO"
    readable = _clean(theme, 60) or "este mercado"
    tag = re.sub(r"[^A-Za-z0-9ÁÉÍÓÚÜÑáéíóúüñ]", "", readable.title())[:36] or "Negocios"
    return {
        "label": label,
        "headline": f"También hay oportunidades comerciales por descubrir en {readable}.",
        "subtitle": f"LUMEN puede investigar señales públicas, organizar alternativas y buscar encajes comerciales dentro de {readable} con más contexto.",
        "caption": (
            f"Cada mercado tiene necesidades, proveedores y señales que no siempre aparecen ordenadas a simple vista. {readable.capitalize()} no es la excepción.\n\n"
            "LUMEN investiga información pública, organiza alternativas y ayuda a transformar señales dispersas en conversaciones comerciales con más contexto.\n\n"
            f"Si tu empresa trabaja en {readable}, escribinos por DM y contanos qué ofrecés o qué necesitás."
        ),
        "hashtags": ["#LUMENB2B", f"#{tag}", "#NegociosB2B", "#OportunidadesComerciales", "#DesarrolloComercial", "#InteligenciaComercial"],
        "audience": "b2b",
        "pillar": f"thematic_{_slug(readable)}",
        "goal": "qualified_thematic_business_conversation",
        "style": "evidence_grid",
        "cta": "HABLEMOS POR DM",
    }


def _template(theme: str) -> Dict[str, Any]:
    key = _slug(theme).replace("viajes-turismo", "travel").replace("turismo", "travel").replace("viajes", "travel")
    aliases = {
        "tecnologia": "technology",
        "automatizacion": "technology",
        "construccion": "construction",
        "industria": "industry",
        "importacion-exportacion": "import_export",
        "comercio-exterior": "import_export",
    }
    key = aliases.get(key, key)
    return dict(_theme_library().get(key) or _custom_theme(theme))


def _job_id(theme: str, request_id: str) -> str:
    token = hashlib.sha1(f"LUMEN-IGTHEME|{_slug(theme)}|{request_id}".encode("utf-8")).hexdigest()[:12].upper()
    return f"IGTHEME-{token}"


def prepare_thematic_post(
    state: Dict[str, Any],
    theme: str,
    *,
    request_id: str,
    objective: str = "",
    notes: str = "",
) -> Dict[str, Any]:
    theme = _clean(theme, 80)
    request_id = _clean(request_id, 160)
    if not theme or not request_id:
        return {"status": "invalid_request"}

    brief = _template(theme)
    jid = _job_id(theme, request_id)
    existing = next((x for x in state.get("distribution_operator_jobs", []) or [] if str(x.get("id") or "") == jid), None)
    if existing:
        return {"status": "already_prepared", "job_id": jid, "qa_score": existing.get("editorial_qa_score")}

    headline = str(brief["headline"])
    subtitle = str(brief["subtitle"])
    hashtags: List[str] = list(brief["hashtags"])
    caption = str(brief["caption"]).rstrip() + "\n\n" + " ".join(hashtags)
    score, reasons = pro._qa_piece(headline, subtitle, caption, hashtags, pro._history(state))
    if score < pro.QA_MIN_SCORE:
        state["instagram_thematic_last_block"] = {
            "theme": theme,
            "request_id": request_id,
            "score": score,
            "reasons": reasons,
            "headline": headline,
            "blocked_at": _utcnow(),
        }
        return {"status": "blocked_by_quality", "qa_score": score, "qa_reasons": reasons}

    objective = _clean(objective, 260)
    notes = _clean(notes, 400)
    job = {
        "id": jid,
        "queue_key": f"IGTHEME|{_slug(theme)}|{request_id}",
        "campaign_id": "IG-THEMATIC-ON-DEMAND",
        "variant_id": f"THEME-{_slug(theme).upper()[:32]}",
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
        "content_mode": "thematic_on_demand",
        "theme": _slug(theme),
        "theme_label": brief["label"],
        "content_pillar": brief["pillar"],
        "content_goal": brief["goal"],
        "creative_style": brief["style"],
        "creative_label": brief["label"],
        "editorial_slot": f"on-demand:{request_id}",
        "editorial_strategy": "owner_requested_theme",
        "editorial_qa_score": score,
        "editorial_qa_reasons": reasons,
        "editorial_pro_v1": True,
        "format": "instagram_feed_4x5",
        "hide_tracking_url_in_caption": True,
        "tracking_path": "",
        "tracking_url": "",
        "requires_connector": True,
        "requires_budget_approval": False,
        "approval_required": True,
        "authority": "prepare_autonomously_publish_only_after_explicit_human_approval",
        "owner_objective": objective,
        "owner_notes": notes,
        "thematic_runtime_version": VERSION,
    }
    state.setdefault("distribution_operator_jobs", []).append(job)
    state["distribution_operator_jobs"] = (state.get("distribution_operator_jobs", []) or [])[-500:]
    ipc._ensure_media_url(job)
    ipc._ensure_nonce(job)

    pro._history(state).append({
        "slot": f"on-demand:{request_id}",
        "job_id": jid,
        "pillar": brief["pillar"],
        "audience": brief["audience"],
        "headline": headline,
        "strategy": "owner_requested_theme",
        "qa_score": score,
        "created_at": _utcnow(),
    })
    state["instagram_editorial_history"] = pro._history(state)[-pro.MAX_HISTORY:]

    thematic_history = state.setdefault("instagram_thematic_history", [])
    thematic_history.append({
        "request_id": request_id,
        "job_id": jid,
        "theme": theme,
        "theme_label": brief["label"],
        "qa_score": score,
        "status": "prepared",
        "created_at": _utcnow(),
    })
    state["instagram_thematic_history"] = thematic_history[-MAX_THEMATIC_HISTORY:]
    state["instagram_thematic_runtime"] = {
        "version": VERSION,
        "status": "active",
        "supported_presets": sorted(_theme_library().keys()),
        "free_text_theme": True,
        "format": "4:5",
        "qa_min_score": pro.QA_MIN_SCORE,
        "human_approval_required": True,
        "autonomous_publish": False,
        "updated_at": _utcnow(),
    }
    return {"status": "prepared", "job_id": jid, "qa_score": score, "theme": theme}


def _recent_rows() -> str:
    rows = [x for x in STATE.get("distribution_operator_jobs", []) or [] if isinstance(x, dict) and x.get("content_mode") == "thematic_on_demand"]
    rows.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    out = []
    for row in rows[:12]:
        out.append(
            "<tr>"
            f"<td>{html.escape(str(row.get('theme_label') or row.get('theme') or ''))}</td>"
            f"<td>{html.escape(str(row.get('headline') or ''))}</td>"
            f"<td>{html.escape(str(row.get('editorial_qa_score') or ''))}</td>"
            f"<td>{html.escape(str(row.get('status') or ''))}</td>"
            "</tr>"
        )
    return "".join(out) or "<tr><td colspan='4'>Todavía no hay publicaciones temáticas preparadas.</td></tr>"


@app.get("/instagram/publishing/theme", response_class=HTMLResponse, include_in_schema=False)
def thematic_instagram_dashboard(_=Depends(auth)):
    if not load_state():
        raise HTTPException(status_code=503, detail="state_unavailable")
    return HTMLResponse(f"""<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>LUMEN · Publicación temática</title><style>
body{{margin:0;background:#061117;color:#e8f0f4;font:14px Arial,sans-serif}}main{{max-width:950px;margin:auto;padding:24px}}a{{color:#d7ff64}}.box{{background:#0b1d25;border:1px solid #23404b;border-radius:18px;padding:18px;margin:14px 0}}label{{display:block;font-weight:800;margin:12px 0}}input,textarea{{display:block;width:100%;box-sizing:border-box;margin-top:6px;padding:12px;border-radius:9px;border:1px solid #31505d;background:#07151b;color:white}}textarea{{min-height:90px}}button{{background:#d7ff64;color:#071018;border:0;border-radius:10px;padding:12px 16px;font-weight:900;cursor:pointer}}table{{width:100%;border-collapse:collapse}}th,td{{padding:9px;border-bottom:1px solid #1b3945;text-align:left;vertical-align:top}}.muted{{color:#9fb2bb;font-size:12px}}</style></head><body><main>
<p><a href='/instagram/publishing'>← Publicaciones</a></p><h1>Preparar publicación temática</h1>
<section class='box'><p>LUMEN prepara contenido 4:5, copy, hashtags y QA. <b>No publica automáticamente.</b></p>
<form method='post' action='/api/instagram/publishing/prepare-theme'>
<label>Tema<input name='theme' maxlength='80' placeholder='Ej.: viajes / turismo' required></label>
<label>Objetivo opcional<textarea name='objective' maxlength='260' placeholder='Ej.: atraer agencias, alojamientos y operadores'></textarea></label>
<label>Notas opcionales<textarea name='notes' maxlength='400' placeholder='Cualquier restricción o enfoque'></textarea></label>
<button type='submit'>PREPARAR EN LUMEN</button></form>
<p class='muted'>Presets: viajes/turismo, tecnología, construcción, industria, importación/exportación. También acepta tema libre.</p></section>
<section class='box'><h2>Últimas temáticas</h2><table><thead><tr><th>Tema</th><th>Headline</th><th>QA</th><th>Estado</th></tr></thead><tbody>{_recent_rows()}</tbody></table></section>
</main></body></html>""")


@app.post("/api/instagram/publishing/prepare-theme", include_in_schema=False)
def prepare_theme_endpoint(
    theme: str = Form(...),
    objective: str = Form(""),
    notes: str = Form(""),
    _=Depends(auth),
):
    if not load_state():
        raise HTTPException(status_code=503, detail="state_unavailable")
    request_id = f"manual-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
    result = prepare_thematic_post(STATE, theme, request_id=request_id, objective=objective, notes=notes)
    if result.get("status") == "blocked_by_quality":
        save_state()
        raise HTTPException(status_code=422, detail=f"quality_gate_failed:{result.get('qa_score')}:{','.join(result.get('qa_reasons') or [])}")
    if result.get("status") not in {"prepared", "already_prepared"}:
        raise HTTPException(status_code=400, detail=str(result.get("status") or "prepare_failed"))
    save_state()
    return RedirectResponse("/instagram/publishing", status_code=303)


def _seed_owner_requested_travel_post() -> None:
    """One idempotent preparation matching the owner's 2026-09-24 travel request."""
    try:
        if not load_state():
            return
        result = prepare_thematic_post(
            STATE,
            "travel",
            request_id="owner-travel-request-20260924",
            objective="Atraer agencias, alojamientos, operadores y proveedores turísticos mediante una publicación comercial orgánica.",
            notes="Sin pauta paga. CTA suave a DM. Mantener aprobación humana por publicación.",
        )
        if result.get("status") == "prepared":
            save_state()
        print({"instagram_thematic_seed": result}, flush=True)
    except Exception as exc:
        print({"instagram_thematic_seed": {"status": "error", "error": f"{type(exc).__name__}: {str(exc)[:240]}"}}, flush=True)


_seed_owner_requested_travel_post()

print({
    "instagram_thematic_runtime": {
        "version": VERSION,
        "status": "active",
        "route": "/instagram/publishing/theme",
        "format": "4:5",
        "qa_min_score": pro.QA_MIN_SCORE,
        "human_approval_required": True,
        "autonomous_publish": False,
    }
}, flush=True)
