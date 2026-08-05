import {
  type AcceptedAgentOutputStore,
  acceptedOutputRefKey,
  canonicalAcceptedOutputHash,
} from "../accepted_output.js";
import type { DailyCycleStateType } from "../state.js";
import type { AcceptedCioProposal } from "./accepted.js";

export type DecisionOpportunityAgentId = "alpha_discovery" | "cro" | "autonomous_execution" | "cio";

export interface DecisionStageFrozenObject {
  schema_version: "decision_stage_frozen_object_set_v1";
  agent_id: DecisionOpportunityAgentId;
  object_kind:
    | "ALPHA_NOVEL_CANDIDATE_UNIVERSE"
    | "CRO_CANDIDATE_UNIVERSE"
    | "EXECUTION_ORDER_INTENT_SET"
    | "CIO_FROZEN_PORTFOLIO_CONTEXT";
  frozen_object_set_id: string;
  frozen_object_set_hash: string;
  object_payload: Record<string, unknown>;
  member_refs: Array<Record<string, unknown>>;
}

export interface AlphaCandidateSnapshotAuthority {
  snapshot_id: string;
  snapshot_hash: string;
  candidate_scope_hash: string;
  candidate_universe_id: string;
  candidate_universe_hash: string;
  upstream_accepted_output_refs: Array<Record<string, unknown>>;
  candidate_universe: Array<Record<string, unknown>>;
}

export interface DecisionSnapshotAuthority extends AlphaCandidateSnapshotAuthority {
  candidate_scope: Record<string, unknown>;
  constraints: Record<string, unknown>;
  role_context: Record<string, unknown>;
}

export interface DecisionRuntimeAuthorityBinding {
  source_tool_id:
    | "get_alpha_candidate_snapshot"
    | "get_cro_risk_snapshot"
    | "get_execution_snapshot"
    | "get_cio_decision_snapshot";
  source_snapshot_hash: string;
  candidate_scope_hash: string;
  candidate_universe_hash: string;
  upstream_accepted_output_refs_hash: string;
}

export function buildAlphaStageFrozenObject(
  snapshot: AlphaCandidateSnapshotAuthority,
): DecisionStageFrozenObject {
  const candidates = snapshot.candidate_universe
    .map((row, index) => {
      const candidateRef = requiredText(
        row.candidate_ref,
        `alpha candidate ${index}.candidate_ref`,
      );
      const tsCode = requiredTsCode(row.ts_code, `alpha candidate ${index}.ts_code`);
      return { candidate_ref: candidateRef, ts_code: tsCode };
    })
    .sort((left, right) => left.candidate_ref.localeCompare(right.candidate_ref));
  if (
    new Set(candidates.map((row) => row.candidate_ref)).size !== candidates.length ||
    new Set(candidates.map((row) => row.ts_code)).size !== candidates.length
  ) {
    throw new Error("alpha candidate snapshot contains duplicate refs or tickers");
  }
  const payload = {
    schema_version: "alpha_frozen_novel_candidate_universe_v2",
    snapshot_id: requiredText(snapshot.snapshot_id, "alpha snapshot_id"),
    snapshot_hash: requiredSha256(snapshot.snapshot_hash, "alpha snapshot_hash"),
    candidate_scope_hash: requiredSha256(
      snapshot.candidate_scope_hash,
      "alpha candidate_scope_hash",
    ),
    candidate_universe_id: requiredText(
      snapshot.candidate_universe_id,
      "alpha candidate_universe_id",
    ),
    candidate_universe_hash: requiredSha256(
      snapshot.candidate_universe_hash,
      "alpha candidate_universe_hash",
    ),
    upstream_accepted_output_refs: snapshot.upstream_accepted_output_refs,
    candidates,
  };
  return envelope(
    "alpha_discovery",
    "ALPHA_NOVEL_CANDIDATE_UNIVERSE",
    "alpha-novel-candidate-universe",
    payload,
    candidates,
  );
}

export function buildAuthorityStageFrozenObject(
  agentId: DecisionOpportunityAgentId,
  snapshot: DecisionSnapshotAuthority,
): DecisionStageFrozenObject {
  if (agentId === "alpha_discovery") return buildAlphaStageFrozenObject(snapshot);
  if (agentId === "cro") return buildAuthorityCroStageFrozenObject(snapshot);
  if (agentId === "autonomous_execution") {
    return buildAuthorityExecutionStageFrozenObject(snapshot);
  }
  return buildAuthorityCioStageFrozenObject(snapshot);
}

