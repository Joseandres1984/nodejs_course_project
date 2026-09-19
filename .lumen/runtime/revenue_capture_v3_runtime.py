from __future__ import annotations

import os
from typing import Dict


VERSION = "3.0-low-friction-revenue-capture"


def transform_landing(html: str) -> str:
    """Turn the generic public landing into a direct path to the existing inquiry forms."""
    text = str(html or "")
    text = text.replace(
        '<a class="cta" href="#contacto">Hablar con LUMEN</a>',
        '<a class="cta" href="/services#consulta">Contame qué necesitás</a>'
        '<div class="fine">Sin reunión obligatoria: con tu email y una necesidad concreta alcanza para preparar el caso.</div>',
        1,
    )
    text = text.replace(
        '<p>Para oportunidades B2B, sourcing de proveedores o coordinación comercial:</p>\n          <p><a href="mailto:__CONTACT__">__CONTACT__</a></p>',
        '<p>Elegí el camino más directo. Podés dejar una necesidad comercial en menos de un minuto o escribirnos por email.</p>\n'
        '          <p><a class="cta" href="/services#consulta">Enviar una necesidad</a>&nbsp;&nbsp;'
        '<a href="/intelligence">Ver Intelligence</a></p>\n'
        '          <p class="fine">Contacto: <a href="mailto:__CONTACT__">__CONTACT__</a></p>',
        1,
    )
    return text


def install() -> Dict[str, object]:
    report: Dict[str, object] = {
        "version": VERSION,
        "status": "starting",
        "new_external_connector": False,
        "paid_spend": False,
        "payment_created": False,
        "binding_authority_changed": False,
    }
    try:
        import landing_public

        before = landing_public.LANDING_HTML
        after = transform_landing(before)
        landing_public.LANDING_HTML = after
        report.update({
            "status": "active",
            "hero_direct_to_service_form": '/services#consulta' in after,
            "intelligence_link_present": '/intelligence' in after,
            "landing_changed": before != after,
            "truth_rule": "click_is_not_lead; inquiry_is_unverified_until_existing CRM verification",
        })
        print({"revenue_capture_v3": report}, flush=True)
        return report
    except Exception as exc:
        report.update({"status": "degraded_fail_open", "reason": f"{type(exc).__name__}: {str(exc)[:240]}"})
        print({"revenue_capture_v3": report}, flush=True)
        return report


if os.getenv("LUMEN_REVENUE_CAPTURE_V3_AUTORUN", "true").strip().lower() not in {"0", "false", "no", "off"}:
    install()
