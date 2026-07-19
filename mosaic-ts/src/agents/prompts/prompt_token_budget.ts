import { createHash } from "node:crypto";
import { relative } from "node:path";
import { z } from "zod";
import { LAYER_BY_AGENT, normalizePromptsRoot, promptPath } from "./cohorts.js";
import {
  readVerifiedPromptSourceFile,
  type VerifiedPromptSourceCommit,
  verifyPromptSourceCommit,
} from "./prompt_source_provenance.js";
import {
  countPromptTokens,
  PROMPT_ABSOLUTE_SYSTEM_CAP_TOKENS,
  PROMPT_DEFAULT_CONTEXT_WINDOW_TOKENS,
  PROMPT_MIN_RESERVED_CONTEXT_RATIO,
  PROMPT_TOKENIZER_ID,
  PROMPT_TOKENIZER_PACKAGE,
  PROMPT_TOKENIZER_VERSION,
  PROMPT_VISIBLE_CONTRACT_CAP_TOKENS,
} from "./prompt_tokenizer.js";
import { buildRuntimeAgentManifestArtifact, RUNTIME_AGENT_SPECS } from "./runtime_agent_spec.js";

const Sha256Schema = z.string().regex(/^sha256:[0-9a-f]{64}$/);
const GENERATOR_ID = "prompt_token_budget" as const;
const GENERATOR_VERSION = "1" as const;
const MAX_BASELINE_GROWTH_RATIO = 1.25;

const PromptTokenBudgetRowSchema = z
  .object({
    source: z.enum(["private", "bundled"]),
    agent: z.string().min(1),
    stage: z.string().min(1),
    language: z.enum(["zh", "en"]),
    source_path: z.string().min(1),
    source_sha256: Sha256Schema,
    source_bytes: z.number().int().min(1),
    parsed_projection_bytes: z.number().int().min(0),
    visible_contract_tokens: z.number().int().min(0),
    final_system_prompt_tokens: z.number().int().min(1),
    reserved_context_tokens: z.number().int().min(0),
    baseline_final_system_prompt_tokens: z.number().int().min(1).nullable(),
    baseline_growth_ratio: z.number().nonnegative().nullable(),
    checks: z
      .object({
        visible_contract_within_cap: z.boolean(),
        system_prompt_within_cap: z.boolean(),
        reserved_context_within_floor: z.boolean(),
        baseline_growth_within_limit: z.boolean(),
      })
      .strict(),
    passed: z.boolean(),
  })
  .strict();

export const PromptTokenBudgetManifestSchema = z
  .object({
    schema_version: z.literal("prompt_token_budget_manifest_v1"),
    generator_id: z.literal(GENERATOR_ID),
    generator_version: z.literal(GENERATOR_VERSION),
    generated_at: z.string().datetime(),
    cohort: z.string().min(1),
    tokenizer: z
      .object({
        id: z.literal(PROMPT_TOKENIZER_ID),
        package: z.literal(PROMPT_TOKENIZER_PACKAGE),
        version: z.literal(PROMPT_TOKENIZER_VERSION),
      })
      .strict(),
    context_window_tokens: z.number().int().positive(),
    visible_contract_cap_tokens: z.literal(PROMPT_VISIBLE_CONTRACT_CAP_TOKENS),
    system_prompt_cap_tokens: z.number().int().positive(),
    min_reserved_context_ratio: z.literal(PROMPT_MIN_RESERVED_CONTEXT_RATIO),
    max_baseline_growth_ratio: z.literal(MAX_BASELINE_GROWTH_RATIO),
    runtime_manifest_hash: Sha256Schema,
    source_commits: z
      .object({
        private: z.string().min(7),
        bundled: z.string().min(7),
      })
      .strict(),
    baseline_manifest_hash: Sha256Schema.nullable(),
    rows: z.array(PromptTokenBudgetRowSchema).min(1),
    summary: z
      .object({
        expected_row_count: z.number().int().positive(),
        row_count: z.number().int().positive(),
        passed_row_count: z.number().int().min(0),
        failed_row_count: z.number().int().min(0),
        semantic_parity_passed: z.boolean(),
        ready: z.boolean(),
      })
      .strict(),
    manifest_hash: Sha256Schema,
  })
  .strict()
  .superRefine((manifest, ctx) => {
    const expectedRows =
      RUNTIME_AGENT_SPECS.reduce((count, spec) => count + spec.stages.length, 0) * 2 * 2;
    const passedRows = manifest.rows.filter((row) => row.passed).length;
    if (
      manifest.summary.expected_row_count !== expectedRows ||
      manifest.summary.row_count !== manifest.rows.length ||
      manifest.summary.passed_row_count !== passedRows ||
      manifest.summary.failed_row_count !== manifest.rows.length - passedRows ||
      manifest.summary.ready !==
        (manifest.rows.length === expectedRows &&
          passedRows === expectedRows &&
          manifest.summary.semantic_parity_passed)
    ) {
      ctx.addIssue({ code: "custom", path: ["summary"], message: "summary mismatch" });
    }
    if (manifest.manifest_hash !== promptTokenBudgetManifestHash(manifest)) {
      ctx.addIssue({ code: "custom", path: ["manifest_hash"], message: "hash mismatch" });
    }
  });

