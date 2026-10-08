import assert from "node:assert/strict";
import { getFirstSettlementMissionStatus, FIRST_SETTLEMENT_MISSION_POLICY } from "./first-settlement-mission-v1.js";

const sent = {
  opportunity_id:"OPP-EXISTING-SENT", proposal_id:"PROP-EXISTING",
  offer_id:"MP-TENDER-LEAD", stage:"SENT", intent_score:0.67,
  first_cash_score:0.3, updated_at:"2026-10-08T02:30:00Z",
  quality_gate_status:"PASS", commercially_actionable:1,
  commercial_score:100, evidence_strength:"strong",
  synthetic_or_test_only:0, outreach_status:"SENT"
};
const queries=[];
const makeDb = (history,recovered) => ({
  prepare(sql) {
    queries.push(sql);
    return { async all() {
      return {results:sql.includes("FROM lumen_opportunities o")?recovered:history};
    }};
  }
});
const status=await getFirstSettlementMissionStatus({DB:makeDb([], [sent])});
assert.equal(status.ok,true);
assert.equal(status.mission.status,"ACTIVE");
assert.equal(status.mission.focus.proposal_id,sent.proposal_id);
assert.equal(status.mission.diagnosis.blocker,"WAITING_BUYER_RESPONSE");
assert.equal(status.recoverySource,"verified_opportunity_recovery");
assert.equal(status.recoveryCount,1);
assert.equal(status.trackedCandidates,0);
assert.ok(queries[0].includes("a.commercially_actionable=1 AND a.commercial_score>=65"));
assert.ok(queries[0].includes("LIMIT 100"));
assert.ok(queries[1].includes("JOIN lumen_opportunity_assessments"));
assert.ok(queries[1].includes("b.receipt_id IS NULL"));
const existing=await getFirstSettlementMissionStatus({DB:makeDb([sent],[])});
assert.equal(existing.recoverySource,"revenue_loop");
assert.equal(existing.recoveryCount,0);
assert.equal(existing.mission.focus.proposal_id,sent.proposal_id);
const empty=await getFirstSettlementMissionStatus({DB:makeDb([],[])});
assert.equal(empty.mission.status,"NO_OPEN_MISSION");
assert.equal(empty.recoveryCount,0);
assert.equal(FIRST_SETTLEMENT_MISSION_POLICY.prefilterCommercialTruthBeforeLimit,true);
assert.equal(FIRST_SETTLEMENT_MISSION_POLICY.readOnlyRecoveryForUntrackedOpportunities,true);
assert.equal(FIRST_SETTLEMENT_MISSION_POLICY.recoverySendsMessages,false);
console.log("FIRST_SETTLEMENT_TRACKING_RECOVERY_OK");
