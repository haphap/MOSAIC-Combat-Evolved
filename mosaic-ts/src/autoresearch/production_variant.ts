import { createHash } from "node:crypto";
import {
  MACRO_AGENT_CONTRACT_VERSION,
  MACRO_COMPONENT_WEIGHT_CONTRACT_VERSION,
  MACRO_ROLE_CONTRACTS,
} from "../agents/macro/_contracts.js";
import { RUNTIME_AGENT_SPECS } from "../agents/prompts/runtime_agent_spec.js";
import type { MosaicConfig, PromptPreflightResult } from "../bridge/types.js";
import type { LlmHandle } from "../llm/factory.js";
import {
  type ExecutionBehaviorReleaseManifest,
  releaseVariantFor,
} from "./execution_behavior_release.js";
import { OUTCOME_LABEL_REGISTRY } from "./outcome_registry.js";

export interface DarwinianAgentBehaviorBinding {
  agent_contract_version: string;
  prompt_behavior_version: string;
  execution_behavior_version: string;
  component_weight_contract_version: string | null;
  reliability_adapter_contract_version: string | null;
  confidence_semantics_contract_version: string | null;
}

export interface DarwinianRuntimeBinding {
  schema_version: "darwinian_runtime_binding_v2";
  production_variant_roster_id: string;
  cohort_id: string;
  language: "en" | "zh";
  execution_behavior_release_id: string;
  prompt_repo_id: string;
  prompt_repo_revision: string;
  effective_at: string;
  agent_behavior_bindings: Record<string, DarwinianAgentBehaviorBinding>;
  binding_hash: string;
}

export interface DarwinianUsageWeightRow {
  agent_id: string;
  usage_track_key_hash: string;
  weight_record_id: string;
  weight_record_hash: string;
  record_kind: "COLD_START_INITIALIZATION" | "MATURE_UPDATE";
  darwin_weight: number;
  previous_weight_record_id: string | null;
  n_eligible_scores: number;
  scoring_window_hash: string;
  update_event_id: string | null;
  effective_at: string;
  reliability_record_id: string;
  reliability_record_hash: string;
  operational_reliability: number;
  operational_reliability_if_accepted: number;
  reliability_state: "COLD_START" | "OBSERVED";
  accountable_count: number;
  accepted_count: number;
}

export interface DarwinianUsageWeightSnapshot {
  darwinian_snapshot_id: string;
  darwinian_snapshot_hash: string;
  schema_version: "darwinian_usage_weight_snapshot_v2";
  production_variant_roster_id: string;
  production_variant_roster_revision_id: string;
  execution_behavior_release_id: string;
  cohort_id: string;
  language: "en" | "zh";
  as_of: string;
  weights: DarwinianUsageWeightRow[];
}

export interface ComponentWeightRuntimeResolution {
  agent_id: string;
  component_weight_contract_version: string;
  component_weights: Record<string, number>;
  release_revision_id: string | null;
  release_revision_hash: string | null;
  effective_at: string | null;
}

export interface ComponentWeightRuntimeSnapshot {
  component_weight_snapshot_id: string;
  component_weight_snapshot_hash: string;
  schema_version: "component_weight_runtime_snapshot_v2";
  as_of: string;
  resolutions: ComponentWeightRuntimeResolution[];
}

