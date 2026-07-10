import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  buildPromptReleaseCanaryEvent,
  buildPromptReleaseCanarySloArtifact,
  PromptReleaseCanaryEventJournal,
  PromptReleaseCanaryEventSchema,
} from "../src/autoresearch/prompt_release_canary_slo.js";

const HASH = `sha256:${"1".repeat(64)}`;
const roots: string[] = [];

afterEach(() => {
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});

function event(index = 0) {
  const value = buildPromptReleaseCanaryEvent({
    release: {
      release_id: "release-1",
      account_mode: "paper",
      traffic_percent: 10,
      stage_snapshot_hash: HASH,
      lifecycle_state: "canary",
    },
    runId: `run-${index}`,
    agentInvocationId: `agent-invocation-${index}`,
    agent: "central_bank",
    stage: "agent_run",
    observedAt: "2026-07-10T01:30:00.000Z",
    latencyMs: 250,
    systemPrompt: "Measured runtime system prompt.",
    schemaFailed: false,
    fallback: false,
    sourceFailed: false,
    unsupportedInfluenceRejected: false,
    validatorRejected: false,
    validatorIds: ["macro.central_bank.output.v1", "evidence_claim_graph_v1"],
  });
  if (!value) throw new Error("canary event missing");
  return value;
}

describe("runtime prompt canary events", () => {
  it("builds measured events and aggregates an event-hash-bound SLO artifact", () => {
    const events = Array.from({ length: 20 }, (_, index) => event(index));

    const artifact = buildPromptReleaseCanarySloArtifact({
      releaseId: "release-1",
      accountMode: "paper",
      trafficPercent: 10,
      canaryStartedAt: "2026-07-10T01:00:00.000Z",
      observationEndedAt: "2026-07-10T02:00:00.000Z",
      stageSnapshotHashes: { "central_bank:agent_run": HASH },
      events,
    });

    expect(events[0]).toMatchObject({
      tokenizer_id: "cl100k_base",
      tokenizer_version: "1.0.21",
      token_budget_breached: false,
      validator_ids: ["evidence_claim_graph_v1", "macro.central_bank.output.v1"],
    });
    expect(artifact.measurements).toMatchObject({ sample_count: 20, latency_p95_ms: 250 });
  });

  it("rejects asserted token results that disagree with measured counts", () => {
    expect(() =>
      PromptReleaseCanaryEventSchema.parse({
        ...event(),
        token_budget_breached: true,
      }),
    ).toThrow(/token budget result/);
  });

  it("persists events idempotently and rejects conflicting retries", async () => {
    const root = mkdtempSync(join(tmpdir(), "mosaic-canary-events-"));
    roots.push(root);
    const path = join(root, "events.jsonl");
    const journal = new PromptReleaseCanaryEventJournal(path);
    const first = event();

    await journal.appendOnce([first]);
    await journal.appendOnce([first]);

    expect(readFileSync(path, "utf-8").trim().split("\n")).toHaveLength(1);
    await expect(journal.appendOnce([{ ...first, fallback: true }])).rejects.toThrow(
      "prompt_release_canary_event_conflict",
    );
  });

  it("does not emit events for an active release", () => {
    expect(
      buildPromptReleaseCanaryEvent({
        release: {
          release_id: "release-1",
          account_mode: "paper",
          traffic_percent: 100,
          stage_snapshot_hash: HASH,
          lifecycle_state: "active",
        },
        runId: "run-1",
        agentInvocationId: "invocation-1",
        agent: "central_bank",
        stage: "agent_run",
        observedAt: "2026-07-10T01:30:00.000Z",
        latencyMs: 1,
        systemPrompt: "prompt",
        schemaFailed: false,
        fallback: false,
        sourceFailed: false,
        unsupportedInfluenceRejected: false,
        validatorRejected: false,
        validatorIds: ["schema"],
      }),
    ).toBeNull();
  });
});
