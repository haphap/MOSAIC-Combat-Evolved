import type { z } from "zod";
import { assertCioHoldCurrentTargetSet } from "../decision/decision_semantics.js";
import type { CurrentPositionsSnapshot } from "../types.js";
import type { AgentContractIssue, ContractValidationResult } from "./agent_run_contract.js";
import { type RuntimeEvidenceSnapshot, validateOutputByClaimEvidence } from "./evidence_runtime.js";
import {
  applyPrivateKnotPolicy,
  type PrivateKnotSnapshot,
  type ToolStatus,
} from "./private_knot_boundary.js";

export function validateStrictAgentOutput<T>(input: {
  output: T;
  schema: z.ZodType<T>;
  agent: string;
  stage: string;
  cohort: string;
  runtimeEvidence: RuntimeEvidenceSnapshot | null;
  knobSnapshot: PrivateKnotSnapshot | null;
  toolStatuses: ReadonlyArray<ToolStatus>;
  /** Accept risk-flag-only claims for an explicitly neutral/no-action output. */
  allowRiskFlagOnly?: boolean;
  currentPositions?: CurrentPositionsSnapshot;
  /** Deterministic role/stage checks that must pass before consuming one-use KNOT policy. */
  validateBeforePrivatePolicy?: (output: T) => ReadonlyArray<AgentContractIssue>;
}): ContractValidationResult<T> {
  const issues: AgentContractIssue[] = [];
  const privateLineageIssues = validateRuntimeLineage(input);
  issues.push(...privateLineageIssues);
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
  if (input.validateBeforePrivatePolicy) {
    issues.push(...input.validateBeforePrivatePolicy(output));
  }

  if (input.knobSnapshot && privateLineageIssues.length === 0 && issues.length === 0) {
    try {
      const policyResult = applyPrivateKnotPolicy({
        snapshot: input.knobSnapshot,
        output,
        toolStatuses: input.toolStatuses,
      });
      if (policyResult.audit.snapshot_hash !== input.knobSnapshot.snapshot_hash) {
        issues.push(
          issue(
            "private_knot_runtime_v1",
            "PRIVATE_KNOT_AUDIT_SNAPSHOT_MISMATCH",
            "$.private_knot_audit.snapshot_hash",
          ),
        );
      } else if (!policyResult.audit.accepted) {
        for (const reason of policyResult.audit.reason_codes) {
          issues.push(
            issue("private_knot_runtime_v1", "PRIVATE_KNOT_POLICY_REJECTED", "$", reason),
          );
        }
      } else if (issues.length === 0) {
        output = {
          ...(policyResult.output as object),
          private_knot_audit: policyResult.audit,
        } as T;
      }
    } catch (error) {
      issues.push(
        issue(
          "private_knot_runtime_v1",
          "PRIVATE_KNOT_RUNTIME_ERROR",
          "$",
          error instanceof Error ? error.message : String(error),
        ),
      );
    }
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
  cohort: string;
  runtimeEvidence: RuntimeEvidenceSnapshot | null;
  knobSnapshot: PrivateKnotSnapshot | null;
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
  if (!input.knobSnapshot) return issues;
  if (!input.runtimeEvidence?.modelContextHash) {
    issues.push(
      issue(
        "private_knot_runtime_v1",
        "PRIVATE_KNOT_MODEL_CONTEXT_MISSING",
        "$.private_knot_model_context.context_hash",
      ),
    );
  }
  if (!input.runtimeEvidence?.effectiveModelInputHash) {
    issues.push(
      issue(
        "private_knot_runtime_v1",
        "PRIVATE_KNOT_EFFECTIVE_MODEL_INPUT_HASH_MISSING",
        "$.private_knot_model_context.effective_model_input_hash",
      ),
    );
  }
  if (input.knobSnapshot.agent !== input.agent) {
    issues.push(
      issue(
        "private_knot_runtime_v1",
        "PRIVATE_KNOT_SNAPSHOT_AGENT_MISMATCH",
        "$.private_knot_snapshot.agent",
      ),
    );
  }
  if (input.knobSnapshot.stage !== input.stage) {
    issues.push(
      issue(
        "private_knot_runtime_v1",
        "PRIVATE_KNOT_SNAPSHOT_STAGE_MISMATCH",
        "$.private_knot_snapshot.stage",
      ),
    );
  }
  if (input.knobSnapshot.cohort !== input.cohort) {
    issues.push(
      issue(
        "private_knot_runtime_v1",
        "PRIVATE_KNOT_SNAPSHOT_COHORT_MISMATCH",
        "$.private_knot_snapshot.cohort",
      ),
    );
  }
  if (input.knobSnapshot.snapshot_id !== input.knobSnapshot.snapshot_hash) {
    issues.push(
      issue(
        "private_knot_runtime_v1",
        "PRIVATE_KNOT_SNAPSHOT_ID_HASH_MISMATCH",
        "$.private_knot_snapshot.snapshot_id",
      ),
    );
  }
  if (
    input.runtimeEvidence &&
    input.runtimeEvidence.snapshotHash !== input.knobSnapshot.snapshot_hash
  ) {
    issues.push(
      issue(
        "private_knot_runtime_v1",
        "RUNTIME_EVIDENCE_PRIVATE_SNAPSHOT_MISMATCH",
        "$.verified_claim_graph.snapshot_hash",
      ),
    );
  }
  if (input.runtimeEvidence && input.runtimeEvidence.runId !== input.knobSnapshot.graph_run_id) {
    issues.push(
      issue(
        "private_knot_runtime_v1",
        "RUNTIME_EVIDENCE_PRIVATE_GRAPH_RUN_MISMATCH",
        "$.verified_claim_graph.run_id",
      ),
    );
  }
  if (
    input.runtimeEvidence &&
    input.runtimeEvidence.agentInvocationId !== input.knobSnapshot.agent_invocation_id
  ) {
    issues.push(
      issue(
        "private_knot_runtime_v1",
        "RUNTIME_EVIDENCE_PRIVATE_INVOCATION_MISMATCH",
        "$.verified_claim_graph.agent_invocation_id",
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
