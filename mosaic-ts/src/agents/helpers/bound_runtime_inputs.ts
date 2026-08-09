import type {
  AcceptedAgentOutputRecord,
  AcceptedAgentOutputStore,
  AcceptedOutputRecordRef,
} from "../accepted_output.js";
import type { CurrentPositionsSnapshot } from "../types.js";

export function resolveBoundAcceptedOutputRecords(
  refs: ReadonlyArray<AcceptedOutputRecordRef>,
  store: AcceptedAgentOutputStore | undefined,
): AcceptedAgentOutputRecord[] {
  if (!store) throw new Error("bound runtime inputs require the accepted-output store");
  return refs
    .map((ref) => store.resolve(ref))
    .sort((left, right) => left.accepted_output_id.localeCompare(right.accepted_output_id));
}

export function boundCurrentPositions(snapshot: CurrentPositionsSnapshot): {
  snapshot_status: CurrentPositionsSnapshot["snapshot_status"];
  position_source: CurrentPositionsSnapshot["position_source"];
  source_error_code: string | null;
  position_snapshot_hash: string;
  positions: CurrentPositionsSnapshot["positions"];
} {
  const positionSnapshotHash = snapshot.position_snapshot_hash;
  if (!/^sha256:[0-9a-f]{64}$/.test(positionSnapshotHash ?? "")) {
    throw new Error("bound runtime inputs require a content-hashed position snapshot");
  }
  return {
    snapshot_status: snapshot.snapshot_status,
    position_source: snapshot.position_source,
    source_error_code: snapshot.source_error_code,
    position_snapshot_hash: positionSnapshotHash as string,
    positions: snapshot.positions,
  };
}
