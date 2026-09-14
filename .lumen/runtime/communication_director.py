from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Dict

from autonomy_governor import record_decision


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


PROFILE = {
    "tone": "amable, profesional, claro, breve, humano y contextual",
    "principles": [
        "ser respetuoso sin sonar distante",
        "pedir en lugar de exigir",
        "explicar brevemente el contexto real de la conversación",
        "personalizar con empresa, categoría y evidencia pública cuando exista",
        "hacer un pedido concreto",
        "agradecer el tiempo de la contraparte",
        "evitar presión artificial, manipulación o urgencias inventadas",
        "no prometer condiciones, stock, plazos ni compromisos no verificados",
        "no revelar información innecesaria del comprador a proveedores",
        "respetar inmediatamente bajas y pedidos de no contacto",
        "no usar títulos de páginas, informes o estudios como nombre de empresa",
    ],
}

PUBLIC_CONTACT_EMAIL = (os.getenv("LUMEN_PUBLIC_CONTACT_EMAIL") or "").strip()
_TITLE_LIKE_MARKERS = (
    "previsiones del mercado", "pronóstico del mercado", "pronostico del mercado",
    "tamaño del mercado", "tamano del mercado", "market forecast", "market size",
    "market analysis", "market report", "industry report", "research report",
    "informe de mercado", "reporte de mercado", "análisis del mercado", "analisis del mercado",
    "tendencias del mercado", "market trends", "market outlook", "industry outlook",
)
_GENERIC_NAME_WORDS = {
    "home", "inicio", "productos", "products", "servicios", "services", "contacto", "contact",
    "mercado", "market", "previsiones", "forecast", "informe", "report", "analysis", "análisis",
}


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _name_looks_like_page_title(value: Any) -> bool:
    name = _norm(value)
    low = name.lower()
    if not name:
        return True
    if len(name) > 72 or len(name.split()) > 9:
        return True
    if any(marker in low for marker in _TITLE_LIKE_MARKERS):
        return True
    words = {x.lower() for x in re.findall(r"[A-Za-zÁÉÍÓÚáéíóúÑñ]+", name)}
    if words and len(words) <= 3 and words <= _GENERIC_NAME_WORDS:
        return True
    if re.search(r"\b20\d{2}\s*[-–]\s*20\d{2}\b", name):
        return True
    return False


def _email_domain(value: Any) -> str:
    text = _norm(value).lower()
    return text.rsplit("@", 1)[-1].removeprefix("www.") if "@" in text else ""


def _identity(state: Dict[str, Any], item: Dict[str, Any], account: Dict[str, Any]) -> Dict[str, Any]:
    del state
    explicit_candidates = [account.get("company_name"), account.get("name_hint")]
    safe_name = next((_norm(x) for x in explicit_candidates if _norm(x) and not _name_looks_like_page_title(x)), "")
    raw_counterparty = _norm(item.get("counterparty"))
    suspicious_counterparty = bool(raw_counterparty and _name_looks_like_page_title(raw_counterparty))

    try:
        verification_score = max(0.0, min(100.0, float(account.get("verification_score") or 0.0)))
    except (TypeError, ValueError):
        verification_score = 0.0

    score = 0.0
    reasons = []
    if account.get("verified_company"):
        score += 0.45
        reasons.append("empresa verificada")
    if verification_score:
        score += 0.35 * (verification_score / 100.0)
        reasons.append(f"verificación {verification_score:.0f}/100")
    if safe_name:
        score += 0.15
        reasons.append("nombre empresarial utilizable")
    email_domain = _email_domain(item.get("contact"))
    official_domain = _norm(account.get("domain")).lower().removeprefix("www.")
    if email_domain and official_domain and (email_domain == official_domain or email_domain.endswith("." + official_domain)):
        score += 0.05
        reasons.append("email coincide con dominio oficial")
    if suspicious_counterparty and not safe_name:
        reasons.append("título/página descartado como nombre")

    score = round(max(0.0, min(1.0, score)), 2)
    return {
        "name": safe_name,
        "safe_for_greeting": bool(safe_name),
        "confidence": score,
        "suspicious_source_name": suspicious_counterparty,
        "reasons": reasons[:6],
    }


