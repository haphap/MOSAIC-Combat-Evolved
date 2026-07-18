import type { DarwinianAgentBehaviorBinding } from "../../autoresearch/production_variant.js";
import { canonicalAcceptedOutputHash } from "../accepted_output.js";
import type { LlmResearchClaim } from "../evidence_contract.js";
import type {
  AcceptedMacroInputAttribution,
  MacroAttributionTarget,
  MacroInputAttributionSubmission,
} from "../helpers/macro_attribution.js";
import type { KnobInfluenceDeclaration } from "../types.js";

export interface DecisionDriverSubmission {
  driver_local_id: string;
  summary: string;
  claim_refs: string[];
}

export interface DecisionRiskSubmission {
  risk_local_id: string;
  summary: string;
  claim_refs: string[];
}

export interface CroCandidateRiskActionSubmission {
  action_local_id: string;
  candidate_ref: string;
  ts_code: string;
  action: "VETO" | "CAP_WEIGHT" | "REDUCE_WEIGHT" | "REQUIRE_REVIEW" | "NO_OBJECTION";
  predicted_risk_probability: number;
  max_target_weight: number | null;
  reason: string;
  claim_refs: string[];
}

export interface CroRiskReviewPayload {
  review_disposition: "REVIEW_ACTIONS" | "NO_OBJECTION" | "BLOCK_ALL";
  candidate_actions: CroCandidateRiskActionSubmission[];
  correlated_risks: DecisionRiskSubmission[];
  black_swan_scenarios: DecisionRiskSubmission[];
  claims: LlmResearchClaim[];
  claim_refs: string[];
}

export type CroAgentSubmission = CroRiskReviewPayload &
  KnobInfluenceDeclaration & {
    agent_id: "cro";
    confidence: number;
    macro_input_attributions: MacroInputAttributionSubmission[];
  };

export interface AlphaNovelPickSubmission {
  pick_local_id: string;
  candidate_ref: string;
  ts_code: string;
  conviction: number;
  thesis: string;
  claim_refs: string[];
}

interface AlphaDiscoveryPayloadBase {
  key_drivers: DecisionDriverSubmission[];
  risks: DecisionRiskSubmission[];
  claims: LlmResearchClaim[];
  claim_refs: string[];
}

export type AlphaDiscoveryPayload =
  | (AlphaDiscoveryPayloadBase & {
      discovery_disposition: "CANDIDATES";
      novel_picks: [AlphaNovelPickSubmission, ...AlphaNovelPickSubmission[]];
    })
  | (AlphaDiscoveryPayloadBase & {
      discovery_disposition: "NONE_FOUND";
      novel_picks: [];
    });

export type AlphaDiscoverySubmission = AlphaDiscoveryPayload &
  KnobInfluenceDeclaration & {
    agent_id: "alpha_discovery";
    confidence: number;
    macro_input_attributions: MacroInputAttributionSubmission[];
  };

export interface ExecutionOrderAssessmentSubmission {
  assessment_local_id: string;
  order_intent_ref: string;
  ts_code: string;
  requested_delta_weight: number;
  feasibility: "FEASIBLE" | "PARTIAL" | "BLOCKED";
  feasibility_confidence: number;
  predicted_cost_bps: number;
  max_executable_delta_weight: number | null;
  recommended_slice_count: number;
  reason: string;
  claim_refs: string[];
}

interface ExecutionAssessmentPayloadBase {
  order_assessments: [ExecutionOrderAssessmentSubmission, ...ExecutionOrderAssessmentSubmission[]];
  claims: LlmResearchClaim[];
  claim_refs: string[];
}

export type ExecutionAssessmentPayload = ExecutionAssessmentPayloadBase & {
  execution_disposition: "ORDERS_ASSESSED" | "BLOCKED";
};

export type AutonomousExecutionSubmission = ExecutionAssessmentPayload &
  KnobInfluenceDeclaration & {
    agent_id: "autonomous_execution";
    confidence: number;
  };

