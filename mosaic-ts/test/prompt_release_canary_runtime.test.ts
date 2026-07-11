import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { buildAgentPromptCanaryEvent } from "../src/agents/helpers/prompt_canary.js";
import {
  buildPromptReleaseCanaryAssignmentEvent,
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
      source: "private",
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

function records(count = 20) {
  return Array.from({ length: count }, (_, index) => {
    const terminal = event(index);
    const assignment = buildPromptReleaseCanaryAssignmentEvent({
      release: {
        release_id: terminal.release_id,
        account_mode: terminal.account_mode,
        traffic_percent: terminal.traffic_percent,
        stage_snapshot_hash: terminal.stage_snapshot_hash,
        lifecycle_state: "canary",
      },
      runId: terminal.run_id,
      agentInvocationId: terminal.agent_invocation_id,
      agent: terminal.agent,
      stage: terminal.stage,
      observedAt: "2026-07-10T01:29:00.000Z",
    });
    if (!assignment) throw new Error("canary assignment missing");
    return [assignment, terminal];
  }).flat();
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
      records: records(),
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

  it("counts a bundled prompt as both fallback and primary-source failure", () => {
    const terminal = buildAgentPromptCanaryEvent({
      context: {
        release: {
          release_id: "release-1",
          account_mode: "paper",
          traffic_percent: 10,
          stage_snapshot_hash: HASH,
          lifecycle_state: "canary",
          source: "bundled_fallback",
        },
        runId: "run-bundled",
        agentInvocationId: "invocation-bundled",
        systemPrompt: "bundled prompt",
      },
      agent: "central_bank",
      stage: "agent_run",
      startedAt: Date.now(),
      structuredAccepted: true,
      claimGraphAccepted: true,
      knobSnapshot: null,
      knobAudit: null,
      toolStatuses: [],
      output: {},
      validatorIds: ["schema"],
    });

    expect(terminal).toMatchObject({
      prompt_source: "bundled_fallback",
      fallback: true,
      source_failed: true,
    });
  });

  it("records prompt-load failures with zero measured prompt tokens", () => {
    const failed = buildPromptReleaseCanaryEvent({
      release: {
        release_id: "release-1",
        account_mode: "paper",
        traffic_percent: 10,
        stage_snapshot_hash: HASH,
        lifecycle_state: "canary",
        source: "unavailable",
      },
      runId: "run-failed",
      agentInvocationId: "invocation-failed",
      agent: "central_bank",
      stage: "agent_run",
      observedAt: "2026-07-10T01:30:00.000Z",
      latencyMs: 1,
      systemPrompt: "",
      schemaFailed: true,
      fallback: true,
      sourceFailed: true,
      unsupportedInfluenceRejected: false,
      validatorRejected: true,
      validatorIds: ["schema"],
      promptLoadFailed: true,
    });

    expect(failed).toMatchObject({
      prompt_load_failed: true,
      prompt_source: "unavailable",
      system_prompt_tokens: 0,
    });
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
          source: "private",
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
