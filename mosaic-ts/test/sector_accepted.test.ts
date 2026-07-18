import { describe, expect, it } from "vitest";
import { MACRO_AGENT_IDS } from "../src/agents/macro/_contracts.js";
import { SemiconductorSchema } from "../src/agents/sector/_schemas.js";
import {
  acceptedSectorSelectionPayload,
  buildAcceptedSectorSelection,
  modelVisibleAcceptedSectorSelection,
} from "../src/agents/sector/accepted.js";
import { directionComparisonAuditHash } from "../src/agents/sector/selection.js";
import { sectorOutput } from "./helpers/sector.js";

function acceptedFixture() {
  const comparisonAudit = { run_id: "run-1", final: "matrix-1" };
  const output = sectorOutput("semiconductor", {
    sector_runtime_binding: {
      snapshot_bundle_id: "bundle-1",
      snapshot_bundle_hash: `sha256:${"1".repeat(64)}`,
      direction_comparison_audit_hash: directionComparisonAuditHash(comparisonAudit),
      finalized_pair_matrix_hash: `sha256:${"2".repeat(64)}`,
      selection_status: "SELECTED",
      preferred_direction_id: "semiconductor_core",
      least_preferred_status: "NOT_QUALIFIED",
      least_preferred_direction_id: null,
      preferred_security_shortlist_id: "shortlist-1",
      preferred_security_shortlist_hash: `sha256:${"3".repeat(64)}`,
      least_preferred_security_shortlist_id: null,
      least_preferred_security_shortlist_hash: null,
      security_scoring_contract_version: "sector_security_scoring_v1",
      security_scoring_contract_hash: `sha256:${"4".repeat(64)}`,
      required_final_evidence_ids: ["fixture:semiconductor"],
    },
  });
  return buildAcceptedSectorSelection({
    output,
    acceptedMacroInputAttributions: MACRO_AGENT_IDS.map((agentId) => ({
      agent_id: agentId,
      usage_share: 0.1,
      target_type: "SUBMISSION_SUMMARY",
      target_ref: `accepted-target:${agentId}`,
      target_hash: `sha256:${agentId.padEnd(64, "0").slice(0, 64)}`,
      claim_refs_used: [],
      effect: "NOT_MATERIAL",
    })),
    auditBindings: {
      directionComparisonAudit: comparisonAudit,
      leastPreferredEligibilityAudit: { status: "NOT_QUALIFIED" },
      singleDirectionQualificationAudit: null,
      inferenceCostAudit: { normalized_inference_cost: 0.25 },
    },
  });
}

describe("accepted Sector contract", () => {
  it("strips raw confidence, local-ref attribution, and runtime bindings from selection payload", () => {
    const accepted = acceptedFixture();
    expect(accepted.selection).not.toHaveProperty("confidence");
    expect(accepted.selection).not.toHaveProperty("macro_input_attributions");
    expect(accepted.selection).not.toHaveProperty("sector_runtime_binding");
    expect(accepted.directional_confidence).toBe(0.6);
    expect(accepted.abstention_confidence).toBe(0);
    expect(accepted.accepted_macro_input_attributions).toHaveLength(10);
  });

  it("projects only the model-visible whitelist", () => {
    const visible = modelVisibleAcceptedSectorSelection(acceptedFixture());
    expect(Object.keys(visible).sort()).toEqual([
      "abstention_confidence",
      "directional_confidence",
      "sector_agent_id",
      "selection",
    ]);
    expect(visible).not.toHaveProperty("accepted_macro_input_attributions");
    expect(visible).not.toHaveProperty("agent_contract_version");
  });

  it("enforces five-pick, positive-conviction, unique-ticker, and per-leg budget limits", () => {
    const base = sectorOutput("semiconductor");
    const pick = (id: string, ticker: string, conviction: number) => ({
      pick_local_id: id,
      ts_code: ticker,
      direction_local_id: "semiconductor-preferred",
      position_action: "LONG" as const,
      conviction,
      thesis: "fixture security thesis",
      claim_refs: ["semiconductor-claim"],
    });
    expect(
      SemiconductorSchema.safeParse({
        ...base,
        preferred_security_status: "PICKS_PRESENT",
        preferred_security_abstention_confidence: null,
        long_picks: [pick("p1", "600000.SH", 0)],
      }).success,
    ).toBe(false);
    expect(
      SemiconductorSchema.safeParse({
        ...base,
        preferred_security_status: "PICKS_PRESENT",
        preferred_security_abstention_confidence: null,
        long_picks: [pick("p1", "600000.SH", 0.6), pick("p2", "600000.SH", 0.6)],
      }).success,
    ).toBe(false);
  });

  it("uses an explicit abstention confidence without creating directional reliability", () => {
    const output = sectorOutput("semiconductor", {
      selection_status: "NO_QUALIFIED_DIRECTION",
      preferred_direction: { status: "NO_QUALIFIED_DIRECTION" },
      least_preferred_direction: {
        status: "NO_QUALIFIED_AVOID_DIRECTION",
        reason: "PREFERRED_NOT_QUALIFIED",
      },
      confidence: 0.75,
      preferred_security_status: "NO_QUALIFIED_SECURITY",
      preferred_security_abstention_confidence: null,
      long_picks: [],
      least_preferred_security_status: "NOT_APPLICABLE",
      least_preferred_security_abstention_confidence: null,
      short_or_avoid_picks: [],
    });
    const payload = acceptedSectorSelectionPayload(output);
    expect(payload.selection_status).toBe("NO_QUALIFIED_DIRECTION");
  });
});
