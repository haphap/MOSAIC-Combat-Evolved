import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  canonicalJsonHash,
  compareCanonicalStrings,
} from "../src/agents/helpers/canonical_json.js";

const runtimeManifestPath = resolve("../registry/prompt_checks/runtime_agent_manifest_v5.json");
const outcomeManifestPath = resolve(
  "../registry/prompt_checks/agent_outcome_contract_manifest_v2.json",
);
const executionRefArgIndex = process.argv.indexOf("--execution-release-ref");
const executionManifestRef =
  executionRefArgIndex >= 0
    ? requiredArg(process.argv[executionRefArgIndex + 1], "--execution-release-ref")
    : currentExecutionManifestRef();
if (
  !/^registry\/prompt_checks\/execution_behavior_releases\/[0-9a-f]{64}--[0-9a-f]{64}\.json$/.test(
    executionManifestRef,
  )
) {
  throw new Error("--execution-release-ref must be a content-addressed execution archive ref");
}
const executionManifestPath = resolve("..", executionManifestRef);
const outArgIndex = process.argv.indexOf("--out");
const outPath = resolve(
  outArgIndex >= 0
    ? requiredArg(process.argv[outArgIndex + 1], "--out")
    : "../registry/prompt_checks/prompt_release_contract_ref_v2.json",
);

const runtimeManifest = readJson(runtimeManifestPath);
const executionManifest = readJson(executionManifestPath);
const outcomeManifest = readJson(outcomeManifestPath);
const executionContracts = requiredArray(executionManifest, "execution_contracts");

const structuredContracts = executionContracts
  .map((contract) => {
    const value = requiredObject(contract, "execution behavior agent contract");
    return {
      agent_id: requiredString(value, "agent_id"),
      language: requiredString(value, "language"),
      structured_output_schema_set_hash: requiredString(value, "structured_output_schema_set_hash"),
      structured_provider_contract_hash: requiredString(value, "structured_provider_contract_hash"),
      runtime_tool_manifest_hash: requiredString(value, "runtime_tool_manifest_hash"),
    };
  })
  .sort((left, right) =>
    compareCanonicalStrings(
      `${left.agent_id}:${left.language}`,
      `${right.agent_id}:${right.language}`,
    ),
  );

const artifact = {
  schema_version: "prompt_release_contract_ref_v2",
  sources: {
    runtime_agent_manifest: {
      path: "registry/prompt_checks/runtime_agent_manifest_v5.json",
      hash: canonicalJsonHash(runtimeManifest),
    },
    execution_behavior_release_archive: {
      path: executionManifestRef,
      release_id: requiredString(executionManifest, "execution_behavior_release_id"),
      release_hash: requiredString(executionManifest, "execution_behavior_release_hash"),
    },
    agent_outcome_contract_manifest: {
      path: "registry/prompt_checks/agent_outcome_contract_manifest_v2.json",
      registry_hash: requiredString(outcomeManifest, "registry_hash"),
    },
  },
  evaluation_contract: {
    catalog_hash: canonicalJsonHash(runtimeManifest),
    schema_hash: canonicalJsonHash(structuredContracts),
    contract_hash: canonicalJsonHash(outcomeManifest),
  },
};

writeFileSync(outPath, `${JSON.stringify(artifact, null, 2)}\n`, "utf8");

function currentExecutionManifestRef(): string {
  const current = readJson(
    resolve("../registry/prompt_checks/prompt_release_contract_ref_v2.json"),
  );
  const sources = requiredObject(current.sources, "prompt release contract sources");
  const execution = requiredObject(
    sources.execution_behavior_release_archive,
    "execution behavior release archive source",
  );
  return requiredString(execution, "path");
}

function readJson(path: string): Record<string, unknown> {
  return requiredObject(JSON.parse(readFileSync(path, "utf8")), path);
}

function requiredObject(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as Record<string, unknown>;
}

function requiredString(value: Record<string, unknown>, key: string): string {
  const field = value[key];
  if (typeof field !== "string" || field.length === 0) {
    throw new Error(`${key} must be a non-empty string`);
  }
  return field;
}

function requiredArray(value: Record<string, unknown>, key: string): unknown[] {
  const field = value[key];
  if (!Array.isArray(field) || field.length === 0) {
    throw new Error(`${key} must be a non-empty array`);
  }
  return field;
}

function requiredArg(value: string | undefined, label: string): string {
  if (!value) throw new Error(`${label} requires a value`);
  return value;
}
