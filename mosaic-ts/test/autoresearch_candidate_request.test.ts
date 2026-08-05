import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Command } from "commander";
import { describe, expect, it } from "vitest";
import { canonicalJsonHash } from "../src/agents/helpers/canonical_json.js";
import { PromptCandidateSchema } from "../src/autoresearch/prompt_optimizer_contract.js";
import {
  assertPrivateCandidateMatchesRequest,
  buildPrivateCandidateCliArgs,
  buildPrivateCandidateRequest,
  loadFrozenShadowAdapters,
  PromptCandidateGenerationRequestSchema,
  registerAutoresearch,
  runPrivateCandidateCli,
} from "../src/cli/commands/autoresearch.js";

const HASH_A = `sha256:${"a".repeat(64)}`;
const HASH_B = `sha256:${"b".repeat(64)}`;
const COMMIT = "c".repeat(40);
const target = { agentId: "china", stage: "agent_run", cohort: "cohort_default" } as const;
const EXECUTOR_SOURCE =
  "export const executor = { execute: async () => ({ acceptedOutputRef: 'x', effectiveInputHash: 'x', consumedPromptHashes: {} }) };\n";
const EVALUATOR_SOURCE =
  "export const evaluator = { evaluate: async () => ({ normalizedScore: 0 }) };\n";

function runTestGit(repo: string, args: ReadonlyArray<string>): Promise<string> {
  return new Promise((resolveOutput, reject) => {
    execFile("git", ["-C", repo, ...args], { encoding: "utf8" }, (error, stdout) => {
      if (error) reject(error);
      else resolveOutput(stdout.trim());
    });
  });
}

async function createFrozenAdapterRepo() {
  const root = await mkdtemp(join(tmpdir(), "mosaic-shadow-adapters-"));
  const executorPath = join(root, "executor.mjs");
  const evaluatorPath = join(root, "evaluator.mjs");
  await Promise.all([
    writeFile(executorPath, EXECUTOR_SOURCE),
    writeFile(evaluatorPath, EVALUATOR_SOURCE),
  ]);
  await runTestGit(root, ["init", "--quiet"]);
  await runTestGit(root, ["add", "executor.mjs", "evaluator.mjs"]);
  await runTestGit(root, [
    "-c",
    "user.name=MOSAIC Test",
    "-c",
    "user.email=mosaic-test@example.invalid",
    "-c",
    "commit.gpgSign=false",
    "commit",
    "--quiet",
    "-m",
    "adapter fixture",
  ]);
  const codeCommit = await runTestGit(root, ["rev-parse", "HEAD"]);
  return {
    root,
    executorPath,
    evaluatorPath,
    environment: {
      codeCommit,
      executorAdapterHash: `sha256:${createHash("sha256").update(EXECUTOR_SOURCE).digest("hex")}`,
      evaluatorAdapterHash: `sha256:${createHash("sha256").update(EVALUATOR_SOURCE).digest("hex")}`,
    },
  };
}

function request() {
  return {
    parentId: "champion-1",
    parentPromptCommit: COMMIT,
    promptSourceId: "private-prompts",
    target,
    promptRefs: { zh: "macro/china.zh.md", en: "macro/china.en.md" },
    cutoffAt: "2025-01-31T00:00:00Z",
    excludedSampleIds: ["holdout-1", "validation-1"],
    createdAt: "2025-04-01T00:00:00Z",
  };
}

