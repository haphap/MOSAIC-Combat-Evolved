import { createHash } from "node:crypto";
import { writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { TOMBSTONED_MACRO_AGENT_IDS } from "../src/agents/macro/_contracts.js";
import { ALL_AGENTS } from "../src/agents/prompts/cohorts.js";
import { loadExecutionBehaviorReleaseManifest } from "../src/autoresearch/execution_behavior_release.js";

const args = new Map<string, string>();
for (let index = 2; index < process.argv.length; index += 2) {
  const key = process.argv[index];
  const value = process.argv[index + 1];
  if (!key?.startsWith("--") || !value) throw new Error(`invalid argument ${key ?? ""}`);
  args.set(key.slice(2), value);
}
const release = loadExecutionBehaviorReleaseManifest(
  resolve(
    args.get("release") ?? "../registry/prompt_checks/execution_behavior_release_manifest_v1.json",
  ),
);
const treeRows = release.variants.map((variant) => ({
  variant_path: variant.variant_path,
  prompt_content_hash: variant.prompt_content_hash,
}));
const promptTreeSha256 = createHash("sha256").update(JSON.stringify(treeRows)).digest("hex");
const manifest = {
  schema_version: "agent_prompt_role_contract_manifest_v2",
  private_prompt_repository: args.get("repository") ?? "haphap/MOSAIC-Prompts",
  private_prompt_branch: args.get("branch") ?? "codex/macro-agent-role-contracts-v2",
  private_prompt_commit: release.private_prompt_commit,
  prompt_tree_sha256: promptTreeSha256,
  execution_behavior_release_id: release.execution_behavior_release_id,
  execution_behavior_release_hash: release.execution_behavior_release_hash,
  cohorts: [...new Set(release.active_production_variants.map((row) => row.cohort_id))].sort(),
  languages: ["en", "zh"],
  agents: [...ALL_AGENTS],
  agent_count: 28,
  cohort_count: 8,
  prompt_count: 448,
  tombstoned_macro_agents: TOMBSTONED_MACRO_AGENT_IDS.map((agent) => ({
    agent,
    status: "legacy_unverified",
  })),
};
writeFileSync(
  resolve(
    args.get("out") ?? "../registry/prompt_checks/agent_prompt_role_contract_manifest_v2.json",
  ),
  `${JSON.stringify(manifest, null, 2)}\n`,
);
