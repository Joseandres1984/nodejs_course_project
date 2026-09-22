from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "si", "sí", "on"}


def _norm(value: Any) -> str:
    return " ".join(str(value or "").lower().strip().split())


def _rail_env(prefix: str, code: str, label: str, currency: str, scope: str, priority: int, note: str = "") -> Dict[str, Any]:
    instructions = str(os.getenv(f"LUMEN_{prefix}_INSTRUCTIONS", "") or "").strip()
    verified = _truthy(os.getenv(f"LUMEN_{prefix}_VERIFIED", "false"))
    auto_prepare = _truthy(os.getenv(f"LUMEN_{prefix}_AUTO_PREPARE", "false"))
    destination = str(os.getenv(f"LUMEN_{prefix}_DESTINATION_LABEL", "") or "").strip()
    enabled = _truthy(os.getenv(f"LUMEN_{prefix}_ENABLED", "true"))
    return {
        "code": code, "label": label, "currency": currency, "scope": scope, "priority": priority,
        "enabled": enabled, "instructions_present": bool(instructions), "verified": bool(instructions and verified),
        "auto_prepare": bool(auto_prepare), "destination_label": destination or None, "note": note or None,
        "_instructions": instructions,
    }


def _mercadopago_rail() -> Dict[str, Any]:
    rail = _rail_env(
        "MERCADOPAGO", "mercadopago_ars", "Mercado Pago ARS", "ARS", "domestic", 100,
        "Principal local para cobros en Argentina mediante Checkout Pro/API o instrucciones manuales verificadas.",
    )
    api_ready = bool(str(os.getenv("LUMEN_MP_ACCESS_TOKEN", "") or "").strip())
    if api_ready:
        # This sentinel is internal only. It lets legacy settlement logic understand that the destination
        # is operationally verified while preventing static bank/payment instructions from being sent.
        rail.update({
            "verified": True,
            "auto_prepare": False,
            "destination_label": rail.get("destination_label") or "Mercado Pago Checkout Pro",
            "gateway_mode": "checkout_pro_api",
            "dynamic_checkout": True,
            "instructions_present": False,
            "_instructions": "CHECKOUT_PRO_DYNAMIC_LINK",
        })
    else:
        rail["gateway_mode"] = "manual_instructions"
        rail["dynamic_checkout"] = False
    return rail


def runtime_rails() -> Dict[str, Dict[str, Any]]:
    # Raw instructions live only in process environment and are stripped before persistence/API.
    # The generic Argentine bank-transfer rail is intentionally provider-agnostic: CBU/CVU/alias
    # details are supplied only through GitHub Actions secrets, never committed to source or D1.
    return {
        "mercadopago_ars": _mercadopago_rail(),
        "arg_bank_ars": _rail_env(
            "ARG_BANK_ARS", "arg_bank_ars", "Transferencia bancaria Argentina ARS", "ARS", "domestic", 95,
            "Respaldo local sin costo por transferencia a CBU/CVU/alias verificado; los datos sensibles viven solo en secretos de runtime.",
        ),
        "prex_ars": _rail_env("PREX_ARS", "prex_ars", "Prex ARS", "ARS", "domestic", 90, "Respaldo local por CVU/alias."),
        "arg_bank_usd": _rail_env("ARG_BANK_USD", "arg_bank_usd", "Cuenta bancaria argentina USD", "USD", "domestic", 85, "Opcional si más adelante se configura una cuenta bancaria USD apta para el cobro."),
        "payoneer_usd": _rail_env("PAYONEER", "payoneer_usd", "Payoneer USD", "USD", "international", 100, "Principal internacional USD; luego puede retirarse a Prex de forma separada."),
        "prex_eur_iban": _rail_env("PREX_EUR_IBAN", "prex_eur_iban", "Prex vIBAN EUR", "EUR", "international_eur", 95, "Para pagos internacionales directos en EUR/SEPA si el vIBAN está habilitado."),
        "wise_usd": _rail_env("WISE", "wise_usd", "Wise USD", "USD", "international", 70, "Respaldo opcional si se configura en el futuro."),
    }


def public_rail(rail: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in rail.items() if not str(k).startswith("_")}


def _account_index(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(x.get("id")): x for x in state.get("candidate_accounts", []) or [] if x.get("id")}


def _country_for_deal(state: Dict[str, Any], deal: Dict[str, Any]) -> str:
    buyer = _account_index(state).get(str(deal.get("buyer_account_id") or ""), {})
    for value in (buyer.get("country"), buyer.get("market"), deal.get("buyer_country"), deal.get("market"), (deal.get("trade") or {}).get("destination_country")):
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _currency_hint(deal: Dict[str, Any]) -> str:
    for value in (
        deal.get("commission_currency"), deal.get("fee_currency"), deal.get("currency"),
        (deal.get("economics") or {}).get("currency"), (deal.get("trade") or {}).get("currency"),
    ):
        text = str(value or "").strip().upper()
        if text in {"USD", "EUR", "ARS"}:
            return text
    return ""


def _is_argentina(country: str) -> bool:
    value = _norm(country)
    return value in {"argentina", "ar", "arg", "republica argentina", "república argentina"} or "argentina" in value


