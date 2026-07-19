import { describe, expect, it } from "vitest";
import { z } from "zod";
import {
  adaptMacroAttributionProviderJsonSchema,
  type MacroInputAttributionSubmission,
  MacroInputAttributionSubmissionArraySchema,
  normalizeMacroAttributionProviderPayload,
  resolveMacroInputAttributions,
} from "../src/agents/helpers/macro_attribution.js";
import { MACRO_AGENT_IDS } from "../src/agents/macro/_contracts.js";
import type { MacroAgentId, MacroAgentOutput, MacroInputGateReceipt } from "../src/agents/types.js";

function outputs(): Record<string, MacroAgentOutput> {
  return Object.fromEntries(
    MACRO_AGENT_IDS.map((agentId) => [
      agentId,
      {
        agent_id: agentId,
        agent_contract_version: "macro-v2",
        prompt_behavior_version: "prompt-v2",
        execution_behavior_version: "execution-v2",
        component_weight_contract_version: null,
        direction: "NEUTRAL",
        strength: 0,
        persistence_horizon: "DAYS",
        evaluation_horizon_trading_days: 5,
        model_confidence: 0.5,
        deterministic_data_quality: 1,
        confidence: 0.5,
        channels: ["test"],
        claims: [
          {
            claim_id: `${agentId}-claim`,
            claim_kind: "FACT",
            statement: `${agentId} fact`,
            structured_conclusion: { agent_id: agentId },
            evidence_ids: [`evidence:${agentId}`],
            research_rule_refs: [],
          },
        ],
        claim_refs: [`${agentId}-claim`],
        key_drivers: ["test"],
      } satisfies MacroAgentOutput,
    ]),
  );
}

function gate(): MacroInputGateReceipt {
  return {
    schema_version: "macro_input_gate_receipt_v1",
    accepted_agent_ids: [...MACRO_AGENT_IDS],
    accepted_count: 10,
    input_hash: "sha256:gate",
    source_layer_snapshot_id: "macro-layer:test",
    source_layer_snapshot_hash: "sha256:macro-layer",
    darwinian_snapshot_id: null,
    darwinian_snapshot_hash: null,
    reliability_by_agent: Object.fromEntries(
      MACRO_AGENT_IDS.map((agentId, index) => [
        agentId,
        {
          effective_reliability: 1,
          usage_share: (index + 1) / 55,
          weight_record_id: null,
          reliability_record_id: null,
        },
      ]),
    ) as MacroInputGateReceipt["reliability_by_agent"],
  };
}

function summaries(): MacroInputAttributionSubmission[] {
  return MACRO_AGENT_IDS.map((agentId) => ({
    agent_id: agentId,
    target_type: "SUBMISSION_SUMMARY",
    target_local_ref: "$SUBMISSION",
    claim_refs_used: [`${agentId}-claim`],
    effect: "SUPPORTS",
  }));
}

