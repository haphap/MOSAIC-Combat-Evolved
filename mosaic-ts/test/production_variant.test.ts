import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";
import { MACRO_ROLE_CONTRACTS } from "../src/agents/macro/_contracts.js";
import { ALL_AGENTS, LAYER_BY_AGENT } from "../src/agents/prompts/cohorts.js";
import {
  type ActivePromptReleaseManifest,
  releasePromptPairHash,
  releasePromptSetHash,
} from "../src/agents/prompts/prompt_release_contract.js";
import {
  type ExecutionBehaviorReleaseManifest,
  productionVariantRosterId,
} from "../src/autoresearch/execution_behavior_release.js";
import {
  buildDarwinianRuntimeBinding,
  type ComponentWeightRuntimeSnapshot,
  type DarwinianRuntimeBinding,
  resolveProductionLanguage,
  validateComponentWeightRuntimeSnapshot,
} from "../src/autoresearch/production_variant.js";
import type { MosaicConfig, PromptPreflightResult } from "../src/bridge/types.js";

function config(outputLanguage = "Chinese"): MosaicConfig {
  return {
    llm_provider: "fake",
    deep_think_llm: "fake-model",
    quick_think_llm: "fake-model",
    backend_url: null,
    anthropic_base_url: null,
    anthropic_effort: null,
    output_language: outputLanguage,
    research_depth_name: "deep",
    active_cohort: "cohort_default",
    cohorts: {},
    data_vendors: {},
    tool_vendors: {},
  };
}

function preflight(): PromptPreflightResult {
  const revision = "a".repeat(40);
  return {
    ready: true,
    cohort: "cohort_default",
    expected_prompt_repo_id: "private-prompts",
    source_status: {
      ready: true,
      blocked_reason: "",
      resolved_source: "private_repo",
      prompt_repo_id: "private-prompts",
      prompt_repo_revision: revision,
      prompt_repo_dirty_count: 0,
    },
    row_count: 54,
    blocked_count: 0,
    rows: ALL_AGENTS.flatMap((agent) =>
      (["zh", "en"] as const).map((lang) => ({
        agent,
        layer: "test",
        cohort: "cohort_default",
        lang,
        status: "ready" as const,
        prompt_repo_id: "private-prompts",
        prompt_repo_revision: revision,
        prompt_file_path: `${agent}.${lang}.md`,
        prompt_sha256: `${lang === "zh" ? "1" : "2"}${"0".repeat(63)}`,
        resolved_source: "private_repo" as const,
        fallback_used: false,
      })),
    ),
  };
}

function canonicalHash(value: unknown): string {
  const canonicalize = (item: unknown): unknown => {
    if (Array.isArray(item)) return item.map(canonicalize);
    if (item !== null && typeof item === "object") {
      return Object.fromEntries(
        Object.entries(item as Record<string, unknown>)
          .sort(([left], [right]) => left.localeCompare(right))
          .map(([key, nested]) => [key, canonicalize(nested)]),
      );
    }
    return item;
  };
  return `sha256:${createHash("sha256")
    .update(JSON.stringify(canonicalize(value)))
    .digest("hex")}`;
}

