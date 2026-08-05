import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { z } from "zod";
import {
  buildExecutionBehaviorReleaseManifest,
  ExecutionBehaviorReleaseManifestSchema,
  writeExecutionBehaviorReleaseArtifacts,
} from "../src/autoresearch/execution_behavior_release.js";

const args = parseArgs(process.argv.slice(2));
const schemaOut = resolve(
  args.get("schema-out") ?? "../schemas/execution_behavior_release_manifest_v4.schema.json",
);
mkdirSync(dirname(schemaOut), { recursive: true });
writeFileSync(
  schemaOut,
  `${JSON.stringify(z.toJSONSchema(ExecutionBehaviorReleaseManifestSchema), null, 2)}\n`,
);

if (args.has("schema-only")) process.exit(0);

const manifest = buildExecutionBehaviorReleaseManifest({
  provider: args.get("provider") ?? "anthropic",
  model: args.get("model") ?? "claude-sonnet-4",
  baseUrlMode:
    args.get("base-url-mode") === "CONFIGURED_PRIVATE_ENDPOINT"
      ? "CONFIGURED_PRIVATE_ENDPOINT"
      : "PROVIDER_DEFAULT",
});
const archiveRoot = resolve(
  args.get("archive-root") ?? "../registry/prompt_checks/execution_behavior_releases",
);
const written = writeExecutionBehaviorReleaseArtifacts({
  manifest,
  archiveRoot,
});
console.log(written.archivePath);

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