export function validateComponentWeightRuntimeSnapshot(
  snapshot: ComponentWeightRuntimeSnapshot,
  binding: DarwinianRuntimeBinding,
  asOf: string,
): ComponentWeightRuntimeSnapshot {
  if (snapshot.schema_version !== "component_weight_runtime_snapshot_v2") {
    throw new Error("component weight runtime snapshot version mismatch");
  }
  if (snapshot.as_of !== asOf) {
    throw new Error("component weight runtime snapshot as_of mismatch");
  }
  const componentAgents = Object.entries(MACRO_ROLE_CONTRACTS)
    .filter(([, contract]) => contract.mode === "COMPONENTS")
    .map(([agent]) => agent)
    .sort();
  const sorted = [...snapshot.resolutions].sort((left, right) =>
    left.agent_id.localeCompare(right.agent_id),
  );
  if (
    sorted.length !== componentAgents.length ||
    sorted.map((resolution) => resolution.agent_id).join("\0") !== componentAgents.join("\0")
  ) {
    throw new Error("component weight runtime snapshot must cover exactly seven Macro Agents");
  }
  for (const resolution of sorted) {
    const contract = MACRO_ROLE_CONTRACTS[resolution.agent_id as keyof typeof MACRO_ROLE_CONTRACTS];
    const behavior = binding.agent_behavior_bindings[resolution.agent_id];
    if (contract?.mode !== "COMPONENTS" || !behavior) {
      throw new Error(`unknown component weight runtime owner: ${resolution.agent_id}`);
    }
    if (
      behavior.component_weight_contract_version !== resolution.component_weight_contract_version
    ) {
      throw new Error(`${resolution.agent_id}: component version/binding mismatch`);
    }
    const componentIds = Object.keys(resolution.component_weights).sort();
    if (componentIds.join("\0") !== Object.keys(contract.components).sort().join("\0")) {
      throw new Error(`${resolution.agent_id}: component set mismatch`);
    }
    const values = Object.values(resolution.component_weights);
    if (
      values.some((weight) => !Number.isFinite(weight) || weight < 0.15 || weight > 0.35) ||
      Math.abs(values.reduce((sum, weight) => sum + weight, 0) - 1) > 1e-12
    ) {
      throw new Error(`${resolution.agent_id}: component weights violate calibration bounds`);
    }
    const hasReleaseId = resolution.release_revision_id !== null;
    if (
      hasReleaseId !== (resolution.release_revision_hash !== null) ||
      hasReleaseId !== (resolution.effective_at !== null) ||
      (resolution.release_revision_hash !== null &&
        !/^sha256:[0-9a-f]{64}$/.test(resolution.release_revision_hash))
    ) {
      throw new Error(`${resolution.agent_id}: incomplete component release provenance`);
    }
  }
  const withoutIdentity = {
    schema_version: snapshot.schema_version,
    as_of: snapshot.as_of,
    resolutions: snapshot.resolutions,
  };
  if (
    snapshot.component_weight_snapshot_id !==
    deterministicId("component-weight-runtime-snapshot", withoutIdentity)
  ) {
    throw new Error("component weight runtime snapshot ID mismatch");
  }
  const withIdentity = {
    component_weight_snapshot_id: snapshot.component_weight_snapshot_id,
    ...withoutIdentity,
  };
  if (snapshot.component_weight_snapshot_hash !== canonicalHash(withIdentity)) {
    throw new Error("component weight runtime snapshot hash mismatch");
  }
  return snapshot;
}

export function resolveProductionLanguage(config: MosaicConfig): "en" | "zh" {
  const raw = (config.output_language ?? "Chinese").toString().toLowerCase().trim();
  if (raw === "english" || raw === "en") return "en";
  if (raw === "bilingual") {
    throw new Error("Darwinian v2 production variants require one explicit language: en or zh");
  }
  return "zh";
}

