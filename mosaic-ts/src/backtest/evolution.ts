import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import { AGENTS_BY_LAYER, type Layer } from "../agents/prompts/cohorts.js";
import type { CurrentPositionsSnapshot, PreviousTargetState } from "../agents/types.js";
import type {
  BacktestMetricsResult,
  DarwinianWeightTable,
  MacroSkillRow,
} from "../bridge/types.js";

export const EVOLUTION_CHECKPOINT_SCHEMA = "mosaic.backtest_evolution_checkpoint.v1" as const;

export interface EvolutionPolicy {
  warmupTradingDays: number;
  trainingTradingDays: number;
  purgeTradingDays: number;
  validationTradingDays: number;
  embargoTradingDays: number;
  holdoutTradingDays: number;
  blockLength: number;
  bootstrapSamples: number;
  familyAlpha: number;
  maxTurnoverRatio: number;
}

export const DEFAULT_EVOLUTION_POLICY: EvolutionPolicy = {
  warmupTradingDays: 504,
  trainingTradingDays: 504,
  purgeTradingDays: 5,
  validationTradingDays: 90,
  embargoTradingDays: 5,
  holdoutTradingDays: 90,
  blockLength: 5,
  bootstrapSamples: 2_000,
  familyAlpha: 0.05,
  maxTurnoverRatio: 1.1,
};

export interface ArmCheckpoint {
  positions: CurrentPositionsSnapshot;
  previousTarget: PreviousTargetState;
}

export interface LlmUsage {
  calls: number;
  promptTokens: number;
  completionTokens: number;
  costUsd: number;
  elapsedMs: number;
}

export const EMPTY_LLM_USAGE: LlmUsage = {
  calls: 0,
  promptTokens: 0,
  completionTokens: 0,
  costUsd: 0,
  elapsedMs: 0,
};

export function addLlmUsage(left: LlmUsage, right: LlmUsage): LlmUsage {
  return {
    calls: left.calls + right.calls,
    promptTokens: left.promptTokens + right.promptTokens,
    completionTokens: left.completionTokens + right.completionTokens,
    costUsd: left.costUsd + right.costUsd,
    elapsedMs: left.elapsedMs + right.elapsedMs,
  };
}

export interface CandidateRunIds {
  validationBase: number;
  validationCandidate: number;
  holdoutBase: number;
  holdoutCandidate: number;
}

export interface CandidateWindow {
  trainStart: string;
  trainEnd: string;
  validationStart: string;
  validationEnd: string;
  holdoutStart: string;
  holdoutEnd: string;
}

export type CandidateStatus =
  | "purging"
  | "validating"
  | "validation_failed"
  | "embargoed"
  | "holdout"
  | "awaiting_family"
  | "kept"
  | "reverted"
  | "error";

export interface TrajectoryStatistics {
  meanDelta: number;
  ciLower: number;
  ciUpper: number;
  pValue: number;
  effectiveSampleSize: number;
}

export interface ArmEvaluation {
  base: BacktestMetricsResult;
  candidate: BacktestMetricsResult;
  baseTurnover: number;
  candidateTurnover: number;
  paired: TrajectoryStatistics;
}

export interface EvolutionCandidate {
  id: string;
  familyId: string;
  versionId: number;
  agent: string;
  layer: Layer;
  triggerDate: string;
  triggerIndex: number;
  baseCommit: string;
  candidateCommit: string;
  candidatePromptSha256: string;
  branchName: string;
  window: CandidateWindow;
  runs: CandidateRunIds;
  baseArm: ArmCheckpoint;
  candidateArm: ArmCheckpoint;
  status: CandidateStatus;
  validation?: ArmEvaluation;
  holdout?: ArmEvaluation;
  adjustedQ?: number;
  reasonCodes: string[];
  usage: { base: LlmUsage; candidate: LlmUsage };
}

export interface PromptLineageEvent {
  date: string;
  agent: string;
  versionId: number;
  decision: "keep" | "revert";
  previousCommit: string;
  activeCommit: string;
  reasonCodes: string[];
}

export interface PendingEvolution {
  month: string;
  triggerIndex: number;
  triggerDate: string;
  completedLayers: Layer[];
}

