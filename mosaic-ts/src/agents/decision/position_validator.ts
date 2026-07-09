import { buildPositionAuditToolStatusSummary } from "../helpers/position_audit.js";
import type { ResearchKnobsSnapshot } from "../helpers/research_knobs.js";
import type {
  CioOutput,
  CurrentPositionsSnapshot,
  PortfolioAction,
  PositionAudit,
  PositionReview,
} from "../types.js";

export interface PositionValidationResult {
  output: CioOutput;
  position_reviews: PositionReview[];
  position_audit: PositionAudit;
}

export class PositionActionValidationError extends Error {
  override readonly name = "PositionActionValidationError";
}

export function validateCioPositionActions(opts: {
  output: CioOutput;
  currentPositions: CurrentPositionsSnapshot;
  knobSnapshot?: ResearchKnobsSnapshot | null;
  sharedPolicyValues?: Readonly<Record<string, unknown>>;
}): PositionValidationResult {
  const { output, currentPositions, knobSnapshot, sharedPolicyValues } = opts;
  if (currentPositions.snapshot_status === "missing" && output.portfolio_actions.length > 0) {
    throw new PositionActionValidationError(
      "current_positions snapshot is missing; CIO cannot emit portfolio_actions",
    );
  }
  if (isMirofishOnlyAction(output) && output.portfolio_actions.length > 0) {
    throw new PositionActionValidationError(
      "MiroFish-only influence cannot emit portfolio_actions without current data support",
    );
  }
  if (isPriorOrSimulationOnlyAction(output) && output.portfolio_actions.length > 0) {
    throw new PositionActionValidationError(
      "RKE/MiroFish prior-only influence cannot emit portfolio_actions without current data support",
    );
  }
  const stopLossPct = thresholdNumber(knobSnapshot, sharedPolicyValues, "stop_loss_pct", -0.08);
  const maxSingleNameWeight = thresholdNumber(
    knobSnapshot,
    sharedPolicyValues,
    "max_single_name_weight",
    1,
  );
  const maxSectorWeight = thresholdNumber(knobSnapshot, sharedPolicyValues, "max_sector_weight", 1);
  const staleThesisDays = thresholdNumber(
    knobSnapshot,
    sharedPolicyValues,
    "stale_thesis_days",
    20,
  );
  const actions = output.portfolio_actions.map((action) =>
    normalizeAction(action, currentPositions, staleThesisDays, stopLossPct),
  );
  assertMirofishInfluencedPositionChangesHaveDissent(output, actions, currentPositions);
  const reviews = positionReviewsFromActions(actions, currentPositions, output.confidence);
  if (currentPositions.snapshot_status === "loaded") {
    assertEveryCurrentPositionReviewed(currentPositions, actions, reviews);
  }
  assertPositionDecisionSemantics(actions, currentPositions);
  for (const action of actions) {
    if (action.target_weight <= maxSingleNameWeight) continue;
    if (!nonEmptyText(action.override_reason)) {
      throw new PositionActionValidationError(
        `${action.ticker}: target_weight exceeds max_single_name_weight without override_reason`,
      );
    }
    if (!hasCroRiskOverride(action)) {
      throw new PositionActionValidationError(
        `${action.ticker}: target_weight exceeds max_single_name_weight without CRO risk override`,
      );
    }
  }
  assertSectorConcentration(actions, maxSectorWeight);
  for (const position of currentPositions.positions) {
    const action = actions.find((item) => item.ticker === position.ticker);
    const rawAction = output.portfolio_actions.find((item) => item.ticker === position.ticker);
    if (
      position.unrealized_pnl_pct <= stopLossPct &&
      action &&
      action.action === "HOLD" &&
      !nonEmptyText(action.override_reason)
    ) {
      throw new PositionActionValidationError(
        `${position.ticker}: stop_loss breached but HOLD lacks override_reason`,
      );
    }
    if (
      position.unrealized_pnl_pct <= stopLossPct &&
      action &&
      action.action === "HOLD" &&
      !hasCroRiskOverride(action)
    ) {
      throw new PositionActionValidationError(
        `${position.ticker}: stop_loss breached but HOLD lacks CRO risk override`,
      );
    }
    if (
      position.unrealized_pnl_pct <= stopLossPct &&
      action &&
      action.action === "HOLD" &&
      !hasStopLossCounterevidence(rawAction)
    ) {
      throw new PositionActionValidationError(
        `${position.ticker}: stop_loss breached but HOLD lacks counterevidence`,
      );
    }
  }
  const totalWeight = actions.reduce((sum, action) => sum + action.target_weight, 0);
  if (totalWeight > 1.05) {
    throw new PositionActionValidationError(
      `portfolio_actions target_weight sum ${totalWeight.toFixed(3)} exceeds 1.05`,
    );
  }
  return {
    output: { ...output, portfolio_actions: actions },
    position_reviews: reviews,
    position_audit: buildPositionAudit({
      currentPositions,
      reviews,
      actions,
      stopLossPct,
      staleThesisDays,
    }),
  };
}

