import { canonicalAcceptedOutputHash } from "../accepted_output.js";
import type { CandidateTargetState, CroReviewState } from "../types.js";

const WEIGHT_EPSILON = 1e-9;

export interface FrozenControlledTargetView {
  ts_code: string;
  current_weight: number;
  proposal_target_weight: number;
  controlled_target_weight: number;
  requested_delta_weight: number;
  cro_action_local_id: string | null;
  cro_adjustment: "VETO" | "CAP_WEIGHT" | "REDUCE_WEIGHT" | "REQUIRE_REVIEW" | null;
  order_intent_ref: string | null;
  action: "BUY" | "SELL" | "REDUCE" | null;
}

export interface FrozenOrderIntentView extends FrozenControlledTargetView {
  order_intent_ref: string;
  action: "BUY" | "SELL" | "REDUCE";
}

export interface FrozenOrderIntentPlan {
  candidate_target_hash: string;
  cro_review_hash: string;
  controlled_targets: FrozenControlledTargetView[];
  order_intents: FrozenOrderIntentView[];
  controlled_target_set_id: string;
  controlled_target_set_hash: string;
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

/**
 * The sole runtime-owned derivation of post-CRO targets and executable intents.
 * REQUIRE_REVIEW is intentionally fail-closed at current weight and emits no intent.
 */
export function expectedFrozenOrderIntents(
  candidate: CandidateTargetState,
  croReview: CroReviewState,
): FrozenOrderIntentPlan {
  const adjustmentByTicker = new Map(
    (croReview.output.required_adjustments ?? []).map((adjustment) => [
      adjustment.ticker,
      adjustment,
    ]),
  );
  const controlledTargets = candidate.portfolio_actions
    .map((position): FrozenControlledTargetView => {
      const adjustment = adjustmentByTicker.get(position.ticker);
      const currentWeight = position.current_weight ?? 0;
      const controlledTargetWeight =
        adjustment?.adjustment === "VETO"
          ? 0
          : adjustment?.adjustment === "REQUIRE_REVIEW"
            ? currentWeight
            : adjustment?.adjustment === "CAP_WEIGHT" || adjustment?.adjustment === "REDUCE_WEIGHT"
              ? Math.min(
                  position.target_weight,
                  adjustment.max_target_weight ?? position.target_weight,
                )
              : position.target_weight;
      const requestedDeltaWeight = controlledTargetWeight - currentWeight;
      const action =
        requestedDeltaWeight > WEIGHT_EPSILON
          ? "BUY"
          : requestedDeltaWeight < -WEIGHT_EPSILON
            ? controlledTargetWeight <= WEIGHT_EPSILON
              ? "SELL"
              : "REDUCE"
            : null;
      const orderIntentRef = action
        ? frozenOrderIntentRef({
            candidateTargetHash: candidate.candidate_target_hash,
            croReviewHash: croReview.review_hash,
            tsCode: position.ticker,
            requestedDeltaWeight,
          })
        : null;
      return {
        ts_code: position.ticker,
        current_weight: currentWeight,
        proposal_target_weight: position.target_weight,
        controlled_target_weight: controlledTargetWeight,
        requested_delta_weight: requestedDeltaWeight,
        cro_action_local_id: adjustment?.action_local_id ?? null,
        cro_adjustment: adjustment?.adjustment ?? null,
        order_intent_ref: orderIntentRef,
        action,
      };
    })
    .sort((left, right) => left.ts_code.localeCompare(right.ts_code));
  const controlledTargetSetHash = canonicalAcceptedOutputHash({
    schema_version: "decision.frozen_controlled_target_set.v1",
    candidate_target_hash: candidate.candidate_target_hash,
    cro_review_hash: croReview.review_hash,
    controlled_targets: controlledTargets,
  });
  return {
    candidate_target_hash: candidate.candidate_target_hash,
    cro_review_hash: croReview.review_hash,
    controlled_targets: controlledTargets,
    order_intents: controlledTargets.filter(
      (target): target is FrozenOrderIntentView =>
        target.order_intent_ref !== null && target.action !== null,
    ),
    controlled_target_set_id: `controlled-target-set:${controlledTargetSetHash.slice("sha256:".length)}`,
    controlled_target_set_hash: controlledTargetSetHash,
  };
}

export function assertFrozenOrderIntentPlanIntegrity(plan: FrozenOrderIntentPlan): void {
  for (const target of plan.controlled_targets) {
    const expectedDelta = target.controlled_target_weight - target.current_weight;
    const expectedAction =
      expectedDelta > WEIGHT_EPSILON
        ? "BUY"
        : expectedDelta < -WEIGHT_EPSILON
          ? target.controlled_target_weight <= WEIGHT_EPSILON
            ? "SELL"
            : "REDUCE"
          : null;
    const expectedRef = expectedAction
      ? frozenOrderIntentRef({
          candidateTargetHash: plan.candidate_target_hash,
          croReviewHash: plan.cro_review_hash,
          tsCode: target.ts_code,
          requestedDeltaWeight: expectedDelta,
        })
      : null;
    if (
      Math.abs(target.requested_delta_weight - expectedDelta) > WEIGHT_EPSILON ||
      target.action !== expectedAction ||
      target.order_intent_ref !== expectedRef
    ) {
      throw new Error(`${target.ts_code}: frozen controlled-target semantics mismatch`);
    }
  }
  const expectedHash = canonicalAcceptedOutputHash({
    schema_version: "decision.frozen_controlled_target_set.v1",
    candidate_target_hash: plan.candidate_target_hash,
    cro_review_hash: plan.cro_review_hash,
    controlled_targets: plan.controlled_targets,
  });
  if (
    plan.controlled_target_set_hash !== expectedHash ||
    plan.controlled_target_set_id !==
      `controlled-target-set:${expectedHash.slice("sha256:".length)}`
  ) {
    throw new Error("frozen controlled-target set identity mismatch");
  }
  const actionable = plan.controlled_targets.filter(
    (target): target is FrozenOrderIntentView =>
      target.order_intent_ref !== null && target.action !== null,
  );
  if (
    actionable.length !== plan.order_intents.length ||
    canonicalAcceptedOutputHash(actionable) !== canonicalAcceptedOutputHash(plan.order_intents)
  ) {
    throw new Error("frozen controlled-target set has inconsistent order intents");
  }
}

export function assertMatchesFrozenOrderIntents(
  rows: ReadonlyArray<{
    order_intent_ref?: string | undefined;
    ts_code?: string | undefined;
    ticker?: string | undefined;
    requested_delta_weight?: number | undefined;
  }>,
  expected: ReadonlyArray<FrozenOrderIntentView>,
  label: string,
): void {
  if (rows.length !== expected.length) {
    throw new Error(`${label} must cover the frozen order intent set one-to-one`);
  }
  const expectedByRef = new Map(expected.map((intent) => [intent.order_intent_ref, intent]));
  const matchedRefs = new Set<string>();
  for (const row of rows) {
    const ref = row.order_intent_ref;
    const intent = ref ? expectedByRef.get(ref) : undefined;
    if (
      !ref ||
      !intent ||
      matchedRefs.has(ref) ||
      intent.ts_code !== (row.ts_code ?? row.ticker) ||
      row.requested_delta_weight === undefined ||
      Math.abs(intent.requested_delta_weight - row.requested_delta_weight) > WEIGHT_EPSILON
    ) {
      throw new Error(`${label} does not match a frozen order intent`);
    }
    matchedRefs.add(ref);
  }
}

function persistentRef(namespace: string, value: unknown): string {
  return `${namespace}:${canonicalAcceptedOutputHash(value).slice("sha256:".length)}`;
}