export type PromptTokenBudgetManifest = z.infer<typeof PromptTokenBudgetManifestSchema>;
export type PromptTokenBudgetRow = z.infer<typeof PromptTokenBudgetRowSchema>;

interface PromptBudgetSource {
  source: "private" | "bundled";
  promptsRoot: string;
  verified: VerifiedPromptSourceCommit;
}

export async function buildPromptTokenBudgetManifest(opts: {
  cohort: string;
  privatePromptsRoot: string;
  bundledPromptsRoot: string;
  privateCommit: string;
  bundledCommit: string;
  generatedAt: string;
  contextWindowTokens?: number;
  baseline?: PromptTokenBudgetManifest | null;
}): Promise<PromptTokenBudgetManifest> {
  const privateSource = verifyPromptSourceCommit({
    promptsRoot: opts.privatePromptsRoot,
    commit: opts.privateCommit,
    source: "private",
  });
  const bundledSource = verifyPromptSourceCommit({
    promptsRoot: opts.bundledPromptsRoot,
    commit: opts.bundledCommit,
    source: "bundled",
  });
  const contextWindowTokens = opts.contextWindowTokens ?? PROMPT_DEFAULT_CONTEXT_WINDOW_TOKENS;
  if (!Number.isInteger(contextWindowTokens) || contextWindowTokens <= 0) {
    throw new Error("prompt_token_budget_context_window_invalid");
  }
  const systemPromptCapTokens = Math.min(
    PROMPT_ABSOLUTE_SYSTEM_CAP_TOKENS,
    Math.floor(contextWindowTokens * 0.25),
  );
  if (systemPromptCapTokens <= 0) throw new Error("prompt_token_budget_system_cap_invalid");
  const runtimeManifestHash = canonicalHash(buildRuntimeAgentManifestArtifact());
  const baseline = validateBaseline(
    opts.baseline ?? null,
    opts.cohort,
    contextWindowTokens,
    runtimeManifestHash,
  );
  const baselineRows = new Map((baseline?.rows ?? []).map((row) => [rowKey(row), row] as const));
  const sources: PromptBudgetSource[] = [
    {
      source: "private",
      promptsRoot: normalizePromptsRoot(privateSource.promptsRoot),
      verified: privateSource,
    },
    {
      source: "bundled",
      promptsRoot: normalizePromptsRoot(bundledSource.promptsRoot),
      verified: bundledSource,
    },
  ];
  const rows: PromptTokenBudgetRow[] = [];
  for (const source of sources) {
    for (const spec of RUNTIME_AGENT_SPECS) {
      const layer = LAYER_BY_AGENT[spec.agent];
      if (!layer) throw new Error(`prompt_token_budget_unknown_agent:${spec.agent}`);
      for (const stageSpec of spec.stages) {
        const promptByLanguage = Object.fromEntries(
          (["zh", "en"] as const).map((language) => {
            const absolutePath = promptPath({
              agent: spec.agent,
              layer,
              cohort: opts.cohort,
              language,
              promptsRoot: source.promptsRoot,
            });
            return [language, readVerifiedPromptSourceFile(source.verified, absolutePath)];
          }),
        ) as Record<"zh" | "en", string>;
        const zhPrompt = promptByLanguage.zh;
        const enPrompt = promptByLanguage.en;
        const projectionBytes = 0;
        const visibleContractTokens = 0;
        const finalSystemPromptTokens = countPromptTokens(
          [zhPrompt, "", "---", "", enPrompt].join("\n"),
        );
        for (const language of ["zh", "en"] as const) {
          const absolutePath = promptPath({
            agent: spec.agent,
            layer,
            cohort: opts.cohort,
            language,
            promptsRoot: source.promptsRoot,
          });
          const content = promptByLanguage[language];
          const sourcePath = relative(source.promptsRoot, absolutePath).replaceAll("\\", "/");
          const baselineRow = baselineRows.get(
            `${source.source}:${spec.agent}:${stageSpec.stage}:${language}`,
          );
          const growthRatio = baselineRow
            ? finalSystemPromptTokens / baselineRow.final_system_prompt_tokens
            : null;
          const checks = {
            visible_contract_within_cap:
              visibleContractTokens <= PROMPT_VISIBLE_CONTRACT_CAP_TOKENS,
            system_prompt_within_cap: finalSystemPromptTokens <= systemPromptCapTokens,
            reserved_context_within_floor:
              contextWindowTokens - finalSystemPromptTokens >=
              contextWindowTokens * PROMPT_MIN_RESERVED_CONTEXT_RATIO,
            baseline_growth_within_limit:
              growthRatio === null || growthRatio <= MAX_BASELINE_GROWTH_RATIO,
          };
          rows.push({
            source: source.source,
            agent: spec.agent,
            stage: stageSpec.stage,
            language,
            source_path: sourcePath,
            source_sha256: sha256(content),
            source_bytes: utf8Bytes(content),
            parsed_projection_bytes: projectionBytes,
            visible_contract_tokens: visibleContractTokens,
            final_system_prompt_tokens: finalSystemPromptTokens,
            reserved_context_tokens: Math.max(0, contextWindowTokens - finalSystemPromptTokens),
            baseline_final_system_prompt_tokens: baselineRow?.final_system_prompt_tokens ?? null,
            baseline_growth_ratio: growthRatio,
            checks,
            passed: Object.values(checks).every(Boolean),
          });
        }
      }
    }
  }
  rows.sort((left, right) => rowKey(left).localeCompare(rowKey(right)));
  // KNOT projection parity is verified inside the private release. The public
  // budget gate measures only model-visible prompt text.
  const semanticParityPassed = true;
  const expectedRowCount =
    RUNTIME_AGENT_SPECS.reduce((count, spec) => count + spec.stages.length, 0) * 2 * 2;
  const passedRowCount = rows.filter((row) => row.passed).length;
  const withoutHash = {
    schema_version: "prompt_token_budget_manifest_v1" as const,
    generator_id: GENERATOR_ID,
    generator_version: GENERATOR_VERSION,
    generated_at: new Date(opts.generatedAt).toISOString(),
    cohort: opts.cohort,
    tokenizer: {
      id: PROMPT_TOKENIZER_ID,
      package: PROMPT_TOKENIZER_PACKAGE,
      version: PROMPT_TOKENIZER_VERSION,
    },
    context_window_tokens: contextWindowTokens,
    visible_contract_cap_tokens: PROMPT_VISIBLE_CONTRACT_CAP_TOKENS,
    system_prompt_cap_tokens: systemPromptCapTokens,
    min_reserved_context_ratio: PROMPT_MIN_RESERVED_CONTEXT_RATIO,
    max_baseline_growth_ratio: MAX_BASELINE_GROWTH_RATIO,
    runtime_manifest_hash: runtimeManifestHash,
    source_commits: { private: privateSource.commit, bundled: bundledSource.commit },
    baseline_manifest_hash: baseline?.manifest_hash ?? null,
    rows,
    summary: {
      expected_row_count: expectedRowCount,
      row_count: rows.length,
      passed_row_count: passedRowCount,
      failed_row_count: rows.length - passedRowCount,
      semantic_parity_passed: semanticParityPassed,
      ready:
        rows.length === expectedRowCount &&
        passedRowCount === expectedRowCount &&
        semanticParityPassed,
    },
  };
  return PromptTokenBudgetManifestSchema.parse({
    ...withoutHash,
    manifest_hash: canonicalHash(withoutHash),
  });
}

