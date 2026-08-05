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
  return (
    `${output.agent} selection (confidence=${output.confidence.toFixed(2)})\n` +
    `  preferred: ${output.preferred_direction.direction_id}\n` +
    `  least_preferred: ${output.least_preferred_direction.direction_id}\n` +
    `  longs: ${output.long_picks.map((pick) => pick.ts_code).join(", ") || "(none)"}\n` +
    `  shorts_or_avoids: ${output.short_or_avoid_picks.map((pick) => pick.ts_code).join(", ") || "(none)"}`
  );
}
