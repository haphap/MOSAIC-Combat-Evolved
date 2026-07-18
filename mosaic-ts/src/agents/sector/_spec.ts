import type { z } from "zod";
import type { SectorAgentOutputBase, StandardSectorAgentId } from "../types.js";
import { STANDARD_SECTOR_ROLE_CONTRACTS } from "./_contracts.js";
import type { LayerTwoAgentSpec } from "./_factory.js";
import { STANDARD_SECTOR_FIELD_NAMES } from "./_schemas.js";

export function standardSectorSpec<TOutput extends SectorAgentOutputBase>(
  agentId: StandardSectorAgentId,
  schema: z.ZodType<TOutput>,
): LayerTwoAgentSpec<TOutput> {
  return {
    agentId,
    schema,
    fieldNames: STANDARD_SECTOR_FIELD_NAMES,
    requiredTools: STANDARD_SECTOR_ROLE_CONTRACTS[agentId].requiredTools,
    render: renderStandardSector,
  };
}

export function renderStandardSector(output: SectorAgentOutputBase): string {
  const preferred =
    "direction_id" in output.preferred_direction
      ? output.preferred_direction.direction_id
      : "NO_QUALIFIED_DIRECTION";
  const least =
    "direction_id" in output.least_preferred_direction
      ? output.least_preferred_direction.direction_id
      : output.least_preferred_direction.status;
  return (
    `${output.agent} selection (confidence=${output.confidence.toFixed(2)})\n` +
    `  preferred: ${preferred}\n` +
    `  least_preferred: ${least}\n` +
    `  longs: ${output.long_picks.map((pick) => pick.ts_code).join(", ") || "(none)"}\n` +
    `  shorts_or_avoids: ${output.short_or_avoid_picks.map((pick) => pick.ts_code).join(", ") || "(none)"}`
  );
}
