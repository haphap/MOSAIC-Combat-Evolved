import { beforeEach, describe, expect, it, vi } from "vitest";
import { runAutoresearchCycle } from "../src/autoresearch/orchestrator.js";
import type { BridgeApi } from "../src/bridge/types.js";

// Mock the mutator module
vi.mock("../src/autoresearch/mutator.js", () => ({
  mutate: vi.fn(),
}));

import { mutate } from "../src/autoresearch/mutator.js";

const mockedMutate = vi.mocked(mutate);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fakeBridgeApi(overrides: Partial<Record<string, unknown>> = {}): BridgeApi {
  return {
    autoresearchTrigger: vi.fn().mockResolvedValue({
      version_id: 1,
      agent: "volatility",
      branch_name: "autoresearch/volatility/20260101",
      base_commit: "abc123",
    }),
    promptsWrite: vi.fn().mockResolvedValue({
      commit_hash: "def456",
      branch: "autoresearch/volatility/20260101",
      paths: ["prompts/mosaic/cohort_default/macro/volatility.zh.md"],
    }),
    autoresearchRecordMutation: vi.fn().mockResolvedValue({ ok: true }),
    autoresearchPrepareWorktree: vi.fn().mockResolvedValue({ path: "/tmp/wt" }),
    autoresearchEvaluatePending: vi.fn().mockResolvedValue({ results: [] }),
    autoresearchCleanupWorktree: vi.fn().mockResolvedValue({ ok: true }),
    ...overrides,
  } as unknown as BridgeApi;
}