export function authorityBindingFromFrozenObject(
  frozen: DecisionStageFrozenObject,
): DecisionRuntimeAuthorityBinding {
  const sourceToolId = {
    alpha_discovery: "get_alpha_candidate_snapshot",
    cro: "get_cro_risk_snapshot",
    autonomous_execution: "get_execution_snapshot",
    cio: "get_cio_decision_snapshot",
  } as const;
  const refs = frozen.object_payload.upstream_accepted_output_refs;
  if (!Array.isArray(refs) || refs.some((ref) => !isRecord(ref))) {
    throw new Error(`${frozen.agent_id}: upstream accepted-output authority is invalid`);
  }
  return {
    source_tool_id: sourceToolId[frozen.agent_id],
    source_snapshot_hash: requiredSha256(
      frozen.object_payload.snapshot_hash,
      `${frozen.agent_id}.source_snapshot_hash`,
    ),
    candidate_scope_hash: requiredSha256(
      frozen.object_payload.candidate_scope_hash,
      `${frozen.agent_id}.candidate_scope_hash`,
    ),
    candidate_universe_hash: requiredSha256(
      frozen.object_payload.candidate_universe_hash,
      `${frozen.agent_id}.candidate_universe_hash`,
    ),
    upstream_accepted_output_refs_hash: canonicalAcceptedOutputHash(refs),
  };
}

function buildAuthorityCroStageFrozenObject(
  snapshot: DecisionSnapshotAuthority,
): DecisionStageFrozenObject {
  const authority = authorityPayload(snapshot, "get_cro_risk_snapshot");
  const candidates = candidateRows(snapshot).map((row, index) => ({
    candidate_ref: requiredText(row.candidate_ref, `cro candidate ${index}.candidate_ref`),
    ts_code: requiredTsCode(row.ts_code, `cro candidate ${index}.ts_code`),
    proposed_target_weight: requiredWeight(
      row.proposed_target_weight,
      `cro candidate ${index}.proposed_target_weight`,
    ),
  }));
  assertUnique(candidates, "candidate_ref", "CRO candidate refs");
  assertUnique(candidates, "ts_code", "CRO candidate tickers");
  candidates.sort((left, right) => left.candidate_ref.localeCompare(right.candidate_ref));
  const payload = {
    schema_version: "cro_frozen_candidate_universe_v2",
    ...authority,
    candidates,
  };
  return envelope(
    "cro",
    "CRO_CANDIDATE_UNIVERSE",
    "cro-candidate-universe",
    payload,
    candidates.map((row) => ({
      risk_candidate_id: row.candidate_ref,
      ts_code: row.ts_code,
      proposed_target_weight: row.proposed_target_weight,
    })),
  );
}

function buildAuthorityExecutionStageFrozenObject(
  snapshot: DecisionSnapshotAuthority,
): DecisionStageFrozenObject {
  const authority = authorityPayload(snapshot, "get_execution_snapshot");
  const intents = candidateRows(snapshot)
    .map((row, index) => {
      const requestedDeltaWeight = requiredSignedWeight(
        row.requested_delta_weight,
        `execution candidate ${index}.requested_delta_weight`,
      );
      if (Math.abs(requestedDeltaWeight) <= 1e-9) return null;
      const targetWeight = requiredWeight(
        row.target_weight,
        `execution candidate ${index}.target_weight`,
      );
      const action = requestedDeltaWeight > 0 ? "BUY" : targetWeight <= 1e-9 ? "SELL" : "REDUCE";
      return {
        order_intent_ref: requiredText(
          row.order_intent_ref,
          `execution candidate ${index}.order_intent_ref`,
        ),
        ts_code: requiredTsCode(row.ts_code, `execution candidate ${index}.ts_code`),
        action,
        requested_delta_weight: requestedDeltaWeight,
      };
    })
    .filter((row): row is NonNullable<typeof row> => row !== null);
  assertUnique(intents, "order_intent_ref", "Execution order-intent refs");
  assertUnique(intents, "ts_code", "Execution order-intent tickers");
  intents.sort((left, right) => left.order_intent_ref.localeCompare(right.order_intent_ref));
  const payload = {
    schema_version: "execution_frozen_order_intent_set_v2",
    ...authority,
    intents,
  };
  const hash = canonicalAcceptedOutputHash(payload);
  return {
    schema_version: "decision_stage_frozen_object_set_v1",
    agent_id: "autonomous_execution",
    object_kind: "EXECUTION_ORDER_INTENT_SET",
    frozen_object_set_id: `order-intent-set:${hash.slice("sha256:".length)}`,
    frozen_object_set_hash: hash,
    object_payload: payload,
    member_refs: intents.map((row) => ({
      order_intent_id: row.order_intent_ref,
      ts_code: row.ts_code,
      action: row.action,
      requested_delta_weight: row.requested_delta_weight,
    })),
  };
}

