import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { z } from "zod";
import {
  AlphaDiscoverySchema,
  AutonomousExecutionSchema,
  CioFinalSchema,
  CioProposalSchema,
  CroSchema,
} from "../agents/decision/_schemas.js";
import { STRICT_PROVIDER_EXTRACTION_DESCRIPTOR } from "../agents/helpers/agent_run_contract.js";
import {
  canonicalJson,
  canonicalJsonHash,
  compareCanonicalStrings,
} from "../agents/helpers/canonical_json.js";
import { STRUCTURED_PROVIDER_ADAPTER_DESCRIPTOR } from "../agents/helpers/structured_provider_adapters.js";
import {
  canonicalStructuredRepairDirectiveManifest,
  STRUCTURED_REPAIR_DIRECTIVE_CONTRACT_VERSION,
} from "../agents/helpers/structured_repair_directives.js";
import {
  createMacroSubmissionSchema,
  MACRO_AGENT_IDS,
  MACRO_PROMPT_COHORT_IDS,
  MACRO_ROLE_CONTRACTS,
  renderMacroPromptBody,
} from "../agents/macro/_contracts.js";
import { renderBundledPrompt } from "../agents/prompts/bundled_prompt_renderer.js";
import { immutablePromptContractText } from "../agents/prompts/cohort_behavior.js";
import { ALL_AGENTS, type Language } from "../agents/prompts/cohorts.js";
import type { PromptReleaseExecutionBehaviorBinding } from "../agents/prompts/prompt_release_contract.js";
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
  canonicalSectorPhaseDirectiveBundle,
  type SectorStructuredPhase,
} from "../agents/sector/phase_directives.js";
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
export const EXECUTION_BEHAVIOR_RELEASE_SCHEMA_VERSION = "execution_behavior_release_manifest_v4";
export const EXECUTION_BEHAVIOR_RELEASE_CONTRACT_VERSION = "execution_behavior_release_v2";
export const STRUCTURED_PROVIDER_CONTRACT_VERSION = "structured_provider_contract_v2";
const EXECUTION_BEHAVIOR_CONTRACT_COUNT = ALL_AGENTS.length * 2;

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
const VersionHashSchema = z.string().regex(/^execution-behavior:[0-9a-f]{64}$/);

export const StructuredOutputSchemaBindingSchema = z
  .object({
    phase: z.enum(STRUCTURED_OUTPUT_SCHEMA_PHASES),
    schema_id: z.string().trim().min(1),
    schema_hash: Sha256Schema,
    immutable_phase_instruction_hash: Sha256Schema,
  })
  .strict();

const ProviderBindingSchema = z
  .object({
    provider: z.string().trim().min(1),
    model: z.string().trim().min(1),
    base_url_mode: z.enum(["PROVIDER_DEFAULT", "CONFIGURED_PRIVATE_ENDPOINT"]),
    structured_output_mode: z.literal("JSON_SCHEMA_STRICT"),
    repair_policy: z.literal("BOUNDED_SCHEMA_REPAIR_V1"),
  })
  .strict();

export const ExecutionBehaviorAgentContractSchema = z
  .object({
    execution_contract_id: z.string().regex(/^execution-contract:[0-9a-f]{64}$/),
    agent_id: z.string().trim().min(1),
    language: z.enum(["en", "zh"]),
    immutable_contract_block_hash: Sha256Schema,
    execution_behavior_version: VersionHashSchema,
    structured_output_schema_bindings: z.array(StructuredOutputSchemaBindingSchema).min(1),
    structured_output_schema_set_hash: Sha256Schema,
    structured_provider_contract_hash: Sha256Schema,
    runtime_tool_manifest_hash: Sha256Schema,
  })
  .strict();

export const ExecutionBehaviorProductionVariantSchema = z
  .object({
    production_variant_roster_id: z.string().regex(/^production-variant-roster:[0-9a-f]{64}$/),
    cohort_id: z.string().trim().min(1),
    language: z.enum(["en", "zh"]),
  })
  .strict();

const ExecutionBehaviorReleaseManifestBaseSchema = z
  .object({
    schema_version: z.literal(EXECUTION_BEHAVIOR_RELEASE_SCHEMA_VERSION),
    execution_behavior_release_id: z.string().regex(/^execution-behavior-release:[0-9a-f]{64}$/),
    execution_behavior_release_hash: Sha256Schema,
    provider_binding: ProviderBindingSchema,
    active_production_variants: z.array(ExecutionBehaviorProductionVariantSchema).length(16),
    execution_contracts: z.array(ExecutionBehaviorAgentContractSchema),
  })
  .strict();

