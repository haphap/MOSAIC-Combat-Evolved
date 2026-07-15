import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { RUNTIME_AGENT_SPECS } from "../src/agents/prompts/runtime_agent_spec.js";
import { assertRuntimePromptPreflight } from "../src/agents/prompts/runtime_prompt_preflight.js";

const ROOT = resolve(process.cwd(), "..", "prompts", "mosaic", "cohort_default");

describe("strict bilingual runtime prompt contracts", () => {
  it("passes the generated 25-agent/26-stage runtime preflight", async () => {
    const report = await assertRuntimePromptPreflight({
      cohort: "cohort_default",
      promptsRoot: resolve(ROOT, ".."),
    });
    expect(report.ready).toBe(true);
    expect(report.rows).toHaveLength(26);
  });

  it("keeps all 25 bilingual contracts generated from runtime fields without fallback ambiguity", () => {
    for (const spec of RUNTIME_AGENT_SPECS) {
      for (const language of ["zh", "en"] as const) {
        const text = readFileSync(
          resolve(ROOT, spec.layer, `${spec.agent}.${language}.md`),
          "utf8",
        );
        const block = text.match(
          /<!-- runtime-evidence-contract:start -->([\s\S]*?)<!-- runtime-evidence-contract:end -->/,
        )?.[1];
        expect(block, `${spec.agent}:${language}`).toBeTruthy();
        expect(block).not.toMatch(/conservative fallback|保守回退/i);
        for (const field of spec.fieldNames) expect(block).toContain(`\`${field}\``);
      }
    }
  });

  it("does not maintain a handwritten CIO JSON field example", () => {
    for (const language of ["zh", "en"] as const) {
      const text = readFileSync(resolve(ROOT, "decision", `cio.${language}.md`), "utf8");
      expect(text).not.toMatch(/## (?:输出 schema|Output schema)\s*\n\s*```json/);
      expect(text).toContain("decision_disposition");
      expect(text).toContain("decision_claim_refs");
    }
  });
});
