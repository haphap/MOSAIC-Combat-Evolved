import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { z } from "zod";
import {
  buildExecutionBehaviorReleaseManifest,
  ExecutionBehaviorReleaseManifestSchema,
  renderExecutionBehaviorReleaseManifest,
} from "../src/autoresearch/execution_behavior_release.js";

const args = parseArgs(process.argv.slice(2));
const schemaOut = resolve(
  args.get("schema-out") ?? "../schemas/execution_behavior_release_manifest_v1.schema.json",
);
mkdirSync(dirname(schemaOut), { recursive: true });
writeFileSync(schemaOut, `${JSON.stringify(z.toJSONSchema(ExecutionBehaviorReleaseManifestSchema), null, 2)}\n`);

if (args.has("schema-only")) process.exit(0);

const privatePromptsRoot = required(args, "private-prompts-root");
const privatePromptCommit = required(args, "private-prompt-commit");
const manifest = buildExecutionBehaviorReleaseManifest({
  privatePromptsRoot,
  bundledPromptsRoot: args.get("bundled-prompts-root") ?? "../prompts/mosaic",
  privatePromptCommit,
  provider: args.get("provider") ?? "anthropic",
  model: args.get("model") ?? "claude-sonnet-4",
  baseUrlMode:
    args.get("base-url-mode") === "CONFIGURED_PRIVATE_ENDPOINT"
      ? "CONFIGURED_PRIVATE_ENDPOINT"
      : "PROVIDER_DEFAULT",
});
const out = resolve(
  args.get("out") ?? "../registry/prompt_checks/execution_behavior_release_manifest_v1.json",
);
mkdirSync(dirname(out), { recursive: true });
writeFileSync(out, renderExecutionBehaviorReleaseManifest(manifest));

function parseArgs(values: string[]): Map<string, string> {
  const parsed = new Map<string, string>();
  for (let index = 0; index < values.length; index += 1) {
    const token = values[index];
    if (!token?.startsWith("--")) throw new Error(`unexpected argument ${token}`);
    const key = token.slice(2);
    if (key === "schema-only") {
      parsed.set(key, "true");
      continue;
    }
    const value = values[index + 1];
    if (!value || value.startsWith("--")) throw new Error(`missing value for --${key}`);
    parsed.set(key, value);
    index += 1;
  }
  return parsed;
}

function required(args: ReadonlyMap<string, string>, key: string): string {
  const value = args.get(key)?.trim();
  if (!value) throw new Error(`--${key} is required`);
  return value;
}
