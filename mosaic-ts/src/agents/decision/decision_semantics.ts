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
