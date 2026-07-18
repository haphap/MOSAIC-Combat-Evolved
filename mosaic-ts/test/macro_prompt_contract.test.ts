import { readdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  MACRO_AGENT_IDS,
  MACRO_ROLE_CONTRACTS,
  renderMacroPromptBody,
} from "../src/agents/macro/_contracts.js";
import { ALL_AGENTS } from "../src/agents/prompts/cohorts.js";
import { upsertRuntimeEvidenceContract } from "../src/agents/prompts/research_knobs_projection.js";
import { RUNTIME_AGENT_SPECS } from "../src/agents/prompts/runtime_agent_spec.js";

const root = resolve(process.cwd(), "..", "prompts", "mosaic", "cohort_default", "macro");
const privateManifest = JSON.parse(
  readFileSync(
    resolve(
      process.cwd(),
      "..",
      "registry",
      "prompt_checks",
      "agent_prompt_role_contract_manifest_v2.json",
    ),
    "utf8",
  ),
) as {
  agents: string[];
  cohort_count: number;
  languages: string[];
  tombstoned_macro_agents: Array<{ agent: string; status: string }>;
  private_prompt_commit: string;
  prompt_count: number;
  prompt_tree_sha256: string;
  execution_behavior_release_id: string;
  execution_behavior_release_hash: string;
};

function prompt(agent: string, language: "zh" | "en") {
  return readFileSync(join(root, `${agent}.${language}.md`), "utf8");
}

describe("generated bundled macro prompts", () => {
  it("contains exactly ten bilingual current roles", () => {
    expect(
      readdirSync(root)
        .filter((file) => file.endsWith(".md"))
        .sort(),
    ).toEqual(MACRO_AGENT_IDS.flatMap((agent) => [`${agent}.en.md`, `${agent}.zh.md`]).sort());
  });

  it("pins the rebuilt private prompt tree", () => {
    expect(privateManifest.agents).toEqual(ALL_AGENTS);
    expect(privateManifest.languages).toEqual(["en", "zh"]);
    expect(privateManifest.cohort_count).toBe(8);
    expect(privateManifest.prompt_count).toBe(448);
    expect(privateManifest.private_prompt_commit).toMatch(/^[0-9a-f]{40}$/);
    expect(privateManifest.prompt_tree_sha256).toMatch(/^[0-9a-f]{64}$/);
    expect(privateManifest.execution_behavior_release_id).toMatch(
      /^execution-behavior-release:[0-9a-f]{64}$/,
    );
    expect(privateManifest.execution_behavior_release_hash).toMatch(/^sha256:[0-9a-f]{64}$/);
    expect(privateManifest.tombstoned_macro_agents).toEqual([
      { agent: "dollar", status: "legacy_unverified" },
      { agent: "yield_curve", status: "legacy_unverified" },
      { agent: "volatility", status: "legacy_unverified" },
      { agent: "emerging_markets", status: "legacy_unverified" },
      { agent: "news_sentiment", status: "legacy_unverified" },
    ]);
  });

  it.each(MACRO_AGENT_IDS)("binds %s to one role-scoped tool and common schema", (agent) => {
    for (const language of ["zh", "en"] as const) {
      const text = prompt(agent, language);
      const tools = [...new Set(text.match(/\bget_[a-z0-9_]+\b/g) ?? [])];
      expect(tools).toEqual(MACRO_ROLE_CONTRACTS[agent].requiredTools);
      expect(text).toContain(MACRO_ROLE_CONTRACTS[agent].responsibility[language]);
      expect(text).toContain("direction");
      expect(text).toContain("strength");
      expect(text).toContain("claim_refs");
      expect(text).not.toContain("```json");
      expect(text).not.toContain("```research-knobs");
      expect(text).not.toMatch(/domain knob|knob influence/i);
      expect(text).not.toContain("retail_sentiment_score");
      expect(text).not.toContain("contrarian_flag");
      expect(text).not.toMatch(/required tools[^\n]*(get_news|get_caixin|get_xueqiu)/i);
    }
  });

  it.each(MACRO_AGENT_IDS)("keeps generated bundled %s prompts synchronized", (agent) => {
    const spec = RUNTIME_AGENT_SPECS.find((candidate) => candidate.agent === agent);
    expect(spec).toBeDefined();
    if (!spec) throw new Error(`missing runtime spec for ${agent}`);
    for (const language of ["zh", "en"] as const) {
      const expected = upsertRuntimeEvidenceContract(
        renderMacroPromptBody(agent, language, "cohort_default"),
        spec,
        language,
        { includeResearchKnobDetails: false },
      );
      expect(prompt(agent, language)).toBe(expected);
    }
  });

  it("keeps every public bundled prompt free of research-knob internals", () => {
    const bundledRoot = resolve(process.cwd(), "..", "prompts", "mosaic");
    const files = readdirSync(bundledRoot, { recursive: true, encoding: "utf8" }).filter((file) =>
      file.endsWith(".md"),
    );
    expect(files).toHaveLength(56);
    for (const file of files) {
      const text = readFileSync(join(bundledRoot, file), "utf8");
      expect(text).not.toContain("```research-knobs");
      expect(text).not.toMatch(/domain knob|knob influence/i);
    }
  });

  it("keeps Chinese prompt prose localized and rejects nonexistent Macro dispositions", () => {
    for (const agent of MACRO_AGENT_IDS) {
      const zh = prompt(agent, "zh");
      const en = prompt(agent, "en");
      expect(zh).toContain("## 运行时证据输出合同");
      expect(zh).not.toMatch(/^## (Runtime|Analysis|Cohort|Prohibited)/m);
      expect(zh).not.toContain("empty disposition");
      expect(zh).not.toContain("Layer-1");
      expect(en).not.toContain("empty disposition");
    }
  });

  it("removes search/social dependencies and old required-role mistakes", () => {
    const china = prompt("china", "en");
    const centralBank = prompt("central_bank", "en");
    const usFinancialConditions = prompt("us_financial_conditions", "en");
    const euEconomy = prompt("eu_economy", "en");
    expect(china).not.toMatch(/must[^\n]{0,40}property/i);
    expect(china).toContain("Do not require property");
    expect(centralBank).toContain("PBOC reaction function");
    expect(centralBank).toContain("Do not judge foreign central banks");
    expect(centralBank).not.toContain("PBOC/Fed");
    expect(usFinancialConditions).toContain("Fed, US curves, credit/financial stress, and USD/RMB");
    expect(usFinancialConditions).toContain("Do not split the Fed, dollar, and curve");
    expect(euEconomy).toContain("Do not include the UK, Switzerland, or Norway");
    for (const agent of MACRO_AGENT_IDS) {
      const text = `${prompt(agent, "zh")}\n${prompt(agent, "en")}`;
      expect(text).not.toContain("get_news");
      expect(text).not.toContain("get_caixin_sentiment");
      expect(text).not.toContain("get_xueqiu_heat");
      expect(text).not.toContain("Google Caixin");
    }
  });
});