export interface CioTargetPositionSubmission {
  position_local_id: string;
  ts_code: string;
  target_weight: number;
  position_decision: "HOLD" | "ADD" | "REDUCE" | "EXIT";
  holding_period: "DAYS" | "WEEKS" | "MONTHS";
  thesis_status: "INTACT" | "WEAKENED" | "BROKEN" | "EXPIRED";
  risk_flags: string[];
  claim_refs: string[];
}

interface CioPortfolioDecisionPayloadBase {
  cash_weight: number;
  decision_reason: string;
  claims: LlmResearchClaim[];
  claim_refs: string[];
}

export type CioPortfolioDecisionPayload =
  | (CioPortfolioDecisionPayloadBase & {
      decision_disposition: "TARGET_PORTFOLIO";
      target_positions: [CioTargetPositionSubmission, ...CioTargetPositionSubmission[]];
    })
  | (CioPortfolioDecisionPayloadBase & {
      decision_disposition: "HOLD_CURRENT";
      target_positions: CioTargetPositionSubmission[];
    })
  | (CioPortfolioDecisionPayloadBase & {
      decision_disposition: "ALL_CASH";
      target_positions: [];
      cash_weight: 1;
    });

export type CioProposalSubmission = CioPortfolioDecisionPayload &
  KnobInfluenceDeclaration & {
    agent_id: "cio";
    decision_stage: "PROPOSAL";
    confidence: number;
    macro_input_attributions: MacroInputAttributionSubmission[];
  };

export interface CioCroControlResolutionSubmission {
  cro_action_local_ref: string;
  resolution: "COMPLIED" | "MORE_CONSERVATIVE";
  reason: string;
  claim_refs: string[];
}

export interface CioExecutionControlResolutionSubmission {
  execution_assessment_local_ref: string;
  resolution: "COMPLIED" | "MORE_CONSERVATIVE";
  reason: string;
  claim_refs: string[];
}

export type CioFinalSubmission = CioPortfolioDecisionPayload &
  KnobInfluenceDeclaration & {
    agent_id: "cio";
    decision_stage: "FINAL";
    confidence: number;
    cro_control_resolutions: CioCroControlResolutionSubmission[];
    execution_control_resolutions: CioExecutionControlResolutionSubmission[];
    macro_input_attributions: MacroInputAttributionSubmission[];
  };

export type DecisionAgentSubmission =
  | CroAgentSubmission
  | AlphaDiscoverySubmission
  | AutonomousExecutionSubmission
  | CioProposalSubmission
  | CioFinalSubmission;

export interface AcceptedCroRiskAction extends CroCandidateRiskActionSubmission {
  cro_action_ref: string;
  cro_action_hash: string;
}

export interface AcceptedCroRiskReviewPayload
  extends Omit<CroRiskReviewPayload, "candidate_actions"> {
  candidate_actions: AcceptedCroRiskAction[];
}

export interface AcceptedCroRiskReview {
  agent_id: "cro";
  agent_contract_version: string;
  prompt_behavior_version: string;
  execution_behavior_version: string;
  accepted_cro_review_id: string;
  accepted_cro_review_hash: string;
  frozen_proposal_id: string;
  frozen_proposal_hash: string;
  frozen_candidate_universe_id: string;
  frozen_candidate_universe_hash: string;
  review: AcceptedCroRiskReviewPayload;
  accepted_macro_input_attributions: AcceptedMacroInputAttribution[];
  model_confidence: number;
}

export interface AcceptedAlphaDiscovery {
  agent_id: "alpha_discovery";
  agent_contract_version: string;
  prompt_behavior_version: string;
  execution_behavior_version: string;
  accepted_alpha_discovery_id: string;
  accepted_alpha_discovery_hash: string;
  frozen_novel_candidate_universe_id: string;
  frozen_novel_candidate_universe_hash: string;
  selection: AlphaDiscoveryPayload;
  accepted_macro_input_attributions: AcceptedMacroInputAttribution[];
  model_confidence: number;
}

export interface AcceptedExecutionOrderAssessment extends ExecutionOrderAssessmentSubmission {
  execution_assessment_ref: string;
  execution_assessment_hash: string;
}

export type AcceptedExecutionAssessmentPayload = Omit<
  ExecutionAssessmentPayload,
  "order_assessments"
> & {
  order_assessments: [AcceptedExecutionOrderAssessment, ...AcceptedExecutionOrderAssessment[]];
};

