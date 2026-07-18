import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import {
  MACRO_AGENT_IDS,
  TOMBSTONED_MACRO_AGENT_IDS,
  renderMacroPromptBody,
} from "../src/agents/macro/_contracts.js";
import { upsertRuntimeEvidenceContract } from "../src/agents/prompts/research_knobs_projection.js";
import { RUNTIME_AGENT_SPEC_BY_AGENT } from "../src/agents/prompts/runtime_agent_spec.js";

interface Target {
  root: string;
  cohorts: string[];
}

const args = process.argv.slice(2);
const targets = parseTargets(args.filter((arg) => arg !== "--hide-research-knobs"));
if (targets.length === 0) {
  throw new Error("usage: generate_macro_prompts.ts <prompts/mosaic root>:<cohort,...> [...]");
}

for (const target of targets) {
  for (const cohort of target.cohorts) {
    const macroDir = resolve(target.root, cohort, "macro");
    mkdirSync(macroDir, { recursive: true });
    for (const retired of TOMBSTONED_MACRO_AGENT_IDS) {
      rmSync(join(macroDir, `${retired}.zh.md`), { force: true });
      rmSync(join(macroDir, `${retired}.en.md`), { force: true });
    }
    for (const agent of MACRO_AGENT_IDS) {
      const spec = RUNTIME_AGENT_SPEC_BY_AGENT.get(agent);
      if (!spec) throw new Error(`runtime spec missing for ${agent}`);
      for (const language of ["zh", "en"] as const) {
        const prompt = upsertRuntimeEvidenceContract(
          renderMacroPromptBody(agent, language, cohort),
          spec,
          language,
          {
            includeResearchKnobDetails: false,
          },
        );
        writeFileSync(join(macroDir, `${agent}.${language}.md`), prompt, "utf8");
      }
    }
  }
}

function parseTargets(args: string[]): Target[] {
  return args.map((arg) => {
    const separator = arg.lastIndexOf(":");
    if (separator <= 0) throw new Error(`invalid target ${arg}`);
    const root = arg.slice(0, separator);
    const cohorts = arg
      .slice(separator + 1)
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    if (cohorts.length === 0) throw new Error(`target has no cohorts: ${arg}`);
    return { root, cohorts };
  });
}