function isMirofishOnlyAction(output: CioOutput): boolean {
  const declared = output.declared_knob_influence_ids ?? [];
  return declared.length > 0 && declared.every((id) => id.startsWith("mirofish_"));
}

function isPriorOrSimulationOnlyAction(output: CioOutput): boolean {
  const declared = output.declared_knob_influence_ids ?? [];
  return declared.length > 0 && declared.every(isPriorOrSimulationInfluenceId);
}

function isPriorOrSimulationInfluenceId(id: string): boolean {
  const normalized = id.toLowerCase();
  return (
    normalized.startsWith("mirofish_") ||
    normalized === "rke_prior" ||
    normalized === "research_prior" ||
    normalized === "get_rke_research_context" ||
    normalized.startsWith("rke_prior_") ||
    normalized.startsWith("research_prior_")
  );
}

function hasMirofishInfluence(output: CioOutput): boolean {
  return (output.declared_knob_influence_ids ?? []).some((id) => id.startsWith("mirofish_"));
}

function hasCroRiskOverride(action: PortfolioAction): boolean {
  return (action.risk_flags ?? []).includes("cro_risk_override");
}

function hasStopLossCounterevidence(action: PortfolioAction | undefined): boolean {
  return Boolean(
    nonEmptyText(action?.position_decision_reason) ?? nonEmptyText(action?.dissent_notes),
  );
}

function assertMirofishInfluencedPositionChangesHaveDissent(
  output: CioOutput,
  actions: ReadonlyArray<PortfolioAction>,
  currentPositions: CurrentPositionsSnapshot,
): void {
  if (!hasMirofishInfluence(output)) return;
  const currentTickers = new Set(currentPositions.positions.map((position) => position.ticker));
  for (const action of actions) {
    if (!currentTickers.has(action.ticker)) continue;
    const decision = action.position_decision;
    if (
      (decision === "ADD" || decision === "REDUCE" || decision === "EXIT") &&
      !nonEmptyText(action.dissent_notes)
    ) {
      throw new PositionActionValidationError(
        `${action.ticker}: MiroFish-influenced position change requires dissent_notes`,
      );
    }
  }
}

function normalizeAction(
  action: PortfolioAction,
  currentPositions: CurrentPositionsSnapshot,
  staleThesisDays: number,
  stopLossPct: number,
): PortfolioAction {
  const position = currentPositions.positions.find((item) => item.ticker === action.ticker);
  const sector = nonEmptyText(action.sector) ?? nonEmptyText(position?.sector);
  const currentWeight = action.current_weight ?? position?.current_weight;
  const deltaWeight =
    action.delta_weight ??
    (currentWeight === undefined ? undefined : action.target_weight - currentWeight);
  const positionDecision = action.position_decision ?? inferPositionDecision(action, currentWeight);
  const staleThesis = position ? position.holding_days > staleThesisDays : false;
  const stopLossBreached = position
    ? position.unrealized_pnl_pct <= stopLossPct && action.action === "HOLD"
    : false;
  const riskFlags = [
    ...new Set([
      ...(action.risk_flags ?? []),
      ...(stopLossBreached ? ["stop_loss_breached"] : []),
      ...(staleThesis ? ["stale_thesis"] : []),
    ]),
  ];
  const positionDecisionReason =
    nonEmptyText(action.position_decision_reason) ??
    nonEmptyText(action.dissent_notes) ??
    (staleThesis ? "stale thesis review required" : undefined) ??
    `${action.action} target weight`;
  return {
    ...action,
    ...(sector ? { sector } : {}),
    ...(positionDecision ? { position_decision: positionDecision } : {}),
    ...(currentWeight !== undefined ? { current_weight: currentWeight } : {}),
    ...(deltaWeight !== undefined ? { delta_weight: deltaWeight } : {}),
    thesis_status: action.thesis_status ?? "intact",
    risk_flags: riskFlags,
    position_decision_reason: positionDecisionReason,
  };
}

