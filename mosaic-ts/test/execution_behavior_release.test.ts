import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { canonicalJson } from "../src/agents/helpers/canonical_json.js";
import { canonicalStructuredRepairDirectiveManifest } from "../src/agents/helpers/structured_repair_directives.js";
import { canonicalSectorPhaseDirectiveBundle } from "../src/agents/sector/phase_directives.js";
import {
  type BuildExecutionBehaviorReleaseInput,
  buildExecutionBehaviorReleaseManifest,
  executionBehaviorReleaseArchiveFilename,
  loadExecutionBehaviorReleaseManifest,
  STRUCTURED_PROVIDER_CONTRACT_VERSION,
  validateExecutionBehaviorReleaseManifest,
  writeExecutionBehaviorReleaseArtifacts,
} from "../src/autoresearch/execution_behavior_release.js";

const roots: string[] = [];

afterEach(() => {
  for (const root of roots) rmSync(root, { recursive: true, force: true });
  roots.length = 0;
});

describe("execution behavior release", () => {
  it("validates the committed atomic release", () => {
    const release = loadExecutionBehaviorReleaseManifest(committedExecutionReleasePath());
    expect(release.active_production_variants).toHaveLength(16);
    expect(release.execution_contracts).toHaveLength(54);
    expect(release.schema_version).toBe("execution_behavior_release_manifest_v4");
    expect(release.execution_behavior_release_id).toMatch(
      /^execution-behavior-release:[0-9a-f]{64}$/,
    );
    expect(release.execution_behavior_release_hash).toMatch(/^sha256:[0-9a-f]{64}$/);
  });

  it("builds the execution-only roster from public runtime contracts", () => {
    const manifest = buildExecutionBehaviorReleaseManifest(releaseInput());

    expect(manifest.active_production_variants).toHaveLength(16);
    expect(manifest.execution_contracts).toHaveLength(54);
    expect(
      manifest.execution_contracts.every((contract) =>
        /^sha256:[0-9a-f]{64}$/.test(contract.structured_provider_contract_hash),
      ),
    ).toBe(true);
    expect(STRUCTURED_PROVIDER_CONTRACT_VERSION).toBe("structured_provider_contract_v2");
    const contractFor = (agent: string, language: "en" | "zh") => {
      const contract = manifest.execution_contracts.find(
        (candidate) => candidate.agent_id === agent && candidate.language === language,
      );
      if (!contract) throw new Error(`execution contract fixture missing: ${agent}:${language}`);
      return contract;
    };
    expect(contractFor("china", "zh").structured_provider_contract_hash).not.toBe(
      contractFor("geopolitical", "zh").structured_provider_contract_hash,
    );
    expect(
      contractFor("energy", "zh").structured_output_schema_bindings.map((binding) => binding.phase),
    ).toEqual(["DIRECTION_RESEARCH", "CONFLICT_REVIEW", "FINAL_SELECTION"]);
    expect(
      contractFor("cio", "en").structured_output_schema_bindings.map((binding) => binding.phase),
    ).toEqual(["CIO_PROPOSAL", "CIO_FINAL"]);
    expect(contractFor("china", "zh").structured_output_schema_bindings).toHaveLength(1);
    expect(contractFor("china", "zh").execution_behavior_version).not.toBe(
      contractFor("china", "en").execution_behavior_version,
    );
    expect(validateExecutionBehaviorReleaseManifest(manifest)).toEqual(manifest);
  });

  it("does not require or bind a private Prompt commit", () => {
    const baseline = buildExecutionBehaviorReleaseManifest(releaseInput());
    const firstLegacyInput: BuildExecutionBehaviorReleaseInput & {
      privatePromptCommit: string;
      privatePromptsRoot: string;
    } = {
      ...releaseInput(),
      privatePromptCommit: "a".repeat(40),
      privatePromptsRoot: "/missing/private-a",
    };
    const secondLegacyInput: BuildExecutionBehaviorReleaseInput & {
      privatePromptCommit: string;
      privatePromptsRoot: string;
    } = {
      ...releaseInput(),
      privatePromptCommit: "b".repeat(40),
      privatePromptsRoot: "/missing/private-b",
    };

    expect(buildExecutionBehaviorReleaseManifest(firstLegacyInput)).toEqual(baseline);
    expect(buildExecutionBehaviorReleaseManifest(secondLegacyInput)).toEqual(baseline);
    expect(JSON.stringify(baseline)).not.toContain("private_prompt");
  });

  it("hashes the exact canonical Sector phase and repair directives", () => {
    const manifest = buildExecutionBehaviorReleaseManifest(releaseInput());
    const energy = manifest.execution_contracts.find(
      (contract) => contract.agent_id === "energy" && contract.language === "zh",
    );
    if (!energy) throw new Error("energy:zh execution contract is missing");

    for (const binding of energy.structured_output_schema_bindings) {
      const bundle = canonicalSectorPhaseDirectiveBundle({
        agentId: "energy",
        phase: binding.phase as "DIRECTION_RESEARCH" | "CONFLICT_REVIEW" | "FINAL_SELECTION",
        language: "zh",
      });
      expect(bundle.repair_directives).toEqual(canonicalStructuredRepairDirectiveManifest());
      expect(binding.immutable_phase_instruction_hash).toBe(textHash(canonicalJson(bundle)));
    }
  });

  it("rejects immutable public contract and provider-contract drift", () => {
    const manifest = buildExecutionBehaviorReleaseManifest(releaseInput());
    const immutableTampered = structuredClone(manifest);
    const immutableContract = immutableTampered.execution_contracts[0];
    if (!immutableContract) throw new Error("expected an execution contract");
    immutableContract.immutable_contract_block_hash = `sha256:${"0".repeat(64)}`;
    expect(() => validateExecutionBehaviorReleaseManifest(immutableTampered)).toThrow(
      /immutable prompt contract drift/,
    );

    const providerTampered = structuredClone(manifest);
    const providerContract = providerTampered.execution_contracts[0];
    if (!providerContract) throw new Error("expected an execution contract");
    providerContract.structured_provider_contract_hash = `sha256:${"0".repeat(64)}`;
    expect(() => validateExecutionBehaviorReleaseManifest(providerTampered)).toThrow(
      /structured provider contract drift/,
    );
  });

  it("generates schema and archive without private Prompt CLI arguments", () => {
    const root = mkdtempSync(join(tmpdir(), "mosaic-behavior-generator-"));
    roots.push(root);
    const schemaOut = join(root, "execution-release.schema.json");
    const archiveRoot = join(root, "archive");
    execFileSync(
      process.execPath,
      [
        resolve(process.cwd(), "node_modules/tsx/dist/cli.mjs"),
        resolve(process.cwd(), "scripts/generate_execution_behavior_release.ts"),
        "--schema-out",
        schemaOut,
        "--archive-root",
        archiveRoot,
        "--provider",
        "fixture-provider",
        "--model",
        "fixture-model",
      ],
      { cwd: process.cwd(), encoding: "utf8" },
    );

    expect(existsSync(schemaOut)).toBe(true);
    const archives = readdirSync(archiveRoot);
    expect(archives).toHaveLength(1);
    expect(
      loadExecutionBehaviorReleaseManifest(join(archiveRoot, archives[0] ?? "")),
    ).toMatchObject({
      provider_binding: { provider: "fixture-provider", model: "fixture-model" },
    });
  });

  it("writes immutable candidates without creating a production pointer", () => {
    const root = mkdtempSync(join(tmpdir(), "mosaic-behavior-archive-"));
    roots.push(root);
    const activeManifestPath = join(root, "active.json");
    const archiveRoot = join(root, "archive");
    const manifest = buildExecutionBehaviorReleaseManifest(releaseInput());

    writeExecutionBehaviorReleaseArtifacts({ manifest, archiveRoot });
    writeExecutionBehaviorReleaseArtifacts({ manifest, archiveRoot });

    expect(existsSync(activeManifestPath)).toBe(false);
    expect(readdirSync(archiveRoot)).toEqual([executionBehaviorReleaseArchiveFilename(manifest)]);
    const archive = join(archiveRoot, executionBehaviorReleaseArchiveFilename(manifest));
    expect(JSON.parse(readFileSync(archive, "utf8"))).toEqual(manifest);

    writeFileSync(archive, "{}\n");
    expect(() => writeExecutionBehaviorReleaseArtifacts({ manifest, archiveRoot })).toThrow(
      /immutable execution behavior release archive collision/,
    );
  });
});

function releaseInput(): BuildExecutionBehaviorReleaseInput {
  return {
    provider: "anthropic",
    model: "claude-sonnet-4",
    baseUrlMode: "PROVIDER_DEFAULT",
  };
}

function committedExecutionReleasePath(): string {
  const root = resolve(process.cwd(), "..");
  const contractRef = JSON.parse(
    readFileSync(
      resolve(root, "registry", "prompt_checks", "prompt_release_contract_ref_v2.json"),
      "utf8",
    ),
  ) as { sources: { execution_behavior_release_archive: { path: string } } };
  return resolve(root, contractRef.sources.execution_behavior_release_archive.path);
}

function textHash(value: string): string {
  return `sha256:${createHash("sha256").update(value).digest("hex")}`;
}
