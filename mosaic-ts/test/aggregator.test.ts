import { describe, expect, it } from "vitest";
import type { AcceptedOutputRecordRef } from "../src/agents/accepted_output.js";
import {
  buildMacroComponentCompositionAudit,
  composeAcceptedMacroTransmission,
  createMacroSubmissionSchema,
  MACRO_AGENT_IDS,
  MACRO_ROLE_CONTRACTS,
  TOMBSTONED_MACRO_AGENT_IDS,
} from "../src/agents/macro/_contracts.js";
import { validateMacroInputs } from "../src/agents/macro/_input_gate.js";
import type { MacroAgentId, MacroAgentSubmission } from "../src/agents/types.js";
import type { ComponentWeightRuntimeResolution } from "../src/autoresearch/production_variant.js";
import { macroOutput, macroSubmission } from "./helpers/macro.js";

describe("v2 macro composition and input gate", () => {
  it("has ten production roles and five audit-only tombstones", () => {
    expect(MACRO_AGENT_IDS).toHaveLength(10);
    expect(new Set(MACRO_AGENT_IDS).size).toBe(10);
    expect(TOMBSTONED_MACRO_AGENT_IDS).toEqual([
      "dollar",
      "yield_curve",
      "volatility",
      "emerging_markets",
      "news_sentiment",
    ]);
  });

  it("accepts the exact component set once and rejects missing, duplicate, or extra components", () => {
    const valid = macroSubmission("central_bank");
    expect(MACRO_ROLE_CONTRACTS.central_bank.mode).toBe("COMPONENTS");
    if (valid.mode !== "COMPONENTS") throw new Error("fixture mode mismatch");
    const schema = createMacroSubmissionSchema("central_bank");
    expect(schema.safeParse(valid).success).toBe(true);
    expect(schema.safeParse({ ...valid, components: valid.components.slice(1) }).success).toBe(
      false,
    );
    expect(
      schema.safeParse({ ...valid, components: [...valid.components, valid.components[0]] })
        .success,
    ).toBe(false);
    expect(
      schema.safeParse({
        ...valid,
        components: [...valid.components.slice(1), { ...valid.components[0], component: "extra" }],
      }).success,
    ).toBe(false);
  });

  it("composes components once with fixed weights, quality, dispersion, and the five-day horizon", () => {
    const submission = macroSubmission("us_financial_conditions") as Extract<
      MacroAgentSubmission,
      { mode: "COMPONENTS" }
    >;
    submission.components = submission.components.map((component, index) => ({
      ...component,
      direction: index < 3 ? "ADVERSE" : "SUPPORTIVE",
      strength: index < 3 ? 4 : 2,
      confidence: 0.8,
    }));
    const accepted = composeAcceptedMacroTransmission("us_financial_conditions", submission, {
      mode: "COMPONENTS",
      dataQualityByComponent: Object.fromEntries(
        submission.components.map((component) => [component.component, 1]),
      ),
    });
    expect(accepted.agent_id).toBe("us_financial_conditions");
    expect(accepted.direction).toBe("ADVERSE");
    expect(accepted.strength).toBeGreaterThan(0);
    expect(accepted.evaluation_horizon_trading_days).toBe(5);
    expect(accepted.component_weight_contract_version).toBe("macro_component_weights_v2");
    expect(accepted.confidence).toBeLessThanOrEqual(accepted.model_confidence);
    expect(accepted).not.toHaveProperty("stance");
    expect(accepted).not.toHaveProperty("layer_1_consensus_score");

    const audit = buildMacroComponentCompositionAudit(
      "us_financial_conditions",
      submission,
      {
        mode: "COMPONENTS",
        dataQualityByComponent: Object.fromEntries(
          submission.components.map((component) => [component.component, 1]),
        ),
      },
      accepted,
      {
        sourceSnapshotHash: `sha256:${"1".repeat(64)}`,
        contextOnlyProjectionHash: `sha256:${"2".repeat(64)}`,
      },
    );
    expect(audit.components.map((component) => component.component)).toEqual(
      [...audit.components].map((component) => component.component).sort(),
    );
    expect(audit.composed_payload_hash).toMatch(/^sha256:[0-9a-f]{64}$/);
    expect(audit.source_snapshot_hash).toBe(`sha256:${"1".repeat(64)}`);
    expect(audit.context_only_projection_hash).toBe(`sha256:${"2".repeat(64)}`);
    expect(audit.component_composition_hash).toMatch(/^sha256:[0-9a-f]{64}$/);
  });

  it("uses the active calibrated component version and weights at the accepted boundary", () => {
    const submission = macroSubmission("us_economy") as Extract<
      MacroAgentSubmission,
      { mode: "COMPONENTS" }
    >;
    submission.components = submission.components.map((component) => ({
      ...component,
      direction: component.component === "growth_production" ? "SUPPORTIVE" : "ADVERSE",
      strength: component.component === "growth_production" ? 5 : 3,
      confidence: 1,
    }));
    const quality = {
      mode: "COMPONENTS" as const,
      dataQualityByComponent: Object.fromEntries(
        submission.components.map((component) => [component.component, 1]),
      ),
    };
    const fixed = composeAcceptedMacroTransmission("us_economy", submission, quality);
    const active: ComponentWeightRuntimeResolution = {
      agent_id: "us_economy",
      component_weight_contract_version: "us_economy_component_weights_test_v1",
      component_weights: {
        growth_production: 0.35,
        prices: 0.25,
        employment: 0.2,
        demand_trade: 0.2,
      },
      release_revision_id: "component-weight-release:test",
      release_revision_hash: `sha256:${"1".repeat(64)}`,
      effective_at: "2026-01-05T00:00:00+08:00",
    };
    const calibrated = composeAcceptedMacroTransmission(
      "us_economy",
      submission,
      quality,
      {
        agent_contract_version: "macro_agent_contract_v2",
        prompt_behavior_version: "macro_prompt_behavior_v2",
        execution_behavior_version: "macro_execution_behavior_v2",
        component_weight_contract_version: active.component_weight_contract_version,
      },
      active,
    );

    expect(calibrated.component_weight_contract_version).toBe(
      active.component_weight_contract_version,
    );
    expect(calibrated.direction).toBe("NEUTRAL");
    expect(fixed.direction).toBe("ADVERSE");
  });

  it("rejects malformed or cross-Agent calibrated component resolutions", () => {
    const submission = macroSubmission("us_economy");
    const quality = {
      mode: "COMPONENTS" as const,
      dataQualityByComponent: Object.fromEntries(
        submission.mode === "COMPONENTS"
          ? submission.components.map((component) => [component.component, 1])
          : [],
      ),
    };
    const behavior = {
      agent_contract_version: "macro_agent_contract_v2",
      prompt_behavior_version: "macro_prompt_behavior_v2",
      execution_behavior_version: "macro_execution_behavior_v2",
      component_weight_contract_version: "calibrated-v1",
    };
    const base = {
      agent_id: "central_bank",
      component_weight_contract_version: "calibrated-v1",
      component_weights: {
        growth_production: 0.35,
        prices: 0.25,
        employment: 0.2,
        demand_trade: 0.2,
      },
      release_revision_id: null,
      release_revision_hash: null,
      effective_at: null,
    } satisfies ComponentWeightRuntimeResolution;

    expect(() =>
      composeAcceptedMacroTransmission("us_economy", submission, quality, behavior, base),
    ).toThrow(/owner mismatch/);
    expect(() =>
      composeAcceptedMacroTransmission("us_economy", submission, quality, behavior, {
        ...base,
        agent_id: "us_economy",
        component_weights: {
          growth_production: 0.5,
          prices: 0.2,
          employment: 0.2,
          demand_trade: 0.2,
        },
      }),
    ).toThrow(/invalid active component weights/);
  });

  it("applies deterministic quality once for DIRECT roles", () => {
    const accepted = composeAcceptedMacroTransmission(
      "market_breadth",
      macroSubmission("market_breadth"),
      { mode: "DIRECT", dataQuality: 0.8 },
    );
    expect(accepted.model_confidence).toBe(0.7);
    expect(accepted.deterministic_data_quality).toBe(0.8);
    expect(accepted.confidence).toBeCloseTo(0.56);
    expect(accepted.component_weight_contract_version).toBeNull();
  });

  it("fails closed when any accepted slot is absent or a contract version is wrong", () => {
    const outputs = Object.fromEntries(
      MACRO_AGENT_IDS.map((agent) => [agent, macroOutput(agent)]),
    ) as Record<MacroAgentId, ReturnType<typeof macroOutput>>;
    const receipt = validateMacroInputs(outputs);
    expect(receipt.accepted_count).toBe(10);
    expect(receipt.accepted_agent_ids).toEqual(MACRO_AGENT_IDS);
    expect(receipt.input_hash).toMatch(/^sha256:[0-9a-f]{64}$/);
    expect(
      Object.values(receipt.reliability_by_agent).reduce((sum, row) => sum + row.usage_share, 0),
    ).toBeCloseTo(1);
    const incomplete = { ...outputs };
    delete (incomplete as Partial<typeof incomplete>).eu_economy;
    expect(() => validateMacroInputs(incomplete)).toThrow(/requires exactly/);
    const wrong = { ...outputs, china: { ...outputs.china, agent_contract_version: "old" } };
    expect(() => validateMacroInputs(wrong)).toThrow(/version mismatch/);
  });

  it("hashes exact namespace-safe record references at the production gate", () => {
    const outputs = Object.fromEntries(
      MACRO_AGENT_IDS.map((agent) => [agent, macroOutput(agent)]),
    ) as Record<MacroAgentId, ReturnType<typeof macroOutput>>;
    const refs = Object.fromEntries(
      MACRO_AGENT_IDS.map((agent) => [
        agent,
        {
          accepted_output_kind: "MACRO_TRANSMISSION",
          agent_id: agent,
          accepted_output_id: `accepted:${agent}`,
          accepted_output_hash: `sha256:${agent.padEnd(64, "0").slice(0, 64)}`,
        },
      ]),
    ) as Record<MacroAgentId, AcceptedOutputRecordRef<"MACRO_TRANSMISSION">>;
    const receipt = validateMacroInputs(outputs, undefined, undefined, refs);
    expect(receipt.accepted_count).toBe(10);
    const incompleteRefs = Object.fromEntries(
      Object.entries(refs).filter(([agent]) => agent !== "china"),
    );
    expect(() =>
      validateMacroInputs(outputs, undefined, undefined, incompleteRefs as never),
    ).toThrow(/exactly ten accepted Macro record references/);
    expect(() =>
      validateMacroInputs(outputs, undefined, undefined, {
        ...refs,
        china: { ...refs.china, agent_id: "us_economy" },
      } as never),
    ).toThrow(/owner mismatch/);
  });
});