export const ExecutionBehaviorReleaseManifestSchema =
  ExecutionBehaviorReleaseManifestBaseSchema.extend({
    execution_contracts: z
      .array(ExecutionBehaviorAgentContractSchema)
      .length(EXECUTION_BEHAVIOR_CONTRACT_COUNT),
  }).strict();

const ImmutableExecutionBehaviorReleaseManifestSchema = ExecutionBehaviorReleaseManifestBaseSchema;

export type ExecutionBehaviorReleaseManifest = z.infer<
  typeof ExecutionBehaviorReleaseManifestSchema
>;
export type ExecutionBehaviorAgentContract = z.infer<typeof ExecutionBehaviorAgentContractSchema>;

export interface BuildExecutionBehaviorReleaseInput {
  provider: string;
  model: string;
  baseUrlMode: "PROVIDER_DEFAULT" | "CONFIGURED_PRIVATE_ENDPOINT";
}

export interface WriteExecutionBehaviorReleaseArtifactsInput {
  manifest: ExecutionBehaviorReleaseManifest;
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
  const providerBinding = {
    provider: requiredText(input.provider, "provider"),
    model: requiredText(input.model, "model"),
    base_url_mode: input.baseUrlMode,
    structured_output_mode: "JSON_SCHEMA_STRICT" as const,
    repair_policy: "BOUNDED_SCHEMA_REPAIR_V1" as const,
  };
  const activeProductionVariants: z.infer<typeof ExecutionBehaviorProductionVariantSchema>[] = [];

  for (const cohort of MACRO_PROMPT_COHORT_IDS) {
    for (const language of ["en", "zh"] as const) {
      activeProductionVariants.push({
        production_variant_roster_id: productionVariantRosterId(cohort, language),
        cohort_id: cohort,
        language,
      });
    }
  }

