import { describe, expect, it } from "vitest";
import {
  applyResearchKnobCaps,
  buildResearchKnobsSnapshot,
  parseResearchKnobsPrompt,
  type ResearchKnobs,
} from "../src/agents/helpers/research_knobs.js";

function knobs(): ResearchKnobs {
  return {
    schema_version: "research_knobs_v1",
    layer: "macro",
    agent: "macro.central_bank",
    research_scope: {
      must_cover: ["liquidity_regime"],
      must_not_cover: ["final_portfolio_sizing"],
    },
    prediction_targets: [
      {
        id: "liquidity_regime_20d",
        target_variable: "liquidity_regime",
        horizon: "20d",
        allowed_outputs: ["positive", "neutral", "negative"],
      },
    ],
    evidence_registry: {
      pboc_liquidity: {
        tool: "get_pboc_ops",
        metric: "pboc_net_injection_7d",
        current_data: true,
        primary: true,
      },
    },
    evidence_weights: {
      pboc_liquidity: 1,
    },
    lookbacks: {
      net_injection_window_days: 7,
    },
    thresholds: {},
    confidence_caps: {
      missing_current_data: {
        cap: 0.55,
        trigger: "missing_required_evidence",
        enforcement: "code",
        required_evidence: ["pboc_liquidity"],
      },
      fallback_primary_tool: {
        cap: 0.6,
        trigger: "primary_tool_failed_or_fallback",
        enforcement: "code",
        required_evidence: ["pboc_liquidity"],
      },
    },
    tie_breaks: [],
    mutation_targets: [
      {
        path: "/rule_packs/macro.central_bank.liquidity.v1/rules/macro.central_bank.soft.001/learnable_parameters/pboc_liquidity_weight/value",
        type: "number",
        min: 0,
        max: 1,
      },
    ],
  };
}

describe("research knob cap enforcement", () => {
  it("rejects extra fields in the prompt projection schema", () => {
    const text = `\`\`\`research-knobs
research-knobs:
  schema_version: research_knobs_v1
  layer: macro
  agent: macro.central_bank
  unexpected_field: should_fail
  research_scope:
    must_cover: [liquidity_regime]
    must_not_cover: [final_portfolio_sizing]
  prediction_targets:
    - id: liquidity_regime_20d
      target_variable: liquidity_regime
      horizon: 20d
      allowed_outputs: [positive, neutral, negative]
  evidence_registry:
    pboc_liquidity:
      tool: get_pboc_ops
      metric: pboc_net_injection_7d
      current_data: true
      primary: true
  evidence_weights:
    pboc_liquidity: 1.0
  lookbacks: {}
  thresholds: {}
  confidence_caps:
    missing_current_data:
      cap: 0.55
      trigger: missing_required_evidence
      enforcement: code
      required_evidence: [pboc_liquidity]
  tie_breaks: []
  mutation_targets:
    - path: /rule_packs/macro.central_bank.liquidity.v1/rules/macro.central_bank.soft.001/learnable_parameters/pboc_liquidity_weight/value
      type: number
      min: 0
      max: 1
\`\`\``;

    expect(() => parseResearchKnobsPrompt(text)).toThrow(/unrecognized key/i);
  });

  it("clamps top-level and nested confidence when required current data is missing", () => {
    const snapshot = buildResearchKnobsSnapshot({
      agent: "central_bank",
      cohort: "cohort_default",
      knobs: knobs(),
    });

    const result = applyResearchKnobCaps(
      {
        confidence: 0.82,
        evidence_ledger: [{ claim: "liquidity supportive", confidence_impact: 0.7 }],
      },
      snapshot,
      {
        toolStatuses: [],
      },
    );

    expect(result.output.confidence).toBe(0.55);
    expect(result.output.evidence_ledger[0]?.confidence_impact).toBe(0.55);
    expect(result.audit.pre_cap_confidence).toBe(0.82);
    expect(result.audit.post_cap_confidence).toBe(0.55);
    expect(result.audit.fired_cap_ids).toContain("missing_current_data");
    expect(result.audit.knob_snapshot_hash).toMatch(/^sha256:/);
  });

  it("uses the strictest cap when multiple policies fire", () => {
    const snapshot = buildResearchKnobsSnapshot({
      agent: "central_bank",
      cohort: "cohort_default",
      knobs: knobs(),
    });

    const result = applyResearchKnobCaps({ confidence: 0.9 }, snapshot, {
      toolStatuses: [
        {
          name: "get_pboc_ops",
          called: true,
          failed: false,
          missing: false,
          fallback: true,
          cache_hit: false,
        },
      ],
    });

    expect(result.output.confidence).toBe(0.55);
    expect(result.audit.fired_cap_ids).toEqual(["missing_current_data", "fallback_primary_tool"]);
  });
});
