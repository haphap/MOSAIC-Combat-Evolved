import { mkdirSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import {
  NON_MACRO_BUNDLED_AGENTS,
  renderBundledPrompt,
} from "../src/agents/prompts/bundled_prompt_renderer.js";
import { LAYER_BY_AGENT } from "../src/agents/prompts/cohorts.js";
import { upsertRuntimeEvidenceContract } from "../src/agents/prompts/research_knobs_projection.js";
import { RUNTIME_AGENT_SPEC_BY_AGENT } from "../src/agents/prompts/runtime_agent_spec.js";

const root = resolve(process.argv[2] ?? "../prompts/mosaic");
const cohorts = (process.argv[3] ?? "cohort_default").split(",").filter(Boolean);
for (const cohort of cohorts) {
  for (const agent of NON_MACRO_BUNDLED_AGENTS) {
    const layer = LAYER_BY_AGENT[agent];
    const spec = RUNTIME_AGENT_SPEC_BY_AGENT.get(agent);
    if (!layer || !spec) throw new Error(`runtime prompt contract missing for ${agent}`);
    const directory = join(root, cohort, layer);
    mkdirSync(directory, { recursive: true });
    for (const language of ["zh", "en"] as const) {
      const prompt = upsertRuntimeEvidenceContract(renderBundledPrompt(agent, language, cohort), spec, language, {
        includeResearchKnobDetails: false,
      });
      writeFileSync(join(directory, `${agent}.${language}.md`), prompt, "utf8");
    }
  }
}
