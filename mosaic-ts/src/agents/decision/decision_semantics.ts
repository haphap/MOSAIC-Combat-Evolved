export interface CioHoldCurrentTarget {
  ticker: string;
  target_weight: number;
  position_decision?: "HOLD" | "ADD" | "REDUCE" | "EXIT" | undefined;
}

export interface CioCurrentTarget {
  ticker: string;
  current_weight: number;
}

export function assertCioHoldCurrentTargetSet(input: {
  decisionDisposition: string | undefined;
  targets: ReadonlyArray<CioHoldCurrentTarget>;
  currentSnapshotStatus: "loaded" | "empty_confirmed" | "missing";
  currentPositions: ReadonlyArray<CioCurrentTarget>;
  context: string;
}): void {
  if (input.decisionDisposition !== "HOLD_CURRENT") return;
  assertCioHoldCurrentPositions({
    decisionDisposition: input.decisionDisposition,
    targets: input.targets,
    context: input.context,
  });
  if (input.currentSnapshotStatus !== "loaded" || input.currentPositions.length === 0) {
    throw new Error(
      `${input.context}: HOLD_CURRENT requires a loaded, non-empty position snapshot`,
    );
  }

  const currentByTicker = uniqueByTicker(
    input.currentPositions,
    `${input.context} current position`,
  );
  const targetByTicker = uniqueByTicker(input.targets, `${input.context} target`);
  if (targetByTicker.size !== currentByTicker.size) {
    throw new Error(
      `${input.context}: HOLD_CURRENT target ticker set must equal current positions`,
    );
  }
  for (const [ticker, current] of currentByTicker) {
    const target = targetByTicker.get(ticker);
    if (!target) {
      throw new Error(`${input.context}: HOLD_CURRENT omits current position ${ticker}`);
    }
    if (Math.abs(target.target_weight - current.current_weight) > 1e-9) {
      throw new Error(`${input.context}: HOLD_CURRENT changes target weight for ${ticker}`);
    }
  }
}

export function assertCioHoldCurrentPositions(input: {
  decisionDisposition: string | undefined;
  targets: ReadonlyArray<CioHoldCurrentTarget>;
  context: string;
}): void {
  if (input.decisionDisposition !== "HOLD_CURRENT") return;
  for (const target of input.targets) {
    if (target.position_decision !== "HOLD") {
      throw new Error(`${input.context}: HOLD_CURRENT requires HOLD for ${target.ticker}`);
    }
  }
}

export function assertExactExecutionResolutionSet(input: {
  resolutions: ReadonlyArray<{ execution_assessment_local_ref: string }>;
  assessments: ReadonlyArray<{ assessment_local_id?: string | undefined }>;
  context: string;
}): void {
  const assessmentIds = new Set<string>();
  for (const assessment of input.assessments) {
    const id = assessment.assessment_local_id;
    if (!id || assessmentIds.has(id)) {
      throw new Error(`${input.context}: execution assessments lack unique local ids`);
    }
    assessmentIds.add(id);
  }

  const resolutionIds = new Set<string>();
  for (const resolution of input.resolutions) {
    const id = resolution.execution_assessment_local_ref;
    if (!id || resolutionIds.has(id)) {
      throw new Error(`${input.context}: execution resolutions lack unique local refs`);
    }
    resolutionIds.add(id);
  }

  if (
    resolutionIds.size !== assessmentIds.size ||
    [...resolutionIds].some((id) => !assessmentIds.has(id))
  ) {
    throw new Error(
      `${input.context}: execution_control_resolutions must exactly match accepted execution assessments`,
    );
  }
}

export type CioFinalCroAction =
  | "VETO"
  | "CAP_WEIGHT"
  | "REDUCE_WEIGHT"
  | "REQUIRE_REVIEW"
  | "NO_OBJECTION";
export type CioFinalExecutionStatus = "FEASIBLE" | "PARTIAL" | "BLOCKED" | "NO_DELTA";
export type CioFinalComplianceMode = "INTERSECTION" | "STAGED_EXECUTION";
export type CioFinalCroResolution = "COMPLIED" | "MORE_CONSERVATIVE" | "STAGED";
export type CioFinalExecutionResolution = "COMPLIED" | "MORE_CONSERVATIVE";

export interface CioFinalComplianceInput {
  currentWeight: number;
  requestedDeltaWeight: number;
  executionStatus: CioFinalExecutionStatus;
  maxExecutableDeltaWeight: number;
  croAction: CioFinalCroAction;
  croMaxTargetWeight: number | null;
}

