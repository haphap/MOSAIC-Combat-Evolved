import {
  buildAgentInvocationId,
  finalizePrivateKnotSnapshot,
  isPrivateKnotStageEnabled,
  preparePrivateKnotSnapshot,
  privateKnotRuntimeInstalled,
} from "../helpers/private_knot_boundary.js";
import { findBundledPromptsRoot, LAYER_BY_AGENT, type Layer } from "./cohorts.js";
import { loadPrompt } from "./loader.js";
import { containsPrivateKnotPromptContent } from "./private_knot_prompt_markers.js";
import { privateKnotStageEnablement } from "./private_knot_stage_enablement.js";
import { RUNTIME_AGENT_SPECS, type RuntimeAgentStageId } from "./runtime_agent_spec.js";

export interface PrivateKnotPromptCheckRow {
  agent: string;
  layer: Layer;
  stage: RuntimeAgentStageId;
  status: "ready" | "failed" | "bundled_fallback" | "unavailable";
  ready: boolean;
  enabled: boolean;
  snapshot_hash?: string;
  reasons: string[];
}

export interface PrivateKnotPromptCheckReport {
  schema_version: "private_knot_prompt_check_v2";
  cohort: string;
  total_runtime_agents: number;
  total_runtime_stages: number;
  enabled_agents: string[];
  enabled_agent_stages: string[];
  bundled_fallback_agents: string[];
  bundled_fallback_agent_stages: string[];
  unavailable_agents: string[];
  unavailable_agent_stages: string[];
  ready: boolean;
  rows: PrivateKnotPromptCheckRow[];
}

/**
 * Public preflight validates prompt privacy and, when required, asks the
 * installed private adapter for an opaque snapshot. It never parses or
 * constructs KNOT policy values itself.
 */
