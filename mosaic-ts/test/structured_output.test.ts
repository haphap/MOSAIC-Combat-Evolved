import { describe, expect, it } from "vitest";
import { tryParseJsonObject } from "../src/agents/helpers/structured_output.js";

describe("tryParseJsonObject", () => {
  it.each([
    '{"value": 1}',
    '```json\n{"value": 1}\n```',
    'Here is the result: {"value": 1} trailing prose',
  ])("parses JSON from %s", (text) => {
    expect(tryParseJsonObject(text)).toEqual({ value: 1 });
  });

  it("keeps braces and escaped quotes inside strings", () => {
    const value = { nested: { text: 'a } brace and a "quote"' } };
    expect(tryParseJsonObject(`Result: ${JSON.stringify(value)} done`)).toEqual(value);
  });

  it.each([
    "",
    "plain prose",
    '{"value":',
    "{invalid}",
  ])("returns null for an unparseable response: %s", (text) => {
    expect(tryParseJsonObject(text)).toBeNull();
  });
});