export interface EvolutionCheckpoint {
  schemaVersion: typeof EVOLUTION_CHECKPOINT_SCHEMA;
  runId: string;
  cohort: string;
  startDate: string;
  endDate: string;
  nextTradingDayIndex: number;
  tradeDaysHash: string;
  mainBacktestRunId: number;
  activePromptCommit: string;
  activePromptSha256: string;
  activePromptBranch: string;
  mainArm: ArmCheckpoint;
  mainUsage: LlmUsage;
  candidates: EvolutionCandidate[];
  lineage: PromptLineageEvent[];
  processedEvolutionMonths: string[];
  layerRotation: Record<Layer, number>;
  pendingEvolution?: PendingEvolution;
  completedAt?: string;
}

export interface DailyJournal {
  schemaVersion: "mosaic.backtest_evolution_daily_journal.v1";
  tradingDayIndex: number;
  tradeDate: string;
  checkpointHash: string;
  writes: Array<{
    runId: number;
    actions: Array<{
      ticker: string;
      action: "BUY" | "SELL" | "HOLD" | "REDUCE";
      target_weight: number;
      holding_period?: string;
      dissent_notes?: string;
    }>;
  }>;
  mainArm: ArmCheckpoint;
  candidateArms: Record<string, { baseArm: ArmCheckpoint; candidateArm: ArmCheckpoint }>;
  usage: Record<string, LlmUsage>;
  scorecardState: Record<string, unknown>;
}

export function validateEvolutionPolicy(policy: EvolutionPolicy): void {
  for (const [key, value] of Object.entries(policy)) {
    if (!Number.isFinite(value) || value <= 0) {
      throw new Error(`evolution policy ${key} must be positive`);
    }
  }
  if (policy.familyAlpha >= 1) throw new Error("familyAlpha must be below 1");
  if (!Number.isInteger(policy.bootstrapSamples) || policy.bootstrapSamples < 100) {
    throw new Error("bootstrapSamples must be an integer >= 100");
  }
}

