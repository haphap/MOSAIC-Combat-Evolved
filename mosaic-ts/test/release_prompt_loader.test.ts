import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { clearPromptCache, loadPromptWithKnobs } from "../src/agents/prompts/loader.js";
import {
  type ActivePromptReleaseManifest,
  type ReleasePromptPair,
  releasePromptPairHash,
  releasePromptSetHash,
} from "../src/agents/prompts/prompt_release_contract.js";
import {
  buildReleasePromptPairsAtCommit,
  resolveConfiguredPromptReleaseContext,
} from "../src/agents/prompts/release_prompt_loader.js";
import { ActivePromptReleaseRegistry } from "../src/autoresearch/release_registry.js";

const HASH = `sha256:${"1".repeat(64)}`;
const PROMPT_PATHS = {
  zh: "prompts/mosaic/cohort_default/macro/central_bank.zh.md",
  en: "prompts/mosaic/cohort_default/macro/central_bank.en.md",
};
const roots: string[] = [];

afterEach(() => {
  clearPromptCache();
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});

function sha256(text: string): string {
  return `sha256:${createHash("sha256").update(text).digest("hex")}`;
}

function canaryAssignmentKey(releaseId: string, trafficPercent: number, selected: boolean): string {
  for (let index = 0; index < 10_000; index += 1) {
    const key = `assignment-${index}`;
    const bucket = Number.parseInt(
      createHash("sha256").update(`${releaseId}\0${key}`).digest("hex").slice(0, 8),
      16,
    );
    if ((bucket / 0x1_0000_0000) * 100 < trafficPercent === selected) return key;
  }
  throw new Error("canary assignment fixture unavailable");
}

function prompt(body: string): string {
  return `\`\`\`research-knobs
research-knobs:
  schema_version: research_knobs_v1
  layer: macro
  agent: macro.central_bank
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
  lookbacks:
    net_injection_window_days: 7
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
\`\`\`
${body}`;
}

function gitRepo(contents: { zh: string; en: string }): { root: string; commit: string } {
  const root = mkdtempSync(join(tmpdir(), "mosaic-release-prompts-"));
  roots.push(root);
  execFileSync("git", ["init", "-q", root]);
  for (const language of ["zh", "en"] as const) {
    const path = join(root, PROMPT_PATHS[language]);
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, contents[language], "utf-8");
  }
  execFileSync("git", ["-C", root, "add", "."]);
  execFileSync("git", [
    "-C",
    root,
    "-c",
    "user.name=Codex Test",
    "-c",
    "user.email=codex@example.invalid",
    "commit",
    "-qm",
    "fixture",
  ]);
  return {
    root,
    commit: execFileSync("git", ["-C", root, "rev-parse", "HEAD"], {
      encoding: "utf-8",
    }).trim(),
  };
}

function pair(contents: { zh: string; en: string }): ReleasePromptPair {
  const value = {
    agent: "central_bank",
    layer: "macro" as const,
    cohort: "cohort_default",
    stages: ["agent_run" as const],
    zh: { path: PROMPT_PATHS.zh, sha256: sha256(contents.zh) },
    en: { path: PROMPT_PATHS.en, sha256: sha256(contents.en) },
  };
  return { ...value, pair_hash: releasePromptPairHash(value) };
}

