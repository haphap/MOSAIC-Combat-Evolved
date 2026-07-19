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

export interface AcceptedSectorSelectionPayload {
  selection_status: "SELECTED";
  preferred_direction: SectorAgentOutputBase["preferred_direction"];
  least_preferred_direction: SectorAgentOutputBase["least_preferred_direction"];
  persistence_horizon: SectorAgentOutputBase["persistence_horizon"];
  key_drivers: SectorAgentOutputBase["key_drivers"];
  risks: SectorAgentOutputBase["risks"];
  claims: SectorAgentOutputBase["claims"];
  claim_refs: string[];
  preferred_security_status: "PICKS_PRESENT" | "NO_QUALIFIED_SECURITY";
  long_picks: SectorSecurityPickSubmission[];
  least_preferred_security_status: "PICKS_PRESENT" | "NO_QUALIFIED_SECURITY";
  short_or_avoid_picks: SectorSecurityPickSubmission[];
}

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
  preferred_security_shortlist_id: string;
  preferred_security_shortlist_hash: string;
  least_preferred_security_shortlist_id: string;
  least_preferred_security_shortlist_hash: string;
  security_scoring_contract_version: string;
  security_scoring_contract_hash: string;
  inference_cost_audit_id: string;
  inference_cost_audit_hash: string;
  preferred_security_abstention_confidence: number | null;
  least_preferred_security_abstention_confidence: number | null;
  model_confidence: number;
  directional_confidence: number;
}

export interface ModelVisibleAcceptedSectorSelection {
  sector_agent_id: StandardSectorAgentId;
  selection: AcceptedSectorSelectionPayload;
  directional_confidence: number;
}

export interface AcceptedSectorAuditBindings {
  directionComparisonAudit: unknown;
  inferenceCostAudit: unknown;
}

export function acceptedSectorSelectionPayload(
  output: SectorAgentOutputBase,
): AcceptedSectorSelectionPayload {
  if ((output as { selection_status?: unknown }).selection_status !== "SELECTED") {
    throw new Error(`${output.agent}: unqualified direction stages cannot produce accepted output`);
  }
  if (
    !("selection_role" in output.preferred_direction) ||
    !("selection_role" in output.least_preferred_direction)
  ) {
    throw new Error(`${output.agent}: accepted output requires both direction legs`);
  }
  const common = {
    persistence_horizon: output.persistence_horizon,
    key_drivers: output.key_drivers,
    risks: output.risks,
    claims: output.claims,
    claim_refs: output.claim_refs,
  };
  if (output.preferred_direction.direction_id === output.least_preferred_direction.direction_id) {
    throw new Error(`${output.agent}: preferred and least-preferred directions must differ`);
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
    prompt_behavior_version: "sector_prompt_behavior_v3",
    execution_behavior_version: "sector_execution_behavior_v3",
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
  assertInferenceCostAudit(input.auditBindings.inferenceCostAudit, input.output);
  const inferenceCost = auditRef("sector-inference-cost", input.auditBindings.inferenceCostAudit);
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
    directional_confidence: input.output.confidence,
  };
}

export function modelVisibleAcceptedSectorSelection(
  accepted: AcceptedSectorSelection,
): ModelVisibleAcceptedSectorSelection {
  return {
    sector_agent_id: accepted.sector_agent_id,
    selection: accepted.selection,
    directional_confidence: accepted.directional_confidence,
  };
}

function auditRef(namespace: string, value: unknown): { id: string; hash: string } {
  const hash = canonicalHash(value);
  return { id: `${namespace}:${hash.slice("sha256:".length)}`, hash };
}

function assertInferenceCostAudit(value: unknown, output: SectorAgentOutputBase): void {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${output.agent}: inference cost audit must be an object`);
  }
  const audit = value as Record<string, unknown>;
  const summary = audit.usage_summary_receipt;
  if (!summary || typeof summary !== "object" || Array.isArray(summary)) {
    throw new Error(`${output.agent}: signed runtime usage summary is required`);
  }
  const receipt = summary as Record<string, unknown>;
  const receiptBody = Object.fromEntries(
    Object.entries(receipt).filter(
      ([key]) => key !== "usage_summary_receipt_hash" && key !== "receipt_signature",
    ),
  );
  const receiptHash = canonicalHash(receiptBody);
  if (
    audit.schema_version !== "sector_runtime_inference_cost_audit_v3" ||
    audit.evidence_source !== "SIGNED_SERVER_MODEL_USAGE_SUMMARY" ||
    receipt.schema_version !== "sector_model_usage_summary_receipt_v1" ||
    receipt.agent_id !== output.agent ||
    receipt.snapshot_bundle_hash !== output.sector_runtime_binding?.snapshot_bundle_hash ||
    receipt.direction_comparison_audit_hash !==
      output.sector_runtime_binding?.direction_comparison_audit_hash ||
    receipt.usage_summary_receipt_hash !== receiptHash ||
    typeof receipt.receipt_signature !== "string" ||
    receipt.receipt_signature.length === 0 ||
    audit.usage_summary_receipt_id !== receipt.usage_summary_receipt_id ||
    audit.usage_summary_receipt_hash !== receiptHash
  ) {
    throw new Error(`${output.agent}: signed inference usage summary binding mismatch`);
  }
  if (
    !Number.isSafeInteger(receipt.model_subcall_count) ||
    (receipt.model_subcall_count as number) < 2 ||
    !Number.isSafeInteger(receipt.input_tokens) ||
    !Number.isSafeInteger(receipt.output_tokens) ||
    (receipt.input_tokens as number) < 0 ||
    (receipt.output_tokens as number) < 0 ||
    receipt.model_path_disposition !== "COMPLETED" ||
    receipt.last_attempted_stage !== "COMPLETED" ||
    audit.model_subcall_count !== receipt.model_subcall_count ||
    audit.conflict_review_triggered !== receipt.conflict_review_triggered ||
    audit.input_tokens !== receipt.input_tokens ||
    audit.output_tokens !== receipt.output_tokens ||
    audit.last_attempted_stage !== "COMPLETED" ||
    audit.disposition !== "SUCCESS" ||
    "normalized_inference_cost" in audit ||
    "budget_compliant" in audit ||
    "accepted_output_id" in receipt ||
    "accepted_output_hash" in receipt
  ) {
    throw new Error(`${output.agent}: inference cost audit totals or disposition mismatch`);
  }
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