function release(model = "fake-model"): ExecutionBehaviorReleaseManifest {
  const releaseId = `execution-behavior-release:${canonicalHash({ model }).slice("sha256:".length)}`;
  const executionContracts = ALL_AGENTS.flatMap((agent) =>
    (["en", "zh"] as const).map((language) => ({
      execution_contract_id: `execution-contract:${canonicalHash({ agent, language }).slice("sha256:".length)}`,
      agent_id: agent,
      language,
      immutable_contract_block_hash: canonicalHash({ agent, language }),
      execution_behavior_version: `execution-behavior:${canonicalHash({ agent, language, model }).slice("sha256:".length)}`,
      structured_output_schema_bindings: [
        {
          phase: "DEFAULT" as const,
          schema_id: "test",
          schema_hash: canonicalHash({ agent }),
          immutable_phase_instruction_hash: canonicalHash({ agent, language }),
        },
      ],
      structured_output_schema_set_hash: canonicalHash({ agent, language, schema: true }),
      structured_provider_contract_hash: canonicalHash({ agent, provider: true }),
      runtime_tool_manifest_hash: canonicalHash({ agent, tools: true }),
    })),
  ) as ExecutionBehaviorReleaseManifest["execution_contracts"];
  return {
    schema_version: "execution_behavior_release_manifest_v4",
    execution_behavior_release_id: releaseId,
    execution_behavior_release_hash: canonicalHash({ releaseId }),
    provider_binding: {
      provider: "fake",
      model,
      base_url_mode: "PROVIDER_DEFAULT",
      structured_output_mode: "JSON_SCHEMA_STRICT",
      repair_policy: "BOUNDED_SCHEMA_REPAIR_V1",
    },
    active_production_variants: (["en", "zh"] as const).map((language) => ({
      production_variant_roster_id: productionVariantRosterId("cohort_default", language),
      cohort_id: "cohort_default",
      language,
    })) as ExecutionBehaviorReleaseManifest["active_production_variants"],
    execution_contracts: executionContracts,
  };
}

function promptReleaseFor(
  behaviorRelease: ExecutionBehaviorReleaseManifest,
): ActivePromptReleaseManifest {
  const promptPairs = ALL_AGENTS.map((agent) => {
    const layer = LAYER_BY_AGENT[agent];
    if (!layer) throw new Error(`missing test layer for ${agent}`);
    const pairWithoutHash = {
      agent,
      layer,
      cohort: "cohort_default",
      stages: ["agent_run" as const],
      zh: {
        path: `prompts/mosaic/cohort_default/${layer}/${agent}.zh.md`,
        sha256: `sha256:1${"0".repeat(63)}`,
      },
      en: {
        path: `prompts/mosaic/cohort_default/${layer}/${agent}.en.md`,
        sha256: `sha256:2${"0".repeat(63)}`,
      },
    };
    return { ...pairWithoutHash, pair_hash: releasePromptPairHash(pairWithoutHash) };
  });
  const archiveStem =
    `${behaviorRelease.execution_behavior_release_id.slice("execution-behavior-release:".length)}--` +
    `${behaviorRelease.execution_behavior_release_hash.slice("sha256:".length)}.json`;
  return {
    schema_version: "active_prompt_release_manifest_v3",
    release_id: "release:test-canary",
    base_release_id: "release:test-active",
    lifecycle_state: "canary",
    prompt_commit: "a".repeat(40),
    code_commit: "b".repeat(40),
    execution_behavior_release: {
      release_id: behaviorRelease.execution_behavior_release_id,
      release_hash: behaviorRelease.execution_behavior_release_hash,
      archive_ref: `registry/prompt_checks/execution_behavior_releases/${archiveStem}`,
    },
    prompt_hash: releasePromptSetHash(promptPairs),
    prompt_pairs: promptPairs,
    stage_snapshot_hashes: Object.fromEntries(
      ALL_AGENTS.map((agent) => [`${agent}:agent_run`, canonicalHash({ agent, stage: true })]),
    ),
    catalog_hash: canonicalHash({ catalog: true }),
    schema_hash: canonicalHash({ schema: true }),
    evaluation_contract_hash: canonicalHash({ evaluation: true }),
    release_evidence: {
      candidate_id: "candidate:test",
      candidate_hash: canonicalHash({ candidate: true }),
      candidate_publication_hash: canonicalHash({ publication: true }),
      prompt_source_id: "private-prompts",
      promotion_decision_id: "decision:test",
      promotion_decision_hash: canonicalHash({ decision: true }),
      experiment_id: "experiment:test",
      mutated_agent: ALL_AGENTS[0] ?? "china",
      policy_version: "test-policy-v1",
      policy_config_hash: canonicalHash({ policy: true }),
      candidate_prompt_hashes: {
        zh: `sha256:1${"0".repeat(63)}`,
        en: `sha256:2${"0".repeat(63)}`,
      },
      private_state_artifact_hash: canonicalHash({ state: true }),
      behavior_contract_hash: canonicalHash({ behavior: true }),
      mutator_commit: "a".repeat(40),
      mutator_config_hash: canonicalHash({ mutator: true }),
    },
    activation_scope: { cohort: "cohort_default", account_mode: "paper", traffic_percent: 10 },
    approval_policy_id: "manual-test",
    approved_by: "operator:test",
    canary_started_at: "2026-07-17T08:00:00.000Z",
    canary_ended_at: null,
    runtime_slo_summary: null,
    runtime_slo_evidence: null,
    rollback_triggers: ["manual"],
    previous_approved_release_id: "release:test-active",
    bundled_fallback: null,
    created_at: "2026-07-17T08:00:00.000Z",
    activated_at: null,
    rolled_back_at: null,
  };
}