function release(opts: {
  promptCommit: string;
  promptPair: ReleasePromptPair;
  fallback?: { promptCommit: string; promptPair: ReleasePromptPair };
  closure?: { catalogHash: string; schemaHash: string; evaluationContractHash: string };
}): ActivePromptReleaseManifest {
  const promptPairs = [opts.promptPair];
  const fallbackPairs = opts.fallback ? [opts.fallback.promptPair] : null;
  return {
    schema_version: "active_prompt_release_manifest_v1",
    release_id: "release-1",
    base_release_id: null,
    lifecycle_state: "active",
    prompt_commit: opts.promptCommit,
    code_commit: "7654321",
    prompt_hash: releasePromptSetHash(promptPairs),
    prompt_pairs: promptPairs,
    stage_snapshot_hashes: { "central_bank:agent_run": HASH },
    catalog_hash: opts.closure?.catalogHash ?? HASH,
    schema_hash: opts.closure?.schemaHash ?? HASH,
    evaluation_contract_hash: opts.closure?.evaluationContractHash ?? HASH,
    keep_decision_hash: HASH,
    keep_decision_state: "kept",
    release_evidence: {
      version_id: 1,
      mutation_id: "mutation-1",
      experiment_id: "experiment-1",
      mutated_agent: "central_bank",
      evaluation_result_hash: HASH,
      transaction_manifest_hash: HASH,
      prompt_pair_sha256: "1".repeat(64),
    },
    activation_scope: {
      cohort: "cohort_default",
      account_mode: "paper",
      traffic_percent: 100,
    },
    approval_policy_id: "decision_release_manual_v1",
    approved_by: "operator:test",
    canary_started_at: "2026-07-10T00:00:00Z",
    canary_ended_at: "2026-07-10T01:00:00Z",
    runtime_slo_summary: {
      passed: true,
      sample_count: 20,
      schema_failure_rate: 0,
      fallback_rate: 0,
      source_failure_rate: 0,
      unsupported_influence_rejection_rate: 0,
      validator_rejection_rate: 0,
      latency_p95_ms: 100,
      token_budget_breach_count: 0,
      duplicate_order_intent_count: 0,
      exposure_breach_count: 0,
    },
    runtime_slo_evidence: {
      schema_version: "prompt_release_canary_slo_evidence_v1",
      release_id: "release-1",
      account_mode: "paper",
      traffic_percent: 10,
      canary_started_at: "2026-07-10T00:00:00Z",
      observation_ended_at: "2026-07-10T01:00:00Z",
      eligible_event_count: 20,
      excluded_event_count: 0,
      excluded_count_by_reason: {},
      event_set_hash: HASH,
      stage_snapshot_hashes_hash: HASH,
      aggregator_id: "prompt_release_canary_slo",
      aggregator_version: "1",
      artifact_hash: HASH,
    },
    rollback_triggers: ["schema_failure_rate_gt_0"],
    previous_approved_release_id: null,
    bundled_fallback:
      opts.fallback && fallbackPairs
        ? {
            prompt_commit: opts.fallback.promptCommit,
            prompt_hash: releasePromptSetHash(fallbackPairs),
            prompt_pairs: fallbackPairs,
            schema_hash: HASH,
            catalog_hash: HASH,
          }
        : null,
    created_at: "2026-07-10T00:00:00Z",
    activated_at: "2026-07-10T01:00:00Z",
    rolled_back_at: null,
  };
}

