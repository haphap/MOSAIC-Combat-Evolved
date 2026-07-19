import { createHash } from "node:crypto";
import type { NoEvaluationObjectStageSkipRecord } from "../../autoresearch/outcome_stage_skip.js";
import type { RuntimeSourceStatus } from "../helpers/private_knot_boundary.js";
import type { RuntimeAgentStageId } from "../prompts/runtime_agent_spec.js";
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
  L4RunPromptSnapshot,
  L4RunSnapshotBundle,
  Layer4RuntimeState,
  Layer4RuntimeTraceEntry,
  PortfolioAction,
  PortfolioExposureState,
  PortfolioSummary,
  PositionReview,
  PositionReviewState,
  PreviousTargetState,
} from "../types.js";

export class Layer4RuntimeContractError extends Error {}

export function emptyLayer4RuntimeState(): Layer4RuntimeState {
  return {
    l4_run_snapshot_bundle: null,
    cio_proposal: null,
    candidate_target_state: null,
    position_review_state: null,
    portfolio_exposure_state: null,
    cro_review_state: null,
    execution_feasibility_state: null,
    final_target_state: null,
    portfolio_summary: null,
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

export function layer4PromptSourceHash(source: { zh: string; en: string } | string): string {
  return stableHash(
    typeof source === "string"
      ? { schema_version: "decision.l4_prompt_source.v1", prompt: source }
      : { schema_version: "decision.l4_prompt_source.v1", zh: source.zh, en: source.en },
  );
}

function layer4PositionSnapshotHash(state: DailyCycleStateType): string {
  const declared = state.current_positions.position_snapshot_hash;
  if (declared && /^sha256:[0-9a-f]{64}$/.test(declared)) return declared;
  return stableHash({
    schema_version: "portfolio.current_positions.v1",
    declared_snapshot_hash: declared ?? null,
    snapshot: state.current_positions,
  });
}

function layer4AccountSnapshotHash(state: DailyCycleStateType): string {
  return stableHash({
    schema_version: "portfolio.account_snapshot.v1",
    mode: state.mode,
    position_source: state.current_positions.position_source,
    snapshot_status: state.current_positions.snapshot_status,
    position_snapshot_hash: layer4PositionSnapshotHash(state),
  });
}

function layer4UpstreamOutputsHash(state: DailyCycleStateType): string {
  if (state.darwinian_runtime_binding) {
    return stableHash({
      schema_version: "decision.l4_upstream_accepted_refs.v1",
      accepted_output_refs: Object.fromEntries(
        Object.entries(state.accepted_output_refs ?? {})
          .filter(
            ([key]) =>
              key.startsWith("MACRO_TRANSMISSION:") ||
              key.startsWith("STANDARD_SECTOR_SELECTION:") ||
              key.startsWith("RELATIONSHIP_GRAPH:") ||
              key.startsWith("SUPERINVESTOR_SELECTION:"),
          )
          .sort(([left], [right]) => left.localeCompare(right)),
      ),
      macro_input_gate: state.macro_input_gate,
      outcome_stage_skips: state.outcome_stage_skips,
    });
  }
  return stableHash({
    schema_version: "decision.l4_upstream_outputs.v1",
    layer1_outputs: state.layer1_outputs,
    macro_input_gate: state.macro_input_gate,
    layer2_outputs: state.layer2_outputs,
    layer3_outputs: state.layer3_outputs,
    outcome_stage_skips: state.outcome_stage_skips,
  });
}

function marketSourceHashes(statuses: ReadonlyArray<RuntimeSourceStatus>): Record<string, string> {
  return Object.fromEntries(
    statuses
      .filter((status) => status.source_id === "current_market_data")
      .map((status) => [`${status.source_id}|${status.scope}`, stableHash(status)] as const)
      .sort(([left], [right]) => left.localeCompare(right)),
  );
}

export function freezeL4RunSnapshotBundle(input: {
  state: DailyCycleStateType;
  promptSnapshots: ReadonlyArray<L4RunPromptSnapshot>;
  sourceStatuses: ReadonlyArray<RuntimeSourceStatus>;
  mirofishContextHash: string | null;
}): L4RunSnapshotBundle {
  const promptSnapshots = [...input.promptSnapshots].sort((left, right) =>
    left.stage.localeCompare(right.stage),
  );
  const stageSet = new Set(promptSnapshots.map((snapshot) => snapshot.stage));
  if (promptSnapshots.length !== 5 || stageSet.size !== 5) {
    throw new Layer4RuntimeContractError("L4 snapshot requires all five invocation stages");
  }
  const baseMarketSourceHashes = marketSourceHashes(input.sourceStatuses);
  const payload = {
    run_id: input.state.trace_id || input.state.as_of_date || "current_run",
    cohort: input.state.active_cohort || "cohort_default",
    as_of_date: input.state.as_of_date || "live",
    prompt_snapshots: promptSnapshots,
    position_snapshot_hash: layer4PositionSnapshotHash(input.state),
    account_snapshot_hash: layer4AccountSnapshotHash(input.state),
    upstream_outputs_hash: layer4UpstreamOutputsHash(input.state),
    base_market_data_vintage_hash: stableHash(baseMarketSourceHashes),
    base_market_source_hashes: baseMarketSourceHashes,
    mirofish_context_hash: input.mirofishContextHash,
  };
  return {
    schema_version: "decision.l4_run_snapshot_bundle.v1",
    ...payload,
    bundle_hash: stableHash(payload),
    frozen: true,
  };
}

export function assertL4RunSnapshotStage(input: {
  state: DailyCycleStateType;
  agent: string;
  stage: RuntimeAgentStageId;
  promptSourceHash: string;
  privateKnotSnapshotHash: string | null;
  mirofishContextHash: string | null;
}): L4RunSnapshotBundle {
  const bundle = runtimeStateForLayer4(input.state).l4_run_snapshot_bundle;
  if (!bundle) throw new Layer4RuntimeContractError("L4 run snapshot bundle is missing");
  const { schema_version: _schema, bundle_hash: bundleHash, frozen: _frozen, ...payload } = bundle;
  if (bundleHash !== stableHash(payload)) {
    throw new Layer4RuntimeContractError("L4 run snapshot bundle hash mismatch");
  }
  if (
    bundle.run_id !== (input.state.trace_id || input.state.as_of_date || "current_run") ||
    bundle.cohort !== (input.state.active_cohort || "cohort_default") ||
    bundle.as_of_date !== (input.state.as_of_date || "live")
  ) {
    throw new Layer4RuntimeContractError("L4 run identity changed after snapshot freeze");
  }
  if (
    bundle.position_snapshot_hash !== layer4PositionSnapshotHash(input.state) ||
    bundle.account_snapshot_hash !== layer4AccountSnapshotHash(input.state) ||
    bundle.upstream_outputs_hash !== layer4UpstreamOutputsHash(input.state)
  ) {
    throw new Layer4RuntimeContractError("L4 immutable input changed after snapshot freeze");
  }
  const prompt = bundle.prompt_snapshots.find((snapshot) => snapshot.stage === input.stage);
  if (!prompt || prompt.agent !== input.agent) {
    throw new Layer4RuntimeContractError("L4 prompt snapshot stage/agent mismatch");
  }
  if (
    prompt.prompt_source_hash !== input.promptSourceHash ||
    prompt.private_knot_snapshot_hash !== input.privateKnotSnapshotHash
  ) {
    throw new Layer4RuntimeContractError("L4 prompt or knob hash drifted during run");
  }
  const currentSourceHashes = marketSourceHashes(
    runtimeStateForLayer4(input.state).resolved_source_statuses,
  );
  for (const [key, expected] of Object.entries(bundle.base_market_source_hashes)) {
    if (currentSourceHashes[key] !== expected) {
      throw new Layer4RuntimeContractError(`L4 base market source drifted: ${key}`);
    }
  }
  if (
    input.agent !== "alpha_discovery" &&
    bundle.mirofish_context_hash !== input.mirofishContextHash
  ) {
    throw new Layer4RuntimeContractError("L4 MiroFish context changed after snapshot freeze");
  }
  return bundle;
}

function layer4RunSnapshotHash(state: DailyCycleStateType): string {
  return (
    runtimeStateForLayer4(state).l4_run_snapshot_bundle?.bundle_hash ??
    stableHash({
      schema_version: "decision.l4_legacy_snapshot.v1",
      run_id: state.trace_id || state.as_of_date || "current_run",
      position_snapshot_hash: layer4PositionSnapshotHash(state),
      upstream_outputs_hash: layer4UpstreamOutputsHash(state),
    })
  );
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
  const l4RunSnapshotHash = layer4RunSnapshotHash(state);
  const cohort = state.active_cohort || "cohort_default";
  const asOfDate = state.as_of_date || "live";
  const positionsByTicker = new Map(
    state.current_positions.positions.map((position) => [position.ticker, position]),
  );
  const selectedProposal = proposal;
  const explicitReviews = isCioProposalOutput(selectedProposal)
    ? selectedProposal.position_reviews
    : [];
  if (selectedProposal.verified_claim_audit?.raw_output_accepted === false) {
    throw new Layer4RuntimeContractError("CIO proposal evidence graph was rejected");
  }
  const actions = validatedCandidateActions(
    state,
    selectedProposal,
    explicitReviews,
    positionsByTicker,
  );
  const positionReviews = buildPositionReviewState(
    runId,
    "pending_candidate_hash",
    l4RunSnapshotHash,
    actions,
    state.current_positions.positions,
    explicitReviews,
  );
  const frozenProposal: CioOutput = {
    ...selectedProposal,
    portfolio_actions: actions,
    position_reviews: positionReviews.reviews,
  };
  const proposalHash = stableHash(frozenProposal);
  const candidatePayload = {
    run_id: runId,
    cohort,
    as_of_date: asOfDate,
    proposal_hash: proposalHash,
    l4_run_snapshot_hash: l4RunSnapshotHash,
    position_snapshot_hash: state.current_positions.position_snapshot_hash ?? null,
    previous_target_hash: state.layer4_outputs.previous_target_state?.final_target_hash ?? null,
    market_data_vintage_hash: runtimeSourceVintageHash(
      state.layer4_outputs.runtime?.resolved_source_statuses ?? [],
      "current_market_data",
      actions.map((action) => action.ticker),
      asOfDate,
    ),
    portfolio_actions: actions,
    confidence: frozenProposal.confidence,
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
    l4RunSnapshotHash,
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
  const frozenOutput = output;
  validateCroOutput(candidate, frozenOutput);
  const payload = {
    run_id: runId,
    candidate_target_hash: candidate.candidate_target_hash,
    l4_run_snapshot_hash: candidate.l4_run_snapshot_hash,
    source_status: "ACCEPTED_OUTPUT" as const,
    stage_skip_id: null,
    stage_skip_hash: null,
    output: frozenOutput,
  };
  return {
    schema_version: "decision.cro_review_state.v1",
    ...payload,
    review_hash: stableHash(payload),
    frozen: true,
  };
}

export function freezeCroStageSkip(
  runId: string,
  candidate: CandidateTargetState | null,
  stageSkip: NoEvaluationObjectStageSkipRecord,
): CroReviewState {
  if (!candidate) {
    throw new Layer4RuntimeContractError("cro stage skip requires frozen candidate_target_state");
  }
  if (stageSkip.agent_id !== "cro" || stageSkip.member_count !== 0 || stageSkip.model_invoked) {
    throw new Layer4RuntimeContractError("cro stage skip contract mismatch");
  }
  if (candidate.portfolio_actions.length !== 0) {
    throw new Layer4RuntimeContractError("cro stage skip cannot bypass a non-empty candidate set");
  }
  const output: CroOutput = {
    agent: "cro",
    review_disposition: "NO_OBJECTION",
    rejected_picks: [],
    required_adjustments: [],
    correlated_risks: [],
    black_swan_scenarios: [],
    confidence: 0,
  };
  const payload = {
    run_id: runId,
    candidate_target_hash: candidate.candidate_target_hash,
    l4_run_snapshot_hash: candidate.l4_run_snapshot_hash,
    source_status: "NO_EVALUATION_OBJECT" as const,
    stage_skip_id: stageSkip.stage_skip_id,
    stage_skip_hash: stageSkip.stage_skip_hash,
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
  if (croReview.l4_run_snapshot_hash !== candidate.l4_run_snapshot_hash) {
    throw new Layer4RuntimeContractError("execution_feasibility L4 snapshot hash mismatch");
  }
  const frozenOutput = output;
  validateExecutionOutput(candidate, frozenOutput);
  const payload = {
    run_id: runId,
    candidate_target_hash: candidate.candidate_target_hash,
    l4_run_snapshot_hash: candidate.l4_run_snapshot_hash,
    cro_review_hash: croReview.review_hash,
    source_status: "ACCEPTED_OUTPUT" as const,
    stage_skip_id: null,
    stage_skip_hash: null,
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

export function freezeExecutionStageSkip(
  runId: string,
  candidate: CandidateTargetState | null,
  croReview: CroReviewState | null,
  stageSkip: NoEvaluationObjectStageSkipRecord,
): ExecutionFeasibilityState {
  if (!candidate || !croReview) {
    throw new Layer4RuntimeContractError(
      "execution stage skip requires frozen candidate and CRO control",
    );
  }
  if (
    croReview.candidate_target_hash !== candidate.candidate_target_hash ||
    croReview.l4_run_snapshot_hash !== candidate.l4_run_snapshot_hash
  ) {
    throw new Layer4RuntimeContractError("execution stage skip control hash mismatch");
  }
  if (
    stageSkip.agent_id !== "autonomous_execution" ||
    stageSkip.member_count !== 0 ||
    stageSkip.model_invoked
  ) {
    throw new Layer4RuntimeContractError("execution stage skip contract mismatch");
  }
  const actionable = candidate.portfolio_actions.filter(
    (action) => action.action !== "HOLD" || Math.abs(action.delta_weight ?? 0) > 1e-9,
  );
  if (actionable.length !== 0) {
    throw new Layer4RuntimeContractError(
      "execution stage skip cannot bypass non-empty order intents",
    );
  }
  const output: AutoExecOutput = {
    agent: "autonomous_execution",
    execution_disposition: "NO_DELTA",
    trades: [],
    execution_checks: [],
    confidence: 0,
  };
  const payload = {
    run_id: runId,
    candidate_target_hash: candidate.candidate_target_hash,
    l4_run_snapshot_hash: candidate.l4_run_snapshot_hash,
    cro_review_hash: croReview.review_hash,
    source_status: "NO_EVALUATION_OBJECT" as const,
    stage_skip_id: stageSkip.stage_skip_id,
    stage_skip_hash: stageSkip.stage_skip_hash,
    liquidity_vintage_hash: stableHash({
      source_status: "NO_EVALUATION_OBJECT",
      stage_skip_hash: stageSkip.stage_skip_hash,
    }),
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
    execution.cro_review_hash !== croReview.review_hash ||
    croReview.l4_run_snapshot_hash !== candidate.l4_run_snapshot_hash ||
    execution.l4_run_snapshot_hash !== candidate.l4_run_snapshot_hash
  ) {
    throw new Layer4RuntimeContractError("final_target_state cross-stage hash mismatch");
  }
  validateFinalTargetEnvelope(state, output);
  const payload = {
    run_id: state.trace_id || state.as_of_date || "current_run",
    cohort: state.active_cohort || "cohort_default",
    as_of_date: state.as_of_date || "live",
    candidate_target_hash: candidate.candidate_target_hash,
    l4_run_snapshot_hash: candidate.l4_run_snapshot_hash,
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

export function buildPortfolioSummary(input: {
  state: DailyCycleStateType;
  finalTarget: FinalTargetState;
  validationStatus: "accepted" | "fallback";
  reasonCodes?: ReadonlyArray<string>;
}): PortfolioSummary {
  const targetWeightSum = input.finalTarget.portfolio_actions.reduce(
    (sum, action) => sum + action.target_weight,
    0,
  );
  const actionMappingHash = stableHash({
    schema_version: "portfolio.action_mapping.v1",
    mappings: {
      HOLD: "HOLD",
      ADD: "BUY",
      REDUCE: "REDUCE",
      EXIT: "SELL",
    },
    delta_formula: "target_weight-current_weight",
  });
  const validatorBundleHash = stableHash({
    schema_version: "portfolio.validator_bundle.v1",
    validator_hashes: [...input.finalTarget.validator_hashes].sort(),
  });
  const payload = {
    l4_run_snapshot_hash: input.finalTarget.l4_run_snapshot_hash,
    base_position_snapshot_hash: input.state.current_positions.position_snapshot_hash ?? null,
    market_vintage_hash: input.finalTarget.market_data_vintage_hash,
    liquidity_vintage_hash: input.finalTarget.liquidity_vintage_hash,
    candidate_target_hash: input.finalTarget.candidate_target_hash,
    final_target_hash: input.finalTarget.final_target_hash,
    cash_weight: Math.max(0, 1 - targetWeightSum),
    gross_exposure: targetWeightSum,
    net_exposure: targetWeightSum,
    target_weight_sum: targetWeightSum,
    leverage_authorized: false as const,
    action_mapping_hash: actionMappingHash,
    validator_bundle_hash: validatorBundleHash,
    validator_results: input.finalTarget.validator_hashes.map((validatorHash) => ({
      validator_hash: validatorHash,
      status: input.validationStatus,
      reason_codes: [...(input.reasonCodes ?? [])],
    })),
  };
  return {
    schema_version: "portfolio.summary.v1",
    ...payload,
    summary_hash: stableHash(payload),
    frozen: true,
  };
}

export function validateFinalTargetEnvelope(state: DailyCycleStateType, output: CioOutput): void {
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
    execution.cro_review_hash !== croReview.review_hash ||
    croReview.l4_run_snapshot_hash !== candidate.l4_run_snapshot_hash ||
    execution.l4_run_snapshot_hash !== candidate.l4_run_snapshot_hash
  ) {
    throw new Layer4RuntimeContractError("final target validation cross-stage hash mismatch");
  }
  assertControlSourceBinding(
    "cro",
    croReview.source_status,
    croReview.stage_skip_id,
    croReview.stage_skip_hash,
    state,
  );
  assertControlSourceBinding(
    "autonomous_execution",
    execution.source_status,
    execution.stage_skip_id,
    execution.stage_skip_hash,
    state,
  );

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
  const executionChecks = execution.output.execution_checks ?? [];
  const executionCheckByTicker = new Map(executionChecks.map((item) => [item.ticker, item]));
  for (const candidateAction of candidate.portfolio_actions) {
    const finalAction = finalByTicker.get(candidateAction.ticker);
    const finalWeight = finalAction?.target_weight ?? 0;
    const currentWeight = candidateAction.current_weight ?? 0;
    const requestedDelta = candidateAction.target_weight - currentWeight;
    const finalDelta = finalWeight - currentWeight;
    const executionCheck = executionCheckByTicker.get(candidateAction.ticker);
    const executionConstrains = assertFinalTargetHonorsExecutionAssessment({
      ticker: candidateAction.ticker,
      requestedDelta,
      finalDelta,
      executionCheck,
    });
    const adjustment = adjustmentByTicker.get(candidateAction.ticker);
    if (adjustment) assertFinalTargetHonorsCroAdjustment(finalWeight, adjustment);
    if (Math.abs(finalWeight - candidateAction.target_weight) <= 1e-9) {
      continue;
    }
    const croAuthorizesChange = Boolean(adjustment && adjustment.adjustment !== "REQUIRE_REVIEW");
    if (!croAuthorizesChange && !executionConstrains) {
      throw new Layer4RuntimeContractError(
        `${candidateAction.ticker}: final target changed without a binding control`,
      );
    }
    if (croAuthorizesChange && !dissentKeys.has(`${candidateAction.ticker}:cro_review`)) {
      throw new Layer4RuntimeContractError(
        `${candidateAction.ticker}: CRO-adjusted final target lacks frozen CRO dissent reference`,
      );
    }
    if (
      executionConstrains &&
      !dissentKeys.has(`${candidateAction.ticker}:execution_feasibility`)
    ) {
      throw new Layer4RuntimeContractError(
        `${candidateAction.ticker}: execution-adjusted final target lacks frozen execution dissent reference`,
      );
    }
  }
}

function assertFinalTargetHonorsExecutionAssessment(input: {
  ticker: string;
  requestedDelta: number;
  finalDelta: number;
  executionCheck: NonNullable<AutoExecOutput["execution_checks"]>[number] | undefined;
}): boolean {
  const epsilon = 1e-9;
  if (Math.abs(input.requestedDelta) <= epsilon) {
    if (Math.abs(input.finalDelta) > epsilon) {
      throw new Layer4RuntimeContractError(
        `${input.ticker}: final delta has no frozen execution assessment`,
      );
    }
    return false;
  }
  if (!input.executionCheck) {
    throw new Layer4RuntimeContractError(
      `${input.ticker}: actionable final target lacks frozen execution assessment`,
    );
  }
  if (
    Math.abs(input.finalDelta) > epsilon &&
    Math.sign(input.finalDelta) !== Math.sign(input.requestedDelta)
  ) {
    throw new Layer4RuntimeContractError(
      `${input.ticker}: final target reverses the frozen candidate delta`,
    );
  }
  let executableCap = Math.abs(input.requestedDelta);
  if (input.executionCheck.status === "blocked") {
    executableCap = 0;
  } else if (input.executionCheck.status === "partial") {
    const suppliedCap = input.executionCheck.max_executable_delta_weight;
    if (suppliedCap === undefined) {
      throw new Layer4RuntimeContractError(
        `${input.ticker}: partial execution assessment lacks an executable cap`,
      );
    }
    executableCap = suppliedCap;
  }
  if (Math.abs(input.finalDelta) > executableCap + epsilon) {
    throw new Layer4RuntimeContractError(
      `${input.ticker}: final delta exceeds frozen ${input.executionCheck.status} execution cap`,
    );
  }
  return executableCap < Math.abs(input.requestedDelta) - epsilon;
}

function assertControlSourceBinding(
  agentId: "cro" | "autonomous_execution",
  sourceStatus: "ACCEPTED_OUTPUT" | "NO_EVALUATION_OBJECT",
  stageSkipId: string | null,
  stageSkipHash: string | null,
  state: DailyCycleStateType,
): void {
  const stageSkip = state.outcome_stage_skips[agentId];
  if (sourceStatus === "ACCEPTED_OUTPUT") {
    if (stageSkip || stageSkipId !== null || stageSkipHash !== null) {
      throw new Layer4RuntimeContractError(`${agentId} accepted control carries a stage skip`);
    }
    return;
  }
  if (
    !stageSkip ||
    stageSkipId !== stageSkip.stage_skip_id ||
    stageSkipHash !== stageSkip.stage_skip_hash
  ) {
    throw new Layer4RuntimeContractError(`${agentId} stage-skip control binding mismatch`);
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

function validatedCandidateActions(
  state: DailyCycleStateType,
  proposal: CioOutput,
  explicitReviews: ReadonlyArray<PositionReview>,
  positionsByTicker: ReadonlyMap<string, CurrentPosition>,
): PortfolioAction[] {
  if (state.current_positions.snapshot_status === "missing") {
    throw new Layer4RuntimeContractError(
      "CIO proposal cannot construct a candidate from missing current positions",
    );
  }
  assertUniqueTickers(proposal.portfolio_actions, "candidate portfolio action");
  assertUniqueTickers(explicitReviews, "CIO position review");
  const actionByTicker = new Map(
    proposal.portfolio_actions.map((action) => [action.ticker, action]),
  );
  const reviewByTicker = new Map(explicitReviews.map((review) => [review.ticker, review]));
  if (state.current_positions.snapshot_status === "loaded") {
    for (const position of state.current_positions.positions) {
      const action = actionByTicker.get(position.ticker);
      const review = reviewByTicker.get(position.ticker);
      if (!action || !review || !reviewMatchesAction(review, action)) {
        throw new Layer4RuntimeContractError(
          `${position.ticker}: CIO proposal lacks a matching explicit current-position review`,
        );
      }
    }
  }
  const actions = proposal.portfolio_actions.map((action) =>
    normalizeCandidateAction(action, positionsByTicker.get(action.ticker)),
  );
  for (const action of actions) assertCandidateActionSemantics(action);
  const totalWeight = actions.reduce((sum, action) => sum + action.target_weight, 0);
  if (totalWeight > 1 + 1e-6) {
    throw new Layer4RuntimeContractError(
      `candidate target weight sum ${totalWeight.toFixed(6)} exceeds 1.0 + epsilon`,
    );
  }
  return actions.map((action) => ({ ...action, review_source: "llm" }));
}

function assertCandidateActionSemantics(action: PortfolioAction): void {
  const currentWeight = action.current_weight ?? 0;
  const deltaWeight = action.delta_weight ?? action.target_weight - currentWeight;
  const expectedDecision =
    action.action === "BUY"
      ? "ADD"
      : action.action === "REDUCE"
        ? "REDUCE"
        : action.action === "SELL"
          ? "EXIT"
          : "HOLD";
  if (action.position_decision !== expectedDecision) {
    throw new Layer4RuntimeContractError(
      `${action.ticker}: candidate position_decision does not match ${action.action}`,
    );
  }
  if (action.action === "BUY" && (action.target_weight <= 0 || deltaWeight <= 1e-9)) {
    throw new Layer4RuntimeContractError(
      `${action.ticker}: candidate BUY requires positive target-current delta`,
    );
  }
  if (
    action.action === "REDUCE" &&
    (currentWeight <= 0 || action.target_weight <= 0 || deltaWeight >= -1e-9)
  ) {
    throw new Layer4RuntimeContractError(
      `${action.ticker}: candidate REDUCE requires 0 < target_weight < current_weight`,
    );
  }
  if (
    action.action === "SELL" &&
    (currentWeight <= 0 || action.target_weight > 1e-9 || deltaWeight >= -1e-9)
  ) {
    throw new Layer4RuntimeContractError(
      `${action.ticker}: candidate SELL requires an existing position and zero target`,
    );
  }
  if (action.action === "HOLD" && (currentWeight <= 0 || Math.abs(deltaWeight) > 1e-9)) {
    throw new Layer4RuntimeContractError(
      `${action.ticker}: candidate HOLD requires unchanged positive current exposure`,
    );
  }
}

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

function buildPositionReviewState(
  runId: string,
  candidateTargetHash: string,
  l4RunSnapshotHash: string,
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
      if (!explicit || !reviewMatchesAction(explicit, action)) {
        throw new Layer4RuntimeContractError(
          `${action.ticker}: current position lacks an explicit matching model review`,
        );
      }
      return { ...explicit, review_source: "llm" };
    });
  const llmReviewedTickers = reviews.map((review) => review.ticker).sort();
  const fallbackTickers: string[] = [];
  const payload = {
    run_id: runId,
    candidate_target_hash: candidateTargetHash,
    l4_run_snapshot_hash: l4RunSnapshotHash,
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
    l4_run_snapshot_hash: candidate.l4_run_snapshot_hash,
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
  if (action.action === "BUY") return "ADD";
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
