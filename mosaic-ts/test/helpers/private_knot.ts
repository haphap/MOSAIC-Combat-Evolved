import { createHash } from "node:crypto";
import { canonicalJsonHash } from "../../src/agents/helpers/canonical_json.js";
import {
  installPrivateKnotRuntime,
  type PrivateKnotRuntimeAdapter,
} from "../../src/agents/helpers/private_knot_boundary.js";

export function installTestPrivateKnotRuntime(): void {
  const snapshots = new Set<string>();
  let sequence = 0;
  const adapter: PrivateKnotRuntimeAdapter = {
    describe: () => ({
      knot_runtime_contract_manifest_hash: `sha256:${"1".repeat(64)}`,
      private_runtime_manifest_hash: `sha256:${"2".repeat(64)}`,
    }),
    isStageEnabled: () => true,
    prepareSnapshot: async (input) => {
      sequence += 1;
      const digest = createHash("sha256").update(JSON.stringify({ input, sequence })).digest("hex");
      const snapshotId = `sha256:${digest}`;
      snapshots.add(snapshotId);
      const { runtimeSourceStatuses, ...binding } = input;
      return {
        snapshot_id: snapshotId,
        snapshot_hash: `sha256:${digest}`,
        ...binding,
        agent: input.agent,
        stage: input.stage,
        cohort: input.cohort,
        evidence_bindings: [],
        allowed_research_rule_ids: [],
        runtime_source_statuses: [...input.runtimeSourceStatuses],
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
    applyPolicy: (input) => {
      if (!snapshots.has(input.snapshot.snapshot_id)) {
        throw new Error("test_private_knot_snapshot_missing");
      }
      return {
        output: input.output,
        audit: {
          snapshot_hash: input.snapshot.snapshot_hash,
          accepted: true,
          output_selection: "raw",
          reason_codes: [],
          tool_status_summary: {
            called: input.toolStatuses.filter((status) => status.called).length,
            failed: input.toolStatuses.filter((status) => status.failed).length,
            missing: input.toolStatuses.filter((status) => status.missing).length,
            fallback: input.toolStatuses.filter((status) => status.fallback).length,
            cache_hit: input.toolStatuses.filter((status) => status.cache_hit).length,
          },
          runtime_source_status_summary: {
            loaded: 0,
            empty_confirmed: 0,
            missing: 0,
            stale: 0,
            source_error: 0,
          },
        },
      };
    },
    finalize: (snapshot) => {
      snapshots.delete(snapshot.snapshot_id);
    },
  };
  installPrivateKnotRuntime(adapter);
}
