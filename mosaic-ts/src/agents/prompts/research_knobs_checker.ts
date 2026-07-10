import type { Dirent } from "node:fs";
import { readdir } from "node:fs/promises";
import { basename, join } from "node:path";
import {
  canonicalResearchKnobs,
  type ResearchKnobs,
  researchKnobsEnabledAgents,
} from "../helpers/research_knobs.js";
import {
  AGENTS_BY_LAYER,
  ALL_AGENTS,
  LAYER_BY_AGENT,
  type Layer,
  normalizePromptsRoot,
} from "./cohorts.js";
import {
  registeredMetricIdsForTool,
  validateCrossFieldInvariants,
  validateDomainKnobClosure,
  validateWeightGroupInvariants,
} from "./domain_knob_catalog.js";
import {
  type DomainKnobValueRegistry,
  domainKnobValueRegistryPath,
  readDomainKnobValueRegistryFile,
  validateDomainKnobValueRegistry,
} from "./domain_knob_registry.js";
import { loadPromptWithKnobs } from "./loader.js";
import {
  promptIrPathForSpec,
  readPromptIrContractFile,
  validatePromptIrContractForSpec,
} from "./prompt_ir_registry.js";
import { buildRuntimeResearchKnobs } from "./research_knobs_projection.js";
import {
  RUNTIME_AGENT_SPEC_BY_AGENT,
  RUNTIME_AGENT_SPECS,
  type RuntimeAgentSpec,
  type RuntimeAgentStageId,
  runtimeAgentStageKey,
} from "./runtime_agent_spec.js";

export interface ResearchKnobsCheckRow {
  agent: string;
  layer: Layer;
  stage: RuntimeAgentStageId;
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
  total_runtime_stages: number;
  enabled_agents: string[];
  enabled_agent_stages: string[];
  legacy_agents: string[];
  legacy_agent_stages: string[];
  ready: boolean;
  rows: ResearchKnobsCheckRow[];
}

