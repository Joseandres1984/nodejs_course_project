from __future__ import annotations

import unittest

import acquisition_sprint_runtime as sprint


def _variant(cid: str, suffix: str = "V1") -> dict:
    vid = f"{cid}-{suffix}"
    return {
        "id": vid,
        "angle": "evidence",
        "headline": "B2B evidence",
        "body": "LUMEN organiza evidencia comercial para una próxima acción verificable.",
        "cta": "Ver servicios",
        "tracking_path": f"/c/{vid}",
        "status": "testing",
        "performance": {"clicks": 0, "landing_views": 0, "submissions": 0, "verified_companies": 0, "click_to_lead_rate": 0.0, "score": 0.0},
    }


def _campaign(cid: str, audience: str) -> dict:
    v = _variant(cid)
    return {
        "id": cid,
        "audience": audience,
        "status": "active",
        "headline": "Campaign",
        "body": "Campaign body",
        "cta": "CTA",
        "champion_variant_id": v["id"],
        "variants": [v],
    }


def _state() -> dict:
    return {
        "ticks": 21,
        "candidate_accounts": [
            {
                "id": "BUY-QUOTE",
                "type": "buyer",
                "verified_company": True,
                "verified_contact": True,
                "direct_inbound_demand": True,
                "demand_signal": True,
                "category": "instrumentación industrial",
                "source_lead_id": "LEAD-RFQ",
                "source": "official_site",
            },
            {
                "id": "BUY-SUPPLIER",
                "type": "buyer",
                "verified_company": True,
                "verified_contact": True,
                "demand_signal": True,
                "category": "motores eléctricos",
                "source_lead_id": "LEAD-SUPPLIER",
                "source": "official_site",
            },
        ],
        "research_leads": [
            {
                "id": "LEAD-RFQ",
                "title": "Request for quotation RFQ instrumentación",
                "url": "https://buyer.example/rfq/123",
                "public_demand_hint": True,
                "demand_score": 96,
                "source": "official_site",
            },
            {
                "id": "LEAD-SUPPLIER",
                "title": "Necesidad pública de motores eléctricos",
                "url": "https://buyer2.example/needs/456",
                "public_demand_hint": True,
                "demand_score": 88,
                "source": "official_site",
            },
            {
                "id": "LEAD-TENDER",
                "title": "Licitación pública para bombas industriales",
                "description": "Presentar oferta según pliego oficial",
                "url": "https://procurement.example/tender/789",
                "public_demand_hint": True,
                "demand_score": 94,
                "source": "official_site",
            },
        ],
        "acquisition_campaigns": [
            _campaign("ACQ-BUYER", "buyer"),
            _campaign("ACQ-SUPPLIER", "supplier"),
        ],
        "acquisition_distribution_queue": [
            {
                "key": "EXPERIMENT|EXP-1|email_b2b",
                "campaign_id": "ACQ-BUYER",
                "variant_id": "ACQ-BUYER-V1",
                "audience": "buyer",
                "channel": "email_b2b",
                "payload": {},
                "status": "ready_owned_or_existing_channel",
            }
        ],
        "experiment_engine": {
            "status": "active",
            "current_experiment": {
                "id": "EXP-1",
                "mode": "exploit",
                "audience": "buyer",
                "variant_id": "ACQ-BUYER-V1",
                "dispatch": {"queued": True, "key": "EXPERIMENT|EXP-1|email_b2b", "channel": "email_b2b"},
            },
        },
        "cognitive_director_learning": {},
    }