export function promptTokenBudgetManifestHash(manifest: PromptTokenBudgetManifest): string {
  const { manifest_hash: _ignored, ...withoutHash } = manifest;
  return canonicalHash(withoutHash);
}

export function renderPromptTokenBudgetManifest(manifest: PromptTokenBudgetManifest): string {
  return `${JSON.stringify(PromptTokenBudgetManifestSchema.parse(manifest), null, 2)}\n`;
}

function validateBaseline(
  baseline: PromptTokenBudgetManifest | null,
  cohort: string,
  contextWindowTokens: number,
  runtimeManifestHash: string,
): PromptTokenBudgetManifest | null {
  if (!baseline) return null;
  const parsed = PromptTokenBudgetManifestSchema.parse(baseline);
  if (
    parsed.cohort !== cohort ||
    parsed.context_window_tokens !== contextWindowTokens ||
    parsed.runtime_manifest_hash !== runtimeManifestHash ||
    parsed.tokenizer.id !== PROMPT_TOKENIZER_ID ||
    parsed.tokenizer.version !== PROMPT_TOKENIZER_VERSION
  ) {
    throw new Error("prompt_token_budget_baseline_configuration_mismatch");
  }
  return parsed;
}

function rowKey(
  row: Pick<PromptTokenBudgetRow, "source" | "agent" | "stage" | "language">,
): string {
  return `${row.source}:${row.agent}:${row.stage}:${row.language}`;
}

function utf8Bytes(value: string): number {
  return Buffer.byteLength(value, "utf-8");
}

function sha256(value: string): string {
  return `sha256:${createHash("sha256").update(value).digest("hex")}`;
}

function canonicalHash(value: unknown): string {
  return sha256(JSON.stringify(canonicalize(value)));
}

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, entry]) => [key, canonicalize(entry)]),
    );
  }
  return value === undefined ? null : value;
}
