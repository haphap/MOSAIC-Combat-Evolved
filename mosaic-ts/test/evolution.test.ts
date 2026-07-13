import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Command } from "commander";
import { describe, expect, it } from "vitest";
import type { EvolutionCandidate, EvolutionCheckpoint } from "../src/backtest/evolution.js";
import {
  benjaminiHochberg,
  candidateWindow,
  DEFAULT_EVOLUTION_POLICY,
  evaluationReasonCodes,
  pairedBlockBootstrap,
  pendingEvolutionAfterCompletedDay,
  selectFamilyWinnerId,
  selectLayerAgent,
  shouldTriggerEvolution,
} from "../src/backtest/evolution.js";
import type { BacktestMetricsResult } from "../src/bridge/types.js";
import {
  ensureManifest,
  loadStrictQlibTradingDays,
  registerBacktestEvolve,
} from "../src/cli/commands/backtest-evolve.js";

describe("backtest-evolve CLI", () => {
  it("registers the pinned prompt and resumable run options", () => {
    const program = new Command();
    registerBacktestEvolve(program);
    const command = program.commands.find((item) => item.name() === "backtest-evolve");

    expect(command).toBeDefined();
    expect(command?.options.map((option) => option.long)).toEqual(
      expect.arrayContaining([
        "--start",
        "--end",
        "--run-dir",
        "--prompt-baseline-commit",
        "--resume",
        "--fake-llm",
      ]),
    );
  });

  it("fingerprints the strict local Qlib calendar, instruments, and feature inventory", () => {
    const root = mkdtempSync(join(tmpdir(), "mosaic-qlib-fingerprint-"));
    const previous = process.env.QLIB_CN_DATA_PATH;
    try {
      mkdirSync(join(root, "calendars"), { recursive: true });
      mkdirSync(join(root, "instruments"), { recursive: true });
      mkdirSync(join(root, "features", "sh600000"), { recursive: true });
      writeFileSync(join(root, "calendars", "day.txt"), "2009-01-05\n2009-01-06\n");
      writeFileSync(join(root, "instruments", "all.txt"), "SH600000\t2009-01-05\t2099-12-31\n");
      const feature = join(root, "features", "sh600000", "close.day.bin");
      writeFileSync(feature, Buffer.from([1, 2, 3]));
      process.env.QLIB_CN_DATA_PATH = root;

      const first = loadStrictQlibTradingDays("2009-01-05", "2009-01-06");
      writeFileSync(feature, Buffer.from([3, 2, 1]));
      const changed = loadStrictQlibTradingDays("2009-01-05", "2009-01-06");

      expect(first.tradeDays).toEqual(["2009-01-05", "2009-01-06"]);
      expect(first.fingerprint.feature_file_count).toBe(1);
      expect(first.fingerprint.feature_total_bytes).toBe(3);
      expect(changed.fingerprint.feature_inventory_sha256).toBe(
        first.fingerprint.feature_inventory_sha256,
      );
      expect(changed.fingerprint.feature_content_sha256).not.toBe(
        first.fingerprint.feature_content_sha256,
      );
    } finally {
      if (previous === undefined) delete process.env.QLIB_CN_DATA_PATH;
      else process.env.QLIB_CN_DATA_PATH = previous;
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("rejects resume when initial cash or benchmark changes", () => {
    const root = mkdtempSync(join(tmpdir(), "mosaic-evolution-manifest-"));
    const path = join(root, "manifest.json");
    const base = {
      path,
      start: "2009-01-05",
      end: "2026-06-09",
      cohort: "history_walkforward_2009",
      codeCommit: "code-1",
      baselineCommit: "prompt-1",
      baselinePromptSha256: "sha256:prompt",
      resolution: null,
      runtimeImageId: null,
      fakeLlm: true,
      initialCash: 1_000_000,
      benchmark: "SH000300",
      configOverrides: { memory_in_backtest: false },
      qlibData: qlibFingerprint(),
    };
    try {
      ensureManifest({ ...base, resume: false });
      expect(() => ensureManifest({ ...base, resume: true, initialCash: 2_000_000 })).toThrow(
        "resume manifest does not match",
      );
      expect(() => ensureManifest({ ...base, resume: true, benchmark: "SH000905" })).toThrow(
        "resume manifest does not match",
      );
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});

describe("historical evolution schedule", () => {
  it("uses a 504-session trailing train window and future-only validation/holdout", () => {
    const days = isoDays("2009-01-01", 900);
    const triggerIndex = 504;
    const window = candidateWindow(days, triggerIndex);
    expect(window).not.toBeNull();
    if (!window) throw new Error("expected a complete candidate window");

    expect(window).toEqual({
      trainStart: days[1],
      trainEnd: days[504],
      validationStart: days[510],
      validationEnd: days[599],
      holdoutStart: days[605],
      holdoutEnd: days[694],
    });
    expect(window.validationStart > window.trainEnd).toBe(true);
    expect(window.holdoutStart > window.validationEnd).toBe(true);
  });

  it("triggers only on an unprocessed first trading day of a month after warmup", () => {
    const days = isoDays("2009-01-01", 800);
    const index = days.findIndex(
      (day, current) =>
        current >= DEFAULT_EVOLUTION_POLICY.warmupTradingDays &&
        day.slice(0, 7) !== days[current - 1]?.slice(0, 7),
    );
    const month = days[index]?.slice(0, 7) as string;

    expect(shouldTriggerEvolution(days, index, [])).toBe(true);
    expect(shouldTriggerEvolution(days, index, [month])).toBe(false);
    expect(shouldTriggerEvolution(days, index + 1, [])).toBe(false);
  });

  it("selects the worst scored agent and rotates deterministically on cold start", () => {
    expect(
      selectLayerAgent({
        layer: "macro",
        macroSkill: [macroRow("volatility", -0.5), macroRow("china", 0.1)],
        weights: {},
        rotation: 0,
      }),
    ).toBe("volatility");
    expect(
      selectLayerAgent({
        layer: "sector",
        macroSkill: [],
        weights: {},
        rotation: 2,
      }),
    ).toBe("biotech");
  });

  it("retains a pending month across the next trading day until generation completes", () => {
    const days = isoDays("2009-01-01", 800);
    const triggerIndex = days.findIndex(
      (day, current) =>
        current >= DEFAULT_EVOLUTION_POLICY.warmupTradingDays &&
        day.slice(0, 7) !== days[current - 1]?.slice(0, 7),
    );
    const checkpoint = evolutionCheckpoint(triggerIndex + 1);
    const pending = pendingEvolutionAfterCompletedDay(checkpoint, days);
    expect(pending).toMatchObject({
      triggerIndex,
      triggerDate: days[triggerIndex],
      completedLayers: [],
    });

    if (!pending) throw new Error("expected pending evolution");
    checkpoint.pendingEvolution = pending;
    checkpoint.nextTradingDayIndex += 1;
    expect(pendingEvolutionAfterCompletedDay(checkpoint, days)).toEqual(pending);
  });
});

describe("historical evolution statistics", () => {
  it("produces deterministic paired block-bootstrap evidence", () => {
    const base = Array.from({ length: 90 }, (_, index) => (index % 2 === 0 ? 0.001 : -0.001));
    const candidate = base.map((value) => value + 0.002);
    const first = pairedBlockBootstrap({
      baseReturns: base,
      candidateReturns: candidate,
      seed: "candidate-1",
    });
    const second = pairedBlockBootstrap({
      baseReturns: base,
      candidateReturns: candidate,
      seed: "candidate-1",
    });

    expect(first).toEqual(second);
    expect(first.meanDelta).toBeCloseTo(0.002);
    expect(first.ciLower).toBeGreaterThan(0);
    expect(first.effectiveSampleSize).toBe(18);
  });

  it("applies monotone Benjamini-Hochberg correction", () => {
    const adjusted = benjaminiHochberg([
      { id: "a", pValue: 0.01 },
      { id: "b", pValue: 0.02 },
      { id: "c", pValue: 0.2 },
      { id: "d", pValue: 0.8 },
    ]);

    expect(adjusted.a).toBeCloseTo(0.04);
    expect(adjusted.b).toBeCloseTo(0.04);
    expect(adjusted.c).toBeCloseTo(0.2666666667);
    expect(adjusted.d).toBeCloseTo(0.8);
  });

  it("blocks a candidate on FDR, drawdown, and turnover guardrails", () => {
    const base = metrics({ alpha: 0.01, max_drawdown: -0.1 });
    const candidate = metrics({ alpha: 0.02, max_drawdown: -0.12 });
    const reasons = evaluationReasonCodes(
      {
        base,
        candidate,
        baseTurnover: 1,
        candidateTurnover: 1.2,
        paired: {
          meanDelta: 0.001,
          ciLower: 0.0001,
          ciUpper: 0.002,
          pValue: 0.01,
          effectiveSampleSize: 18,
        },
      },
      { adjustedQ: 0.06 },
    );

    expect(reasons).toEqual(["MAX_DRAWDOWN_WORSE", "TURNOVER_GUARDRAIL", "FDR_GATE_FAILED"]);
  });

  it("selects exactly one independently evaluated winner per candidate family", () => {
    const candidates = [
      passingCandidate("macro", 0.02, 0.002),
      passingCandidate("sector", 0.01, 0.001),
      passingCandidate("decision", 0.01, 0.003),
    ];

    expect(selectFamilyWinnerId(candidates)).toBe("decision");
  });
});

function isoDays(start: string, count: number): string[] {
  const first = new Date(`${start}T00:00:00Z`);
  return Array.from({ length: count }, (_, index) => {
    const date = new Date(first);
    date.setUTCDate(first.getUTCDate() + index);
    return date.toISOString().slice(0, 10);
  });
}

function macroRow(agent: string, score: number) {
  return {
    agent,
    n_obs: 10,
    mean_raw_macro_score_5d: score,
    mean_effective_macro_score_5d: null,
    hit_rate_5d: null,
    mean_influence_weight_equal: null,
    latest_label_type: null,
    label_type_counts: {},
    label_source_status_counts: {},
    primary_label_rate: null,
    fallback_label_rate: null,
    missing_label_rate: null,
    sharpe_window: null,
    latest_signal_date: null,
  };
}

function metrics(overrides: Partial<BacktestMetricsResult>): BacktestMetricsResult {
  return {
    run_id: 1,
    cohort: "history_walkforward_2009",
    start_date: "2011-01-01",
    end_date: "2011-05-01",
    benchmark: "SH000300",
    n_trade_days: 90,
    total_return: 0.03,
    annualized_return: 0.08,
    sharpe: 1,
    max_drawdown: -0.1,
    benchmark_return: 0.02,
    alpha: 0.01,
    initial_cash: 1_000_000,
    final_value: 1_030_000,
    ...overrides,
  };
}

function qlibFingerprint() {
  return {
    calendar_sha256: "sha256:calendar",
    instruments_sha256: "sha256:instruments",
    feature_inventory_sha256: "sha256:inventory",
    feature_content_sha256: "sha256:content",
    feature_file_count: 1,
    feature_total_bytes: 3,
    first_date: "2009-01-05",
    last_date: "2026-06-09",
    selected_days_sha256: "sha256:selected",
  };
}

function evolutionCheckpoint(nextTradingDayIndex: number): EvolutionCheckpoint {
  return {
    schemaVersion: "mosaic.backtest_evolution_checkpoint.v1",
    runId: "run-1",
    cohort: "history_walkforward_2009",
    startDate: "2009-01-01",
    endDate: "2030-01-01",
    nextTradingDayIndex,
    tradeDaysHash: "sha256:days",
    mainBacktestRunId: 1,
    activePromptCommit: "base",
    activePromptSha256: "sha256:base",
    activePromptBranch: "history/run-1/active/main",
    mainArm: {
      positions: {
        snapshot_status: "empty_confirmed",
        position_source: "empty_confirmed",
        source_error_code: null,
        position_snapshot_hash: "sha256:empty",
        positions: [],
      },
      previousTarget: {
        schema_version: "portfolio.previous_target_state.v1",
        snapshot_status: "empty_confirmed",
        final_target_hash: null,
        as_of_date: "2009-01-01",
        portfolio_actions: [],
        source_error_code: null,
      },
    },
    mainUsage: { calls: 0, promptTokens: 0, completionTokens: 0, costUsd: 0, elapsedMs: 0 },
    candidates: [],
    lineage: [],
    processedEvolutionMonths: [],
    layerRotation: { macro: 0, sector: 0, superinvestor: 0, decision: 0 },
  };
}

function passingCandidate(id: string, adjustedQ: number, meanDelta: number): EvolutionCandidate {
  const evaluation = {
    base: metrics({ alpha: 0.01, max_drawdown: -0.1 }),
    candidate: metrics({ alpha: 0.02, max_drawdown: -0.09 }),
    baseTurnover: 1,
    candidateTurnover: 1,
    paired: {
      meanDelta,
      ciLower: 0.0001,
      ciUpper: 0.004,
      pValue: adjustedQ,
      effectiveSampleSize: 18,
    },
  };
  return {
    id,
    familyId: "family-1",
    versionId: id.length,
    agent: id,
    layer: id === "macro" ? "macro" : id === "sector" ? "sector" : "decision",
    triggerDate: "2011-01-03",
    triggerIndex: 504,
    baseCommit: "base",
    candidateCommit: `candidate-${id}`,
    candidatePromptSha256: `sha256:${id}`,
    branchName: `history/run/${id}`,
    window: {
      trainStart: "2009-01-01",
      trainEnd: "2011-01-03",
      validationStart: "2011-01-10",
      validationEnd: "2011-05-10",
      holdoutStart: "2011-05-18",
      holdoutEnd: "2011-09-20",
    },
    runs: { validationBase: 1, validationCandidate: 2, holdoutBase: 3, holdoutCandidate: 4 },
    baseArm: evolutionCheckpoint(0).mainArm,
    candidateArm: evolutionCheckpoint(0).mainArm,
    status: "awaiting_family",
    holdout: evaluation,
    adjustedQ,
    reasonCodes: [],
    usage: {
      base: { calls: 0, promptTokens: 0, completionTokens: 0, costUsd: 0, elapsedMs: 0 },
      candidate: { calls: 0, promptTokens: 0, completionTokens: 0, costUsd: 0, elapsedMs: 0 },
    },
  };
}
