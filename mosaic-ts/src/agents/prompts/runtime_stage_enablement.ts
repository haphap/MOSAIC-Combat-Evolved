export type RuntimeResearchKnobsEnablement = "legacy" | "enabled";

export const DEFAULT_RUNTIME_RESEARCH_KNOBS_COHORT = "cohort_default";

export const RUNTIME_RESEARCH_KNOBS_COHORT_STAGE_ENABLEMENT = {
  cohort_default: {
    "china:agent_run": "enabled",
    "us_economy:agent_run": "enabled",
    "eu_economy:agent_run": "enabled",
    "central_bank:agent_run": "enabled",
    "us_financial_conditions:agent_run": "enabled",
    "euro_area_financial_conditions:agent_run": "enabled",
    "commodities:agent_run": "enabled",
    "geopolitical:agent_run": "enabled",
    "market_breadth:agent_run": "enabled",
    "institutional_flow:agent_run": "enabled",
    "semiconductor:agent_run": "enabled",
    "technology:agent_run": "enabled",
    "energy:agent_run": "enabled",
    "biotech:agent_run": "enabled",
    "consumer:agent_run": "enabled",
    "industrials:agent_run": "enabled",
    "real_estate_construction:agent_run": "enabled",
    "financials:agent_run": "enabled",
    "agriculture:agent_run": "enabled",
    "relationship_mapper:agent_run": "enabled",
    "druckenmiller:agent_run": "enabled",
    "munger:agent_run": "enabled",
    "burry:agent_run": "enabled",
    "ackman:agent_run": "enabled",
    "cro:cro_review": "enabled",
    "alpha_discovery:alpha_discovery": "enabled",
    "autonomous_execution:execution_feasibility": "enabled",
    "cio:cio_proposal": "enabled",
    "cio:cio_final": "enabled",
  },
} as const satisfies Readonly<
  Record<string, Readonly<Record<string, RuntimeResearchKnobsEnablement>>>
>;

export function configuredRuntimeResearchKnobsCohorts(): ReadonlyArray<string> {
  return Object.keys(RUNTIME_RESEARCH_KNOBS_COHORT_STAGE_ENABLEMENT).sort();
}

export function configuredRuntimeResearchKnobsStageKeys(
  cohort = DEFAULT_RUNTIME_RESEARCH_KNOBS_COHORT,
): ReadonlySet<string> {
  const stages =
    RUNTIME_RESEARCH_KNOBS_COHORT_STAGE_ENABLEMENT[
      cohort as keyof typeof RUNTIME_RESEARCH_KNOBS_COHORT_STAGE_ENABLEMENT
    ];
  if (!stages) return new Set();
  return new Set(
    Object.entries(stages)
      .filter(([, enablement]) => enablement === "enabled")
      .map(([key]) => key),
  );
}

export function runtimeResearchKnobsStageEnablement(
  cohort: string,
  agent: string,
  stage: string,
): RuntimeResearchKnobsEnablement {
  const key = `${agent}:${stage}`;
  const cohortStages =
    RUNTIME_RESEARCH_KNOBS_COHORT_STAGE_ENABLEMENT[
      cohort as keyof typeof RUNTIME_RESEARCH_KNOBS_COHORT_STAGE_ENABLEMENT
    ];
  if (!cohortStages) return "legacy";
  const enablement = cohortStages[key as keyof typeof cohortStages];
  if (!enablement) throw new Error(`runtime_research_knobs_stage_not_declared:${key}`);
  return enablement;
}
