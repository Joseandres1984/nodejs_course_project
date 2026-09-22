from __future__ import annotations

import unittest

import demand_recovery_runtime as recovery


class DemandRecoveryRuntimeTests(unittest.TestCase):
    def _buyer(self, account_id: str, verification: int = 80, lead: int = 70, demand_score: int = 0):
        return {
            "id": account_id,
            "type": "buyer",
            "verified_company": True,
            "domain": f"{account_id.lower()}.example",
            "category": "instrumentación industrial",
            "verification_score": verification,
            "lead_score": lead,
            "demand_score": demand_score,
            "demand_signal": False,
        }

    def test_stored_strong_exact_evidence_gets_priority_without_promoting_demand(self):
        evidence_buyer = self._buyer("ACC-EVIDENCE", verification=90, lead=80, demand_score=60)
        clean_buyer = self._buyer("ACC-CLEAN", verification=90, lead=80, demand_score=0)
        state = {
            "autonomous_director": {"stall_cycles": 14},
            "research_leads": [
                {
                    "account_id": "ACC-EVIDENCE",
                    "title": "Solicitud de cotización de instrumentación industrial",
                    "snippet": "Compras solicita proveedores y cotización para instrumentación industrial",
                    "url": "https://buyer.example/procurement/123",
                    "score": 68,
                }
            ],
        }

        queue = recovery.build_queue(state, [clean_buyer, evidence_buyer])

        self.assertEqual(queue[0]["account_id"], "ACC-EVIDENCE")
        self.assertGreater(queue[0]["strong_evidence_rows"], 0)
        self.assertFalse(evidence_buyer["demand_signal"])
        self.assertFalse(clean_buyer["demand_signal"])

    def test_portfolio_rotation_penalizes_recently_repeated_buyer(self):
        recent = self._buyer("ACC-RECENT", verification=90, lead=80)
        fresh = self._buyer("ACC-FRESH", verification=90, lead=80)
        state = {
            "autonomous_director": {"stall_cycles": 8},
            "demand_recovery": {
                "history": [
                    {"selected_account_ids": ["ACC-RECENT"]},
                    {"selected_account_ids": ["ACC-RECENT"]},
                ]
            },
        }

        queue = recovery.build_queue(state, [recent, fresh])

        self.assertEqual(queue[0]["account_id"], "ACC-FRESH")
        self.assertEqual(recovery._mode(8), "portfolio_rotation")

    def test_candidate_wrapper_preserves_original_eligibility_and_cooldown_scope(self):
        eligible = self._buyer("ACC-ELIGIBLE")
        ineligible_not_returned_by_original = self._buyer("ACC-COOLDOWN")
        ineligible_not_returned_by_original["demand_next_check"] = "2099-01-01"
        original = recovery._ORIGINAL_CANDIDATES
        try:
            recovery._ORIGINAL_CANDIDATES = lambda state: [eligible]
            ordered = recovery._prioritized_candidates(
                {
                    "autonomous_director": {"stall_cycles": 20},
                    "candidate_accounts": [eligible, ineligible_not_returned_by_original],
                }
            )
        finally:
            recovery._ORIGINAL_CANDIDATES = original

        self.assertEqual([row["id"] for row in ordered], ["ACC-ELIGIBLE"])
        self.assertEqual(ineligible_not_returned_by_original["demand_next_check"], "2099-01-01")

    def test_recovery_logic_failure_falls_back_to_original_candidate_order(self):
        a = self._buyer("ACC-A")
        b = self._buyer("ACC-B")
        original_candidates = recovery._ORIGINAL_CANDIDATES
        original_build_queue = recovery.build_queue
        try:
            recovery._ORIGINAL_CANDIDATES = lambda state: [a, b]

            def broken_queue(state, eligible):
                raise RuntimeError("synthetic recovery failure")

            recovery.build_queue = broken_queue
            ordered = recovery._prioritized_candidates({})
        finally:
            recovery._ORIGINAL_CANDIDATES = original_candidates
            recovery.build_queue = original_build_queue

        self.assertEqual([row["id"] for row in ordered], ["ACC-A", "ACC-B"])

    def test_run_once_reports_guardrails_unchanged(self):
        buyer = self._buyer("ACC-A")
        original_candidates = recovery._ORIGINAL_CANDIDATES
        original_save_state = recovery.app.save_state
        try:
            recovery._ORIGINAL_CANDIDATES = lambda state: [buyer]
            recovery.app.save_state = lambda: True
            report = recovery.run_once({
                "ticks": 99,
                "autonomous_director": {"stall_cycles": 15},
                "candidate_accounts": [buyer],
            })
        finally:
            recovery._ORIGINAL_CANDIDATES = original_candidates
            recovery.app.save_state = original_save_state

        self.assertEqual(report["mode"], "challenge_plan")
        self.assertEqual(report["minimum_demand_score_unchanged"], 75)
        self.assertEqual(report["searches_used"], 0)
        self.assertFalse(report["search_cap_changed"])
        self.assertFalse(report["cooldowns_bypassed"])
        self.assertFalse(report["requirements_inferred"])
        self.assertFalse(report["outbound_gate_relaxed"])
        self.assertFalse(report["binding_authority_changed"])
        self.assertEqual(report["monetary_budget_usd"], 0)
        self.assertFalse(buyer["demand_signal"])


if __name__ == "__main__":
    unittest.main()
