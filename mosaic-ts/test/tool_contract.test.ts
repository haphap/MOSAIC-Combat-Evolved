import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { RUNTIME_AGENT_SPECS } from "../src/agents/prompts/runtime_agent_spec.js";
import {
  AGENT_EXECUTION_STAGE_IDS,
  AGENT_IDS,
  AGENT_TOOL_IDS,
  AgentSnapshotBundleSchema,
  AgentToolCapabilityManifestSchema,
  buildAgentToolContractManifest,
  validatePreparedCapability,
} from "../src/agents/tool_contract.js";

const hash = `sha256:${"a".repeat(64)}`;

function bundle() {
  return {
    snapshot_bundle_id: "bundle-1",
    snapshot_bundle_hash: hash,
    snapshot_bundle_contract_version: "agent_snapshot_bundle_v1",
    materialization_request_id: "materialize-1",
    agent_id: "china",
    stage: "china",
    as_of: "2026-07-09",
    candidate_scope_hash: null,
    runtime_input_hash: hash,
    tool_payload_hashes: { get_china_macro_snapshot: hash },
    materialized_at: "2026-07-09T00:00:00Z",
  } as const;
}

function capability() {
  return {
    manifest: {
      capability_contract_version: "agent_tool_capability_v1",
      capability_id: "cap-1",
      graph_run_id: "graph-1",
      run_slot_id: "slot-1",
      run_id: "run-1",
      node_id: "node-1",
      agent_id: "china",
      stage: "china",
      allowed_tools: ["get_china_macro_snapshot"],
      as_of: "2026-07-09",
      candidate_scope_hash: null,
      snapshot_bundle_id: "bundle-1",
      snapshot_bundle_hash: hash,
      issued_at: "2026-07-09T00:00:00Z",
      expires_at: "2026-07-09T00:15:00Z",
      nonce: "nonce-1",
    },
    signing_key_id: "test-key",
    signature: `hmac-sha256:${"b".repeat(64)}`,
  } as const;
}

describe("canonical Agent tool contract", () => {
  it("contains exactly 28 agents, 29 stages, and 18 zero-argument tools", () => {
    expect(AGENT_IDS).toHaveLength(28);
    expect(new Set(AGENT_IDS).size).toBe(28);
    expect(AGENT_EXECUTION_STAGE_IDS).toHaveLength(29);
    expect(new Set(AGENT_EXECUTION_STAGE_IDS).size).toBe(29);
    expect(AGENT_TOOL_IDS).toHaveLength(18);
    expect(new Set(AGENT_TOOL_IDS).size).toBe(18);
  });

  it("matches every runtime Agent spec and the committed generated artifact", () => {
    const artifact = buildAgentToolContractManifest();
    const committed = JSON.parse(
      readFileSync(
        join(
          process.cwd(),
          "..",
          "registry",
          "prompt_checks",
          "agent_tool_contract_manifest_v1.json",
        ),
        "utf-8",
      ),
    );
    expect(committed).toEqual(artifact);
    expect(RUNTIME_AGENT_SPECS.map((spec) => [spec.agent, spec.layer, spec.requiredTools])).toEqual(
      artifact.agents.map((row) => [row.agent_id, row.layer, row.allowed_tools]),
    );
  });

  it("validates bundle/capability binding and rejects role or stage expansion", () => {
    expect(validatePreparedCapability(bundle(), capability())).toEqual({
      bundle: bundle(),
      capability: capability(),
    });
    expect(
      AgentSnapshotBundleSchema.safeParse({
        ...bundle(),
        tool_payload_hashes: { get_us_macro_snapshot: hash },
      }).success,
    ).toBe(false);
    expect(
      AgentToolCapabilityManifestSchema.safeParse({
        ...capability().manifest,
        stage: "us_economy",
      }).success,
    ).toBe(false);
    expect(() =>
      validatePreparedCapability(bundle(), {
        ...capability(),
        manifest: { ...capability().manifest, snapshot_bundle_id: "bundle-2" },
      }),
    ).toThrow(/binding mismatch/);
  });
});
