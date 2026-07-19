import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  KNOT_RUNTIME_CONTRACT_REF,
  KnotRuntimeContractRefSchema,
  renderKnotRuntimeContractRefArtifact,
} from "../src/autoresearch/knot_contract.js";

describe("private KNOT contract boundary", () => {
  it("publishes only opaque integrity references", () => {
    expect(KnotRuntimeContractRefSchema.parse(KNOT_RUNTIME_CONTRACT_REF)).toEqual(
      KNOT_RUNTIME_CONTRACT_REF,
    );
    expect(JSON.parse(renderKnotRuntimeContractRefArtifact())).toEqual(KNOT_RUNTIME_CONTRACT_REF);
    expect(JSON.stringify(KNOT_RUNTIME_CONTRACT_REF)).not.toMatch(
      /minimum_accountable_pairs|promotion_mean_delta_floor|agent_failure_score/,
    );
  });

  it("reproduces the committed public reference artifact exactly", () => {
    const committed = readFileSync(
      join(process.cwd(), "..", "registry", "prompt_checks", "knot_runtime_contract_ref_v2.json"),
      "utf8",
    );
    expect(committed).toBe(renderKnotRuntimeContractRefArtifact());
  });
});
