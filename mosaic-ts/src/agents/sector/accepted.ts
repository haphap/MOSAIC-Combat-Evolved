import { createHash } from "node:crypto";
import type { DarwinianAgentBehaviorBinding } from "../../autoresearch/production_variant.js";
import type {
  AcceptedMacroInputAttribution,
  MacroAttributionTarget,
} from "../helpers/macro_attribution.js";
import type {
  SectorAgentOutputBase,
  SectorSecurityPickSubmission,
  StandardSectorAgentId,
} from "../types.js";
import { SECTOR_CONTRACT_VERSION } from "./_contracts.js";
import { SECTOR_DIRECTION_REGISTRY_HASH, SECTOR_DIRECTION_REGISTRY_VERSION } from "./registry.js";
import { directionComparisonAuditHash } from "./selection.js";

export type AcceptedSectorSelectionPayload =
  | {
      selection_status: "SELECTED";
      preferred_direction: Extract<
        SectorAgentOutputBase["preferred_direction"],
        { selection_role: "PREFERRED" }
      >;
      least_preferred_direction: SectorAgentOutputBase["least_preferred_direction"];
      persistence_horizon: SectorAgentOutputBase["persistence_horizon"];
      key_drivers: SectorAgentOutputBase["key_drivers"];
      risks: SectorAgentOutputBase["risks"];
      claims: SectorAgentOutputBase["claims"];
      claim_refs: string[];
      preferred_security_status: "PICKS_PRESENT" | "NO_QUALIFIED_SECURITY";
      long_picks: SectorSecurityPickSubmission[];
      least_preferred_security_status: "PICKS_PRESENT" | "NO_QUALIFIED_SECURITY" | "NOT_APPLICABLE";
      short_or_avoid_picks: SectorSecurityPickSubmission[];
    }
  | {
      selection_status: "NO_QUALIFIED_DIRECTION";
      preferred_direction: { status: "NO_QUALIFIED_DIRECTION" };
      least_preferred_direction: Extract<
        SectorAgentOutputBase["least_preferred_direction"],
        { status: "NO_QUALIFIED_AVOID_DIRECTION" }
      >;
      persistence_horizon: SectorAgentOutputBase["persistence_horizon"];
      key_drivers: SectorAgentOutputBase["key_drivers"];
      risks: SectorAgentOutputBase["risks"];
      claims: SectorAgentOutputBase["claims"];
      claim_refs: string[];
      preferred_security_status: "NO_QUALIFIED_SECURITY";
      long_picks: [];
      least_preferred_security_status: "NOT_APPLICABLE";
      short_or_avoid_picks: [];
    };

export interface AcceptedSectorSelection {
  sector_agent_id: StandardSectorAgentId;
  agent_contract_version: string;
  prompt_behavior_version: string;
  execution_behavior_version: string;
  sector_direction_registry_version: typeof SECTOR_DIRECTION_REGISTRY_VERSION;
  sector_direction_registry_hash: string;
  selection: AcceptedSectorSelectionPayload;
  accepted_macro_input_attributions: AcceptedMacroInputAttribution[];
  direction_comparison_audit_id: string;
  direction_comparison_audit_hash: string;
  least_preferred_eligibility_audit_id: string;
  least_preferred_eligibility_audit_hash: string;
  single_direction_qualification_audit_id: string | null;
  single_direction_qualification_audit_hash: string | null;
  preferred_security_shortlist_id: string | null;
  preferred_security_shortlist_hash: string | null;
  least_preferred_security_shortlist_id: string | null;
  least_preferred_security_shortlist_hash: string | null;
  security_scoring_contract_version: string;
  security_scoring_contract_hash: string;
  inference_cost_audit_id: string;
  inference_cost_audit_hash: string;
  preferred_security_abstention_confidence: number | null;
  least_preferred_security_abstention_confidence: number | null;
  model_confidence: number;
  directional_confidence: number;
  abstention_confidence: number;
}

export interface ModelVisibleAcceptedSectorSelection {
  sector_agent_id: StandardSectorAgentId;
  selection: AcceptedSectorSelectionPayload;
  directional_confidence: number;
  abstention_confidence: number;
}

export interface AcceptedSectorAuditBindings {
  directionComparisonAudit: unknown;
  leastPreferredEligibilityAudit: unknown;
  singleDirectionQualificationAudit: unknown | null;
  inferenceCostAudit: unknown;
}

export function acceptedSectorSelectionPayload(
  output: SectorAgentOutputBase,
): AcceptedSectorSelectionPayload {
  const common = {
    persistence_horizon: output.persistence_horizon,
    key_drivers: output.key_drivers,
    risks: output.risks,
    claims: output.claims,
    claim_refs: output.claim_refs,
  };
  if (output.selection_status === "NO_QUALIFIED_DIRECTION") {
    if (
      "selection_role" in output.preferred_direction ||
      "selection_role" in output.least_preferred_direction ||
      output.long_picks.length !== 0 ||
      output.short_or_avoid_picks.length !== 0
    ) {
      throw new Error(`${output.agent}: invalid accepted abstention payload`);
    }
    return {
      selection_status: output.selection_status,
      preferred_direction: output.preferred_direction,
      least_preferred_direction: output.least_preferred_direction,
      ...common,
      preferred_security_status: "NO_QUALIFIED_SECURITY",
      long_picks: [],
      least_preferred_security_status: "NOT_APPLICABLE",
      short_or_avoid_picks: [],
    };
  }
  if (!("selection_role" in output.preferred_direction)) {
    throw new Error(`${output.agent}: selected payload has no preferred direction`);
  }
  return {
    selection_status: output.selection_status,
    preferred_direction: output.preferred_direction,
    least_preferred_direction: output.least_preferred_direction,
    ...common,
    preferred_security_status: output.preferred_security_status,
    long_picks: output.long_picks,
    least_preferred_security_status: output.least_preferred_security_status,
    short_or_avoid_picks: output.short_or_avoid_picks,
  };
}

