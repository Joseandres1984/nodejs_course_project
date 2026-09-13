from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List

from operating_constitution import constitutional_check

MAX_LISTINGS = max(4, min(40, int(os.getenv("LUMEN_DISTRIBUTION_MAX_LISTINGS", "16"))))
MIN_PUBLIC_SCORE = max(35, min(90, int(os.getenv("LUMEN_DISTRIBUTION_MIN_PUBLIC_SCORE", "58"))))
MARKET = os.getenv("LUMEN_SCOUT_MARKET", "Argentina").strip() or "Argentina"

TECHNICAL_HINTS = (
    "industrial", "instrument", "manometr", "presi", "sensor", "válvula", "valvula", "bomba",
    "motor", "eléctr", "electr", "automat", "control", "medidor", "term", "caudal", "cable",
    "conector", "repuesto", "herramient", "mantenimiento", "laboratorio", "seguridad",
)
STANDARDIZED_HINTS = (
    "cable", "conector", "adaptador", "linterna", "medidor", "termómetro", "termometro",
    "herramienta", "resistencia", "diodo", "fuente", "sensor", "filtro", "interruptor",
)


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _slug_id(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def _category_from(row: Dict[str, Any]) -> str:
    for key in ("category", "need", "product", "title", "technical_scope"):
        value = " ".join(str(row.get(key) or "").split())
        if value:
            return value[:180]
    return ""


def _verified_accounts(state: Dict[str, Any], kind: str) -> List[Dict[str, Any]]:
    return [
        x for x in state.get("candidate_accounts", []) or []
        if x.get("type") == kind and x.get("verified_company")
    ]


def _account_category(account: Dict[str, Any]) -> str:
    return _category_from(account)


def _same_category(a: str, b: str) -> bool:
    aa, bb = _norm(a), _norm(b)
    if not aa or not bb:
        return False
    if aa in bb or bb in aa:
        return True
    aw = {x for x in aa.replace("/", " ").replace("-", " ").split() if len(x) >= 4}
    bw = {x for x in bb.replace("/", " ").replace("-", " ").split() if len(x) >= 4}
    return bool(aw & bw)


def _category_metrics(state: Dict[str, Any], category: str) -> Dict[str, Any]:
    suppliers = [x for x in _verified_accounts(state, "supplier") if _same_category(category, _account_category(x))]
    buyers = [x for x in _verified_accounts(state, "buyer") if _same_category(category, _account_category(x))]
    demand_buyers = [x for x in buyers if x.get("demand_signal") or x.get("public_demand_hint")]
    signals = [x for x in state.get("unlinked_demand_signals", []) or [] if _same_category(category, str(x.get("category") or ""))]
    opps = [
        x for x in (list(state.get("market_opportunities", []) or []) + list(state.get("opportunities", []) or []))
        if _same_category(category, _category_from(x))
    ]
    deals = [x for x in state.get("deals", []) or [] if _same_category(category, _category_from(x))]
    real_offers = [
        x for x in state.get("offers", []) or []
        if x.get("source") != "demo/simulación" and _same_category(category, _category_from(x))
    ]
    max_signal = max([_f(x.get("score")) for x in signals] + [0.0])
    max_opp = max([_f(x.get("portfolio_priority_score") or x.get("score")) for x in opps] + [0.0])
    return {
        "verified_suppliers": len(suppliers),
        "verified_buyers": len(buyers),
        "demand_buyers": len(demand_buyers),
        "demand_signals": len(signals),
        "real_offers": len(real_offers),
        "active_deals": len([x for x in deals if str(x.get("stage") or "") not in {"closed", "lost", "cancelled"}]),
        "best_demand_score": round(max_signal, 1),
        "best_opportunity_score": round(max_opp, 1),
        "has_public_evidence": any(x.get("source") == "public_evidence" for x in opps) or bool(signals),
    }


def _collect_categories(state: Dict[str, Any]) -> List[str]:
    weighted: Dict[str, int] = defaultdict(int)

    for row in state.get("unlinked_demand_signals", []) or []:
        category = _category_from(row)
        if category:
            weighted[category] += 4
    for row in state.get("market_opportunities", []) or []:
        category = _category_from(row)
        if category:
            weighted[category] += 5
    for row in state.get("opportunities", []) or []:
        category = _category_from(row)
        if category:
            weighted[category] += 3
    for row in _verified_accounts(state, "supplier"):
        category = _account_category(row)
        if category:
            weighted[category] += 2
    for row in state.get("deals", []) or []:
        category = _category_from(row)
        if category:
            weighted[category] += 5

    normalized: Dict[str, Dict[str, Any]] = {}
    for category, weight in weighted.items():
        key = _norm(category)
        if not key:
            continue
        if key not in normalized or weight > normalized[key]["weight"]:
            normalized[key] = {"category": category, "weight": weight}
    return [x["category"] for x in sorted(normalized.values(), key=lambda r: r["weight"], reverse=True)[:40]]


def _learning(state: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
    stats: Dict[str, Dict[str, float]] = {}
    for event in state.get("distribution_events", []) or []:
        channel = str(event.get("channel") or "")
        if not channel:
            continue
        row = stats.setdefault(channel, {"exposures": 0.0, "inquiries": 0.0, "qualified": 0.0, "wins": 0.0, "commission_usd": 0.0})
        kind = str(event.get("event") or "")
        if kind in {"published", "view", "exposure"}:
            row["exposures"] += 1
        if kind in {"inquiry", "reply"}:
            row["inquiries"] += 1
        if kind in {"qualified", "rfq"}:
            row["qualified"] += 1
        if kind in {"won", "commission_collected"}:
            row["wins"] += 1
        row["commission_usd"] += max(0.0, _f(event.get("commission_usd")))

    for channel, row in stats.items():
        exposures = max(1.0, row["exposures"])
        row["inquiry_rate"] = row["inquiries"] / exposures
        row["win_rate"] = row["wins"] / max(1.0, row["qualified"])
    return stats


def _channel_score(category: str, channel: str, metrics: Dict[str, Any], learning: Dict[str, Dict[str, float]]) -> float:
    low = _norm(category)
    technical = any(x in low for x in TECHNICAL_HINTS)
    standardized = any(x in low for x in STANDARDIZED_HINTS)
    demand = min(25.0, metrics["best_demand_score"] * 0.25 + metrics["demand_buyers"] * 5 + metrics["demand_signals"] * 2)
    supplier = min(18.0, metrics["verified_suppliers"] * 7 + metrics["real_offers"] * 4)

    base = {
        "lumen_public_catalog": 72.0,
        "targeted_b2b_email": 58.0 if technical else 48.0,
        "linkedin_company": 58.0 if technical else 42.0,
        "mercadolibre": 58.0 if standardized else 32.0,
        "b2b_directories": 50.0 if technical else 40.0,
    }.get(channel, 30.0)

    if channel == "targeted_b2b_email":
        base += min(18.0, metrics["verified_buyers"] * 4 + metrics["demand_buyers"] * 6)
    elif channel == "lumen_public_catalog":
        base += 6.0 if metrics["has_public_evidence"] else 0.0
    elif channel == "mercadolibre":
        base += 8.0 if standardized and metrics["verified_suppliers"] else 0.0
    elif channel == "linkedin_company":
        base += min(10.0, metrics["active_deals"] * 3 + metrics["demand_signals"])

    hist = learning.get(channel, {})
    if hist:
        base += min(12.0, _f(hist.get("inquiry_rate")) * 35 + _f(hist.get("win_rate")) * 25)
    return round(max(0.0, min(100.0, base + demand * 0.35 + supplier * 0.25)), 1)


def _choose_channels(category: str, metrics: Dict[str, Any], learning: Dict[str, Dict[str, float]]) -> List[Dict[str, Any]]:
    channels = ["lumen_public_catalog", "targeted_b2b_email", "linkedin_company", "mercadolibre", "b2b_directories"]
    ranked = sorted(
        [{"channel": ch, "score": _channel_score(category, ch, metrics, learning)} for ch in channels],
        key=lambda x: x["score"], reverse=True,
    )
    selected = []
    for row in ranked[:3]:
        channel = row["channel"]
        if channel == "lumen_public_catalog":
            row["execution_mode"] = "autonomous_owned_channel"
            row["connector_required"] = False
        elif channel == "targeted_b2b_email":
            row["execution_mode"] = "managed_by_existing_revops"
            row["connector_required"] = False
        else:
            row["execution_mode"] = "autonomous_when_connector_is_authorized"
            row["connector_required"] = True
        selected.append(row)
    return selected


def _listing_copy(category: str, metrics: Dict[str, Any]) -> Dict[str, str]:
    title = f"Suministro B2B de {category}"[:150]
    evidence = []
    if metrics["verified_suppliers"]:
        evidence.append(f"{metrics['verified_suppliers']} proveedor(es) verificado(s)")
    if metrics["demand_signals"]:
        evidence.append(f"{metrics['demand_signals']} señal(es) de demanda")
    if metrics["real_offers"]:
        evidence.append(f"{metrics['real_offers']} cotización(es) real(es) registrada(s)")
    proof = ", ".join(evidence[:3]) or "investigación comercial y sourcing activo"
    short = (
        f"LUMEN coordina alternativas de suministro para {category}. {proof.capitalize()}. "
        "Precio, disponibilidad, plazo y condiciones se confirman para cada requerimiento."
    )
    body = (
        f"Gestionamos sourcing e intermediación comercial B2B para {category}. "
        "Buscamos encajar una necesidad real con proveedores adecuados, comparar condiciones y coordinar la conversación comercial. "
        "No publicamos stock, precio ni disponibilidad como hechos si no están confirmados para el caso concreto. "
        "LUMEN actúa como intermediario: el comprador paga al proveedor y el proveedor entrega al comprador; "
        "LUMEN no recibe el valor bruto de la mercadería y monetiza únicamente su servicio/comisión de intermediación cuando corresponda."
    )
    return {"title": title, "short": short[:560], "body": body[:2200]}


def _score_candidate(metrics: Dict[str, Any]) -> float:
    score = 0.0
    score += min(34.0, metrics["best_demand_score"] * 0.34)
    score += min(18.0, metrics["demand_buyers"] * 8 + metrics["demand_signals"] * 2)
    score += min(24.0, metrics["verified_suppliers"] * 10 + metrics["real_offers"] * 5)
    score += min(14.0, metrics["best_opportunity_score"] * 0.14)
    score += min(10.0, metrics["active_deals"] * 5)
    if metrics["has_public_evidence"]:
        score += 5.0
    return round(max(0.0, min(100.0, score)), 1)


def distribution_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    learning = _learning(state)
    categories = _collect_categories(state)
    existing = {str(x.get("id")): x for x in state.get("autonomous_listings", []) or [] if x.get("id")}
    next_rows: List[Dict[str, Any]] = []

    constitution = constitutional_check(state, "publish_owned_catalog", outbound=True)
    owned_publish_allowed = bool(constitution.get("allowed"))

    for category in categories:
        metrics = _category_metrics(state, category)
        score = _score_candidate(metrics)
        listing_id = f"LST-{_slug_id(_norm(category))}"
        channels = _choose_channels(category, metrics, learning)
        copy = _listing_copy(category, metrics)
        previous = existing.get(listing_id, {})

        status = "published" if score >= MIN_PUBLIC_SCORE and metrics["verified_suppliers"] > 0 and owned_publish_allowed else "watching"
        if score < MIN_PUBLIC_SCORE:
            reason = "insufficient_demand_supply_evidence"
        elif metrics["verified_suppliers"] <= 0:
            reason = "verified_supplier_required"
        elif not owned_publish_allowed:
            reason = "constitutional_outbound_gate"
        else:
            reason = "evidence_backed_autonomous_publication"

        row = {
            "id": listing_id,
            "category": category,
            "market": MARKET,
            "score": score,
            "status": status,
            "reason": reason,
            "title": copy["title"],
            "summary": copy["short"],
            "description": copy["body"],
            "evidence": metrics,
            "channels": channels,
            "business_model": {
                "role": "broker_intermediary",
                "inventory_owned": False,
                "buyer_pays_supplier_directly": True,
                "supplier_delivers_to_buyer": True,
                "gross_transaction_funds_received_by_lumen": False,
                "lumen_revenue": "commission_or_success_fee_only",
            },
            "external_publication": {
                "policy": "publish_only_through_authorized_connectors_and_platform-compliant_flows",
                "ready_payload": True,
                "connector_required_for_external_channels": any(x["connector_required"] for x in channels),
            },
            "first_created_at": previous.get("first_created_at") or utcnow(),
            "updated_at": utcnow(),
        }
        next_rows.append(row)

    next_rows.sort(key=lambda x: _f(x.get("score")), reverse=True)
    state["autonomous_listings"] = next_rows[:MAX_LISTINGS]

    published = [x for x in state["autonomous_listings"] if x.get("status") == "published"]
    connector_queue = []
    for row in published:
        for channel in row.get("channels", []) or []:
            if channel.get("connector_required"):
                connector_queue.append({
                    "listing_id": row["id"],
                    "channel": channel["channel"],
                    "score": channel["score"],
                    "status": "ready_when_connector_authorized",
                    "payload": {"title": row["title"], "summary": row["summary"], "description": row["description"]},
                })
    state["distribution_connector_queue"] = connector_queue[:60]

    report = {
        "updated_at": utcnow(),
        "mode": "autonomous_commission_only_broker_distribution",
        "categories_evaluated": len(categories),
        "listings_total": len(state["autonomous_listings"]),
        "published_owned_catalog": len(published),
        "external_connector_actions_ready": len(connector_queue),
        "minimum_public_score": MIN_PUBLIC_SCORE,
        "learning_channels": learning,
        "constitutional_publish_allowed": owned_publish_allowed,
        "money_rule": "LUMEN no compra mercadería, no recibe el valor bruto de la operación y solo monetiza comisión/success fee por intermediación.",
        "primary_listing": published[0] if published else (state["autonomous_listings"][0] if state["autonomous_listings"] else None),
    }
    state["autonomous_distribution"] = report
    state.setdefault("distribution_history", []).append({
        "ts": report["updated_at"],
        "published": report["published_owned_catalog"],
        "connector_actions": report["external_connector_actions_ready"],
        "primary_listing_id": (report.get("primary_listing") or {}).get("id"),
    })
    state["distribution_history"] = state["distribution_history"][-120:]
    return report