def choose_payment_route(state: Dict[str, Any], deal: Dict[str, Any]) -> Dict[str, Any]:
    rails = runtime_rails(); country = _country_for_deal(state, deal); currency = _currency_hint(deal); domestic = _is_argentina(country)
    if domestic and currency == "USD":
        preferred_codes = ["arg_bank_usd"]
    elif domestic and currency == "EUR":
        preferred_codes = []
    elif domestic:
        preferred_codes = ["mercadopago_ars", "arg_bank_ars", "prex_ars"]
    elif currency == "EUR":
        preferred_codes = ["prex_eur_iban", "payoneer_usd", "wise_usd"]
    else:
        preferred_codes = ["payoneer_usd", "wise_usd", "prex_eur_iban"]

    candidates = [rails[x] for x in preferred_codes if rails.get(x, {}).get("enabled")]
    verified = [x for x in candidates if x.get("verified")]
    selected = verified[0] if verified else (candidates[0] if candidates else None)

    if not country:
        status, reason = "COUNTRY_REQUIRED", "Falta país/mercado verificable del comprador para seleccionar un riel de cobro sin adivinar."
    elif selected is None:
        status, reason = "NO_RAIL_AVAILABLE", f"No existe un riel de cobro habilitado para {currency or 'la moneda documentada'} en este mercado."
    elif currency and selected.get("currency") != currency:
        status, reason = "CURRENCY_MISMATCH", f"El riel {selected.get('label')} no coincide con la moneda documentada {currency}; LUMEN no convierte moneda por su cuenta."
    elif not selected.get("verified"):
        status, reason = "RAIL_SETUP_REQUIRED", f"{selected.get('label')} es la ruta preferida, pero todavía no está verificada."
    else:
        status, reason = "READY", f"Ruta seleccionada por mercado y moneda: {selected.get('label')}."

    fallback = next((public_rail(x) for x in candidates if selected and x.get("code") != selected.get("code") and x.get("verified") and (not currency or x.get("currency") == currency)), None)
    return {
        "deal_id": deal.get("id"), "buyer_country": country or None, "currency_hint": currency or None,
        "domestic": domestic if country else None, "status": status, "reason": reason,
        "selected_rail": public_rail(selected) if selected else None, "fallback_rail": fallback,
        "currency_preference": (selected or {}).get("currency"), "updated_at": utcnow(),
        "rule": "Nunca inventar datos de cobro ni conversiones; usar solo rieles de runtime verificados y compatibles con la moneda documentada.",
    }


def runtime_instruction_for(code: str) -> str:
    return str((runtime_rails().get(str(code or "")) or {}).get("_instructions") or "")


def payment_rails_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    rails = runtime_rails(); routes = []; route_index: Dict[str, Dict[str, Any]] = {}
    for deal in state.get("deals", []) or []:
        if deal.get("source") == "demo" or str(deal.get("stage") or "") in {"closed_simulated", "cerrado (simulación)"}:
            continue
        route = choose_payment_route(state, deal); routes.append(route)
        if deal.get("id"):
            route_index[str(deal.get("id"))] = route
            deal["payment_route"] = route
            deal["payment_route_ready"] = route.get("status") == "READY"
            deal["payment_instructions_verified"] = route.get("status") == "READY"
            deal["payment_rail_code"] = ((route.get("selected_rail") or {}).get("code"))

    report = {
        "updated_at": utcnow(), "mode": "autonomous_payment_rail_routing",
        "primary_domestic_rail": "mercadopago_ars", "domestic_fallback": "arg_bank_ars",
        "secondary_domestic_fallback": "prex_ars",
        "primary_international_rail": "payoneer_usd", "international_eur_rail": "prex_eur_iban",
        "rails": [public_rail(x) for x in rails.values()], "routes": routes[:160],
        "ready_routes": sum(1 for x in routes if x.get("status") == "READY"),
        "setup_required": sum(1 for x in routes if x.get("status") != "READY"),
        "governance": {
            "secret_rule": "Las credenciales e instrucciones bancarias/PSP no se persisten en Git, estado, logs ni API.",
            "selection_rule": "Argentina ARS: Mercado Pago; si no está disponible, transferencia bancaria argentina verificada; luego Prex ARS. Argentina USD: solo rail USD verificado. Exterior USD: Payoneer. EUR/SEPA: Prex vIBAN si está habilitado.",
            "currency_rule": "LUMEN no convierte automáticamente una comisión USD/EUR a ARS para cobrar por Mercado Pago o transferencia local.",
            "cash_truth_rule": "Preparar instrucciones o un link de pago no equivale a cobrar; el ingreso solo se reconoce con evidencia de liquidación verificada.",
            "prex_rule": "Prex Argentina no se trata como receptor genérico de transferencias bancarias internacionales USD; el vIBAN EUR es un rail separado.",
            "authority_rule": "El sistema puede seleccionar/preparar el riel y un link o instrucciones de cobro sobre términos ya documentados; no puede cambiar destinos, mover fondos ni autorizar pagos por sí solo.",
        },
    }
    state["payment_rails"] = report; state["payment_route_index"] = route_index

    # Checkout Pro is a dynamic collection rail. It creates at most one new preference/request per cycle,
    # only for real ARS receivables already supported by invoice/settlement evidence.
    try:
        from mercadopago_checkout import mercadopago_checkout_tick
        checkout = mercadopago_checkout_tick(state)
    except Exception as exc:
        checkout = {"updated_at": utcnow(), "status": "ERROR", "errors": 1, "error_type": type(exc).__name__}
        state["mercadopago_checkout"] = checkout
    report["mercadopago_checkout"] = checkout
    return report