function assertSectorConcentration(
  actions: ReadonlyArray<PortfolioAction>,
  maxSectorWeight: number,
): void {
  if (maxSectorWeight >= 1) return;
  const totals = new Map<string, number>();
  for (const action of actions) {
    if (action.target_weight <= 0) continue;
    const sector = nonEmptyText(action.sector);
    if (!sector) {
      throw new PositionActionValidationError(
        `${action.ticker}: max_sector_weight active but sector is missing`,
      );
    }
    totals.set(sector, (totals.get(sector) ?? 0) + action.target_weight);
  }
  for (const [sector, total] of totals.entries()) {
    if (total > maxSectorWeight + 1e-9) {
      throw new PositionActionValidationError(
        `${sector}: target_weight ${total.toFixed(3)} exceeds max_sector_weight ${maxSectorWeight}`,
      );
    }
  }
}

function assertPositionDecisionSemantics(
  actions: ReadonlyArray<PortfolioAction>,
  currentPositions: CurrentPositionsSnapshot,
): void {
  const currentByTicker = new Map(
    currentPositions.positions.map((position) => [position.ticker, position.current_weight]),
  );
  for (const action of actions) {
    const currentWeight = action.current_weight ?? currentByTicker.get(action.ticker);
    const deltaWeight =
      action.delta_weight ??
      (currentWeight === undefined ? undefined : action.target_weight - currentWeight);
    const decision = action.position_decision ?? inferPositionDecision(action, currentWeight);
    switch (decision) {
      case "ADD":
        if (action.action !== "BUY") {
          throw new PositionActionValidationError(
            `${action.ticker}: ADD position_decision must map to BUY action`,
          );
        }
        if (action.target_weight <= 0) {
          throw new PositionActionValidationError(
            `${action.ticker}: ADD position_decision requires positive target_weight`,
          );
        }
        if (currentWeight !== undefined && action.target_weight <= currentWeight) {
          throw new PositionActionValidationError(
            `${action.ticker}: ADD position_decision requires target_weight above current_weight`,
          );
        }
        if (deltaWeight !== undefined && deltaWeight <= 0) {
          throw new PositionActionValidationError(
            `${action.ticker}: ADD position_decision requires positive delta_weight`,
          );
        }
        break;
      case "REDUCE":
        if (action.action !== "REDUCE") {
          throw new PositionActionValidationError(
            `${action.ticker}: REDUCE position_decision must map to REDUCE action`,
          );
        }
        if (currentWeight === undefined) {
          throw new PositionActionValidationError(
            `${action.ticker}: REDUCE position_decision requires current_weight`,
          );
        }
        if (action.target_weight <= 0 || action.target_weight >= currentWeight) {
          throw new PositionActionValidationError(
            `${action.ticker}: REDUCE position_decision requires 0 < target_weight < current_weight`,
          );
        }
        if (deltaWeight === undefined || deltaWeight >= 0) {
          throw new PositionActionValidationError(
            `${action.ticker}: REDUCE position_decision requires negative delta_weight`,
          );
        }
        break;
      case "EXIT":
        if (action.action !== "SELL") {
          throw new PositionActionValidationError(
            `${action.ticker}: EXIT position_decision must map to SELL action`,
          );
        }
        if (currentWeight === undefined) {
          throw new PositionActionValidationError(
            `${action.ticker}: EXIT position_decision requires current_weight`,
          );
        }
        if (action.target_weight !== 0) {
          throw new PositionActionValidationError(
            `${action.ticker}: EXIT position_decision requires target_weight = 0`,
          );
        }
        if (deltaWeight !== undefined && deltaWeight > 0) {
          throw new PositionActionValidationError(
            `${action.ticker}: EXIT position_decision cannot have positive delta_weight`,
          );
        }
        break;
      case "HOLD":
        if (action.action !== "HOLD") {
          throw new PositionActionValidationError(
            `${action.ticker}: HOLD position_decision must map to HOLD action`,
          );
        }
        if (currentWeight === undefined) {
          throw new PositionActionValidationError(
            `${action.ticker}: HOLD position_decision requires current_weight`,
          );
        }
        if (action.target_weight <= 0) {
          throw new PositionActionValidationError(
            `${action.ticker}: HOLD position_decision requires positive target_weight`,
          );
        }
        break;
    }
  }
}

