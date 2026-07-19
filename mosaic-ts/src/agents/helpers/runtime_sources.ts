import { createHash } from "node:crypto";
import { AGENTS_BY_LAYER } from "../prompts/cohorts.js";
import type { RuntimeAgentStageId } from "../prompts/runtime_agent_spec.js";
import type { DailyCycleStateType } from "../state.js";
import type { RuntimeSourceStatus } from "./private_knot_boundary.js";

export function resolveRuntimeSourceStatusesForAgent(
  state: DailyCycleStateType,
  agentId: string,
  stage?: RuntimeAgentStageId,
): RuntimeSourceStatus[] {
  const cohort = state.active_cohort || "cohort_default";
  const runId = state.trace_id || state.as_of_date || "current_run";
  const asOf = state.as_of_date || undefined;
  const statuses: RuntimeSourceStatus[] = [];
  const runtime = state.layer4_outputs?.runtime;

  if (isDecisionAgent(agentId)) {
    const currentPositions = state.current_positions ?? {
      snapshot_status: "missing",
      positions: [],
    };
    const positionStatus =
      currentPositions.snapshot_status === "loaded"
        ? "loaded"
        : currentPositions.snapshot_status === "empty_confirmed"
          ? "empty_confirmed"
          : "missing";
    statuses.push(
      runtimeStatus(
        "current_position_snapshot",
        `account:default|cohort:${cohort}|run:${runId}`,
        positionStatus,
        asOf,
        {
          ...(currentPositions.position_snapshot_hash
            ? { snapshot_hash: currentPositions.position_snapshot_hash }
            : {}),
          ...(positionStatus === "missing"
            ? { error_code: currentPositions.source_error_code ?? "current_positions_missing" }
            : {}),
          producer_stage: "cycle_input",
          ...(stage ? { resolved_at_stage: stage } : {}),
          adapter_id: "portfolio.current_positions_adapter.v1",
        },
      ),
    );
    if (agentId === "alpha_discovery" || (agentId === "cio" && stage === "cio_proposal")) {
      statuses.push(
        ...upstreamOutputStatuses(state, cohort, runId, asOf, {
          includeAlphaDiscovery: agentId === "cio",
        }),
      );
    }
    if (agentId === "cio" && stage === "cio_proposal") {
      const previousTarget = state.layer4_outputs?.previous_target_state;
      statuses.push(
        previousTarget
          ? runtimeStatus(
              "previous_target_state",
              `account:default|cohort:${cohort}`,
              previousTarget.snapshot_status,
              previousTarget.as_of_date ?? asOf,
              {
                ...(previousTarget.final_target_hash
                  ? { snapshot_hash: previousTarget.final_target_hash }
                  : {}),
                ...(previousTarget.source_error_code
                  ? { error_code: previousTarget.source_error_code }
                  : {}),
                producer_stage: "cycle_input",
                ...(stage ? { resolved_at_stage: stage } : {}),
                adapter_id: "portfolio.previous_target_adapter.v1",
              },
            )
          : runtimeStatus(
              "previous_target_state",
              `account:default|cohort:${cohort}`,
              "missing",
              asOf,
              {
                error_code: "previous_target_state_adapter_not_resolved",
                ...(stage ? { resolved_at_stage: stage } : {}),
                adapter_id: "portfolio.previous_target_adapter.v1",
              },
            ),
      );
    }
    const marketScopes = scopedTickers(decisionMarketTickers(state, agentId, stage));
    if (marketScopes.length === 0) {
      statuses.push(
        currentPositions.snapshot_status === "missing"
          ? runtimeStatus("current_market_data", "ticker_scope:unknown", "missing", asOf, {
              error_code: "current_market_data_unresolved_without_positions",
              ...(stage ? { resolved_at_stage: stage } : {}),
              adapter_id: "market.scoped_snapshot_adapter.v1",
            })
          : runtimeStatus("current_market_data", "ticker_scope:empty", "empty_confirmed", asOf, {
              error_code: "current_market_data_scope_empty",
              ...(stage ? { resolved_at_stage: stage } : {}),
              adapter_id: "market.scoped_snapshot_adapter.v1",
            }),
      );
    } else {
      for (const scope of marketScopes) {
        const resolved = runtime?.resolved_source_statuses?.find(
          (status) => status.source_id === "current_market_data" && status.scope === scope,
        );
        statuses.push(
          resolved ??
            runtimeStatus("current_market_data", scope, "missing", asOf, {
              error_code: "current_market_data_adapter_not_resolved",
            }),
        );
      }
    }
    if (
      agentId === "cio" &&
      stage === "cio_proposal" &&
      currentPositions.snapshot_status === "loaded"
    ) {
      for (const position of currentPositions.positions) {
        statuses.push(
          runtimeStatus("position_thesis_state", `ticker:${position.ticker}`, "loaded", asOf, {
            snapshot_hash: stableHash({
              entry_thesis_id: position.entry_thesis_id,
              last_review_date: position.last_review_date,
              ticker: position.ticker,
            }),
            producer_stage: "cycle_input",
            ...(stage ? { resolved_at_stage: stage } : {}),
            adapter_id: "portfolio.position_thesis_adapter.v1",
          }),
        );
      }
    }
  }
  if (agentId === "cro") {
    statuses.push(
      frozenSourceStatus(
        "candidate_target_state",
        `account:default|cohort:${cohort}|run:${runId}`,
        runtime?.candidate_target_state?.candidate_target_hash,
        asOf,
      ),
      frozenSourceStatus(
        "position_review_state",
        `account:default|cohort:${cohort}|run:${runId}`,
        runtime?.position_review_state?.position_review_hash,
        asOf,
      ),
      frozenSourceStatus(
        "portfolio_exposure_state",
        `account:default|cohort:${cohort}|run:${runId}`,
        runtime?.portfolio_exposure_state?.exposure_hash,
        asOf,
      ),
    );
  }
  if (agentId === "autonomous_execution") {
    statuses.push(
      frozenSourceStatus(
        "candidate_target_state",
        `account:default|cohort:${cohort}|run:${runId}`,
        runtime?.candidate_target_state?.candidate_target_hash,
        asOf,
      ),
      frozenSourceStatus(
        "cro_review_state",
        `account:default|cohort:${cohort}|run:${runId}|candidate:${runtime?.candidate_target_state?.candidate_target_hash ?? "missing"}`,
        runtime?.cro_review_state?.review_hash,
        asOf,
      ),
    );
    const liquidityScopes = scopedTickers(
      (runtime?.candidate_target_state?.portfolio_actions ?? [])
        .filter((action) => action.action !== "HOLD" || (action.delta_weight ?? 0) !== 0)
        .map((action) => action.ticker),
    );
    if (liquidityScopes.length === 0) {
      statuses.push(
        runtimeStatus("execution_liquidity_state", "ticker_scope:empty", "empty_confirmed", asOf, {
          error_code: "execution_liquidity_scope_empty",
          ...(stage ? { resolved_at_stage: stage } : {}),
          adapter_id: "execution.liquidity_adapter.v1",
        }),
      );
    } else {
      for (const scope of liquidityScopes) {
        const resolved = runtime?.resolved_source_statuses?.find(
          (status) => status.source_id === "execution_liquidity_state" && status.scope === scope,
        );
        statuses.push(
          resolved ??
            runtimeStatus("execution_liquidity_state", scope, "missing", asOf, {
              error_code: "execution_liquidity_adapter_not_resolved",
              ...(stage ? { resolved_at_stage: stage } : {}),
              adapter_id: "execution.liquidity_adapter.v1",
            }),
        );
      }
    }
  }
  if (agentId === "cio" && stage === "cio_final") {
    statuses.push(
      frozenSourceStatus(
        "candidate_target_state",
        `account:default|cohort:${cohort}|run:${runId}`,
        runtime?.candidate_target_state?.candidate_target_hash,
        asOf,
      ),
      frozenSourceStatus(
        "position_review_state",
        `account:default|cohort:${cohort}|run:${runId}`,
        runtime?.position_review_state?.position_review_hash,
        asOf,
      ),
      frozenSourceStatus(
        "cro_review_state",
        `account:default|cohort:${cohort}|run:${runId}|candidate:${runtime?.candidate_target_state?.candidate_target_hash ?? "missing"}`,
        runtime?.cro_review_state?.review_hash,
        asOf,
      ),
      frozenSourceStatus(
        "execution_feasibility_state",
        `account:default|cohort:${cohort}|run:${runId}|candidate:${runtime?.candidate_target_state?.candidate_target_hash ?? "missing"}`,
        runtime?.execution_feasibility_state?.feasibility_hash,
        asOf,
      ),
    );
  }
  return statuses;
}

