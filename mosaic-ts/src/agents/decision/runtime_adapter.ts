import { canonicalAcceptedOutputHash } from "../accepted_output.js";
import type { DailyCycleStateType } from "../state.js";
import type {
  AlphaDiscoveryOutput,
  AutoExecOutput,
  CioFinalOutput,
  CioOutput,
  CioProposalOutput,
  CroOutput,
  PortfolioAction,
  PositionReview,
} from "../types.js";
import type {
  AlphaDiscoverySubmission,
  AutonomousExecutionSubmission,
  CioFinalSubmission,
  CioProposalSubmission,
  CroAgentSubmission,
  DecisionAgentSubmission,
} from "./accepted.js";

export function decisionSubmissionToRuntimeOutput(
  submission: DecisionAgentSubmission,
  state: DailyCycleStateType,
): CroOutput | AlphaDiscoveryOutput | AutoExecOutput | CioOutput {
  if (submission.agent_id === "cro") return croSubmissionToRuntime(submission);
  if (submission.agent_id === "alpha_discovery") {
    return alphaSubmissionToRuntime(submission);
  }
  if (submission.agent_id === "autonomous_execution") {
    return executionSubmissionToRuntime(submission, state);
  }
  return cioSubmissionToRuntime(submission, state);
}

export function croSubmissionToRuntime(submission: CroAgentSubmission): CroOutput {
  return {
    ...runtimeEnvelope(submission),
    agent: "cro",
    review_disposition: submission.review_disposition,
    rejected_picks: submission.candidate_actions
      .filter((action) => action.action === "VETO")
      .map((action) => ({
        ticker: action.ts_code,
        reason: action.reason,
        claim_refs: action.claim_refs,
      })),
    required_adjustments: submission.candidate_actions
      .filter(
        (
          action,
        ): action is typeof action & {
          action: "VETO" | "CAP_WEIGHT" | "REDUCE_WEIGHT" | "REQUIRE_REVIEW";
        } => action.action !== "NO_OBJECTION",
      )
      .map((action) => ({
        action_local_id: action.action_local_id,
        candidate_ref: action.candidate_ref,
        ticker: action.ts_code,
        adjustment: action.action,
        ...(action.max_target_weight !== null
          ? { max_target_weight: action.max_target_weight }
          : {}),
        reason: action.reason,
        claim_refs: action.claim_refs,
      })),
    correlated_risks: submission.correlated_risks.map((risk) => risk.summary),
    black_swan_scenarios: submission.black_swan_scenarios.map((risk) => risk.summary),
    confidence: submission.confidence,
  };
}

export function alphaSubmissionToRuntime(
  submission: AlphaDiscoverySubmission,
): AlphaDiscoveryOutput {
  return {
    ...runtimeEnvelope(submission),
    agent: "alpha_discovery",
    discovery_disposition: submission.discovery_disposition,
    novel_picks: submission.novel_picks.map((pick) => ({
      pick_local_id: pick.pick_local_id,
      candidate_ref: pick.candidate_ref,
      ticker: pick.ts_code,
      conviction: pick.conviction,
      why_missed_by_others: pick.thesis,
      claim_refs: pick.claim_refs,
    })),
    confidence: submission.confidence,
  };
}

export function executionSubmissionToRuntime(
  submission: AutonomousExecutionSubmission,
  state: DailyCycleStateType,
): AutoExecOutput {
  const candidate = state.layer4_outputs.runtime?.candidate_target_state;
  const candidateByTicker = new Map(
    (candidate?.portfolio_actions ?? []).map((action) => [action.ticker, action]),
  );
  const trades = submission.order_assessments.flatMap((assessment) => {
    if (assessment.feasibility === "BLOCKED") return [];
    const candidateAction = candidateByTicker.get(assessment.ts_code);
    const candidateDelta = candidateAction?.delta_weight ?? assessment.requested_delta_weight;
    const executableMagnitude =
      assessment.feasibility === "PARTIAL"
        ? (assessment.max_executable_delta_weight ?? 0)
        : Math.abs(assessment.requested_delta_weight);
    const deltaWeight = Math.sign(candidateDelta) * executableMagnitude;
    return [
      {
        assessment_local_id: assessment.assessment_local_id,
        order_intent_ref: assessment.order_intent_ref,
        ticker: assessment.ts_code,
        action: executionAction(candidateAction, candidateDelta),
        size_pct: Math.abs(deltaWeight),
        delta_weight: deltaWeight,
        estimated_slippage_pct: assessment.predicted_cost_bps / 10_000,
        order_split_count: assessment.recommended_slice_count,
        conviction: assessment.feasibility_confidence,
        claim_refs: assessment.claim_refs,
      },
    ];
  });
  return {
    ...runtimeEnvelope(submission),
    agent: "autonomous_execution",
    execution_disposition: submission.execution_disposition === "BLOCKED" ? "BLOCKED" : "TRADES",
    trades,
    execution_checks: submission.order_assessments.map((assessment) => ({
      assessment_local_id: assessment.assessment_local_id,
      order_intent_ref: assessment.order_intent_ref,
      ticker: assessment.ts_code,
      status: assessment.feasibility.toLowerCase() as "feasible" | "partial" | "blocked",
      estimated_cost_bps: assessment.predicted_cost_bps,
      ...(assessment.max_executable_delta_weight !== null
        ? { max_executable_delta_weight: assessment.max_executable_delta_weight }
        : {}),
      reason: assessment.reason,
      claim_refs: assessment.claim_refs,
    })),
    confidence: submission.confidence,
  };
}

