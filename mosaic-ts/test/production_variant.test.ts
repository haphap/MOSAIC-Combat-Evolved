import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";
import { MACRO_ROLE_CONTRACTS } from "../src/agents/macro/_contracts.js";
import { ALL_AGENTS } from "../src/agents/prompts/cohorts.js";
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
    autoresearch: {
      agent_mutation_cooldown_hours: 24,
      keep_revert_lockout_days: 3,
      keep_threshold_delta_sharpe: 0.1,
      monthly_modification_cap_per_cohort: 4,
      evaluation_horizon_trading_days: 5,
    },
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
    row_count: 56,
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
  const revision = "a".repeat(40);
  const releaseId = `execution-behavior-release:${canonicalHash({ model }).slice("sha256:".length)}`;
  return {
    schema_version: "execution_behavior_release_manifest_v1",
    execution_behavior_release_id: releaseId,
    execution_behavior_release_hash: canonicalHash({ releaseId }),
    private_prompt_commit: revision,
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
    variants: ALL_AGENTS.flatMap((agent) =>
      (["en", "zh"] as const).map((language) => {
        const contentHash = `sha256:${language === "zh" ? "1" : "2"}${"0".repeat(63)}`;
        return {
          variant_path: `cohort_default/test/${agent}.${language}.md`,
          agent_id: agent,
          cohort_id: "cohort_default",
          language,
          prompt_content_hash: contentHash,
          immutable_contract_block_hash: canonicalHash({ agent, language }),
          prompt_behavior_version: `prompt-behavior:${contentHash.slice("sha256:".length)}`,
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
          runtime_tool_manifest_hash: canonicalHash({ agent, tools: true }),
          knot_champion_baseline_hash: canonicalHash({ agent, language, knot: true }),
        };
      }),
    ) as ExecutionBehaviorReleaseManifest["variants"],
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
  it("freezes exactly 28 behavior bindings with 24/4 dimension semantics", () => {
    const binding = buildDarwinianRuntimeBinding({
      cohortId: "cohort_default",
      config: config(),
      llmHandle: { provider: "fake", model: "fake-model", baseUrl: undefined },
      promptPreflight: preflight(),
      executionBehaviorRelease: release(),
      effectiveAt: "2026-07-17T09:00:00.000Z",
    });
    expect(binding.language).toBe("zh");
    expect(Object.keys(binding.agent_behavior_bindings)).toHaveLength(28);
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
      binding.agent_behavior_bindings.geopolitical?.component_weight_contract_version,
    ).toBeNull();
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
    const zh = buildDarwinianRuntimeBinding({
      ...base,
      config: config("Chinese"),
      llmHandle: { provider: "fake", model: "model-a", baseUrl: undefined },
      executionBehaviorRelease: release("model-a"),
    });
    const en = buildDarwinianRuntimeBinding({
      ...base,
      config: config("English"),
      llmHandle: { provider: "fake", model: "model-a", baseUrl: undefined },
      executionBehaviorRelease: release("model-a"),
    });
    const otherModel = buildDarwinianRuntimeBinding({
      ...base,
      config: config("Chinese"),
      llmHandle: { provider: "fake", model: "model-b", baseUrl: undefined },
      executionBehaviorRelease: release("model-b"),
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
    expect(() =>
      buildDarwinianRuntimeBinding({
        ...base,
        llmHandle: { provider: "fake", model: "fake-model", baseUrl: "https://private.test" },
        executionBehaviorRelease: release(),
      }),
    ).toThrow(/base URL mode/);

    const privateEndpointRelease = release();
    privateEndpointRelease.provider_binding.base_url_mode = "CONFIGURED_PRIVATE_ENDPOINT";
    expect(() =>
      buildDarwinianRuntimeBinding({
        ...base,
        llmHandle: { provider: "fake", model: "fake-model", baseUrl: undefined },
        executionBehaviorRelease: privateEndpointRelease,
      }),
    ).toThrow(/base URL mode/);
  });

  it("validates the complete component snapshot before graph execution", () => {
    const asOf = "2026-07-17T09:00:00.000Z";
    const binding = buildDarwinianRuntimeBinding({
      cohortId: "cohort_default",
      config: config(),
      llmHandle: { provider: "fake", model: "fake-model", baseUrl: undefined },
      promptPreflight: preflight(),
      executionBehaviorRelease: release(),
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
