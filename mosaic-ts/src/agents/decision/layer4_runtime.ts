import { createHash } from "node:crypto";
import type { RuntimeSourceStatus } from "../helpers/research_knobs.js";
import type { DailyCycleStateType } from "../state.js";
import type {
  AutoExecOutput,
  CandidateTargetState,
  CioOutput,
  CroOutput,
  CroReviewState,
  CurrentPosition,
  ExecutionFeasibilityState,
  FinalTargetState,
  Layer4RuntimeState,
  Layer4RuntimeTraceEntry,
  PortfolioAction,
  PortfolioExposureState,
  PositionReview,
  PositionReviewState,
} from "../types.js";

export class Layer4RuntimeContractError extends Error {}

export function emptyLayer4RuntimeState(): Layer4RuntimeState {
  return {
    cio_proposal: null,
    candidate_target_state: null,
    position_review_state: null,
    portfolio_exposure_state: null,
    cro_review_state: null,
    execution_feasibility_state: null,
    final_target_state: null,
    cio_final_knob_snapshot: null,
    resolved_source_statuses: [],
    stage_trace: [],
  };
}

export function runtimeStateForLayer4(state: DailyCycleStateType): Layer4RuntimeState {
  return state.layer4_outputs.runtime ?? emptyLayer4RuntimeState();
}

export function freezeCioProposal(
  state: DailyCycleStateType,
  proposal: CioOutput,
): {
  proposal: CioOutput;
  candidate: CandidateTargetState;
  reviews: PositionReviewState;
  exposure: PortfolioExposureState;
} {
  const runId = state.trace_id || state.as_of_date || "current_run";
  const cohort = state.active_cohort || "cohort_default";
  const asOfDate = state.as_of_date || "live";
  const llmActions = proposal.portfolio_actions.map((action) => ({
    ...action,
    review_source: "llm" as const,
  }));
  const actions = appendFallbackHolds(llmActions, state.current_positions.positions);
  const frozenProposal: CioOutput = { ...proposal, portfolio_actions: actions };
  const proposalHash = stableHash(proposal);
  const candidatePayload = {
    run_id: runId,
    cohort,
    as_of_date: asOfDate,
    proposal_hash: proposalHash,
    position_snapshot_hash: state.current_positions.position_snapshot_hash ?? null,
    market_data_vintage_hash: runtimeSourceVintageHash(
      state.layer4_outputs.runtime?.resolved_source_statuses ?? [],
      "current_market_data",
      actions.map((action) => action.ticker),
      asOfDate,
    ),
    portfolio_actions: actions,
    confidence: proposal.confidence,
  };
  const candidate: CandidateTargetState = {
    schema_version: "portfolio.candidate_target_state.v1",
    ...candidatePayload,
    candidate_target_hash: stableHash(candidatePayload),
    frozen: true,
  };
  const positionReviews = buildPositionReviewState(
    runId,
    candidate.candidate_target_hash,
    actions,
    state.current_positions.positions,
    proposal.confidence,
  );
  return {
    proposal: frozenProposal,
    candidate,
    reviews: positionReviews,
    exposure: buildPortfolioExposureState(candidate, state.current_positions.positions),
  };
}

export function freezeCroReview(
  runId: string,
  candidate: CandidateTargetState | null,
  output: CroOutput,
): CroReviewState {
  if (!candidate) {
    throw new Layer4RuntimeContractError("cro_review requires frozen candidate_target_state");
  }
  const payload = {
    run_id: runId,
    candidate_target_hash: candidate.candidate_target_hash,
    output,
  };
  return {
    schema_version: "decision.cro_review_state.v1",
    ...payload,
    review_hash: stableHash(payload),
    frozen: true,
  };
}

export function freezeExecutionFeasibility(
  runId: string,
  candidate: CandidateTargetState | null,
  croReview: CroReviewState | null,
  output: AutoExecOutput,
  sourceStatuses: ReadonlyArray<RuntimeSourceStatus> = [],
  asOfDate = "live",
): ExecutionFeasibilityState {
  if (!candidate || !croReview) {
    throw new Layer4RuntimeContractError(
      "execution_feasibility requires frozen candidate_target_state and cro_review_state",
    );
  }
  if (croReview.candidate_target_hash !== candidate.candidate_target_hash) {
    throw new Layer4RuntimeContractError("execution_feasibility candidate hash mismatch");
  }
  const payload = {
    run_id: runId,
    candidate_target_hash: candidate.candidate_target_hash,
    cro_review_hash: croReview.review_hash,
    liquidity_vintage_hash: runtimeSourceVintageHash(
      sourceStatuses,
      "execution_liquidity_state",
      candidate.portfolio_actions
        .filter((action) => action.action !== "HOLD" || (action.delta_weight ?? 0) !== 0)
        .map((action) => action.ticker),
      asOfDate,
    ),
    output,
  };
  return {
    schema_version: "decision.execution_feasibility_state.v1",
    ...payload,
    feasibility_hash: stableHash(payload),
    frozen: true,
  };
}

