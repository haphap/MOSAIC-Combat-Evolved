import { canonicalJsonHash } from "../../src/agents/helpers/canonical_json.js";
import type { RuntimeBehaviorRunPins } from "../../src/autoresearch/runtime_behavior_bundle.js";

export const EXECUTION_RELEASE_ID_FIXTURE = `execution-behavior-release:${"c".repeat(64)}`;
export const ROSTER_REVISION_ID_FIXTURE = `production-variant-roster-revision:${"d".repeat(64)}`;

export function runtimeBehaviorRunPinsFixture(input?: {
  executionBehaviorReleaseId?: string;
  rosterRevisionId?: string;
}): RuntimeBehaviorRunPins {
  const body = {
    schema_version: "runtime_behavior_run_pins_v1" as const,
    active_prompt_release_id: `active-prompt-release:${"1".repeat(64)}`,
    active_prompt_release_manifest_hash: `sha256:${"2".repeat(64)}`,
    full_bundle_id: `runtime-behavior-bundle:${"3".repeat(64)}`,
    full_bundle_hash: `sha256:${"4".repeat(64)}`,
    execution_behavior_release_id:
      input?.executionBehaviorReleaseId ?? EXECUTION_RELEASE_ID_FIXTURE,
    execution_behavior_release_hash: `sha256:${"5".repeat(64)}`,
    production_variant_roster_revision_id: input?.rosterRevisionId ?? ROSTER_REVISION_ID_FIXTURE,
    production_variant_roster_revision_hash: `sha256:${"6".repeat(64)}`,
    private_runtime_manifest_hash: `sha256:${"7".repeat(64)}`,
    private_policy_hash: `sha256:${"8".repeat(64)}`,
    effect_registry_hash: `sha256:${"9".repeat(64)}`,
    consumer_registry_hash: `sha256:${"a".repeat(64)}`,
    fitness_registry_hash: `sha256:${"b".repeat(64)}`,
    origin_kind: "BASELINE_MIGRATION" as const,
  };
  return { ...body, run_pins_hash: canonicalJsonHash(body) };
}