export function cioSubmissionToRuntime(
  submission: CioProposalSubmission | CioFinalSubmission,
  state: DailyCycleStateType,
): CioProposalOutput | CioFinalOutput {
  const currentByTicker = new Map(
    state.current_positions.positions.map((position) => [position.ticker, position]),
  );
  const portfolioActions = submission.target_positions.map((position): PortfolioAction => {
    const currentWeight = currentByTicker.get(position.ts_code)?.current_weight ?? 0;
    const dissentNotes =
      submission.decision_stage === "FINAL"
        ? finalResolutionReasons(submission, position.ts_code, state).join(" | ")
        : "";
    return {
      ticker: position.ts_code,
      action: positionAction(position.position_decision),
      position_decision: position.position_decision,
      current_weight: currentWeight,
      target_weight: position.target_weight,
      delta_weight: position.target_weight - currentWeight,
      holding_period: legacyHoldingPeriod(position.holding_period),
      position_decision_reason: submission.decision_reason,
      thesis_status: position.thesis_status.toLowerCase() as PortfolioAction["thesis_status"],
      risk_flags: position.risk_flags,
      dissent_notes: dissentNotes,
      claim_refs: position.claim_refs,
    };
  });
  const base: CioOutput = {
    ...runtimeEnvelope(submission),
    agent: "cio",
    decision_disposition: submission.decision_disposition,
    decision_reason: submission.decision_reason,
    decision_claim_refs: submission.claim_refs,
    portfolio_actions: portfolioActions,
    confidence: submission.confidence,
  };
  if (submission.decision_stage === "PROPOSAL") {
    return {
      ...base,
      position_reviews: submission.target_positions
        .filter((position) => currentByTicker.has(position.ts_code))
        .map(
          (position): PositionReview => ({
            ticker: position.ts_code,
            decision: position.position_decision,
            target_weight: position.target_weight,
            reason: submission.decision_reason,
            thesis_status: position.thesis_status.toLowerCase() as PositionReview["thesis_status"],
            risk_flags: position.risk_flags,
            confidence: submission.confidence,
            claim_refs: position.claim_refs,
          }),
        ),
    };
  }
  return { ...base, dissent_refs: finalDissentRefs(submission, state) };
}

export function frozenCandidateRef(candidateTargetHash: string, tsCode: string): string {
  return persistentRef("candidate", {
    candidate_target_hash: candidateTargetHash,
    ts_code: tsCode,
  });
}

export function frozenOrderIntentRef(input: {
  candidateTargetHash: string;
  croReviewHash: string;
  tsCode: string;
  requestedDeltaWeight: number;
}): string {
  return persistentRef("order-intent", {
    candidate_target_hash: input.candidateTargetHash,
    cro_review_hash: input.croReviewHash,
    ts_code: input.tsCode,
    requested_delta_weight: input.requestedDeltaWeight,
  });
}

export interface FrozenOrderIntentView {
  order_intent_ref: string;
  ts_code: string;
  requested_delta_weight: number;
}

export function expectedFrozenOrderIntents(state: DailyCycleStateType): FrozenOrderIntentView[] {
  const runtime = state.layer4_outputs.runtime;
  const candidate = runtime?.candidate_target_state;
  const cro = runtime?.cro_review_state;
  if (!candidate || !cro) return [];
  const adjustments = new Map(
    (cro.output.required_adjustments ?? []).map((adjustment) => [adjustment.ticker, adjustment]),
  );
  return candidate.portfolio_actions
    .flatMap((position): FrozenOrderIntentView[] => {
      const adjustment = adjustments.get(position.ticker);
      if (adjustment?.adjustment === "REQUIRE_REVIEW") return [];
      const controlledTarget =
        adjustment?.adjustment === "VETO"
          ? 0
          : adjustment?.adjustment === "CAP_WEIGHT" || adjustment?.adjustment === "REDUCE_WEIGHT"
            ? Math.min(
                position.target_weight,
                adjustment.max_target_weight ?? position.target_weight,
              )
            : position.target_weight;
      const requestedDeltaWeight = controlledTarget - (position.current_weight ?? 0);
      if (Math.abs(requestedDeltaWeight) <= 1e-9) return [];
      return [
        {
          order_intent_ref: frozenOrderIntentRef({
            candidateTargetHash: candidate.candidate_target_hash,
            croReviewHash: cro.review_hash,
            tsCode: position.ticker,
            requestedDeltaWeight,
          }),
          ts_code: position.ticker,
          requested_delta_weight: requestedDeltaWeight,
        },
      ];
    })
    .sort((left, right) => left.ts_code.localeCompare(right.ts_code));
}

