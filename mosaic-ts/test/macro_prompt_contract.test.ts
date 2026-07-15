import { readdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";
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

  it("keeps every public bundled prompt free of research-knob internals", () => {
    const bundledRoot = resolve(process.cwd(), "..", "prompts", "mosaic");
    const files = readdirSync(bundledRoot, { recursive: true, encoding: "utf8" }).filter((file) =>
      file.endsWith(".md"),
    );
    expect(files).toHaveLength(50);
    for (const file of files) {
      const text = readFileSync(join(bundledRoot, file), "utf8");
      expect(text).not.toContain("```research-knobs");
      expect(text).not.toMatch(/domain knob|knob influence/i);
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