  const sortedExecutionContracts = ALL_AGENTS.flatMap((agent) =>
    (["en", "zh"] as const).map((language) =>
      buildExecutionBehaviorAgentContract({ agent, language, providerBinding }),
    ),
  ).sort((left, right) =>
    compareCanonicalStrings(
      `${left.agent_id}:${left.language}`,
      `${right.agent_id}:${right.language}`,
    ),
  );
  const sortedProductionVariants = activeProductionVariants.sort((left, right) =>
    compareCanonicalStrings(
      `${left.cohort_id}:${left.language}`,
      `${right.cohort_id}:${right.language}`,
    ),
  );
  const releaseContent = {
    schema_version: EXECUTION_BEHAVIOR_RELEASE_SCHEMA_VERSION,
    provider_binding: providerBinding,
    active_production_variants: sortedProductionVariants,
    execution_contracts: sortedExecutionContracts,
  } as const;
  const releaseId = deterministicId("execution-behavior-release", releaseContent);
  const withId = {
    schema_version: releaseContent.schema_version,
    execution_behavior_release_id: releaseId,
    provider_binding: releaseContent.provider_binding,
    active_production_variants: releaseContent.active_production_variants,
    execution_contracts: releaseContent.execution_contracts,
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

  const contractIds = new Set<string>();
  const contractKeys = new Set<string>();
  for (const contract of manifest.execution_contracts) {
    if (contractIds.has(contract.execution_contract_id)) {
      throw new Error(`duplicate execution contract ${contract.execution_contract_id}`);
    }
    const key = `${contract.agent_id}:${contract.language}`;
    if (contractKeys.has(key)) throw new Error(`duplicate agent execution contract ${key}`);
    contractIds.add(contract.execution_contract_id);
    contractKeys.add(key);
    validateSchemaBindings(contract.agent_id, contract.structured_output_schema_bindings);
    if (
      contract.structured_output_schema_set_hash !==
      canonicalHash(contract.structured_output_schema_bindings)
    ) {
      throw new Error(`${key}: schema binding set hash mismatch`);
    }
    const currentBindings = structuredSchemaBindings(contract.agent_id, contract.language);
    if (
      canonicalJson(contract.structured_output_schema_bindings) !== canonicalJson(currentBindings)
    ) {
      throw new Error(`${key}: structured output contract drift`);
    }
    if (contract.runtime_tool_manifest_hash !== computeRuntimeToolManifestHash(contract.agent_id)) {
      throw new Error(`${key}: runtime tool contract drift`);
    }
    if (
      contract.structured_provider_contract_hash !==
      computeStructuredProviderContractHash(contract.agent_id)
    ) {
      throw new Error(`${key}: structured provider contract drift`);
    }
    if (
      contract.immutable_contract_block_hash !==
      immutablePromptContractHash(expectedPrompt(contract.agent_id, contract.language))
    ) {
      throw new Error(`${key}: immutable prompt contract drift`);
    }
    const currentExecutionVersion = computeExecutionBehaviorVersion({
      agentId: contract.agent_id,
      language: contract.language,
      providerBinding: manifest.provider_binding,
      schemaSetHash: contract.structured_output_schema_set_hash,
      structuredProviderContractHash: contract.structured_provider_contract_hash,
      runtimeToolManifestHash: contract.runtime_tool_manifest_hash,
    });
    if (contract.execution_behavior_version !== currentExecutionVersion) {
      throw new Error(`${key}: execution behavior contract drift`);
    }
    if (contract.execution_contract_id !== executionBehaviorAgentContractId(contract)) {
      throw new Error(`${key}: execution contract id mismatch`);
    }
  }
  const expectedContractKeys = new Set(
    expectedAgents.flatMap((agent) => ["en", "zh"].map((language) => `${agent}:${language}`)),
  );
  if (!setEqual(contractKeys, expectedContractKeys)) {
    throw new Error(
      `execution contracts must cover exactly ${ALL_AGENTS.length} Agents x 2 languages`,
    );
  }

  return validateExecutionBehaviorReleaseArtifactIntegrity(manifest);
}

/** Validate an immutable release artifact without comparing it with today's runtime code. */
export function validateExecutionBehaviorReleaseArtifactIntegrity(
  value: unknown,
): ExecutionBehaviorReleaseManifest {
  const manifest = ImmutableExecutionBehaviorReleaseManifestSchema.parse(value);
  const withoutHash = {
    schema_version: manifest.schema_version,
    execution_behavior_release_id: manifest.execution_behavior_release_id,
    provider_binding: manifest.provider_binding,
    active_production_variants: manifest.active_production_variants,
    execution_contracts: manifest.execution_contracts,
  };
  if (manifest.execution_behavior_release_hash !== canonicalHash(withoutHash)) {
    throw new Error("execution behavior release hash mismatch");
  }
  const releaseContent = {
    schema_version: manifest.schema_version,
    provider_binding: manifest.provider_binding,
    active_production_variants: manifest.active_production_variants,
    execution_contracts: manifest.execution_contracts,
  };
  if (
    manifest.execution_behavior_release_id !==
    deterministicId("execution-behavior-release", releaseContent)
  ) {
    throw new Error("execution behavior release id mismatch");
  }
  return manifest as ExecutionBehaviorReleaseManifest;
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

export function executionBehaviorReleaseArchiveFilename(value: unknown): string {
  const manifest = validateArchivableExecutionBehaviorReleaseArtifact(value);
  return `${manifest.execution_behavior_release_id.replace(
    /^execution-behavior-release:/,
    "",
  )}--${stripSha(manifest.execution_behavior_release_hash)}.json`;
}

export function executionBehaviorReleaseArchiveRef(value: unknown): string {
  return `registry/prompt_checks/execution_behavior_releases/${executionBehaviorReleaseArchiveFilename(value)}`;
}

/** Persist a content-addressed candidate. Prompt Release is the only production selector. */
export function writeExecutionBehaviorReleaseArtifacts(
  input: WriteExecutionBehaviorReleaseArtifactsInput,
): { archivePath: string } {
  const manifest = validateExecutionBehaviorReleaseManifest(input.manifest);
  const archiveRoot = resolve(input.archiveRoot);
  mkdirSync(archiveRoot, { recursive: true });
  const archivePath = archiveExecutionBehaviorRelease(manifest, archiveRoot);
  return { archivePath };
}

export async function loadExecutionBehaviorReleaseAtCommit(opts: {
  repo: string;
  commit: string;
  binding: PromptReleaseExecutionBehaviorBinding;
}): Promise<ExecutionBehaviorReleaseManifest> {
  const manifest = await loadExecutionBehaviorReleaseArchiveAtCommit({
    repo: opts.repo,
    commit: opts.commit,
    archiveRef: opts.binding.archive_ref,
  });
  if (
    manifest.execution_behavior_release_id !== opts.binding.release_id ||
    manifest.execution_behavior_release_hash !== opts.binding.release_hash
  ) {
    throw new Error("prompt_release_execution_behavior_binding_mismatch");
  }
  return manifest;
}

export async function loadExecutionBehaviorReleaseArchiveAtCommit(opts: {
  repo: string;
  commit: string;
  archiveRef: string;
}): Promise<ExecutionBehaviorReleaseManifest> {
  let payload: unknown;
  try {
    payload = JSON.parse((await gitShow(opts.repo, opts.commit, opts.archiveRef)).toString("utf8"));
  } catch (cause) {
    throw new Error("prompt_release_execution_behavior_archive_unavailable", { cause });
  }
  const manifest = validateExecutionBehaviorReleaseArtifactIntegrity(payload);
  if (executionBehaviorReleaseArchiveRef(manifest) !== opts.archiveRef) {
    throw new Error("prompt_release_execution_behavior_archive_ref_mismatch");
  }
  return manifest;
}

function gitShow(repo: string, commit: string, ref: string): Promise<Buffer> {
  return new Promise((resolvePromise, reject) => {
    execFile(
      "git",
      ["-C", repo, "show", `${commit}:${ref}`],
      { encoding: "buffer", maxBuffer: 64 * 1024 * 1024 },
      (error, stdout) => {
        if (error) reject(error);
        else resolvePromise(stdout);
      },
    );
  });
}

function archiveExecutionBehaviorRelease(value: unknown, archiveRoot: string): string {
  const manifest = validateArchivableExecutionBehaviorReleaseArtifact(value);
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

function validateArchivableExecutionBehaviorReleaseArtifact(
  value: unknown,
): ExecutionBehaviorReleaseManifest {
  return validateExecutionBehaviorReleaseArtifactIntegrity(value);
}

function buildExecutionBehaviorAgentContract(input: {
  agent: string;
  language: Language;
  providerBinding: ExecutionBehaviorReleaseManifest["provider_binding"];
}): ExecutionBehaviorAgentContract {
  const bindings = structuredSchemaBindings(input.agent, input.language);
  const schemaSetHash = canonicalHash(bindings);
  const runtimeToolManifestHash = computeRuntimeToolManifestHash(input.agent);
  const structuredProviderContractHash = computeStructuredProviderContractHash(input.agent);
  const executionBehaviorVersion = computeExecutionBehaviorVersion({
    agentId: input.agent,
    language: input.language,
    providerBinding: input.providerBinding,
    schemaSetHash,
    structuredProviderContractHash,
    runtimeToolManifestHash,
  });
  const body = {
    agent_id: input.agent,
    language: input.language,
    immutable_contract_block_hash: immutablePromptContractHash(
      expectedPrompt(input.agent, input.language),
    ),
    execution_behavior_version: executionBehaviorVersion,
    structured_output_schema_bindings: bindings,
    structured_output_schema_set_hash: schemaSetHash,
    structured_provider_contract_hash: structuredProviderContractHash,
    runtime_tool_manifest_hash: runtimeToolManifestHash,
  };
  return ExecutionBehaviorAgentContractSchema.parse({
    execution_contract_id: deterministicId("execution-contract", body),
    ...body,
  });
}

function executionBehaviorAgentContractId(contract: ExecutionBehaviorAgentContract): string {
  const { execution_contract_id: _executionContractId, ...body } = contract;
  return deterministicId("execution-contract", body);
}

function expectedPrompt(agent: string, language: Language): string {
  const spec = RUNTIME_AGENT_SPEC_BY_AGENT.get(agent);
  if (!spec) throw new Error(`runtime spec missing for ${agent}`);
  const body = MACRO_AGENT_IDS.includes(agent as (typeof MACRO_AGENT_IDS)[number])
    ? renderMacroPromptBody(agent as (typeof MACRO_AGENT_IDS)[number], language, "cohort_default")
    : renderBundledPrompt(agent, language, "cohort_default");
  return upsertRuntimeEvidenceContract(body, spec, language);
}

export function immutablePromptContractHash(prompt: string): string {
  return canonicalTextHash(immutablePromptContractText(prompt));
}

function structuredSchemaBindings(
  agent: string,
  language: Language,
): ExecutionBehaviorAgentContract["structured_output_schema_bindings"] {
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
  if (STANDARD_SECTOR_IDS.includes(agent)) {
    if (!isSectorStructuredPhase(phase)) {
      throw new Error(`${agent}: unsupported Sector structured phase ${phase}`);
    }
    return canonicalJson(canonicalSectorPhaseDirectiveBundle({ agentId: agent, phase, language }));
  }
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
  return canonicalJson({
    contract_version: "structured_phase_directive_bundle_v1",
    agent_id: agent,
    phase,
    primary_system_instruction: instructions[phase],
    language_instruction: languageInstruction,
    repair_contract_version: STRUCTURED_REPAIR_DIRECTIVE_CONTRACT_VERSION,
    repair_directives: canonicalStructuredRepairDirectiveManifest(),
  });
}

function isSectorStructuredPhase(
  phase: StructuredOutputSchemaPhase,
): phase is SectorStructuredPhase {
  return (
    phase === "DIRECTION_RESEARCH" || phase === "CONFLICT_REVIEW" || phase === "FINAL_SELECTION"
  );
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
  bindings: ExecutionBehaviorAgentContract["structured_output_schema_bindings"],
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