export interface CioFinalComplianceBounds {
  direction: "INCREASE" | "DECREASE" | "HOLD";
  croTargetWeightMin: number;
  croTargetWeightMax: number;
  executionTargetWeightMin: number;
  executionTargetWeightMax: number;
  targetWeightMin: number;
  targetWeightMax: number;
  complianceMode: CioFinalComplianceMode;
  stagedTargetWeight: number | null;
}

export interface CioFinalComplianceResult {
  bounds: CioFinalComplianceBounds;
  croResolution: CioFinalCroResolution | null;
  executionResolution: CioFinalExecutionResolution;
}

const CIO_FINAL_COMPLIANCE_EPSILON = 1e-9;

export function deriveCioFinalComplianceBounds(
  input: CioFinalComplianceInput,
): CioFinalComplianceBounds {
  const epsilon = CIO_FINAL_COMPLIANCE_EPSILON;
  if (
    !Number.isFinite(input.currentWeight) ||
    input.currentWeight < -epsilon ||
    input.currentWeight > 1 + epsilon ||
    !Number.isFinite(input.requestedDeltaWeight) ||
    !Number.isFinite(input.maxExecutableDeltaWeight) ||
    input.maxExecutableDeltaWeight < -epsilon
  ) {
    throw new Error("invalid CIO final compliance weights");
  }
  const currentWeight = clampWeight(input.currentWeight);
  const requestedMagnitude = Math.abs(input.requestedDeltaWeight);
  const direction =
    input.requestedDeltaWeight > epsilon
      ? "INCREASE"
      : input.requestedDeltaWeight < -epsilon
        ? "DECREASE"
        : "HOLD";
  const executableCap = input.maxExecutableDeltaWeight;
  if (
    (input.executionStatus === "FEASIBLE" &&
      Math.abs(executableCap - requestedMagnitude) > epsilon) ||
    (input.executionStatus === "PARTIAL" &&
      (requestedMagnitude <= epsilon ||
        executableCap <= epsilon ||
        executableCap >= requestedMagnitude - epsilon)) ||
    (input.executionStatus === "BLOCKED" && executableCap > epsilon) ||
    (input.executionStatus === "NO_DELTA" &&
      (requestedMagnitude > epsilon || executableCap > epsilon))
  ) {
    throw new Error(`invalid ${input.executionStatus} CIO final execution cap`);
  }

  if (input.croAction === "VETO") {
    if (input.croMaxTargetWeight !== 0) {
      throw new Error("CIO final VETO requires max_target_weight 0");
    }
  } else if (input.croAction === "CAP_WEIGHT" || input.croAction === "REDUCE_WEIGHT") {
    if (
      input.croMaxTargetWeight === null ||
      !Number.isFinite(input.croMaxTargetWeight) ||
      input.croMaxTargetWeight < -epsilon ||
      input.croMaxTargetWeight > 1 + epsilon
    ) {
      throw new Error(`CIO final ${input.croAction} requires a valid max_target_weight`);
    }
  } else if (input.croMaxTargetWeight !== null) {
    throw new Error(`CIO final ${input.croAction} requires null max_target_weight`);
  }

  const croTargetWeightMin = input.croAction === "REQUIRE_REVIEW" ? currentWeight : 0;
  const croTargetWeightMax =
    input.croAction === "VETO"
      ? 0
      : input.croAction === "REQUIRE_REVIEW"
        ? currentWeight
        : input.croAction === "CAP_WEIGHT" || input.croAction === "REDUCE_WEIGHT"
          ? clampWeight(input.croMaxTargetWeight as number)
          : 1;
  const executionTargetWeightMin = roundCioFinalWeight(
    direction === "DECREASE" ? currentWeight - executableCap : currentWeight,
  );
  const executionTargetWeightMax = roundCioFinalWeight(
    direction === "INCREASE" ? currentWeight + executableCap : currentWeight,
  );
  const intersectionMin = Math.max(croTargetWeightMin, executionTargetWeightMin);
  const intersectionMax = Math.min(croTargetWeightMax, executionTargetWeightMax);
  if (intersectionMin <= intersectionMax + epsilon) {
    return {
      direction,
      croTargetWeightMin,
      croTargetWeightMax,
      executionTargetWeightMin,
      executionTargetWeightMax,
      targetWeightMin: roundCioFinalWeight(intersectionMin),
      targetWeightMax: roundCioFinalWeight(intersectionMax),
      complianceMode: "INTERSECTION",
      stagedTargetWeight: null,
    };
  }

  const stagedTargetWeight =
    direction === "DECREASE" && croTargetWeightMax < executionTargetWeightMin - epsilon
      ? executionTargetWeightMin
      : direction === "INCREASE" && croTargetWeightMin > executionTargetWeightMax + epsilon
        ? executionTargetWeightMax
        : null;
  if (
    stagedTargetWeight === null ||
    (direction === "DECREASE" && stagedTargetWeight >= currentWeight - epsilon) ||
    (direction === "INCREASE" && stagedTargetWeight <= currentWeight + epsilon)
  ) {
    throw new Error("CIO final CRO and execution bounds have no valid staged boundary");
  }
  return {
    direction,
    croTargetWeightMin,
    croTargetWeightMax,
    executionTargetWeightMin,
    executionTargetWeightMax,
    targetWeightMin: roundCioFinalWeight(stagedTargetWeight),
    targetWeightMax: roundCioFinalWeight(stagedTargetWeight),
    complianceMode: "STAGED_EXECUTION",
    stagedTargetWeight: roundCioFinalWeight(stagedTargetWeight),
  };
}

