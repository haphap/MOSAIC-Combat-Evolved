import { MACRO_ATTRIBUTION_PROVIDER_INSTRUCTION } from "../helpers/macro_attribution.js";
import { SECTOR_DIRECTION_PROVIDER_INSTRUCTION } from "../helpers/sector_direction_provider_adapter.js";
import { SECTOR_SELECTED_PROVIDER_INSTRUCTION } from "../helpers/structured_provider_adapters.js";
import {
  canonicalStructuredRepairDirectiveManifest,
  STRUCTURED_REPAIR_DIRECTIVE_CONTRACT_VERSION,
} from "../helpers/structured_repair_directives.js";
import type { LoaderLanguage } from "../prompts/loader.js";

export const SECTOR_PHASE_DIRECTIVE_CONTRACT_VERSION = "sector_phase_directive_bundle_v1";
export const ACTIVE_SECTOR_SYSTEM_PROMPT_PLACEHOLDER = "{{ACTIVE_SECTOR_SYSTEM_PROMPT}}";

export type SectorStructuredPhase = "DIRECTION_RESEARCH" | "CONFLICT_REVIEW" | "FINAL_SELECTION";

export function buildSectorDirectionResearchSystemMessage(input: {
  agentId: string;
  systemPrompt: string;
}): string {
  return (
    `Runtime agent id: ${input.agentId}\nRuntime substage: direction_research\n\n` +
    `${input.systemPrompt}\n\nYou are conducting direction research for the ${input.agentId} sector agent. ` +
    `${SECTOR_DIRECTION_PROVIDER_INSTRUCTION} ` +
    `Submit only the runtime schema's complete pairwise comparison matrix. ` +
    `comparison_claims[].evidence_ids may use only exact ids from the runtime-owned ` +
    `evidence catalog. Each available or confirmed-no-event coverage criterion must reference ` +
    `claims whose evidence_ids collectively include every exact coverage_evidence_id. ` +
    `Copy the exact runtime-owned coverage states and complete ordered coverage evidence-id list. ` +
    `For every comparison, top-level claim_refs must equal exactly the ` +
    `deduplicated union of criterion_results[].claim_refs; omit claims that no criterion uses. ` +
    `Do not submit preferred/least directions, security picks, final_selection, scores, or rankings.`
  );
}

export function buildSectorConflictReviewSystemMessage(agentId: string): string {
  return (
    `Runtime agent id: ${agentId}\nRuntime substage: conflict_review\n\n` +
    `You are performing the one permitted conflict review for the ${agentId} sector agent. ` +
    `${SECTOR_DIRECTION_PROVIDER_INSTRUCTION} ` +
    `Use only the frozen projection below. Submit every conflict-internal pair exactly once. ` +
    `Create new review claims with claim_id values that do not reuse any reserved claim id. ` +
    `Do not use tools and do not submit a final selection, direction ranking, or security picks.`
  );
}

export function buildSectorFinalSelectionSystemMessage(input: {
  agentId: string;
  language: LoaderLanguage;
}): string {
  return (
    `Runtime agent id: ${input.agentId}\nRuntime substage: final_selection\n\n` +
    `You are making the final selection for the ${input.agentId} sector agent. ` +
    `Obey the runtime directive exactly. Do not submit comparisons, review rows, scores, hashes, ` +
    `rankings, or unlisted securities. Keep the payload compact: use one to three key drivers, ` +
    `one to three risks, no more than fourteen reusable claims, and no more than five picks per side; ` +
    `do not restate the same evidence in multiple claims. Author only local Sector claims: upstream ` +
    `Macro claim ids may appear only in macro_input_attributions.claim_refs_used and must never be ` +
    `copied into claims or top-level claim_refs. Every claim_refs field outside ` +
    `macro_input_attributions—including directions, picks, drivers, risks, and the submission—must ` +
    `reference only ids authored in the local claims array. macro_input_attributions must contain exactly one ` +
    `SUBMISSION_SUMMARY row for each of the eight Macro agents with target_local_ref=$SUBMISSION; ` +
    `NOT_MATERIAL rows use an empty claim_refs_used array. Add target-specific rows only for material ` +
    `links to an exact directive target, with no more than six such rows. ` +
    `${SECTOR_SELECTED_PROVIDER_INSTRUCTION} ` +
    `${MACRO_ATTRIBUTION_PROVIDER_INSTRUCTION} ` +
    finalLanguageInstruction(input.language)
  );
}

export function canonicalSectorPhaseDirectiveBundle(input: {
  agentId: string;
  phase: SectorStructuredPhase;
  language: LoaderLanguage;
}): {
  contract_version: typeof SECTOR_PHASE_DIRECTIVE_CONTRACT_VERSION;
  phase: SectorStructuredPhase;
  primary_system_message_template: string;
  repair_contract_version: typeof STRUCTURED_REPAIR_DIRECTIVE_CONTRACT_VERSION;
  repair_directives: ReturnType<typeof canonicalStructuredRepairDirectiveManifest>;
} {
  const primarySystemMessage =
    input.phase === "DIRECTION_RESEARCH"
      ? buildSectorDirectionResearchSystemMessage({
          agentId: input.agentId,
          systemPrompt: ACTIVE_SECTOR_SYSTEM_PROMPT_PLACEHOLDER,
        })
      : input.phase === "CONFLICT_REVIEW"
        ? buildSectorConflictReviewSystemMessage(input.agentId)
        : buildSectorFinalSelectionSystemMessage({
            agentId: input.agentId,
            language: input.language,
          });
  return {
    contract_version: SECTOR_PHASE_DIRECTIVE_CONTRACT_VERSION,
    phase: input.phase,
    primary_system_message_template: primarySystemMessage,
    repair_contract_version: STRUCTURED_REPAIR_DIRECTIVE_CONTRACT_VERSION,
    repair_directives: canonicalStructuredRepairDirectiveManifest(),
  };
}

function finalLanguageInstruction(language: LoaderLanguage): string {
  return language === "en"
    ? "Write prose fields in English."
    : "Write prose fields in Chinese; keep numbers numeric.";
}
