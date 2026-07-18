import { writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { renderOutcomeContractManifestArtifact } from "../src/autoresearch/outcome_registry.ts";

const output = resolve(
  process.cwd(),
  "..",
  "registry",
  "prompt_checks",
  "agent_outcome_contract_manifest_v2.json",
);
writeFileSync(output, renderOutcomeContractManifestArtifact(), "utf8");