export interface DecisionStageAcceptedSourceRef<
  A extends "alpha_discovery" | "cro" | "autonomous_execution",
> {
  source_status: "ACCEPTED_OUTPUT";
  agent_id: A;
  accepted_output_id: string;
  accepted_output_hash: string;
  stage_skip_id: null;
  stage_skip_hash: null;
}

export interface DecisionStageSkippedSourceRef<
  A extends "alpha_discovery" | "cro" | "autonomous_execution",
> {
  source_status: "NO_EVALUATION_OBJECT";
  agent_id: A;
  accepted_output_id: null;
  accepted_output_hash: null;
  stage_skip_id: string;
  stage_skip_hash: string;
}

export type DecisionStageSourceRef<A extends "alpha_discovery" | "cro" | "autonomous_execution"> =
  | DecisionStageAcceptedSourceRef<A>
  | DecisionStageSkippedSourceRef<A>;

export type DecisionControlSourceRef<A extends "cro" | "autonomous_execution"> =
  DecisionStageSourceRef<A>;

export interface AcceptedExecutionAssessment {
  agent_id: "autonomous_execution";
  agent_contract_version: string;
  prompt_behavior_version: string;
  execution_behavior_version: string;
  accepted_execution_assessment_id: string;
  accepted_execution_assessment_hash: string;
  execution_mode: "PAPER" | "REAL";
  frozen_proposal_id: string;
  frozen_proposal_hash: string;
  cro_control_source: DecisionControlSourceRef<"cro">;
  frozen_order_intent_set_id: string;
  frozen_order_intent_set_hash: string;
  assessment: AcceptedExecutionAssessmentPayload;
  model_confidence: number;
}

export interface AcceptedCioCroControlResolution {
  cro_action_ref: string;
  cro_action_hash: string;
  resolution: "COMPLIED" | "MORE_CONSERVATIVE";
  reason: string;
  claim_refs: string[];
}

export interface AcceptedCioExecutionControlResolution {
  execution_assessment_ref: string;
  execution_assessment_hash: string;
  resolution: "COMPLIED" | "MORE_CONSERVATIVE";
  reason: string;
  claim_refs: string[];
}

export interface AcceptedCioProposal {
  agent_id: "cio";
  decision_stage: "PROPOSAL";
  agent_contract_version: string;
  prompt_behavior_version: string;
  execution_behavior_version: string;
  frozen_pre_cio_input_id: string;
  frozen_pre_cio_input_hash: string;
  alpha_source: DecisionStageSourceRef<"alpha_discovery">;
  alpha_pick_resolutions: AcceptedCioAlphaPickResolution[];
  proposal_id: string;
  proposal_hash: string;
  decision: CioPortfolioDecisionPayload;
  accepted_macro_input_attributions: AcceptedMacroInputAttribution[];
  model_confidence: number;
}

export interface AcceptedCioAlphaPickResolution {
  alpha_pick_local_ref: string;
  ts_code: string;
  resolution: "INCLUDED" | "NOT_INCLUDED";
  target_position_local_ref: string | null;
  reason: string;
}

export interface AcceptedCioFinal {
  agent_id: "cio";
  decision_stage: "FINAL";
  agent_contract_version: string;
  prompt_behavior_version: string;
  execution_behavior_version: string;
  frozen_proposal_id: string;
  frozen_proposal_hash: string;
  cro_control_source: DecisionControlSourceRef<"cro">;
  execution_control_source: DecisionControlSourceRef<"autonomous_execution">;
  final_portfolio_id: string;
  final_portfolio_hash: string;
  decision: CioPortfolioDecisionPayload;
  cro_control_resolutions: AcceptedCioCroControlResolution[];
  execution_control_resolutions: AcceptedCioExecutionControlResolution[];
  accepted_macro_input_attributions: AcceptedMacroInputAttribution[];
  model_confidence: number;
}

export type AcceptedDecisionOutput =
  | AcceptedCroRiskReview
  | AcceptedAlphaDiscovery
  | AcceptedExecutionAssessment
  | AcceptedCioProposal
  | AcceptedCioFinal;

