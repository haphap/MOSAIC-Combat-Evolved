import { createHash } from "node:crypto";
import type { BridgeApi } from "../../bridge/index.js";
import type { DailyCycleStateType } from "../state.js";
import type { RuntimeSourceEvidenceObservation, RuntimeSourceStatus } from "./research_knobs.js";

export type Layer4SourceResolutionStage =
  | "pre_candidate"
  | "candidate_market"
  | "execution_liquidity";

const MARKET_ADAPTER_ID = "market.scoped_snapshot_adapter.v1";
const LIQUIDITY_ADAPTER_ID = "execution.liquidity_adapter.v1";

export interface Layer4SourceResolutionBundle {
  statuses: RuntimeSourceStatus[];
  evidence: RuntimeSourceEvidenceObservation[];
}

export async function resolveLayer4SourceStatuses(
  state: DailyCycleStateType,
  stage: Layer4SourceResolutionStage,
  api?: Pick<BridgeApi, "toolsCall">,
): Promise<RuntimeSourceStatus[]> {
  return (await resolveLayer4SourceBundle(state, stage, api)).statuses;
}

export async function resolveLayer4SourceBundle(
  state: DailyCycleStateType,
  stage: Layer4SourceResolutionStage,
  api?: Pick<BridgeApi, "toolsCall">,
): Promise<Layer4SourceResolutionBundle> {
  const asOf = state.as_of_date || new Date().toISOString().slice(0, 10);
  const sourceId =
    stage === "execution_liquidity" ? "execution_liquidity_state" : "current_market_data";
  const adapterId = stage === "execution_liquidity" ? LIQUIDITY_ADAPTER_ID : MARKET_ADAPTER_ID;
  const tickers =
    stage === "pre_candidate" ? preCandidateTickers(state) : frozenCandidateTickers(state);
  const existing = state.layer4_outputs?.runtime?.resolved_source_statuses ?? [];
  const frozenBaseSources = new Set(
    Object.keys(
      state.layer4_outputs?.runtime?.l4_run_snapshot_bundle?.base_market_source_hashes ?? {},
    ),
  );
  const unresolved = tickers.filter(
    (ticker) =>
      !frozenBaseSources.has(`${sourceId}|ticker:${ticker}`) &&
      !existing.some(
        (status) =>
          status.source_id === sourceId &&
          status.scope === `ticker:${ticker}` &&
          status.status === "loaded" &&
          status.as_of === asOf,
      ),
  );
  const additions = await mapWithConcurrency(unresolved, 4, (ticker) =>
    resolveTickerSource({ api, state, ticker, asOf, sourceId, adapterId, stage }),
  );
  return {
    statuses: mergeRuntimeSourceStatuses(
      existing,
      additions.map((addition) => addition.status),
    ),
    evidence: mergeRuntimeSourceEvidence(
      state.layer4_outputs?.runtime?.source_evidence_observations ?? [],
      additions.flatMap((addition) => (addition.evidence ? [addition.evidence] : [])),
    ),
  };
}

export function mergeRuntimeSourceStatuses(
  current: ReadonlyArray<RuntimeSourceStatus>,
  additions: ReadonlyArray<RuntimeSourceStatus>,
): RuntimeSourceStatus[] {
  const merged = new Map(current.map((status) => [statusKey(status), status]));
  for (const status of additions) merged.set(statusKey(status), status);
  return [...merged.values()].sort((left, right) =>
    statusKey(left).localeCompare(statusKey(right)),
  );
}

export function mergeRuntimeSourceEvidence(
  current: ReadonlyArray<RuntimeSourceEvidenceObservation>,
  additions: ReadonlyArray<RuntimeSourceEvidenceObservation>,
): RuntimeSourceEvidenceObservation[] {
  const merged = new Map(current.map((entry) => [evidenceKey(entry), entry]));
  for (const entry of additions) merged.set(evidenceKey(entry), entry);
  return [...merged.values()].sort((left, right) =>
    evidenceKey(left).localeCompare(evidenceKey(right)),
  );
}