def _context(state: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Any]:
    account_id = str(item.get("counterparty_account_id") or "")
    account = next((x for x in state.get("candidate_accounts", []) or [] if str(x.get("id") or "") == account_id), {})
    opportunity_id = str(item.get("opportunity_id") or "")
    opportunity = next((x for x in state.get("market_opportunities", []) or [] if str(x.get("id") or "") == opportunity_id), {})
    deal_id = str(item.get("deal_id") or "")
    deal = next((x for x in state.get("deals", []) or [] if str(x.get("id") or "") == deal_id), {})
    interlocution_id = str(item.get("interlocution_case_id") or "")
    interlocution = next((x for x in state.get("interlocution_cases", []) or [] if str(x.get("id") or "") == interlocution_id), {})
    requirement = interlocution.get("requirement", {}) or {}
    category = _norm(item.get("category") or interlocution.get("category") or opportunity.get("category") or deal.get("need"))
    identity = _identity(state, item, account)

    signal = None
    if account.get("type") == "buyer":
        candidates = [
            x for x in state.get("demand_signals", []) or []
            if str(x.get("account_id") or "") == account_id and float(x.get("score") or 0) >= 75
        ]
        candidates.sort(key=lambda x: float(x.get("score") or 0), reverse=True)
        signal = candidates[0] if candidates else None

    return {
        "company": identity["name"],
        "company_name_safe_for_greeting": identity["safe_for_greeting"],
        "company_identity_confidence": identity["confidence"],
        "company_identity_reasons": identity["reasons"],
        "company_name_source_suspicious": identity["suspicious_source_name"],
        "role": account.get("type"),
        "category": category,
        "demand_title": _norm((signal or {}).get("title"))[:160],
        "delivery_location": _norm(requirement.get("delivery_location"))[:160],
        "quantity": requirement.get("quantity"),
        "unit": _norm(requirement.get("unit")),
    }


def _context_prefix(kind: str, ctx: Dict[str, Any]) -> str:
    category = ctx.get("category") or "este requerimiento"
    demand_title = ctx.get("demand_title")
    location = ctx.get("delivery_location")
    quantity = ctx.get("quantity")
    unit = ctx.get("unit")

    if kind == "buyer_requirement_request":
        if demand_title:
            return (
                f"Tomamos como punto de partida una referencia pública asociada a su organización y vinculada a {category}: “{demand_title}”. "
                "Antes de preparar cualquier alternativa preferimos confirmar con ustedes los datos vigentes y no asumir detalles a partir de una publicación."
            )
        return f"Estamos revisando una necesidad vinculada a {category} y queremos validar con ustedes los datos vigentes antes de preparar alternativas."
    if kind == "supplier_rfq":
        details = []
        if quantity:
            details.append(f"{quantity} {unit}".strip())
        if location:
            details.append(f"entrega en {location}")
        suffix = f" ({'; '.join(details)})" if details else ""
        return f"Estamos trabajando sobre un requerimiento B2B confirmado de {category}{suffix} y buscamos una alternativa técnicamente adecuada y comercialmente comparable."
    if kind == "quote_clarification":
        return f"Estamos normalizando las condiciones de la cotización vinculada a {category} para compararla sin interpretar datos faltantes."
    if kind == "supplier_negotiation":
        return f"Estamos optimizando una oportunidad real de {category} y queremos revisar condiciones sin alterar el alcance técnico confirmado."
    if kind in {"buyer_information_response", "terms_clarification"}:
        return f"Seguimos el caso de {category} y preferimos responder cada punto únicamente con información trazable."
    if kind == "follow_up":
        return f"Retomamos brevemente el caso de {category}, manteniendo como referencia únicamente la información ya conversada."
    return ""


def _signature() -> str:
    lines = [
        "Muchas gracias por su tiempo. Quedamos atentos y a disposición.",
        "",
        "Saludos cordiales,",
        "LUMEN B2B",
        "Inteligencia comercial y oportunidades B2B",
        "Equipo de Desarrollo Comercial",
    ]
    if PUBLIC_CONTACT_EMAIL:
        lines.append(PUBLIC_CONTACT_EMAIL)
    return "\n".join(lines)


