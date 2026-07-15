import type { z } from "zod";
import type { CurrentPositionsSnapshot } from "../types.js";
import type { AgentContractIssue, ContractValidationResult } from "./agent_run_contract.js";
import { type RuntimeEvidenceSnapshot, validateOutputByClaimEvidence } from "./evidence_runtime.js";
import {
  applyResearchKnobCaps,
  type ResearchKnobsSnapshot,
  type ToolStatus,
} from "./research_knobs.js";

export function validateStrictAgentOutput<T>(input: {
  output: T;
  schema: z.ZodType<T>;
  agent: string;
  stage: string;
  runtimeEvidence: RuntimeEvidenceSnapshot | null;
  knobSnapshot: ResearchKnobsSnapshot | null;
  toolStatuses: ReadonlyArray<ToolStatus>;
  /** Accept uncertainty-only claims for an explicitly neutral/no-action output. */
  allowUncertaintyOnly?: boolean;
  currentPositions?: CurrentPositionsSnapshot;
}): ContractValidationResult<T> {
  let output = input.output;
  const issues: AgentContractIssue[] = [];
  if (!input.runtimeEvidence) {
    issues.push(issue("evidence_claim_graph_v1", "EVIDENCE_SNAPSHOT_MISSING", "$"));
  } else {
    const claimValidation = validateOutputByClaimEvidence(output, input.runtimeEvidence, {
      ...(input.allowUncertaintyOnly !== undefined
        ? { allowUncertaintyOnly: input.allowUncertaintyOnly }
        : {}),
    });
    if (!claimValidation.rawOutputAccepted) {
      issues.push(
        ...claimValidation.rejectionReasons.map((reason) =>
          issue(
            "evidence_claim_graph_v1",
            claimReasonCode(reason),
            claimReasonPath(reason),
            reason,
          ),
        ),
      );
    } else {
      output = claimValidation.output;
    }
  }

  if (input.knobSnapshot) {
    try {
      const capped = applyResearchKnobCaps(input.output, input.knobSnapshot, {
        toolStatuses: input.toolStatuses,
      });
      if (capped.audit.unsupported_knob_influence_ids.length > 0) {
        for (const knobId of capped.audit.unsupported_knob_influence_ids) {
          issues.push(
            issue(
              "research_knobs_runtime_v1",
              "UNSUPPORTED_KNOB_INFLUENCE",
              "$.declared_knob_influence_ids",
              knobId,
            ),
          );
        }
      }
      if (
        capped.audit.pre_cap_confidence !== null &&
        capped.audit.post_cap_confidence !== capped.audit.pre_cap_confidence
      ) {
        issues.push(
          issue(
            "research_knobs_runtime_v1",
            "CONFIDENCE_CAP_EXCEEDED",
            "$.confidence",
            `maximum allowed confidence is ${capped.audit.post_cap_confidence}`,
          ),
        );
      } else if (issues.length === 0) {
        // Audit attachment is allowed; the model-authored decision is unchanged.
        output = { ...(output as object), verified_knob_audit: capped.audit } as T;
      }
    } catch (error) {
      issues.push(
        issue(
          "research_knobs_runtime_v1",
          "KNOB_SEMANTIC_REJECTED",
          "$.declared_knob_influence_ids",
          error instanceof Error ? error.message : String(error),
        ),
      );
    }
  }

  issues.push(
    ...validateDispositionAndCioCoverage(input.output, input.agent, input.currentPositions),
  );
  return { output, issues };
}

function validateDispositionAndCioCoverage(
  output: unknown,
  agent: string,
  currentPositions?: CurrentPositionsSnapshot,
): AgentContractIssue[] {
  if (agent !== "cio" || !currentPositions) return [];
  const record = output as {
    decision_disposition?: string;
    claim_refs?: string[];
    decision_claim_refs?: string[];
    portfolio_actions?: Array<{
      ticker: string;
      action: string;
      target_weight: number;
      position_decision?: string;
      current_weight?: number;
    }>;
    position_reviews?: Array<{ ticker: string }>;
  };
  const actions = record.portfolio_actions ?? [];
  const positions = currentPositions.positions;
  const positionByTicker = new Map(positions.map((position) => [position.ticker, position]));
  const actionByTicker = new Map(actions.map((action) => [action.ticker, action]));
  const issues: AgentContractIssue[] = [];
  const decisionClaimRefs = record.decision_claim_refs;
  if (
    record.claim_refs &&
    decisionClaimRefs &&
    (record.claim_refs.length !== decisionClaimRefs.length ||
      [...record.claim_refs]
        .sort()
        .some((ref, index) => ref !== [...decisionClaimRefs].sort()[index]))
  ) {
    issues.push(
      issue("cio_position_semantics_v1", "DECISION_CLAIM_REFS_MISMATCH", "$.decision_claim_refs"),
    );
  }
  for (const position of positions) {
    if (!actionByTicker.has(position.ticker)) {
      issues.push(
        issue(
          "cio_position_semantics_v1",
          "CURRENT_POSITION_OMITTED",
          "$.portfolio_actions",
          position.ticker,
        ),
      );
    }
  }
  if (record.decision_disposition === "HOLD_CURRENT") {
    if (positions.length === 0) {
      issues.push(
        issue("cio_position_semantics_v1", "EMPTY_PORTFOLIO_CANNOT_HOLD", "$.decision_disposition"),
      );
    }
    for (const action of actions) {
      const position = positionByTicker.get(action.ticker);
      if (!position) {
        issues.push(
          issue("cio_position_semantics_v1", "HOLD_ADDS_NEW_TICKER", "$.portfolio_actions"),
        );
      } else if (
        action.action !== "HOLD" ||
        Math.abs(action.target_weight - position.current_weight) > 1e-6
      ) {
        issues.push(
          issue(
            "cio_position_semantics_v1",
            "HOLD_CURRENT_WEIGHT_CHANGED",
            `$.portfolio_actions.${action.ticker}`,
          ),
        );
      }
    }
  }
  if (record.decision_disposition === "ALL_CASH") {
    for (const action of actions) {
      if (
        action.target_weight > 1e-9 ||
        action.action !== "SELL" ||
        action.position_decision !== "EXIT"
      ) {
        issues.push(
          issue(
            "cio_position_semantics_v1",
            "ALL_CASH_REQUIRES_EXIT",
            `$.portfolio_actions.${action.ticker}`,
          ),
        );
      }
    }
    if (positions.length === 0 && actions.length > 0) {
      issues.push(
        issue(
          "cio_position_semantics_v1",
          "EMPTY_ALL_CASH_REQUIRES_NO_ACTIONS",
          "$.portfolio_actions",
        ),
      );
    }
  }
  if (record.position_reviews) {
    const reviews = new Set(record.position_reviews.map((review) => review.ticker));
    for (const position of positions) {
      if (!reviews.has(position.ticker)) {
        issues.push(
          issue(
            "cio_position_semantics_v1",
            "POSITION_REVIEW_OMITTED",
            "$.position_reviews",
            position.ticker,
          ),
        );
      }
    }
  }
  return issues;
}

function claimReasonCode(reason: string): string {
  const head = reason.split(":", 1)[0] ?? "claim_invalid";
  return head.replace(/[^A-Za-z0-9]+/g, "_").toUpperCase();
}

function claimReasonPath(reason: string): string {
  const parts = reason.split(":");
  return parts.length > 1 && parts[1] ? `$.${parts[1].replace(/\./g, ".")}` : "$";
}

function issue(
  validator: string,
  reason_code: string,
  json_path: string,
  message = reason_code,
): AgentContractIssue {
  return { validator, reason_code, json_path, message };
}
