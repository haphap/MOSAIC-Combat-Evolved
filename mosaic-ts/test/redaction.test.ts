import { describe, expect, it } from "vitest";
import { redactSensitiveText, redactSensitiveValue } from "../src/security/redaction.js";

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

  it("redacts escaped quotes without leaking the prompt tail", () => {
    const text = `validation failed: {"zh_prompt":"alpha \\"inner\\" leaked tail","en_prompt":"ok"}`;

    const out = redactSensitiveText(text);

    expect(out).toContain(`"zh_prompt":"<redacted-prompt-body>"`);
    expect(out).not.toContain("inner");
    expect(out).not.toContain("leaked tail");
  });

  it("redacts contents zh/en fields from echoed RPC params", () => {
    const text = `write failed: {"contents":{"zh":"中文 \\"tail\\"","en":"english tail"},"agent":"volatility"}`;

    expect(redactSensitiveText(text)).toBe(
      `write failed: {"contents":{"zh":"<redacted-prompt-body>","en":"<redacted-prompt-body>"},"agent":"volatility"}`,
    );
  });

  it("redacts prompt bodies before structured payloads are stringified", () => {
    const payload = redactSensitiveValue({
      agent: "volatility",
      contents: { zh: "中文 prompt", en: "english prompt" },
      nested: { zh_prompt: `quoted "body"` },
    });

    expect(payload).toEqual({
      agent: "volatility",
      contents: { zh: "<redacted-prompt-body>", en: "<redacted-prompt-body>" },
      nested: { zh_prompt: "<redacted-prompt-body>" },
    });
  });
});