describe("release-pinned prompt loading", () => {
  it("builds a prompt-pair closure from the exact candidate commit", async () => {
    const contents = { zh: prompt("candidate zh"), en: prompt("candidate en") };
    const repo = gitRepo(contents);
    writeFileSync(join(repo.root, PROMPT_PATHS.zh), prompt("floating zh"), "utf-8");

    const pairs = await buildReleasePromptPairsAtCommit({
      repo: repo.root,
      commit: repo.commit,
      cohort: "cohort_default",
      specs: [{ agent: "central_bank", layer: "macro", stages: [{ stage: "agent_run" }] }],
    });

    expect(pairs).toEqual([pair(contents)]);
  });

  it("keeps explicit authoring roots outside the active release pointer", async () => {
    const contents = { zh: prompt("authoring zh"), en: prompt("authoring en") };
    const repo = gitRepo(contents);
    const previous = process.env.MOSAIC_ACTIVE_PROMPT_RELEASE_REGISTRY_ROOT;
    process.env.MOSAIC_ACTIVE_PROMPT_RELEASE_REGISTRY_ROOT = join(repo.root, "missing-registry");
    try {
      const loaded = await loadPromptWithKnobs({
        agent: "central_bank",
        cohort: "cohort_default",
        stage: "agent_run",
        privatePromptsRoot: join(repo.root, "prompts", "mosaic"),
        noCache: true,
      });
      expect(loaded.bodies.zh).toContain("authoring zh");
      expect(loaded.release).toBeUndefined();
    } finally {
      if (previous === undefined) delete process.env.MOSAIC_ACTIVE_PROMPT_RELEASE_REGISTRY_ROOT;
      else process.env.MOSAIC_ACTIVE_PROMPT_RELEASE_REGISTRY_ROOT = previous;
    }
  });

  it("reads the manifest commit instead of a floating private worktree", async () => {
    const contents = { zh: prompt("private zh v1"), en: prompt("private en v1") };
    const repo = gitRepo(contents);
    writeFileSync(join(repo.root, PROMPT_PATHS.zh), prompt("floating zh v2"), "utf-8");

    const loaded = await loadPromptWithKnobs({
      agent: "central_bank",
      cohort: "cohort_default",
      stage: "agent_run",
      noCache: true,
      releaseContext: {
        manifest: release({ promptCommit: repo.commit, promptPair: pair(contents) }),
        privatePromptRepo: repo.root,
        accountMode: "paper",
        expectedCatalogHash: HASH,
        expectedSchemaHash: HASH,
        expectedEvaluationContractHash: HASH,
      },
    });

    expect(loaded.bodies.zh).toContain("private zh v1");
    expect(loaded.bodies.zh).not.toContain("floating zh v2");
    expect(loaded.release).toMatchObject({
      release_id: "release-1",
      source: "private",
      prompt_commit: repo.commit,
    });
  });

  it("loads a traffic-assigned canary manifest", async () => {
    const contents = { zh: prompt("canary zh"), en: prompt("canary en") };
    const repo = gitRepo(contents);
    const active = release({ promptCommit: repo.commit, promptPair: pair(contents) });
    const canary: ActivePromptReleaseManifest = {
      ...active,
      lifecycle_state: "canary",
      activation_scope: { ...active.activation_scope, traffic_percent: 10 },
      canary_ended_at: null,
      runtime_slo_summary: null,
      runtime_slo_evidence: null,
      activated_at: null,
    };

    const loaded = await loadPromptWithKnobs({
      agent: "central_bank",
      cohort: "cohort_default",
      stage: "agent_run",
      noCache: true,
      releaseContext: {
        manifest: canary,
        privatePromptRepo: repo.root,
        accountMode: "paper",
      },
    });

    expect(loaded.release).toMatchObject({
      release_id: "release-1",
      lifecycle_state: "canary",
      traffic_percent: 10,
    });
  });

  it("refreshes rollout metadata when a cached canary becomes active", async () => {
    const contents = { zh: prompt("candidate zh"), en: prompt("candidate en") };
    const repo = gitRepo(contents);
    const active = release({ promptCommit: repo.commit, promptPair: pair(contents) });
    const canary: ActivePromptReleaseManifest = {
      ...active,
      lifecycle_state: "canary",
      activation_scope: { ...active.activation_scope, traffic_percent: 10 },
      canary_ended_at: null,
      runtime_slo_summary: null,
      runtime_slo_evidence: null,
      activated_at: null,
    };

    const first = await loadPromptWithKnobs({
      agent: "central_bank",
      cohort: "cohort_default",
      stage: "agent_run",
      releaseContext: { manifest: canary, privatePromptRepo: repo.root, accountMode: "paper" },
    });
    const second = await loadPromptWithKnobs({
      agent: "central_bank",
      cohort: "cohort_default",
      stage: "agent_run",
      releaseContext: { manifest: active, privatePromptRepo: repo.root, accountMode: "paper" },
    });

    expect(first.release).toMatchObject({ lifecycle_state: "canary", traffic_percent: 10 });
    expect(second.release).toMatchObject({ lifecycle_state: "active", traffic_percent: 100 });
  });

  it("fails closed for first-canary control traffic instead of reading unpinned prompts", async () => {
    const contents = { zh: prompt("canary candidate zh"), en: prompt("canary candidate en") };
    const registryRoot = mkdtempSync(join(tmpdir(), "mosaic-first-canary-"));
    roots.push(registryRoot);
    const activeShape = release({
      promptCommit: "1234567",
      promptPair: pair(contents),
    });
    const staged: ActivePromptReleaseManifest = {
      ...activeShape,
      lifecycle_state: "staged",
      activation_scope: { ...activeShape.activation_scope, traffic_percent: 0 },
      approved_by: null,
      canary_started_at: null,
      canary_ended_at: null,
      runtime_slo_summary: null,
      runtime_slo_evidence: null,
      activated_at: null,
    };
    const canary: ActivePromptReleaseManifest = {
      ...staged,
      lifecycle_state: "canary",
      activation_scope: { ...staged.activation_scope, traffic_percent: 10 },
      approved_by: "operator:test",
      canary_started_at: "2026-07-10T00:00:00Z",
    };
    const registry = new ActivePromptReleaseRegistry(registryRoot);
    await registry.stage(staged);
    await registry.transition(canary, {
      audit: { operator: "operator:test", reason: "start first canary" },
    });

    const previousRegistry = process.env.MOSAIC_ACTIVE_PROMPT_RELEASE_REGISTRY_ROOT;
    try {
      process.env.MOSAIC_ACTIVE_PROMPT_RELEASE_REGISTRY_ROOT = registryRoot;
      await expect(
        resolveConfiguredPromptReleaseContext(canaryAssignmentKey("release-1", 10, false)),
      ).rejects.toThrow("active_prompt_release_missing");
    } finally {
      if (previousRegistry === undefined) {
        delete process.env.MOSAIC_ACTIVE_PROMPT_RELEASE_REGISTRY_ROOT;
      } else {
        process.env.MOSAIC_ACTIVE_PROMPT_RELEASE_REGISTRY_ROOT = previousRegistry;
      }
    }
  });

  it("uses only a manifest-pinned bundled fallback when private source is unavailable", async () => {
    const privateContents = { zh: prompt("private zh"), en: prompt("private en") };
    const fallbackContents = { zh: prompt("fallback zh"), en: prompt("fallback en") };
    const bundled = gitRepo(fallbackContents);
    const loaded = await loadPromptWithKnobs({
      agent: "central_bank",
      cohort: "cohort_default",
      stage: "agent_run",
      noCache: true,
      releaseContext: {
        manifest: release({
          promptCommit: "deadbee",
          promptPair: pair(privateContents),
          fallback: { promptCommit: bundled.commit, promptPair: pair(fallbackContents) },
        }),
        bundledRepo: bundled.root,
        expectedCatalogHash: HASH,
        expectedSchemaHash: HASH,
        expectedEvaluationContractHash: HASH,
      },
    });

    expect(loaded.bodies.zh).toContain("fallback zh");
    expect(loaded.release?.source).toBe("bundled_fallback");
  });

  it("fails closed on hash drift instead of switching to fallback", async () => {
    const privateContents = { zh: prompt("private zh"), en: prompt("private en") };
    const fallbackContents = { zh: prompt("fallback zh"), en: prompt("fallback en") };
    const privateRepo = gitRepo(privateContents);
    const bundled = gitRepo(fallbackContents);
    const driftedPair = pair(privateContents);
    driftedPair.zh.sha256 = HASH;
    driftedPair.pair_hash = releasePromptPairHash(driftedPair);

    await expect(
      loadPromptWithKnobs({
        agent: "central_bank",
        cohort: "cohort_default",
        stage: "agent_run",
        noCache: true,
        releaseContext: {
          manifest: release({
            promptCommit: privateRepo.commit,
            promptPair: driftedPair,
            fallback: { promptCommit: bundled.commit, promptPair: pair(fallbackContents) },
          }),
          privatePromptRepo: privateRepo.root,
          bundledRepo: bundled.root,
        },
      }),
    ).rejects.toThrow("prompt_release_file_hash_mismatch:private:zh");
  });

  it("resolves the aggregate active pointer for configured runtime loads", async () => {
    const contents = { zh: prompt("active zh"), en: prompt("active en") };
    const repo = gitRepo(contents);
    const registryRoot = mkdtempSync(join(tmpdir(), "mosaic-active-release-"));
    roots.push(registryRoot);
    const localClosure = JSON.parse(
      readFileSync(
        join(
          process.cwd(),
          "..",
          "registry",
          "prompt_checks",
          "domain_knob_evaluation_contract_v1.json",
        ),
        "utf-8",
      ),
    ) as { catalog_hash: string; schema_hash: string; contract_hash: string };
    const active = release({
      promptCommit: repo.commit,
      promptPair: pair(contents),
      closure: {
        catalogHash: localClosure.catalog_hash,
        schemaHash: localClosure.schema_hash,
        evaluationContractHash: localClosure.contract_hash,
      },
    });
    const staged: ActivePromptReleaseManifest = {
      ...active,
      lifecycle_state: "staged",
      activation_scope: { ...active.activation_scope, traffic_percent: 0 },
      approved_by: null,
      canary_started_at: null,
      canary_ended_at: null,
      runtime_slo_summary: null,
      runtime_slo_evidence: null,
      activated_at: null,
    };
    const canary: ActivePromptReleaseManifest = {
      ...active,
      lifecycle_state: "canary",
      activation_scope: { ...active.activation_scope, traffic_percent: 10 },
      canary_ended_at: null,
      runtime_slo_summary: null,
      runtime_slo_evidence: null,
      activated_at: null,
    };
    const registry = new ActivePromptReleaseRegistry(registryRoot);
    await registry.stage(staged);
    await registry.transition(canary, {
      audit: { operator: "operator:test", reason: "start canary" },
    });
    await registry.transition(active, {
      expectedBaseReleaseId: null,
      audit: { operator: "operator:test", reason: "activate" },
    });

    const previous = {
      registry: process.env.MOSAIC_ACTIVE_PROMPT_RELEASE_REGISTRY_ROOT,
      repo: process.env.MOSAIC_PROMPTS_REPO,
      root: process.env.MOSAIC_PROMPTS_ROOT,
      privateRepo: process.env.MOSAIC_PRIVATE_PROMPT_REPO,
      mode: process.env.MOSAIC_PROMPT_ACCOUNT_MODE,
      codeCommit: process.env.MOSAIC_CODE_COMMIT,
    };
    try {
      process.env.MOSAIC_ACTIVE_PROMPT_RELEASE_REGISTRY_ROOT = registryRoot;
      process.env.MOSAIC_PROMPTS_REPO = repo.root;
      process.env.MOSAIC_PROMPT_ACCOUNT_MODE = "paper";
      process.env.MOSAIC_CODE_COMMIT = active.code_commit;
      delete process.env.MOSAIC_PROMPTS_ROOT;
      delete process.env.MOSAIC_PRIVATE_PROMPT_REPO;
      const loaded = await loadPromptWithKnobs({
        agent: "central_bank",
        cohort: "cohort_default",
        stage: "agent_run",
        noCache: true,
      });
      expect(loaded.release).toMatchObject({
        release_id: "release-1",
        source: "private",
        prompt_commit: repo.commit,
      });
      process.env.MOSAIC_CODE_COMMIT = "abcdef0";
      await expect(
        loadPromptWithKnobs({
          agent: "central_bank",
          cohort: "cohort_default",
          stage: "agent_run",
          noCache: true,
        }),
      ).rejects.toThrow("prompt_release_code_commit_mismatch");
    } finally {
      for (const [key, value] of [
        ["MOSAIC_ACTIVE_PROMPT_RELEASE_REGISTRY_ROOT", previous.registry],
        ["MOSAIC_PROMPTS_REPO", previous.repo],
        ["MOSAIC_PROMPTS_ROOT", previous.root],
        ["MOSAIC_PRIVATE_PROMPT_REPO", previous.privateRepo],
        ["MOSAIC_PROMPT_ACCOUNT_MODE", previous.mode],
        ["MOSAIC_CODE_COMMIT", previous.codeCommit],
      ] as const) {
        if (value === undefined) delete process.env[key];
        else process.env[key] = value;
      }
    }
  });
});