function buildAuthorityCioStageFrozenObject(
  snapshot: DecisionSnapshotAuthority,
): DecisionStageFrozenObject {
  const authority = authorityPayload(snapshot, "get_cio_decision_snapshot");
  const positions = candidateRows(snapshot)
    .map((row, index) => ({
      position_ref: requiredText(
        row.proposal_position_ref,
        `cio candidate ${index}.proposal_position_ref`,
      ),
      ts_code: requiredTsCode(row.ts_code, `cio candidate ${index}.ts_code`),
      baseline_weight: requiredWeight(row.current_weight, `cio candidate ${index}.current_weight`),
      controlled_target_weight: requiredWeight(
        row.proposed_target_weight,
        `cio candidate ${index}.proposed_target_weight`,
      ),
    }))
    .sort((left, right) => left.ts_code.localeCompare(right.ts_code));
  assertUnique(positions, "position_ref", "CIO position refs");
  assertUnique(positions, "ts_code", "CIO position tickers");
  const baselineCashWeight = 1 - positions.reduce((sum, row) => sum + row.baseline_weight, 0);
  if (baselineCashWeight < -1e-9 || baselineCashWeight > 1 + 1e-9) {
    throw new Error("cio: authoritative baseline weights are invalid");
  }
  const portfolioContext = {
    controlled_target_set_id: requiredText(
      snapshot.candidate_universe_id,
      "cio candidate_universe_id",
    ),
    baseline_cash_weight: Math.max(0, baselineCashWeight),
    positions,
  };
  const payload = {
    schema_version: "decision.frozen_portfolio_context.v2",
    ...authority,
    portfolio_context: portfolioContext,
  };
  return envelope("cio", "CIO_FROZEN_PORTFOLIO_CONTEXT", "cio-frozen-portfolio", payload, [
    portfolioContext,
  ]);
}

function authorityPayload(
  snapshot: DecisionSnapshotAuthority,
  sourceToolId: DecisionRuntimeAuthorityBinding["source_tool_id"],
): Record<string, unknown> {
  if (
    !Array.isArray(snapshot.upstream_accepted_output_refs) ||
    snapshot.upstream_accepted_output_refs.some((ref) => !isRecord(ref))
  ) {
    throw new Error(`${sourceToolId}: upstream accepted-output refs are invalid`);
  }
  return {
    source_tool_id: sourceToolId,
    snapshot_id: requiredText(snapshot.snapshot_id, `${sourceToolId}.snapshot_id`),
    snapshot_hash: requiredSha256(snapshot.snapshot_hash, `${sourceToolId}.snapshot_hash`),
    candidate_scope_hash: requiredSha256(
      snapshot.candidate_scope_hash,
      `${sourceToolId}.candidate_scope_hash`,
    ),
    candidate_universe_id: requiredText(
      snapshot.candidate_universe_id,
      `${sourceToolId}.candidate_universe_id`,
    ),
    candidate_universe_hash: requiredSha256(
      snapshot.candidate_universe_hash,
      `${sourceToolId}.candidate_universe_hash`,
    ),
    upstream_accepted_output_refs: snapshot.upstream_accepted_output_refs,
  };
}