function frozenSourceStatus(
  sourceId: string,
  scope: string,
  snapshotHash: string | undefined,
  asOf: string | undefined,
): RuntimeSourceStatus {
  return runtimeStatus(
    sourceId,
    scope,
    snapshotHash ? "loaded" : "missing",
    asOf,
    snapshotHash ? { snapshot_hash: snapshotHash } : { error_code: `${sourceId}_missing` },
  );
}

function runtimeStatus(
  source_id: string,
  scope: string,
  status: RuntimeSourceStatus["status"],
  as_of?: string,
  extra: Pick<
    RuntimeSourceStatus,
    "snapshot_hash" | "error_code" | "producer_stage" | "resolved_at_stage" | "adapter_id"
  > = {},
): RuntimeSourceStatus {
  return {
    source_id,
    scope,
    status,
    ...(as_of ? { as_of } : {}),
    ...(extra.snapshot_hash ? { snapshot_hash: extra.snapshot_hash } : {}),
    ...(extra.error_code ? { error_code: extra.error_code } : {}),
    ...(extra.producer_stage ? { producer_stage: extra.producer_stage } : {}),
    ...(extra.resolved_at_stage ? { resolved_at_stage: extra.resolved_at_stage } : {}),
    ...(extra.adapter_id ? { adapter_id: extra.adapter_id } : {}),
  };
}

