import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import type { ActivePromptReleaseManifest } from "../src/agents/prompts/prompt_release_contract.js";
import type { RuntimeAgentSpec } from "../src/agents/prompts/runtime_agent_spec.js";
import {
  buildPromptReleaseCanaryAssignmentEvent,
  buildPromptReleaseCanarySloArtifact,
  type PromptReleaseCanaryEvent,
  PromptReleaseCanaryEventJournal,
} from "../src/autoresearch/prompt_release_canary_slo.js";
import {
  activatePromptRelease,
  provisionPromptReleaseBaseline,
  rollbackPromptRelease,
  stagePromptRelease,
  startPromptReleaseCanary,
} from "../src/autoresearch/prompt_release_manager.js";
import { ActivePromptReleaseRegistry } from "../src/autoresearch/release_registry.js";
import type { PromptReleaseCheckResult } from "../src/bridge/types.js";

const HASH = `sha256:${"1".repeat(64)}`;
const PROMPT_PATHS = {
  zh: "prompts/mosaic/cohort_default/macro/central_bank.zh.md",
  en: "prompts/mosaic/cohort_default/macro/central_bank.en.md",
};
const SPEC: RuntimeAgentSpec = {
  agent: "central_bank",
  layer: "macro",
  promptIrAgentId: "macro.central_bank",
  fieldNames: ["signal"],
  requiredTools: [],
  stages: [
    {
      stage: "agent_run",
      enablement: "enabled",
      outputSchemaRef: "macro.central_bank.output.v1",
      outputSchemaFields: ["signal"],
      maxRepairAttempts: 3,
      requiredSourceIds: [],
      producedSourceIds: ["upstream_agent_outputs"],
    },
  ],
};
const roots: string[] = [];

afterEach(() => {
  delete process.env.MOSAIC_PROMPT_RELEASE_AUTHORIZED_OPERATORS;
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});

function initRepo(files: Record<string, string>): { root: string; commit: string } {
  const root = mkdtempSync(join(tmpdir(), "mosaic-release-manager-"));
  roots.push(root);
  execFileSync("git", ["init", "-q", root]);
  for (const [path, content] of Object.entries(files)) {
    const absolute = join(root, path);
    mkdirSync(dirname(absolute), { recursive: true });
    writeFileSync(absolute, content, "utf-8");
  }
  execFileSync("git", ["-C", root, "add", "."]);
  execFileSync("git", [
    "-C",
    root,
    "-c",
    "user.name=Codex Test",
    "-c",
    "user.email=codex@example.invalid",
    "commit",
    "-qm",
    "fixture",
  ]);
  return {
    root,
    commit: execFileSync("git", ["-C", root, "rev-parse", "HEAD"], {
      encoding: "utf-8",
    }).trim(),
  };
}

function versionSha(files: Record<string, string>): string {
  const digest = createHash("sha256");
  for (const path of Object.keys(files).sort()) {
    digest.update(path);
    digest.update("\0");
    digest.update(files[path] ?? "");
    digest.update("\0");
  }
  return digest.digest("hex");
}

function verification(opts: {
  promptCommit: string;
  codeCommit: string;
  promptSha: string;
}): PromptReleaseCheckResult {
  return {
    ready: true,
    checks: { status_ok: true, metadata_ok: true, sha_ok: true, compatible: true },
    details: {},
    pin: {
      version_id: 1,
      cohort: "cohort_default",
      agent: "central_bank",
      prompt_repo_id: "private",
      prompt_commit_hash: opts.promptCommit,
      code_commit_hash: opts.codeCommit,
      prompt_sha256: opts.promptSha,
      mutation_id: "mutation-1",
      experiment_id: "experiment-1",
      keep_decision_hash: HASH,
      evaluation_result_hash: HASH,
      transaction_manifest_hash: HASH,
    },
  };
}

