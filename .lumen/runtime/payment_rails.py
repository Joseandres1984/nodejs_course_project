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


def _rail_env(prefix: str, code: str, label: str, currency: str, scope: str, priority: int) -> Dict[str, Any]:
    instructions = str(os.getenv(f"LUMEN_{prefix}_INSTRUCTIONS", "") or "").strip()
    verified = _truthy(os.getenv(f"LUMEN_{prefix}_VERIFIED", "false"))
    auto_prepare = _truthy(os.getenv(f"LUMEN_{prefix}_AUTO_PREPARE", "false"))
    destination = str(os.getenv(f"LUMEN_{prefix}_DESTINATION_LABEL", "") or "").strip()
    enabled = _truthy(os.getenv(f"LUMEN_{prefix}_ENABLED", "true"))
    return {
        "code": code,
        "label": label,
        "currency": currency,
        "scope": scope,
        "priority": priority,
        "enabled": enabled,
        "instructions_present": bool(instructions),
        "verified": bool(instructions and verified),
        "auto_prepare": bool(auto_prepare),
        "destination_label": destination or None,
        "_instructions": instructions,
    }


def runtime_rails() -> Dict[str, Dict[str, Any]]:
    # Raw instructions live only in process environment. They are stripped before state/API persistence.
    return {
        "payoneer_usd": _rail_env("PAYONEER", "payoneer_usd", "Payoneer USD", "USD", "international", 100),
        "arg_bank_usd": _rail_env("ARG_BANK_USD", "arg_bank_usd", "Cuenta bancaria argentina USD", "USD", "domestic", 95),
        "arg_bank_ars": _rail_env("ARG_BANK_ARS", "arg_bank_ars", "Cuenta bancaria argentina ARS", "ARS", "domestic", 90),
        "mercadopago_ars": _rail_env("MERCADOPAGO", "mercadopago_ars", "Mercado Pago ARS", "ARS", "domestic", 80),
        "wise_usd": _rail_env("WISE", "wise_usd", "Wise USD", "USD", "international", 70),
    }


def public_rail(rail: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in rail.items() if not str(k).startswith("_")}


def _account_index(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(x.get("id")): x for x in state.get("candidate_accounts", []) or [] if x.get("id")}


def _country_for_deal(state: Dict[str, Any], deal: Dict[str, Any]) -> str:
    accounts = _account_index(state)
    buyer = accounts.get(str(deal.get("buyer_account_id") or ""), {})
    for value in (
        buyer.get("country"), buyer.get("market"), deal.get("buyer_country"), deal.get("market"),
        (deal.get("trade") or {}).get("destination_country"),
    ):
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _is_argentina(country: str) -> bool:
    value = _norm(country)
    return value in {"argentina", "ar", "arg", "republica argentina", "república argentina"} or "argentina" in value


def _eligible(rail: Dict[str, Any]) -> bool:
    return bool(rail.get("enabled"))


def choose_payment_route(state: Dict[str, Any], deal: Dict[str, Any]) -> Dict[str, Any]:
    rails = runtime_rails()
    country = _country_for_deal(state, deal)
    domestic = _is_argentina(country)
    preferred_codes = (
        ["arg_bank_usd", "arg_bank_ars", "mercadopago_ars"]
        if domestic
        else ["payoneer_usd", "wise_usd"]
    )

    candidates = [rails[x] for x in preferred_codes if _eligible(rails[x])]
    verified = [x for x in candidates if x.get("verified")]
    selected = verified[0] if verified else (candidates[0] if candidates else None)

    if not country:
        status = "COUNTRY_REQUIRED"
        reason = "Falta país/mercado verificable del comprador para seleccionar un riel de cobro sin adivinar."
    elif selected is None:
        status = "NO_RAIL_AVAILABLE"
        reason = "No existe un riel de cobro habilitado para este mercado."
    elif not selected.get("verified"):
        status = "RAIL_SETUP_REQUIRED"
        reason = f"{selected.get('label')} es la ruta preferida, pero sus instrucciones todavía no están verificadas."
    else:
        status = "READY"
        reason = f"Ruta seleccionada por mercado: {selected.get('label')}."

    fallback = next((public_rail(x) for x in candidates if selected and x.get("code") != selected.get("code") and x.get("verified")), None)
    return {
        "deal_id": deal.get("id"),
        "buyer_country": country or None,
        "domestic": domestic if country else None,
        "status": status,
        "reason": reason,
        "selected_rail": public_rail(selected) if selected else None,
        "fallback_rail": fallback,
        "currency_preference": (selected or {}).get("currency"),
        "updated_at": utcnow(),
        "rule": "Nunca inventar datos de cobro; solo usar instrucciones de runtime previamente verificadas.",
    }


def runtime_instruction_for(code: str) -> str:
    return str((runtime_rails().get(str(code or "")) or {}).get("_instructions") or "")


def payment_rails_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    rails = runtime_rails()
    routes = []
    route_index: Dict[str, Dict[str, Any]] = {}
    for deal in state.get("deals", []) or []:
        if deal.get("source") == "demo" or str(deal.get("stage") or "") in {"closed_simulated", "cerrado (simulación)"}:
            continue
        route = choose_payment_route(state, deal)
        routes.append(route)
        if deal.get("id"):
            route_index[str(deal.get("id"))] = route
            deal["payment_route"] = route

    public_rails = [public_rail(x) for x in rails.values()]
    report = {
        "updated_at": utcnow(),
        "mode": "autonomous_payment_rail_routing",
        "primary_international_rail": "payoneer_usd",
        "domestic_preference": ["arg_bank_usd", "arg_bank_ars", "mercadopago_ars"],
        "international_preference": ["payoneer_usd", "wise_usd"],
        "rails": public_rails,
        "routes": routes[:160],
        "ready_routes": sum(1 for x in routes if x.get("status") == "READY"),
        "setup_required": sum(1 for x in routes if x.get("status") != "READY"),
        "governance": {
            "secret_rule": "Las instrucciones bancarias/PSP no se persisten en Git, estado, logs ni API.",
            "selection_rule": "Argentina prioriza banco local; exterior prioriza Payoneer USD; Wise queda como respaldo configurable.",
            "authority_rule": "El sistema puede seleccionar/preparar el riel; no puede cambiar destinos, mover fondos ni autorizar pagos por sí solo.",
        },
    }
    state["payment_rails"] = report
    state["payment_route_index"] = route_index
    return report