function isDecisionAgent(agentId: string): boolean {
  return ["cro", "alpha_discovery", "autonomous_execution", "cio"].includes(agentId);
}

function upstreamOutputStatuses(
  state: DailyCycleStateType,
  cohort: string,
  runId: string,
  asOf: string | undefined,
  opts: { includeAlphaDiscovery: boolean },
): RuntimeSourceStatus[] {
  const outputs: Record<string, unknown> = {
    ...state.layer1_outputs,
    ...state.layer2_outputs,
    ...state.layer3_outputs,
    ...(opts.includeAlphaDiscovery
      ? { alpha_discovery: state.layer4_outputs?.alpha_discovery }
      : {}),
  };
  const agents = [
    ...AGENTS_BY_LAYER.macro,
    ...AGENTS_BY_LAYER.sector,
    ...AGENTS_BY_LAYER.superinvestor,
    ...(opts.includeAlphaDiscovery ? ["alpha_discovery"] : []),
  ];
  return agents.map((agent) => {
    const output = outputs[agent];
    const outputStatus = upstreamOutputStatus(agent, output);
    const extra: Pick<
      RuntimeSourceStatus,
      "snapshot_hash" | "error_code" | "producer_stage" | "adapter_id"
    > = output
      ? {
          snapshot_hash: stableHash(output),
          ...(outputStatus.error_code ? { error_code: outputStatus.error_code } : {}),
          producer_stage: agent === "alpha_discovery" ? "alpha_discovery" : "agent_run",
          adapter_id: "daily_cycle.agent_output_adapter.v1",
        }
      : {
          error_code: outputStatus.error_code ?? `upstream_agent_output_missing:${agent}`,
          producer_stage: agent === "alpha_discovery" ? "alpha_discovery" : "agent_run",
          adapter_id: "daily_cycle.agent_output_adapter.v1",
        };
    return runtimeStatus(
      "upstream_agent_outputs",
      `agent:${agent}|cohort:${cohort}|run:${runId}`,
      outputStatus.status,
      asOf,
      extra,
    );
  });
}

function decisionMarketTickers(
  state: DailyCycleStateType,
  agentId: string,
  stage: RuntimeAgentStageId | undefined,
): string[] {
  const current = state.current_positions.positions.map((position) => position.ticker);
  if (agentId === "alpha_discovery" || (agentId === "cio" && stage === "cio_proposal")) {
    const layer2 = Object.values(state.layer2_outputs).flatMap((output) =>
      output.agent !== "relationship_mapper"
        ? [
            ...output.long_picks.map((pick) => pick.ts_code),
            ...output.short_or_avoid_picks.map((pick) => pick.ts_code),
          ]
        : [],
    );
    const layer3 = Object.values(state.layer3_outputs).flatMap((output) =>
      output.picks.map((pick) => pick.ts_code),
    );
    const alpha =
      agentId === "cio"
        ? (state.layer4_outputs?.alpha_discovery?.novel_picks.map((pick) => pick.ticker) ?? [])
        : [];
    return [...current, ...layer2, ...layer3, ...alpha];
  }
  return [
    ...current,
    ...(state.layer4_outputs?.runtime?.candidate_target_state?.portfolio_actions ?? []).map(
      (action) => action.ticker,
    ),
  ];
}

function upstreamOutputStatus(
  agent: string,
  output: unknown,
): Pick<RuntimeSourceStatus, "status" | "error_code"> {
  if (!output) {
    return {
      status: "missing",
      error_code: `upstream_agent_output_missing:${agent}`,
    };
  }
  if (output === null || typeof output !== "object" || Array.isArray(output)) {
    return {
      status: "source_error",
      error_code: `upstream_agent_output_invalid:${agent}`,
    };
  }
  const record = output as Record<string, unknown>;
  const confidence = record.confidence;
  if (typeof confidence === "number" && Number.isFinite(confidence) && confidence <= 0.05) {
    return {
      status: "source_error",
      error_code: `upstream_agent_output_low_confidence:${agent}`,
    };
  }
  return { status: "loaded" };
}

function scopedTickers(tickers: ReadonlyArray<string>): string[] {
  return [...new Set(tickers.filter((ticker) => ticker.trim().length > 0))].map(
    (ticker) => `ticker:${ticker}`,
  );
}

function stableHash(value: unknown): string {
  return `sha256:${createHash("sha256")
    .update(JSON.stringify(sortJson(value)))
    .digest("hex")}`;
}

function sortJson(value: unknown): unknown {
  if (Array.isArray(value)) return value.map((item) => sortJson(item));
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, sortJson(item)]),
    );
  }
  return value;
}
