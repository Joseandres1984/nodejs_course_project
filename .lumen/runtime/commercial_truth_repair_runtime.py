from __future__ import annotations

"""Commercial truth repair for LUMEN.

Repairs four high-value conversion gaps without widening authority:
- current official procurement evidence may populate RFQ fields only when the exact values are present;
- stale procurement results are strongly demoted;
- outbound "sent" is treated as genuine contact only after provider acceptance or verified delivery;
- dashboard metrics expose raw vs provider-accepted sends separately.

No requirement, quantity, delivery location, quote, delivery, reply or revenue is fabricated.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List
from urllib.parse import urlparse
import re

import conversion_unblock_runtime
import interlocutor_engine
import outbound_engine
import public_procurement_hunter

VERSION = "1.0-commercial-truth-repair"

_ORIGINAL_PROCUREMENT_SCORE = public_procurement_hunter._score
_ORIGINAL_INTERLOCUTOR_TICK = interlocutor_engine.interlocutor_tick
_ORIGINAL_OUTBOUND_METRICS = outbound_engine._metrics


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _clean(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _host(url: Any) -> str:
    try:
        return (urlparse(str(url or "")).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _official_procurement_host(host: str) -> bool:
    if not host:
        return False
    return (
        host.endswith(".gob.ar")
        or host.endswith(".gov.ar")
        or host in {
            "comprar.gob.ar",
            "boletinoficial.gob.ar",
            "nuevaweb.boletinoficial.gob.ar",
            "argentina.gob.ar",
            "compras.tierradelfuego.gob.ar",
        }
    )


def _signal_text(signal: Dict[str, Any]) -> str:
    return " ".join(
        _clean(signal.get(k))
        for k in ("title", "snippet", "summary", "query", "category", "url")
        if _clean(signal.get(k))
    )


def _is_current_official_signal(signal: Dict[str, Any]) -> bool:
    url = signal.get("url") or signal.get("source_url")
    host = _host(url) or _clean(signal.get("host") or signal.get("source"))
    if not _official_procurement_host(host):
        return False
    year = datetime.now(timezone.utc).year
    text = _signal_text(signal)
    years = {int(x) for x in re.findall(r"\b20\d{2}\b", text)}
    # Current-year evidence is accepted. Explicitly older evidence without the current year is rejected.
    if year in years:
        return True
    if years and max(years) < year:
        return False
    # A current-year collection timestamp alone is not enough to claim the procurement itself is current.
    return False


def _fresh_procurement_score(category: str, item: Dict[str, str]) -> Dict[str, Any]:
    result = dict(_ORIGINAL_PROCUREMENT_SCORE(category, item) or {})
    text = f"{item.get('title') or ''} {item.get('snippet') or ''} {item.get('url') or ''}"
    year = datetime.now(timezone.utc).year
    years = {int(x) for x in re.findall(r"\b20\d{2}\b", text)}
    if year in years:
        result["score"] = min(100, int(result.get("score") or 0) + 8)
        result["freshness"] = "current_year_explicit"
    elif years and max(years) < year:
        result["score"] = min(int(result.get("score") or 0), 35)
        result["freshness"] = "stale_explicit_year"
    else:
        result["score"] = max(0, int(result.get("score") or 0) - 8)
        result["freshness"] = "year_unverified"
    return result


public_procurement_hunter._score = _fresh_procurement_score


def _all_procurement_signals(state: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    seen: set[str] = set()
    for key in ("unlinked_demand_signals", "public_procurement_signals"):
        for signal in state.get(key, []) or []:
            if not isinstance(signal, dict):
                continue
            url = str(signal.get("url") or signal.get("source_url") or "")
            if not url or url in seen:
                continue
            seen.add(url)
            yield signal


def _extract_quantity(text: str) -> str | None:
    patterns = (
        r"\b(?:cantidad|cant\.?|unidades?|unidad)\s*(?:[:=xX\-]|de)?\s*(\d+(?:[.,]\d+)?)\b",
        r"\b(\d+(?:[.,]\d+)?)\s*(?:unidades?|uds?\.?|u\.)\b",
        r"\bx\s*(\d+(?:[.,]\d+)?)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            return match.group(1).replace(",", ".")
    return None


def _extract_delivery_location(text: str) -> str | None:
    patterns = (
        r"(?:lugar|sitio|domicilio)\s+de\s+entrega\s*[:\-]\s*([^.;\n]{3,120})",
        r"entrega\s+(?:en|a realizarse en)\s+([^.;\n]{3,120})",
        r"lugar\s+de\s+recepci[oó]n\s*[:\-]\s*([^.;\n]{3,120})",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            value = _clean(match.group(1))[:120]
            if len(value) >= 3:
                return value
    return None


def _extract_technical_scope(signal: Dict[str, Any]) -> str | None:
    title = _clean(signal.get("title"))
    summary = _clean(signal.get("summary") or signal.get("snippet"))
    category = _clean(signal.get("category"))
    demand_terms = ("licit", "adquis", "solicitud de cot", "compra", "contrat")
    combined = f"{title} {summary}".lower()
    if not any(term in combined for term in demand_terms):
        return None
    parts = [x for x in (title, summary, category) if x]
    exact = " | ".join(parts)
    return exact[:700] if exact else None


def _signal_map(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        str(signal.get("url") or signal.get("source_url") or ""): signal
        for signal in _all_procurement_signals(state)
        if _is_current_official_signal(signal)
    }


def _candidate_urls(state: Dict[str, Any], case: Dict[str, Any], opportunity: Dict[str, Any]) -> List[str]:
    urls: List[str] = []
    for value in opportunity.get("evidence_refs", []) or []:
        if isinstance(value, str) and value.startswith("http"):
            urls.append(value)
    accounts = {
        str(x.get("id") or ""): x
        for x in state.get("candidate_accounts", []) or []
        if isinstance(x, dict)
    }
    buyer = accounts.get(str(case.get("buyer_account_id") or opportunity.get("buyer_account_id") or ""), {})
    for key in ("demand_evidence_url", "source_url", "official_url"):
        value = buyer.get(key)
        if isinstance(value, str) and value.startswith("http"):
            urls.append(value)
    for value in buyer.get("demand_evidence_urls", []) or []:
        if isinstance(value, str) and value.startswith("http"):
            urls.append(value)
    return list(dict.fromkeys(urls))


def _apply_procurement_requirement_evidence(state: Dict[str, Any]) -> Dict[str, int]:
    signals = _signal_map(state)
    opportunities = {
        str(x.get("id") or ""): x
        for x in state.get("market_opportunities", []) or []
        if isinstance(x, dict)
    }
    stats = {"matched": 0, "fields_added": 0, "rfq_ready_from_official_evidence": 0}

    for case in state.get("interlocution_cases", []) or []:
        if not isinstance(case, dict):
            continue
        opp = opportunities.get(str(case.get("opportunity_id") or ""), {})
        if not opp:
            continue
        matched_signal = None
        matched_url = None
        for url in _candidate_urls(state, case, opp):
            if url in signals:
                matched_signal = signals[url]
                matched_url = url
                break
        if not matched_signal:
            continue

        stats["matched"] += 1
        requirement = case.setdefault("requirement", {})
        text = _signal_text(matched_signal)
        extracted = {
            "technical_scope": _extract_technical_scope(matched_signal),
            "quantity": _extract_quantity(text),
            "delivery_location": _extract_delivery_location(text),
        }
        field_sources = requirement.setdefault("field_evidence", {})
        for field, value in extracted.items():
            if value in (None, "") or requirement.get(field) not in (None, "", [], {}):
                continue
            requirement[field] = value
            field_sources[field] = {
                "source": "official_current_public_procurement",
                "url": matched_url,
                "captured_at": _now(),
            }
            stats["fields_added"] += 1

        requirement["public_procurement_evidence_urls"] = list(dict.fromkeys(
            list(requirement.get("public_procurement_evidence_urls", []) or []) + [matched_url]
        ))[-6:]
        requirement["confirmed_by_public_procurement_evidence"] = True
        requirement["source"] = "official_current_public_procurement_evidence"
        requirement["public_procurement_evidence_year"] = datetime.now(timezone.utc).year

        missing = [
            field for field in conversion_unblock_runtime.RFQ_MINIMUM_FIELDS
            if requirement.get(field) in (None, "", [], {})
        ]
        case["missing_required_fields"] = missing
        case["requirement_completeness"] = interlocutor_engine._completeness(requirement)
        case["buyer_questions"] = interlocutor_engine._questions(missing)
        if not missing:
            case["supplier_rfq_ready"] = True
            case["status"] = "ready_for_supplier_rfq"
            case["requirement_confirmation_basis"] = "official_current_public_procurement_evidence"
            case["next_action"] = "Solicitar ofertas comparables a proveedores validados"
            opp["requirement_confirmed"] = True
            opp["requirements_ready_for_rfq"] = True
            opp["requirement_confirmation_basis"] = "official_current_public_procurement_evidence"
            opp["requirement_evidence_url"] = matched_url
            opp["next_action"] = "Solicitar/normalizar ofertas comparables y completar economía real"
            opp["updated_at"] = _now()
            stats["rfq_ready_from_official_evidence"] += 1

    state["procurement_requirement_bridge"] = {
        "version": VERSION,
        "status": "active",
        **stats,
        "policy": "current_official_exact_evidence_only_no_inference",
        "updated_at": _now(),
    }
    return stats


def _interlocutor_tick_with_procurement_bridge(state: Dict[str, Any]) -> Dict[str, Any]:
    _apply_procurement_requirement_evidence(state)
    report = dict(_ORIGINAL_INTERLOCUTOR_TICK(state) or {})
    bridge = _apply_procurement_requirement_evidence(state)
    report["public_procurement_evidence_matched"] = bridge["matched"]
    report["public_procurement_fields_added"] = bridge["fields_added"]
    report["public_procurement_rfq_ready"] = bridge["rfq_ready_from_official_evidence"]
    report["requirement_ready"] = sum(
        1 for x in state.get("interlocution_cases", []) or [] if x.get("supplier_rfq_ready")
    )
    report["awaiting_details"] = sum(
        1 for x in state.get("interlocution_cases", []) or [] if not x.get("supplier_rfq_ready")
    )
    return report


interlocutor_engine.interlocutor_tick = _interlocutor_tick_with_procurement_bridge


def _provider_accepted(item: Dict[str, Any]) -> bool:
    if str(item.get("provider_last_event") or "").lower() == "delivered" or item.get("delivered_at"):
        return True
    if str(item.get("status") or "").lower() != "sent":
        return False
    if item.get("last_error"):
        return False
    provider = str(item.get("email_provider") or "").lower()
    provider_id = _clean(item.get("email_provider_message_id"))
    return provider in {"brevo", "resend"} and bool(provider_id)


def _recently_contacted_truthful(state: Dict[str, Any], email: str) -> bool:
    cutoff = outbound_engine.utcnow_dt() - outbound_engine.timedelta(days=outbound_engine.RECONTACT_DAYS)
    for item in reversed(state.get("outbox", []) or []):
        if str(item.get("contact") or "").strip().lower() != email:
            continue
        if item.get("source") not in {"outbound_engine", "distribution_operator_canary"}:
            continue
        if not _provider_accepted(item):
            continue
        when = outbound_engine._parse(item.get("sent_at") or item.get("delivered_at") or item.get("created_at"))
        if when and when >= cutoff:
            return True
    return False


def _latest_engine_sent_truthful(state: Dict[str, Any], contact: str) -> Dict[str, Any]:
    rows = [
        x for x in state.get("outbox", []) or []
        if x.get("source") == "outbound_engine"
        and str(x.get("contact") or "").strip().lower() == contact
        and _provider_accepted(x)
    ]
    rows.sort(key=lambda x: str(x.get("sent_at") or x.get("delivered_at") or x.get("created_at") or ""), reverse=True)
    return rows[0] if rows else {}


outbound_engine._recently_contacted = _recently_contacted_truthful
outbound_engine._latest_engine_sent = _latest_engine_sent_truthful


def _truthful_outbound_metrics(
    state: Dict[str, Any],
    prospects: List[Dict[str, Any]],
    new_queued: int,
    followups: int,
    delivery_checks: int,
    requeued: int,
) -> Dict[str, Any]:
    report = dict(_ORIGINAL_OUTBOUND_METRICS(state, prospects, new_queued, followups, delivery_checks, requeued) or {})
    messages = [x for x in state.get("outbox", []) or [] if x.get("source") == "outbound_engine"]
    raw_sent = [x for x in messages if str(x.get("status") or "").lower() == "sent"]
    accepted = [x for x in messages if _provider_accepted(x)]
    delivered = [x for x in accepted if str(x.get("provider_last_event") or "").lower() == "delivered" or x.get("delivered_at")]
    report["sent_recorded_total"] = len(raw_sent)
    report["sent_total"] = len(accepted)
    report["provider_accepted_total"] = len(accepted)
    report["delivered_verified"] = len(delivered)
    report["truth_rule"] = "sent_counts_only_provider_accepted_or_verified_delivery"
    return report


outbound_engine._metrics = _truthful_outbound_metrics

print(
    {
        "commercial_truth_repair_runtime": {
            "version": VERSION,
            "status": "active",
            "current_public_procurement_requirement_bridge": True,
            "stale_procurement_demotion": True,
            "outbound_provider_acceptance_truth": True,
            "binding_authority_changed": False,
        }
    },
    flush=True,
)