export interface ModelVisibleAcceptedCroRiskReview {
  agent_id: "cro";
  review: CroRiskReviewPayload;
}

export interface ModelVisibleAcceptedAlphaDiscovery {
  agent_id: "alpha_discovery";
  selection: AlphaDiscoveryPayload;
}

export interface ModelVisibleAcceptedExecutionAssessment {
  agent_id: "autonomous_execution";
  execution_mode: "PAPER" | "REAL";
  assessment: ExecutionAssessmentPayload;
}

export interface ModelVisibleAcceptedCioProposal {
  agent_id: "cio";
  decision_stage: "PROPOSAL";
  decision: CioPortfolioDecisionPayload;
}

export interface ModelVisibleAcceptedCioFinal {
  agent_id: "cio";
  decision_stage: "FINAL";
  decision: CioPortfolioDecisionPayload;
}

export function croRiskReviewPayload(submission: CroAgentSubmission): CroRiskReviewPayload {
  return {
    review_disposition: submission.review_disposition,
    candidate_actions: submission.candidate_actions,
    correlated_risks: submission.correlated_risks,
    black_swan_scenarios: submission.black_swan_scenarios,
    claims: submission.claims,
    claim_refs: submission.claim_refs,
  };
}

export function alphaDiscoveryPayload(submission: AlphaDiscoverySubmission): AlphaDiscoveryPayload {
  return submission.discovery_disposition === "CANDIDATES"
    ? {
        discovery_disposition: "CANDIDATES",
        novel_picks: submission.novel_picks,
        key_drivers: submission.key_drivers,
        risks: submission.risks,
        claims: submission.claims,
        claim_refs: submission.claim_refs,
      }
    : {
        discovery_disposition: "NONE_FOUND",
        novel_picks: [],
        key_drivers: submission.key_drivers,
        risks: submission.risks,
        claims: submission.claims,
        claim_refs: submission.claim_refs,
      };
}

export function executionAssessmentPayload(
  submission: AutonomousExecutionSubmission,
): ExecutionAssessmentPayload {
  return {
    execution_disposition: submission.execution_disposition,
    order_assessments: submission.order_assessments,
    claims: submission.claims,
    claim_refs: submission.claim_refs,
  };
}

export function cioDecisionPayload(
  submission: CioProposalSubmission | CioFinalSubmission,
): CioPortfolioDecisionPayload {
  const common = {
    cash_weight: submission.cash_weight,
    decision_reason: submission.decision_reason,
    claims: submission.claims,
    claim_refs: submission.claim_refs,
  };
  if (submission.decision_disposition === "TARGET_PORTFOLIO") {
    return {
      decision_disposition: "TARGET_PORTFOLIO",
      target_positions: submission.target_positions,
      ...common,
    };
  }
  if (submission.decision_disposition === "ALL_CASH") {
    return {
      decision_disposition: "ALL_CASH",
      target_positions: [],
      ...common,
      cash_weight: 1,
    };
  }
  return {
    decision_disposition: "HOLD_CURRENT",
    target_positions: submission.target_positions,
    ...common,
  };
}

export function decisionMacroAttributionTargets(
  submission:
    | CroAgentSubmission
    | AlphaDiscoverySubmission
    | CioProposalSubmission
    | CioFinalSubmission,
): MacroAttributionTarget[] {
  if (submission.agent_id === "cro") {
    return submission.candidate_actions.map((action) => ({
      target_type: "RISK_ACTION",
      target_local_ref: action.action_local_id,
      target: action,
    }));
  }
  if (submission.agent_id === "alpha_discovery") {
    return submission.novel_picks.map((pick) => ({
      target_type: "SECURITY_PICK",
      target_local_ref: pick.pick_local_id,
      target: pick,
    }));
  }
  return submission.target_positions.map((position) => ({
    target_type: "PORTFOLIO_DECISION",
    target_local_ref: position.position_local_id,
    target: position,
  }));
}