describe("Macro input attribution v2", () => {
  it("requires one and only one submission summary for every Macro Agent", () => {
    const providerSchema = z.toJSONSchema(MacroInputAttributionSubmissionArraySchema);
    expect(providerSchema).toMatchObject({ minItems: 10, maxItems: 16 });
    expect(MacroInputAttributionSubmissionArraySchema.safeParse(summaries()).success).toBe(true);
    expect(MacroInputAttributionSubmissionArraySchema.safeParse(summaries().slice(1)).success).toBe(
      false,
    );
    expect(
      MacroInputAttributionSubmissionArraySchema.safeParse([
        summaries()[1],
        summaries()[0],
        ...summaries().slice(2),
      ]).success,
    ).toBe(false);
    expect(
      MacroInputAttributionSubmissionArraySchema.safeParse([...summaries(), summaries()[0]])
        .success,
    ).toBe(false);
  });

  it("uses a bounded keyed provider shape and normalizes it to canonical rows", () => {
    const domainSchema = z.toJSONSchema(
      z.object({ macro_input_attributions: MacroInputAttributionSubmissionArraySchema }),
    );
    const adapted = adaptMacroAttributionProviderJsonSchema(domainSchema) as {
      properties: {
        macro_input_attributions: {
          type: string;
          properties: { submission_summaries: { required: string[] } };
        };
      };
    };
    expect(adapted.properties.macro_input_attributions.type).toBe("object");
    expect(
      adapted.properties.macro_input_attributions.properties.submission_summaries.required,
    ).toEqual([...MACRO_AGENT_IDS]);
    expect(adapted.properties.macro_input_attributions).not.toHaveProperty("$schema");

    const normalized = normalizeMacroAttributionProviderPayload({
      final_selection: {
        macro_input_attributions: {
          submission_summaries: Object.fromEntries(
            MACRO_AGENT_IDS.map((agentId) => [
              agentId,
              { claim_ref_used: `${agentId}-claim`, effect: "SUPPORTS" },
            ]),
          ),
          target_attributions: [],
        },
      },
    }) as { final_selection: { macro_input_attributions: MacroInputAttributionSubmission[] } };
    expect(normalized.final_selection.macro_input_attributions).toEqual(summaries());
    expect(
      MacroInputAttributionSubmissionArraySchema.safeParse(
        normalized.final_selection.macro_input_attributions,
      ).success,
    ).toBe(true);
  });

  it("limits standard Sector target attribution to exact supported target types", () => {
    const adapted = adaptMacroAttributionProviderJsonSchema(
      z.toJSONSchema(
        z.object({
          agent: z.literal("energy"),
          selection_status: z.literal("SELECTED"),
          macro_input_attributions: MacroInputAttributionSubmissionArraySchema,
        }),
      ),
    ) as {
      properties: {
        macro_input_attributions: {
          properties: {
            target_attributions: {
              items: { properties: { target_type: { enum: string[] } } };
            };
          };
        };
      };
    };
    expect(
      adapted.properties.macro_input_attributions.properties.target_attributions.items.properties
        .target_type.enum,
    ).toEqual(["SECTOR_THESIS", "SECURITY_PICK"]);
  });

  it("resolves local targets and copies authoritative usage shares", () => {
    const rows = summaries();
    rows.push({
      agent_id: "china",
      target_type: "SECURITY_PICK",
      target_local_ref: "pick-1",
      claim_refs_used: ["china-claim"],
      effect: "SUPPORTS",
    });
    const accepted = resolveMacroInputAttributions({
      submissions: rows,
      acceptedMacroOutputs: outputs(),
      macroInputGate: gate(),
      acceptedSubmissionBody: {
        selection_status: "SELECTED",
        macro_input_attributions: rows,
        accepted_at: "future-runtime-field",
      },
      targets: [
        {
          target_type: "SECURITY_PICK",
          target_local_ref: "pick-1",
          target: { pick_local_id: "pick-1", ts_code: "600000.SH" },
        },
      ],
    });
    const chinaSummary = accepted.find(
      (row) => row.agent_id === "china" && row.target_type === "SUBMISSION_SUMMARY",
    );
    const chinaTarget = accepted.find((row) => row.target_type === "SECURITY_PICK");
    expect(chinaSummary?.usage_share).toBeCloseTo(1 / 55);
    expect(chinaSummary?.target_ref).toMatch(/^accepted-target:submission:/);
    expect(chinaTarget?.target_ref).toMatch(/^accepted-target:security_pick:/);
    expect(chinaTarget?.target_hash).toMatch(/^sha256:[0-9a-f]{64}$/);
  });

  it("rejects claims that are not owned by the named Macro Agent", () => {
    const rows = summaries();
    const china = rows.find((row) => row.agent_id === "china");
    if (!china) throw new Error("missing china fixture");
    china.claim_refs_used = ["us_economy-claim"];
    expect(() =>
      resolveMacroInputAttributions({
        submissions: rows,
        acceptedMacroOutputs: outputs(),
        macroInputGate: gate(),
        acceptedSubmissionBody: { status: "test" },
      }),
    ).toThrow(/unowned claim/);
  });

  it("rejects unresolved target-local refs and material rows without claims", () => {
    const rows = summaries();
    rows.push({
      agent_id: "china" as MacroAgentId,
      target_type: "RISK_ACTION",
      target_local_ref: "missing-risk-action",
      claim_refs_used: ["china-claim"],
      effect: "RISK_ONLY",
    });
    expect(() =>
      resolveMacroInputAttributions({
        submissions: rows,
        acceptedMacroOutputs: outputs(),
        macroInputGate: gate(),
        acceptedSubmissionBody: { status: "test" },
      }),
    ).toThrow(/unresolved attribution target/);
    expect(
      MacroInputAttributionSubmissionArraySchema.safeParse([
        ...summaries().slice(0, -1),
        {
          agent_id: "institutional_flow",
          target_type: "SUBMISSION_SUMMARY",
          target_local_ref: "$SUBMISSION",
          claim_refs_used: [],
          effect: "SUPPORTS",
        },
      ]).success,
    ).toBe(false);
  });
});