export function freezeFinalTarget(
  state: DailyCycleStateType,
  output: CioOutput,
  validatorHashes: ReadonlyArray<string>,
): FinalTargetState {
  const runtime = runtimeStateForLayer4(state);
  const candidate = runtime.candidate_target_state;
  const croReview = runtime.cro_review_state;
  const execution = runtime.execution_feasibility_state;
  if (!candidate || !croReview || !execution) {
    throw new Layer4RuntimeContractError(
      "final_target_state requires candidate, CRO review, and execution feasibility",
    );
  }
  if (
    croReview.candidate_target_hash !== candidate.candidate_target_hash ||
    execution.candidate_target_hash !== candidate.candidate_target_hash ||
    execution.cro_review_hash !== croReview.review_hash
  ) {
    throw new Layer4RuntimeContractError("final_target_state cross-stage hash mismatch");
  }
  const payload = {
    run_id: state.trace_id || state.as_of_date || "current_run",
    cohort: state.active_cohort || "cohort_default",
    as_of_date: state.as_of_date || "live",
    candidate_target_hash: candidate.candidate_target_hash,
    cro_review_hash: croReview.review_hash,
    execution_feasibility_hash: execution.feasibility_hash,
    position_snapshot_hash: state.current_positions.position_snapshot_hash ?? null,
    market_data_vintage_hash: candidate.market_data_vintage_hash,
    liquidity_vintage_hash: execution.liquidity_vintage_hash,
    portfolio_actions: output.portfolio_actions,
    confidence: output.confidence,
    validator_hashes: [...validatorHashes].sort(),
  };
  return {
    schema_version: "portfolio.final_target_state.v1",
    ...payload,
    final_target_hash: stableHash(payload),
    frozen: true,
  };
}

export function withFrozenCandidatePositionCoverage(
  state: DailyCycleStateType,
  output: CioOutput,
): CioOutput {
  if (state.current_positions.snapshot_status !== "loaded") return output;
  const candidateActions = new Map(
    (state.layer4_outputs.runtime?.candidate_target_state?.portfolio_actions ?? []).map(
      (action) => [action.ticker, action],
    ),
  );
  const covered = new Set(output.portfolio_actions.map((action) => action.ticker));
  const missing = state.current_positions.positions
    .filter((position) => !covered.has(position.ticker))
    .map((position) => candidateActions.get(position.ticker))
    .filter((action): action is PortfolioAction => action !== undefined);
  if (missing.length === 0) return output;
  return { ...output, portfolio_actions: [...output.portfolio_actions, ...missing] };
}

export function updateLayer4Runtime(
  current: Layer4RuntimeState,
  update: Partial<Omit<Layer4RuntimeState, "stage_trace">>,
  trace: Omit<Layer4RuntimeTraceEntry, "sequence">,
): Layer4RuntimeState {
  return {
    ...current,
    ...update,
    stage_trace: [...current.stage_trace, { ...trace, sequence: current.stage_trace.length + 1 }],
  };
}

export function stableRuntimeHash(value: unknown): string {
  return stableHash(value);
}

export function runtimeSourceVintageHash(
  statuses: ReadonlyArray<RuntimeSourceStatus>,
  sourceId: string,
  tickers: ReadonlyArray<string>,
  asOfDate: string,
): string {
  const scopes = [...new Set(tickers)].sort().map((ticker) => {
    const scope = `ticker:${ticker}`;
    const status = statuses.find((item) => item.source_id === sourceId && item.scope === scope);
    return status
      ? {
          source_id: sourceId,
          scope,
          status: status.status,
          as_of: status.as_of ?? null,
          snapshot_hash: status.snapshot_hash ?? null,
          error_code: status.error_code ?? null,
          adapter_id: status.adapter_id ?? null,
        }
      : {
          source_id: sourceId,
          scope,
          status: "missing",
          as_of: null,
          snapshot_hash: null,
          error_code: `${sourceId}_adapter_not_resolved`,
          adapter_id: null,
        };
  });
  return stableHash({ source_id: sourceId, as_of_date: asOfDate, scopes });
}