class FakeLlm {
  async invoke() {
    return { content: "fake" };
  }
  withStructuredOutput() {
    return { invoke: async () => ({}) };
  }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("runAutoresearchCycle", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedMutate.mockResolvedValue({
      zh_prompt: "rewritten zh",
      en_prompt: "rewritten en",
      modification_summary: "tighten thresholds",
      rationale: "low sharpe",
    });
  });

  it("dry-run generates mutation but does not commit", async () => {
    const api = fakeBridgeApi();
    const llm = new FakeLlm();

    const result = await runAutoresearchCycle({
      cohort: "cohort_default",
      dryRun: true,
      maxMutations: 1,
      deps: { llm: llm as never, api },
    });

    expect(result.mutations).toHaveLength(1);
    expect(result.mutations[0]?.status).toBe("dry_run");
    expect(result.mutations[0]?.summary).toBe("tighten thresholds");

    // promptsWrite should NOT be called in dry-run mode
    expect(api.promptsWrite).not.toHaveBeenCalled();
    expect(api.autoresearchRecordMutation).not.toHaveBeenCalled();
    // trigger must be told it's a dry run so it skips branch/DB persistence
    expect(api.autoresearchTrigger).toHaveBeenCalledWith({
      cohort: "cohort_default",
      dry_run: true,
    });
  });

  it("fakeLlm is threaded through to the mutator", async () => {
    const api = fakeBridgeApi();
    const llm = new FakeLlm();

    await runAutoresearchCycle({
      cohort: "cohort_default",
      dryRun: true,
      fakeLlm: true,
      maxMutations: 1,
      deps: { llm: llm as never, api },
    });

    expect(mockedMutate).toHaveBeenCalledWith({
      cohort: "cohort_default",
      agent: "volatility",
      deps: { llm: llm as never, api },
      fakeLlm: true,
    });
  });

  it("full cycle triggers, mutates, writes, and records", async () => {
    const api = fakeBridgeApi();
    const llm = new FakeLlm();

    const result = await runAutoresearchCycle({
      cohort: "cohort_default",
      dryRun: false,
      maxMutations: 1,
      deps: { llm: llm as never, api },
    });

    expect(result.mutations).toHaveLength(1);
    expect(result.mutations[0]?.agent).toBe("volatility");
    expect(result.mutations[0]?.version_id).toBe(1);

    // Full cycle calls: trigger -> mutate -> write -> record -> worktree -> eval -> cleanup
    expect(api.autoresearchTrigger).toHaveBeenCalledWith({ cohort: "cohort_default" });
    expect(mockedMutate).toHaveBeenCalledWith({
      cohort: "cohort_default",
      agent: "volatility",
      deps: { llm: llm as never, api },
    });
    expect(api.promptsWrite).toHaveBeenCalledWith({
      agent: "volatility",
      cohort: "cohort_default",
      contents: { zh: "rewritten zh", en: "rewritten en" },
      branch: "autoresearch/volatility/20260101",
      message: "autoresearch: tighten thresholds",
    });
    expect(api.autoresearchRecordMutation).toHaveBeenCalledWith({
      version_id: 1,
      commit_hash: "def456",
      summary: "tighten thresholds",
    });
    expect(api.autoresearchPrepareWorktree).toHaveBeenCalled();
    expect(api.autoresearchCleanupWorktree).toHaveBeenCalled();
  });

  it("constraint rejection (trigger throws) stops the loop", async () => {
    const api = fakeBridgeApi({
      autoresearchTrigger: vi.fn().mockRejectedValue(new Error("cooldown active")),
    });
    const llm = new FakeLlm();

    const result = await runAutoresearchCycle({
      cohort: "cohort_default",
      maxMutations: 3,
      deps: { llm: llm as never, api },
    });

    // Loop should break immediately; no mutations produced
    expect(result.mutations).toHaveLength(0);
    expect(mockedMutate).not.toHaveBeenCalled();
  });

  it("multiple mutations: loops N times when maxMutations=N", async () => {
    let callCount = 0;
    const api = fakeBridgeApi({
      autoresearchTrigger: vi.fn().mockImplementation(async () => {
        callCount++;
        return {
          version_id: callCount,
          agent: callCount === 1 ? "volatility" : "sentiment",
          branch_name: `autoresearch/agent${callCount}/20260101`,
          base_commit: `commit${callCount}`,
        };
      }),
    });
    const llm = new FakeLlm();

    const result = await runAutoresearchCycle({
      cohort: "cohort_default",
      maxMutations: 2,
      deps: { llm: llm as never, api },
    });

    expect(result.mutations).toHaveLength(2);
    expect(result.mutations[0]?.version_id).toBe(1);
    expect(result.mutations[0]?.agent).toBe("volatility");
    expect(result.mutations[1]?.version_id).toBe(2);
    expect(result.mutations[1]?.agent).toBe("sentiment");
    expect(api.autoresearchTrigger).toHaveBeenCalledTimes(2);
    expect(mockedMutate).toHaveBeenCalledTimes(2);
  });

  it("records error status when mutate throws", async () => {
    const api = fakeBridgeApi();
    const llm = new FakeLlm();
    mockedMutate.mockRejectedValueOnce(new Error("invariant violated"));

    const result = await runAutoresearchCycle({
      cohort: "cohort_default",
      maxMutations: 1,
      deps: { llm: llm as never, api },
    });

    expect(result.mutations).toHaveLength(1);
    expect(result.mutations[0]?.status).toBe("error");
    expect(result.mutations[0]?.error).toContain("invariant violated");
    expect(api.promptsWrite).not.toHaveBeenCalled();
  });

  it("passes forceAgent to trigger", async () => {
    const api = fakeBridgeApi();
    const llm = new FakeLlm();

    await runAutoresearchCycle({
      cohort: "cohort_default",
      forceAgent: "sentiment",
      maxMutations: 1,
      deps: { llm: llm as never, api },
    });

    expect(api.autoresearchTrigger).toHaveBeenCalledWith({
      cohort: "cohort_default",
      force_agent: "sentiment",
    });
  });

  it("records kept status when evaluation succeeds", async () => {
    const api = fakeBridgeApi({
      autoresearchEvaluatePending: vi.fn().mockResolvedValue({
        results: [{ version_id: 1, status: "kept", delta_sharpe: 0.15 }],
      }),
    });
    const llm = new FakeLlm();

    const result = await runAutoresearchCycle({
      cohort: "cohort_default",
      maxMutations: 1,
      deps: { llm: llm as never, api },
    });

    expect(result.mutations[0]?.status).toBe("kept");
    expect(result.mutations[0]?.delta_sharpe).toBe(0.15);
    // §11.6 O(N²) fix: evaluation is scoped to the version just triggered.
    expect(api.autoresearchEvaluatePending).toHaveBeenCalledWith({
      cohort: "cohort_default",
      version_id: 1,
    });
  });
});
