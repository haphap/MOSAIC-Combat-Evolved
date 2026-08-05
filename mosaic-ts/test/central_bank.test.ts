import { describe, expect, it } from "vitest";
import { MACRO_ROLE_CONTRACTS } from "../src/agents/macro/_contracts.js";

describe("central_bank boundary", () => {
  it("reads deterministic inputs rather than other agents", () => {
    expect(MACRO_ROLE_CONTRACTS.central_bank.requiredTools).toEqual(["get_central_bank_snapshot"]);
    expect(MACRO_ROLE_CONTRACTS.central_bank.prohibited.en.join(" ")).toContain(
      "other Macro LLM outputs",
    );
  });
});
