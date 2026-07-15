import type { DailyCycleStateType } from "../agents/state.js";

export const MAX_CONSECUTIVE_EMPTY_DECISION_DAYS = 1;

export type HistoricalDecisionFailureCode =
  | "EMPTY_DECISION_WITH_OPEN_POSITIONS"
  | "L4_FALLBACK_EMPTY_DECISION"
  | "CONSECUTIVE_EMPTY_DECISIONS"
  | "UNACCEPTED_AGENT_STAGE"
  | "UNCLASSIFIED_EMPTY_DECISION";

export interface HistoricalDecisionHealth {
  tradeDate: string;
  upstreamCandidateCount: number;
  currentPositionCount: number;
  actionCount: number;
  fallbackReasonCodes: string[];
  consecutiveEmptyDecisionDays: number;
  failureCode: HistoricalDecisionFailureCode | null;
}

export function evaluateHistoricalDecisionHealth(
  state: DailyCycleStateType,
  previousConsecutiveEmptyDays = 0,
): HistoricalDecisionHealth {
  const upstreamTickers = new Set<string>();
  for (const output of Object.values(state.layer2_outputs)) {
    if (!("longs" in output)) continue;
    for (const pick of [...output.longs, ...output.shorts]) upstreamTickers.add(pick.ticker);
  }
  for (const output of Object.values(state.layer3_outputs)) {
    for (const pick of output.picks) upstreamTickers.add(pick.ticker);
  }
  for (const pick of state.layer4_outputs.alpha_discovery?.novel_picks ?? []) {
    upstreamTickers.add(pick.ticker);
  }

  const fallbackReasonCodes = [
    ...new Set(
      (state.layer4_outputs.runtime?.stage_trace ?? [])
        .filter(
          (entry) =>
            ["cio_proposal", "cio_final", "shared_validation"].includes(entry.stage) &&
            entry.status !== "completed",
        )
        .flatMap((entry) =>
          entry.reason_codes?.length ? entry.reason_codes : [`${entry.stage}:${entry.status}`],
        ),
    ),
  ].sort();
  const currentPositionCount = state.current_positions.positions.length;
  const actionCount = state.portfolio_actions.length;
  const audits = state.llm_calls
    .map((call) => call.agent_run_audit)
    .filter((audit) => audit !== undefined);
  const rejectedAudits = audits.filter(
    (audit) => audit.status !== "accepted" && audit.status !== "accepted_empty",
  );
  const allStagesAccepted = audits.length === 26 && rejectedAudits.length === 0;
  const explicitAcceptedAllCash =
    state.layer4_outputs.cio?.decision_disposition === "ALL_CASH" &&
    audits.some(
      (audit) =>
        audit.agent === "cio" &&
        audit.stage === "cio_final" &&
        (audit.status === "accepted" || audit.status === "accepted_empty"),
    );
  const decisionExpected = upstreamTickers.size > 0 || currentPositionCount > 0;
  const emptyDecision = decisionExpected && actionCount === 0 && !explicitAcceptedAllCash;
  const consecutiveEmptyDecisionDays = emptyDecision ? previousConsecutiveEmptyDays + 1 : 0;

  let failureCode: HistoricalDecisionFailureCode | null = null;
  if (!allStagesAccepted) {
    failureCode = "UNACCEPTED_AGENT_STAGE";
  } else if (currentPositionCount > 0 && actionCount === 0 && !explicitAcceptedAllCash) {
    failureCode = "EMPTY_DECISION_WITH_OPEN_POSITIONS";
  } else if (emptyDecision && fallbackReasonCodes.length > 0) {
    failureCode = "L4_FALLBACK_EMPTY_DECISION";
  } else if (emptyDecision) {
    failureCode = "UNCLASSIFIED_EMPTY_DECISION";
  }

  return {
    tradeDate: state.as_of_date,
    upstreamCandidateCount: upstreamTickers.size,
    currentPositionCount,
    actionCount,
    fallbackReasonCodes,
    consecutiveEmptyDecisionDays,
    failureCode,
  };
}

export function assertAcceptedDailyCycle(state: DailyCycleStateType): HistoricalDecisionHealth {
  const health = evaluateHistoricalDecisionHealth(state);
  if (health.failureCode) {
    throw new Error(
      `FAILED_NO_DECISION:${health.failureCode}:date=${health.tradeDate}:` +
        `accepted_stages=${
          state.llm_calls.filter((call) => {
            const status = call.agent_run_audit?.status;
            return status === "accepted" || status === "accepted_empty";
          }).length
        }/26`,
    );
  }
  return health;
}

export function requireDecisionDisposition(
  state: DailyCycleStateType,
): "TARGET_PORTFOLIO" | "HOLD_CURRENT" | "ALL_CASH" {
  const disposition = state.layer4_outputs.cio?.decision_disposition;
  if (!disposition) throw new Error("FAILED_NO_DECISION:CIO_DISPOSITION_MISSING");
  return disposition;
}