export function buildAcceptedCroRiskReview(input: {
  submission: CroAgentSubmission;
  behavior: DarwinianAgentBehaviorBinding;
  frozenProposalId: string;
  frozenProposalHash: string;
  frozenCandidateUniverseId: string;
  frozenCandidateUniverseHash: string;
  acceptedMacroInputAttributions: AcceptedMacroInputAttribution[];
}): AcceptedCroRiskReview {
  const payload = croRiskReviewPayload(input.submission);
  const seed = {
    agent_id: "cro",
    frozen_proposal_id: input.frozenProposalId,
    frozen_proposal_hash: input.frozenProposalHash,
    frozen_candidate_universe_id: input.frozenCandidateUniverseId,
    frozen_candidate_universe_hash: input.frozenCandidateUniverseHash,
    review: payload,
    accepted_macro_input_attributions: input.acceptedMacroInputAttributions,
  };
  const acceptedReviewId = persistentId("accepted-cro-review", seed);
  const candidateActions = payload.candidate_actions
    .map((action): AcceptedCroRiskAction => {
      const croActionHash = canonicalAcceptedOutputHash({
        accepted_cro_review_id: acceptedReviewId,
        action_local_id: action.action_local_id,
        action,
      });
      return {
        ...action,
        cro_action_ref: `cro-action:${croActionHash.slice("sha256:".length)}`,
        cro_action_hash: croActionHash,
      };
    })
    .sort((left, right) => left.action_local_id.localeCompare(right.action_local_id));
  const withoutHash = {
    agent_id: "cro" as const,
    agent_contract_version: input.behavior.agent_contract_version,
    prompt_behavior_version: input.behavior.prompt_behavior_version,
    execution_behavior_version: input.behavior.execution_behavior_version,
    accepted_cro_review_id: acceptedReviewId,
    frozen_proposal_id: input.frozenProposalId,
    frozen_proposal_hash: input.frozenProposalHash,
    frozen_candidate_universe_id: input.frozenCandidateUniverseId,
    frozen_candidate_universe_hash: input.frozenCandidateUniverseHash,
    review: { ...payload, candidate_actions: candidateActions },
    accepted_macro_input_attributions: input.acceptedMacroInputAttributions,
    model_confidence: input.submission.confidence,
  };
  return {
    ...withoutHash,
    accepted_cro_review_hash: canonicalAcceptedOutputHash(withoutHash),
  };
}

export function buildAcceptedAlphaDiscovery(input: {
  submission: AlphaDiscoverySubmission;
  behavior: DarwinianAgentBehaviorBinding;
  frozenNovelCandidateUniverseId: string;
  frozenNovelCandidateUniverseHash: string;
  acceptedMacroInputAttributions: AcceptedMacroInputAttribution[];
}): AcceptedAlphaDiscovery {
  const selection = alphaDiscoveryPayload(input.submission);
  const withoutHash = {
    agent_id: "alpha_discovery" as const,
    agent_contract_version: input.behavior.agent_contract_version,
    prompt_behavior_version: input.behavior.prompt_behavior_version,
    execution_behavior_version: input.behavior.execution_behavior_version,
    frozen_novel_candidate_universe_id: input.frozenNovelCandidateUniverseId,
    frozen_novel_candidate_universe_hash: input.frozenNovelCandidateUniverseHash,
    selection,
    accepted_macro_input_attributions: input.acceptedMacroInputAttributions,
    model_confidence: input.submission.confidence,
  };
  const acceptedAlphaDiscoveryId = persistentId("accepted-alpha-discovery", withoutHash);
  const hashBody = {
    ...withoutHash,
    accepted_alpha_discovery_id: acceptedAlphaDiscoveryId,
  };
  return {
    ...hashBody,
    accepted_alpha_discovery_hash: canonicalAcceptedOutputHash(hashBody),
  };
}

