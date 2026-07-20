import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  CANONICAL_JSON_CONTRACT_VERSION,
  canonicalJson,
  canonicalJsonHash,
} from "../src/agents/helpers/canonical_json.js";

interface CanonicalCase {
  name: string;
  value: unknown;
  canonical: string;
}

const cases = JSON.parse(
  readFileSync(resolve(process.cwd(), "../tests/fixtures/canonical_json_v1_cases.json"), "utf8"),
) as CanonicalCase[];

describe("cross-runtime canonical JSON", () => {
  it("uses a versioned JCS contract", () => {
    expect(CANONICAL_JSON_CONTRACT_VERSION).toBe("rfc8785_jcs_v1");
  });

  for (const row of cases) {
    it(row.name, () => {
      expect(canonicalJson(row.value)).toBe(row.canonical);
      expect(canonicalJsonHash(row.value)).toMatch(/^sha256:[0-9a-f]{64}$/);
    });
  }

  it.each([
    Number.NaN,
    Number.POSITIVE_INFINITY,
    Number.NEGATIVE_INFINITY,
  ])("rejects non-finite number %s", (value) => {
    expect(() => canonicalJson({ value })).toThrow(/non-finite/);
  });

  it("rejects invalid Unicode and values JSON.stringify would silently omit", () => {
    expect(() => canonicalJson({ value: "\ud800" })).toThrow(/surrogate/);
    expect(() => canonicalJson({ value: undefined })).toThrow(/undefined/);
  });
});
