export type RuntimeResearchKnobsEnablement = "legacy" | "enabled";

export const RUNTIME_RESEARCH_KNOBS_STAGE_ENABLEMENT = {
  "central_bank:agent_run": "enabled",
  "geopolitical:agent_run": "enabled",
  "china:agent_run": "enabled",
  "dollar:agent_run": "enabled",
  "yield_curve:agent_run": "enabled",
  "commodities:agent_run": "enabled",
  "volatility:agent_run": "enabled",
  "emerging_markets:agent_run": "enabled",
  "news_sentiment:agent_run": "enabled",
  "institutional_flow:agent_run": "enabled",
  "semiconductor:agent_run": "enabled",
  "energy:agent_run": "enabled",
  "biotech:agent_run": "enabled",
  "consumer:agent_run": "enabled",
  "industrials:agent_run": "enabled",
  "financials:agent_run": "enabled",
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
} as const satisfies Readonly<Record<string, RuntimeResearchKnobsEnablement>>;

export function configuredRuntimeResearchKnobsStageKeys(): ReadonlySet<string> {
  return new Set(
    Object.entries(RUNTIME_RESEARCH_KNOBS_STAGE_ENABLEMENT)
      .filter(([, enablement]) => enablement === "enabled")
      .map(([key]) => key),
  );
}

export function runtimeResearchKnobsStageEnablement(
  agent: string,
  stage: string,
): RuntimeResearchKnobsEnablement {
  const key = `${agent}:${stage}`;
  const enablement =
    RUNTIME_RESEARCH_KNOBS_STAGE_ENABLEMENT[
      key as keyof typeof RUNTIME_RESEARCH_KNOBS_STAGE_ENABLEMENT
    ];
  if (!enablement) throw new Error(`runtime_research_knobs_stage_not_declared:${key}`);
  return enablement;
}