function appendFallbackHolds(
  actions: ReadonlyArray<PortfolioAction>,
  positions: ReadonlyArray<CurrentPosition>,
): PortfolioAction[] {
  const covered = new Set(actions.map((action) => action.ticker));
  return [
    ...actions,
    ...positions
      .filter((position) => !covered.has(position.ticker))
      .map(
        (position): PortfolioAction => ({
          ticker: position.ticker,
          action: "HOLD",
          ...(position.sector ? { sector: position.sector } : {}),
          position_decision: "HOLD",
          current_weight: position.current_weight,
          target_weight: position.current_weight,
          delta_weight: 0,
          holding_period: "1M",
          position_decision_reason:
            "position omitted by CIO proposal; runtime preserved current target",
          thesis_status: "intact",
          risk_flags: ["position_review_missing"],
          dissent_notes: "",
          review_source: "runtime_safety_fallback",
        }),
      ),
  ];
}

function buildPositionReviewState(
  runId: string,
  candidateTargetHash: string,
  actions: ReadonlyArray<PortfolioAction>,
  positions: ReadonlyArray<CurrentPosition>,
  confidence: number,
): PositionReviewState {
  const currentTickers = new Set(positions.map((position) => position.ticker));
  const reviews = actions
    .filter((action) => currentTickers.has(action.ticker))
    .map(
      (action): PositionReview => ({
        ticker: action.ticker,
        decision: action.position_decision ?? inferPositionDecision(action),
        target_weight: action.target_weight,
        reason: action.position_decision_reason ?? "position target supplied without review reason",
        thesis_status: action.thesis_status ?? "weakened",
        risk_flags: [...(action.risk_flags ?? [])],
        confidence: action.review_source === "runtime_safety_fallback" ? 0 : confidence,
        review_source: action.review_source ?? "llm",
      }),
    );
  const llmReviewedTickers = reviews
    .filter((review) => review.review_source === "llm")
    .map((review) => review.ticker)
    .sort();
  const fallbackTickers = reviews
    .filter((review) => review.review_source === "runtime_safety_fallback")
    .map((review) => review.ticker)
    .sort();
  const payload = {
    run_id: runId,
    candidate_target_hash: candidateTargetHash,
    reviews,
    llm_reviewed_tickers: llmReviewedTickers,
    fallback_tickers: fallbackTickers,
  };
  return {
    schema_version: "portfolio.position_review_state.v1",
    ...payload,
    position_review_hash: stableHash(payload),
    frozen: true,
  };
}

function buildPortfolioExposureState(
  candidate: CandidateTargetState,
  positions: ReadonlyArray<CurrentPosition>,
): PortfolioExposureState {
  const sectors = new Map(positions.map((position) => [position.ticker, position.sector]));
  const tickerWeights: Record<string, number> = {};
  const sectorWeights: Record<string, number> = {};
  for (const action of candidate.portfolio_actions) {
    tickerWeights[action.ticker] = action.target_weight;
    const sector = action.sector ?? sectors.get(action.ticker);
    if (sector) sectorWeights[sector] = (sectorWeights[sector] ?? 0) + action.target_weight;
  }
  const grossExposure = Object.values(tickerWeights).reduce((sum, weight) => sum + weight, 0);
  const payload = {
    candidate_target_hash: candidate.candidate_target_hash,
    gross_exposure: grossExposure,
    net_exposure: grossExposure,
    cash_weight: Math.max(0, 1 - grossExposure),
    ticker_weights: tickerWeights,
    sector_weights: sectorWeights,
  };
  return {
    schema_version: "portfolio.exposure_state.v1",
    ...payload,
    exposure_hash: stableHash(payload),
    frozen: true,
  };
}

function inferPositionDecision(action: PortfolioAction): PositionReview["decision"] {
  if (action.action === "SELL" || action.target_weight === 0) return "EXIT";
  if (action.action === "REDUCE") return "REDUCE";
  if (action.action === "BUY" && (action.delta_weight ?? 0) > 0) return "ADD";
  return "HOLD";
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
        .filter(([, item]) => item !== undefined)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, sortJson(item)]),
    );
  }
  return value;
}
