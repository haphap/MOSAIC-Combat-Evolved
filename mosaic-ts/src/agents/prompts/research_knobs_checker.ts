import type { Dirent } from "node:fs";
import { readdir } from "node:fs/promises";
import { basename, join } from "node:path";
import { researchKnobsEnabledAgents } from "../helpers/research_knobs.js";
import {
  AGENTS_BY_LAYER,
  ALL_AGENTS,
  LAYER_BY_AGENT,
  normalizePromptsRoot,
  type Layer,
} from "./cohorts.js";
import { loadPromptWithKnobs } from "./loader.js";
import { RUNTIME_AGENT_SPEC_BY_AGENT, RUNTIME_AGENT_SPECS } from "./runtime_agent_spec.js";

export interface ResearchKnobsCheckRow {
  agent: string;
  layer: Layer;
  status: "ready" | "failed" | "legacy";
  ready: boolean;
  enabled: boolean;
  snapshot_hash?: string;
  reasons: string[];
}

export interface ResearchKnobsCheckReport {
  schema_version: "research_knobs_prompt_check_v1";
  cohort: string;
  total_runtime_agents: number;
  enabled_agents: string[];
  legacy_agents: string[];
  ready: boolean;
  rows: ResearchKnobsCheckRow[];
}

export async function checkResearchKnobsPrompts(opts: {
  cohort: string;
  promptsRoot?: string;
  privatePromptsRoot?: string;
  enabledAgents?: ReadonlySet<string>;
}): Promise<ResearchKnobsCheckReport> {
  const enabled =
    opts.enabledAgents ?? (opts.privatePromptsRoot ? new Set(["*"]) : researchKnobsEnabledAgents());
  const rows: ResearchKnobsCheckRow[] = [];
  const runtimeAgents = new Set(RUNTIME_AGENT_SPECS.map((spec) => spec.agent));
  const manifestDrift = ALL_AGENTS.filter((agent) => !runtimeAgents.has(agent));
  rows.push(...(await collectOrphanPromptRows(opts)));
  for (const agent of ALL_AGENTS) {
    const spec = RUNTIME_AGENT_SPEC_BY_AGENT.get(agent);
    const layer = spec?.layer ?? LAYER_BY_AGENT[agent];
    if (!layer) continue;
    if (!spec) {
      rows.push({
        agent,
        layer,
        status: "failed",
        ready: false,
        enabled: true,
        reasons: ["runtime_agent_spec_missing"],
      });
      continue;
    }
    const isEnabled = enabled.has("*") || enabled.has(agent);
    if (!isEnabled) {
      rows.push({
        agent,
        layer,
        status: "legacy",
        ready: false,
        enabled: false,
        reasons: ["agent_not_enabled_for_research_knobs"],
      });
      continue;
    }
    try {
      const loaded = await loadPromptWithKnobs({
        agent,
        cohort: opts.cohort,
        ...(opts.promptsRoot ? { promptsRoot: opts.promptsRoot } : {}),
        ...(opts.privatePromptsRoot ? { privatePromptsRoot: opts.privatePromptsRoot } : {}),
        noCache: true,
      });
      const semanticReasons = validateLoadedKnobsAgainstRuntimeSpec(loaded.snapshot.knobs, spec);
      if (semanticReasons.length > 0) {
        rows.push({
          agent,
          layer,
          status: "failed",
          ready: false,
          enabled: true,
          reasons: semanticReasons,
        });
        continue;
      }
      rows.push({
        agent,
        layer,
        status: "ready",
        ready: true,
        enabled: true,
        snapshot_hash: loaded.snapshot.hash,
        reasons: [],
      });
    } catch (err) {
      rows.push({
        agent,
        layer,
        status: "failed",
        ready: false,
        enabled: true,
        reasons: [(err as Error).message],
      });
    }
  }
  const enabledRows = rows.filter((row) => row.enabled);
  const legacyAgents = rows.filter((row) => !row.enabled).map((row) => row.agent);
  return {
    schema_version: "research_knobs_prompt_check_v1",
    cohort: opts.cohort,
    total_runtime_agents: ALL_AGENTS.length,
    enabled_agents: enabledRows.map((row) => row.agent),
    legacy_agents: legacyAgents,
    ready:
      manifestDrift.length === 0 && enabledRows.length > 0 && enabledRows.every((row) => row.ready),
    rows,
  };
}