function preCandidateTickers(state: DailyCycleStateType): string[] {
  const tickers = [
    ...state.current_positions.positions.map((position) => position.ticker),
    ...Object.values(state.layer2_outputs).flatMap((output) =>
      "longs" in output
        ? [...output.longs.map((pick) => pick.ticker), ...output.shorts.map((pick) => pick.ticker)]
        : [],
    ),
    ...Object.values(state.layer3_outputs).flatMap((output) =>
      output.picks.map((pick) => pick.ticker),
    ),
    ...(state.layer4_outputs?.alpha_discovery?.novel_picks.map((pick) => pick.ticker) ?? []),
  ];
  return uniqueTickers(tickers);
}

function frozenCandidateTickers(state: DailyCycleStateType): string[] {
  return uniqueTickers(
    (
      state.layer4_outputs?.runtime?.candidate_target_state?.portfolio_actions ??
      state.layer4_outputs?.runtime?.cio_proposal?.portfolio_actions ??
      []
    ).map((action) => action.ticker),
  );
}

async function resolveTickerSource(opts: {
  api: Pick<BridgeApi, "toolsCall"> | undefined;
  state: DailyCycleStateType;
  ticker: string;
  asOf: string;
  sourceId: string;
  adapterId: string;
  stage: Layer4SourceResolutionStage;
}): Promise<{
  status: RuntimeSourceStatus;
  evidence: RuntimeSourceEvidenceObservation | null;
}> {
  const common = {
    source_id: opts.sourceId,
    scope: `ticker:${opts.ticker}`,
    as_of: opts.asOf,
    producer_stage: "pre_stage_source_resolution",
    resolved_at_stage: opts.stage,
    adapter_id: opts.adapterId,
  } satisfies Partial<RuntimeSourceStatus> & Pick<RuntimeSourceStatus, "source_id" | "scope">;
  if (!opts.api) {
    return {
      status: {
        ...common,
        status: "source_error",
        error_code: `${opts.sourceId}_adapter_unavailable`,
      },
      evidence: null,
    };
  }
  const args = {
    symbol: opts.ticker,
    start_date: shiftIsoDate(opts.asOf, -10),
    end_date: opts.asOf,
  };
  try {
    const result = await opts.api.toolsCall(
      "get_stock_data",
      args,
      opts.state.mode === "backtest"
        ? { mode: "backtest", as_of_date: opts.asOf }
        : { mode: "live", as_of_date: opts.asOf },
    );
    const text = result.text.trim();
    if (text.length === 0 || /(?:no data|no rows|not found|empty result|无数据)/i.test(text)) {
      return {
        status: { ...common, status: "missing", error_code: `${opts.sourceId}_empty_result` },
        evidence: null,
      };
    }
    const normalized = parseLatestMarketRecord(text);
    if (!normalized) {
      return {
        status: {
          ...common,
          status: "source_error",
          error_code: `${opts.sourceId}_schema_unparseable`,
        },
        evidence: null,
      };
    }
    const observedAsOf = normalized.asOf;
    if (observedAsOf > opts.asOf) {
      return {
        status: { ...common, status: "source_error", error_code: `${opts.sourceId}_lookahead` },
        evidence: null,
      };
    }
    const snapshot_hash = stableHash({
      adapter_id: opts.adapterId,
      args,
      observed_as_of: observedAsOf,
      response_hash: stableHash(text),
    });
    const stale = observedAsOf !== opts.asOf;
    const status: RuntimeSourceStatus = stale
      ? {
          ...common,
          status: "stale",
          as_of: observedAsOf,
          snapshot_hash,
          error_code: `${opts.sourceId}_not_current_for_run_date`,
        }
      : { ...common, status: "loaded", as_of: observedAsOf, snapshot_hash };
    return {
      status,
      evidence: {
        source_id: opts.sourceId,
        scope: `ticker:${opts.ticker}`,
        metric: opts.sourceId,
        value: normalized.value,
        unit: "market_record",
        as_of: observedAsOf,
        lookback: "10d",
        freshness: stale ? "stale" : "current",
        source_fingerprint: snapshot_hash,
        direction: "ambiguous",
        privacy_class: "private_runtime",
        adapter_id: opts.adapterId,
        adapter_version: "1",
      },
    };
  } catch {
    return {
      status: { ...common, status: "source_error", error_code: `${opts.sourceId}_tool_failed` },
      evidence: null,
    };
  }
}

