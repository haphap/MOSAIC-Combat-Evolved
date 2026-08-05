import { LAYER_BY_AGENT, type Layer } from "./cohorts.js";
import { loadPrompt } from "./loader.js";
import { containsPrivateKnotPromptContent } from "./private_knot_prompt_markers.js";
import type { PromptReleaseLoadContext } from "./release_prompt_loader.js";
import { RUNTIME_AGENT_SPECS, type RuntimeAgentStageId } from "./runtime_agent_spec.js";

export interface RuntimePromptCheckRow {
  agent: string;
  layer: Layer;
  stage: RuntimeAgentStageId;
  ready: boolean;
  reasons: string[];
}

export interface RuntimePromptCheckReport {
  schema_version: "runtime_prompt_check_v1";
  cohort: string;
  total_runtime_agents: number;
  total_runtime_stages: number;
  ready: boolean;
  rows: RuntimePromptCheckRow[];
}

export async function checkRuntimePrompts(opts: {
  cohort: string;
  promptsRoot?: string;
  privatePromptsRoot?: string;
  releaseContext?: PromptReleaseLoadContext | null;
  enabledAgents?: ReadonlySet<string>;
  enabledAgentStages?: ReadonlySet<string>;
}): Promise<RuntimePromptCheckReport> {
  const allStageKeys = new Set(
    RUNTIME_AGENT_SPECS.flatMap((spec) =>
      spec.stages.map((stage) => `${spec.agent}:${stage.stage}`),
    ),
  );
  validateSelection(opts.enabledAgents, new Set(RUNTIME_AGENT_SPECS.map((spec) => spec.agent)));
  validateSelection(opts.enabledAgentStages, allStageKeys);
  const rows: RuntimePromptCheckRow[] = [];
  for (const spec of RUNTIME_AGENT_SPECS) {
    if (!isSelected(opts.enabledAgents, spec.agent)) continue;
    const layer = LAYER_BY_AGENT[spec.agent];
    if (!layer) throw new Error(`runtime_agent_layer_missing:${spec.agent}`);
    for (const stage of spec.stages) {
      const stageKey = `${spec.agent}:${stage.stage}`;
      if (!isSelected(opts.enabledAgentStages, stageKey)) continue;
      const reasons = await promptReasons(opts, spec.agent, stage.stage);
      rows.push({
        agent: spec.agent,
        layer,
        stage: stage.stage,
        ready: reasons.length === 0,
        reasons,
      });
    }
  }
  if (rows.length === 0) throw new Error("runtime_prompt_selection_empty");
  return {
    schema_version: "runtime_prompt_check_v1",
    cohort: opts.cohort,
    total_runtime_agents: new Set(rows.map((row) => row.agent)).size,
    total_runtime_stages: rows.length,
    ready: rows.every((row) => row.ready),
    rows,
  };
}

function isSelected(selection: ReadonlySet<string> | undefined, value: string): boolean {
  return !selection || selection.has("*") || selection.has(value);
}

function validateSelection(
  selection: ReadonlySet<string> | undefined,
  allowed: ReadonlySet<string>,
): void {
  if (!selection || selection.has("*")) return;
  const unknown = [...selection].filter((value) => !allowed.has(value)).sort();
  if (unknown.length > 0) throw new Error(`runtime_prompt_selection_unknown:${unknown.join(",")}`);
}

async function promptReasons(
  opts: {
    cohort: string;
    promptsRoot?: string;
    privatePromptsRoot?: string;
    releaseContext?: PromptReleaseLoadContext | null;
  },
  agent: string,
  stage: RuntimeAgentStageId,
): Promise<string[]> {
  try {
    const [zh, en] = await Promise.all(
      (["zh", "en"] as const).map((language) =>
        loadPrompt({
          agent,
          cohort: opts.cohort,
          language,
          stage,
          ...(opts.promptsRoot ? { promptsRoot: opts.promptsRoot } : {}),
          ...(opts.privatePromptsRoot ? { privatePromptsRoot: opts.privatePromptsRoot } : {}),
          ...(opts.releaseContext !== undefined ? { releaseContext: opts.releaseContext } : {}),
          noCache: true,
        }),
      ),
    );
    return containsPrivateKnotPromptContent(`${zh}\n${en}`)
      ? ["private_policy_content_embedded_in_model_prompt"]
      : [];
  } catch (error) {
    return [error instanceof Error ? error.message : String(error)];
  }
}