export async function checkResearchKnobsPrompts(opts: {
  cohort: string;
  promptsRoot?: string;
  privatePromptsRoot?: string;
  enabledAgents?: ReadonlySet<string>;
  enabledAgentStages?: ReadonlySet<string>;
}): Promise<ResearchKnobsCheckReport> {
  const enabled =
    opts.enabledAgents ?? (opts.privatePromptsRoot ? new Set(["*"]) : researchKnobsEnabledAgents());
  const enabledStages = opts.enabledAgentStages;
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
        stage: "agent_run",
        status: "failed",
        ready: false,
        enabled: true,
        reasons: ["runtime_agent_spec_missing"],
      });
      continue;
    }
    for (const stageSpec of spec.stages) {
      const stageKey = runtimeAgentStageKey(agent, stageSpec.stage);
      const isEnabled = enabledStages
        ? enabledStages.has("*") || enabledStages.has(stageKey) || enabledStages.has(`${agent}:*`)
        : enabled.has("*") || enabled.has(agent);
      if (!isEnabled) {
        rows.push({
          agent,
          layer,
          stage: stageSpec.stage,
          status: "legacy",
          ready: false,
          enabled: false,
          reasons: ["agent_stage_not_enabled_for_research_knobs"],
        });
        continue;
      }
      try {
        const loaded = await loadPromptWithKnobs({
          agent,
          stage: stageSpec.stage,
          cohort: opts.cohort,
          ...(opts.promptsRoot ? { promptsRoot: opts.promptsRoot } : {}),
          ...(opts.privatePromptsRoot ? { privatePromptsRoot: opts.privatePromptsRoot } : {}),
          noCache: true,
        });
        const registry = await loadDomainKnobRegistryForCheck(opts, spec);
        const promptIr = await loadPromptIrForCheck(opts, spec);
        const semanticReasons = [
          ...registry.reasons,
          ...promptIr.reasons,
          ...validatePromptBodiesAgainstRuntimeSpec(loaded.bodies, spec, loaded.snapshot.knobs),
          ...validateLoadedKnobsAgainstRuntimeSpec(loaded.snapshot.knobs, spec, {
            cohort: opts.cohort,
            domainRegistry: registry.registry,
          }),
        ];
        if (semanticReasons.length > 0) {
          rows.push({
            agent,
            layer,
            stage: stageSpec.stage,
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
          stage: stageSpec.stage,
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
          stage: stageSpec.stage,
          status: "failed",
          ready: false,
          enabled: true,
          reasons: [(err as Error).message],
        });
      }
    }
  }
  const enabledRows = rows.filter((row) => row.enabled);
  const enabledAgentStages = enabledRows.map((row) => runtimeAgentStageKey(row.agent, row.stage));
  const legacyRows = rows.filter((row) => !row.enabled);
  const legacyAgentStages = legacyRows.map((row) => runtimeAgentStageKey(row.agent, row.stage));
  return {
    schema_version: "research_knobs_prompt_check_v1",
    cohort: opts.cohort,
    total_runtime_agents: ALL_AGENTS.length,
    total_runtime_stages: RUNTIME_AGENT_SPECS.reduce(
      (count, spec) => count + spec.stages.length,
      0,
    ),
    enabled_agents: [...new Set(enabledRows.map((row) => row.agent))],
    enabled_agent_stages: enabledAgentStages,
    legacy_agents: [...new Set(legacyRows.map((row) => row.agent))],
    legacy_agent_stages: legacyAgentStages,
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
          stage: "agent_run",
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

function validatePromptBodiesAgainstRuntimeSpec(
  bodies: { zh: string; en: string },
  spec: RuntimeAgentSpec,
  knobs: ResearchKnobs,
): string[] {
  const combined = `${bodies.zh}\n${bodies.en}`;
  const reasons: string[] = [];
  for (const tool of spec.requiredTools) {
    if (!combined.includes(tool)) {
      reasons.push(`required_tool_missing_from_prompt_body:${tool}`);
    }
  }
  for (const field of spec.fieldNames) {
    if (!combined.includes(field)) {
      reasons.push(`output_schema_field_missing_from_prompt_body:${field}`);
    }
  }
  if (hasPostRunDomainDependencies(knobs)) {
    for (const field of ["declared_knob_influence_ids", "declared_influence_rationale"]) {
      if (!combined.includes(field)) {
        reasons.push(`knob_influence_field_missing_from_prompt_body:${field}`);
      }
    }
  }
  return reasons;
}

function hasPostRunDomainDependencies(knobs: ResearchKnobs): boolean {
  const metadata = knobs.projection_metadata?.domain_knob_catalog;
  if (metadata === null || typeof metadata !== "object" || Array.isArray(metadata)) return false;
  const cards = (metadata as Record<string, unknown>).cards;
  if (!Array.isArray(cards)) return false;
  return cards.some((card) => {
    if (card === null || typeof card !== "object" || Array.isArray(card)) return false;
    const dependencies = (card as Record<string, unknown>).evidence_dependencies;
    return Array.isArray(dependencies) && dependencies.length > 0;
  });
}

function validateLoadedKnobsAgainstRuntimeSpec(
  knobs: ResearchKnobs,
  spec: RuntimeAgentSpec,
  opts: { cohort: string; domainRegistry?: DomainKnobValueRegistry | null },
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
    if (entry.tool && !registeredMetricIdsForTool(entry.tool).has(entry.metric)) {
      reasons.push(`evidence_metric_not_registered:${key}:${entry.metric}`);
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
  for (const [capId, policy] of Object.entries(knobs.confidence_caps)) {
    if (policy.trigger === "conflicting_evidence") {
      reasons.push(`conflicting_evidence_direction_adapter_missing:${capId}`);
    }
  }
  if (opts.domainRegistry) {
    reasons.push(...validateDomainKnobValueRegistry(spec, opts.domainRegistry, opts.cohort));
  }
  reasons.push(...validateDomainKnobClosure(spec, knobs, { domainRegistry: opts.domainRegistry }));
  reasons.push(...validateCrossFieldInvariants(spec, knobs));
  reasons.push(...validateWeightGroupInvariants(spec, knobs));
  const expected = buildRuntimeResearchKnobs(spec, { domainRegistry: opts.domainRegistry ?? null });
  const actualProjection = JSON.stringify(canonicalResearchKnobs(knobs));
  const expectedProjection = JSON.stringify(canonicalResearchKnobs(expected));
  if (actualProjection !== expectedProjection) {
    reasons.push("research_knobs_projection_stale_or_not_canonical");
  }
  for (const target of knobs.mutation_targets) {
    if (target.path.includes("*")) {
      reasons.push(`mutation_target_not_concrete:${target.path}`);
    }
    if (!target.path.startsWith("/rule_packs/")) {
      reasons.push(`mutation_target_not_rule_pack:${target.path}`);
    }
    const ruleId = ruleIdFromTargetPath(target.path);
    if (ruleId && !isCanonicalRuleId(ruleId)) {
      reasons.push(`mutation_target_noncanonical_rule_id:${ruleId}`);
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

async function loadDomainKnobRegistryForCheck(
  opts: {
    cohort: string;
    privatePromptsRoot?: string;
  },
  spec: RuntimeAgentSpec,
): Promise<{ registry: DomainKnobValueRegistry | null; reasons: string[] }> {
  if (!opts.privatePromptsRoot) return { registry: null, reasons: [] };
  const path = domainKnobValueRegistryPath({
    privatePromptsRoot: opts.privatePromptsRoot,
    cohort: opts.cohort,
    agent: spec.agent,
  });
  const registry = await readDomainKnobValueRegistryFile(path);
  if (!registry) {
    return { registry: null, reasons: [`domain_registry_missing:${path}`] };
  }
  return { registry, reasons: [] };
}

async function loadPromptIrForCheck(
  opts: {
    cohort: string;
    privatePromptsRoot?: string;
  },
  spec: RuntimeAgentSpec,
): Promise<{ reasons: string[] }> {
  if (!opts.privatePromptsRoot) return { reasons: [] };
  const path = promptIrPathForSpec({
    privatePromptsRoot: opts.privatePromptsRoot,
    spec,
  });
  const contract = await readPromptIrContractFile(path);
  if (!contract) {
    return { reasons: [`prompt_ir_missing:${path}`] };
  }
  return { reasons: validatePromptIrContractForSpec(contract, spec, opts.cohort) };
}

function ruleIdFromTargetPath(path: string): string | null {
  const match = path.match(/^\/rule_packs\/[^/]+\/rules\/([^/]+)\//);
  return match?.[1] ?? null;
}

function isCanonicalRuleId(ruleId: string): boolean {
  const parts = ruleId.split(".");
  if (parts.length !== 4) return false;
  const [layer, agent, kind, serial] = parts;
  return (
    ["macro", "sector", "superinvestor", "decision"].includes(layer ?? "") &&
    /^[a-z][a-z0-9_]*$/.test(agent ?? "") &&
    ["soft", "hard", "guard", "prior", "policy", "risk"].includes(kind ?? "") &&
    /^\d{3}$/.test(serial ?? "")
  );
}
