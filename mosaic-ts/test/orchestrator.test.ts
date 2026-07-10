import { mkdtempSync, readdirSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { disableManifestResearchKnobsForLegacyFixtures } from "./helpers/research_knobs_env.js";

disableManifestResearchKnobsForLegacyFixtures();

import { backtestFillCommand, runAutoresearchCycle } from "../src/autoresearch/orchestrator.js";
import type { BridgeApi } from "../src/bridge/types.js";

// Mock the mutator module
vi.mock("../src/autoresearch/mutator.js", () => ({
  buildKnobMutationMetadata: vi.fn((opts) => ({
    schema_version: "knob_mutation_metadata_v1",
    mutation_id: opts.mutationId,
    transaction_id: `TX-${opts.mutationId}`,
    experiment_id: `EXP-${opts.mutationId}`,
    mutation_kind: "generic_knob",
    lifecycle_state: "proposed",
    created_at: "2026-01-01T00:00:00.000Z",
    agent: opts.agent,
    cohort: opts.cohort,
    prediction_target: opts.mutation.prediction_target,
    evaluation_metric: opts.mutation.evaluation_metric,
    horizon: opts.mutation.horizon,
    rollback_condition: opts.mutation.rollback_condition,
    base_knobs_sha256: `sha256:${"1".repeat(64)}`,
    new_knobs_sha256: `sha256:${"2".repeat(64)}`,
    catalog_version: "domain_knob_catalog_v1",
    catalog_hash: `sha256:${"3".repeat(64)}`,
    schema_hash: `sha256:${"4".repeat(64)}`,
    evaluation_contract_hash: `sha256:${"5".repeat(64)}`,
    metric_registry_hash: `sha256:${"6".repeat(64)}`,
    calculator_registry_hash: `sha256:${"7".repeat(64)}`,
    domain_card_ids: [],
    evaluation_policy: {
      baseline_id: `sha256:${"1".repeat(64)}`,
      baseline: "rolling_sharpe",
      min_effect_size: 0,
      min_sample_size: 1,
      uncertainty_method: "not_applicable",
      overlapping_sample_policy: "not_applicable",
      require_uncertainty_bound: false,
    },
    changed_paths: opts.mutation.knob_patches.map((patch: { path: string }) => patch.path),
    patches: opts.mutation.knob_patches,
    renormalization: opts.mutation.renormalization,
    decision: opts.decision,
    expected_effect: "effect",
    risk: opts.mutation.risk,
  })),
  appendKnobMutationMetadataLog: vi.fn(),
  mutate: vi.fn(),
  mutateResearchKnobs: vi.fn(),
}));

import { mutate, mutateResearchKnobs } from "../src/autoresearch/mutator.js";

const mockedMutate = vi.mocked(mutate);
const mockedMutateResearchKnobs = vi.mocked(mutateResearchKnobs);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fakeBridgeApi(overrides: Partial<Record<string, unknown>> = {}): BridgeApi {
  return {
    autoresearchTrigger: vi.fn().mockResolvedValue({
      version_id: 1,
      agent: "volatility",
      branch_name: "autoresearch/volatility/20260101",
      base_commit: "abc1234",
    }),
    promptsWrite: vi.fn().mockResolvedValue({
      target: "private_git",
      prompt_repo_id: "private",
      prompt_base_commit_hash: "baseprompt123",
      prompt_commit_hash: "def456",
      prompt_sha256: "f".repeat(64),
      commit_hash: "def456",
      branch: "autoresearch/volatility/20260101",
      paths: ["prompts/mosaic/cohort_default/macro/volatility.zh.md"],
    }),
    autoresearchRecordMutation: vi.fn().mockResolvedValue({ ok: true }),
    autoresearchPrepareWorktree: vi.fn().mockResolvedValue({ path: "/tmp/wt" }),
    autoresearchEvaluatePending: vi.fn().mockResolvedValue({ results: [] }),
    autoresearchCleanupWorktree: vi.fn().mockResolvedValue({ ok: true }),
    ...overrides,
  } as unknown as BridgeApi;
}

class FakeLlm {
  async invoke() {
    return { content: "fake" };
  }
  withStructuredOutput() {
    return { invoke: async () => ({}) };
  }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("runAutoresearchCycle", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedMutate.mockResolvedValue({
      zh_prompt: "rewritten zh",
      en_prompt: "rewritten en",
      modification_summary: "tighten thresholds",
      rationale: "low sharpe",
    });
    mockedMutateResearchKnobs.mockResolvedValue({
      zh_prompt: "knob zh",
      en_prompt: "knob en",
      modification_summary: "knob patch: missing_current_data",
      rationale: "calibration",
      knob_mutation: {
        prediction_target: "policy_stance_1w",
        evaluation_metric: "confidence_calibration_error",
        horizon: "5d",
        rollback_condition: {
          metric: "confidence_calibration_error",
          worse_by: 0.03,
          unit: "ratio",
        },
        knob_patches: [
          {
            path: "/rule_packs/x/rules/y/confidence_policy/missing_current_data/cap",
            old_value: 0.55,
            new_value: 0.5,
            rationale: "calibration",
            expected_effect: "lower overconfidence",
          },
        ],
        renormalization: [],
        risk: "noise",
      },
      base_knobs: {} as never,
      new_knobs: {} as never,
      prompt_file_hashes: {
        zh: { old_sha256: `sha256:${"1".repeat(64)}`, new_sha256: `sha256:${"2".repeat(64)}` },
        en: { old_sha256: `sha256:${"3".repeat(64)}`, new_sha256: `sha256:${"4".repeat(64)}` },
      },
      governance_registry_update: {
        relative_path: "registry/prompt_governance/cohort_default/volatility.json",
        content: '{"schema_version":"prompt_governance_values_v1"}\n',
        old_sha256: `sha256:${"8".repeat(64)}`,
        new_sha256: `sha256:${"9".repeat(64)}`,
      },
      bundled_prompt_update: {
        zh_prompt: "bundled knob zh",
        en_prompt: "bundled knob en",
        prompt_file_hashes: {
          zh: {
            old_sha256: `sha256:${"a".repeat(64)}`,
            new_sha256: `sha256:${"b".repeat(64)}`,
          },
          en: {
            old_sha256: `sha256:${"c".repeat(64)}`,
            new_sha256: `sha256:${"d".repeat(64)}`,
          },
        },
      },
    });
  });

  it("dry-run generates mutation but does not commit", async () => {
    const api = fakeBridgeApi();
    const llm = new FakeLlm();

    const result = await runAutoresearchCycle({
      cohort: "cohort_default",
      dryRun: true,
      maxMutations: 1,
      deps: { llm: llm as never, api },
    });

    expect(result.mutations).toHaveLength(1);
    expect(result.mutations[0]?.status).toBe("dry_run");
    expect(result.mutations[0]?.summary).toBe("tighten thresholds");

    // promptsWrite should NOT be called in dry-run mode
    expect(api.promptsWrite).not.toHaveBeenCalled();
    expect(api.autoresearchRecordMutation).not.toHaveBeenCalled();
    // trigger must be told it's a dry run so it skips branch/DB persistence
    expect(api.autoresearchTrigger).toHaveBeenCalledWith({
      cohort: "cohort_default",
      dry_run: true,
    });
  });

  it("fakeLlm is threaded through to the mutator", async () => {
    const api = fakeBridgeApi();
    const llm = new FakeLlm();

    await runAutoresearchCycle({
      cohort: "cohort_default",
      dryRun: true,
      fakeLlm: true,
      maxMutations: 1,
      deps: { llm: llm as never, api },
    });

    expect(mockedMutate).toHaveBeenCalledWith({
      cohort: "cohort_default",
      agent: "volatility",
      deps: { llm: llm as never, api },
      fakeLlm: true,
    });
  });

  it("auto mode uses parameter-level knob mutation for enabled agents", async () => {
    const api = fakeBridgeApi();
    const llm = new FakeLlm();
    const oldEnv = process.env.MOSAIC_RESEARCH_KNOBS_ENABLED_AGENTS;
    process.env.MOSAIC_RESEARCH_KNOBS_ENABLED_AGENTS = "*";
    try {
      const result = await runAutoresearchCycle({
        cohort: "cohort_default",
        dryRun: true,
        fakeLlm: true,
        maxMutations: 1,
        deps: { llm: llm as never, api },
      });

      expect(result.mutations[0]?.summary).toBe("knob patch: missing_current_data");
      expect(mockedMutateResearchKnobs).toHaveBeenCalledWith({
        cohort: "cohort_default",
        agent: "volatility",
        deps: { llm: llm as never, api },
        fakeLlm: true,
        mutationId: expect.stringMatching(/^KM-1-/),
      });
      expect(mockedMutate).not.toHaveBeenCalled();
      expect(api.promptsWrite).not.toHaveBeenCalled();
    } finally {
      if (oldEnv === undefined) {
        delete process.env.MOSAIC_RESEARCH_KNOBS_ENABLED_AGENTS;
      } else {
        process.env.MOSAIC_RESEARCH_KNOBS_ENABLED_AGENTS = oldEnv;
      }
    }
  });

  it("commits knob mutations through the durable transaction journal", async () => {
    const root = mkdtempSync(join(tmpdir(), "mosaic-orchestrator-transaction-"));
    const oldEnabled = process.env.MOSAIC_RESEARCH_KNOBS_ENABLED_AGENTS;
    const oldTransactionDir = process.env.MOSAIC_PROMPT_MUTATION_TRANSACTION_DIR;
    const oldLog = process.env.MOSAIC_KNOB_MUTATION_LOG;
    process.env.MOSAIC_RESEARCH_KNOBS_ENABLED_AGENTS = "*";
    process.env.MOSAIC_PROMPT_MUTATION_TRANSACTION_DIR = join(root, "transactions");
    process.env.MOSAIC_KNOB_MUTATION_LOG = join(root, "knob_mutations.jsonl");
    const api = fakeBridgeApi({
      promptsWrite: vi.fn(async (params: { target?: string }) =>
        params.target === "project_git"
          ? {
              target: "project_git",
              prompt_repo_id: "project",
              prompt_base_commit_hash: "abc1234",
              prompt_commit_hash: "code4567",
              commit_hash: "code4567",
              branch: "autoresearch/volatility/20260101",
              paths: [
                "prompts/mosaic/cohort_default/macro/volatility.zh.md",
                "prompts/mosaic/cohort_default/macro/volatility.en.md",
              ],
            }
          : {
              target: "private_git",
              prompt_repo_id: "private",
              prompt_base_commit_hash: "baseprompt123",
              prompt_commit_hash: "def4567",
              commit_hash: "def4567",
              branch: "autoresearch/volatility/20260101",
              paths: [
                "prompts/mosaic/cohort_default/macro/volatility.zh.md",
                "prompts/mosaic/cohort_default/macro/volatility.en.md",
              ],
            },
      ),
      promptsPreflight: vi.fn().mockResolvedValue({
        ready: true,
        source_status: { ready: true, prompt_repo_revision: "baseprompt123" },
      }),
    });
    try {
      const result = await runAutoresearchCycle({
        cohort: "cohort_default",
        fakeLlm: true,
        maxMutations: 1,
        deps: { llm: new FakeLlm() as never, api },
      });

      expect(result.mutations[0]?.status).toBe("needs_fill");
      expect(api.promptsWrite).toHaveBeenCalledTimes(2);
      expect(api.autoresearchRecordMutation).toHaveBeenCalledWith(
        expect.objectContaining({
          commit_hash: "def4567",
          code_commit_hash: "code4567",
          mutation_metadata: expect.objectContaining({
            mutation_id: expect.stringMatching(/^KM-1-/),
            transaction_manifest_hash: expect.stringMatching(/^sha256:[0-9a-f]{64}$/),
          }),
        }),
      );
      const manifestDir = join(root, "transactions", "manifests");
      const manifestFiles = readdirSync(manifestDir);
      expect(manifestFiles).toHaveLength(1);
      const manifest = JSON.parse(
        readFileSync(join(manifestDir, manifestFiles[0] ?? "missing"), "utf-8"),
      ) as {
        state: string;
        components: Array<{ repo_id: string; new_commit: string }>;
        metadata_log: { appended: boolean };
      };
      expect(manifest).toMatchObject({
        state: "committed",
        components: [
          { repo_id: "MOSAIC-Prompts", new_commit: "def4567" },
          { repo_id: "MOSAIC-RKE", new_commit: "code4567" },
        ],
        metadata_log: { appended: true },
      });
    } finally {
      if (oldEnabled === undefined) delete process.env.MOSAIC_RESEARCH_KNOBS_ENABLED_AGENTS;
      else process.env.MOSAIC_RESEARCH_KNOBS_ENABLED_AGENTS = oldEnabled;
      if (oldTransactionDir === undefined)
        delete process.env.MOSAIC_PROMPT_MUTATION_TRANSACTION_DIR;
      else process.env.MOSAIC_PROMPT_MUTATION_TRANSACTION_DIR = oldTransactionDir;
      if (oldLog === undefined) delete process.env.MOSAIC_KNOB_MUTATION_LOG;
      else process.env.MOSAIC_KNOB_MUTATION_LOG = oldLog;
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("full cycle triggers, mutates, writes, and records", async () => {
    const api = fakeBridgeApi();
    const llm = new FakeLlm();

    const result = await runAutoresearchCycle({
      cohort: "cohort_default",
      dryRun: false,
      maxMutations: 1,
      deps: { llm: llm as never, api },
    });

    expect(result.mutations).toHaveLength(1);
    expect(result.mutations[0]?.agent).toBe("volatility");
    expect(result.mutations[0]?.version_id).toBe(1);

    // Full cycle calls: trigger -> mutate -> write -> record -> worktree -> eval -> cleanup
    expect(api.autoresearchTrigger).toHaveBeenCalledWith({ cohort: "cohort_default" });
    expect(mockedMutate).toHaveBeenCalledWith({
      cohort: "cohort_default",
      agent: "volatility",
      deps: { llm: llm as never, api },
    });
    expect(api.promptsWrite).toHaveBeenCalledWith({
      agent: "volatility",
      cohort: "cohort_default",
      contents: { zh: "rewritten zh", en: "rewritten en" },
      target: "private_git",
      branch: "autoresearch/volatility/20260101",
      message: "autoresearch: tighten thresholds",
    });
    expect(api.autoresearchRecordMutation).toHaveBeenCalledWith({
      version_id: 1,
      commit_hash: "def456",
      summary: "tighten thresholds",
      prompt_repo_id: "private",
      prompt_base_commit_hash: "baseprompt123",
      prompt_sha256: "f".repeat(64),
      code_commit_hash: "abc1234",
    });
    expect(api.autoresearchPrepareWorktree).not.toHaveBeenCalled();
    expect(api.autoresearchCleanupWorktree).not.toHaveBeenCalled();
  });

  it("does not persist or log mutation rationale", async () => {
    const api = fakeBridgeApi();
    const onLog = vi.fn();
    const llm = new FakeLlm();
    mockedMutate.mockResolvedValueOnce({
      zh_prompt: "rewritten zh",
      en_prompt: "rewritten en",
      modification_summary: "tighten thresholds",
      rationale: "private reasoning that should not be public",
    });

    await runAutoresearchCycle({
      cohort: "cohort_default",
      maxMutations: 1,
      deps: { llm: llm as never, api },
      onLog,
    });

    expect(api.autoresearchRecordMutation).toHaveBeenCalledWith(
      expect.not.objectContaining({
        rationale: expect.any(String),
      }),
    );
    expect(onLog).not.toHaveBeenCalledWith(expect.stringContaining("private reasoning"));
  });

  it("returns and logs backtest-fill commands for missing private prompt runs", async () => {
    const missingRun = {
      kind: "mod" as const,
      cohort: "cohort_default",
      start_date: "2020-01-01",
      end_date: "2020-02-01",
      prompt_commit_hash: "def456",
      prompt_repo_id: "private",
      prompt_sha256: "f".repeat(64),
      code_commit_hash: "abc123",
      private_prompt_commit: "def456",
    };
    const api = fakeBridgeApi({
      autoresearchEvaluatePending: vi.fn().mockResolvedValue({
        results: [{ version_id: 1, status: "needs_fill", missing_runs: [missingRun] }],
      }),
    });
    const onLog = vi.fn();
    const llm = new FakeLlm();

    const result = await runAutoresearchCycle({
      cohort: "cohort_default",
      maxMutations: 1,
      deps: { llm: llm as never, api },
      onLog,
    });

    const expectedCommand = [
      "pnpm dev backtest-fill",
      "--cohort cohort_default",
      "--start 2020-01-01",
      "--end 2020-02-01",
      "--prompt-commit-hash def456",
      "--private-prompt-commit def456",
      "--prompt-repo-id private",
      `--prompt-sha256 ${"f".repeat(64)}`,
      "--code-commit-hash abc123",
    ].join(" ");
    expect(result.mutations[0]?.status).toBe("needs_fill");
    expect(result.mutations[0]?.fill_commands).toEqual([expectedCommand]);
    expect(onLog).toHaveBeenCalledWith(`backtest-fill required: ${expectedCommand}`);
  });

  it("preserves incompatible evaluation status", async () => {
    const api = fakeBridgeApi({
      autoresearchEvaluatePending: vi.fn().mockResolvedValue({
        results: [
          { version_id: 1, status: "incompatible", detail: "unknown_tools=['get_removed']" },
        ],
      }),
    });
    const onLog = vi.fn();
    const llm = new FakeLlm();

    const result = await runAutoresearchCycle({
      cohort: "cohort_default",
      maxMutations: 1,
      deps: { llm: llm as never, api },
      onLog,
    });

    expect(result.mutations[0]?.status).toBe("incompatible");
    expect(result.mutations[0]?.error).toContain("get_removed");
    expect(onLog).toHaveBeenCalledWith("evaluation incompatible: unknown_tools=['get_removed']");
  });

  it("constraint rejection (trigger throws) stops the loop", async () => {
    const api = fakeBridgeApi({
      autoresearchTrigger: vi.fn().mockRejectedValue(new Error("cooldown active")),
    });
    const llm = new FakeLlm();

    const result = await runAutoresearchCycle({
      cohort: "cohort_default",
      maxMutations: 3,
      deps: { llm: llm as never, api },
    });

    // Loop should break immediately; no mutations produced
    expect(result.mutations).toHaveLength(0);
    expect(mockedMutate).not.toHaveBeenCalled();
  });

  it("multiple mutations: loops N times when maxMutations=N", async () => {
    let callCount = 0;
    const api = fakeBridgeApi({
      autoresearchTrigger: vi.fn().mockImplementation(async () => {
        callCount++;
        return {
          version_id: callCount,
          agent: callCount === 1 ? "volatility" : "sentiment",
          branch_name: `autoresearch/agent${callCount}/20260101`,
          base_commit: `commit${callCount}`,
        };
      }),
    });
    const llm = new FakeLlm();

    const result = await runAutoresearchCycle({
      cohort: "cohort_default",
      maxMutations: 2,
      deps: { llm: llm as never, api },
    });

    expect(result.mutations).toHaveLength(2);
    expect(result.mutations[0]?.version_id).toBe(1);
    expect(result.mutations[0]?.agent).toBe("volatility");
    expect(result.mutations[1]?.version_id).toBe(2);
    expect(result.mutations[1]?.agent).toBe("sentiment");
    expect(api.autoresearchTrigger).toHaveBeenCalledTimes(2);
    expect(mockedMutate).toHaveBeenCalledTimes(2);
  });

  it("records error status when mutate throws", async () => {
    const api = fakeBridgeApi();
    const llm = new FakeLlm();
    mockedMutate.mockRejectedValueOnce(new Error("invariant violated"));

    const result = await runAutoresearchCycle({
      cohort: "cohort_default",
      maxMutations: 1,
      deps: { llm: llm as never, api },
    });

    expect(result.mutations).toHaveLength(1);
    expect(result.mutations[0]?.status).toBe("error");
    expect(result.mutations[0]?.error).toContain("invariant violated");
    expect(api.promptsWrite).not.toHaveBeenCalled();
  });

  it("redacts private paths and prompt fields from mutation errors", async () => {
    const api = fakeBridgeApi();
    const llm = new FakeLlm();
    mockedMutate.mockRejectedValueOnce(
      new Error(`failed at /tmp/private-prompts/prompts/mosaic/x.md with {"zh_prompt":"秘密正文"}`),
    );

    const result = await runAutoresearchCycle({
      cohort: "cohort_default",
      maxMutations: 1,
      deps: { llm: llm as never, api },
    });

    expect(result.mutations[0]?.error).toContain("<private-prompt-repo>");
    expect(result.mutations[0]?.error).toContain("<redacted-prompt-body>");
    expect(result.mutations[0]?.error).not.toContain("/tmp/private-prompts");
    expect(result.mutations[0]?.error).not.toContain("秘密正文");
  });

  it("redacts private paths from evaluation logs and result errors", async () => {
    const api = fakeBridgeApi({
      autoresearchEvaluatePending: vi.fn().mockResolvedValue({
        results: [
          {
            version_id: 1,
            status: "error",
            detail: "loader failed at /tmp/private-prompts/prompts/mosaic/x.md",
          },
        ],
      }),
    });
    const onLog = vi.fn();
    const llm = new FakeLlm();

    const result = await runAutoresearchCycle({
      cohort: "cohort_default",
      maxMutations: 1,
      deps: { llm: llm as never, api },
      onLog,
    });

    expect(result.mutations[0]?.error).toBe("loader failed at <private-prompt-repo>");
    expect(onLog).toHaveBeenCalledWith("evaluation error: loader failed at <private-prompt-repo>");
    expect(onLog).not.toHaveBeenCalledWith(expect.stringContaining("/tmp/private-prompts"));
  });

  it("passes forceAgent to trigger", async () => {
    const api = fakeBridgeApi();
    const llm = new FakeLlm();

    await runAutoresearchCycle({
      cohort: "cohort_default",
      forceAgent: "sentiment",
      maxMutations: 1,
      deps: { llm: llm as never, api },
    });

    expect(api.autoresearchTrigger).toHaveBeenCalledWith({
      cohort: "cohort_default",
      force_agent: "sentiment",
    });
  });

  it("records kept status when evaluation succeeds", async () => {
    const api = fakeBridgeApi({
      autoresearchEvaluatePending: vi.fn().mockResolvedValue({
        results: [{ version_id: 1, status: "kept", delta_sharpe: 0.15 }],
      }),
    });
    const llm = new FakeLlm();

    const result = await runAutoresearchCycle({
      cohort: "cohort_default",
      maxMutations: 1,
      deps: { llm: llm as never, api },
    });

    expect(result.mutations[0]?.status).toBe("kept");
    expect(result.mutations[0]?.delta_sharpe).toBe(0.15);
    // §11.6 O(N²) fix: evaluation is scoped to the version just triggered.
    expect(api.autoresearchEvaluatePending).toHaveBeenCalledWith({
      cohort: "cohort_default",
      version_id: 1,
    });
  });
});

describe("backtestFillCommand", () => {
  it("quotes arguments that contain whitespace", () => {
    expect(
      backtestFillCommand({
        kind: "base",
        cohort: "cohort default",
        start_date: "2020-01-01",
        end_date: "2020-02-01",
        prompt_commit_hash: "abc123",
      }),
    ).toBe(
      "pnpm dev backtest-fill --cohort 'cohort default' --start 2020-01-01 --end 2020-02-01 --prompt-commit-hash abc123",
    );
  });
});
