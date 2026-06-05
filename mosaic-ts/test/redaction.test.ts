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

  it("redacts URL query secrets from provider/tool errors", () => {
    const text =
      "400 Client Error: https://api.example.test/fred?series_id=X&api_key=abc123&file_type=json";

    expect(redactSensitiveText(text)).toBe(
      "400 Client Error: https://api.example.test/fred?series_id=X&api_key=<redacted-secret>&file_type=json",
    );
  });

  it("redacts provider endpoint fields and CLI base-url arguments", () => {
    const text =
      "$ tsx src/cli/index.ts daily-cycle --base-url https://provider.example/v1\n" +
      'provider=openai model=mimo-v2.5-pro base=https://provider.example/v1 config={"baseUrl":"https://provider.example/v1"}';

    expect(redactSensitiveText(text)).toBe(
      "$ tsx src/cli/index.ts daily-cycle --base-url <redacted-endpoint>\n" +
        'provider=openai model=mimo-v2.5-pro base=<redacted-endpoint> config={"baseUrl":"<redacted-endpoint>"}',
    );
  });

  it("redacts serialized secret fields and auth headers", () => {
    const text = `headers: Authorization: Bearer sk-secret, body={"token":"tp-secret","key":"plain"}`;

    expect(redactSensitiveText(text)).toBe(
      `headers: Authorization: <redacted-secret>, body={"token":"<redacted-secret>","key":"<redacted-secret>"}`,
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