class AcquisitionSprintRuntimeTests(unittest.TestCase):
    def test_real_evidence_builds_only_three_entry_products(self) -> None:
        state = _state()
        rows = sprint._ranked_candidates(state)
        products = {row["product_slug"] for row in rows}
        self.assertEqual(products, {"supplier-snapshot", "quote-sanity", "tender-scan"})
        self.assertTrue(products.issubset(set(sprint.FOCUS_PRODUCTS)))
        self.assertLessEqual(len(rows), sprint.MAX_BRIEFS_PER_CYCLE)

    def test_demo_canary_and_simulation_are_never_brief_evidence(self) -> None:
        state = _state()
        state["candidate_accounts"] = [
            {"id": "DEMO", "type": "buyer", "verified_company": True, "demand_signal": True, "source": "demo"},
            {"id": "CANARY", "type": "buyer", "verified_company": True, "demand_signal": True, "technical_canary": True},
        ]
        state["research_leads"] = [
            {"id": "SIM", "title": "Tender simulation", "url": "https://example.invalid", "public_demand_hint": True, "simulation": True},
        ]
        self.assertEqual(sprint._ranked_candidates(state), [])

    def test_sprint_routes_to_cloudflare_conversion_with_full_attribution(self) -> None:
        state = _state()
        report = sprint.acquisition_sprint_tick(state)
        self.assertEqual(report["status"], "active")
        self.assertEqual(report["selected_product_slug"], "quote-sanity")
        selected = next(row for row in state["acquisition_sprint_briefs"] if row["id"] == report["selected_brief_id"])
        url = selected["tracking_url"]
        self.assertTrue(url.startswith("https://lumen-zero-conversion.lumen-b2b.workers.dev/offer/quote-sanity?"))
        self.assertIn("src=lumen-acquisition-sprint", url)
        self.assertIn("campaign=ACQ-SPRINT-FIRST-CASH-V1", url)
        self.assertIn("offer=ASB-", url)
        self.assertNotIn("railway", url.lower())
        self.assertEqual(report["guardrails"]["monetary_budget_usd"], 0)
        self.assertFalse(report["guardrails"]["paid_media"])
        self.assertFalse(report["guardrails"]["search_budget_increased"])
        self.assertFalse(report["guardrails"]["outbound_caps_increased"])
        self.assertFalse(report["guardrails"]["binding_authority_changed"])

    def test_current_experiment_email_canary_becomes_product_specific_without_new_authority(self) -> None:
        state = _state()
        report = sprint.acquisition_sprint_tick(state)
        self.assertTrue(report["dispatch"]["queued"])
        self.assertEqual(report["dispatch"]["mode"], "experiment_dispatch_reused")
        item = state["acquisition_distribution_queue"][0]
        self.assertEqual(item["product_slug"], "quote-sanity")
        self.assertEqual(item["acquisition_sprint_id"], sprint.SPRINT_ID)
        self.assertIn("USD 7", item["payload"]["copy"])
        self.assertFalse(item["payload"]["requires_authorized_connector"])
        self.assertFalse(item["payload"]["requires_human_budget_approval"])
        self.assertEqual(item["payload"]["policy"], "verified_business_contacts_only_opt_out_respected")

    def test_generic_acquisition_links_refresh_to_conversion_not_railway(self) -> None:
        campaign = _campaign("ACQ-BUYER", "buyer")
        variant = campaign["variants"][0]
        payloads = sprint._conversion_channel_payloads(campaign, variant)
        self.assertTrue(payloads)
        for payload in payloads:
            self.assertIn("lumen-zero-conversion.lumen-b2b.workers.dev", payload["tracking_url"])
            self.assertNotIn("railway", payload["tracking_url"].lower())
        paid = next(row for row in payloads if row["channel"] == "paid_ads")
        self.assertTrue(paid["requires_human_budget_approval"])

    def test_director_keeps_hard_bottleneck_above_sprint_and_zero_budget(self) -> None:
        state = _state()
        sprint.acquisition_sprint_tick(state)
        state["canonical_revenue_truth"] = {"counts": {"verified_buyers": 3, "buyers_with_verified_demand": 0}}
        state["business_funnel"] = {"verified_buyers": 3, "buyers_with_public_demand": 0}
        report = sprint.director_tick_with_acquisition_sprint(
            state,
            {"no_progress_cycles": 0, "search": {"remaining": 2}},
        )
        self.assertEqual(report["plan"][0]["priority"], 100)
        task = next(row for row in report["plan"] if row.get("id") == "DIR-ACQUISITION-SPRINT")
        self.assertLess(task["priority"], 100)
        self.assertEqual(task["spend_usd"], 0)
        self.assertFalse(task["binding"])
        authority = report["authority"]
        self.assertEqual(authority["acquisition_sprint_monetary_budget_usd"], 0)
        self.assertFalse(authority["acquisition_sprint_search_budget_increased"])
        self.assertFalse(authority["acquisition_sprint_outbound_caps_increased"])
        self.assertFalse(authority["acquisition_sprint_binding_authority_changed"])
        self.assertFalse(authority["acquisition_sprint_hard_bottleneck_override"])
        self.assertTrue(all(float(v) <= sprint.director.ROLE_BOOST_CAP for v in report["role_boosts"].values()))


if __name__ == "__main__":
    unittest.main()
