export type PrivateKnotEnablement = "enabled" | "unavailable";

export const DEFAULT_PRIVATE_KNOT_COHORT = "cohort_default";

export const PRIVATE_KNOT_COHORT_IDS = [
  "cohort_default",
  "cohort_bull_2007",
  "cohort_bull_2016",
  "cohort_crisis_2008",
  "cohort_crisis_covid",
  "cohort_euphoria_2021",
  "cohort_rate_tightening",
  "cohort_recovery_2020",
] as const;

const ENABLED_PRIVATE_KNOT_STAGES = {
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
} as const satisfies Readonly<Record<string, PrivateKnotEnablement>>;

export const PRIVATE_KNOT_COHORT_STAGE_ENABLEMENT: Readonly<
  Record<string, Readonly<Record<string, PrivateKnotEnablement>>>
> = Object.fromEntries(
  PRIVATE_KNOT_COHORT_IDS.map((cohort) => [cohort, ENABLED_PRIVATE_KNOT_STAGES]),
);

export function configuredPrivateKnotCohorts(): ReadonlyArray<string> {
  return Object.keys(PRIVATE_KNOT_COHORT_STAGE_ENABLEMENT).sort();
}

export function configuredPrivateKnotStageKeys(
  cohort = DEFAULT_PRIVATE_KNOT_COHORT,
): ReadonlySet<string> {
  const stages = PRIVATE_KNOT_COHORT_STAGE_ENABLEMENT[cohort];
  if (!stages) return new Set();
  return new Set(
    Object.entries(stages)
      .filter(([, enablement]) => enablement === "enabled")
      .map(([key]) => key),
  );
}

export function privateKnotStageEnablement(
  cohort: string,
  agent: string,
  stage: string,
): PrivateKnotEnablement {
  const key = `${agent}:${stage}`;
  const cohortStages = PRIVATE_KNOT_COHORT_STAGE_ENABLEMENT[cohort];
  if (!cohortStages) return "unavailable";
  const enablement = cohortStages[key];
  if (!enablement) throw new Error(`private_knot_stage_not_declared:${key}`);
  return enablement;
}