export function sha256Json(value: unknown): string {
  return `sha256:${createHash("sha256").update(canonicalJson(value)).digest("hex")}`;
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.entries(value as Record<string, unknown>)
      .filter(([, entry]) => entry !== undefined)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, entry]) => `${JSON.stringify(key)}:${canonicalJson(entry)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

export function isFirstTradingDayOfMonth(tradeDays: ReadonlyArray<string>, index: number): boolean {
  if (index < 0 || index >= tradeDays.length) return false;
  if (index === 0) return true;
  return tradeDays[index]?.slice(0, 7) !== tradeDays[index - 1]?.slice(0, 7);
}

export function shouldTriggerEvolution(
  tradeDays: ReadonlyArray<string>,
  index: number,
  processedMonths: ReadonlyArray<string>,
  policy = DEFAULT_EVOLUTION_POLICY,
): boolean {
  const date = tradeDays[index];
  if (!date || index < policy.warmupTradingDays || !isFirstTradingDayOfMonth(tradeDays, index)) {
    return false;
  }
  return !processedMonths.includes(date.slice(0, 7));
}

export function pendingEvolutionAfterCompletedDay(
  checkpoint: EvolutionCheckpoint,
  tradeDays: ReadonlyArray<string>,
  policy = DEFAULT_EVOLUTION_POLICY,
): PendingEvolution | null {
  if (checkpoint.pendingEvolution) return checkpoint.pendingEvolution;
  const triggerIndex = checkpoint.nextTradingDayIndex - 1;
  const triggerDate = tradeDays[triggerIndex];
  if (
    !triggerDate ||
    !shouldTriggerEvolution(tradeDays, triggerIndex, checkpoint.processedEvolutionMonths, policy)
  ) {
    return null;
  }
  return {
    month: triggerDate.slice(0, 7),
    triggerIndex,
    triggerDate,
    completedLayers: [],
  };
}

export function candidateWindow(
  tradeDays: ReadonlyArray<string>,
  triggerIndex: number,
  policy = DEFAULT_EVOLUTION_POLICY,
): CandidateWindow | null {
  validateEvolutionPolicy(policy);
  const trainEndIndex = triggerIndex;
  const trainStartIndex = trainEndIndex - policy.trainingTradingDays + 1;
  const validationStartIndex = triggerIndex + policy.purgeTradingDays + 1;
  const validationEndIndex = validationStartIndex + policy.validationTradingDays - 1;
  const holdoutStartIndex = validationEndIndex + policy.embargoTradingDays + 1;
  const holdoutEndIndex = holdoutStartIndex + policy.holdoutTradingDays - 1;
  if (trainStartIndex < 0 || holdoutEndIndex >= tradeDays.length) return null;
  const values = [
    tradeDays[trainStartIndex],
    tradeDays[trainEndIndex],
    tradeDays[validationStartIndex],
    tradeDays[validationEndIndex],
    tradeDays[holdoutStartIndex],
    tradeDays[holdoutEndIndex],
  ];
  if (values.some((value) => !value)) return null;
  return {
    trainStart: values[0] as string,
    trainEnd: values[1] as string,
    validationStart: values[2] as string,
    validationEnd: values[3] as string,
    holdoutStart: values[4] as string,
    holdoutEnd: values[5] as string,
  };
}

export function phaseForDate(candidate: EvolutionCandidate, date: string): CandidateStatus | null {
  if (["kept", "reverted", "validation_failed", "error"].includes(candidate.status)) return null;
  if (date >= candidate.window.validationStart && date <= candidate.window.validationEnd) {
    return "validating";
  }
  if (date > candidate.window.validationEnd && date < candidate.window.holdoutStart) {
    return "embargoed";
  }
  if (date >= candidate.window.holdoutStart && date <= candidate.window.holdoutEnd) {
    return "holdout";
  }
  return date < candidate.window.validationStart ? "purging" : null;
}

export function pendingLayer(candidates: ReadonlyArray<EvolutionCandidate>, layer: Layer): boolean {
  return candidates.some(
    (candidate) =>
      candidate.layer === layer &&
      !["kept", "reverted", "validation_failed", "error"].includes(candidate.status),
  );
}

export function selectLayerAgent(opts: {
  layer: Layer;
  macroSkill: ReadonlyArray<MacroSkillRow>;
  weights: DarwinianWeightTable;
  rotation: number;
}): string {
  const agents = [...AGENTS_BY_LAYER[opts.layer]];
  const score = (agent: string): number | null => {
    if (opts.layer === "macro") {
      return opts.macroSkill.find((row) => row.agent === agent)?.mean_raw_macro_score_5d ?? null;
    }
    return opts.weights[agent]?.sharpe_30 ?? null;
  };
  const scored = agents
    .map((agent) => ({ agent, score: score(agent) }))
    .filter((row) => row.score !== null)
    .map((row) => ({ agent: row.agent, score: row.score as number }))
    .sort((left, right) => left.score - right.score || left.agent.localeCompare(right.agent));
  if (scored.length > 0) return scored[0]?.agent as string;
  return agents[opts.rotation % agents.length] as string;
}

export function writeJsonAtomic(path: string, value: unknown): void {
  mkdirSync(dirname(path), { recursive: true });
  const temp = `${path}.tmp-${process.pid}`;
  writeFileSync(temp, `${JSON.stringify(value, null, 2)}\n`, "utf-8");
  renameSync(temp, path);
}

export function loadCheckpoint(path: string): EvolutionCheckpoint {
  const value = JSON.parse(readFileSync(path, "utf-8")) as EvolutionCheckpoint;
  if (value.schemaVersion !== EVOLUTION_CHECKPOINT_SCHEMA) {
    throw new Error(`unsupported evolution checkpoint schema: ${String(value.schemaVersion)}`);
  }
  if (!Number.isInteger(value.nextTradingDayIndex) || value.nextTradingDayIndex < 0) {
    throw new Error("evolution checkpoint has invalid nextTradingDayIndex");
  }
  return value;
}

function seedFromString(value: string): number {
  return Number.parseInt(createHash("sha256").update(value).digest("hex").slice(0, 8), 16);
}

function mulberry32(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state += 0x6d2b79f5;
    let value = state;
    value = Math.imul(value ^ (value >>> 15), value | 1);
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
    return ((value ^ (value >>> 14)) >>> 0) / 4_294_967_296;
  };
}

function quantile(sorted: ReadonlyArray<number>, probability: number): number {
  if (sorted.length === 0) return 0;
  const position = (sorted.length - 1) * probability;
  const lower = Math.floor(position);
  const upper = Math.ceil(position);
  const left = sorted[lower] as number;
  const right = sorted[upper] as number;
  return left + (right - left) * (position - lower);
}

export function pairedBlockBootstrap(opts: {
  baseReturns: ReadonlyArray<number>;
  candidateReturns: ReadonlyArray<number>;
  blockLength?: number;
  samples?: number;
  seed: string;
}): TrajectoryStatistics {
  if (opts.baseReturns.length !== opts.candidateReturns.length || opts.baseReturns.length === 0) {
    throw new Error("paired bootstrap requires equal non-empty return series");
  }
  const blockLength = opts.blockLength ?? DEFAULT_EVOLUTION_POLICY.blockLength;
  const samples = opts.samples ?? DEFAULT_EVOLUTION_POLICY.bootstrapSamples;
  if (!Number.isInteger(blockLength) || blockLength < 1) throw new Error("invalid block length");
  const differences = opts.candidateReturns.map(
    (value, index) => value - (opts.baseReturns[index] ?? 0),
  );
  const observed = differences.reduce((sum, value) => sum + value, 0) / differences.length;
  const random = mulberry32(seedFromString(opts.seed));
  const means: number[] = [];
  for (let sample = 0; sample < samples; sample += 1) {
    let sum = 0;
    let count = 0;
    while (count < differences.length) {
      const start = Math.floor(random() * differences.length);
      for (let offset = 0; offset < blockLength && count < differences.length; offset += 1) {
        sum += differences[(start + offset) % differences.length] as number;
        count += 1;
      }
    }
    means.push(sum / differences.length);
  }
  means.sort((left, right) => left - right);
  const nonPositive = means.filter((value) => value <= 0).length;
  return {
    meanDelta: observed,
    ciLower: quantile(means, 0.025),
    ciUpper: quantile(means, 0.975),
    pValue: (nonPositive + 1) / (means.length + 1),
    effectiveSampleSize: Math.floor(differences.length / blockLength),
  };
}

export function benjaminiHochberg(
  rows: ReadonlyArray<{ id: string; pValue: number }>,
): Record<string, number> {
  const sorted = [...rows].sort(
    (left, right) => left.pValue - right.pValue || left.id.localeCompare(right.id),
  );
  const adjusted: Record<string, number> = {};
  let running = 1;
  for (let index = sorted.length - 1; index >= 0; index -= 1) {
    const row = sorted[index] as { id: string; pValue: number };
    running = Math.min(running, (row.pValue * sorted.length) / (index + 1));
    adjusted[row.id] = Math.min(1, running);
  }
  return adjusted;
}

export function evaluationReasonCodes(
  evaluation: ArmEvaluation,
  opts: { adjustedQ?: number; policy?: EvolutionPolicy } = {},
): string[] {
  const policy = opts.policy ?? DEFAULT_EVOLUTION_POLICY;
  const reasons: string[] = [];
  if (evaluation.paired.ciLower <= 0) reasons.push("NET_ALPHA_CI_NOT_POSITIVE");
  if (evaluation.candidate.alpha <= evaluation.base.alpha) reasons.push("ALPHA_NOT_IMPROVED");
  if (evaluation.candidate.max_drawdown < evaluation.base.max_drawdown) {
    reasons.push("MAX_DRAWDOWN_WORSE");
  }
  const turnoverLimit = Math.max(1e-12, evaluation.baseTurnover) * policy.maxTurnoverRatio;
  if (evaluation.candidateTurnover > turnoverLimit) reasons.push("TURNOVER_GUARDRAIL");
  if (opts.adjustedQ !== undefined && opts.adjustedQ > policy.familyAlpha) {
    reasons.push("FDR_GATE_FAILED");
  }
  return reasons;
}

export function selectFamilyWinnerId(candidates: ReadonlyArray<EvolutionCandidate>): string | null {
  const passing = candidates
    .filter(
      (candidate) =>
        candidate.status === "awaiting_family" &&
        candidate.holdout !== undefined &&
        evaluationReasonCodes(
          candidate.holdout,
          candidate.adjustedQ === undefined ? {} : { adjustedQ: candidate.adjustedQ },
        ).length === 0,
    )
    .sort(
      (left, right) =>
        (left.adjustedQ ?? 1) - (right.adjustedQ ?? 1) ||
        (right.holdout?.paired.meanDelta ?? Number.NEGATIVE_INFINITY) -
          (left.holdout?.paired.meanDelta ?? Number.NEGATIVE_INFINITY) ||
        left.id.localeCompare(right.id),
    );
  return passing[0]?.id ?? null;
}
