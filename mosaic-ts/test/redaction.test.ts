import { describe, expect, it } from "vitest";
import { redactSensitiveText } from "../src/security/redaction.js";

describe("redactSensitiveText", () => {
  it("redacts configured private prompt repo paths", () => {
    const text = "failed under /tmp/private-prompts/prompts/mosaic/cohort_default/macro/x.zh.md";

    expect(redactSensitiveText(text, ["/tmp/private-prompts"])).toBe(
      "failed under <private-prompt-repo>/prompts/mosaic/cohort_default/macro/x.zh.md",
    );
  });

  it("redacts prompt body fields in serialized errors", () => {
    const text = `validation failed: {"zh_prompt":"秘密正文","en_prompt":"secret body"}`;

    expect(redactSensitiveText(text)).toBe(
      `validation failed: {"zh_prompt":"<redacted-prompt-body>","en_prompt":"<redacted-prompt-body>"}`,
    );
  });
});