export async function checkPrivateKnotPromptBoundary(opts: {
  cohort: string;
  promptsRoot?: string;
  privatePromptsRoot?: string;
  requirePrivateKnot?: boolean;
  enabledAgents?: ReadonlySet<string>;
  enabledAgentStages?: ReadonlySet<string>;
}): Promise<PrivateKnotPromptCheckReport> {
  const requirePrivate = opts.requirePrivateKnot ?? false;
  const allStageKeys = new Set(
    RUNTIME_AGENT_SPECS.flatMap((spec) =>
      spec.stages.map((stage) => `${spec.agent}:${stage.stage}`),
    ),
  );
  validateSelection(opts.enabledAgents, new Set(RUNTIME_AGENT_SPECS.map((spec) => spec.agent)));
  validateSelection(opts.enabledAgentStages, allStageKeys);
  const rows: PrivateKnotPromptCheckRow[] = [];
  for (const spec of RUNTIME_AGENT_SPECS) {
    if (!isSelected(opts.enabledAgents, spec.agent)) continue;
    const layer = LAYER_BY_AGENT[spec.agent];
    if (!layer) throw new Error(`runtime_agent_layer_missing:${spec.agent}`);
    for (const stage of spec.stages) {
      const stageKey = `${spec.agent}:${stage.stage}`;
      if (!isSelected(opts.enabledAgentStages, stageKey)) continue;
      const configuredEnablement = privateKnotStageEnablement(opts.cohort, spec.agent, stage.stage);
      const cohortAvailable = configuredEnablement === "enabled";
      const promptReasons = cohortAvailable
        ? await modelVisiblePromptReasons(opts, spec.agent, requirePrivate)
        : [];
      const reasons = [...promptReasons];
      let snapshotHash: string | undefined;
      const enabled =
        requirePrivate && cohortAvailable && privateKnotRuntimeInstalled()
          ? isPrivateKnotStageEnabled(spec.agent, stage.stage, opts.cohort)
          : false;
      if (!cohortAvailable) {
        reasons.push(`private_knot_cohort_unavailable:${opts.cohort}`);
      } else if (requirePrivate && !enabled) {
        reasons.push("private_knot_stage_unavailable");
      } else if (enabled) {
        try {
          const graphRunId = `private-knot-preflight:${opts.cohort}:${spec.agent}:${stage.stage}`;
          const promptReleaseHash = `sha256:${"0".repeat(64)}`;
          const snapshot = await preparePrivateKnotSnapshot({
            agent: spec.agent,
            stage: stage.stage,
            cohort: opts.cohort,
            invocation_mode: "NON_PRODUCTION_PREFLIGHT",
            graph_run_id: graphRunId,
            agent_invocation_id: buildAgentInvocationId({
              runId: graphRunId,
              agent: spec.agent,
              stage: stage.stage,
              cohort: opts.cohort,
              asOf: "1970-01-01",
              promptReleaseHash,
            }),
            as_of: "1970-01-01",
            execution_behavior_release_id: "non-production-preflight",
            prompt_release_id: "non-production-preflight",
            prompt_release_hash: promptReleaseHash,
            prompt_pair_hash: `sha256:${"0".repeat(64)}`,
            prompt_commit: "non-production-preflight",
            runtimeSourceStatuses: [],
          });
          snapshotHash = snapshot.snapshot_hash;
          finalizePrivateKnotSnapshot(snapshot);
        } catch (error) {
          reasons.push(error instanceof Error ? error.message : String(error));
        }
      }
      rows.push({
        agent: spec.agent,
        layer,
        stage: stage.stage,
        status:
          !cohortAvailable || (requirePrivate && !enabled)
            ? "unavailable"
            : reasons.length > 0
              ? "failed"
              : enabled
                ? "ready"
                : "bundled_fallback",
        ready: reasons.length === 0,
        enabled,
        ...(snapshotHash ? { snapshot_hash: snapshotHash } : {}),
        reasons,
      });
    }
  }

  if (rows.length === 0) throw new Error("private_knot_selection_empty");

  const enabledRows = rows.filter((row) => row.enabled);
  const bundledFallbackRows = requirePrivate
    ? []
    : rows.filter((row) => row.status !== "unavailable");
  const unavailableRows = rows.filter((row) => row.status === "unavailable");
  return {
    schema_version: "private_knot_prompt_check_v2",
    cohort: opts.cohort,
    total_runtime_agents: new Set(rows.map((row) => row.agent)).size,
    total_runtime_stages: rows.length,
    enabled_agents: [...new Set(enabledRows.map((row) => row.agent))].sort(),
    enabled_agent_stages: enabledRows.map((row) => `${row.agent}:${row.stage}`).sort(),
    bundled_fallback_agents: [...new Set(bundledFallbackRows.map((row) => row.agent))].sort(),
    bundled_fallback_agent_stages: bundledFallbackRows
      .map((row) => `${row.agent}:${row.stage}`)
      .sort(),
    unavailable_agents: [...new Set(unavailableRows.map((row) => row.agent))].sort(),
    unavailable_agent_stages: unavailableRows.map((row) => `${row.agent}:${row.stage}`).sort(),
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
  if (unknown.length > 0) throw new Error(`private_knot_selection_unknown:${unknown.join(",")}`);
}

async function modelVisiblePromptReasons(
  opts: { cohort: string; promptsRoot?: string; privatePromptsRoot?: string },
  agent: string,
  requirePrivate: boolean,
): Promise<string[]> {
  try {
    const [zh, en] = await Promise.all(
      (["zh", "en"] as const).map((language) =>
        loadPrompt({
          agent,
          cohort: opts.cohort,
          language,
          ...(requirePrivate
            ? {
                ...(opts.promptsRoot ? { promptsRoot: opts.promptsRoot } : {}),
                ...(opts.privatePromptsRoot ? { privatePromptsRoot: opts.privatePromptsRoot } : {}),
              }
            : { promptsRoot: opts.promptsRoot ?? findBundledPromptsRoot() }),
          noCache: true,
        }),
      ),
    );
    const combined = `${zh}\n${en}`;
    return containsPrivateKnotPromptContent(combined)
      ? ["private_knot_content_embedded_in_model_prompt"]
      : [];
  } catch (error) {
    return [error instanceof Error ? error.message : String(error)];
  }
}
