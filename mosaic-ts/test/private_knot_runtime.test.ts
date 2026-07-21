import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { canonicalJsonHash } from "../src/agents/helpers/canonical_json.js";
import {
  applyPrivateKnotPolicy,
  buildAgentInvocationId,
  clearPrivateKnotRuntimeForTests,
  finalizePrivateKnotSnapshot,
  installPrivateKnotRuntime,
  type PrivateKnotRuntimeAdapter,
  preparePrivateKnotModelContext,
  preparePrivateKnotSnapshot,
} from "../src/agents/helpers/private_knot_boundary.js";
import {
  assertPrivateKnotAdapterClosedBundle,
  assertRuntimeBehaviorBundlePrivateClosure,
  type PrivateRuntimeManifest,
  verifyPrivateKnotRuntimeManifestFiles,
} from "../src/autoresearch/private_knot_runtime.js";
import { buildRuntimeBehaviorBundleRef } from "../src/autoresearch/runtime_behavior_bundle.js";

const roots: string[] = [];

afterEach(() => {
  clearPrivateKnotRuntimeForTests();
  for (const root of roots) rmSync(root, { recursive: true, force: true });
  roots.length = 0;
});

describe("private KNOT runtime integrity", () => {
  it("fails closed on out-of-order, repeated, finalized, and leaked model context", async () => {
    installPrivateKnotRuntime(echoAdapter());
    const snapshot = await preparePrivateKnotSnapshot(prepareInput());
    expect(() =>
      applyPrivateKnotPolicy({ snapshot, output: { ok: true }, toolStatuses: [] }),
    ).toThrow(/policy_before_model_context/);

    clearPrivateKnotRuntimeForTests();
    installPrivateKnotRuntime(echoAdapter());
    const repeated = await preparePrivateKnotSnapshot(prepareInput());
    const frozen = initialToolResult(repeated.agent_invocation_id);
    await preparePrivateKnotModelContext({ snapshot: repeated, initialToolResults: [frozen] });
    await expect(
      preparePrivateKnotModelContext({ snapshot: repeated, initialToolResults: [frozen] }),
    ).rejects.toThrow(/already_consumed/);
    finalizePrivateKnotSnapshot(repeated);
    expect(() =>
      applyPrivateKnotPolicy({ snapshot: repeated, output: { ok: true }, toolStatuses: [] }),
    ).toThrow(/not_issued/);

    clearPrivateKnotRuntimeForTests();
    const leaking = echoAdapter();
    leaking.prepareModelContext = async ({ snapshot: current }) => {
      const context = [
        {
          schema_version: "knot_derived_economic_feature_v1" as const,
          public_feature_id: "china.activity.composite_observation",
          observation_period: "2026-07",
          as_of: current.as_of,
          value: "candidate threshold=0.4",
          unit: "index",
          evidence_refs: [hash("leak-source")],
          pit_status: "PIT_VERIFIED" as const,
        },
      ];
      return {
        context,
        context_hash: canonicalJsonHash({
          schema_version: "private_knot_model_context_v1",
          snapshot_hash: current.snapshot_hash,
          context,
        }),
        audit: {
          snapshot_hash: current.snapshot_hash,
          disposition: "APPLIED" as const,
          envelope_hashes: context.map((item) => canonicalJsonHash(item)),
        },
      };
    };
    installPrivateKnotRuntime(leaking);
    const leaked = await preparePrivateKnotSnapshot(prepareInput());
    await expect(
      preparePrivateKnotModelContext({
        snapshot: leaked,
        initialToolResults: [initialToolResult(leaked.agent_invocation_id)],
      }),
    ).rejects.toThrow(/private_content/);
  });

  it("consumes an invocation-bound snapshot once and rejects cached replay", async () => {
    installPrivateKnotRuntime(echoAdapter());
    const snapshot = await preparePrivateKnotSnapshot(prepareInput());
    await preparePrivateKnotModelContext({
      snapshot,
      initialToolResults: [initialToolResult(snapshot.agent_invocation_id)],
    });
    expect(
      applyPrivateKnotPolicy({ snapshot, output: { ok: true }, toolStatuses: [] }).output,
    ).toEqual({ ok: true });
    expect(() =>
      applyPrivateKnotPolicy({ snapshot, output: { ok: true }, toolStatuses: [] }),
    ).toThrow(/private_knot_snapshot_(?:already_consumed|not_issued)/);
  });

  it.each([
    "graph_run_id",
    "as_of",
    "execution_behavior_release_id",
  ] as const)("rejects a cross-binding %s echo before issuance", async (field) => {
    installPrivateKnotRuntime(echoAdapter({ [field]: `wrong-${field}` }));
    await expect(preparePrivateKnotSnapshot(prepareInput())).rejects.toThrow(
      new RegExp(`private_knot_snapshot_${field}_mismatch`),
    );
  });

  it("consumes the issued capability when apply receives a tampered binding", async () => {
    installPrivateKnotRuntime(echoAdapter());
    const snapshot = await preparePrivateKnotSnapshot(prepareInput());
    await preparePrivateKnotModelContext({
      snapshot,
      initialToolResults: [initialToolResult(snapshot.agent_invocation_id)],
    });
    expect(() =>
      applyPrivateKnotPolicy({
        snapshot: { ...snapshot, as_of: "2026-07-10" },
        output: { ok: true },
        toolStatuses: [],
      }),
    ).toThrow(/private_knot_snapshot_binding_mismatch/);
    expect(() =>
      applyPrivateKnotPolicy({ snapshot, output: { ok: true }, toolStatuses: [] }),
    ).toThrow(/private_knot_snapshot_(?:already_consumed|not_issued)/);
  });

  it("verifies every manifest file and rejects a tampered dependency", async () => {
    const root = fixtureRoot();
    const adapter = 'import { createHash } from "node:crypto";\nexport const ok = createHash;\n';
    const dependency = "export const value = 1;\n";
    const manifest = manifestFixture(root, {
      typescript_agent_policy_adapter: ["runtime/typescript/dist/public_adapter.js", adapter],
      knot_contract_typescript: ["runtime/typescript/src/knot_contract.ts", dependency],
    });

    expect(await verifyPrivateKnotRuntimeManifestFiles(root, manifest)).toHaveLength(2);
    writeFileSync(join(root, "runtime/typescript/src/knot_contract.ts"), "tampered\n");
    await expect(verifyPrivateKnotRuntimeManifestFiles(root, manifest)).rejects.toThrow(
      /private_knot_runtime_file_hash_mismatch:knot_contract_typescript/,
    );
  });

  it("rejects manifest symlinks before reading their targets", async () => {
    const root = fixtureRoot();
    const outside = join(root, "outside.js");
    writeFileSync(outside, "export const value = 1;\n");
    const link = join(root, "runtime/typescript/dist/public_adapter.js");
    mkdirSync(dirname(link), { recursive: true });
    symlinkSync(outside, link);
    const manifest: PrivateRuntimeManifest = {
      schema_version: "private_knot_runtime_manifest_v1",
      files: {
        typescript_agent_policy_adapter: {
          relative_path: "runtime/typescript/dist/public_adapter.js",
          sha256: hash("export const value = 1;\n"),
        },
      },
    };

    await expect(verifyPrivateKnotRuntimeManifestFiles(root, manifest)).rejects.toThrow(
      /private_knot_path_symlink/,
    );
  });

  it("requires the public adapter to remain a node-only closed bundle", () => {
    expect(() =>
      assertPrivateKnotAdapterClosedBundle(
        'import { createHash } from "node:crypto";\nexport const value = createHash;\n',
      ),
    ).not.toThrow();
    expect(() =>
      assertPrivateKnotAdapterClosedBundle(
        'import { value } from "./unpinned-dependency.js";\nexport { value };\n',
      ),
    ).toThrow(/external_import/);
    expect(() => assertPrivateKnotAdapterClosedBundle('await import("./late.js");\n')).toThrow(
      /dynamic_import/,
    );
    expect(() => assertPrivateKnotAdapterClosedBundle('require("./late.cjs");\n')).toThrow(
      /dynamic_import/,
    );
  });

  it("binds the installed private runtime, policy, and effect registries to one full bundle", () => {
    const effectHash = hash("effect-registry");
    const consumerHash = hash("consumer-registry");
    const fitnessHash = hash("fitness-registry");
    const bundle = buildRuntimeBehaviorBundleRef({
      schema_version: "runtime_behavior_bundle_ref_v1",
      prompt_hash: hash("prompt"),
      execution_behavior_release_id: `execution-behavior-release:${"1".repeat(64)}`,
      execution_behavior_release_hash: hash("execution"),
      production_variant_roster_revision_id: `production-variant-roster-revision:${"2".repeat(64)}`,
      production_variant_roster_revision_hash: hash("roster"),
      origin: {
        kind: "BASELINE_MIGRATION",
        migration_id: "migration:1",
        migration_evidence_hash: hash("migration"),
      },
      private_runtime_commit: "a".repeat(40),
      private_runtime_manifest_hash: hash("runtime-manifest"),
      private_policy_commit: "a".repeat(40),
      private_policy_hash: hash("policy"),
      effect_registry_hash: effectHash,
      consumer_registry_hash: consumerHash,
      fitness_registry_hash: fitnessHash,
      catalog_hash: hash("catalog"),
      agent_contract_hash: hash("agent-contract"),
      evaluation_contract_hash: hash("evaluation"),
      schema_hash: hash("schema"),
      score_contract_hash: hash("score"),
      scheduler_contract_hash: hash("scheduler"),
      earliest_activation_slot: "2026-07-21T09:00:00+08:00",
    });
    const verifiedFiles = new Map([
      ["knot_effect_registry", Buffer.from(JSON.stringify({ registry_hash: effectHash }))],
      [
        "knot_effect_consumer_registry",
        Buffer.from(JSON.stringify({ registry_hash: consumerHash })),
      ],
      ["knot_effect_fitness_registry", Buffer.from(JSON.stringify({ registry_hash: fitnessHash }))],
    ]);
    const closure = {
      bundle,
      privateRuntimeManifestHash: hash("runtime-manifest"),
      projectionManifestHash: hash("policy"),
      verifiedFiles,
    };
    expect(() => assertRuntimeBehaviorBundlePrivateClosure(closure)).not.toThrow();
    expect(() =>
      assertRuntimeBehaviorBundlePrivateClosure({
        ...closure,
        projectionManifestHash: hash("other-policy"),
      }),
    ).toThrow(/bundle_policy_mismatch/);
    verifiedFiles.set(
      "knot_effect_registry",
      Buffer.from(JSON.stringify({ registry_hash: hash("other-effect") })),
    );
    expect(() => assertRuntimeBehaviorBundlePrivateClosure(closure)).toThrow(
      /bundle_registry_mismatch:knot_effect_registry/,
    );
  });
});

