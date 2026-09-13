from __future__ import annotations

import os
from typing import Any, Dict

import contact_intelligence
import lead_intelligence
import mission_scout
import scout_connector

VERSION = "1.0-prospect-funnel"
MIN_B_SCORE = max(55, min(74, int(os.getenv("LUMEN_PROSPECT_MIN_B_SCORE", "65"))))
MAX_B_PROMOTIONS = max(0, min(8, int(os.getenv("LUMEN_PROSPECT_B_PROMOTIONS_PER_TICK", "4"))))
NEGATIVE_SEARCH_TERMS = " -linkedin -facebook -instagram -youtube -mercadolibre -wikipedia -indeed -glassdoor -pinterest"

# Expand only public role-based corporate aliases. Personal addresses are still never inferred.
contact_intelligence.GENERIC_LOCALPARTS.update({
    "negocios", "business", "abastecimiento", "supply", "sourcing", "licitaciones",
    "presupuestos", "quotes", "cotizacion", "cotizaciones", "servicio", "soporte", "support",
    "customerservice", "customer.service", "ventasindustriales", "comercializacion",
})
_extra_paths = (
    "/abastecimiento", "/sourcing", "/licitaciones", "/cotizaciones", "/presupuestos",
    "/customer-service", "/servicio-al-cliente", "/support",
)
contact_intelligence.COMMON_CONTACT_PATHS = tuple(dict.fromkeys(contact_intelligence.COMMON_CONTACT_PATHS + _extra_paths))


def _with_negatives(rows):
    out = []
    for query, lead_type, category in rows:
        q = str(query or "").strip()
        if q and "-linkedin" not in q:
            q += NEGATIVE_SEARCH_TERMS
        out.append((q, lead_type, category))
    return out


_original_supplier_queries = scout_connector._supplier_queries
_original_buyer_queries = scout_connector._buyer_queries
_original_focused_queries = mission_scout._focused_queries


def _supplier_queries(state):
    return _with_negatives(_original_supplier_queries(state))


def _buyer_queries(state):
    return _with_negatives(_original_buyer_queries(state))


def _focused_queries(state, side):
    return _with_negatives(_original_focused_queries(state, side))


scout_connector._supplier_queries = _supplier_queries
scout_connector._buyer_queries = _buyer_queries
mission_scout._focused_queries = _focused_queries


_original_qualify_tick = lead_intelligence.qualify_tick


def _candidate_account_from_lead(state: Dict[str, Any], lead: Dict[str, Any], key: str) -> Dict[str, Any]:
    accounts = state.setdefault("candidate_accounts", [])
    return {
        "id": f"ACC-{len(accounts)+1:05d}",
        "candidate_key": key,
        "type": lead.get("type"),
        "category": lead.get("category"),
        "name_hint": lead.get("title"),
        "domain": lead.get("domain"),
        "source_url": lead.get("url"),
        "source_lead_id": lead.get("id"),
        "lead_score": lead.get("lead_score"),
        "confidence": lead.get("confidence"),
        "market": lead.get("growth_market") or lead.get("market"),
        "growth_market": lead.get("growth_market"),
        "growth_kind": lead.get("growth_kind"),
        "growth_hypothesis_key": lead.get("growth_hypothesis_key"),
        "growth_research_only": bool(lead.get("growth_research_only")),
        "status": "verification_required",
        "verified_company": False,
        "verified_contact": False,
        "prospect_source": "high_tier_b_verification",
        "next_action": "Verificar identidad, encaje y evidencia en el sitio oficial antes de cualquier outreach",
        "created_at": lead_intelligence.utcnow(),
    }


def qualify_tick(state: Dict[str, Any]) -> Dict[str, int]:
    stats = dict(_original_qualify_tick(state) or {})
    accounts = state.setdefault("candidate_accounts", [])
    known_keys = {str(x.get("candidate_key") or "") for x in accounts if x.get("candidate_key")}
    promoted = 0

    if MAX_B_PROMOTIONS > 0:
        candidates = []
        for lead in state.get("research_leads", []) or []:
            if str(lead.get("tier") or "") != "B":
                continue
            if int(lead.get("lead_score") or 0) < MIN_B_SCORE:
                continue
            if not lead.get("domain") or str(lead.get("qualification_status") or "") not in {"research_required", "qualified_candidate"}:
                continue
            key = lead_intelligence._candidate_key(lead)
            if not key or key in known_keys:
                continue
            candidates.append((int(lead.get("lead_score") or 0), str(lead.get("qualified_at") or ""), lead, key))

        candidates.sort(key=lambda row: (-row[0], row[1], str(row[2].get("id") or "")))
        for _score, _when, lead, key in candidates[:MAX_B_PROMOTIONS]:
            account = _candidate_account_from_lead(state, lead, key)
            accounts.append(account)
            known_keys.add(key)
            lead["qualification_status"] = "verification_required_high_b"
            lead["next_research_action"] = "Validación corporativa estricta por Company Verification"
            promoted += 1
            lead_intelligence.record_decision(
                state,
                engine="Lead Intelligence",
                object_type="candidate_account",
                object_id=account["id"],
                decision="high_tier_b_promoted_for_verification",
                reason=f"Lead Tier B de score {lead.get('lead_score')} con dominio identificable; se permite sólo verificación adicional, no outreach directo.",
                action="verify_company",
                confidence=float(account.get("confidence") or 0),
                evidence_refs=[str(account.get("source_url") or "")],
            )

    stats["tier_b_promoted_to_verification"] = promoted
    stats["prospect_funnel_version"] = VERSION
    stats["candidate_accounts_total"] = len(accounts)
    state.setdefault("lead_intelligence_stats", {}).update(stats)
    state["prospect_funnel"] = {
        "version": VERSION,
        "min_tier_b_score": MIN_B_SCORE,
        "max_tier_b_promotions_per_tick": MAX_B_PROMOTIONS,
        "promoted_this_tick": promoted,
        "candidate_accounts_total": len(accounts),
        "search_spend_policy": "same_query_budget_better_result_utilization",
        "contact_policy": "public_role_emails_only_no_personal_inference",
        "updated_at": lead_intelligence.utcnow(),
    }
    if promoted:
        lead_intelligence._log(state, f"Prospect Funnel promovió {promoted} leads B fuertes a verificación corporativa estricta; todavía no habilita contacto.")
    return stats


lead_intelligence.qualify_tick = qualify_tick
