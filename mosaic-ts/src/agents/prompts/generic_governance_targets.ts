import type { RuntimeAgentSpec } from "./runtime_agent_spec.js";

export interface GenericGovernanceTargetDefinition {
  path: string;
  target: {
    path: string;
    type: "number";
    min: number;
    max: number;
    step: number;
  };
  defaultValue: number;
  evidenceKey?: string;
  confidenceCapId?: string;
  weightGroup?: "evidence_weights";
}

export function genericGovernanceTargetDefinitions(
  spec: RuntimeAgentSpec,
): GenericGovernanceTargetDefinition[] {
  const rulePackId = `${spec.layer}.${spec.agent}.runtime.v1`;
  const ruleId = canonicalRuntimeRuleId(spec);
  const nonRkeTools = spec.requiredTools.filter((tool) => tool !== "get_rke_research_context");
  const evidenceKeys =
    nonRkeTools.length > 0
      ? nonRkeTools.map((tool) => evidenceKeyForTool(tool))
      : ["upstream_context"];
  const unitWeight = 1 / evidenceKeys.length;
  const definitions: GenericGovernanceTargetDefinition[] = evidenceKeys.map((evidenceKey) => {
    const path = `/rule_packs/${rulePackId}/rules/${ruleId}/learnable_parameters/${evidenceKey}_weight/value`;
    return {
      path,
      target: { path, type: "number", min: 0, max: 1, step: 0.05 },
      defaultValue: unitWeight,
      evidenceKey,
      weightGroup: "evidence_weights",
    };
  });
  for (const [confidenceCapId, defaultValue] of [
    ["missing_current_data", 0.55],
    ["fallback_primary_tool", 0.6],
  ] as const) {
    const path = `/rule_packs/${rulePackId}/rules/${ruleId}/confidence_policy/${confidenceCapId}/cap`;
    definitions.push({
      path,
      target: { path, type: "number", min: 0.25, max: 0.75, step: 0.05 },
      defaultValue,
      confidenceCapId,
    });
  }
  return definitions;
}

export function evidenceKeyForTool(tool: string): string {
  return tool
    .replace(/^get_/, "")
    .replace(/[^a-zA-Z0-9]+/g, "_")
    .replace(/_+$/g, "");
}

function canonicalRuntimeRuleId(spec: RuntimeAgentSpec): string {
  const kind = spec.layer === "decision" ? (spec.agent === "cro" ? "risk" : "policy") : "soft";
  return `${spec.layer}.${spec.agent}.${kind}.001`;
}