function prepareInput() {
  const promptReleaseHash = hash("prompt-release");
  const binding = {
    invocation_mode: "PRODUCTION" as const,
    graph_run_id: "graph-run-1",
    as_of: "2026-07-09",
    execution_behavior_release_id: "execution-release-1",
    prompt_release_id: "prompt-release-1",
    prompt_release_hash: promptReleaseHash,
    prompt_pair_hash: hash("prompt-pair"),
    prompt_commit: "a".repeat(40),
  };
  return {
    ...binding,
    agent_invocation_id: buildAgentInvocationId({
      runId: binding.graph_run_id,
      agent: "china",
      stage: "agent_run",
      cohort: "cohort_default",
      asOf: binding.as_of,
      promptReleaseHash,
    }),
    agent: "china",
    stage: "agent_run" as const,
    cohort: "cohort_default",
    runtimeSourceStatuses: [],
  };
}

function echoAdapter(
  mutation: Partial<{
    graph_run_id: string;
    as_of: string;
    execution_behavior_release_id: string;
  }> = {},
): PrivateKnotRuntimeAdapter {
  let sequence = 0;
  return {
    describe: () => ({
      knot_runtime_contract_manifest_hash: hash("contract"),
      private_runtime_manifest_hash: hash("runtime"),
    }),
    isStageEnabled: () => true,
    prepareSnapshot: async (input) => {
      sequence += 1;
      const snapshotHash = hash(JSON.stringify({ input, sequence }));
      const { runtimeSourceStatuses, ...binding } = input;
      return {
        snapshot_id: snapshotHash,
        snapshot_hash: snapshotHash,
        ...binding,
        ...mutation,
        evidence_bindings: [],
        allowed_research_rule_ids: [],
        runtime_source_statuses: [...runtimeSourceStatuses],
      };
    },
    prepareModelContext: async ({ snapshot }) => ({
      context: [],
      context_hash: canonicalJsonHash({
        schema_version: "private_knot_model_context_v1",
        snapshot_hash: snapshot.snapshot_hash,
        context: [],
      }),
      audit: {
        snapshot_hash: snapshot.snapshot_hash,
        disposition: "NOT_TRIGGERED",
        envelope_hashes: [],
      },
    }),
    applyPolicy: ({ snapshot, output }) => ({
      output,
      audit: {
        snapshot_hash: snapshot.snapshot_hash,
        accepted: true,
        output_selection: "raw",
        reason_codes: [],
        tool_status_summary: { called: 0, failed: 0, missing: 0, fallback: 0, cache_hit: 0 },
        runtime_source_status_summary: {
          loaded: 0,
          empty_confirmed: 0,
          missing: 0,
          stale: 0,
          source_error: 0,
        },
      },
    }),
    finalize: () => undefined,
  };
}

function initialToolResult(agentInvocationId: string) {
  return {
    tool_name: "get_china_macro_snapshot",
    tool_call_id: "initial_tool_1",
    agent_invocation_id: agentInvocationId,
    args: {},
    payload: { as_of: "2026-07-09" },
    args_fingerprint: hash("args"),
    result_fingerprint: hash("result"),
    source_fingerprint: hash("source"),
    as_of: "2026-07-09",
    status: "CURRENT" as const,
  };
}

function fixtureRoot(): string {
  const root = mkdtempSync(join(tmpdir(), "mosaic-private-knot-runtime-"));
  roots.push(root);
  return root;
}

function manifestFixture(
  root: string,
  files: Record<string, readonly [string, string]>,
): PrivateRuntimeManifest {
  const entries: PrivateRuntimeManifest["files"] = {};
  for (const [logicalName, [relativePath, content]] of Object.entries(files)) {
    const path = join(root, relativePath);
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, content);
    entries[logicalName] = { relative_path: relativePath, sha256: hash(content) };
  }
  return { schema_version: "private_knot_runtime_manifest_v1", files: entries };
}

function hash(value: string): string {
  return `sha256:${createHash("sha256").update(value).digest("hex")}`;
}