function canaryEvents(
  overrides: Omit<Partial<PromptReleaseCanaryEvent>, "schema_version"> = {},
  startIndex = 0,
  count = 20,
): PromptReleaseCanaryEvent[] {
  return Array.from({ length: count }, (_, offset) => {
    const index = startIndex + offset;
    return {
      schema_version: "prompt_release_canary_event_v2",
      event_id: `sha256:${createHash("sha256").update(`event-${index}`).digest("hex")}`,
      run_id: `run-${index}`,
      agent_invocation_id: `invocation-${index}`,
      release_id: "release-1",
      account_mode: "paper",
      traffic_percent: 10,
      agent: "central_bank",
      stage: "agent_run",
      stage_snapshot_hash: HASH,
      observed_at: "2026-07-10T01:30:00.000Z",
      prompt_source: "private",
      prompt_load_failed: false,
      schema_failed: false,
      fallback: false,
      source_failed: false,
      unsupported_influence_rejected: false,
      validator_rejected: false,
      latency_ms: 100,
      tokenizer_id: "cl100k_base",
      tokenizer_version: "1.0.21",
      context_window_tokens: 131_072,
      system_prompt_tokens: 1_000,
      system_prompt_cap_tokens: 32_768,
      token_budget_breached: false,
      validator_ids: ["macro.central_bank.output.v1"],
      duplicate_order_intent_count: 0,
      exposure_breach_count: 0,
      ...overrides,
    };
  });
}

function canaryRecords(
  overrides: Omit<Partial<PromptReleaseCanaryEvent>, "schema_version"> = {},
  startIndex = 0,
  count = 20,
) {
  return canaryEvents(overrides, startIndex, count).flatMap((event) => {
    const assignment = buildPromptReleaseCanaryAssignmentEvent({
      release: {
        release_id: event.release_id,
        account_mode: event.account_mode,
        traffic_percent: event.traffic_percent,
        stage_snapshot_hash: event.stage_snapshot_hash,
        lifecycle_state: "canary",
      },
      runId: event.run_id,
      agentInvocationId: event.agent_invocation_id,
      agent: event.agent,
      stage: event.stage,
      observedAt: "2026-07-10T01:29:00.000Z",
    });
    if (!assignment) throw new Error("canary assignment missing");
    return [assignment, event];
  });
}

function sloArtifact(overrides: Omit<Partial<PromptReleaseCanaryEvent>, "schema_version"> = {}) {
  const records = canaryRecords(overrides);
  const eventJournalPath = join(
    mkdtempSync(join(tmpdir(), "mosaic-canary-activation-")),
    "events.jsonl",
  );
  roots.push(dirname(eventJournalPath));
  writeFileSync(
    eventJournalPath,
    `${records.map((record) => JSON.stringify(record)).join("\n")}\n`,
  );
  return {
    eventJournalPath,
    artifact: buildPromptReleaseCanarySloArtifact({
      releaseId: "release-1",
      accountMode: "paper",
      trafficPercent: 10,
      canaryStartedAt: "2026-07-10T01:00:00.000Z",
      observationEndedAt: "2026-07-10T02:00:00.000Z",
      stageSnapshotHashes: { "central_bank:agent_run": HASH },
      records,
    }),
  };
}

function approvedBaseline(staged: ActivePromptReleaseManifest): ActivePromptReleaseManifest {
  return {
    ...staged,
    lifecycle_state: "active",
    activation_scope: { ...staged.activation_scope, traffic_percent: 100 },
    approved_by: "operator:test",
    canary_started_at: "2026-07-09T00:00:00.000Z",
    canary_ended_at: "2026-07-09T01:00:00.000Z",
    runtime_slo_summary: {
      passed: true,
      sample_count: 20,
      schema_failure_rate: 0,
      fallback_rate: 0,
      source_failure_rate: 0,
      unsupported_influence_rejection_rate: 0,
      validator_rejection_rate: 0,
      latency_p95_ms: 100,
      token_budget_breach_count: 0,
      duplicate_order_intent_count: 0,
      exposure_breach_count: 0,
    },
    runtime_slo_evidence: {
      schema_version: "prompt_release_canary_slo_evidence_v1",
      release_id: staged.release_id,
      account_mode: staged.activation_scope.account_mode,
      traffic_percent: 10,
      canary_started_at: "2026-07-09T00:00:00.000Z",
      observation_ended_at: "2026-07-09T01:00:00.000Z",
      eligible_event_count: 20,
      excluded_event_count: 0,
      excluded_count_by_reason: {},
      event_set_hash: HASH,
      stage_snapshot_hashes_hash: HASH,
      aggregator_id: "prompt_release_canary_slo",
      aggregator_version: "1",
      artifact_hash: HASH,
    },
    activated_at: "2026-07-09T01:00:00.000Z",
  };
}