def _friendly_body(kind: str, original: str, counterparty: str, ctx: Dict[str, Any]) -> str:
    original = (original or "").strip()
    safe_name = _norm(ctx.get("company")) if ctx.get("company_name_safe_for_greeting") else ""
    greeting = f"Hola, buen día{(' equipo de ' + safe_name) if safe_name else ''}."
    prefix = _context_prefix(kind, ctx)

    if kind == "buyer_intro":
        core = original or "Estamos evaluando una alternativa de abastecimiento que podría resultarles útil. Nos gustaría comprender mejor su necesidad, especificación, volumen, plazo objetivo y condiciones comerciales para preparar una propuesta concreta y relevante."
    elif kind == "supplier_rfq":
        core = original or "Nos gustaría contar con su mejor propuesta comercial. Si es posible, agradeceremos precio, validez, plazo de entrega, condiciones de pago, garantía, origen y documentación técnica disponible."
    elif kind == "buyer_proposal":
        core = original or "Preparamos una propuesta comercial en función de la información confirmada. Quedamos a disposición para revisar cualquier aspecto técnico o comercial que necesiten ajustar."
    elif kind == "follow_up":
        core = original or "Queríamos consultar, cuando tengan un momento, si pudieron revisar nuestro mensaje anterior y si podemos aportar alguna información adicional para facilitar la evaluación."
    else:
        core = original

    low = core.lower()
    replacements = {
        "solicitamos cotización": "nos gustaría solicitar una cotización",
        "agradecemos precio": "si es posible, agradeceremos precio",
        "necesitamos": "nos sería útil contar con",
        "debe": "sería importante que",
        "urgente": "prioritario",
    }
    for old, new in replacements.items():
        if old in low:
            idx = low.find(old)
            core = core[:idx] + new + core[idx + len(old):]
            low = core.lower()

    paragraphs = [greeting]
    if prefix and prefix.lower() not in core.lower():
        paragraphs.append(prefix)
    if core:
        paragraphs.append(core.strip())
    paragraphs.append(_signature())
    return "\n\n".join(paragraphs)


def review_outbox(state: Dict[str, Any]) -> Dict[str, int]:
    # Response Intelligence runs immediately before communication review so newly created safe replies
    # can be personalized and pass through the same Quality Gate in the current worker cycle.
    from response_intelligence import response_intelligence_tick
    response_report = response_intelligence_tick(state)

    outbox = state.setdefault("outbox", [])
    opt_out = {str(x).lower() for x in state.setdefault("opt_out", [])}
    stats = {"reviewed": 0, "polished": 0, "personalized": 0, "blocked_opt_out": 0, "generic_greetings": 0}

    for item in outbox:
        if item.get("communication_reviewed"):
            continue
        if item.get("status") not in {"ready", "needs_verified_contact"}:
            continue
        stats["reviewed"] += 1
        target = str(item.get("contact") or "").strip().lower()
        if target and target in opt_out:
            item["status"] = "blocked"
            item["communication_reviewed"] = True
            item["communication_note"] = "blocked_opt_out"
            stats["blocked_opt_out"] += 1
            record_decision(
                state, engine="Communication Director", object_type="message", object_id=str(item.get("id") or ""),
                decision="do_not_contact", reason="La contraparte pidió no recibir más comunicaciones.",
                action="block_outbound", confidence=1.0, evidence_refs=[],
            )
            continue

        original = str(item.get("body") or "")
        ctx = _context(state, item)
        polished = _friendly_body(str(item.get("kind") or "general"), original, str(item.get("counterparty") or ""), ctx)
        item["body"] = polished
        item["communication_reviewed"] = True
        item["communication_profile"] = PROFILE["tone"]
        item["communication_context"] = {k: v for k, v in ctx.items() if v not in (None, "", [], {})}
        item["company_identity_confidence"] = ctx.get("company_identity_confidence", 0.0)
        item["company_name_safe_for_greeting"] = bool(ctx.get("company_name_safe_for_greeting"))
        item["company_name_source_suspicious"] = bool(ctx.get("company_name_source_suspicious"))
        item["communication_reviewed_at"] = utcnow()
        stats["polished"] += 1
        if not ctx.get("company_name_safe_for_greeting"):
            stats["generic_greetings"] += 1
        if ctx.get("category") or ctx.get("demand_title") or ctx.get("delivery_location"):
            stats["personalized"] += 1
        record_decision(
            state, engine="Communication Director", object_type="message", object_id=str(item.get("id") or ""),
            decision="professional_contextual_tone_applied",
            reason=(
                "Se aplicó el estándar relacional de LUMEN con identidad empresarial validada para el saludo cuando fue segura; "
                "si el nombre parecía un título de página/informe se usó saludo genérico."
            ),
            action="polish_outbound_message", confidence=max(0.55, float(ctx.get("company_identity_confidence") or 0.0)), evidence_refs=[],
        )

    state["communication_policy"] = {**PROFILE, "updated_at": utcnow()}
    state["communication_stats"] = {
        **stats,
        "response_intelligence": response_report.get("stats", {}),
        "open_response_escalations": response_report.get("open_escalations", 0),
        "updated_at": utcnow(),
    }
    return stats
