from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from autonomy_governor import record_decision


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


PROFILE = {
    "tone": "amable, profesional, claro, breve y humano",
    "principles": [
        "ser respetuoso sin sonar distante",
        "pedir en lugar de exigir",
        "explicar brevemente el contexto",
        "hacer un pedido concreto",
        "agradecer el tiempo de la contraparte",
        "evitar presión artificial, manipulación o urgencias inventadas",
        "no prometer condiciones, stock, plazos ni compromisos no verificados",
        "respetar inmediatamente bajas y pedidos de no contacto",
    ],
}


def _friendly_body(kind: str, original: str, counterparty: str) -> str:
    original = (original or "").strip()
    name = (counterparty or "").strip()
    greeting = f"Hola, buen día{(' equipo de ' + name) if name else ''}."

    if kind == "buyer_intro":
        core = original or "Estamos evaluando una alternativa de abastecimiento que podría resultarles útil. Nos gustaría comprender mejor su necesidad, especificación, volumen, plazo objetivo y condiciones comerciales para preparar una propuesta concreta y relevante."
    elif kind == "supplier_rfq":
        core = original or "Estamos evaluando una necesidad de abastecimiento y nos gustaría contar con su mejor propuesta comercial. Si es posible, agradeceremos precio, validez, plazo de entrega, condiciones de pago, garantía, origen y documentación técnica disponible."
    elif kind == "buyer_proposal":
        core = original or "Preparamos una propuesta comercial en función de la información disponible. Quedamos a disposición para revisar cualquier aspecto técnico o comercial que necesiten ajustar."
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

    closing = "Muchas gracias por su tiempo. Quedamos atentos y a disposición.\n\nSaludos cordiales,\nLUMEN B2B"
    return f"{greeting}\n\n{core.strip()}\n\n{closing}"


def review_outbox(state: Dict[str, Any]) -> Dict[str, int]:
    outbox = state.setdefault("outbox", [])
    opt_out = {str(x).lower() for x in state.setdefault("opt_out", [])}
    stats = {"reviewed": 0, "polished": 0, "blocked_opt_out": 0}

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
        polished = _friendly_body(str(item.get("kind") or "general"), original, str(item.get("counterparty") or ""))
        item["body"] = polished
        item["communication_reviewed"] = True
        item["communication_profile"] = PROFILE["tone"]
        item["communication_reviewed_at"] = utcnow()
        stats["polished"] += 1
        record_decision(
            state, engine="Communication Director", object_type="message", object_id=str(item.get("id") or ""),
            decision="professional_tone_applied",
            reason="Se aplicó el estándar relacional de LUMEN: amable, claro, no manipulativo y orientado a una relación B2B de largo plazo.",
            action="polish_outbound_message", confidence=0.98, evidence_refs=[],
        )

    state["communication_policy"] = {**PROFILE, "updated_at": utcnow()}
    state["communication_stats"] = {**stats, "updated_at": utcnow()}
    return stats
