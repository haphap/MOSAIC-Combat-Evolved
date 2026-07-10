import { createHash } from "node:crypto";
import { attachRuntimeOwnedFallbackClaims } from "../helpers/evidence_runtime.js";
import type { RuntimeSourceStatus } from "../helpers/research_knobs.js";
import type { DailyCycleStateType } from "../state.js";
import type {
  AutoExecOutput,
  CandidateTargetState,
  CioOutput,
  CioProposalOutput,
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
  PreviousTargetState,
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
    source_evidence_observations: [],
    stage_trace: [],
  };
}

export function missingPreviousTargetState(
  reason = "previous_target_state_not_supplied",
): PreviousTargetState {
  return {
    schema_version: "portfolio.previous_target_state.v1",
    snapshot_status: "missing",
    final_target_hash: null,
    as_of_date: null,
    portfolio_actions: [],
    source_error_code: reason,
  };
}

export function previousTargetStateFromFinal(
  finalTarget: FinalTargetState | null | undefined,
): PreviousTargetState {
  if (!finalTarget) return missingPreviousTargetState("prior_final_target_missing");
  return {
    schema_version: "portfolio.previous_target_state.v1",
    snapshot_status: finalTarget.portfolio_actions.length > 0 ? "loaded" : "empty_confirmed",
    final_target_hash: finalTarget.final_target_hash,
    as_of_date: finalTarget.as_of_date,
    portfolio_actions: finalTarget.portfolio_actions.map((action) => ({ ...action })),
    source_error_code: null,
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
  const explicitReviews = isCioProposalOutput(proposal) ? proposal.position_reviews : [];
  const positionsByTicker = new Map(
    state.current_positions.positions.map((position) => [position.ticker, position]),
  );
  const reviewsByTicker = new Map(explicitReviews.map((review) => [review.ticker, review]));
  const llmActions = proposal.portfolio_actions.map((action) => {
    const position = positionsByTicker.get(action.ticker);
    const review = reviewsByTicker.get(action.ticker);
    if (position && (!review || !reviewMatchesAction(review, action))) {
      return runtimeSafetyHold(position);
    }
    return { ...action, review_source: "llm" as const };
  });
  const actions = appendFallbackHolds(llmActions, state.current_positions.positions).map((action) =>
    normalizeCandidateAction(action, positionsByTicker.get(action.ticker)),
  );
  assertUniqueTickers(actions, "candidate portfolio action");
  const positionReviews = buildPositionReviewState(
    runId,
    "pending_candidate_hash",
    actions,
    state.current_positions.positions,
    explicitReviews,
  );
  const frozenProposal: CioOutput = {
    ...proposal,
    portfolio_actions: actions,
    ...(isCioProposalOutput(proposal) ? { position_reviews: positionReviews.reviews } : {}),
  };
  const proposalHash = stableHash(proposal);
  const candidatePayload = {
    run_id: runId,
    cohort,
    as_of_date: asOfDate,
    proposal_hash: proposalHash,
    position_snapshot_hash: state.current_positions.position_snapshot_hash ?? null,
    previous_target_hash: state.layer4_outputs.previous_target_state?.final_target_hash ?? null,
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
  const finalizedPositionReviews = buildPositionReviewState(
    runId,
    candidate.candidate_target_hash,
    actions,
    state.current_positions.positions,
    explicitReviews,
  );
  return {
    proposal: frozenProposal,
    candidate,
    reviews: finalizedPositionReviews,
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
  let frozenOutput = isConservativeCroFallback(output)
    ? buildConservativeCroFallback(candidate, output)
    : output;
  try {
    validateCroOutput(candidate, frozenOutput);
  } catch (error) {
    if (frozenOutput.confidence === 0 || !(error instanceof Layer4RuntimeContractError)) {
      throw error;
    }
    frozenOutput = buildConservativeCroFallback(candidate, output, [error.message]);
    validateCroOutput(candidate, frozenOutput);
  }
  const payload = {
    run_id: runId,
    candidate_target_hash: candidate.candidate_target_hash,
    output: frozenOutput,
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
  let frozenOutput = isConservativeExecutionFallback(output)
    ? buildConservativeExecutionFallback(candidate, output)
    : output;
  try {
    validateExecutionOutput(candidate, frozenOutput);
  } catch (error) {
    if (frozenOutput.confidence === 0 || !(error instanceof Layer4RuntimeContractError)) {
      throw error;
    }
    frozenOutput = buildConservativeExecutionFallback(candidate, output, [error.message]);
    validateExecutionOutput(candidate, frozenOutput);
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
    output: frozenOutput,
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
  opts: { allowRuntimeSafetyFallback?: boolean } = {},
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
  validateFinalTargetEnvelope(state, output, opts);
  const payload = {
    run_id: state.trace_id || state.as_of_date || "current_run",
    cohort: state.active_cohort || "cohort_default",
    as_of_date: state.as_of_date || "live",
    candidate_target_hash: candidate.candidate_target_hash,
    cro_review_hash: croReview.review_hash,
    execution_feasibility_hash: execution.feasibility_hash,
    position_snapshot_hash: state.current_positions.position_snapshot_hash ?? null,
    previous_target_hash: candidate.previous_target_hash,
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

export function validateFinalTargetEnvelope(
  state: DailyCycleStateType,
  output: CioOutput,
  opts: { allowRuntimeSafetyFallback?: boolean } = {},
): void {
  const runtime = runtimeStateForLayer4(state);
  const candidate = runtime.candidate_target_state;
  const croReview = runtime.cro_review_state;
  const execution = runtime.execution_feasibility_state;
  if (!candidate || !croReview || !execution) {
    throw new Layer4RuntimeContractError(
      "final target validation requires candidate, CRO review, and execution feasibility",
    );
  }
  if (
    croReview.candidate_target_hash !== candidate.candidate_target_hash ||
    execution.candidate_target_hash !== candidate.candidate_target_hash ||
    execution.cro_review_hash !== croReview.review_hash
  ) {
    throw new Layer4RuntimeContractError("final target validation cross-stage hash mismatch");
  }

  assertUniqueTickers(candidate.portfolio_actions, "candidate portfolio action");
  assertUniqueTickers(output.portfolio_actions, "final portfolio action");
  const candidateByTicker = new Map(
    candidate.portfolio_actions.map((action) => [action.ticker, action]),
  );
  const finalByTicker = new Map(output.portfolio_actions.map((action) => [action.ticker, action]));
  for (const action of output.portfolio_actions) {
    if (!candidateByTicker.has(action.ticker)) {
      throw new Layer4RuntimeContractError(
        `final target contains ticker outside frozen candidate: ${action.ticker}`,
      );
    }
  }
  for (const position of state.current_positions.positions) {
    if (!finalByTicker.has(position.ticker)) {
      throw new Layer4RuntimeContractError(
        `final target omits current position ticker: ${position.ticker}`,
      );
    }
  }

  const dissentRefs = output.dissent_refs ?? [];
  const dissentKeys = new Set<string>();
  for (const dissent of dissentRefs) {
    if (!candidateByTicker.has(dissent.ticker)) {
      throw new Layer4RuntimeContractError(
        `dissent reference contains ticker outside frozen candidate: ${dissent.ticker}`,
      );
    }
    const key = `${dissent.ticker}:${dissent.source}`;
    if (dissentKeys.has(key)) {
      throw new Layer4RuntimeContractError(`duplicate dissent reference: ${key}`);
    }
    dissentKeys.add(key);
    const expectedHash =
      dissent.source === "cro_review" ? croReview.review_hash : execution.feasibility_hash;
    if (dissent.source_hash !== expectedHash) {
      throw new Layer4RuntimeContractError(
        `${dissent.ticker}: ${dissent.source} dissent hash mismatch`,
      );
    }
  }

  const adjustments = croReview.output.required_adjustments ?? [];
  const adjustmentByTicker = new Map(adjustments.map((item) => [item.ticker, item]));
  const runtimeFallback =
    opts.allowRuntimeSafetyFallback === true &&
    output.portfolio_actions.every((action) => action.review_source === "runtime_safety_fallback");
  for (const candidateAction of candidate.portfolio_actions) {
    const finalAction = finalByTicker.get(candidateAction.ticker);
    const finalWeight = finalAction?.target_weight ?? 0;
    if (finalWeight > candidateAction.target_weight + 1e-9) {
      throw new Layer4RuntimeContractError(
        `${candidateAction.ticker}: final target exceeds frozen candidate target`,
      );
    }
    const adjustment = adjustmentByTicker.get(candidateAction.ticker);
    if (adjustment) assertFinalTargetHonorsCroAdjustment(finalWeight, adjustment);
    if (Math.abs(finalWeight - candidateAction.target_weight) <= 1e-9 || runtimeFallback) {
      continue;
    }
    if (!adjustment) {
      throw new Layer4RuntimeContractError(
        `${candidateAction.ticker}: final target changed without structured CRO adjustment`,
      );
    }
    if (!dissentKeys.has(`${candidateAction.ticker}:cro_review`)) {
      throw new Layer4RuntimeContractError(
        `${candidateAction.ticker}: CRO-adjusted final target lacks frozen CRO dissent reference`,
      );
    }
    if (adjustment.adjustment === "REQUIRE_REVIEW") {
      throw new Layer4RuntimeContractError(
        `${candidateAction.ticker}: REQUIRE_REVIEW does not authorize a target change`,
      );
    }
  }
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

type CroAdjustment = NonNullable<CroOutput["required_adjustments"]>[number];

function normalizeCandidateAction(
  action: PortfolioAction,
  position: CurrentPosition | undefined,
): PortfolioAction {
  const currentWeight = position?.current_weight ?? action.current_weight ?? 0;
  return {
    ...action,
    current_weight: currentWeight,
    delta_weight: action.target_weight - currentWeight,
    position_decision: action.position_decision ?? inferPositionDecision(action),
  };
}

function isConservativeCroFallback(output: CroOutput): boolean {
  return (
    output.verified_claim_audit?.raw_output_accepted === false ||
    (output.confidence === 0 &&
      output.rejected_picks.length === 0 &&
      (output.required_adjustments?.length ?? 0) === 0)
  );
}

function buildConservativeCroFallback(
  candidate: CandidateTargetState,
  sourceOutput: CroOutput,
  rejectionReasons: ReadonlyArray<string> = ["cro_review_not_accepted"],
): CroOutput {
  const rejected_picks: CroOutput["rejected_picks"] = [];
  const required_adjustments: NonNullable<CroOutput["required_adjustments"]> = [];
  for (const action of candidate.portfolio_actions) {
    const currentWeight = action.current_weight ?? 0;
    const deltaWeight = action.target_weight - currentWeight;
    if (deltaWeight <= 1e-9) continue;
    if (currentWeight <= 1e-9) {
      rejected_picks.push({
        ticker: action.ticker,
        reason: "CRO fallback cannot approve a new risk position",
      });
      required_adjustments.push({
        ticker: action.ticker,
        adjustment: "VETO",
        max_target_weight: 0,
        reason: "CRO fallback vetoed unreviewed new exposure",
      });
    } else {
      required_adjustments.push({
        ticker: action.ticker,
        adjustment: "CAP_WEIGHT",
        max_target_weight: currentWeight,
        reason: "CRO fallback capped unreviewed added exposure at current weight",
      });
    }
  }
  const fallback: CroOutput = {
    ...sourceOutput,
    rejected_picks,
    required_adjustments,
    correlated_risks: [],
    black_swan_scenarios: [],
    confidence: 0,
  };
  return attachRuntimeOwnedFallbackClaims({
    output: fallback,
    sourceOutput,
    stage: "cro_review",
    fallbackReasonCode: "CRO_SEMANTIC_FALLBACK",
    rejectionReasons,
    statement: "Runtime denied new or increased risk because CRO review was unavailable.",
  });
}

function validateCroOutput(candidate: CandidateTargetState, output: CroOutput): void {
  const candidateTickers = new Set(candidate.portfolio_actions.map((action) => action.ticker));
  assertUniqueTickers(output.rejected_picks, "CRO rejected pick");
  const adjustments = output.required_adjustments ?? [];
  assertUniqueTickers(adjustments, "CRO required adjustment");
  const vetoedTickers = new Set(
    adjustments
      .filter((adjustment) => adjustment.adjustment === "VETO")
      .map((adjustment) => adjustment.ticker),
  );
  for (const rejected of output.rejected_picks) {
    if (!candidateTickers.has(rejected.ticker)) {
      throw new Layer4RuntimeContractError(
        `CRO rejected ticker outside frozen candidate: ${rejected.ticker}`,
      );
    }
    if (!vetoedTickers.has(rejected.ticker)) {
      throw new Layer4RuntimeContractError(
        `${rejected.ticker}: rejected CRO pick requires structured VETO`,
      );
    }
  }
  const candidateByTicker = new Map(
    candidate.portfolio_actions.map((action) => [action.ticker, action]),
  );
  for (const adjustment of adjustments) {
    const candidateAction = candidateByTicker.get(adjustment.ticker);
    if (!candidateAction) {
      throw new Layer4RuntimeContractError(
        `CRO adjustment ticker outside frozen candidate: ${adjustment.ticker}`,
      );
    }
    switch (adjustment.adjustment) {
      case "VETO":
        if ((adjustment.max_target_weight ?? 0) > 1e-9) {
          throw new Layer4RuntimeContractError(
            `${adjustment.ticker}: VETO max_target_weight must be zero when supplied`,
          );
        }
        break;
      case "CAP_WEIGHT":
        if (adjustment.max_target_weight === undefined) {
          throw new Layer4RuntimeContractError(
            `${adjustment.ticker}: CAP_WEIGHT requires max_target_weight`,
          );
        }
        if (adjustment.max_target_weight > candidateAction.target_weight + 1e-9) {
          throw new Layer4RuntimeContractError(
            `${adjustment.ticker}: CAP_WEIGHT cannot exceed frozen candidate target`,
          );
        }
        break;
      case "REDUCE_WEIGHT":
        if (adjustment.max_target_weight === undefined) {
          throw new Layer4RuntimeContractError(
            `${adjustment.ticker}: REDUCE_WEIGHT requires max_target_weight`,
          );
        }
        if (adjustment.max_target_weight >= candidateAction.target_weight - 1e-9) {
          throw new Layer4RuntimeContractError(
            `${adjustment.ticker}: REDUCE_WEIGHT must be below frozen candidate target`,
          );
        }
        break;
      case "REQUIRE_REVIEW":
        if (adjustment.max_target_weight !== undefined) {
          throw new Layer4RuntimeContractError(
            `${adjustment.ticker}: REQUIRE_REVIEW must not set max_target_weight`,
          );
        }
        break;
    }
  }
}

function isConservativeExecutionFallback(output: AutoExecOutput): boolean {
  return (
    output.verified_claim_audit?.raw_output_accepted === false ||
    (output.confidence === 0 &&
      output.trades.length === 0 &&
      (output.execution_checks?.length ?? 0) === 0)
  );
}

function buildConservativeExecutionFallback(
  candidate: CandidateTargetState,
  sourceOutput: AutoExecOutput,
  rejectionReasons: ReadonlyArray<string> = ["execution_feasibility_not_accepted"],
): AutoExecOutput {
  const fallback: AutoExecOutput = {
    ...sourceOutput,
    trades: [],
    execution_checks: candidate.portfolio_actions
      .filter((action) => Math.abs(action.delta_weight ?? 0) > 1e-9)
      .map((action) => ({
        ticker: action.ticker,
        status: "blocked" as const,
        estimated_cost_bps: 0,
        max_executable_delta_weight: 0,
        reason: "execution fallback blocked an unverified target delta",
      })),
    confidence: 0,
  };
  return attachRuntimeOwnedFallbackClaims({
    output: fallback,
    sourceOutput,
    stage: "execution_feasibility",
    fallbackReasonCode: "EXECUTION_SEMANTIC_FALLBACK",
    rejectionReasons,
    statement: "Runtime blocked target deltas because execution feasibility was unavailable.",
  });
}

function validateExecutionOutput(candidate: CandidateTargetState, output: AutoExecOutput): void {
  const candidateByTicker = new Map(
    candidate.portfolio_actions.map((action) => [action.ticker, action]),
  );
  assertUniqueTickers(output.trades, "execution trade");
  const checks = output.execution_checks ?? [];
  assertUniqueTickers(checks, "execution check");
  const tradeByTicker = new Map(output.trades.map((trade) => [trade.ticker, trade]));
  const checkByTicker = new Map(checks.map((check) => [check.ticker, check]));
  for (const trade of output.trades) {
    const candidateAction = candidateByTicker.get(trade.ticker);
    if (!candidateAction) {
      throw new Layer4RuntimeContractError(
        `execution trade ticker outside frozen candidate: ${trade.ticker}`,
      );
    }
    const candidateDelta = candidateAction.delta_weight ?? 0;
    const tradeDelta = trade.delta_weight ?? (trade.action === "HOLD" ? 0 : trade.size_pct);
    if (Math.abs(candidateDelta) <= 1e-9 && Math.abs(tradeDelta) > 1e-9) {
      throw new Layer4RuntimeContractError(
        `${trade.ticker}: execution trade exists without candidate delta`,
      );
    }
    const expectedAction =
      candidateDelta > 1e-9
        ? "BUY"
        : candidateAction.target_weight <= 1e-9
          ? "SELL"
          : candidateDelta < -1e-9
            ? "REDUCE"
            : "HOLD";
    if (trade.action !== expectedAction) {
      throw new Layer4RuntimeContractError(
        `${trade.ticker}: execution action ${trade.action} does not match ${expectedAction}`,
      );
    }
  }
  for (const check of checks) {
    if (!candidateByTicker.has(check.ticker)) {
      throw new Layer4RuntimeContractError(
        `execution check ticker outside frozen candidate: ${check.ticker}`,
      );
    }
  }
  for (const [ticker, candidateAction] of candidateByTicker.entries()) {
    const candidateDelta = candidateAction.delta_weight ?? 0;
    if (Math.abs(candidateDelta) <= 1e-9) continue;
    const check = checkByTicker.get(ticker);
    if (!check) {
      throw new Layer4RuntimeContractError(`${ticker}: target delta lacks execution check`);
    }
    const trade = tradeByTicker.get(ticker);
    if (check.status === "blocked") {
      if ((check.max_executable_delta_weight ?? 0) > 1e-9) {
        throw new Layer4RuntimeContractError(
          `${ticker}: blocked execution check must have zero executable delta`,
        );
      }
      if (trade && Math.abs(trade.delta_weight ?? trade.size_pct) > 1e-9) {
        throw new Layer4RuntimeContractError(`${ticker}: blocked execution cannot carry a trade`);
      }
      continue;
    }
    if (!trade) {
      throw new Layer4RuntimeContractError(`${ticker}: executable target delta lacks trade`);
    }
    if (trade.delta_weight === undefined) {
      throw new Layer4RuntimeContractError(`${ticker}: execution trade requires delta_weight`);
    }
    if (Math.sign(trade.delta_weight) !== Math.sign(candidateDelta)) {
      throw new Layer4RuntimeContractError(`${ticker}: execution trade reverses candidate delta`);
    }
    if (Math.abs(trade.delta_weight) > Math.abs(candidateDelta) + 1e-9) {
      throw new Layer4RuntimeContractError(`${ticker}: execution trade exceeds candidate delta`);
    }
    if (check.status === "partial") {
      const maxDelta = check.max_executable_delta_weight;
      if (maxDelta === undefined) {
        throw new Layer4RuntimeContractError(
          `${ticker}: partial execution requires max_executable_delta_weight`,
        );
      }
      if (maxDelta > Math.abs(candidateDelta) + 1e-9) {
        throw new Layer4RuntimeContractError(
          `${ticker}: partial execution cap exceeds candidate delta`,
        );
      }
      if (Math.abs(trade.delta_weight) > maxDelta + 1e-9) {
        throw new Layer4RuntimeContractError(
          `${ticker}: execution trade exceeds partial executable cap`,
        );
      }
    }
  }
}

function assertFinalTargetHonorsCroAdjustment(
  finalWeight: number,
  adjustment: CroAdjustment,
): void {
  if (adjustment.adjustment === "VETO" && finalWeight > 1e-9) {
    throw new Layer4RuntimeContractError(`${adjustment.ticker}: final target violates CRO VETO`);
  }
  if (
    (adjustment.adjustment === "CAP_WEIGHT" || adjustment.adjustment === "REDUCE_WEIGHT") &&
    adjustment.max_target_weight !== undefined &&
    finalWeight > adjustment.max_target_weight + 1e-9
  ) {
    throw new Layer4RuntimeContractError(
      `${adjustment.ticker}: final target exceeds CRO ${adjustment.adjustment} limit`,
    );
  }
}

function assertUniqueTickers(entries: ReadonlyArray<{ ticker: string }>, label: string): void {
  const seen = new Set<string>();
  for (const entry of entries) {
    if (seen.has(entry.ticker)) {
      throw new Layer4RuntimeContractError(`duplicate ${label} ticker: ${entry.ticker}`);
    }
    seen.add(entry.ticker);
  }
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
      .map((position) => runtimeSafetyHold(position)),
  ];
}

function runtimeSafetyHold(position: CurrentPosition): PortfolioAction {
  return {
    ticker: position.ticker,
    action: "HOLD",
    ...(position.sector ? { sector: position.sector } : {}),
    position_decision: "HOLD",
    current_weight: position.current_weight,
    target_weight: position.current_weight,
    delta_weight: 0,
    holding_period: "1M",
    position_decision_reason:
      "position omitted from a valid CIO review; runtime preserved current target",
    thesis_status: "intact",
    risk_flags: ["position_review_missing"],
    dissent_notes: "",
    review_source: "runtime_safety_fallback",
  };
}

function buildPositionReviewState(
  runId: string,
  candidateTargetHash: string,
  actions: ReadonlyArray<PortfolioAction>,
  positions: ReadonlyArray<CurrentPosition>,
  explicitReviews: ReadonlyArray<PositionReview>,
): PositionReviewState {
  const currentTickers = new Set(positions.map((position) => position.ticker));
  const explicitByTicker = new Map(explicitReviews.map((review) => [review.ticker, review]));
  const reviews = actions
    .filter((action) => currentTickers.has(action.ticker))
    .map((action): PositionReview => {
      const explicit = explicitByTicker.get(action.ticker);
      if (action.review_source !== "runtime_safety_fallback" && explicit) {
        return { ...explicit, review_source: "llm" };
      }
      return {
        ticker: action.ticker,
        decision: "HOLD",
        target_weight: action.target_weight,
        reason: action.position_decision_reason ?? "position target lacks a valid explicit review",
        thesis_status: action.thesis_status ?? "weakened",
        risk_flags: [...(action.risk_flags ?? ["position_review_missing"])],
        confidence: 0,
        review_source: "runtime_safety_fallback",
      };
    });
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

function isCioProposalOutput(proposal: CioOutput): proposal is CioProposalOutput {
  return Array.isArray((proposal as Partial<CioProposalOutput>).position_reviews);
}

function reviewMatchesAction(review: PositionReview, action: PortfolioAction): boolean {
  return (
    review.ticker === action.ticker &&
    review.decision === inferPositionDecision(action) &&
    Math.abs(review.target_weight - action.target_weight) <= 1e-9 &&
    review.review_source !== "runtime_safety_fallback"
  );
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
