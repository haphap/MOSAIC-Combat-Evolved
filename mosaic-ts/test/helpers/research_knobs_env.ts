import { afterEach, beforeEach } from "vitest";

export function disableManifestResearchKnobsForLegacyFixtures(): void {
  let previousAgents: string | undefined;
  let previousStages: string | undefined;
  beforeEach(() => {
    previousAgents = process.env.MOSAIC_RESEARCH_KNOBS_ENABLED_AGENTS;
    previousStages = process.env.MOSAIC_RESEARCH_KNOBS_ENABLED_AGENT_STAGES;
    process.env.MOSAIC_RESEARCH_KNOBS_ENABLED_AGENTS = "__none__";
    process.env.MOSAIC_RESEARCH_KNOBS_ENABLED_AGENT_STAGES = "__none__";
  });
  afterEach(() => {
    if (previousAgents === undefined) delete process.env.MOSAIC_RESEARCH_KNOBS_ENABLED_AGENTS;
    else process.env.MOSAIC_RESEARCH_KNOBS_ENABLED_AGENTS = previousAgents;
    if (previousStages === undefined) {
      delete process.env.MOSAIC_RESEARCH_KNOBS_ENABLED_AGENT_STAGES;
    } else {
      process.env.MOSAIC_RESEARCH_KNOBS_ENABLED_AGENT_STAGES = previousStages;
    }
  });
}
