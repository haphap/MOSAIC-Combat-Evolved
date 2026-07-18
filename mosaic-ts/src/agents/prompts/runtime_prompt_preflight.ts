import {
  checkResearchKnobsPrompts,
  type ResearchKnobsCheckReport,
} from "./research_knobs_checker.js";
import {
  buildRuntimeAgentManifestArtifact,
  validateRuntimeAgentManifestArtifact,
} from "./runtime_agent_spec.js";

export async function assertRuntimePromptPreflight(opts: {
  cohort: string;
  promptsRoot?: string;
  privatePromptsRoot?: string;
}): Promise<ResearchKnobsCheckReport> {
  const manifest = buildRuntimeAgentManifestArtifact();
  const manifestReasons = validateRuntimeAgentManifestArtifact(manifest);
  if (manifestReasons.length > 0) {
    throw new Error(`runtime manifest preflight failed: ${manifestReasons.join(",")}`);
  }
  const report = await checkResearchKnobsPrompts({
    cohort: opts.cohort,
    enabledAgentStages: new Set(["*"]),
    ...(opts.promptsRoot ? { promptsRoot: opts.promptsRoot } : {}),
    ...(opts.privatePromptsRoot ? { privatePromptsRoot: opts.privatePromptsRoot } : {}),
  });
  const failed = report.rows.filter((row) => !row.ready);
  if (
    !report.ready ||
    report.total_runtime_agents !== manifest.runtime_agent_count ||
    report.total_runtime_stages !== manifest.runtime_stage_count
  ) {
    const reasons = failed.flatMap((row) =>
      row.reasons.map((reason) => `${row.agent}:${row.stage}:${reason}`),
    );
    throw new Error(
      `runtime prompt preflight failed: ${reasons.slice(0, 20).join(",") || "coverage_mismatch"}`,
    );
  }
  return report;
}
