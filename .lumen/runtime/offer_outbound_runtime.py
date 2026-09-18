from __future__ import annotations

from typing import Any, Dict

import commercial_offer_engine_runtime as offer_engine
import outbound_engine


VERSION = "1.0-offer-aware-outbound"
_ORIGINAL_MESSAGE_TEXT = outbound_engine._message_text


def _offer_aware_message_text(account: Dict[str, Any], variant: Dict[str, Any], tracking_url: str):
    kind, subject, body = _ORIGINAL_MESSAGE_TEXT(account, variant, tracking_url)
    ctx = account.get("_lumen_service_revenue_context")
    if not isinstance(ctx, dict):
        return kind, subject, body
    service_id = str(ctx.get("service_id") or "")
    start = offer_engine.public_from_usd(service_id)
    if not start:
        return kind, subject, body

    marker = "Referencia de lanzamiento:"
    if marker in body:
        return kind, subject, body
    pricing_note = (
        f"\n\n{marker} este servicio parte de USD {int(start)} para el alcance inicial. "
        "Si el caso requiere más mercados, proveedores, segmentos o profundidad, LUMEN recomienda un paquete superior. "
        "El precio y alcance final se confirman antes de cualquier contratación; este mensaje no genera un cobro ni compromiso vinculante."
    )
    return kind, subject, (body + pricing_note)[:5000]


if not getattr(outbound_engine, "_lumen_offer_aware_outbound_installed", False):
    outbound_engine._message_text = _offer_aware_message_text
    outbound_engine._lumen_offer_aware_outbound_installed = True

print({
    "offer_outbound_runtime": {
        "version": VERSION,
        "status": "installed",
        "transparent_launch_price": True,
        "autonomous_discount": False,
        "binding_authority_changed": False,
        "paid_spend": False,
    }
}, flush=True)
