import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { upsertRuntimeEvidenceContract } from "../src/agents/prompts/research_knobs_projection.js";
import { RUNTIME_AGENT_SPECS } from "../src/agents/prompts/runtime_agent_spec.js";

const roots = process.argv.slice(2);
if (roots.length === 0) throw new Error("provide at least one prompts/mosaic root");
for (const root of roots) {
  for (const spec of RUNTIME_AGENT_SPECS) {
    for (const language of ["zh", "en"] as const) {
      const path = resolve(
        root,
        "cohort_default",
        spec.layer,
        `${spec.agent}.${language}.md`,
      );
      if (!existsSync(path)) throw new Error(`prompt missing: ${path}`);
      const current = readFileSync(path, "utf8");
      let updated = upsertRuntimeEvidenceContract(current, spec, language);
      if (spec.agent === "cio") updated = removeHandwrittenCioSchema(updated, language);
      writeFileSync(path, updated, "utf8");
    }
  }
}

function removeHandwrittenCioSchema(text: string, language: "zh" | "en"): string {
  const heading = language === "zh" ? "## 输出 schema" : "## Output schema";
  const authority =
    language === "zh"
      ? "以运行时提供的 JSON Schema 为唯一字段与约束来源；不得使用手写字段表。"
      : "Treat the runtime-provided JSON Schema as the sole source of fields and constraints; do not use a hand-maintained field table.";
  return text.replace(
    new RegExp(`${escapeRegExp(heading)}\\s*\\n\\s*\`\`\`json[\\s\\S]*?\`\`\``, "g"),
    `${heading}\n\n${authority}`,
  );
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
