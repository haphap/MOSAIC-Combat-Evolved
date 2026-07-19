import { createHash, randomUUID } from "node:crypto";
import type {
  BridgeApi,
  PreparedAgentToolCapability,
  ToolCapabilityPrepareRequest,
} from "../../bridge/index.js";
import type { DailyCycleStateType } from "../state.js";
import {
  type AgentExecutionStageId,
  AgentIdSchema,
  validatePreparedCapability,
} from "../tool_contract.js";

export type { AgentExecutionStageId } from "../tool_contract.js";

export interface PrepareAgentToolCapabilityArgs {
  api: BridgeApi;
  state: DailyCycleStateType;
  agentId: string;
  stage: AgentExecutionStageId;
  runtimeInputs?: Record<string, unknown>;
  candidateScope?: Record<string, unknown> | null;
}

export function hasAgentToolCapabilityApi(api: BridgeApi | undefined): api is BridgeApi {
  return (
    typeof api?.toolsPrepareCapability === "function" &&
    typeof api.toolsList === "function" &&
    typeof api.toolsCall === "function" &&
    typeof api.toolsTerminateCapability === "function"
  );
}

/**
 * Prepare the immutable tool bundle before any model invocation.  The signed
 * envelope stays in runtime memory and is never rendered into a prompt.
 */
export async function prepareAgentToolCapability(
  args: PrepareAgentToolCapabilityArgs,
): Promise<PreparedAgentToolCapability> {
  const asOf = args.state.as_of_date;
  if (!asOf) throw new Error(`${args.agentId}: capability preparation requires as_of_date`);
  const agentId = AgentIdSchema.parse(args.agentId);
  const graphRunId = args.state.trace_id || stableRunId(args.state);
  const nodeId = `${args.agentId}:${args.stage}`;
  const invocationNonce = randomUUID();
  const request: ToolCapabilityPrepareRequest = {
    graph_run_id: graphRunId,
    run_slot_id: `${graphRunId}:${nodeId}`,
    run_id: graphRunId,
    node_id: nodeId,
    agent_id: agentId,
    stage: args.stage,
    as_of: asOf,
    materialization_request_id: `materialize:${graphRunId}:${nodeId}:${invocationNonce}`,
    runtime_inputs: args.runtimeInputs ?? {},
    candidate_scope: args.candidateScope ?? null,
  };
  const rawPrepared = await args.api.toolsPrepareCapability(request);
  const prepared = validatePreparedCapability(rawPrepared.bundle, rawPrepared.capability);
  if (
    prepared.bundle.agent_id !== agentId ||
    prepared.bundle.stage !== args.stage ||
    prepared.bundle.as_of !== asOf
  ) {
    throw new Error(`${args.agentId}: bridge returned a mismatched tool capability`);
  }
  return prepared;
}

export async function terminateAgentToolCapability(
  api: BridgeApi,
  prepared: PreparedAgentToolCapability,
  reason: string,
): Promise<void> {
  await api.toolsTerminateCapability(prepared.capability, reason);
}

export async function issueAgentToolCapabilityForBundle(args: {
  api: BridgeApi;
  state: DailyCycleStateType;
  agentId: string;
  stage: AgentExecutionStageId;
  nodeId: string;
  root: PreparedAgentToolCapability;
}): Promise<PreparedAgentToolCapability> {
  const agentId = AgentIdSchema.parse(args.agentId);
  const graphRunId = args.state.trace_id || stableRunId(args.state);
  const rawPrepared = await args.api.toolsIssueCapability({
    graph_run_id: graphRunId,
    run_slot_id: `${graphRunId}:${args.nodeId}`,
    run_id: graphRunId,
    node_id: args.nodeId,
    agent_id: agentId,
    stage: args.stage,
    as_of: args.root.bundle.as_of,
    snapshot_bundle_id: args.root.bundle.snapshot_bundle_id,
    snapshot_bundle_hash: args.root.bundle.snapshot_bundle_hash,
  });
  const prepared = validatePreparedCapability(rawPrepared.bundle, rawPrepared.capability);
  if (
    prepared.bundle.snapshot_bundle_id !== args.root.bundle.snapshot_bundle_id ||
    prepared.bundle.snapshot_bundle_hash !== args.root.bundle.snapshot_bundle_hash ||
    prepared.bundle.materialized_at !== args.root.bundle.materialized_at
  ) {
    throw new Error(`${args.agentId}: issued capability did not reuse the root bundle`);
  }
  return prepared;
}

function stableRunId(state: DailyCycleStateType): string {
  const input = `${state.active_cohort}\u0000${state.mode}\u0000${state.as_of_date}`;
  return `daily:${createHash("sha256").update(input).digest("hex").slice(0, 24)}`;
}
