import { describe, expect, it } from "vitest";
import type { DailyCycleStateType } from "../src/agents/state.js";
import type { RkeFixedEpisodeManifestResult } from "../src/bridge/types.js";
import {
  aggregatePairedOutputStats,
  buildBenchmarkEvidenceRefs,
  buildBenchmarkQualitySummary,
  collectPairedOutputRecords,
  completedEpisodeDateModelRuns,
  episodeDateCases,
  fixedBenchmarkPrivateOutputDir,
  selectModelConfigs,
} from "../src/cli/commands/rke-fixed-benchmark.js";

const manifest = {
  schema_version: "rke_fixed_episode_benchmark_manifest_v1",
  benchmark_status: "ready_to_run",
  cohort: "cohort_default",
  episode_count: 2,
  as_of_date_count: 3,
  agent_count: 2,
  model_config_count: 2,
  planned_run_count: 6,
  episodes: [
    { episode_id: "e1", regime: "r1", as_of_dates: ["2024-01-02", "2024-01-03"] },
    { episode_id: "e2", regime: "r2", as_of_dates: ["2024-02-01"] },
  ],
  agents_by_layer: {},
  model_configs: [
    { model_config_id: "baseline_current_config", runner: "configured_default", required: true },
    { model_config_id: "api_model_if_available", runner: "api", required: false },
  ],
  input_requirements: [],
  scoring_metrics: [],
  prompt_preflight: {
    ready: true,
    row_count: 0,
    blocked_count: 0,
    blocked_reasons: [],
    source_status: {
      ready: true,
      blocked_reason: "",
      resolved_source: "private_repo",
      prompt_repo_id: "private-prompts",
      prompt_repo_revision: "abc123",
      prompt_repo_dirty_count: 0,
    },
    fallback_used: false,
  },
  manual_review: { status: "not_run", required: true, reviewer_timestamp: null },
  promotion_allowed: false,
} as RkeFixedEpisodeManifestResult;

describe("rke-fixed-benchmark helpers", () => {
  it("expands fixed episodes and selects required model configs by default", () => {
    expect(episodeDateCases(manifest)).toEqual([
      { episode_id: "e1", as_of_date: "2024-01-02" },
      { episode_id: "e1", as_of_date: "2024-01-03" },
      { episode_id: "e2", as_of_date: "2024-02-01" },
    ]);
    expect(selectModelConfigs(manifest).map((config) => config.model_config_id)).toEqual([
      "baseline_current_config",
    ]);
    expect(selectModelConfigs(manifest, ["api_model_if_available"])[0]?.model_config_id).toBe(
      "api_model_if_available",
    );
  });

  it("filters fixed episode dates for split runs", () => {
    expect(episodeDateCases(manifest, ["2024-02-01"])).toEqual([
      { episode_id: "e2", as_of_date: "2024-02-01" },
    ]);
    expect(() => episodeDateCases(manifest, ["2024-03-01"])).toThrow(
      "no fixed episode cases matched as_of_date=2024-03-01",
    );
  });

  it("records paired output hashes without output bodies", () => {
    const state = {
      layer1_outputs: { dollar: { agent: "dollar", confidence: 0.7 } },
      layer2_outputs: {},
      layer3_outputs: {},
      layer4_outputs: { cro: { agent: "cro", confidence: 0.2 } },
    } as unknown as DailyCycleStateType;

    const rows = collectPairedOutputRecords(
      "bench-1",
      "episode-1",
      "2024-01-02",
      "baseline_current_config",
      state,
    );

    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({
      benchmark_run_id: "bench-1",
      agent: "dollar",
      layer: "macro",
    });
    expect(rows[0]?.output_sha256).toMatch(/^[a-f0-9]{64}$/);
    expect(JSON.stringify(rows)).not.toContain("confidence");
  });

  it("builds gate evidence refs and quality summary", () => {
    const refs = buildBenchmarkEvidenceRefs("bench-1");
    expect(refs.benchmark_runner_ref).toBe("rke-fixed:bench-1:runner");
    expect(JSON.stringify(refs)).not.toContain(".mosaic");

    const summary = buildBenchmarkQualitySummary(manifest, {
      benchmarkRunId: "bench-1",
      pairedOutputCount: 2,
      modelConfigOutputCounts: { baseline_current_config: 2 },
      coveredEpisodeIds: new Set(["e1"]),
      coveredAsOfDates: new Set(["2024-01-02"]),
      coveredAgents: new Set(["dollar", "cro"]),
      currentDataViolationCount: 1,
      fallbackPromptRunCount: 0,
      errorCount: 0,
    });
    expect(summary.current_data_confirmation_violation_count).toBe(1);
    expect(summary.covered_agent_count).toBe(2);
    expect(summary.schema_failure_gate_passed).toBe(true);
  });

  it("aggregates paired output stats across split model-config runs", () => {
    const rows = [
      {
        benchmark_run_id: "bench-1",
        episode_id: "e1",
        as_of_date: "2024-01-02",
        model_config_id: "local_qwen_27b",
        agent: "dollar",
        layer: "macro",
        output_sha256: "a".repeat(64),
      },
      {
        benchmark_run_id: "bench-1",
        episode_id: "e1",
        as_of_date: "2024-01-02",
        model_config_id: "local_qwen_27b",
        agent: "dollar",
        layer: "macro",
        output_sha256: "a".repeat(64),
      },
      {
        benchmark_run_id: "bench-1",
        episode_id: "e1",
        as_of_date: "2024-01-02",
        model_config_id: "local_qwen3_6_35b",
        agent: "dollar",
        layer: "macro",
        output_sha256: "b".repeat(64),
      },
    ];

    const stats = aggregatePairedOutputStats("bench-1", rows);

    expect(stats.pairedOutputCount).toBe(2);
    expect(stats.modelConfigOutputCounts).toEqual({
      local_qwen3_6_35b: 1,
      local_qwen_27b: 1,
    });
    expect(stats.coveredAsOfDates).toEqual(new Set(["2024-01-02"]));
  });

  it("detects completed episode/date/model runs for resume", () => {
    const rows = [
      {
        benchmark_run_id: "bench-1",
        episode_id: "e1",
        as_of_date: "2024-01-02",
        model_config_id: "local_qwen_27b",
        agent: "dollar",
        layer: "macro",
        output_sha256: "a".repeat(64),
      },
      {
        benchmark_run_id: "bench-1",
        episode_id: "e1",
        as_of_date: "2024-01-02",
        model_config_id: "local_qwen_27b",
        agent: "cro",
        layer: "decision",
        output_sha256: "b".repeat(64),
      },
      {
        benchmark_run_id: "bench-1",
        episode_id: "e1",
        as_of_date: "2024-01-03",
        model_config_id: "local_qwen_27b",
        agent: "dollar",
        layer: "macro",
        output_sha256: "c".repeat(64),
      },
    ];

    expect(completedEpisodeDateModelRuns(rows, 2)).toEqual(
      new Set(["local_qwen_27b|e1|2024-01-02"]),
    );
  });

  it("resolves private benchmark output under the repo root", () => {
    const outputDir = fixedBenchmarkPrivateOutputDir();

    expect(outputDir).toMatch(/\/\.mosaic\/rke\/all_agent_evolution\/fixed_episode_benchmark$/);
    expect(outputDir).not.toContain("/mosaic-ts/.mosaic/");
  });
});
