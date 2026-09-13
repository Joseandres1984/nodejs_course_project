from __future__ import annotations

import json

import growth_prospector  # noqa: F401
import demand_hunter
import demand_hunter_runtime
import demand_intelligence
import lead_intelligence

state = {
    "candidate_accounts": [
        {
            "id": "SUP-1",
            "type": "supplier",
            "category": "instrumentación industrial",
            "verified_company": True,
            "market": "Argentina",
        }
    ],
    "research_leads": [],
}

assert demand_hunter._needs_hunt(state) is True
assert "solicitud de oferta" in demand_hunter._query("instrumentación industrial")
assert "registro de proveedores" in demand_hunter._query("instrumentación industrial")

lead = {
    "id": "LEAD-X",
    "type": "buyer",
    "category": "instrumentación industrial",
    "title": "Empresa industrial abre solicitud de cotización para instrumentación industrial",
    "url": "https://example.com/compras/instrumentacion",
    "snippet": "Compras y abastecimiento - solicitud de cotización vigente",
    "market": "Argentina",
    "public_demand_hint": True,
    "demand_score": 88,
}
scored = lead_intelligence.score_lead(lead)
assert int(scored.get("lead_score") or 0) > 0
assert scored.get("tier") in {"A", "B"}

state2 = {
    "candidate_accounts": [
        {
            "id": "BUY-1",
            "type": "buyer",
            "category": "instrumentación industrial",
            "verified_company": True,
            "verification_score": 85,
            "lead_score": 78,
            "public_demand_hint": True,
            "demand_discovery_score": 88,
            "domain": "example.com",
        }
    ]
}
rows = demand_intelligence._candidates(state2)
assert rows and rows[0]["id"] == "BUY-1"

print(json.dumps({
    "demand_hunter_probe": {
        "ok": True,
        "version": demand_hunter_runtime.VERSION,
        "gap_detection": True,
        "demand_query_enriched": True,
        "demand_hint_scoring": True,
        "demand_candidate_priority": True,
        "daily_cap": demand_hunter_runtime.DAILY_CAP,
    }
}, ensure_ascii=False), flush=True)