export function sectorMacroAttributionTargets(
  output: SectorAgentOutputBase,
): MacroAttributionTarget[] {
  if (
    output.selection_status !== "SELECTED" ||
    !("direction_local_id" in output.preferred_direction)
  ) {
    return [];
  }
  const targets: MacroAttributionTarget[] = [
    {
      target_type: "SECTOR_THESIS",
      target_local_ref: output.preferred_direction.direction_local_id,
      target: output.preferred_direction,
    },
  ];
  if ("direction_local_id" in output.least_preferred_direction) {
    targets.push({
      target_type: "SECTOR_THESIS",
      target_local_ref: output.least_preferred_direction.direction_local_id,
      target: output.least_preferred_direction,
    });
  }
  for (const pick of [...output.long_picks, ...output.short_or_avoid_picks]) {
    targets.push({
      target_type: "SECURITY_PICK",
      target_local_ref: pick.pick_local_id,
      target: pick,
    });
  }
  return targets;
}

export function buildAcceptedSectorSelection(input: {
  output: SectorAgentOutputBase;
  behavior?: DarwinianAgentBehaviorBinding;
  acceptedMacroInputAttributions: AcceptedMacroInputAttribution[];
  auditBindings: AcceptedSectorAuditBindings;
}): AcceptedSectorSelection {
  const runtime = input.output.sector_runtime_binding;
  if (!runtime) throw new Error(`${input.output.agent}: sector runtime binding is unavailable`);
  const behavior = input.behavior ?? {
    agent_contract_version: SECTOR_CONTRACT_VERSION,
    prompt_behavior_version: "sector_prompt_behavior_v2",
    execution_behavior_version: "sector_execution_behavior_v2",
  };
  const directionComparisonHash = directionComparisonAuditHash(
    input.auditBindings.directionComparisonAudit,
  );
  const directionComparison = {
    id: `sector-direction-comparison:${directionComparisonHash.slice("sha256:".length)}`,
    hash: directionComparisonHash,
  };
  if (runtime.direction_comparison_audit_hash !== directionComparison.hash) {
    throw new Error(`${input.output.agent}: direction comparison audit hash mismatch`);
  }
  const leastEligibility = auditRef(
    "least-preferred-eligibility",
    input.auditBindings.leastPreferredEligibilityAudit,
  );
  const singleQualification = input.auditBindings.singleDirectionQualificationAudit
    ? auditRef(
        "single-direction-qualification",
        input.auditBindings.singleDirectionQualificationAudit,
      )
    : null;
  const inferenceCost = auditRef("sector-inference-cost", input.auditBindings.inferenceCostAudit);
  const selected = input.output.selection_status === "SELECTED";
  return {
    sector_agent_id: input.output.agent,
    agent_contract_version: behavior.agent_contract_version,
    prompt_behavior_version: behavior.prompt_behavior_version,
    execution_behavior_version: behavior.execution_behavior_version,
    sector_direction_registry_version: SECTOR_DIRECTION_REGISTRY_VERSION,
    sector_direction_registry_hash: SECTOR_DIRECTION_REGISTRY_HASH,
    selection: acceptedSectorSelectionPayload(input.output),
    accepted_macro_input_attributions: input.acceptedMacroInputAttributions,
    direction_comparison_audit_id: directionComparison.id,
    direction_comparison_audit_hash: directionComparison.hash,
    least_preferred_eligibility_audit_id: leastEligibility.id,
    least_preferred_eligibility_audit_hash: leastEligibility.hash,
    single_direction_qualification_audit_id: singleQualification?.id ?? null,
    single_direction_qualification_audit_hash: singleQualification?.hash ?? null,
    preferred_security_shortlist_id: runtime.preferred_security_shortlist_id,
    preferred_security_shortlist_hash: runtime.preferred_security_shortlist_hash,
    least_preferred_security_shortlist_id: runtime.least_preferred_security_shortlist_id,
    least_preferred_security_shortlist_hash: runtime.least_preferred_security_shortlist_hash,
    security_scoring_contract_version: runtime.security_scoring_contract_version,
    security_scoring_contract_hash: runtime.security_scoring_contract_hash,
    inference_cost_audit_id: inferenceCost.id,
    inference_cost_audit_hash: inferenceCost.hash,
    preferred_security_abstention_confidence: input.output.preferred_security_abstention_confidence,
    least_preferred_security_abstention_confidence:
      input.output.least_preferred_security_abstention_confidence,
    model_confidence: input.output.confidence,
    directional_confidence: selected ? input.output.confidence : 0,
    abstention_confidence: selected ? 0 : input.output.confidence,
  };
}

export function modelVisibleAcceptedSectorSelection(
  accepted: AcceptedSectorSelection,
): ModelVisibleAcceptedSectorSelection {
  return {
    sector_agent_id: accepted.sector_agent_id,
    selection: accepted.selection,
    directional_confidence: accepted.directional_confidence,
    abstention_confidence: accepted.abstention_confidence,
  };
}

function auditRef(namespace: string, value: unknown): { id: string; hash: string } {
  const hash = canonicalHash(value);
  return { id: `${namespace}:${hash.slice("sha256:".length)}`, hash };
}

function canonicalHash(value: unknown): string {
  return `sha256:${createHash("sha256")
    .update(JSON.stringify(canonicalize(value)))
    .digest("hex")}`;
}

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, canonicalize(item)]),
    );
  }
  return value;
}