function componentSnapshot(
  binding: DarwinianRuntimeBinding,
  asOf: string,
): ComponentWeightRuntimeSnapshot {
  const resolutions = Object.entries(MACRO_ROLE_CONTRACTS)
    .filter(([, contract]) => contract.mode === "COMPONENTS")
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([agent, contract]) => ({
      agent_id: agent,
      component_weight_contract_version:
        binding.agent_behavior_bindings[agent]?.component_weight_contract_version ?? "",
      component_weights: { ...contract.components },
      release_revision_id: null,
      release_revision_hash: null,
      effective_at: null,
    }));
  const body = {
    schema_version: "component_weight_runtime_snapshot_v2" as const,
    as_of: asOf,
    resolutions,
  };
  const id = `component-weight-runtime-snapshot:${canonicalHash(body).slice("sha256:".length)}`;
  const withId = { component_weight_snapshot_id: id, ...body };
  return { ...withId, component_weight_snapshot_hash: canonicalHash(withId) };
}

describe("Darwinian production runtime binding", () => {
  it("freezes exactly 25 behavior bindings with 21/4 dimension semantics", () => {
    const behaviorRelease = release();
    const binding = buildDarwinianRuntimeBinding({
      cohortId: "cohort_default",
      config: config(),
      llmHandle: { provider: "fake", model: "fake-model", baseUrl: undefined },
      promptPreflight: preflight(),
      executionBehaviorRelease: behaviorRelease,
      activePromptRelease: promptReleaseFor(behaviorRelease),
      effectiveAt: "2026-07-17T09:00:00.000Z",
    });
    expect(binding.language).toBe("zh");
    expect(Object.keys(binding.agent_behavior_bindings)).toHaveLength(25);
    expect(binding.production_variant_roster_id).toMatch(
      /^production-variant-roster:[0-9a-f]{64}$/,
    );
    expect(binding.execution_behavior_release_id).toMatch(
      /^execution-behavior-release:[0-9a-f]{64}$/,
    );
    expect(binding.binding_hash).toMatch(/^sha256:[0-9a-f]{64}$/);
    expect(binding.agent_behavior_bindings.china?.component_weight_contract_version).toBe(
      "macro_component_weights_v2",
    );
    expect(
      binding.agent_behavior_bindings.semiconductor?.reliability_adapter_contract_version,
    ).toMatch(/^reliability-adapter:/);
    expect(binding.agent_behavior_bindings.cio?.reliability_adapter_contract_version).toBeNull();
  });

  it("separates language and model behavior tracks", () => {
    const base = {
      cohortId: "cohort_default",
      promptPreflight: preflight(),
      effectiveAt: "2026-07-17T09:00:00.000Z",
    };
    const zhRelease = release("model-a");
    const zh = buildDarwinianRuntimeBinding({
      ...base,
      config: config("Chinese"),
      llmHandle: { provider: "fake", model: "model-a", baseUrl: undefined },
      executionBehaviorRelease: zhRelease,
      activePromptRelease: promptReleaseFor(zhRelease),
    });
    const enRelease = release("model-a");
    const en = buildDarwinianRuntimeBinding({
      ...base,
      config: config("English"),
      llmHandle: { provider: "fake", model: "model-a", baseUrl: undefined },
      executionBehaviorRelease: enRelease,
      activePromptRelease: promptReleaseFor(enRelease),
    });
    const modelBRelease = release("model-b");
    const otherModel = buildDarwinianRuntimeBinding({
      ...base,
      config: config("Chinese"),
      llmHandle: { provider: "fake", model: "model-b", baseUrl: undefined },
      executionBehaviorRelease: modelBRelease,
      activePromptRelease: promptReleaseFor(modelBRelease),
    });
    expect(en.production_variant_roster_id).not.toBe(zh.production_variant_roster_id);
    expect(en.agent_behavior_bindings.china?.prompt_behavior_version).not.toBe(
      zh.agent_behavior_bindings.china?.prompt_behavior_version,
    );
    expect(otherModel.agent_behavior_bindings.china?.execution_behavior_version).not.toBe(
      zh.agent_behavior_bindings.china?.execution_behavior_version,
    );
  });

  it("rejects Bilingual as an ambiguous production variant", () => {
    expect(() => resolveProductionLanguage(config("Bilingual"))).toThrow(/one explicit language/);
  });

  it("rejects provider-default and private-endpoint base URL mode drift", () => {
    const base = {
      cohortId: "cohort_default",
      config: config(),
      promptPreflight: preflight(),
      effectiveAt: "2026-07-17T09:00:00.000Z",
    };
    const defaultRelease = release();
    expect(() =>
      buildDarwinianRuntimeBinding({
        ...base,
        llmHandle: { provider: "fake", model: "fake-model", baseUrl: "https://private.test" },
        executionBehaviorRelease: defaultRelease,
        activePromptRelease: promptReleaseFor(defaultRelease),
      }),
    ).toThrow(/base URL mode/);

    const privateEndpointRelease = release();
    privateEndpointRelease.provider_binding.base_url_mode = "CONFIGURED_PRIVATE_ENDPOINT";
    expect(() =>
      buildDarwinianRuntimeBinding({
        ...base,
        llmHandle: { provider: "fake", model: "fake-model", baseUrl: undefined },
        executionBehaviorRelease: privateEndpointRelease,
        activePromptRelease: promptReleaseFor(privateEndpointRelease),
      }),
    ).toThrow(/base URL mode/);
  });

  it("rejects an active Prompt Release that differs from the attested execution identity", () => {
    const behaviorRelease = release();
    const activePromptRelease = {
      ...promptReleaseFor(behaviorRelease),
      prompt_commit: "b".repeat(40),
    };
    expect(() =>
      buildDarwinianRuntimeBinding({
        cohortId: "cohort_default",
        config: config(),
        llmHandle: { provider: "fake", model: "fake-model", baseUrl: undefined },
        promptPreflight: preflight(),
        executionBehaviorRelease: behaviorRelease,
        activePromptRelease,
        effectiveAt: "2026-07-17T09:00:00.000Z",
      }),
    ).toThrow(/active Prompt Release/);
  });

  it("validates the complete component snapshot before graph execution", () => {
    const asOf = "2026-07-17T09:00:00.000Z";
    const behaviorRelease = release();
    const binding = buildDarwinianRuntimeBinding({
      cohortId: "cohort_default",
      config: config(),
      llmHandle: { provider: "fake", model: "fake-model", baseUrl: undefined },
      promptPreflight: preflight(),
      executionBehaviorRelease: behaviorRelease,
      activePromptRelease: promptReleaseFor(behaviorRelease),
      effectiveAt: asOf,
    });
    const snapshot = componentSnapshot(binding, asOf);
    expect(validateComponentWeightRuntimeSnapshot(snapshot, binding, asOf)).toBe(snapshot);
    expect(() =>
      validateComponentWeightRuntimeSnapshot(
        {
          ...snapshot,
          resolutions: snapshot.resolutions.slice(1),
        },
        binding,
        asOf,
      ),
    ).toThrow(/exactly seven/);
    expect(() =>
      validateComponentWeightRuntimeSnapshot(
        {
          ...snapshot,
          resolutions: snapshot.resolutions.map((resolution, index) =>
            index === 0
              ? {
                  ...resolution,
                  component_weights: Object.fromEntries(
                    Object.keys(resolution.component_weights).map((component) => [component, 0.5]),
                  ),
                }
              : resolution,
          ),
        },
        binding,
        asOf,
      ),
    ).toThrow(/calibration bounds/);
  });
});
