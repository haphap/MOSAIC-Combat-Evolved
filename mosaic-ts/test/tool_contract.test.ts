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
  it("contains exactly 28 agents, 29 stages, and the 32-tool active surface", () => {
    expect(AGENT_IDS).toHaveLength(28);
    expect(new Set(AGENT_IDS).size).toBe(28);
    expect(AGENT_EXECUTION_STAGE_IDS).toHaveLength(29);
    expect(new Set(AGENT_EXECUTION_STAGE_IDS).size).toBe(29);
    expect(AGENT_TOOL_IDS).toHaveLength(32);
    expect(new Set(AGENT_TOOL_IDS).size).toBe(32);
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

  it("is the exact frozen preactivation surface plus the staged L1-L4 bindings", () => {
    const preservationRoot = join(
      process.cwd(),
      "..",
      "registry",
      "prompt_checks",
      "capability_preservation",
    );
    const base = JSON.parse(
      readFileSync(join(preservationRoot, "current_agent_tool_contract_snapshot_v1.json"), "utf-8"),
    ) as {
      agents: Array<{
        agent_id: string;
        execution_stages: string[];
        allowed_tools: string[];
      }>;
    };
    const sectorOverlay = JSON.parse(
      readFileSync(
        join(preservationRoot, "sector_relationship_preservation_overlay_v1.json"),
        "utf-8",
      ),
    ) as {
      activation_state: string;
      bindings: Array<{ agent_id: string; stage: string; tool_id: string }>;
    };
    const l3L4Overlay = JSON.parse(
      readFileSync(join(preservationRoot, "l3_l4_preservation_overlay_v1.json"), "utf-8"),
    ) as {
      activation_state: string;
      bindings: Array<{ agent_id: string; stage: string; tool_id: string }>;
    };
    const active = buildAgentToolContractManifest();
    const surface = (manifest: typeof base) =>
      new Set(
        manifest.agents.flatMap((agent) =>
          agent.execution_stages.flatMap((stage) =>
            agent.allowed_tools.map((toolId) => `${agent.agent_id}\0${stage}\0${toolId}`),
          ),
        ),
      );
    const activeSurface = surface(active);
    const baseSurface = surface(base);
    const added = new Set([...activeSurface].filter((row) => !baseSurface.has(row)));
    const activeStage = (binding: { agent_id: string; stage: string }) => {
      if (binding.agent_id === "cro" && binding.stage === "cro_review") return "cro";
      if (
        binding.agent_id === "autonomous_execution" &&
        binding.stage === "execution_feasibility"
      ) {
        return "autonomous_execution";
      }
      return binding.stage;
    };
    const expectedAdded = new Set(
      [...sectorOverlay.bindings, ...l3L4Overlay.bindings].map(
        (binding) => `${binding.agent_id}\0${activeStage(binding)}\0${binding.tool_id}`,
      ),
    );

    expect(sectorOverlay.activation_state).toBe("staged");
    expect(l3L4Overlay.activation_state).toBe("staged");
    expect(added).toEqual(expectedAdded);
    expect([...baseSurface].every((row) => activeSurface.has(row))).toBe(true);
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
