from __future__ import annotations

"""Blend LUMEN's paid services into the existing professional Instagram calendar.

Only buyer Monday and supplier Wednesday become explicit service-led posts. The remaining
editorial pillars stay authority/education/partner-led so the account does not turn into a
constant sales catalog. The existing immutable human approval gate is untouched.
"""

from typing import Any, Dict

import instagram_pro_editorial_runtime as editorial


VERSION = "1.0-instagram-service-offers"
_ORIGINAL_WEEKDAY_BRIEF = editorial._weekday_brief


def _weekday_brief_with_services(weekday: int, strategy: str) -> Dict[str, Any]:
    brief = dict(_ORIGINAL_WEEKDAY_BRIEF(weekday, strategy) or {})
    if not brief:
        return brief

    if weekday == 0:  # buyer / sourcing
        brief.update({
            "pillar": "buyer_service_sourcing",
            "goal": "qualified_sourcing_service_inquiry",
            "label": "LUMEN SOURCING EXPRESS",
            "headlines": [
                "Decinos qué necesitás. LUMEN investiga proveedores por vos.",
                "Una necesidad concreta merece proveedores comparables.",
                "De la necesidad a una shortlist de proveedores con más criterio.",
            ],
            "subtitle": "Sourcing Express organiza la búsqueda B2B: investigamos alternativas, reunimos evidencia disponible y preparamos una shortlist para avanzar con más claridad.",
            "cta": "CONTANOS QUÉ NECESITÁS",
            "caption": (
                "¿Necesitás encontrar proveedores para una compra B2B concreta?\n\n"
                "LUMEN Sourcing Express transforma ese requerimiento en una búsqueda comercial ordenada: investiga alternativas, reúne información disponible y prepara una shortlist para que puedas evaluar próximos pasos con más contexto.\n\n"
                "El alcance y las condiciones se confirman para cada caso. Si tenés una necesidad real, escribinos por DM o consultá los servicios de LUMEN en nuestra web."
            ),
            "hashtags": ["#LUMENB2B", "#Sourcing", "#ComprasB2B", "#Proveedores", "#ComprasIndustriales", "#Abastecimiento", "#InteligenciaComercial"],
        })

    elif weekday == 2:  # supplier / prospecting
        brief.update({
            "pillar": "supplier_service_prospecting",
            "goal": "qualified_prospecting_service_inquiry",
            "label": "LUMEN PROSPECCIÓN B2B",
            "headlines": [
                "Vendés B2B: enfoquemos la prospección donde puede haber encaje.",
                "Menos contactos al azar. Más empresas objetivo con criterio.",
                "Tu oferta necesita mejores objetivos, no solamente más contactos.",
            ],
            "subtitle": "LUMEN investiga empresas objetivo, señales públicas y canales corporativos para priorizar dónde puede tener más sentido iniciar una conversación comercial.",
            "cta": "CONTANOS QUÉ VENDÉS",
            "caption": (
                "La prospección B2B no mejora solamente por aumentar el volumen de contactos.\n\n"
                "LUMEN Prospección B2B investiga empresas objetivo, señales públicas y encaje comercial para ordenar dónde conviene concentrar el esfuerzo comercial.\n\n"
                "No prometemos ventas ni leads inexistentes: trabajamos con evidencia disponible y priorización. Si tu empresa vende B2B, escribinos por DM o consultá nuestros servicios en la web."
            ),
            "hashtags": ["#LUMENB2B", "#ProspeccionB2B", "#VentasB2B", "#DesarrolloComercial", "#Proveedores", "#InteligenciaComercial", "#OportunidadesComerciales"],
        })

    return brief


editorial._weekday_brief = _weekday_brief_with_services

print({
    "instagram_service_offers_runtime": {
        "version": VERSION,
        "status": "active",
        "service_led_weekdays": ["monday_buyer_sourcing", "wednesday_supplier_prospecting"],
        "non_service_pillars_preserved": 3,
        "human_approval_unchanged": True,
        "binding_claims": False,
    }
}, flush=True)
