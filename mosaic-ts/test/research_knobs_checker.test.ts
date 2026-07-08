import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { AGENTS_BY_LAYER } from "../src/agents/prompts/cohorts.js";
import { clearPromptCache } from "../src/agents/prompts/loader.js";
import { checkResearchKnobsPrompts } from "../src/agents/prompts/research_knobs_checker.js";
import {
  buildRuntimeResearchKnobs,
  upsertResearchKnobsFence,
} from "../src/agents/prompts/research_knobs_projection.js";
import { RUNTIME_AGENT_SPECS } from "../src/agents/prompts/runtime_agent_spec.js";

interface FakeRoot {
  root: string;
  cleanup: () => void;
}

function makeRoot(): FakeRoot {
  const root = mkdtempSync(join(tmpdir(), "mosaic-knobs-check-"));
  return { root, cleanup: () => rmSync(root, { recursive: true, force: true }) };
}

function writePrompt(
  root: string,
  agent: string,
  layer: string,
  lang: "zh" | "en",
  text: string,
): void {
  const dir = join(root, "cohort_default", layer);
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, `${agent}.${lang}.md`), text, "utf-8");
}

function researchKnobsFence(): string {
  return `\`\`\`research-knobs
research-knobs:
  schema_version: research_knobs_v1
  layer: macro
  agent: macro.central_bank
  research_scope:
    must_cover: [liquidity_regime]
    must_not_cover: [final_portfolio_sizing]
  prediction_targets:
    - id: policy_stance_1w
      target_variable: central_bank_stance
      horizon: 1w
      allowed_outputs: [tightening, neutral, easing]
  evidence_registry:
    pboc_liquidity:
      tool: get_pboc_ops
      metric: pboc_net_injection_7d
      current_data: true
      primary: true
  evidence_weights:
    pboc_liquidity: 1.0
  lookbacks:
    net_injection_window_days: 7
  thresholds: {}
  confidence_caps:
    missing_current_data:
      cap: 0.55
      trigger: missing_required_evidence
      enforcement: code
      required_evidence: [pboc_liquidity]
  tie_breaks: []
  mutation_targets:
    - path: /rule_packs/macro.central_bank.liquidity.v1/rules/macro.central_bank.soft.001/learnable_parameters/pboc_liquidity_weight/value
      type: number
      min: 0
      max: 1
\`\`\``;
}

describe("checkResearchKnobsPrompts", () => {
  let fake: FakeRoot;
  beforeEach(() => {
    fake = makeRoot();
    clearPromptCache();
  });

  afterEach(() => {
    fake.cleanup();
    clearPromptCache();
  });

  it("checks enabled runtime agents and reports legacy agents explicitly", async () => {
    writePrompt(
      fake.root,
      "central_bank",
      "macro",
      "zh",
      `${researchKnobsFence()}\n\n# central_bank zh`,
    );
    writePrompt(
      fake.root,
      "central_bank",
      "macro",
      "en",
      `${researchKnobsFence()}\n\n# central_bank en`,
    );

    const report = await checkResearchKnobsPrompts({
      cohort: "cohort_default",
      promptsRoot: fake.root,
      enabledAgents: new Set(["central_bank"]),
    });

    expect(report.ready).toBe(true);
    expect(report.total_runtime_agents).toBe(25);
    expect(report.enabled_agents).toEqual(["central_bank"]);
    expect(report.legacy_agents).toHaveLength(24);
    const row = report.rows.find((item) => item.agent === "central_bank");
    expect(row?.status).toBe("ready");
    expect(row?.snapshot_hash).toMatch(/^sha256:/);
    for (const agent of AGENTS_BY_LAYER.sector) {
      expect(report.legacy_agents).toContain(agent);
    }
  });

  it("fails enabled agents without a research-knobs fence", async () => {
    writePrompt(fake.root, "central_bank", "macro", "zh", "# central_bank zh");
    writePrompt(fake.root, "central_bank", "macro", "en", "# central_bank en");

    const report = await checkResearchKnobsPrompts({
      cohort: "cohort_default",
      promptsRoot: fake.root,
      enabledAgents: new Set(["central_bank"]),
    });

    expect(report.ready).toBe(false);
    const row = report.rows.find((item) => item.agent === "central_bank");
    expect(row?.status).toBe("failed");
    expect(row?.reasons.join("\n")).toContain("expected exactly one research-knobs fence");
  });

  it("fails non-runtime prompt files in runtime layer directories", async () => {
    writePrompt(
      fake.root,
      "central_bank",
      "macro",
      "zh",
      `${researchKnobsFence()}\n\n# central_bank zh`,
    );
    writePrompt(
      fake.root,
      "central_bank",
      "macro",
      "en",
      `${researchKnobsFence()}\n\n# central_bank en`,
    );
    writePrompt(fake.root, "aschenbrenner", "superinvestor", "zh", "# orphan");

    const report = await checkResearchKnobsPrompts({
      cohort: "cohort_default",
      promptsRoot: fake.root,
      enabledAgents: new Set(["central_bank"]),
    });

    expect(report.ready).toBe(false);
    const row = report.rows.find((item) => item.agent === "aschenbrenner");
    expect(row?.status).toBe("failed");
    expect(row?.reasons.join("\n")).toContain("orphan_prompt_file");
  });

  it("accepts generated research-knobs projections for all 25 runtime agents", async () => {
    for (const spec of RUNTIME_AGENT_SPECS) {
      const knobs = buildRuntimeResearchKnobs(spec);
      for (const lang of ["zh", "en"] as const) {
        writePrompt(
          fake.root,
          spec.agent,
          spec.layer,
          lang,
          upsertResearchKnobsFence(`# ${spec.agent} ${lang}`, knobs),
        );
      }
    }

    const report = await checkResearchKnobsPrompts({
      cohort: "cohort_default",
      promptsRoot: fake.root,
      enabledAgents: new Set(["*"]),
    });

    expect(report.ready).toBe(true);
    expect(report.enabled_agents).toHaveLength(25);
    expect(report.legacy_agents).toEqual([]);
    const cioSpec = RUNTIME_AGENT_SPECS.find((spec) => spec.agent === "cio");
    expect(cioSpec).toBeDefined();
    if (!cioSpec) return;
    const cioKnobs = buildRuntimeResearchKnobs(cioSpec);
    expect(cioKnobs.evidence_registry.upstream_context?.source).toBe("daily_cycle_state");
    expect(cioKnobs.evidence_weights.rke_prior).toBe(0);
  });
});
