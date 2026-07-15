import { readdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { parseResearchKnobsPrompt } from "../src/agents/helpers/research_knobs.js";
import { MACRO_AGENT_IDS, MACRO_ROLE_CONTRACTS } from "../src/agents/macro/_contracts.js";

const root = resolve(process.cwd(), "..", "prompts", "mosaic", "cohort_default", "macro");
const privateManifest = JSON.parse(
  readFileSync(
    resolve(
      process.cwd(),
      "..",
      "registry",
      "prompt_checks",
      "macro_prompt_role_contract_manifest_v1.json",
    ),
    "utf8",
  ),
) as {
  agents: string[];
  cohort_count: number;
  languages: string[];
  legacy_agents: Array<{ agent: string; status: string }>;
  private_prompt_commit: string;
  prompt_count: number;
  prompt_tree_sha256: string;
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
    expect(privateManifest.agents).toEqual(MACRO_AGENT_IDS);
    expect(privateManifest.languages).toEqual(["en", "zh"]);
    expect(privateManifest.cohort_count).toBe(8);
    expect(privateManifest.prompt_count).toBe(160);
    expect(privateManifest.private_prompt_commit).toMatch(/^[0-9a-f]{40}$/);
    expect(privateManifest.prompt_tree_sha256).toMatch(/^[0-9a-f]{64}$/);
    expect(privateManifest.legacy_agents).toEqual([
      { agent: "emerging_markets", status: "legacy_unverified" },
      { agent: "news_sentiment", status: "legacy_unverified" },
    ]);
  });

  it.each(MACRO_AGENT_IDS)("binds %s to one role-scoped tool and common schema", (agent) => {
    for (const language of ["zh", "en"] as const) {
      const text = prompt(agent, language);
      const parsed = parseResearchKnobsPrompt(text);
      const tools = Object.values(parsed.knobs.evidence_registry).flatMap((entry) =>
        entry.tool ? [entry.tool] : [],
      );
      expect(tools).toEqual(MACRO_ROLE_CONTRACTS[agent].requiredTools);
      expect(parsed.body).toContain(MACRO_ROLE_CONTRACTS[agent].responsibility[language]);
      expect(parsed.body).toContain("direction");
      expect(parsed.body).toContain("strength");
      expect(parsed.body).toContain("claim_refs");
      expect(parsed.body).not.toContain("```json");
      expect(parsed.body).not.toContain("retail_sentiment_score");
      expect(parsed.body).not.toContain("contrarian_flag");
      expect(parsed.body).not.toMatch(/required tools[^\n]*(get_news|get_caixin|get_xueqiu)/i);
    }
  });

  it("removes search/social dependencies and old required-role mistakes", () => {
    const china = prompt("china", "en");
    const dollar = prompt("dollar", "en");
    const volatility = prompt("volatility", "en");
    expect(china).not.toMatch(/must[^\n]{0,40}property/i);
    expect(china).toContain("Do not require property");
    expect(dollar).toContain("Do not label a broad-dollar index as DXY");
    expect(volatility).toContain("Do not call realized volatility iVX");
    for (const agent of MACRO_AGENT_IDS) {
      const text = `${prompt(agent, "zh")}\n${prompt(agent, "en")}`;
      expect(text).not.toContain("get_news");
      expect(text).not.toContain("get_caixin_sentiment");
      expect(text).not.toContain("get_xueqiu_heat");
      expect(text).not.toContain("Google Caixin");
    }
  });
});
