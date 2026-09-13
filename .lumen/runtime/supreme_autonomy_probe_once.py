from __future__ import annotations

import json

import buyer_identity_resolver
import demand_hunter
import demand_hunter_runtime
import demand_intelligence
import growth_prospector  # noqa: F401
import scout_connector
import search_budget_governor
import supreme_autonomy_runtime

# 1) Fresh local day keeps the original total envelope, split 18 general/retail + 6 demand.
fresh = {}
general = search_budget_governor.general_budget(fresh)
demand = search_budget_governor.demand_budget(fresh)
assert search_budget_governor.TOTAL_DAILY_CAP == general["daily_budget"] + demand["daily_budget"]
assert general["queries_remaining"] == search_budget_governor.GENERAL_POOL_CAP
assert demand["queries_remaining"] == search_budget_governor.DEMAND_RESERVED

# 2) Migration from a fully consumed legacy 24-query day cannot create extra searches today.
legacy = {
    "scout_budget": {
        "date": search_budget_governor.local_day(),
        "queries_used": search_budget_governor.TOTAL_DAILY_CAP,
        "daily_budget": search_budget_governor.TOTAL_DAILY_CAP,
    }
}
legacy_general = search_budget_governor.general_budget(legacy)
legacy_demand = search_budget_governor.demand_budget(legacy)
assert legacy_general["queries_remaining"] == 0
assert legacy_demand["queries_remaining"] == 0
assert legacy_demand["migration_debt"] == search_budget_governor.DEMAND_RESERVED

# 3) Demand modules must share the protected lane rather than the generic search pool.
assert demand_hunter._budget is search_budget_governor.demand_budget
assert demand_intelligence._budget is search_budget_governor.demand_budget
assert demand_hunter.DAILY_QUERY_BUDGET == search_budget_governor.DEMAND_RESERVED
assert demand_intelligence.DAILY_QUERY_BUDGET == search_budget_governor.DEMAND_RESERVED

# 4) Supply without confirmed buyer demand forces generic discovery to buyer-only mode.
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
strategy, queue = supreme_autonomy_runtime.adaptive_search_plan(state)
assert strategy == "demand_gap_buyer_priority"
assert queue and all(row[1] == "buyer" for row in queue)

# 5) Procurement-source identity extraction/ranking is deterministic and still only creates research evidence.
signal = {
    "category": "instrumentación industrial",
    "title": "Licitación Pública - Municipalidad de Campana",
    "snippet": "Solicitud de cotización para instrumentación industrial",
    "url": "https://comprar.gob.ar/proceso/123",
    "host": "comprar.gob.ar",
    "score": 86,
}
phrase = buyer_identity_resolver._candidate_phrase(signal)
assert "municipalidad" in phrase.lower() and "campana" in phrase.lower()
scoring = buyer_identity_resolver._score_result(
    signal,
    phrase,
    {
        "title": "Municipalidad de Campana - Sitio oficial",
        "url": "https://www.campana.gob.ar/",
        "snippet": "Municipalidad de Campana. Gobierno local, compras y servicios.",
    },
)
assert scoring["score"] >= buyer_identity_resolver.MIN_RESOLUTION_SCORE
assert scoring["domain"].endswith("gob.ar")

print(json.dumps({
    "supreme_autonomy_probe": {
        "ok": True,
        "version": supreme_autonomy_runtime.VERSION,
        "budget_governor": search_budget_governor.VERSION,
        "buyer_identity_resolver": buyer_identity_resolver.VERSION,
        "total_daily_cap": search_budget_governor.TOTAL_DAILY_CAP,
        "general_retail_pool": search_budget_governor.GENERAL_POOL_CAP,
        "demand_reserved": search_budget_governor.DEMAND_RESERVED,
        "legacy_migration_fail_closed": True,
        "buyer_priority_on_demand_gap": True,
        "identity_resolution_guarded": True,
    }
}, ensure_ascii=False), flush=True)
