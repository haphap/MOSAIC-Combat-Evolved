import { createHash } from "node:crypto";
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
      preferred_direction_id: "chip_design",
      least_preferred_direction_id: "discrete_devices",
      preferred_security_shortlist_id: "shortlist-1",
      preferred_security_shortlist_hash: `sha256:${"3".repeat(64)}`,
      least_preferred_security_shortlist_id: "shortlist-2",
      least_preferred_security_shortlist_hash: `sha256:${"5".repeat(64)}`,
      security_scoring_contract_version: "sector_security_scoring_v2",
      security_scoring_contract_hash: `sha256:${"4".repeat(64)}`,
      required_preferred_evidence_ids: ["fixture:semiconductor"],
      required_least_preferred_evidence_ids: ["fixture:semiconductor"],
      required_final_evidence_ids: ["fixture:semiconductor"],
    },
  });
  const usageSummaryBody = {
    schema_version: "sector_model_usage_summary_receipt_v1",
    usage_summary_receipt_id: "sector-usage-summary:fixture",
    agent_id: "semiconductor",
    snapshot_bundle_hash: `sha256:${"1".repeat(64)}`,
    direction_comparison_audit_hash: directionComparisonAuditHash(comparisonAudit),
    model_subcall_count: 2,
    last_attempted_stage: "COMPLETED",
    conflict_review_triggered: false,
    input_tokens: 22,
    output_tokens: 11,
    model_path_disposition: "COMPLETED",
    receipt_signing_key_id: "fixture-key",
  };
  const usageSummaryHash = canonicalHash(usageSummaryBody);
  const usageSummary = {
    ...usageSummaryBody,
    usage_summary_receipt_hash: usageSummaryHash,
    receipt_signature: "fixture-signature",
  };
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
      inferenceCostAudit: {
        schema_version: "sector_runtime_inference_cost_audit_v3",
        evidence_source: "SIGNED_SERVER_MODEL_USAGE_SUMMARY",
        model_subcall_count: 2,
        last_attempted_stage: "COMPLETED",
        conflict_review_triggered: false,
        input_tokens: 22,
        output_tokens: 11,
        usage_summary_receipt: usageSummary,
        usage_summary_receipt_id: usageSummary.usage_summary_receipt_id,
        usage_summary_receipt_hash: usageSummaryHash,
        disposition: "SUCCESS",
      },
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
    expect(accepted).not.toHaveProperty("abstention_confidence");
    expect(accepted.accepted_macro_input_attributions).toHaveLength(10);
  });

  it("projects only the model-visible whitelist", () => {
    const visible = modelVisibleAcceptedSectorSelection(acceptedFixture());
    expect(Object.keys(visible).sort()).toEqual([
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

  it("rejects identical preferred and least-preferred directions", () => {
    const output = sectorOutput("semiconductor");
    output.least_preferred_direction.direction_id = output.preferred_direction.direction_id;
    expect(SemiconductorSchema.safeParse(output).success).toBe(false);
    expect(() => acceptedSectorSelectionPayload(output)).toThrow(
      "preferred and least-preferred directions must differ",
    );
  });
});

function canonicalHash(value: unknown): string {
  const canonicalize = (item: unknown): unknown => {
    if (Array.isArray(item)) return item.map(canonicalize);
    if (item !== null && typeof item === "object") {
      return Object.fromEntries(
        Object.entries(item as Record<string, unknown>)
          .sort(([left], [right]) => left.localeCompare(right))
          .map(([key, entry]) => [key, canonicalize(entry)]),
      );
    }
    return item;
  };
  return `sha256:${createHash("sha256")
    .update(JSON.stringify(canonicalize(value)))
    .digest("hex")}`;
}