export function buildDarwinianRuntimeBinding(input: {
  cohortId: string;
  config: MosaicConfig;
  llmHandle: Pick<LlmHandle, "provider" | "model" | "baseUrl">;
  promptPreflight: PromptPreflightResult;
  executionBehaviorRelease: ExecutionBehaviorReleaseManifest;
  effectiveAt: string;
}): DarwinianRuntimeBinding {
  const language = resolveProductionLanguage(input.config);
  const cohortId = requiredText(input.cohortId, "cohortId");
  const promptRepoId = requiredText(
    input.promptPreflight.source_status.prompt_repo_id,
    "prompt_repo_id",
  );
  const promptRepoRevision = requiredText(
    input.promptPreflight.source_status.prompt_repo_revision,
    "prompt_repo_revision",
  );
  if (!input.promptPreflight.ready || input.promptPreflight.cohort !== cohortId) {
    throw new Error("Darwinian runtime binding requires a READY matching prompt preflight");
  }
  const release = input.executionBehaviorRelease;
  if (release.private_prompt_commit !== promptRepoRevision) {
    throw new Error(
      "prompt repository revision does not match the pinned execution behavior release",
    );
  }
  if (
    release.provider_binding.provider !== input.llmHandle.provider ||
    release.provider_binding.model !== input.llmHandle.model
  ) {
    throw new Error("LLM provider/model does not match the pinned execution behavior release");
  }
  const configuredBaseUrl = input.llmHandle.baseUrl?.trim() || undefined;
  if (
    (release.provider_binding.base_url_mode === "PROVIDER_DEFAULT" && configuredBaseUrl) ||
    (release.provider_binding.base_url_mode === "CONFIGURED_PRIVATE_ENDPOINT" && !configuredBaseUrl)
  ) {
    throw new Error("LLM base URL mode does not match the pinned execution behavior release");
  }
  const productionVariant = release.active_production_variants.find(
    (row) => row.cohort_id === cohortId && row.language === language,
  );
  if (!productionVariant) {
    throw new Error(`execution behavior release does not activate ${cohortId}:${language}`);
  }
  const selectedRows = input.promptPreflight.rows.filter((row) => row.lang === language);
  const promptShaByAgent = new Map(
    selectedRows.map((row) => {
      if (row.status !== "ready" || row.fallback_used || !row.prompt_sha256) {
        throw new Error(`prompt provenance is not production-ready for ${row.agent}:${language}`);
      }
      return [row.agent, requiredSha256(row.prompt_sha256, `${row.agent}.prompt_sha256`)] as const;
    }),
  );
  const expectedAgents = Object.keys(OUTCOME_LABEL_REGISTRY).sort();
  if (
    promptShaByAgent.size !== 28 ||
    expectedAgents.some((agent) => !promptShaByAgent.has(agent))
  ) {
    throw new Error("prompt preflight must provide the selected language for all 28 Agents");
  }

  const runtimeSpecByAgent = new Map(RUNTIME_AGENT_SPECS.map((spec) => [spec.agent, spec]));
  const bindings: Record<string, DarwinianAgentBehaviorBinding> = {};
  for (const agentId of expectedAgents) {
    const outcome = OUTCOME_LABEL_REGISTRY[agentId];
    const spec = runtimeSpecByAgent.get(agentId);
    if (!outcome || !spec) throw new Error(`missing runtime/outcome contract for ${agentId}`);
    const promptSha = promptShaByAgent.get(agentId);
    if (!promptSha) throw new Error(`missing prompt SHA for ${agentId}:${language}`);
    const releaseVariant = releaseVariantFor(release, cohortId, language, agentId);
    if (releaseVariant.prompt_content_hash !== promptSha) {
      throw new Error(`prompt content does not match release for ${agentId}:${language}`);
    }
    const dimensions = outcome.track_contract_dimensions;
    const agentContractVersion =
      spec.layer === "macro"
        ? MACRO_AGENT_CONTRACT_VERSION
        : versionHash("agent-contract", {
            agent_id: agentId,
            accepted_output_kind: outcome.accepted_output_kind,
            evaluation_object_schema_version: outcome.evaluation_object_schema_version,
            output_schema_fields: [...spec.fieldNames],
            stages: spec.stages.map((stage) => ({
              stage: stage.stage,
              output_schema_ref: stage.outputSchemaRef,
              output_schema_fields: [...stage.outputSchemaFields],
            })),
          });
    const componentVersion =
      dimensions.component_weight_contract === "REQUIRED"
        ? spec.layer === "macro" &&
          MACRO_ROLE_CONTRACTS[agentId as keyof typeof MACRO_ROLE_CONTRACTS]
          ? MACRO_COMPONENT_WEIGHT_CONTRACT_VERSION
          : null
        : null;
    if (dimensions.component_weight_contract === "REQUIRED" && componentVersion === null) {
      throw new Error(`required component contract is unavailable for ${agentId}`);
    }
    const reliabilityVersion =
      dimensions.reliability_adapter_contract === "REQUIRED"
        ? versionHash("reliability-adapter", {
            agent_id: agentId,
            accepted_output_kind: outcome.accepted_output_kind,
            confidence_source:
              agentId === "relationship_mapper"
                ? "MATERIALITY_WEIGHTED_PREDICTIVE_EDGES"
                : spec.layer === "sector"
                  ? "CALIBRATED_SECTOR_OUTPUT_UTILITY"
                  : "CALIBRATED_OUTPUT_LEVEL",
          })
        : null;
    const confidenceVersion =
      dimensions.confidence_semantics_contract === "REQUIRED"
        ? versionHash("confidence-semantics", {
            agent_id: agentId,
            accepted_output_kind: outcome.accepted_output_kind,
            directional_and_abstention_are_distinct: true,
          })
        : null;
    bindings[agentId] = {
      agent_contract_version: agentContractVersion,
      prompt_behavior_version: releaseVariant.prompt_behavior_version,
      execution_behavior_version: releaseVariant.execution_behavior_version,
      component_weight_contract_version: componentVersion,
      reliability_adapter_contract_version: reliabilityVersion,
      confidence_semantics_contract_version: confidenceVersion,
    };
  }

  const productionVariantRosterId = productionVariant.production_variant_roster_id;
  const releaseId = release.execution_behavior_release_id;
  const withoutHash = {
    schema_version: "darwinian_runtime_binding_v2" as const,
    production_variant_roster_id: productionVariantRosterId,
    cohort_id: cohortId,
    language,
    execution_behavior_release_id: releaseId,
    prompt_repo_id: promptRepoId,
    prompt_repo_revision: promptRepoRevision,
    effective_at: requiredText(input.effectiveAt, "effectiveAt"),
    agent_behavior_bindings: bindings,
  };
  return { ...withoutHash, binding_hash: canonicalHash(withoutHash) };
}

function requiredText(value: unknown, label: string): string {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${label} must be non-empty`);
  return value.trim();
}

function requiredSha256(value: string, label: string): string {
  const normalized = value.startsWith("sha256:") ? value : `sha256:${value}`;
  if (!/^sha256:[0-9a-f]{64}$/.test(normalized)) throw new Error(`${label} must be sha256`);
  return normalized;
}

function versionHash(namespace: string, value: unknown): string {
  return `${namespace}:${canonicalHash(value).slice("sha256:".length)}`;
}

function deterministicId(namespace: string, value: unknown): string {
  return `${namespace}:${canonicalHash(value).slice("sha256:".length)}`;
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
