import type { PromptReleaseLoadContext } from "./release_prompt_loader.js";
import {
  buildRuntimeAgentManifestArtifact,
  validateRuntimeAgentManifestArtifact,
} from "./runtime_agent_spec.js";
import { checkRuntimePrompts, type RuntimePromptCheckReport } from "./runtime_prompt_checker.js";

export async function assertRuntimePromptPreflight(opts: {
  cohort: string;
  promptsRoot?: string;
  privatePromptsRoot?: string;
  releaseContext?: PromptReleaseLoadContext | null;
}): Promise<RuntimePromptCheckReport> {
  const manifest = buildRuntimeAgentManifestArtifact();
  const manifestReasons = validateRuntimeAgentManifestArtifact(manifest);
  if (manifestReasons.length > 0) {
    throw new Error(`runtime manifest preflight failed: ${manifestReasons.join(",")}`);
  }
  const report = await checkRuntimePrompts({
    cohort: opts.cohort,
    ...(opts.promptsRoot ? { promptsRoot: opts.promptsRoot } : {}),
    ...(opts.privatePromptsRoot ? { privatePromptsRoot: opts.privatePromptsRoot } : {}),
    ...(opts.releaseContext !== undefined ? { releaseContext: opts.releaseContext } : {}),
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