export function buildAcceptedExecutionAssessment(input: {
  submission: AutonomousExecutionSubmission;
  behavior: DarwinianAgentBehaviorBinding;
  executionMode: "PAPER" | "REAL";
  frozenProposalId: string;
  frozenProposalHash: string;
  croControlSource: DecisionControlSourceRef<"cro">;
  frozenOrderIntentSetId: string;
  frozenOrderIntentSetHash: string;
}): AcceptedExecutionAssessment {
  const payload = executionAssessmentPayload(input.submission);
  const seed = {
    agent_id: "autonomous_execution",
    frozen_proposal_id: input.frozenProposalId,
    frozen_proposal_hash: input.frozenProposalHash,
    cro_control_source: input.croControlSource,
    frozen_order_intent_set_id: input.frozenOrderIntentSetId,
    frozen_order_intent_set_hash: input.frozenOrderIntentSetHash,
    assessment: payload,
  };
  const acceptedId = persistentId("accepted-execution-assessment", seed);
  const orderAssessments = payload.order_assessments
    .map((assessment): AcceptedExecutionOrderAssessment => {
      const assessmentHash = canonicalAcceptedOutputHash({
        accepted_execution_assessment_id: acceptedId,
        assessment_local_id: assessment.assessment_local_id,
        assessment,
      });
      return {
        ...assessment,
        execution_assessment_ref: `execution-assessment:${assessmentHash.slice("sha256:".length)}`,
        execution_assessment_hash: assessmentHash,
      };
    })
    .sort((left, right) => left.assessment_local_id.localeCompare(right.assessment_local_id)) as [
    AcceptedExecutionOrderAssessment,
    ...AcceptedExecutionOrderAssessment[],
  ];
  const withoutHash = {
    agent_id: "autonomous_execution" as const,
    agent_contract_version: input.behavior.agent_contract_version,
    prompt_behavior_version: input.behavior.prompt_behavior_version,
    execution_behavior_version: input.behavior.execution_behavior_version,
    accepted_execution_assessment_id: acceptedId,
    execution_mode: input.executionMode,
    frozen_proposal_id: input.frozenProposalId,
    frozen_proposal_hash: input.frozenProposalHash,
    cro_control_source: input.croControlSource,
    frozen_order_intent_set_id: input.frozenOrderIntentSetId,
    frozen_order_intent_set_hash: input.frozenOrderIntentSetHash,
    assessment: { ...payload, order_assessments: orderAssessments },
    model_confidence: input.submission.confidence,
  };
  return {
    ...withoutHash,
    accepted_execution_assessment_hash: canonicalAcceptedOutputHash(withoutHash),
  };
}

export function buildAcceptedCioProposal(input: {
  submission: CioProposalSubmission;
  behavior: DarwinianAgentBehaviorBinding;
  frozenPreCioInputId: string;
  frozenPreCioInputHash: string;
  alphaSource: DecisionStageSourceRef<"alpha_discovery">;
  acceptedAlphaDiscovery: AcceptedAlphaDiscovery | null;
  acceptedMacroInputAttributions: AcceptedMacroInputAttribution[];
}): AcceptedCioProposal {
  assertAlphaSource(input.alphaSource, input.acceptedAlphaDiscovery);
  const decision = cioDecisionPayload(input.submission);
  const targetByTicker = new Map(
    decision.target_positions.map((position) => [position.ts_code, position.position_local_id]),
  );
  const alphaPickResolutions = (input.acceptedAlphaDiscovery?.selection.novel_picks ?? [])
    .map((pick): AcceptedCioAlphaPickResolution => {
      const targetPositionLocalRef = targetByTicker.get(pick.ts_code) ?? null;
      return {
        alpha_pick_local_ref: pick.pick_local_id,
        ts_code: pick.ts_code,
        resolution: targetPositionLocalRef ? "INCLUDED" : "NOT_INCLUDED",
        target_position_local_ref: targetPositionLocalRef,
        reason: targetPositionLocalRef
          ? "The proposal includes this frozen Alpha candidate."
          : input.submission.decision_reason,
      };
    })
    .sort((left, right) => left.alpha_pick_local_ref.localeCompare(right.alpha_pick_local_ref));
  const withoutIdentity = {
    agent_id: "cio" as const,
    decision_stage: "PROPOSAL" as const,
    agent_contract_version: input.behavior.agent_contract_version,
    prompt_behavior_version: input.behavior.prompt_behavior_version,
    execution_behavior_version: input.behavior.execution_behavior_version,
    frozen_pre_cio_input_id: input.frozenPreCioInputId,
    frozen_pre_cio_input_hash: input.frozenPreCioInputHash,
    alpha_source: input.alphaSource,
    alpha_pick_resolutions: alphaPickResolutions,
    decision,
    accepted_macro_input_attributions: input.acceptedMacroInputAttributions,
    model_confidence: input.submission.confidence,
  };
  const proposalId = persistentId("cio-proposal", withoutIdentity);
  const hashBody = { ...withoutIdentity, proposal_id: proposalId };
  return { ...hashBody, proposal_hash: canonicalAcceptedOutputHash(hashBody) };
}

