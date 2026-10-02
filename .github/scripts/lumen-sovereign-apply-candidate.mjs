import { readFileSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { validatePlaybooks } from "../../.lumen/a2a-worker/sovereign-operations.js";

// This lab accepts one small JSON playbook patch, never arbitrary executable
// code, workflow edits, paths, permissions, financial settings or secrets.
export function validateCandidate(candidate, baseContent) {
  if (!candidate || !/^CODE-[a-f0-9]{64}$/.test(candidate.id || "") || candidate.status !== "ISOLATED_PR_REQUIRED") throw new Error("invalid_lab_candidate");
  const patch = JSON.parse(candidate.patch_json);
  if (patch.path !== ".lumen/a2a-worker/sovereign-playbooks.json" || patch.encoding !== "utf-8" ||
      patch.touchesFinancialAuthority !== false || patch.autoMerge !== false || patch.autoDeploy !== false ||
      typeof patch.content !== "string" || patch.content.length > 1000 ||
      !Array.isArray(patch.evidence) || patch.evidence.length < 1) throw new Error("unsafe_lab_patch");
  if (createHash("sha256").update(baseContent).digest("hex") !== patch.baseContentSha256) throw new Error("stale_lab_base");
  const previous = validatePlaybooks(JSON.parse(baseContent)), next = validatePlaybooks(JSON.parse(patch.content));
  // Initial lab changes are reductions of workload only. No new capability or
  // greater execution limits can enter through the unattended branch builder.
  if (next.maxInternalDeals > previous.maxInternalDeals || next.minimumProductHostSignals < previous.minimumProductHostSignals ||
      next.diagnosticLookbackHours > previous.diagnosticLookbackHours) throw new Error("lab_cannot_expand_authority_or_workload");
  return { path: patch.path, content: JSON.stringify(next, null, 2) + "\n" };
}

if (process.argv[1]?.endsWith("lumen-sovereign-apply-candidate.mjs")) {
  const response = JSON.parse(readFileSync(process.argv[2], "utf-8"));
  if (!response.candidate) { console.log("NO_EVIDENCED_CANDIDATE"); process.exit(0); }
  const target = ".lumen/a2a-worker/sovereign-playbooks.json";
  const patch = validateCandidate(response.candidate, readFileSync(target, "utf-8"));
  writeFileSync(target, patch.content);
  writeFileSync("sovereign-lab-branch.txt", `lumen-v4-lab-${response.candidate.id.slice(5,25)}\n`);
  console.log("BOUNDED_PLAYBOOK_PATCH_PREPARED");
}
