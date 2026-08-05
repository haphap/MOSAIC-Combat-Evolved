import type { z } from "zod";
import { assertCioHoldCurrentTargetSet } from "../decision/decision_semantics.js";
import type { CurrentPositionsSnapshot } from "../types.js";
import type { AgentContractIssue, ContractValidationResult } from "./agent_run_contract.js";
import { type RuntimeEvidenceSnapshot, validateOutputByClaimEvidence } from "./evidence_runtime.js";

export function validateStrictAgentOutput<T>(input: {
  output: T;
  schema: z.ZodType<T>;
  agent: string;
  stage: string;
  runtimeEvidence: RuntimeEvidenceSnapshot | null;
  /** Accept risk-flag-only claims for an explicitly neutral/no-action output. */
  allowRiskFlagOnly?: boolean;
  currentPositions?: CurrentPositionsSnapshot;
  validateRoleContract?: (output: T) => ReadonlyArray<AgentContractIssue>;
}): ContractValidationResult<T> {
  const issues: AgentContractIssue[] = [];
  issues.push(...validateRuntimeLineage(input));
  const parsed = input.schema.safeParse(input.output);
  if (!parsed.success) {
    issues.push(
      ...parsed.error.issues.map((schemaIssue) =>
        issue(
          "zod_schema",
          `ZOD_${schemaIssue.code.toUpperCase()}`,
          zodJsonPath(schemaIssue.path),
          schemaIssue.message,
        ),
      ),
    );
    return { output: input.output, issues };
  }
  let output = parsed.data;
  if (!input.runtimeEvidence) {
    issues.push(issue("evidence_claim_graph_v1", "EVIDENCE_SNAPSHOT_MISSING", "$"));
  } else {
    const claimValidation = validateOutputByClaimEvidence(output, input.runtimeEvidence, {
      ...(input.allowRiskFlagOnly !== undefined
        ? { allowRiskFlagOnly: input.allowRiskFlagOnly }
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

  issues.push(...validateDispositionAndCioCoverage(output, input.agent, input.currentPositions));
  if (input.validateRoleContract) {
    issues.push(...input.validateRoleContract(output));
  }

  return { output, issues };
}

function zodJsonPath(path: ReadonlyArray<PropertyKey>): string {
  if (path.length === 0) return "$";
  return `$${path
    .map((segment) =>
      typeof segment === "number" ? `[${segment}]` : `.${String(segment).replaceAll("~", "~0")}`,
    )
    .join("")}`;
}

function validateRuntimeLineage(input: {
  agent: string;
  stage: string;
  runtimeEvidence: RuntimeEvidenceSnapshot | null;
}): AgentContractIssue[] {
  const issues: AgentContractIssue[] = [];
  if (
    input.runtimeEvidence?.agentId !== undefined &&
    input.runtimeEvidence.agentId !== input.agent
  ) {
    issues.push(
      issue(
        "evidence_claim_graph_v1",
        "RUNTIME_EVIDENCE_AGENT_MISMATCH",
        "$.verified_claim_graph.agent_id",
      ),
    );
  }
  if (input.runtimeEvidence?.stage !== undefined && input.runtimeEvidence.stage !== input.stage) {
    issues.push(
      issue(
        "evidence_claim_graph_v1",
        "RUNTIME_EVIDENCE_STAGE_MISMATCH",
        "$.verified_claim_graph.stage",
      ),
    );
  }
  return issues;
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
    target_positions?: Array<{
      ts_code: string;
      target_weight: number;
      position_decision: "HOLD" | "ADD" | "REDUCE" | "EXIT";
    }>;
    position_reviews?: Array<{ ticker: string }>;
  };
  const actions =
    record.portfolio_actions ??
    (record.target_positions ?? []).map((position) => ({
      ticker: position.ts_code,
      target_weight: position.target_weight,
      position_decision: position.position_decision,
      action:
        position.position_decision === "ADD"
          ? "BUY"
          : position.position_decision === "REDUCE"
            ? "REDUCE"
            : position.position_decision === "EXIT"
              ? "SELL"
              : "HOLD",
    }));
  const positions = currentPositions.positions;
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
    try {
      assertCioHoldCurrentTargetSet({
        decisionDisposition: record.decision_disposition,
        targets: actions.map((action) => ({
          ticker: action.ticker,
          target_weight: action.target_weight,
          position_decision: action.position_decision as
            | "HOLD"
            | "ADD"
            | "REDUCE"
            | "EXIT"
            | undefined,
        })),
        currentSnapshotStatus: currentPositions.snapshot_status,
        currentPositions: positions,
        context: "CIO strict output",
      });
    } catch (error) {
      issues.push(
        issue(
          "cio_position_semantics_v1",
          "HOLD_CURRENT_TARGET_SET_MISMATCH",
          "$.portfolio_actions",
          error instanceof Error ? error.message : String(error),
        ),
      );
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