function assertAlphaSource(
  source: DecisionStageSourceRef<"alpha_discovery">,
  accepted: AcceptedAlphaDiscovery | null,
): void {
  if (source.source_status === "ACCEPTED_OUTPUT") {
    if (!accepted) {
      throw new Error("CIO proposal Alpha accepted source mismatch");
    }
    return;
  }
  if (accepted)
    throw new Error("CIO proposal cannot pair an Alpha stage skip with accepted output");
}

export function buildAcceptedCioFinal(input: {
  submission: CioFinalSubmission;
  behavior: DarwinianAgentBehaviorBinding;
  frozenProposalId: string;
  frozenProposalHash: string;
  croControlSource: DecisionControlSourceRef<"cro">;
  executionControlSource: DecisionControlSourceRef<"autonomous_execution">;
  acceptedCroReview: AcceptedCroRiskReview | null;
  acceptedExecutionAssessment: AcceptedExecutionAssessment | null;
  acceptedMacroInputAttributions: AcceptedMacroInputAttribution[];
}): AcceptedCioFinal {
  const croResolutions = resolveCroControls(input.submission, input.acceptedCroReview);
  const executionResolutions = resolveExecutionControls(
    input.submission,
    input.acceptedExecutionAssessment,
  );
  assertResolutionSource("cro", input.croControlSource, input.acceptedCroReview);
  assertResolutionSource(
    "autonomous_execution",
    input.executionControlSource,
    input.acceptedExecutionAssessment,
  );
  const withoutIdentity = {
    agent_id: "cio" as const,
    decision_stage: "FINAL" as const,
    agent_contract_version: input.behavior.agent_contract_version,
    prompt_behavior_version: input.behavior.prompt_behavior_version,
    execution_behavior_version: input.behavior.execution_behavior_version,
    frozen_proposal_id: input.frozenProposalId,
    frozen_proposal_hash: input.frozenProposalHash,
    cro_control_source: input.croControlSource,
    execution_control_source: input.executionControlSource,
    decision: cioDecisionPayload(input.submission),
    cro_control_resolutions: croResolutions,
    execution_control_resolutions: executionResolutions,
    accepted_macro_input_attributions: input.acceptedMacroInputAttributions,
    model_confidence: input.submission.confidence,
  };
  const finalPortfolioId = persistentId("cio-final-portfolio", withoutIdentity);
  const hashBody = { ...withoutIdentity, final_portfolio_id: finalPortfolioId };
  return { ...hashBody, final_portfolio_hash: canonicalAcceptedOutputHash(hashBody) };
}

export function modelVisibleAcceptedDecision(
  accepted: AcceptedDecisionOutput,
):
  | ModelVisibleAcceptedCroRiskReview
  | ModelVisibleAcceptedAlphaDiscovery
  | ModelVisibleAcceptedExecutionAssessment
  | ModelVisibleAcceptedCioProposal
  | ModelVisibleAcceptedCioFinal {
  if (accepted.agent_id === "cro") {
    return {
      agent_id: "cro",
      review: {
        ...accepted.review,
        candidate_actions: accepted.review.candidate_actions.map(
          ({ cro_action_ref: _ref, cro_action_hash: _hash, ...action }) => action,
        ),
      },
    };
  }
  if (accepted.agent_id === "alpha_discovery") {
    return { agent_id: "alpha_discovery", selection: accepted.selection };
  }
  if (accepted.agent_id === "autonomous_execution") {
    return {
      agent_id: "autonomous_execution",
      execution_mode: accepted.execution_mode,
      assessment: {
        ...accepted.assessment,
        order_assessments: accepted.assessment.order_assessments.map(
          ({ execution_assessment_ref: _ref, execution_assessment_hash: _hash, ...assessment }) =>
            assessment,
        ) as [ExecutionOrderAssessmentSubmission, ...ExecutionOrderAssessmentSubmission[]],
      },
    };
  }
  return {
    agent_id: "cio",
    decision_stage: accepted.decision_stage,
    decision: accepted.decision,
  };
}