function candidate(mutatorConfigHash = HASH_A, mutatorCommit = COMMIT) {
  return PromptCandidateSchema.parse({
    schemaVersion: "prompt_candidate_v1",
    candidateId: "candidate-1",
    parentId: "champion-1",
    parentPromptCommit: COMMIT,
    parentPromptHashes: { zh: HASH_A, en: HASH_B },
    target,
    promptRefs: request().promptRefs,
    promptHashes: { zh: HASH_B, en: HASH_A },
    trainingProjectionHash: HASH_B,
    excludedSampleIdsHash: canonicalJsonHash([...request().excludedSampleIds].sort()),
    mutatorConfigHash,
    mutatorCommit,
    mutationCategories: ["CONFLICT_RESOLUTION"],
    mutationSummary: "Behavior focus: CONFLICT_RESOLUTION.",
    hypothesis:
      "Preregistered hypothesis: CONFLICT_RESOLUTION improves the frozen Agent outcome score.",
    behaviorContractHash: HASH_A,
    privateLineageHash: HASH_B,
    privateStateArtifactHash: HASH_A,
    createdAt: request().createdAt,
  });
}

describe("public to private Candidate request", () => {
  it("does not let the public caller author private mutator identity", () => {
    const parsed = PromptCandidateGenerationRequestSchema.parse(request());
    expect(() =>
      PromptCandidateGenerationRequestSchema.parse({
        ...request(),
        mutatorConfigHash: HASH_A,
        mutatorCommit: COMMIT,
      }),
    ).toThrow();

    expect(() => assertPrivateCandidateMatchesRequest(candidate(), parsed)).not.toThrow();
    expect(() =>
      assertPrivateCandidateMatchesRequest(candidate(HASH_B, "d".repeat(40)), parsed),
    ).not.toThrow();
  });

  it("builds the private request without caller-authored mutator identity", () => {
    const projection = { schemaVersion: "prompt_training_projection_v1" };

    expect(buildPrivateCandidateRequest(request(), projection)).toEqual({
      parentId: "champion-1",
      parentPromptCommit: COMMIT,
      target,
      promptRefs: request().promptRefs,
      trainingProjection: projection,
      createdAt: "2025-04-01T00:00:00Z",
    });
  });

  it("does not expose private CLI stderr through the public error", async () => {
    const root = await mkdtemp(join(tmpdir(), "mosaic-private-cli-error-"));
    const privateCli = join(root, "fail.mjs");
    try {
      await writeFile(
        privateCli,
        'process.stderr.write("provider-secret-token"); process.exitCode = 1;\n',
      );
      const error = await runPrivateCandidateCli(privateCli, []).catch((value: unknown) => value);
      expect(error).toBeInstanceOf(Error);
      expect((error as Error).message).toBe("private Prompt candidate execution failed");
      expect((error as Error).message).not.toContain("provider-secret-token");
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("requires a publication remote and forwards it only to the private CLI", () => {
    const program = new Command().exitOverride();
    registerAutoresearch(program);
    const generate = program.commands
      .find((command) => command.name() === "autoresearch")
      ?.commands.find((command) => command.name() === "generate-candidate");
    const remoteOption = generate?.options.find((option) => option.long === "--publication-remote");
    expect(remoteOption?.mandatory).toBe(true);
    expect(
      buildPrivateCandidateCliArgs({
        requestPath: "/tmp/request.json",
        mutationAdapter: "/private/adapter.mjs",
        privateRepo: "/private/repo",
        publicationRemote: "origin",
      }),
    ).toEqual([
      "--request",
      "/tmp/request.json",
      "--adapter",
      "/private/adapter.mjs",
      "--repo",
      "/private/repo",
      "--publication-remote",
      "origin",
    ]);
    expect(request()).not.toHaveProperty("publicationRemote");
  });

  it("loads frozen executor and evaluator adapters from separate modules", async () => {
    const fixture = await createFrozenAdapterRepo();
    try {
      const adapters = await loadFrozenShadowAdapters({
        publicRepo: fixture.root,
        executorAdapter: fixture.executorPath,
        evaluatorAdapter: fixture.evaluatorPath,
        environment: fixture.environment,
      });
      expect(adapters.executor.execute).toBeTypeOf("function");
      expect(adapters.evaluator.evaluate).toBeTypeOf("function");
      await expect(
        loadFrozenShadowAdapters({
          publicRepo: fixture.root,
          executorAdapter: fixture.executorPath,
          evaluatorAdapter: fixture.executorPath,
          environment: fixture.environment,
        }),
      ).rejects.toThrow(/must be separate modules/);
      await expect(
        loadFrozenShadowAdapters({
          publicRepo: fixture.root,
          executorAdapter: fixture.executorPath,
          evaluatorAdapter: fixture.evaluatorPath,
          environment: { ...fixture.environment, evaluatorAdapterHash: HASH_A },
        }),
      ).rejects.toThrow(/evaluator adapter content hash/);
    } finally {
      await rm(fixture.root, { recursive: true, force: true });
    }
  });

  it("rejects a public checkout whose HEAD differs from the frozen commit", async () => {
    const fixture = await createFrozenAdapterRepo();
    try {
      await expect(
        loadFrozenShadowAdapters({
          publicRepo: fixture.root,
          executorAdapter: fixture.executorPath,
          evaluatorAdapter: fixture.evaluatorPath,
          environment: { ...fixture.environment, codeCommit: "d".repeat(40) },
        }),
      ).rejects.toThrow(/does not match the frozen code commit/);
    } finally {
      await rm(fixture.root, { recursive: true, force: true });
    }
  });

  it("rejects a public checkout with dirty tracked files", async () => {
    const fixture = await createFrozenAdapterRepo();
    try {
      await writeFile(fixture.executorPath, `${EXECUTOR_SOURCE}// dirty\n`);
      await expect(
        loadFrozenShadowAdapters({
          publicRepo: fixture.root,
          executorAdapter: fixture.executorPath,
          evaluatorAdapter: fixture.evaluatorPath,
          environment: fixture.environment,
        }),
      ).rejects.toThrow(/must be clean/);
    } finally {
      await rm(fixture.root, { recursive: true, force: true });
    }
  });

  it("rejects a public checkout with untracked files", async () => {
    const fixture = await createFrozenAdapterRepo();
    try {
      await writeFile(join(fixture.root, "untracked.txt"), "untracked\n");
      await expect(
        loadFrozenShadowAdapters({
          publicRepo: fixture.root,
          executorAdapter: fixture.executorPath,
          evaluatorAdapter: fixture.evaluatorPath,
          environment: fixture.environment,
        }),
      ).rejects.toThrow(/must be clean/);
    } finally {
      await rm(fixture.root, { recursive: true, force: true });
    }
  });

  it("rejects an adapter entry outside the frozen public checkout", async () => {
    const fixture = await createFrozenAdapterRepo();
    const outsideRoot = await mkdtemp(join(tmpdir(), "mosaic-shadow-outside-adapter-"));
    const outsideExecutor = join(outsideRoot, "executor.mjs");
    try {
      await writeFile(outsideExecutor, EXECUTOR_SOURCE);
      await expect(
        loadFrozenShadowAdapters({
          publicRepo: fixture.root,
          executorAdapter: outsideExecutor,
          evaluatorAdapter: fixture.evaluatorPath,
          environment: fixture.environment,
        }),
      ).rejects.toThrow(/must be inside the frozen public checkout/);
    } finally {
      await Promise.all([
        rm(fixture.root, { recursive: true, force: true }),
        rm(outsideRoot, { recursive: true, force: true }),
      ]);
    }
  });

  it("requires separate executor and evaluator adapter options", () => {
    const program = new Command().exitOverride();
    registerAutoresearch(program);
    const shadow = program.commands
      .find((command) => command.name() === "autoresearch")
      ?.commands.find((command) => command.name() === "shadow-run");
    expect(shadow?.options.find((option) => option.long === "--executor-adapter")?.mandatory).toBe(
      true,
    );
    expect(shadow?.options.find((option) => option.long === "--evaluator-adapter")?.mandatory).toBe(
      true,
    );
    expect(shadow?.options.some((option) => option.long === "--adapter")).toBe(false);
  });
});