function candidateRows(snapshot: DecisionSnapshotAuthority): Array<Record<string, unknown>> {
  if (
    !Array.isArray(snapshot.candidate_universe) ||
    snapshot.candidate_universe.some((row) => !isRecord(row))
  ) {
    throw new Error("decision candidate universe is invalid");
  }
  return snapshot.candidate_universe;
}

export function buildCroStageFrozenObject(
  state: DailyCycleStateType,
  store: AcceptedAgentOutputStore,
): DecisionStageFrozenObject {
  const proposal = acceptedPayload<"CIO_PROPOSAL", AcceptedCioProposal>(
    state,
    store,
    "CIO_PROPOSAL",
    "cio",
  );
  const candidate = state.layer4_outputs.runtime?.candidate_target_state;
  if (!candidate) throw new Error("cro: candidate target is not frozen");
  const candidates = candidate.portfolio_actions
    .map((action) => ({
      candidate_ref: persistentRef("candidate", {
        candidate_target_hash: candidate.candidate_target_hash,
        ts_code: action.ticker,
      }),
      ts_code: action.ticker,
      proposed_target_weight: action.target_weight,
    }))
    .sort((left, right) => left.candidate_ref.localeCompare(right.candidate_ref));
  const payload = {
    proposal_id: proposal.proposal_id,
    proposal_hash: proposal.proposal_hash,
    candidate_target_hash: candidate.candidate_target_hash,
    candidates,
  };
  return envelope(
    "cro",
    "CRO_CANDIDATE_UNIVERSE",
    "cro-candidate-universe",
    payload,
    candidates.map((row) => ({
      risk_candidate_id: row.candidate_ref,
      ts_code: row.ts_code,
      proposed_target_weight: row.proposed_target_weight,
    })),
  );
}

function envelope(
  agentId: "alpha_discovery" | "cro" | "cio",
  objectKind:
    | "ALPHA_NOVEL_CANDIDATE_UNIVERSE"
    | "CRO_CANDIDATE_UNIVERSE"
    | "CIO_FROZEN_PORTFOLIO_CONTEXT",
  namespace: string,
  payload: Record<string, unknown>,
  memberRefs: Array<Record<string, unknown>>,
): DecisionStageFrozenObject {
  const hash = canonicalAcceptedOutputHash(payload);
  return {
    schema_version: "decision_stage_frozen_object_set_v1",
    agent_id: agentId,
    object_kind: objectKind,
    frozen_object_set_id: `${namespace}:${hash.slice("sha256:".length)}`,
    frozen_object_set_hash: hash,
    object_payload: payload,
    member_refs: memberRefs,
  };
}

function requiredText(value: unknown, label: string): string {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${label} is missing`);
  return value.trim();
}

function requiredSha256(value: unknown, label: string): string {
  const text = requiredText(value, label);
  if (!/^sha256:[0-9a-f]{64}$/.test(text)) throw new Error(`${label} is not a sha256 hash`);
  return text;
}

function requiredTsCode(value: unknown, label: string): string {
  const text = requiredText(value, label).toUpperCase();
  if (!/^\d{6}\.(?:SH|SZ|BJ)$/.test(text)) throw new Error(`${label} is not an A-share code`);
  return text;
}

function requiredWeight(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > 1) {
    throw new Error(`${label} must be a finite weight in [0,1]`);
  }
  return value;
}

function requiredSignedWeight(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < -1 || value > 1) {
    throw new Error(`${label} must be a finite weight in [-1,1]`);
  }
  return value;
}

function assertUnique<T extends Record<string, unknown>>(
  rows: readonly T[],
  field: keyof T,
  label: string,
): void {
  const values = rows.map((row) => row[field]);
  if (new Set(values).size !== values.length) throw new Error(`${label} must be unique`);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function acceptedPayload<K extends "CIO_PROPOSAL", T>(
  state: DailyCycleStateType,
  store: AcceptedAgentOutputStore,
  kind: K,
  agentId: "cio",
): T {
  const ref = state.accepted_output_refs[acceptedOutputRefKey(kind, agentId)];
  if (!ref) throw new Error(`${kind}: accepted output reference is unavailable`);
  return store.resolve<K, T>(ref as never).output.payload;
}

function persistentRef(namespace: string, value: unknown): string {
  return `${namespace}:${canonicalAcceptedOutputHash(value).slice("sha256:".length)}`;
}
