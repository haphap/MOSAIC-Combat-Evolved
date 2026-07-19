import { writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { renderKnotRuntimeContractRefArtifact } from "../src/autoresearch/knot_contract.js";

const output = resolve(
  process.cwd(),
  "..",
  "registry",
  "prompt_checks",
  "knot_runtime_contract_ref_v2.json",
);
writeFileSync(output, renderKnotRuntimeContractRefArtifact(), "utf8");
