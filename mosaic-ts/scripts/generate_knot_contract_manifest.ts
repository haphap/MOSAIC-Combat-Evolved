import { writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { renderKnotRuntimeContractManifestArtifact } from "../src/autoresearch/knot_contract.js";

const output = resolve(
  process.cwd(),
  "..",
  "registry",
  "prompt_checks",
  "knot_runtime_contract_manifest_v2.json",
);
writeFileSync(output, renderKnotRuntimeContractManifestArtifact(), "utf8");
