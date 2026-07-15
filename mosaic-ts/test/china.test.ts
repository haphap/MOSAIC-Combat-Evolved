import { describe, expect, it } from "vitest";
import { MACRO_ROLE_CONTRACTS } from "../src/agents/macro/_contracts.js";

describe("china boundary", () => {
  it("does not require property and does not infer PBOC", () => {
    expect(MACRO_ROLE_CONTRACTS.china.prohibited.en.join(" ")).toContain("property");
    expect(MACRO_ROLE_CONTRACTS.china.prohibited.en.join(" ")).toContain("PBOC");
  });
});
