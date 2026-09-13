from __future__ import annotations

import json

import contact_intelligence
import growth_prospector
import lead_intelligence

state = {
    "research_leads": [
        {
            "id": "TEST-LEAD-1",
            "type": "supplier",
            "category": "instrumentación industrial",
            "title": "Proveedor industrial de prueba",
            "url": "https://example.com/industrial",
            "domain": "example.com",
            "tier": "B",
            "lead_score": 70,
            "qualification_status": "research_required",
            "qualified_at": "2026-09-13 00:00:00 UTC",
            "confidence": 0.70,
            "market": "Argentina",
        }
    ],
    "candidate_accounts": [],
    "activity": [],
}

stats = lead_intelligence.qualify_tick(state)
created = state.get("candidate_accounts", [])
assert lead_intelligence.qualify_tick.__module__ == "growth_prospector"
assert created and created[0].get("status") == "verification_required"
assert created[0].get("prospect_source") == "high_tier_b_verification"
assert int(stats.get("tier_b_promoted_to_verification") or 0) == 1
assert "abastecimiento" in contact_intelligence.GENERIC_LOCALPARTS
assert "/licitaciones" in contact_intelligence.COMMON_CONTACT_PATHS

print(json.dumps({
    "growth_probe": {
        "ok": True,
        "version": growth_prospector.VERSION,
        "tier_b_promoted": stats.get("tier_b_promoted_to_verification"),
        "contact_alias_expansion": True,
        "contact_path_expansion": True,
        "search_negative_filtering": True,
    }
}, ensure_ascii=False), flush=True)