export function parseLatestMarketRecord(
  text: string,
): { asOf: string; value: Record<string, string | number | null> } | null {
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  for (let headerIndex = 0; headerIndex < lines.length; headerIndex++) {
    const header = parseCsvLine(lines[headerIndex] ?? "");
    const dateIndex = header.findIndex((field) =>
      ["date", "trade_date", "datetime", "timestamp"].includes(field.trim().toLowerCase()),
    );
    if (dateIndex < 0) continue;
    const records = lines
      .slice(headerIndex + 1)
      .map((line) => parseCsvLine(line))
      .filter((row) => row.length === header.length)
      .flatMap((row) => {
        const asOf = normalizeObservedDate(row[dateIndex] ?? "");
        if (!asOf) return [];
        const value = Object.fromEntries(
          header.map((field, index) => [field.trim(), parseScalar(row[index] ?? "")]),
        );
        return [{ asOf, value }];
      })
      .sort((left, right) => left.asOf.localeCompare(right.asOf));
    return records.at(-1) ?? null;
  }
  return null;
}

function parseCsvLine(line: string): string[] {
  const fields: string[] = [];
  let current = "";
  let quoted = false;
  for (let index = 0; index < line.length; index++) {
    const char = line[index];
    if (char === '"') {
      if (quoted && line[index + 1] === '"') {
        current += '"';
        index++;
      } else {
        quoted = !quoted;
      }
    } else if (char === "," && !quoted) {
      fields.push(current);
      current = "";
    } else {
      current += char;
    }
  }
  fields.push(current);
  return fields;
}

function normalizeObservedDate(value: string): string | null {
  const trimmed = value.trim();
  const match = trimmed.match(/^(\d{4})-?(\d{2})-?(\d{2})/);
  if (!match) return null;
  const normalized = `${match[1]}-${match[2]}-${match[3]}`;
  return Number.isNaN(Date.parse(`${normalized}T00:00:00Z`)) ? null : normalized;
}

function parseScalar(value: string): string | number | null {
  const trimmed = value.trim();
  if (trimmed === "") return null;
  if (/^-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$/.test(trimmed)) {
    const numeric = Number(trimmed);
    if (Number.isFinite(numeric)) return numeric;
  }
  return trimmed;
}

function shiftIsoDate(value: string, days: number): string {
  const date = new Date(`${value}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function uniqueTickers(tickers: ReadonlyArray<string>): string[] {
  return [...new Set(tickers.map((ticker) => ticker.trim()).filter(Boolean))].sort();
}

function statusKey(status: Pick<RuntimeSourceStatus, "source_id" | "scope">): string {
  return `${status.source_id}\u0000${status.scope}`;
}

function evidenceKey(
  evidence: Pick<RuntimeSourceEvidenceObservation, "source_id" | "scope" | "metric">,
): string {
  return `${evidence.source_id}\u0000${evidence.scope}\u0000${evidence.metric}`;
}

function stableHash(value: unknown): string {
  return `sha256:${createHash("sha256").update(JSON.stringify(value)).digest("hex")}`;
}

async function mapWithConcurrency<T, U>(
  values: ReadonlyArray<T>,
  concurrency: number,
  fn: (value: T) => Promise<U>,
): Promise<U[]> {
  const results = new Array<U>(values.length);
  let index = 0;
  async function worker(): Promise<void> {
    while (index < values.length) {
      const current = index;
      index += 1;
      const value = values[current];
      if (value !== undefined) results[current] = await fn(value);
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, values.length) }, () => worker()));
  return results;
}