describe("prompt release manager", () => {
  it("stages a hash-closed aggregate release and runs audited idempotent lifecycle steps", async () => {
    const promptFiles = { [PROMPT_PATHS.zh]: "private zh\n", [PROMPT_PATHS.en]: "private en\n" };
    const privateRepo = initRepo(promptFiles);
    const closure = {
      catalog_hash: HASH,
      schema_hash: HASH,
      contract_hash: HASH,
    };
    const codeRepo = initRepo({
      [PROMPT_PATHS.zh]: "fallback zh\n",
      [PROMPT_PATHS.en]: "fallback en\n",
      "registry/prompt_checks/private_knot_assets_ref_v1.json": `${JSON.stringify({ evaluation_contract: closure })}\n`,
    });
    const registryRoot = mkdtempSync(join(tmpdir(), "mosaic-release-registry-"));
    roots.push(registryRoot);
    const candidateSources: string[] = [];
    const candidateRuntimePins: Array<{ repo: string; commit: string }> = [];
    const stageOptions = {
      registryRoot,
      releaseId: "release-1",
      verification: verification({
        promptCommit: privateRepo.commit,
        codeCommit: codeRepo.commit,
        promptSha: versionSha(promptFiles),
      }),
      privatePromptRepo: privateRepo.root,
      codeRepo: codeRepo.root,
      cohort: "cohort_default",
      accountMode: "paper" as const,
      approvalPolicyId: "decision_release_manual_v1" as const,
    };
    const deps = {
      specs: [SPEC],
      checkCandidate: async ({
        source,
        privateRuntimeRepo,
        privateRuntimeCommit,
      }: {
        source: string;
        privateRuntimeRepo: string;
        privateRuntimeCommit: string;
      }) => {
        candidateSources.push(source);
        candidateRuntimePins.push({ repo: privateRuntimeRepo, commit: privateRuntimeCommit });
        return { snapshotHashes: { "central_bank:agent_run": HASH } };
      },
      now: () => "2026-07-10T00:00:00.000Z",
    };

    process.env.MOSAIC_PROMPT_RELEASE_AUTHORIZED_OPERATORS = "operator:test";
    const baselineRegistryRoot = mkdtempSync(join(tmpdir(), "mosaic-baseline-source-"));
    roots.push(baselineRegistryRoot);
    const baselineStaged = await stagePromptRelease(
      { ...stageOptions, registryRoot: baselineRegistryRoot, releaseId: "baseline-1" },
      {
        ...deps,
        checkCandidate: async () => ({
          snapshotHashes: { "central_bank:agent_run": HASH },
        }),
      },
    );
    await provisionPromptReleaseBaseline({
      registryRoot,
      manifest: approvedBaseline(baselineStaged),
      privatePromptRepo: privateRepo.root,
      approvedBy: "operator:test",
      reason: "import previously approved deployment baseline",
      codeRepo: codeRepo.root,
      deps: {
        specs: [SPEC],
        checkCandidate: async () => ({
          snapshotHashes: { "central_bank:agent_run": HASH },
        }),
      },
    });

    const staged = await stagePromptRelease(stageOptions, deps);
    await stagePromptRelease(stageOptions, deps);
    expect(staged.prompt_pairs).toHaveLength(1);
    expect(staged.bundled_fallback?.prompt_pairs).toHaveLength(1);
    expect(candidateSources).toEqual(["private", "bundled", "private", "bundled"]);
    expect(candidateRuntimePins).toEqual(
      Array.from({ length: 4 }, () => ({ repo: privateRepo.root, commit: privateRepo.commit })),
    );

    const canaryOptions = {
      registryRoot,
      releaseId: "release-1",
      approvedBy: "operator:test",
      reason: "candidate closure reviewed",
      trafficPercent: 10,
      deps: { now: () => "2026-07-10T01:00:00.000Z" },
    };
    await startPromptReleaseCanary(canaryOptions);
    await startPromptReleaseCanary(canaryOptions);
    const canaryRegistry = new ActivePromptReleaseRegistry(registryRoot);
    expect(await canaryRegistry.canaryPointer()).toMatchObject({
      current_release_id: "release-1",
      traffic_percent: 10,
    });
    const assignments = await Promise.all(
      Array.from({ length: 100 }, (_, index) =>
        canaryRegistry.resolveForRuntime(`assignment-${index}`),
      ),
    );
    expect(assignments.some((manifest) => manifest?.lifecycle_state === "canary")).toBe(true);
    expect(assignments.some((manifest) => manifest?.release_id === "baseline-1")).toBe(true);
    const failingSlo = sloArtifact({ latency_ms: 120_001 });
    await expect(
      activatePromptRelease({
        registryRoot,
        releaseId: "release-1",
        approvedBy: "operator:test",
        reason: "asserted pass with excessive latency",
        sloArtifact: failingSlo.artifact,
        eventJournalPath: failingSlo.eventJournalPath,
        codeRepo: codeRepo.root,
        deps: { now: () => "2026-07-10T02:00:00.000Z" },
      }),
    ).rejects.toThrow("prompt_release_runtime_slo_failed");
    const staleSlo = sloArtifact();
    await new PromptReleaseCanaryEventJournal(staleSlo.eventJournalPath).appendOnce(
      canaryRecords({}, 100, 1),
    );
    await expect(
      activatePromptRelease({
        registryRoot,
        releaseId: "release-1",
        approvedBy: "operator:test",
        reason: "stale journal snapshot must not activate",
        sloArtifact: staleSlo.artifact,
        eventJournalPath: staleSlo.eventJournalPath,
        codeRepo: codeRepo.root,
        deps: { now: () => "2026-07-10T02:00:00.000Z" },
      }),
    ).rejects.toThrow("prompt_release_canary_slo_journal_closure_mismatch");
    const passingSlo = sloArtifact();
    const activationOptions = {
      registryRoot,
      releaseId: "release-1",
      approvedBy: "operator:test",
      reason: "canary SLOs passed",
      sloArtifact: passingSlo.artifact,
      eventJournalPath: passingSlo.eventJournalPath,
      codeRepo: codeRepo.root,
      deps: { now: () => "2026-07-10T02:00:00.000Z" },
    };
    await activatePromptRelease(activationOptions);
    await activatePromptRelease(activationOptions);
    expect((await new ActivePromptReleaseRegistry(registryRoot).resolveActive())?.release_id).toBe(
      "release-1",
    );
    expect((await canaryRegistry.canaryPointer()).current_release_id).toBeNull();
    const rollbackOptions = {
      registryRoot,
      releaseId: "release-1",
      approvedBy: "operator:test",
      reason: "operational rollback drill",
      deps: { now: () => "2026-07-10T03:00:00.000Z" },
    };
    await rollbackPromptRelease(rollbackOptions);
    await rollbackPromptRelease(rollbackOptions);

    const registry = new ActivePromptReleaseRegistry(registryRoot);
    expect((await registry.pointer()).current_release_id).toBe("baseline-1");
    const audit = readFileSync(join(registryRoot, "release-audit.jsonl"), "utf-8")
      .trim()
      .split("\n")
      .map((line) => JSON.parse(line) as { event: string });
    expect(audit.map((row) => row.event)).toEqual([
      "baseline_provisioned",
      "staged",
      "canary",
      "active",
      "rolled_back",
    ]);
  });

  it("fails closed for unlisted operators", async () => {
    process.env.MOSAIC_PROMPT_RELEASE_AUTHORIZED_OPERATORS = "operator:allowed";
    await expect(
      startPromptReleaseCanary({
        registryRoot: "/unused",
        releaseId: "release-1",
        approvedBy: "operator:unlisted",
        reason: "not authorized",
        trafficPercent: 10,
      }),
    ).rejects.toThrow("prompt_release_operator_not_authorized");
  });

  it("rejects duplicate records and incomplete canary invocations", () => {
    const duplicate = canaryRecords();
    const first = duplicate[0];
    const third = duplicate[2];
    if (!first || !third) throw new Error("canary record fixture incomplete");
    duplicate[2] = { ...third, event_id: first.event_id };
    expect(() =>
      buildPromptReleaseCanarySloArtifact({
        releaseId: "release-1",
        accountMode: "paper",
        trafficPercent: 10,
        canaryStartedAt: "2026-07-10T01:00:00.000Z",
        observationEndedAt: "2026-07-10T02:00:00.000Z",
        stageSnapshotHashes: { "central_bank:agent_run": HASH },
        records: duplicate,
      }),
    ).toThrow("prompt_release_canary_slo_duplicate_event");
    expect(() =>
      buildPromptReleaseCanarySloArtifact({
        releaseId: "release-1",
        accountMode: "paper",
        trafficPercent: 10,
        canaryStartedAt: "2026-07-10T01:00:00.000Z",
        observationEndedAt: "2026-07-10T02:00:00.000Z",
        stageSnapshotHashes: { "central_bank:agent_run": HASH },
        records: canaryRecords().slice(1),
      }),
    ).toThrow("prompt_release_canary_slo_incomplete_invocations");
  });
});
