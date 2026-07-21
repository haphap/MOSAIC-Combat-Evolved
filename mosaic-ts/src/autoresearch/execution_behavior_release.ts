import { createHash } from "node:crypto";
import {
  existsSync,
  mkdirSync,
  readFileSync,
  renameSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { dirname, relative, resolve } from "node:path";
import { z } from "zod";
import {
  AlphaDiscoverySchema,
  AutonomousExecutionSchema,
  CioFinalSchema,
  CioProposalSchema,
  CroSchema,
} from "../agents/decision/_schemas.js";
import { STRICT_PROVIDER_EXTRACTION_DESCRIPTOR } from "../agents/helpers/agent_run_contract.js";
import { canonicalJson, canonicalJsonHash } from "../agents/helpers/canonical_json.js";
import { STRUCTURED_PROVIDER_ADAPTER_DESCRIPTOR } from "../agents/helpers/structured_provider_adapters.js";
import {
  createMacroSubmissionSchema,
  MACRO_AGENT_IDS,
  MACRO_PROMPT_COHORT_IDS,
  MACRO_ROLE_CONTRACTS,
  renderMacroPromptBody,
} from "../agents/macro/_contracts.js";
import { renderBundledPrompt } from "../agents/prompts/bundled_prompt_renderer.js";
import {
  extractCohortBehavior,
  immutablePromptContractText,
  validateCohortBehaviorLanguage,
} from "../agents/prompts/cohort_behavior.js";
import {
  ALL_AGENTS,
  LAYER_BY_AGENT,
  type Language,
  promptPath,
} from "../agents/prompts/cohorts.js";
import { containsPrivateKnotPromptContent } from "../agents/prompts/private_knot_prompt_markers.js";
import {
  readVerifiedPromptSourceFile,
  type VerifiedPromptSourceCommit,
  verifyPromptSourceCommit,
} from "../agents/prompts/prompt_source_provenance.js";
import { RUNTIME_AGENT_SPEC_BY_AGENT } from "../agents/prompts/runtime_agent_spec.js";
import { upsertRuntimeEvidenceContract } from "../agents/prompts/runtime_evidence_contract.js";
import { STANDARD_SECTOR_ROLE_CONTRACTS } from "../agents/sector/_contracts.js";
import {
  AgricultureSchema,
  BiotechSchema,
  ConsumerSchema,
  EnergySchema,
  FinancialsSchema,
  IndustrialsSchema,
  RealEstateConstructionSchema,
  RelationshipMapperSchema,
  SemiconductorSchema,
  TechnologySchema,
} from "../agents/sector/_schemas.js";
import {
  DirectionPairwiseComparisonSubmissionSchema,
  SECTOR_DIRECTION_COMPARISON_CONTRACT_VERSION,
} from "../agents/sector/comparison.js";
import {
  AckmanSchema,
  BurrySchema,
  DruckenmillerSchema,
  MungerSchema,
} from "../agents/superinvestor/_schemas.js";
import {
  CAPABILITY_CONTRACT_VERSION,
  SNAPSHOT_BUNDLE_CONTRACT_VERSION,
} from "../agents/tool_contract.js";
import { KNOT_RUNTIME_CONTRACT_REF } from "./knot_contract.js";

export const EXECUTION_BEHAVIOR_RELEASE_SCHEMA_VERSION = "execution_behavior_release_manifest_v1";
export const EXECUTION_BEHAVIOR_RELEASE_CONTRACT_VERSION = "execution_behavior_release_v1";
export const STRUCTURED_PROVIDER_CONTRACT_VERSION = "structured_provider_contract_v2";

export const STRUCTURED_OUTPUT_SCHEMA_PHASES = [
  "DEFAULT",
  "DIRECTION_RESEARCH",
  "CONFLICT_REVIEW",
  "FINAL_SELECTION",
  "CIO_PROPOSAL",
  "CIO_FINAL",
] as const;

export type StructuredOutputSchemaPhase = (typeof STRUCTURED_OUTPUT_SCHEMA_PHASES)[number];

const Sha256Schema = z.string().regex(/^sha256:[0-9a-f]{64}$/);
const VersionHashSchema = z.string().regex(/^(?:prompt-behavior|execution-behavior):[0-9a-f]{64}$/);

export const StructuredOutputSchemaBindingSchema = z
  .object({
    phase: z.enum(STRUCTURED_OUTPUT_SCHEMA_PHASES),
    schema_id: z.string().trim().min(1),
    schema_hash: Sha256Schema,
    immutable_phase_instruction_hash: Sha256Schema,
  })
  .strict();

export const ExecutionBehaviorReleaseVariantSchema = z
  .object({
    variant_path: z
      .string()
      .regex(
        /^cohort_[a-z0-9_]+\/(?:macro|sector|superinvestor|decision)\/[a-z0-9_]+\.(?:en|zh)\.md$/,
      ),
    agent_id: z.string().trim().min(1),
    cohort_id: z.string().trim().min(1),
    language: z.enum(["en", "zh"]),
    prompt_content_hash: Sha256Schema,
    immutable_contract_block_hash: Sha256Schema,
    prompt_behavior_version: VersionHashSchema,
    execution_behavior_version: VersionHashSchema,
    structured_output_schema_bindings: z.array(StructuredOutputSchemaBindingSchema).min(1),
    structured_output_schema_set_hash: Sha256Schema,
    structured_provider_contract_hash: Sha256Schema,
    runtime_tool_manifest_hash: Sha256Schema,
    knot_champion_baseline_hash: Sha256Schema,
  })
  .strict();

export const ExecutionBehaviorProductionVariantSchema = z
  .object({
    production_variant_roster_id: z.string().regex(/^production-variant-roster:[0-9a-f]{64}$/),
    cohort_id: z.string().trim().min(1),
    language: z.enum(["en", "zh"]),
  })
  .strict();

export const ExecutionBehaviorReleaseManifestSchema = z
  .object({
    schema_version: z.literal(EXECUTION_BEHAVIOR_RELEASE_SCHEMA_VERSION),
    execution_behavior_release_id: z.string().regex(/^execution-behavior-release:[0-9a-f]{64}$/),
    execution_behavior_release_hash: Sha256Schema,
    private_prompt_commit: z.string().regex(/^[0-9a-f]{40}$/),
    provider_binding: z
      .object({
        provider: z.string().trim().min(1),
        model: z.string().trim().min(1),
        base_url_mode: z.enum(["PROVIDER_DEFAULT", "CONFIGURED_PRIVATE_ENDPOINT"]),
        structured_output_mode: z.literal("JSON_SCHEMA_STRICT"),
        repair_policy: z.literal("BOUNDED_SCHEMA_REPAIR_V1"),
      })
      .strict(),
    active_production_variants: z.array(ExecutionBehaviorProductionVariantSchema).length(16),
    variants: z.array(ExecutionBehaviorReleaseVariantSchema).length(448),
  })
  .strict();

export type ExecutionBehaviorReleaseManifest = z.infer<
  typeof ExecutionBehaviorReleaseManifestSchema
>;
export type ExecutionBehaviorReleaseVariant = z.infer<typeof ExecutionBehaviorReleaseVariantSchema>;

export interface BuildExecutionBehaviorReleaseInput {
  privatePromptsRoot: string;
  bundledPromptsRoot: string;
  privatePromptCommit: string;
  provider: string;
  model: string;
  baseUrlMode: "PROVIDER_DEFAULT" | "CONFIGURED_PRIVATE_ENDPOINT";
}

export interface WriteExecutionBehaviorReleaseArtifactsInput {
  manifest: ExecutionBehaviorReleaseManifest;
  activeManifestPath: string;
  archiveRoot: string;
}

const STANDARD_SECTOR_IDS = Object.keys(STANDARD_SECTOR_ROLE_CONTRACTS).sort();

const OUTPUT_SCHEMA_BY_AGENT: Readonly<Record<string, z.ZodType>> = {
  semiconductor: SemiconductorSchema,
  technology: TechnologySchema,
  energy: EnergySchema,
  biotech: BiotechSchema,
  consumer: ConsumerSchema,
  industrials: IndustrialsSchema,
  real_estate_construction: RealEstateConstructionSchema,
  financials: FinancialsSchema,
  agriculture: AgricultureSchema,
  relationship_mapper: RelationshipMapperSchema,
  druckenmiller: DruckenmillerSchema,
  munger: MungerSchema,
  burry: BurrySchema,
  ackman: AckmanSchema,
  cro: CroSchema,
  alpha_discovery: AlphaDiscoverySchema,
  autonomous_execution: AutonomousExecutionSchema,
};

export function buildExecutionBehaviorReleaseManifest(
  input: BuildExecutionBehaviorReleaseInput,
): ExecutionBehaviorReleaseManifest {
  const privatePromptSource = verifyPromptSourceCommit({
    promptsRoot: input.privatePromptsRoot,
    commit: requiredCommit(input.privatePromptCommit),
    source: "private",
  });
  const privatePromptCommit = privatePromptSource.commit;
  const providerBinding = {
    provider: requiredText(input.provider, "provider"),
    model: requiredText(input.model, "model"),
    base_url_mode: input.baseUrlMode,
    structured_output_mode: "JSON_SCHEMA_STRICT" as const,
    repair_policy: "BOUNDED_SCHEMA_REPAIR_V1" as const,
  };
  const variants: ExecutionBehaviorReleaseVariant[] = [];
  const activeProductionVariants: z.infer<typeof ExecutionBehaviorProductionVariantSchema>[] = [];

  for (const cohort of MACRO_PROMPT_COHORT_IDS) {
    for (const language of ["en", "zh"] as const) {
      activeProductionVariants.push({
        production_variant_roster_id: productionVariantRosterId(cohort, language),
        cohort_id: cohort,
        language,
      });
      for (const agent of ALL_AGENTS) {
        variants.push(
          buildVariant({
            ...input,
            privatePromptSource,
            providerBinding,
            cohort,
            language,
            agent,
          }),
        );
      }
    }
  }

  const sortedVariants = variants.sort((left, right) =>
    left.variant_path.localeCompare(right.variant_path),
  );
  const sortedProductionVariants = activeProductionVariants.sort((left, right) =>
    `${left.cohort_id}:${left.language}`.localeCompare(`${right.cohort_id}:${right.language}`),
  );
  const releaseContent = {
    schema_version: EXECUTION_BEHAVIOR_RELEASE_SCHEMA_VERSION,
    private_prompt_commit: privatePromptCommit,
    provider_binding: providerBinding,
    active_production_variants: sortedProductionVariants,
    variants: sortedVariants,
  } as const;
  const releaseId = deterministicId("execution-behavior-release", releaseContent);
  const withId = {
    schema_version: releaseContent.schema_version,
    execution_behavior_release_id: releaseId,
    private_prompt_commit: releaseContent.private_prompt_commit,
    provider_binding: releaseContent.provider_binding,
    active_production_variants: releaseContent.active_production_variants,
    variants: releaseContent.variants,
  };
  return validateExecutionBehaviorReleaseManifest({
    ...withId,
    execution_behavior_release_hash: canonicalHash(withId),
  });
}

export function validateExecutionBehaviorReleaseManifest(
  value: unknown,
): ExecutionBehaviorReleaseManifest {
  const manifest = ExecutionBehaviorReleaseManifestSchema.parse(value);
  const expectedAgents = [...ALL_AGENTS].sort();
  const productionKeys = new Set<string>();
  for (const row of manifest.active_production_variants) {
    const key = `${row.cohort_id}:${row.language}`;
    if (productionKeys.has(key)) throw new Error(`duplicate production variant ${key}`);
    productionKeys.add(key);
    if (
      row.production_variant_roster_id !== productionVariantRosterId(row.cohort_id, row.language)
    ) {
      throw new Error(`production roster id mismatch for ${key}`);
    }
  }
  const expectedProductionKeys = new Set(
    MACRO_PROMPT_COHORT_IDS.flatMap((cohort) =>
      ["en", "zh"].map((language) => `${cohort}:${language}`),
    ),
  );
  if (!setEqual(productionKeys, expectedProductionKeys)) {
    throw new Error("active production variants must cover exactly 8 cohorts x 2 languages");
  }

  const variantPaths = new Set<string>();
  const agentsByProductionKey = new Map<string, string[]>();
  const promptHashesByAgentLanguage = new Map<string, Set<string>>();
  for (const variant of manifest.variants) {
    if (variantPaths.has(variant.variant_path))
      throw new Error(`duplicate variant path ${variant.variant_path}`);
    variantPaths.add(variant.variant_path);
    const expectedPath = `${variant.cohort_id}/${LAYER_BY_AGENT[variant.agent_id]}/${variant.agent_id}.${variant.language}.md`;
    if (variant.variant_path !== expectedPath)
      throw new Error(`variant path mismatch: ${variant.variant_path}`);
    const key = `${variant.cohort_id}:${variant.language}`;
    agentsByProductionKey.set(key, [...(agentsByProductionKey.get(key) ?? []), variant.agent_id]);
    const behaviorKey = `${variant.agent_id}:${variant.language}`;
    const promptHashes = promptHashesByAgentLanguage.get(behaviorKey) ?? new Set<string>();
    promptHashes.add(variant.prompt_content_hash);
    promptHashesByAgentLanguage.set(behaviorKey, promptHashes);
    validateSchemaBindings(variant.agent_id, variant.structured_output_schema_bindings);
    if (
      variant.structured_output_schema_set_hash !==
      canonicalHash(variant.structured_output_schema_bindings)
    ) {
      throw new Error(`${variant.variant_path}: schema binding set hash mismatch`);
    }
    const currentBindings = structuredSchemaBindings(variant.agent_id, variant.language);
    if (
      canonicalJson(variant.structured_output_schema_bindings) !== canonicalJson(currentBindings)
    ) {
      throw new Error(`${variant.variant_path}: structured output contract drift`);
    }
    const currentToolManifestHash = computeRuntimeToolManifestHash(variant.agent_id);
    if (variant.runtime_tool_manifest_hash !== currentToolManifestHash) {
      throw new Error(`${variant.variant_path}: runtime tool contract drift`);
    }
    const currentProviderContractHash = computeStructuredProviderContractHash(variant.agent_id);
    if (variant.structured_provider_contract_hash !== currentProviderContractHash) {
      throw new Error(`${variant.variant_path}: structured provider contract drift`);
    }
    if (
      variant.prompt_behavior_version !== `prompt-behavior:${stripSha(variant.prompt_content_hash)}`
    ) {
      throw new Error(`${variant.variant_path}: prompt behavior version mismatch`);
    }
    const currentExecutionVersion = computeExecutionBehaviorVersion({
      agentId: variant.agent_id,
      language: variant.language,
      providerBinding: manifest.provider_binding,
      schemaSetHash: variant.structured_output_schema_set_hash,
      structuredProviderContractHash: variant.structured_provider_contract_hash,
      runtimeToolManifestHash: variant.runtime_tool_manifest_hash,
    });
    if (variant.execution_behavior_version !== currentExecutionVersion) {
      throw new Error(`${variant.variant_path}: execution behavior contract drift`);
    }
    const expectedKnot = knotChampionBaselineHash(variant);
    if (variant.knot_champion_baseline_hash !== expectedKnot) {
      throw new Error(`${variant.variant_path}: KNOT champion baseline hash mismatch`);
    }
  }
  for (const key of expectedProductionKeys) {
    const agents = (agentsByProductionKey.get(key) ?? []).sort();
    if (agents.join("\0") !== expectedAgents.join("\0")) {
      throw new Error(`${key}: production variant must resolve exactly 28 Agents`);
    }
  }
  for (const agent of expectedAgents) {
    for (const language of ["en", "zh"] as const) {
      const hashes = promptHashesByAgentLanguage.get(`${agent}:${language}`);
      if (hashes?.size !== MACRO_PROMPT_COHORT_IDS.length) {
        throw new Error(
          `${agent}:${language}: every production cohort must have distinct cohort behavior`,
        );
      }
    }
  }

  return validateExecutionBehaviorReleaseArtifactIntegrity(manifest);
}

/** Validate an immutable release artifact without comparing it with today's runtime code. */
export function validateExecutionBehaviorReleaseArtifactIntegrity(
  value: unknown,
): ExecutionBehaviorReleaseManifest {
  const manifest = ExecutionBehaviorReleaseManifestSchema.parse(value);
  const withoutHash = {
    schema_version: manifest.schema_version,
    execution_behavior_release_id: manifest.execution_behavior_release_id,
    private_prompt_commit: manifest.private_prompt_commit,
    provider_binding: manifest.provider_binding,
    active_production_variants: manifest.active_production_variants,
    variants: manifest.variants,
  };
  if (manifest.execution_behavior_release_hash !== canonicalHash(withoutHash)) {
    throw new Error("execution behavior release hash mismatch");
  }
  const releaseContent = {
    schema_version: manifest.schema_version,
    private_prompt_commit: manifest.private_prompt_commit,
    provider_binding: manifest.provider_binding,
    active_production_variants: manifest.active_production_variants,
    variants: manifest.variants,
  };
  if (
    manifest.execution_behavior_release_id !==
    deterministicId("execution-behavior-release", releaseContent)
  ) {
    throw new Error("execution behavior release id mismatch");
  }
  return manifest;
}

export function releaseVariantFor(
  manifest: ExecutionBehaviorReleaseManifest,
  cohort: string,
  language: Language,
  agentId: string,
): ExecutionBehaviorReleaseVariant {
  const found = manifest.variants.find(
    (variant) =>
      variant.cohort_id === cohort && variant.language === language && variant.agent_id === agentId,
  );
  if (!found)
    throw new Error(`execution behavior variant missing: ${cohort}:${language}:${agentId}`);
  return found;
}

export function renderExecutionBehaviorReleaseManifest(
  manifest: ExecutionBehaviorReleaseManifest,
): string {
  return `${JSON.stringify(validateExecutionBehaviorReleaseManifest(manifest), null, 2)}\n`;
}

export function loadExecutionBehaviorReleaseManifest(
  path: string,
): ExecutionBehaviorReleaseManifest {
  let payload: unknown;
  try {
    payload = JSON.parse(readFileSync(path, "utf8"));
  } catch (cause) {
    throw new Error(`cannot load execution behavior release manifest ${path}`, { cause });
  }
  return validateExecutionBehaviorReleaseManifest(payload);
}

export function loadExecutionBehaviorReleaseArchive(input: {
  archiveRoot: string;
  executionBehaviorReleaseId: string;
  executionBehaviorReleaseHash: string;
}): ExecutionBehaviorReleaseManifest {
  if (!/^execution-behavior-release:[0-9a-f]{64}$/.test(input.executionBehaviorReleaseId)) {
    throw new Error("execution behavior release archive id is invalid");
  }
  if (!/^sha256:[0-9a-f]{64}$/.test(input.executionBehaviorReleaseHash)) {
    throw new Error("execution behavior release archive hash is invalid");
  }
  const archivePath = resolve(
    input.archiveRoot,
    `${input.executionBehaviorReleaseId.slice("execution-behavior-release:".length)}--${stripSha(
      input.executionBehaviorReleaseHash,
    )}.json`,
  );
  const manifest = loadExecutionBehaviorReleaseManifest(archivePath);
  if (
    manifest.execution_behavior_release_id !== input.executionBehaviorReleaseId ||
    manifest.execution_behavior_release_hash !== input.executionBehaviorReleaseHash
  ) {
    throw new Error("execution behavior release archive pin mismatch");
  }
  return manifest;
}

export function executionBehaviorReleaseArchiveFilename(value: unknown): string {
  const manifest = validateExecutionBehaviorReleaseArtifactIntegrity(value);
  return `${manifest.execution_behavior_release_id.replace(
    /^execution-behavior-release:/,
    "",
  )}--${stripSha(manifest.execution_behavior_release_hash)}.json`;
}

/**
 * Preserve the previous active release, persist the new immutable archive, and
 * only then atomically advance the mutable active pointer.
 */
export function writeExecutionBehaviorReleaseArtifacts(
  input: WriteExecutionBehaviorReleaseArtifactsInput,
): { activeManifestPath: string; archivePath: string } {
  const manifest = validateExecutionBehaviorReleaseManifest(input.manifest);
  const activeManifestPath = resolve(input.activeManifestPath);
  const archiveRoot = resolve(input.archiveRoot);
  mkdirSync(archiveRoot, { recursive: true });
  if (existsSync(activeManifestPath)) {
    archiveExecutionBehaviorRelease(
      parseExecutionBehaviorReleaseArtifact(activeManifestPath),
      archiveRoot,
    );
  }
  const archivePath = archiveExecutionBehaviorRelease(manifest, archiveRoot);
  mkdirSync(dirname(activeManifestPath), { recursive: true });
  const temporaryPath = `${activeManifestPath}.${process.pid}.tmp`;
  try {
    writeFileSync(temporaryPath, renderExecutionBehaviorReleaseManifest(manifest), {
      flag: "wx",
    });
    renameSync(temporaryPath, activeManifestPath);
  } finally {
    if (existsSync(temporaryPath)) unlinkSync(temporaryPath);
  }
  return { activeManifestPath, archivePath };
}

function parseExecutionBehaviorReleaseArtifact(path: string): ExecutionBehaviorReleaseManifest {
  let payload: unknown;
  try {
    payload = JSON.parse(readFileSync(path, "utf8"));
  } catch (cause) {
    throw new Error(`cannot load execution behavior release artifact ${path}`, { cause });
  }
  return validateExecutionBehaviorReleaseArtifactIntegrity(payload);
}

function archiveExecutionBehaviorRelease(value: unknown, archiveRoot: string): string {
  const manifest = validateExecutionBehaviorReleaseArtifactIntegrity(value);
  const rendered = `${JSON.stringify(manifest, null, 2)}\n`;
  const archivePath = resolve(archiveRoot, executionBehaviorReleaseArchiveFilename(manifest));
  if (existsSync(archivePath)) {
    if (readFileSync(archivePath, "utf8") !== rendered) {
      throw new Error(`immutable execution behavior release archive collision: ${archivePath}`);
    }
    return archivePath;
  }
  writeFileSync(archivePath, rendered, { flag: "wx" });
  return archivePath;
}

function buildVariant(
  input: BuildExecutionBehaviorReleaseInput & {
    privatePromptSource: VerifiedPromptSourceCommit;
    providerBinding: ExecutionBehaviorReleaseManifest["provider_binding"];
    cohort: string;
    language: Language;
    agent: string;
  },
): ExecutionBehaviorReleaseVariant {
  const layer = LAYER_BY_AGENT[input.agent];
  if (!layer) throw new Error(`unknown Agent ${input.agent}`);
  const spec = RUNTIME_AGENT_SPEC_BY_AGENT.get(input.agent);
  if (!spec) throw new Error(`runtime spec missing for ${input.agent}`);
  const path = promptPath({
    agent: input.agent,
    cohort: input.cohort,
    language: input.language,
    promptsRoot: input.privatePromptsRoot,
  });
  const prompt = readVerifiedPromptSourceFile(input.privatePromptSource, path);
  const expected = expectedPrompt(input.agent, input.language);
  const cohortBehavior = extractCohortBehavior(prompt);
  if (containsPrivateKnotPromptContent(prompt)) {
    throw new Error(
      `${relative(input.privatePromptsRoot, path)}: private KNOT policy must remain hidden`,
    );
  }
  try {
    validateCohortBehaviorLanguage(cohortBehavior, input.language);
  } catch (error) {
    throw new Error(`${relative(input.privatePromptsRoot, path)}: ${(error as Error).message}`);
  }
  const bundledPath = promptPath({
    agent: input.agent,
    cohort: "cohort_default",
    language: input.language,
    promptsRoot: input.bundledPromptsRoot,
  });
  const bundledPrompt = readFileSync(bundledPath, "utf8");
  const canonicalDefault = expectedPrompt(input.agent, input.language);
  if (bundledPrompt !== canonicalDefault) {
    throw new Error(
      `${relative(resolve(input.bundledPromptsRoot, ".."), bundledPath)}: bundled prompt drift`,
    );
  }
  const promptContentHash = canonicalTextHash(prompt);
  const immutableContractBlockHash = immutablePromptContractHash(prompt);
  const expectedImmutableHash = immutablePromptContractHash(expected);
  const bundledImmutableHash = immutablePromptContractHash(bundledPrompt);
  if (
    immutableContractBlockHash !== expectedImmutableHash ||
    immutableContractBlockHash !== bundledImmutableHash
  ) {
    throw new Error(
      `${input.agent}:${input.cohort}:${input.language}: immutable prompt contract drift`,
    );
  }
  const bindings = structuredSchemaBindings(input.agent, input.language);
  const schemaSetHash = canonicalHash(bindings);
  const runtimeToolManifestHash = computeRuntimeToolManifestHash(input.agent);
  const structuredProviderContractHash = computeStructuredProviderContractHash(input.agent);
  const promptBehaviorVersion = `prompt-behavior:${stripSha(promptContentHash)}`;
  const executionBehaviorVersion = computeExecutionBehaviorVersion({
    agentId: input.agent,
    language: input.language,
    providerBinding: input.providerBinding,
    schemaSetHash,
    structuredProviderContractHash,
    runtimeToolManifestHash,
  });
  const base = {
    variant_path: `${input.cohort}/${layer}/${input.agent}.${input.language}.md`,
    agent_id: input.agent,
    cohort_id: input.cohort,
    language: input.language,
    prompt_content_hash: promptContentHash,
    immutable_contract_block_hash: immutableContractBlockHash,
    prompt_behavior_version: promptBehaviorVersion,
    execution_behavior_version: executionBehaviorVersion,
    structured_output_schema_bindings: bindings,
    structured_output_schema_set_hash: schemaSetHash,
    structured_provider_contract_hash: structuredProviderContractHash,
    runtime_tool_manifest_hash: runtimeToolManifestHash,
  };
  return ExecutionBehaviorReleaseVariantSchema.parse({
    ...base,
    knot_champion_baseline_hash: knotChampionBaselineHash(base),
  });
}

function expectedPrompt(agent: string, language: Language): string {
  const spec = RUNTIME_AGENT_SPEC_BY_AGENT.get(agent);
  if (!spec) throw new Error(`runtime spec missing for ${agent}`);
  const body = MACRO_AGENT_IDS.includes(agent as (typeof MACRO_AGENT_IDS)[number])
    ? renderMacroPromptBody(agent as (typeof MACRO_AGENT_IDS)[number], language, "cohort_default")
    : renderBundledPrompt(agent, language, "cohort_default");
  return upsertRuntimeEvidenceContract(body, spec, language);
}

function immutablePromptContractHash(prompt: string): string {
  return canonicalTextHash(immutablePromptContractText(prompt));
}

function structuredSchemaBindings(
  agent: string,
  language: Language,
): ExecutionBehaviorReleaseVariant["structured_output_schema_bindings"] {
  if (STANDARD_SECTOR_IDS.includes(agent)) {
    const directions =
      STANDARD_SECTOR_ROLE_CONTRACTS[agent as keyof typeof STANDARD_SECTOR_ROLE_CONTRACTS]
        .directionIds;
    return [
      schemaBinding(
        agent,
        "DIRECTION_RESEARCH",
        `${agent}.direction_research.v2`,
        {
          contract_version: SECTOR_DIRECTION_COMPARISON_CONTRACT_VERSION,
          eligible_direction_contract: directions,
          pairwise_schema: toJsonSchema(DirectionPairwiseComparisonSubmissionSchema),
        },
        language,
      ),
      schemaBinding(
        agent,
        "CONFLICT_REVIEW",
        `${agent}.conflict_review.v2`,
        {
          contract_version: SECTOR_DIRECTION_COMPARISON_CONTRACT_VERSION,
          eligible_direction_contract: directions,
          review_round: 1,
          pairwise_schema: toJsonSchema(DirectionPairwiseComparisonSubmissionSchema),
        },
        language,
      ),
      schemaBinding(
        agent,
        "FINAL_SELECTION",
        `${agent}.final_selection.v2`,
        toJsonSchema(OUTPUT_SCHEMA_BY_AGENT[agent]),
        language,
      ),
    ];
  }
  if (agent === "cio") {
    return [
      schemaBinding(
        agent,
        "CIO_PROPOSAL",
        "decision.cio.proposal.v1",
        toJsonSchema(CioProposalSchema),
        language,
      ),
      schemaBinding(
        agent,
        "CIO_FINAL",
        "decision.cio.final.v1",
        toJsonSchema(CioFinalSchema),
        language,
      ),
    ];
  }
  const schema = MACRO_AGENT_IDS.includes(agent as (typeof MACRO_AGENT_IDS)[number])
    ? createMacroSubmissionSchema(agent as (typeof MACRO_AGENT_IDS)[number])
    : OUTPUT_SCHEMA_BY_AGENT[agent];
  if (!schema) throw new Error(`output schema missing for ${agent}`);
  const schemaId = RUNTIME_AGENT_SPEC_BY_AGENT.get(agent)?.stages[0]?.outputSchemaRef;
  if (!schemaId) throw new Error(`output schema id missing for ${agent}`);
  return [schemaBinding(agent, "DEFAULT", schemaId, toJsonSchema(schema), language)];
}

function schemaBinding(
  agent: string,
  phase: StructuredOutputSchemaPhase,
  schemaId: string,
  schemaDescriptor: unknown,
  language: Language,
): z.infer<typeof StructuredOutputSchemaBindingSchema> {
  return {
    phase,
    schema_id: schemaId,
    schema_hash: canonicalHash(schemaDescriptor),
    immutable_phase_instruction_hash: canonicalTextHash(phaseInstruction(agent, phase, language)),
  };
}

function phaseInstruction(
  agent: string,
  phase: StructuredOutputSchemaPhase,
  language: Language,
): string {
  const languageInstruction = language === "zh" ? "prose=zh;numbers=numeric" : "prose=en";
  const instructions: Record<StructuredOutputSchemaPhase, string> = {
    DEFAULT: "populate-runtime-json-schema;cite-only-frozen-evidence;explicit-empty-disposition",
    DIRECTION_RESEARCH:
      "compare-complete-frozen-direction-domain;no-final-selection;no-rank-or-score",
    CONFLICT_REVIEW: "one-review-only;conflict-internal-pairs;no-tools;no-final-selection",
    FINAL_SELECTION: "obey-runtime-directive;no-comparison-or-ranking;registered-securities-only",
    CIO_PROPOSAL: "freeze-candidate-target-from-pre-cio-snapshot;bind-alpha-source",
    CIO_FINAL: "reuse-proposal-pre-cio-snapshot;apply-cro-and-execution;no-new-candidate",
  };
  return `${agent};${phase};${instructions[phase]};${languageInstruction}`;
}

function computeRuntimeToolManifestHash(agent: string): string {
  const spec = RUNTIME_AGENT_SPEC_BY_AGENT.get(agent);
  if (!spec) throw new Error(`runtime spec missing for ${agent}`);
  const phaseTools = STANDARD_SECTOR_IDS.includes(agent)
    ? [
        { phase: "DIRECTION_RESEARCH", tools: [...spec.requiredTools] },
        { phase: "CONFLICT_REVIEW", tools: [] },
        { phase: "FINAL_SELECTION", tools: [] },
      ]
    : agent === "cio"
      ? [
          { phase: "CIO_PROPOSAL", tools: [...spec.requiredTools] },
          { phase: "CIO_FINAL", tools: [...spec.requiredTools] },
        ]
      : [{ phase: "DEFAULT", tools: [...spec.requiredTools] }];
  return canonicalHash({
    agent_tool_contract_version: "agent_tool_contract_manifest_v1",
    capability_contract_version: CAPABILITY_CONTRACT_VERSION,
    snapshot_bundle_contract_version: SNAPSHOT_BUNDLE_CONTRACT_VERSION,
    agent_id: agent,
    phase_tools: phaseTools,
  });
}

function computeExecutionBehaviorVersion(input: {
  agentId: string;
  language: Language;
  providerBinding: ExecutionBehaviorReleaseManifest["provider_binding"];
  schemaSetHash: string;
  structuredProviderContractHash: string;
  runtimeToolManifestHash: string;
}): string {
  return `execution-behavior:${stripSha(
    canonicalHash({
      contract_version: EXECUTION_BEHAVIOR_RELEASE_CONTRACT_VERSION,
      agent_id: input.agentId,
      language: input.language,
      provider_binding: input.providerBinding,
      structured_output_schema_set_hash: input.schemaSetHash,
      structured_provider_contract_hash: input.structuredProviderContractHash,
      runtime_tool_manifest_hash: input.runtimeToolManifestHash,
      capability_contract_version: CAPABILITY_CONTRACT_VERSION,
      snapshot_bundle_contract_version: SNAPSHOT_BUNDLE_CONTRACT_VERSION,
    }),
  )}`;
}

function validateSchemaBindings(
  agent: string,
  bindings: ExecutionBehaviorReleaseVariant["structured_output_schema_bindings"],
): void {
  const phases = bindings.map((binding) => binding.phase);
  if (new Set(phases).size !== phases.length)
    throw new Error(`${agent}: duplicate structured schema phase`);
  const order = phases.map((phase) => STRUCTURED_OUTPUT_SCHEMA_PHASES.indexOf(phase));
  if (order.some((value, index) => index > 0 && value <= (order[index - 1] ?? -1))) {
    throw new Error(`${agent}: structured schema phases are not canonical`);
  }
  const expected = STANDARD_SECTOR_IDS.includes(agent)
    ? ["DIRECTION_RESEARCH", "CONFLICT_REVIEW", "FINAL_SELECTION"]
    : agent === "cio"
      ? ["CIO_PROPOSAL", "CIO_FINAL"]
      : ["DEFAULT"];
  if (phases.join("\0") !== expected.join("\0"))
    throw new Error(`${agent}: structured schema phase set mismatch`);
}

function knotChampionBaselineHash(
  variant: Omit<ExecutionBehaviorReleaseVariant, "knot_champion_baseline_hash">,
): string {
  return canonicalHash({
    contract: "knot_champion_baseline_v1",
    agent_id: variant.agent_id,
    cohort_id: variant.cohort_id,
    language: variant.language,
    prompt_behavior_version: variant.prompt_behavior_version,
    execution_behavior_version: variant.execution_behavior_version,
    structured_output_schema_set_hash: variant.structured_output_schema_set_hash,
    structured_provider_contract_hash: variant.structured_provider_contract_hash,
    runtime_tool_manifest_hash: variant.runtime_tool_manifest_hash,
    knot_runtime_contract_manifest_hash:
      KNOT_RUNTIME_CONTRACT_REF.knot_runtime_contract_manifest_hash,
  });
}

function computeStructuredProviderContractHash(agent: string): string {
  const runtimeDomainContract = MACRO_AGENT_IDS.includes(agent as (typeof MACRO_AGENT_IDS)[number])
    ? {
        schema_domain: "MACRO_RUNTIME_COMPACT_DOMAIN_V1",
        mode: MACRO_ROLE_CONTRACTS[agent as (typeof MACRO_AGENT_IDS)[number]].mode,
        components: Object.keys(
          MACRO_ROLE_CONTRACTS[agent as (typeof MACRO_AGENT_IDS)[number]].components,
        ).sort(),
        claim_materialization: "ONE_CLAIM_PER_JUDGMENT_V1",
      }
    : STANDARD_SECTOR_IDS.includes(agent)
      ? {
          schema_domain: "STANDARD_SECTOR_RUNTIME_DIRECTIVE_V1",
          direction_research: "EXACT_COMPLETE_PAIRWISE_DOMAIN_V1",
          conflict_review: "FROZEN_CONFLICT_PAIR_DOMAIN_V1",
          final_selection: "EXACT_DIRECTIVE_AND_SECURITY_ENUM_DOMAIN_V1",
        }
      : agent === "relationship_mapper"
        ? {
            schema_domain: "RELATIONSHIP_RUNTIME_OPPORTUNITY_DOMAIN_V1",
            factual_edges: "FROZEN_FACTUAL_EDGE_ENUM_V1",
            predictive_edges: "FROZEN_NONEMPTY_OPPORTUNITY_ENUM_V1",
          }
        : ["druckenmiller", "munger", "burry", "ackman"].includes(agent)
          ? {
              schema_domain: "SUPERINVESTOR_RUNTIME_CANDIDATE_DOMAIN_V1",
              nonempty: "EXACT_A_SHARE_CANDIDATE_ENUM_V1",
              empty: "ABSTENTION_ONLY_V1",
            }
          : agent === "alpha_discovery"
            ? {
                schema_domain: "ALPHA_RUNTIME_NOVEL_CANDIDATE_DOMAIN_V1",
                nonempty: "EXACT_CANDIDATE_REF_TS_CODE_PAIR_ENUM_V1",
                empty: "NONE_FOUND_ONLY_V1",
              }
            : agent === "cio"
              ? {
                  schema_domain: "CIO_RUNTIME_PORTFOLIO_DOMAIN_V1",
                  empty_positions: "NO_HOLD_ENUM_V1",
                  no_investable_candidate: "ALL_CASH_ONLY_V1",
                }
              : { schema_domain: "STATIC_AGENT_SUBMISSION_DOMAIN_V1" };
  return canonicalHash({
    contract_version: STRUCTURED_PROVIDER_CONTRACT_VERSION,
    zod_json_schema_projection: "ZOD_TO_JSON_SCHEMA_V1",
    unsupported_keyword_projection: "STRICT_PROVIDER_KEYWORD_OMISSION_V1",
    extraction_descriptor: STRICT_PROVIDER_EXTRACTION_DESCRIPTOR,
    adapter_descriptor: STRUCTURED_PROVIDER_ADAPTER_DESCRIPTOR,
    runtime_domain_contract: runtimeDomainContract,
  });
}

export function productionVariantRosterId(cohort: string, language: Language): string {
  return deterministicId("production-variant-roster", { cohort_id: cohort, language });
}

function toJsonSchema(schema: z.ZodType | undefined): unknown {
  if (!schema) throw new Error("Zod schema is missing");
  return z.toJSONSchema(schema);
}

function requiredText(value: string, label: string): string {
  const normalized = value.trim();
  if (!normalized) throw new Error(`${label} must be non-empty`);
  return normalized;
}

function requiredCommit(value: string): string {
  const normalized = value.trim();
  if (!/^[0-9a-f]{40}$/.test(normalized))
    throw new Error("private prompt commit must be 40 lowercase hex characters");
  return normalized;
}

function setEqual(left: ReadonlySet<string>, right: ReadonlySet<string>): boolean {
  return left.size === right.size && [...left].every((value) => right.has(value));
}

function canonicalTextHash(value: string): string {
  return `sha256:${createHash("sha256").update(value).digest("hex")}`;
}

function deterministicId(namespace: string, value: unknown): string {
  return `${namespace}:${stripSha(canonicalHash(value))}`;
}

function stripSha(value: string): string {
  return value.replace(/^sha256:/, "");
}

function canonicalHash(value: unknown): string {
  return canonicalJsonHash(value);
}
