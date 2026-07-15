import { writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { renderRuntimeAgentManifestArtifact } from "../src/agents/prompts/runtime_agent_spec.js";

const output = resolve(
  process.cwd(),
  "..",
  "registry",
  "prompt_checks",
  "runtime_agent_manifest_v2.json",
);
writeFileSync(output, renderRuntimeAgentManifestArtifact(), "utf8");