export function assertCioFinalTargetCompliance(
  input: CioFinalComplianceInput & { finalWeight: number; context?: string },
): CioFinalComplianceResult {
  const bounds = deriveCioFinalComplianceBounds(input);
  const epsilon = CIO_FINAL_COMPLIANCE_EPSILON;
  const context = input.context ?? "CIO final";
  const finalWeight = input.finalWeight;
  if (!Number.isFinite(finalWeight) || finalWeight < -epsilon || finalWeight > 1 + epsilon) {
    throw new Error(`${context}: final target weight is invalid`);
  }
  if (
    input.croAction === "REQUIRE_REVIEW" &&
    Math.abs(finalWeight - input.currentWeight) > epsilon
  ) {
    throw new Error(`${context}: REQUIRE_REVIEW final target must remain at current weight`);
  }
  if (
    finalWeight < bounds.executionTargetWeightMin - epsilon ||
    finalWeight > bounds.executionTargetWeightMax + epsilon
  ) {
    throw new Error(
      `${context}: final delta exceeds frozen ${input.executionStatus.toLowerCase()} execution cap; ` +
        `final target exceeds the accepted ${input.executionStatus} execution cap`,
    );
  }
  if (
    bounds.complianceMode === "STAGED_EXECUTION" &&
    Math.abs(finalWeight - (bounds.stagedTargetWeight as number)) > epsilon
  ) {
    throw new Error(`${context}: final target must equal the staged execution boundary`);
  }
  if (
    finalWeight < bounds.croTargetWeightMin - epsilon ||
    finalWeight > bounds.croTargetWeightMax + epsilon
  ) {
    if (bounds.complianceMode !== "STAGED_EXECUTION" && input.croAction === "REQUIRE_REVIEW") {
      throw new Error(`${context}: REQUIRE_REVIEW final target must remain at current weight`);
    }
    if (bounds.complianceMode !== "STAGED_EXECUTION") {
      throw new Error(`${context}: final target exceeds accepted CRO ${input.croAction} cap`);
    }
  }
  const finalDelta = finalWeight - input.currentWeight;
  const executionResolution: CioFinalExecutionResolution =
    Math.abs(Math.abs(finalDelta) - input.maxExecutableDeltaWeight) <= epsilon
      ? "COMPLIED"
      : "MORE_CONSERVATIVE";
  let croResolution: CioFinalCroResolution | null = null;
  if (input.croAction !== "NO_OBJECTION") {
    croResolution =
      bounds.complianceMode === "STAGED_EXECUTION"
        ? "STAGED"
        : input.croAction === "VETO" || input.croAction === "REQUIRE_REVIEW"
          ? "COMPLIED"
          : Math.abs(finalWeight - bounds.croTargetWeightMax) <= epsilon
            ? "COMPLIED"
            : "MORE_CONSERVATIVE";
  }
  return { bounds, croResolution, executionResolution };
}

function clampWeight(value: number): number {
  return Math.max(0, Math.min(1, value));
}

function roundCioFinalWeight(value: number): number {
  return Math.round(clampWeight(value) * 1e12) / 1e12;
}

function uniqueByTicker<T extends { ticker: string }>(
  values: ReadonlyArray<T>,
  label: string,
): Map<string, T> {
  const byTicker = new Map<string, T>();
  for (const value of values) {
    if (byTicker.has(value.ticker)) throw new Error(`duplicate ${label} ticker: ${value.ticker}`);
    byTicker.set(value.ticker, value);
  }
  return byTicker;
}
