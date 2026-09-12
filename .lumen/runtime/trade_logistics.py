from __future__ import annotations

import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from autonomy_governor import record_decision
from scout_connector import MARKET


HOME_MARKET = os.getenv("LUMEN_HOME_MARKET", MARKET or "Argentina").strip() or "Argentina"
MAX_TRADE_CASES = 40
MAX_COMPARISONS = 20
INCOTERMS = {"EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"}
TRANSPORT_INCLUDED = {"CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"}
INSURANCE_INCLUDED = {"CIF", "CIP"}
DESTINATION_DELIVERY_INCLUDED = {"DAP", "DPU", "DDP"}
IMPORT_CLEARANCE_SELLER = {"DDP"}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _has_number(value: Any) -> bool:
    if value in (None, "", "unknown", "por validar"):
        return False
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _norm(value: Any) -> str:
    return " ".join(str(value or "").lower().strip().split())


def _known(value: Any) -> bool:
    return value not in (None, "", "unknown", "por validar", "n/a")


def _name(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _supplier_accounts(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [x for x in state.get("candidate_accounts", []) if x.get("type") == "supplier" and x.get("verified_company")]


def _supplier_account(state: Dict[str, Any], supplier: Any) -> Dict[str, Any]:
    target = _norm(supplier)
    if not target:
        return {}
    accounts = _supplier_accounts(state)
    for account in accounts:
        names = {_norm(account.get("company_name")), _norm(account.get("name_hint")), _norm(account.get("site_title"))}
        if target in names:
            return account
    for account in accounts:
        names = [_norm(account.get("company_name")), _norm(account.get("name_hint")), _norm(account.get("site_title"))]
        if any(name and (target in name or name in target) for name in names):
            return account
    return {}


def _incoterm(offer: Dict[str, Any]) -> str | None:
    for field in ("incoterm", "incoterms", "freight_terms", "delivery_terms"):
        text = str(offer.get(field) or "").upper()
        for token in re.findall(r"\b[A-Z]{3}\b", text):
            if token in INCOTERMS:
                return token
    return None


def _origin_country(offer: Dict[str, Any], account: Dict[str, Any]) -> str | None:
    for value in (
        offer.get("origin_country"), offer.get("supplier_country"), offer.get("country"), offer.get("market"),
        account.get("growth_market"), account.get("market"), account.get("country"),
    ):
        if _known(value):
            return _name(value)
    return None


def _is_cross_border(origin: str | None) -> bool | None:
    if not origin:
        return None
    return _norm(origin) != _norm(HOME_MARKET)


def _explicit_zero_or_amount(
    offer: Dict[str, Any], amount_fields: Tuple[str, ...], status_fields: Tuple[str, ...] = ()
) -> Tuple[bool, float, str | None]:
    for field in amount_fields:
        if _has_number(offer.get(field)):
            return True, max(0.0, _f(offer.get(field))), field
    for field in status_fields:
        value = _norm(offer.get(field))
        if value in {"included", "incluido", "incluida", "zero", "0", "exempt", "exento", "exenta", "not applicable", "no aplica"}:
            return True, 0.0, field
    return False, 0.0, None


def _international_cost_model(offer: Dict[str, Any], incoterm: str | None) -> Tuple[Dict[str, float], List[str], List[str]]:
    components: Dict[str, float] = {}
    missing: List[str] = []
    evidence: List[str] = []

    base = _f(offer.get("amount"))
    if base > 0:
        components["supplier_price"] = base
        evidence.append("amount")
    else:
        missing.append("supplier_price")

    freight_ok, freight, freight_field = _explicit_zero_or_amount(
        offer, ("freight_cost", "international_freight_cost", "transport_cost"), ("freight_status",)
    )
    if incoterm in TRANSPORT_INCLUDED:
        freight_ok, freight, freight_field = True, 0.0, f"incoterm_{incoterm}_transport_embedded"
    if freight_ok:
        components["freight_external"] = freight
        if freight_field: evidence.append(freight_field)
    else:
        missing.append("freight_cost_or_incoterm_coverage")

    insurance_ok, insurance, insurance_field = _explicit_zero_or_amount(
        offer, ("insurance_cost", "cargo_insurance_cost"), ("insurance_status",)
    )
    if incoterm in INSURANCE_INCLUDED:
        insurance_ok, insurance, insurance_field = True, 0.0, f"incoterm_{incoterm}_insurance_embedded"
    if insurance_ok:
        components["insurance_external"] = insurance
        if insurance_field: evidence.append(insurance_field)
    else:
        missing.append("insurance_cost_or_explicit_status")

    duty_ok, duty, duty_field = _explicit_zero_or_amount(
        offer, ("import_duty_amount", "customs_duty_amount", "tariff_amount"), ("import_duty_status", "duty_status")
    )
    if not duty_ok and _has_number(offer.get("customs_value")) and _has_number(offer.get("import_duty_pct")):
        duty = max(0.0, _f(offer.get("customs_value")) * _f(offer.get("import_duty_pct")) / 100.0)
        duty_ok, duty_field = True, "customs_value_x_import_duty_pct"
    if incoterm in IMPORT_CLEARANCE_SELLER and _norm(offer.get("import_duty_status")) in {"included", "incluido", "seller paid", "pagado por vendedor"}:
        duty_ok, duty, duty_field = True, 0.0, "ddp_duty_explicitly_included"
    if duty_ok:
        components["import_duty"] = duty
        if duty_field: evidence.append(duty_field)
    else:
        missing.append("import_duty_amount_or_verified_exemption")

    tax_ok, tax, tax_field = _explicit_zero_or_amount(
        offer, ("import_tax_amount", "import_vat_amount", "destination_tax_amount"), ("import_tax_status", "tax_terms")
    )
    if not tax_ok and _has_number(offer.get("import_tax_base")) and _has_number(offer.get("import_tax_pct")):
        tax = max(0.0, _f(offer.get("import_tax_base")) * _f(offer.get("import_tax_pct")) / 100.0)
        tax_ok, tax_field = True, "import_tax_base_x_import_tax_pct"
    if tax_ok:
        components["import_tax"] = tax
        if tax_field: evidence.append(tax_field)
    else:
        missing.append("import_tax_amount_or_verified_tax_treatment")

    brokerage_ok, brokerage, brokerage_field = _explicit_zero_or_amount(
        offer, ("customs_brokerage_cost", "brokerage_cost", "customs_clearance_cost"), ("customs_brokerage_status",)
    )
    if incoterm in IMPORT_CLEARANCE_SELLER and _norm(offer.get("customs_brokerage_status")) in {"included", "incluido", "seller paid", "pagado por vendedor"}:
        brokerage_ok, brokerage, brokerage_field = True, 0.0, "ddp_clearance_explicitly_included"
    if brokerage_ok:
        components["customs_brokerage"] = brokerage
        if brokerage_field: evidence.append(brokerage_field)
    else:
        missing.append("customs_brokerage_cost_or_explicit_status")

    delivery_ok, delivery, delivery_field = _explicit_zero_or_amount(
        offer, ("local_delivery_cost", "last_mile_cost", "domestic_delivery_cost"), ("local_delivery_status",)
    )
    if incoterm in DESTINATION_DELIVERY_INCLUDED:
        delivery_ok, delivery, delivery_field = True, 0.0, f"incoterm_{incoterm}_destination_transport_embedded"
    if delivery_ok:
        components["local_delivery"] = delivery
        if delivery_field: evidence.append(delivery_field)
    else:
        missing.append("local_delivery_cost_or_incoterm_coverage")

    bank_ok, bank, bank_field = _explicit_zero_or_amount(
        offer, ("bank_fee", "payment_fee", "wire_fee", "fx_cost"), ("bank_fee_status", "payment_fee_status")
    )
    if bank_ok:
        components["bank_and_payment_fees"] = bank
        if bank_field: evidence.append(bank_field)
    else:
        missing.append("bank_fx_payment_cost_or_explicit_zero")

    if _has_number(offer.get("other_import_cost")) and _f(offer.get("other_import_cost")) > 0:
        components["other_import_cost"] = _f(offer.get("other_import_cost"))
        evidence.append("other_import_cost")

    return components, missing, evidence


def _local_delivered_cost(offer: Dict[str, Any]) -> Tuple[float | None, List[str], List[str]]:
    # Never compare an international landed cost against a bare local unit price. Prefer an explicit all-in field.
    for field in ("local_delivered_cost", "delivered_total_cost", "all_in_total", "landed_cost"):
        if _has_number(offer.get(field)):
            return round(max(0.0, _f(offer.get(field))), 2), [], [field]

    amount = _f(offer.get("amount"))
    scope = _norm(offer.get("amount_scope"))
    if amount > 0 and scope in {"delivered_total", "all_in", "landed_total", "puesto_en_destino", "total_entregado"}:
        return round(amount, 2), [], ["amount", "amount_scope"]

    freight_included = _norm(offer.get("freight_status")) in {"included", "incluido", "incluida"}
    tax_text = _norm(offer.get("tax_terms"))
    tax_included = any(token in tax_text for token in ("incluido", "included", "impuestos incluidos", "iva incluido"))
    if amount > 0 and freight_included and tax_included:
        return round(amount, 2), [], ["amount", "freight_status", "tax_terms"]

    missing = ["local_delivered_total_confirmation"]
    if amount <= 0:
        missing.append("supplier_price")
    return None, missing, []


def _time_model(offer: Dict[str, Any], cross_border: bool | None) -> Dict[str, Any]:
    required = ["lead_days"]
    if cross_border:
        required.extend(["transit_days", "customs_days"])
    values: Dict[str, float] = {}
    missing: List[str] = []
    for field in required:
        if _has_number(offer.get(field)):
            values[field] = max(0.0, _f(offer.get(field)))
        else:
            missing.append(field)
    if cross_border and _has_number(offer.get("local_delivery_days")):
        values["local_delivery_days"] = max(0.0, _f(offer.get("local_delivery_days")))
    total = sum(values.values()) if not missing else None
    return {"components_days": values, "missing": missing, "total_days": round(total, 1) if total is not None else None, "complete": not missing}


def _trade_case(state: Dict[str, Any], offer: Dict[str, Any]) -> Dict[str, Any]:
    account = _supplier_account(state, offer.get("supplier"))
    origin = _origin_country(offer, account)
    cross_border = _is_cross_border(origin)
    incoterm = _incoterm(offer)
    missing: List[str] = []
    warnings: List[str] = []
    evidence: List[str] = []
    components: Dict[str, float] = {}
    landed_cost: float | None = None

    if cross_border is None:
        missing.append("supplier_origin_country")
    if not _known(offer.get("technical_compliance")):
        missing.append("technical_compliance")

    if cross_border:
        if not incoterm:
            missing.append("incoterm")
        if incoterm and not _known(offer.get("incoterm_named_place")):
            missing.append("incoterm_named_place")
        if not _known(offer.get("hs_code") or offer.get("ncm_code")):
            missing.append("hs_or_ncm_code")
        if not _known(offer.get("origin_documentation") or offer.get("certificate_of_origin_status")):
            missing.append("origin_documentation_status")
        components, monetary_missing, monetary_evidence = _international_cost_model(offer, incoterm)
        missing.extend(monetary_missing)
        evidence.extend(monetary_evidence)
        if not monetary_missing and _f(offer.get("amount")) > 0:
            landed_cost = round(sum(components.values()), 2)
        if incoterm == "DDP" and not _known(offer.get("tax_terms")):
            warnings.append("DDP_does_not_replace_explicit_destination_tax_validation")
        if incoterm in {"EXW", "FCA", "FAS", "FOB"}:
            warnings.append("buyer_controls_more_logistics_components")
        if not bool(offer.get("source_traceable")):
            warnings.append("trade_terms_not_from_traceable_quote")
        if not _known(offer.get("currency")):
            missing.append("currency")
    elif cross_border is False:
        landed_cost, local_missing, local_evidence = _local_delivered_cost(offer)
        missing.extend(local_missing)
        evidence.extend(local_evidence)
        if landed_cost is not None:
            components = {"local_delivered_total": landed_cost}

    time_model = _time_model(offer, cross_border)
    missing.extend(time_model.get("missing", []))
    missing = list(dict.fromkeys(missing))
    warnings = list(dict.fromkeys(warnings))

    critical_fields = {
        "supplier_origin_country", "incoterm", "hs_or_ncm_code", "technical_compliance", "currency",
        "freight_cost_or_incoterm_coverage", "import_duty_amount_or_verified_exemption",
        "import_tax_amount_or_verified_tax_treatment", "customs_brokerage_cost_or_explicit_status",
        "local_delivered_total_confirmation",
    }
    critical_missing = [x for x in missing if x in critical_fields]
    confidence = 1.0 - min(0.55, len(critical_missing) * 0.10) - min(0.25, max(0, len(missing) - len(critical_missing)) * 0.035)
    if cross_border and not offer.get("source_traceable"):
        confidence -= 0.12
    confidence = max(0.15, min(0.98, confidence))

    status = "origin_required"
    if cross_border is True:
        status = "landed_cost_ready" if not missing and landed_cost is not None and time_model.get("complete") else "trade_data_incomplete"
    elif cross_border is False:
        status = "local_delivered_cost_ready" if not missing and landed_cost is not None and time_model.get("complete") else "local_cost_incomplete"

    decision_ready = (
        status in {"landed_cost_ready", "local_delivered_cost_ready"}
        and bool(offer.get("comparable"))
        and bool(offer.get("source_traceable"))
    )

    return {
        "id": f"TRADE-{offer.get('id') or len(state.get('trade_cases', []))+1}",
        "deal_id": offer.get("deal_id"),
        "offer_id": offer.get("id"),
        "supplier": offer.get("supplier"),
        "supplier_account_id": account.get("id"),
        "origin_country": origin,
        "home_market": HOME_MARKET,
        "cross_border": cross_border,
        "incoterm": incoterm,
        "incoterm_named_place": offer.get("incoterm_named_place"),
        "currency": offer.get("currency"),
        "supplier_amount": offer.get("amount"),
        "landed_cost": landed_cost,
        "landed_cost_components": components,
        "lead_time": time_model,
        "missing": missing,
        "critical_missing": critical_missing,
        "warnings": warnings,
        "evidence_fields": evidence,
        "technical_compliance": offer.get("technical_compliance"),
        "hs_or_ncm_code": offer.get("hs_code") or offer.get("ncm_code"),
        "confidence": round(confidence, 2),
        "status": status,
        "decision_ready": decision_ready,
        "updated_at": utcnow(),
    }


def _comparisons(cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_deal: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for case in cases:
        if case.get("deal_id"):
            by_deal[str(case["deal_id"])].append(case)

    out: List[Dict[str, Any]] = []
    for deal_id, items in by_deal.items():
        local = [x for x in items if x.get("cross_border") is False and x.get("decision_ready") and x.get("landed_cost") is not None]
        intl = [x for x in items if x.get("cross_border") is True and x.get("decision_ready") and x.get("landed_cost") is not None]
        currencies = {_norm(x.get("currency")) for x in local + intl if x.get("currency")}
        comparison = {
            "deal_id": deal_id,
            "status": "insufficient_normalized_routes",
            "local_routes": len(local),
            "international_routes": len(intl),
            "currency": None,
            "best_local": None,
            "best_international": None,
            "landed_savings_pct": None,
            "lead_time_delta_days": None,
            "recommendation": "collect_missing_trade_data",
            "rule": "comparar solamente costo local entregado vs landed cost internacional, con equivalencia técnica, trazabilidad y misma moneda",
            "updated_at": utcnow(),
        }
        if not local or not intl:
            out.append(comparison)
            continue
        if len(currencies) != 1:
            comparison["status"] = "currency_normalization_required"
            comparison["recommendation"] = "normalize_currency_with_verified_fx_source"
            out.append(comparison)
            continue

        best_local = min(local, key=lambda x: _f(x.get("landed_cost"), 10**18))
        best_intl = min(intl, key=lambda x: _f(x.get("landed_cost"), 10**18))
        local_cost, intl_cost = _f(best_local.get("landed_cost")), _f(best_intl.get("landed_cost"))
        savings = ((local_cost - intl_cost) / local_cost * 100.0) if local_cost > 0 else 0.0
        local_days = best_local.get("lead_time", {}).get("total_days")
        intl_days = best_intl.get("lead_time", {}).get("total_days")
        lead_delta = round(_f(intl_days) - _f(local_days), 1) if local_days is not None and intl_days is not None else None

        comparison.update({
            "status": "comparable_routes",
            "currency": best_local.get("currency"),
            "best_local": {"offer_id": best_local.get("offer_id"), "supplier": best_local.get("supplier"), "delivered_cost": local_cost, "lead_days": local_days},
            "best_international": {"offer_id": best_intl.get("offer_id"), "supplier": best_intl.get("supplier"), "origin_country": best_intl.get("origin_country"), "landed_cost": intl_cost, "lead_days": intl_days, "incoterm": best_intl.get("incoterm")},
            "landed_savings_pct": round(savings, 2),
            "lead_time_delta_days": lead_delta,
            "recommendation": (
                "international_route_economically_advantaged_review_nonprice_risk" if savings >= 5.0
                else "local_route_preferred_on_cost" if savings <= -5.0
                else "costs_close_compare_reliability_and_terms"
            ),
        })
        out.append(comparison)

    out.sort(key=lambda x: (x.get("status") == "comparable_routes", abs(_f(x.get("landed_savings_pct")))), reverse=True)
    return out[:MAX_COMPARISONS]


def _international_accounts_without_quotes(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    quoted_suppliers = {_norm(x.get("supplier")) for x in state.get("offers", []) if x.get("supplier")}
    rows: List[Dict[str, Any]] = []
    for account in _supplier_accounts(state):
        market = _name(account.get("growth_market") or account.get("market"))
        if not market or _norm(market) == _norm(HOME_MARKET):
            continue
        label = _name(account.get("company_name") or account.get("name_hint") or account.get("site_title"))
        if _norm(label) in quoted_suppliers:
            continue
        rows.append({
            "account_id": account.get("id"), "supplier": label, "market": market, "category": account.get("category"),
            "verification_score": account.get("verification_score"),
            "commercial_channel_verified": bool(account.get("commercial_channel_verified")),
            "next_action": "obtain_formal_quote_with_incoterm_origin_and_trade_terms",
        })
    rows.sort(key=lambda x: (_f(x.get("verification_score")), x.get("commercial_channel_verified")), reverse=True)
    return rows[:12]


def _primary_directive(cases: List[Dict[str, Any]], comparisons: List[Dict[str, Any]], supplier_pool: List[Dict[str, Any]]) -> Dict[str, Any]:
    comparable = next((x for x in comparisons if x.get("status") == "comparable_routes"), None)
    if comparable:
        return {
            "mode": "route_optimization", "priority": 90, "deal_id": comparable.get("deal_id"),
            "recommendation": comparable.get("recommendation"), "landed_savings_pct": comparable.get("landed_savings_pct"),
            "reason": "Existe comparación local/internacional sobre bases equivalentes: costo local entregado vs landed cost internacional.",
        }
    incomplete_intl = [x for x in cases if x.get("cross_border") is True and not x.get("decision_ready")]
    if incomplete_intl:
        first = sorted(incomplete_intl, key=lambda x: (len(x.get("critical_missing", [])), -_f(x.get("confidence"))))[0]
        return {
            "mode": "complete_trade_data", "priority": 82, "deal_id": first.get("deal_id"), "offer_id": first.get("offer_id"),
            "recommendation": "collect_missing_trade_inputs", "missing": first.get("missing", [])[:10],
            "reason": "Hay una oferta internacional real pero todavía no es seguro comparar su costo total puesto en destino.",
        }
    if supplier_pool:
        first = supplier_pool[0]
        return {
            "mode": "international_supplier_quote", "priority": 74, "supplier_account_id": first.get("account_id"),
            "market": first.get("market"), "category": first.get("category"), "recommendation": first.get("next_action"),
            "reason": "Existe proveedor internacional verificado sin cotización normalizada para evaluar landed cost.",
        }
    return {"mode": "observe", "priority": 50, "recommendation": "wait_for_verified_cross_border_evidence", "reason": "Todavía no existe evidencia comercial internacional suficiente para modelar una ruta real."}


def trade_logistics_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    real_offers = [x for x in state.get("offers", []) if x.get("source") != "demo/simulación"]
    cases = [_trade_case(state, offer) for offer in real_offers][:MAX_TRADE_CASES]
    comparisons = _comparisons(cases)
    supplier_pool = _international_accounts_without_quotes(state)
    directive = _primary_directive(cases, comparisons, supplier_pool)

    state["trade_cases"] = cases
    state["trade_route_comparisons"] = comparisons
    state["international_supplier_quote_candidates"] = supplier_pool
    state["trade_directive"] = {**directive, "updated_at": utcnow()}

    ready_cases = sum(1 for x in cases if x.get("status") == "landed_cost_ready")
    incomplete_cases = sum(1 for x in cases if x.get("cross_border") is True and x.get("status") != "landed_cost_ready")
    report = {
        "updated_at": utcnow(),
        "mode": "international_trade_and_logistics_brain",
        "home_market": HOME_MARKET,
        "offers_reviewed": len(real_offers),
        "cross_border_cases": sum(1 for x in cases if x.get("cross_border") is True),
        "landed_cost_ready": ready_cases,
        "trade_data_incomplete": incomplete_cases,
        "route_comparisons_ready": sum(1 for x in comparisons if x.get("status") == "comparable_routes"),
        "international_suppliers_without_quotes": len(supplier_pool),
        "primary_directive": directive,
        "governance": {
            "cost_rule": "no inventar flete, arancel, impuestos, seguro, aduana, tipo de cambio ni gastos bancarios; usar solo importes o tratamientos explícitos y trazables",
            "local_baseline_rule": "no comparar una importación contra un precio local desnudo; exigir costo local entregado/all-in confirmado",
            "incoterm_rule": "Incoterm define responsabilidades, no autoriza inferir importes no cotizados ni sustituye el lugar convenido",
            "tariff_rule": "clasificación HS/NCM y tratamiento arancelario/fiscal deben estar confirmados por fuente competente antes de una decisión vinculante",
            "comparison_rule": "local vs importación solo es comparable con equivalencia técnica, moneda normalizada, landed cost completo y evidencia trazable",
            "binding_rule": "selección de ruta puede prepararse automáticamente; órdenes de compra, pagos, contratos, despachos y compromisos financieros requieren aprobación humana",
        },
    }
    state["trade_logistics"] = report

    if directive.get("mode") != "observe":
        record_decision(
            state,
            engine="International Trade & Logistics Brain",
            object_type="deal" if directive.get("deal_id") else "supplier_account",
            object_id=str(directive.get("deal_id") or directive.get("supplier_account_id") or "trade"),
            decision=str(directive.get("mode")),
            reason=str(directive.get("reason")),
            action="compare_supplier_quotes" if directive.get("mode") == "route_optimization" else "prepare_draft",
            confidence=0.90 if directive.get("mode") == "route_optimization" else 0.72,
            evidence_refs=[],
            requires_approval=False,
        )
    return report