async function collectOrphanPromptRows(opts: {
  cohort: string;
  promptsRoot?: string;
  privatePromptsRoot?: string;
}): Promise<ResearchKnobsCheckRow[]> {
  const roots = [
    ...new Set(
      [opts.privatePromptsRoot, opts.promptsRoot]
        .filter((root): root is string => root !== undefined && root.length > 0)
        .map((root) => normalizePromptsRoot(root)),
    ),
  ] as string[];
  const rows: ResearchKnobsCheckRow[] = [];
  for (const root of roots) {
    for (const layer of Object.keys(AGENTS_BY_LAYER) as Layer[]) {
      const dir = join(root, opts.cohort, layer);
      let entries: Dirent[];
      try {
        entries = await readdir(dir, { withFileTypes: true });
      } catch {
        continue;
      }
      const allowed = new Set(AGENTS_BY_LAYER[layer]);
      for (const entry of entries) {
        if (!entry.isFile() || !entry.name.endsWith(".md")) continue;
        const agent = basename(entry.name).replace(/\.(zh|en)\.md$/, "");
        if (!entry.name.match(/\.(zh|en)\.md$/)) continue;
        if (allowed.has(agent)) continue;
        rows.push({
          agent,
          layer,
          status: "failed",
          ready: false,
          enabled: true,
          reasons: [`orphan_prompt_file:${join(dir, entry.name)}`],
        });
      }
    }
  }
  return rows;
}

function validateLoadedKnobsAgainstRuntimeSpec(
  knobs: {
    agent: string;
    layer: Layer;
    evidence_registry: Record<
      string,
      { tool?: string | undefined; source?: string | undefined; metric: string }
    >;
    evidence_weights: Record<string, number>;
    mutation_targets: ReadonlyArray<{ path: string }>;
  },
  spec: {
    agent: string;
    layer: Layer;
    promptIrAgentId: string;
    requiredTools: ReadonlyArray<string>;
  },
): string[] {
  const reasons: string[] = [];
  if (knobs.agent !== spec.promptIrAgentId) {
    reasons.push(`agent_mismatch:${knobs.agent}:expected:${spec.promptIrAgentId}`);
  }
  if (knobs.layer !== spec.layer) {
    reasons.push(`layer_mismatch:${knobs.layer}:expected:${spec.layer}`);
  }
  const allowedTools = new Set(spec.requiredTools);
  for (const [key, entry] of Object.entries(knobs.evidence_registry)) {
    if (!entry.tool && !entry.source) {
      reasons.push(`evidence_source_missing:${key}`);
    }
    if (entry.tool && !allowedTools.has(entry.tool)) {
      reasons.push(`evidence_tool_not_allowed:${key}:${entry.tool}`);
    }
    if (entry.source && !["daily_cycle_state", "upstream_agent_outputs"].includes(entry.source)) {
      reasons.push(`evidence_source_not_allowed:${key}:${entry.source}`);
    }
    if (!entry.metric.trim()) {
      reasons.push(`evidence_metric_missing:${key}`);
    }
  }
  for (const key of Object.keys(knobs.evidence_weights)) {
    if (!(key in knobs.evidence_registry)) {
      reasons.push(`evidence_weight_missing_registry:${key}`);
    }
  }
  const rkePriorWeight = knobs.evidence_weights.rke_prior;
  if (rkePriorWeight !== undefined && rkePriorWeight !== 0) {
    reasons.push("rke_prior_weight_nonzero_without_promotion_gate");
  }
  for (const target of knobs.mutation_targets) {
    if (!target.path.startsWith("/rule_packs/")) {
      reasons.push(`mutation_target_not_rule_pack:${target.path}`);
    }
    if (target.path.startsWith("/research_weighting/source_profiles/")) {
      reasons.push(`mutation_target_report_source_reliability:${target.path}`);
    }
    if (!target.path.endsWith("/value") && !target.path.includes("/confidence_policy/")) {
      reasons.push(`mutation_target_not_learnable_or_confidence_policy:${target.path}`);
    }
  }
  return reasons;
}