function resolveCroControls(
  submission: CioFinalSubmission,
  accepted: AcceptedCroRiskReview | null,
): AcceptedCioCroControlResolution[] {
  if (!accepted) {
    if (submission.cro_control_resolutions.length !== 0) {
      throw new Error("CIO final cannot resolve CRO actions without an accepted CRO review");
    }
    return [];
  }
  const required = accepted.review.candidate_actions.filter(
    (action) => action.action !== "NO_OBJECTION",
  );
  const byLocalId = uniqueBy(
    submission.cro_control_resolutions,
    (resolution) => resolution.cro_action_local_ref,
    "CRO resolution",
  );
  if (byLocalId.size !== required.length) {
    throw new Error("CIO final must resolve every non-NO_OBJECTION CRO action exactly once");
  }
  return required
    .map((action): AcceptedCioCroControlResolution => {
      const resolution = byLocalId.get(action.action_local_id);
      if (!resolution) throw new Error(`CIO final omitted CRO action ${action.action_local_id}`);
      return {
        cro_action_ref: action.cro_action_ref,
        cro_action_hash: action.cro_action_hash,
        resolution: resolution.resolution,
        reason: resolution.reason,
        claim_refs: resolution.claim_refs,
      };
    })
    .sort((left, right) => left.cro_action_ref.localeCompare(right.cro_action_ref));
}

function resolveExecutionControls(
  submission: CioFinalSubmission,
  accepted: AcceptedExecutionAssessment | null,
): AcceptedCioExecutionControlResolution[] {
  if (!accepted) {
    if (submission.execution_control_resolutions.length !== 0) {
      throw new Error(
        "CIO final cannot resolve execution assessments without an accepted assessment",
      );
    }
    return [];
  }
  const required = accepted.assessment.order_assessments;
  const byLocalId = uniqueBy(
    submission.execution_control_resolutions,
    (resolution) => resolution.execution_assessment_local_ref,
    "execution resolution",
  );
  if (byLocalId.size !== required.length) {
    throw new Error("CIO final must resolve every execution assessment exactly once");
  }
  return required
    .map((assessment): AcceptedCioExecutionControlResolution => {
      const resolution = byLocalId.get(assessment.assessment_local_id);
      if (!resolution) {
        throw new Error(`CIO final omitted execution assessment ${assessment.assessment_local_id}`);
      }
      return {
        execution_assessment_ref: assessment.execution_assessment_ref,
        execution_assessment_hash: assessment.execution_assessment_hash,
        resolution: resolution.resolution,
        reason: resolution.reason,
        claim_refs: resolution.claim_refs,
      };
    })
    .sort((left, right) =>
      left.execution_assessment_ref.localeCompare(right.execution_assessment_ref),
    );
}

function assertResolutionSource(
  agentId: "cro" | "autonomous_execution",
  source: DecisionControlSourceRef<"cro"> | DecisionControlSourceRef<"autonomous_execution">,
  accepted: AcceptedCroRiskReview | AcceptedExecutionAssessment | null,
): void {
  if (source.agent_id !== agentId) throw new Error(`${agentId}: control source owner mismatch`);
  if (source.source_status === "ACCEPTED_OUTPUT" && !accepted) {
    throw new Error(`${agentId}: accepted control source is unavailable`);
  }
  if (source.source_status === "NO_EVALUATION_OBJECT" && accepted) {
    throw new Error(`${agentId}: stage skip cannot mask an accepted control output`);
  }
}

function uniqueBy<T>(
  values: readonly T[],
  keyFor: (value: T) => string,
  label: string,
): Map<string, T> {
  const result = new Map<string, T>();
  for (const value of values) {
    const key = keyFor(value);
    if (result.has(key)) throw new Error(`${label} local ref is duplicated: ${key}`);
    result.set(key, value);
  }
  return result;
}

function persistentId(namespace: string, value: unknown): string {
  return `${namespace}:${canonicalAcceptedOutputHash(value).slice("sha256:".length)}`;
}