function finalResolutionReasons(
  submission: CioFinalSubmission,
  ticker: string,
  state: DailyCycleStateType,
): string[] {
  const croByLocal = runtimeCroActionsByLocalId(state);
  const executionByLocal = runtimeExecutionAssessmentsByLocalId(state);
  return [
    ...submission.cro_control_resolutions
      .filter((resolution) => croByLocal.get(resolution.cro_action_local_ref)?.ticker === ticker)
      .map((resolution) => resolution.reason),
    ...submission.execution_control_resolutions
      .filter(
        (resolution) =>
          executionByLocal.get(resolution.execution_assessment_local_ref)?.ticker === ticker,
      )
      .map((resolution) => resolution.reason),
  ];
}

function finalDissentRefs(
  submission: CioFinalSubmission,
  state: DailyCycleStateType,
): CioFinalOutput["dissent_refs"] {
  const runtime = state.layer4_outputs.runtime;
  const croByLocal = runtimeCroActionsByLocalId(state);
  const executionByLocal = runtimeExecutionAssessmentsByLocalId(state);
  return [
    ...submission.cro_control_resolutions.flatMap((resolution) => {
      const action = croByLocal.get(resolution.cro_action_local_ref);
      return action && runtime?.cro_review_state
        ? [
            {
              ticker: action.ticker,
              source: "cro_review" as const,
              source_hash: runtime.cro_review_state.review_hash,
              reason: resolution.reason,
            },
          ]
        : [];
    }),
    ...submission.execution_control_resolutions.flatMap((resolution) => {
      const assessment = executionByLocal.get(resolution.execution_assessment_local_ref);
      return assessment && runtime?.execution_feasibility_state
        ? [
            {
              ticker: assessment.ticker,
              source: "execution_feasibility" as const,
              source_hash: runtime.execution_feasibility_state.feasibility_hash,
              reason: resolution.reason,
            },
          ]
        : [];
    }),
  ];
}

function runtimeCroActionsByLocalId(state: DailyCycleStateType): Map<string, { ticker: string }> {
  const rows = (state.layer4_outputs.cro?.required_adjustments ?? []) as Array<{
    action_local_id?: string;
    ticker: string;
  }>;
  return new Map(
    rows.flatMap((row) =>
      row.action_local_id ? [[row.action_local_id, { ticker: row.ticker }] as const] : [],
    ),
  );
}

function runtimeExecutionAssessmentsByLocalId(
  state: DailyCycleStateType,
): Map<string, { ticker: string }> {
  const rows = (state.layer4_outputs.autonomous_execution?.execution_checks ?? []) as Array<{
    assessment_local_id?: string;
    ticker: string;
  }>;
  return new Map(
    rows.flatMap((row) =>
      row.assessment_local_id ? [[row.assessment_local_id, { ticker: row.ticker }] as const] : [],
    ),
  );
}

function runtimeEnvelope(submission: DecisionAgentSubmission) {
  return {
    claims: submission.claims,
    claim_refs: submission.claim_refs,
    ...(submission.verified_claim_graph
      ? { verified_claim_graph: submission.verified_claim_graph }
      : {}),
    ...(submission.verified_claim_audit
      ? { verified_claim_audit: submission.verified_claim_audit }
      : {}),
  };
}

function executionAction(
  candidate: PortfolioAction | undefined,
  delta: number,
): "BUY" | "SELL" | "HOLD" | "REDUCE" {
  if (delta > 1e-9) return "BUY";
  if (candidate && candidate.target_weight <= 1e-9) return "SELL";
  if (delta < -1e-9) return "REDUCE";
  return "HOLD";
}

function positionAction(decision: "HOLD" | "ADD" | "REDUCE" | "EXIT"): PortfolioAction["action"] {
  return decision === "ADD"
    ? "BUY"
    : decision === "REDUCE"
      ? "REDUCE"
      : decision === "EXIT"
        ? "SELL"
        : "HOLD";
}

function legacyHoldingPeriod(
  period: "DAYS" | "WEEKS" | "MONTHS",
): PortfolioAction["holding_period"] {
  return period === "DAYS" ? "1W" : period === "WEEKS" ? "1M" : "3M";
}

function persistentRef(namespace: string, value: unknown): string {
  return `${namespace}:${canonicalAcceptedOutputHash(value).slice("sha256:".length)}`;
}
