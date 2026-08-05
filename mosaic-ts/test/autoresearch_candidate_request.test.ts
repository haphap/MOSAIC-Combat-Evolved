import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { canonicalJsonHash } from "../src/agents/helpers/canonical_json.js";
import { PromptCandidateSchema } from "../src/autoresearch/prompt_optimizer_contract.js";
import {
  assertPrivateCandidateMatchesRequest,
  buildPrivateCandidateRequest,
  PromptCandidateGenerationRequestSchema,
  runPrivateCandidateCli,
} from "../src/cli/commands/autoresearch.js";

const HASH_A = `sha256:${"a".repeat(64)}`;
const HASH_B = `sha256:${"b".repeat(64)}`;
const COMMIT = "c".repeat(40);
const target = { agentId: "china", stage: "agent_run", cohort: "cohort_default" } as const;

function request() {
  return {
    parentId: "champion-1",
    parentPromptCommit: COMMIT,
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
});
