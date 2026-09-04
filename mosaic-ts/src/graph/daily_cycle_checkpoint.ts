import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import type {
  AcceptedAgentOutputStore,
  AcceptedAgentOutputStoreSnapshot,
} from "../agents/accepted_output.js";
import type { DailyCycleStateType, DailyCycleStateUpdate } from "../agents/state.js";

interface DailyCycleCheckpointDocument {
  completed_stages: string[];
  state: DailyCycleStateType;
  accepted_output_store: AcceptedAgentOutputStoreSnapshot;
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
  readonly stageRoster: readonly string[];
  private document: DailyCycleCheckpointDocument | null;

  private constructor(
    path: string,
    stageRoster: readonly string[],
    document: DailyCycleCheckpointDocument | null,
  ) {
    this.path = resolve(path);
    this.stageRoster = stageRoster;
    this.document = document;
  }

  static open(input: {
    path?: string;
    resume?: boolean;
    asOfDate: string;
    cohort: string;
    stageRoster: readonly string[];
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
      return new DailyCycleCheckpoint(
        path,
        input.stageRoster,
        loadCheckpoint(path, input.asOfDate, input.cohort, input.stageRoster),
      );
    }
    if (input.resume) throw new Error(`checkpoint is missing: ${path}`);
    return new DailyCycleCheckpoint(path, input.stageRoster, null);
  }

  get completedStages(): readonly string[] {
    return this.document?.completed_stages ?? [];
  }

  get restoredState(): DailyCycleStateType | null {
    return this.document?.state ?? null;
  }

  restoreAcceptedOutputStore(store: AcceptedAgentOutputStore): void {
    if (this.document) store.restore(this.document.accepted_output_store);
  }

  shouldSkip(stageId: string): boolean {
    return this.completedStages.includes(stageId);
  }

  commit(stageId: string, state: DailyCycleStateType, store: AcceptedAgentOutputStore): void {
    if (!this.stageRoster.includes(stageId)) return;
    if (this.shouldSkip(stageId)) return;
    const expectedStage = this.stageRoster[this.completedStages.length];
    if (stageId !== expectedStage) {
      throw new Error(
        `checkpoint stage order mismatch: expected ${expectedStage ?? "END"}, got ${stageId}`,
      );
    }
    const document: DailyCycleCheckpointDocument = {
      completed_stages: [...this.completedStages, stageId],
      state: JSON.parse(JSON.stringify(state)) as DailyCycleStateType,
      accepted_output_store: store.snapshot(),
    };
    writeCheckpoint(this.path, document);
    this.document = document;
  }
}

function loadCheckpoint(
  path: string,
  asOfDate: string,
  cohort: string,
  stageRoster: readonly string[],
): DailyCycleCheckpointDocument {
  let parsed: unknown;
  try {
    parsed = JSON.parse(readFileSync(path, "utf-8"));
  } catch (cause) {
    throw new Error(`checkpoint is unreadable or partially written: ${path}`, { cause });
  }
  if (!isRecord(parsed)) throw new Error("checkpoint document must be an object");
  if (
    !Array.isArray(parsed.completed_stages) ||
    !isRecord(parsed.state) ||
    !isRecord(parsed.accepted_output_store)
  ) {
    throw new Error("checkpoint document schema mismatch");
  }
  if (parsed.state.as_of_date !== asOfDate) {
    throw new Error("checkpoint date does not match --date");
  }
  if (parsed.state.active_cohort !== cohort) {
    throw new Error("checkpoint cohort does not match --cohort");
  }
  const completedStages = parsed.completed_stages;
  if (
    completedStages.some((stage) => typeof stage !== "string") ||
    completedStages.some((stage, index) => stage !== stageRoster[index])
  ) {
    throw new Error("checkpoint completed stage prefix is invalid");
  }
  return parsed as unknown as DailyCycleCheckpointDocument;
}

function writeCheckpoint(path: string, document: DailyCycleCheckpointDocument): void {
  mkdirSync(dirname(path), { recursive: true });
  const temporaryPath = `${path}.tmp`;
  writeFileSync(temporaryPath, `${JSON.stringify(document)}\n`, "utf-8");
  renameSync(temporaryPath, path);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
