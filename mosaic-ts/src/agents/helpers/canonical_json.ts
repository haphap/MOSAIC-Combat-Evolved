import { createHash } from "node:crypto";

/** Cross-runtime canonical JSON contract used for public authority hashes. */
export const CANONICAL_JSON_CONTRACT_VERSION = "rfc8785_jcs_v1" as const;

/**
 * Serialize the JSON data model using RFC 8785/JCS ordering and ECMAScript
 * number rendering. Unsupported JavaScript values and invalid Unicode fail
 * closed instead of being silently dropped or rewritten by JSON.stringify.
 */
export function canonicalJson(value: unknown): string {
  if (value === null) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new Error("canonical JSON rejects non-finite numbers");
    return JSON.stringify(value);
  }
  if (typeof value === "string") {
    assertValidUnicode(value);
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => canonicalJson(item)).join(",")}]`;
  }
  if (typeof value !== "object") {
    throw new Error(`canonical JSON rejects ${typeof value} values`);
  }
  if (Object.prototype.toString.call(value) !== "[object Object]") {
    throw new Error("canonical JSON requires JSON objects");
  }
  const record = value as Record<string, unknown>;
  const keys = Object.keys(record).sort();
  return `{${keys
    .map((key) => {
      assertValidUnicode(key);
      return `${JSON.stringify(key)}:${canonicalJson(record[key])}`;
    })
    .join(",")}}`;
}

export function canonicalJsonHash(value: unknown): string {
  return `sha256:${createHash("sha256").update(canonicalJson(value)).digest("hex")}`;
}

function assertValidUnicode(value: string): void {
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (!(next >= 0xdc00 && next <= 0xdfff)) {
        throw new Error("canonical JSON rejects unpaired UTF-16 surrogates");
      }
      index += 1;
    } else if (code >= 0xdc00 && code <= 0xdfff) {
      throw new Error("canonical JSON rejects unpaired UTF-16 surrogates");
    }
  }
}
