import { randomUUID } from "node:crypto";
import {
  closeSync,
  existsSync,
  fsyncSync,
  mkdirSync,
  openSync,
  readFileSync,
  renameSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { dirname, resolve } from "node:path";
import type {
  AcceptedAgentOutputStore,
  AcceptedAgentOutputStoreSnapshot,
} from "../agents/accepted_output.js";
import { canonicalJsonHash } from "../agents/helpers/canonical_json.js";
import type { DailyCycleStateType, DailyCycleStateUpdate } from "../agents/state.js";

export const DAILY_CYCLE_CHECKPOINT_SCHEMA_VERSION =
  "daily_cycle_agent_stage_checkpoint_v2" as const;

export interface DailyCycleCheckpointIdentity {
  cycle_kind: string;
  as_of_date: string;
  cohort: string;
  stage_roster: readonly string[];
  graph_contract: string;
  prompt_release: string;
  prompt_content_hash: string;
  prompt_contract: string;
  fixture_bundle_hash: string | null;
  current_positions_hash: string;
}

interface DailyCycleCheckpointStage {
  stage_id: string;
  state: unknown;
  state_hash: string;
  accepted_output_store: AcceptedAgentOutputStoreSnapshot;
  accepted_output_store_hash: string;
}

interface DailyCycleCheckpointDocument {
  schema_version: typeof DAILY_CYCLE_CHECKPOINT_SCHEMA_VERSION;
  identity: DailyCycleCheckpointIdentity;
  identity_hash: string;
  completed_stages: string[];
  latest: DailyCycleCheckpointStage;
}

export interface DailyCycleStageCheckpointController {
  shouldSkip(stageId: string): boolean;
  commit(stageId: string, state: DailyCycleStateType, store: AcceptedAgentOutputStore): void;
}

export type DailyCycleStageNode = (
  state: DailyCycleStateType,
) => Promise<DailyCycleStateUpdate> | DailyCycleStateUpdate;

export function checkpointedStageNode(
  stageId: string,
  node: DailyCycleStageNode,
  checkpoint: DailyCycleStageCheckpointController | undefined,
): DailyCycleStageNode {
  return async (state) => {
    if (checkpoint?.shouldSkip(stageId)) return {};
    return node(state);
  };
}

export const DAILY_CYCLE_COMMIT_BARRIER_BY_STAGE = {
  institutional_flow: "macro_input_gate_node",
  cio_final: "shared_validation",
} as const;

/** Map a completed graph node to the Agent stage it is allowed to commit. */
export function checkpointCommitStageForNode(nodeId: string): string | null {
  if (nodeId === "institutional_flow" || nodeId === "cio_final") return null;
  for (const [stageId, barrierNodeId] of Object.entries(DAILY_CYCLE_COMMIT_BARRIER_BY_STAGE)) {
    if (barrierNodeId === nodeId) return stageId;
  }
  return nodeId;
}

export class DailyCycleCheckpoint implements DailyCycleStageCheckpointController {
  readonly path: string;
  readonly identity: DailyCycleCheckpointIdentity;
  private document: DailyCycleCheckpointDocument | null;

  private constructor(
    path: string,
    identity: DailyCycleCheckpointIdentity,
    document: DailyCycleCheckpointDocument | null,
  ) {
    this.path = resolve(path);
    this.identity = identity;
    this.document = document;
  }

  static open(input: {
    path?: string;
    resume?: boolean;
    identity: DailyCycleCheckpointIdentity;
  }): DailyCycleCheckpoint | undefined {
    if (!input.path) {
      if (input.resume) throw new Error("--resume requires --checkpoint");
      return undefined;
    }
    const path = resolve(input.path);
    if (existsSync(path)) {
      if (!input.resume) {
        throw new Error(`checkpoint already exists; use --resume: ${path}`);
      }
      return new DailyCycleCheckpoint(path, input.identity, loadCheckpoint(path, input.identity));
    }
    if (input.resume) throw new Error(`checkpoint is missing: ${path}`);
    return new DailyCycleCheckpoint(path, input.identity, null);
  }

  get completedStages(): readonly string[] {
    return this.document?.completed_stages ?? [];
  }

  get restoredState(): DailyCycleStateType | null {
    return (this.document?.latest.state as DailyCycleStateType | undefined) ?? null;
  }

  restoreAcceptedOutputStore(store: AcceptedAgentOutputStore): void {
    if (this.document) store.restore(this.document.latest.accepted_output_store);
  }

  shouldSkip(stageId: string): boolean {
    return this.completedStages.includes(stageId);
  }

  commit(stageId: string, state: DailyCycleStateType, store: AcceptedAgentOutputStore): void {
    if (!this.identity.stage_roster.includes(stageId)) return;
    if (this.shouldSkip(stageId)) return;
    const expectedStage = this.identity.stage_roster[this.completedStages.length];
    if (stageId !== expectedStage) {
      throw new Error(
        `checkpoint stage order mismatch: expected ${expectedStage ?? "END"}, got ${stageId}`,
      );
    }
    const safeState = JSON.parse(JSON.stringify(state)) as unknown;
    const acceptedOutputStore = store.snapshot();
    const latest: DailyCycleCheckpointStage = {
      stage_id: stageId,
      state: safeState,
      state_hash: canonicalJsonHash(safeState),
      accepted_output_store: acceptedOutputStore,
      accepted_output_store_hash: canonicalJsonHash(acceptedOutputStore),
    };
    const document: DailyCycleCheckpointDocument = {
      schema_version: DAILY_CYCLE_CHECKPOINT_SCHEMA_VERSION,
      identity: this.identity,
      identity_hash: canonicalJsonHash(this.identity),
      completed_stages: [...this.completedStages, stageId],
      latest,
    };
    writeCheckpoint(this.path, document);
    this.document = document;
  }
}

function loadCheckpoint(
  path: string,
  expectedIdentity: DailyCycleCheckpointIdentity,
): DailyCycleCheckpointDocument {
  let parsed: unknown;
  try {
    parsed = JSON.parse(readFileSync(path, "utf-8"));
  } catch (cause) {
    throw new Error(`checkpoint is unreadable or partially written: ${path}`, { cause });
  }
  if (!isRecord(parsed)) throw new Error("checkpoint document must be an object");
  if (
    parsed.schema_version !== DAILY_CYCLE_CHECKPOINT_SCHEMA_VERSION ||
    !isRecord(parsed.identity) ||
    typeof parsed.identity_hash !== "string" ||
    !Array.isArray(parsed.completed_stages) ||
    !isRecord(parsed.latest)
  ) {
    throw new Error("checkpoint document schema mismatch");
  }
  const identity = parsed.identity as unknown as DailyCycleCheckpointIdentity;
  if (canonicalJsonHash(identity) !== parsed.identity_hash) {
    throw new Error("checkpoint identity hash mismatch");
  }
  if (canonicalJsonHash(identity) !== canonicalJsonHash(expectedIdentity)) {
    throw new Error("checkpoint identity drift detected");
  }
  const completedStages = parsed.completed_stages;
  if (
    completedStages.some((stage) => typeof stage !== "string") ||
    completedStages.some((stage, index) => stage !== expectedIdentity.stage_roster[index])
  ) {
    throw new Error("checkpoint completed stage prefix is invalid");
  }
  const latest = parsed.latest as unknown as DailyCycleCheckpointStage;
  if (
    typeof latest.stage_id !== "string" ||
    latest.stage_id !== completedStages.at(-1) ||
    typeof latest.state_hash !== "string" ||
    !isRecord(latest.accepted_output_store) ||
    typeof latest.accepted_output_store_hash !== "string"
  ) {
    throw new Error("checkpoint latest stage is invalid");
  }
  if (canonicalJsonHash(latest.state) !== latest.state_hash) {
    throw new Error("checkpoint graph state hash mismatch");
  }
  if (canonicalJsonHash(latest.accepted_output_store) !== latest.accepted_output_store_hash) {
    throw new Error("checkpoint accepted-output store hash mismatch");
  }
  return parsed as unknown as DailyCycleCheckpointDocument;
}

function writeCheckpoint(path: string, document: DailyCycleCheckpointDocument): void {
  mkdirSync(dirname(path), { recursive: true });
  const temporaryPath = `${path}.${process.pid}.${randomUUID()}.tmp`;
  const fileDescriptor = openSync(temporaryPath, "wx");
  try {
    writeFileSync(fileDescriptor, `${JSON.stringify(document)}\n`, "utf-8");
    fsyncSync(fileDescriptor);
  } finally {
    closeSync(fileDescriptor);
  }
  try {
    renameSync(temporaryPath, path);
  } catch (cause) {
    try {
      unlinkSync(temporaryPath);
    } catch {
      // Preserve the original atomic-rename error.
    }
    throw new Error(`checkpoint atomic replace failed: ${path}`, { cause });
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