function inferPositionDecision(
  action: PortfolioAction,
  currentWeight: number | undefined,
): PortfolioAction["position_decision"] {
  if (action.action === "SELL" || action.target_weight === 0) return "EXIT";
  if (action.action === "REDUCE") return "REDUCE";
  if (
    action.action === "BUY" &&
    currentWeight !== undefined &&
    action.target_weight > currentWeight
  ) {
    return "ADD";
  }
  if (action.action === "BUY") return "ADD";
  return "HOLD";
}

function positionReviewsFromActions(
  actions: ReadonlyArray<PortfolioAction>,
  currentPositions: CurrentPositionsSnapshot,
  confidence: number,
): PositionReview[] {
  const currentTickers = new Set(currentPositions.positions.map((position) => position.ticker));
  return actions
    .filter((action) => currentTickers.has(action.ticker))
    .map((action) => ({
      ticker: action.ticker,
      decision: action.position_decision ?? "HOLD",
      target_weight: action.target_weight,
      reason:
        nonEmptyText(action.position_decision_reason) ??
        nonEmptyText(action.dissent_notes) ??
        "position reviewed",
      thesis_status: action.thesis_status ?? "intact",
      risk_flags: action.risk_flags ?? [],
      confidence,
    }));
}

function nonEmptyText(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed ? trimmed : undefined;
}

function assertEveryCurrentPositionReviewed(
  currentPositions: CurrentPositionsSnapshot,
  actions: ReadonlyArray<PortfolioAction>,
  reviews: ReadonlyArray<PositionReview>,
): void {
  const covered = new Set([
    ...actions.map((action) => action.ticker),
    ...reviews.map((review) => review.ticker),
  ]);
  const missing = currentPositions.positions
    .map((position) => position.ticker)
    .filter((ticker) => !covered.has(ticker));
  if (missing.length > 0) {
    throw new PositionActionValidationError(
      `current_positions missing from portfolio_actions/position_reviews: ${missing.join(",")}`,
    );
  }
}

function thresholdNumber(
  snapshot: ResearchKnobsSnapshot | null | undefined,
  sharedPolicyValues: Readonly<Record<string, unknown>> | undefined,
  key: string,
  fallback: number,
): number {
  const value =
    snapshot?.knobs.thresholds[key] ?? snapshot?.knobs.lookbacks[key] ?? sharedPolicyValues?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function buildPositionAudit(opts: {
  currentPositions: CurrentPositionsSnapshot;
  reviews: ReadonlyArray<PositionReview>;
  actions: ReadonlyArray<PortfolioAction>;
  stopLossPct: number;
  staleThesisDays: number;
}): PositionAudit {
  const reviewed = new Set(opts.reviews.map((review) => review.ticker));
  const stopLossOverrideCount = opts.currentPositions.positions.filter((position) => {
    const action = opts.actions.find((item) => item.ticker === position.ticker);
    return (
      position.unrealized_pnl_pct <= opts.stopLossPct &&
      action?.action === "HOLD" &&
      Boolean(action.override_reason)
    );
  }).length;
  return {
    position_snapshot_hash: opts.currentPositions.position_snapshot_hash ?? null,
    snapshot_status: opts.currentPositions.snapshot_status,
    position_source: opts.currentPositions.position_source,
    source_error_code: opts.currentPositions.source_error_code,
    tool_status_summary: buildPositionAuditToolStatusSummary(opts.currentPositions),
    positions_loaded: opts.currentPositions.positions.length,
    positions_reviewed: reviewed.size,
    positions_unreviewed: opts.currentPositions.positions.filter(
      (position) => !reviewed.has(position.ticker),
    ).length,
    hold_count: opts.reviews.filter((review) => review.decision === "HOLD").length,
    add_count: opts.reviews.filter((review) => review.decision === "ADD").length,
    reduce_count: opts.reviews.filter((review) => review.decision === "REDUCE").length,
    exit_count: opts.reviews.filter((review) => review.decision === "EXIT").length,
    stale_thesis_count: opts.currentPositions.positions.filter(
      (position) => position.holding_days > opts.staleThesisDays,
    ).length,
    stop_loss_override_count: stopLossOverrideCount,
    target_current_drift_count: opts.actions.filter(
      (action) => Math.abs(action.delta_weight ?? 0) > 0.01,
    ).length,
  };
}
