import { appendFileSync, mkdirSync } from "node:fs";
import { basename, dirname, resolve } from "node:path";
import type { BaseChatModel } from "@langchain/core/language_models/chat_models";
import { HumanMessage, SystemMessage } from "@langchain/core/messages";
import { z } from "zod";
import { canonicalJsonHash } from "./canonical_json.js";
import { extractLlmTokenUsage } from "./runtime.js";
import {
  adaptStrictProviderJsonSchema,
  normalizeStrictProviderPayload,
} from "./structured_provider_adapters.js";

export const MAX_AGENT_REPAIRS = 3;

export type AgentRunStatus = "accepted" | "accepted_empty" | "rejected" | "timeout" | "error";
export type AgentOutputSource = "structured_primary" | "structured_repair" | "none";

export interface AgentContractIssue {
  validator: string;
  reason_code: string;
  json_path: string;
  message: string;
}

export interface AgentAttemptAudit {
  attempt: number;
  kind: "primary" | "repair";
  accepted: boolean;
  validation_issues: AgentContractIssue[];
  error_fingerprints: string[];
  output_hash: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  elapsed_ms: number;
}

export interface AgentRunAudit {
  schema_version: "agent_run_audit_v1";
  run_id: string;
  agent: string;
  stage: string;
  status: AgentRunStatus;
  output_source: AgentOutputSource;
  attempt_count: number;
  repair_count: number;
  stop_reason:
    | "accepted"
    | "accepted_empty"
    | "repair_budget_exhausted"
    | "duplicate_output"
    | "no_error_improvement"
    | "structured_output_unsupported"
    | "timeout"
    | "connection_error"
    | "model_service_error"
    | "private_policy_failure"
    | "evidence_contract_failure";
  reason_codes: string[];
  prompt_hash: string;
  schema_hash: string;
  evidence_hash: string;
  output_hash: string | null;
  attempts: AgentAttemptAudit[];
}

export interface ContractValidationResult<T> {
  output: T;
  issues: AgentContractIssue[];
}

export interface StrictStructuredRunOptions<T> {
  llm: BaseChatModel;
  schema: z.ZodType<T>;
  messages: [SystemMessage, HumanMessage];
  agent: string;
  stage: string;
  runId: string;
  evidenceSnapshot: unknown;
  validate?: (output: T) => ContractValidationResult<T> | Promise<ContractValidationResult<T>>;
  isAcceptedEmpty?: (output: T) => boolean;
  signal?: AbortSignal;
  maxRepairs?: number;
  onAttempt?: (audit: AgentAttemptAudit, rawOutput: unknown) => void | Promise<void>;
}

export class AgentRunContractError extends Error {
  readonly audit: AgentRunAudit;

  constructor(message: string, audit: AgentRunAudit, cause?: unknown) {
    super(message, cause === undefined ? undefined : { cause });
    this.name = "AgentRunContractError";
    this.audit = audit;
  }
}

export async function assertStructuredOutputCapability(llm: BaseChatModel): Promise<void> {
  try {
    const preflightSchema = z.object({ preflight: z.literal("ok") });
    // biome-ignore lint/suspicious/noExplicitAny: provider-specific LangChain surface.
    const bound = (llm as any).withStructuredOutput(providerJsonSchema(preflightSchema), {
      includeRaw: true,
      name: "mosaic_structured_output_preflight",
      method: "jsonSchema",
      strict: true,
    });
    if (!bound || typeof bound.invoke !== "function") throw new Error("invalid structured binding");
    const response = await bound.invoke([
      new SystemMessage("Return the structured-output preflight object exactly as requested."),
      new HumanMessage('Set preflight to "ok".'),
    ]);
    const parsed = preflightSchema.safeParse(structuredEnvelope(response).parsed);
    if (!parsed.success)
      throw new Error("provider returned an invalid structured preflight object");
  } catch (cause) {
    throw new Error(
      `structured-output capability preflight failed: ${cause instanceof Error ? cause.message : String(cause)}`,
      { cause },
    );
  }
}

export async function invokeStrictStructured<T>(
  opts: StrictStructuredRunOptions<T>,
): Promise<{ output: T; audit: AgentRunAudit }> {
  const maxRepairs = opts.maxRepairs ?? MAX_AGENT_REPAIRS;
  const hashes = {
    prompt_hash: canonicalHash(opts.messages.map((message) => message.content)),
    schema_hash: canonicalHash(safeJsonSchema(opts.schema)),
    evidence_hash: canonicalHash(projectEvidenceSnapshotForHash(opts.evidenceSnapshot ?? null)),
  };
  let strictProviderSchema: unknown;
  try {
    strictProviderSchema = providerJsonSchema(opts.schema, opts.evidenceSnapshot);
  } catch (cause) {
    if (cause instanceof ProviderRuntimeBindingError) {
      const audit = failedAudit(opts, hashes, [], "error", "evidence_contract_failure", [
        cause.reasonCode,
      ]);
      throw new AgentRunContractError(
        `${opts.agent}/${opts.stage}: ${cause.reasonCode}`,
        audit,
        cause,
      );
    }
    throw cause;
  }
  let bound: { invoke: (input: unknown, options?: { signal?: AbortSignal }) => Promise<unknown> };
  try {
    // biome-ignore lint/suspicious/noExplicitAny: LangChain providers expose different generic signatures.
    bound = (opts.llm as any).withStructuredOutput(strictProviderSchema, {
      includeRaw: true,
      method: "jsonSchema",
      strict: true,
      name: `${opts.agent}_${opts.stage}`.replace(/[^A-Za-z0-9_-]/g, "_"),
    });
  } catch (cause) {
    const audit = failedAudit(opts, hashes, [], "error", "structured_output_unsupported", [
      "STRUCTURED_OUTPUT_UNSUPPORTED",
    ]);
    throw new AgentRunContractError(
      `${opts.agent}/${opts.stage}: structured output is not supported`,
      audit,
      cause,
    );
  }

  const attempts: AgentAttemptAudit[] = [];
  const repairEvidenceCatalog = extractRepairEvidenceCatalog(opts.evidenceSnapshot);
  const cumulativeIssues: AgentContractIssue[] = [];
  let previousOutputHash: string | null = null;
  let previousFingerprints = new Set<string>();
  let noImprovementCount = 0;
  let previousProviderRaw: unknown = null;

  for (let attempt = 0; attempt <= maxRepairs; attempt += 1) {
    const startedAt = Date.now();
    const kind = attempt === 0 ? "primary" : "repair";
    const input =
      attempt === 0
        ? opts.messages
        : buildRepairMessages({
            attempt,
            providerSchema: strictProviderSchema,
            originalMessages: opts.messages,
            originalOutput: previousProviderRaw,
            cumulativeIssues,
            evidenceHash: hashes.evidence_hash,
            repairEvidenceCatalog,
          });
    let raw: unknown = null;
    let providerRaw: unknown = null;
    let promptTokens = 0;
    let completionTokens = 0;
    let issues: AgentContractIssue[] = [];
    let candidate: T | null = null;
    try {
      const response = await bound.invoke(input, opts.signal ? { signal: opts.signal } : undefined);
      const envelope = structuredEnvelope(response);
      providerRaw = envelope.parsed;
      raw = normalizeStrictProviderPayload(providerRaw);
      const usage = extractLlmTokenUsage(envelope.raw);
      promptTokens = usage.promptTokens;
      completionTokens = usage.completionTokens;
      const parsed = opts.schema.safeParse(raw);
      if (!parsed.success) {
        issues = zodIssues(parsed.error);
      } else {
        const validated = opts.validate
          ? await opts.validate(parsed.data)
          : { output: parsed.data, issues: [] };
        candidate = validated.output;
        issues = normalizeIssues(validated.issues);
      }
    } catch (cause) {
      const failure = classifyOperationalFailure(cause, opts.signal);
      if (failure) {
        const failureIssue: AgentContractIssue = {
          validator: "model_runtime",
          reason_code: failure.reasonCode,
          json_path: "$",
          message: cause instanceof Error ? cause.message : String(cause),
        };
        const attemptAudit: AgentAttemptAudit = {
          attempt: attempt + 1,
          kind,
          accepted: false,
          validation_issues: [failureIssue],
          error_fingerprints: [issueFingerprint(failureIssue)],
          output_hash: null,
          prompt_tokens: promptTokens,
          completion_tokens: completionTokens,
          elapsed_ms: Date.now() - startedAt,
        };
        attempts.push(attemptAudit);
        if (opts.onAttempt) await opts.onAttempt(attemptAudit, null);
        else persistPrivateAttemptTelemetry(opts, attemptAudit, null);
        const audit = failedAudit(opts, hashes, attempts, failure.status, failure.stopReason, [
          failure.reasonCode,
        ]);
        throw new AgentRunContractError(
          `${opts.agent}/${opts.stage}: ${failure.reasonCode}`,
          audit,
          cause,
        );
      }
      issues = exceptionIssues(cause);
    }

    const outputHash = raw === null ? null : canonicalHash(raw);
    const fingerprints = new Set(issues.map(issueFingerprint));
    const attemptAudit: AgentAttemptAudit = {
      attempt: attempt + 1,
      kind,
      accepted: issues.length === 0 && candidate !== null,
      validation_issues: issues,
      error_fingerprints: [...fingerprints].sort(),
      output_hash: outputHash,
      prompt_tokens: promptTokens,
      completion_tokens: completionTokens,
      elapsed_ms: Date.now() - startedAt,
    };
    attempts.push(attemptAudit);
    if (opts.onAttempt) await opts.onAttempt(attemptAudit, raw);
    else persistPrivateAttemptTelemetry(opts, attemptAudit, raw);

    const privatePolicyIssues = issues.filter(
      (issue) => issue.validator === "private_knot_runtime_v1",
    );
    if (privatePolicyIssues.length > 0) {
      const reasonCodes = [
        ...new Set(privatePolicyIssues.map((issue) => issue.reason_code)),
      ].sort();
      throw new AgentRunContractError(
        `${opts.agent}/${opts.stage}: private KNOT policy failed: ${reasonCodes.join(",")}`,
        failedAudit(opts, hashes, attempts, "error", "private_policy_failure", reasonCodes),
      );
    }

    if (attemptAudit.accepted && candidate !== null) {
      const acceptedEmpty = opts.isAcceptedEmpty?.(candidate) ?? false;
      return {
        output: candidate,
        audit: {
          schema_version: "agent_run_audit_v1",
          run_id: opts.runId,
          agent: opts.agent,
          stage: opts.stage,
          status: acceptedEmpty ? "accepted_empty" : "accepted",
          output_source: attempt === 0 ? "structured_primary" : "structured_repair",
          attempt_count: attempts.length,
          repair_count: attempt,
          stop_reason: acceptedEmpty ? "accepted_empty" : "accepted",
          reason_codes: [],
          ...hashes,
          output_hash: canonicalHash(candidate),
          attempts,
        },
      };
    }

    cumulativeIssues.push(...issues);
    if (attempt > 0 && outputHash !== null && outputHash === previousOutputHash) {
      throw rejectedError(opts, hashes, attempts, "duplicate_output");
    }
    if (attempt > 0) {
      const removedPreviousError = [...previousFingerprints].some(
        (fingerprint) => !fingerprints.has(fingerprint),
      );
      noImprovementCount = removedPreviousError ? 0 : noImprovementCount + 1;
      if (noImprovementCount >= 2) {
        throw rejectedError(opts, hashes, attempts, "no_error_improvement");
      }
    }
    previousOutputHash = outputHash;
    previousFingerprints = fingerprints;
    previousProviderRaw = providerRaw;
  }

  throw rejectedError(opts, hashes, attempts, "repair_budget_exhausted");
}

function persistPrivateAttemptTelemetry<T>(
  opts: StrictStructuredRunOptions<T>,
  audit: AgentAttemptAudit,
  rawOutput: unknown,
): void {
  if (process.env.MOSAIC_AGENT_RAW_TELEMETRY === "off") return;
  const cwd = process.cwd();
  const repoRoot = basename(cwd) === "mosaic-ts" ? dirname(cwd) : cwd;
  const root = resolve(
    process.env.MOSAIC_AGENT_TELEMETRY_DIR ?? resolve(repoRoot, ".mosaic", "agent_run_telemetry"),
  );
  mkdirSync(root, { recursive: true });
  const file = resolve(root, `${sanitize(opts.runId)}.jsonl`);
  appendFileSync(
    file,
    `${JSON.stringify({
      schema_version: "agent_attempt_private_telemetry_v1",
      run_id: opts.runId,
      agent: opts.agent,
      stage: opts.stage,
      audit,
      raw_output: rawOutput,
    })}\n`,
    { encoding: "utf8", mode: 0o600 },
  );
}

function sanitize(value: string): string {
  return value.replace(/[^A-Za-z0-9_.-]/g, "_").slice(0, 160) || "unknown_run";
}

function buildRepairMessages(input: {
  attempt: number;
  providerSchema: unknown;
  originalMessages: [SystemMessage, HumanMessage];
  originalOutput: unknown;
  cumulativeIssues: AgentContractIssue[];
  evidenceHash: string;
  repairEvidenceCatalog: RepairEvidenceCatalog;
}): [SystemMessage, HumanMessage] {
  const issuePayload = dedupeIssues(input.cumulativeIssues);
  const contract = input.providerSchema;
  const originalSystem = input.originalMessages[0].content;
  const originalUser = input.originalMessages[1].content;
  if (input.attempt === 1) {
    return [
      new SystemMessage(
        [
          "Structured repair 1/3. Correct the complete prior object directly. Return a complete object; do not omit disposition fields or add prose. Copy exact evidence_id and opaque permitted citation identifiers from the immutable catalog: every claim needs evidence_ids, and every INTERPRETATION also needs research_rule_refs. Do not repeat invalid text: remove numeric facts including spelled-out numbers, and shorten dangling narrative to a complete phrase well below its limit.",
          "Original system contract remains binding:",
          String(originalSystem),
        ].join("\n\n"),
      ),
      new HumanMessage(
        JSON.stringify({
          immutable_evidence_hash: input.evidenceHash,
          ...input.repairEvidenceCatalog,
          original_evidence_and_task: originalUser,
          prior_output: input.originalOutput,
          validation_errors: issuePayload,
        }),
      ),
    ];
  }
  if (input.attempt === 2) {
    return [
      new SystemMessage(
        [
          "Structured repair 2/3. Regenerate one complete object from the original immutable evidence. Satisfy every machine constraint and all cumulative errors. Use only exact catalog ids; all claims require evidence_ids and INTERPRETATION claims require research_rule_refs. Remove numeric facts including spelled-out numbers, and keep every narrative phrase complete and comfortably below its limit.",
          "Original system contract remains binding:",
          String(originalSystem),
        ].join("\n\n"),
      ),
      new HumanMessage(
        JSON.stringify({
          immutable_evidence_hash: input.evidenceHash,
          ...input.repairEvidenceCatalog,
          original_evidence_and_task: originalUser,
          cumulative_validation_errors: issuePayload,
          complete_json_schema: contract,
        }),
      ),
    ];
  }
  return [
    new SystemMessage(
      [
        "FINAL structured repair 3/3. Rebuild the complete object under the strict contract. Use only exact catalog ids; all claims require evidence_ids and INTERPRETATION claims require research_rule_refs. Remove numeric facts including spelled-out numbers, and keep every narrative phrase complete and comfortably below its limit. You may choose an explicitly supported empty disposition, but disposition and conclusion references are mandatory. Return no prose.",
        "Original system contract remains binding:",
        String(originalSystem),
      ].join("\n\n"),
    ),
    new HumanMessage(
      JSON.stringify({
        immutable_evidence_hash: input.evidenceHash,
        ...input.repairEvidenceCatalog,
        original_evidence_and_task: originalUser,
        normalized_errors: issuePayload.map(({ validator, reason_code, json_path }) => ({
          validator,
          reason_code,
          json_path,
        })),
        complete_json_schema: contract,
      }),
    ),
  ];
}

interface RepairEvidenceCatalog {
  allowed_evidence_ids: string[];
  allowed_citation_ids: string[];
  required_preferred_evidence_ids: string[];
  required_least_evidence_ids: string[];
  required_final_evidence_ids: string[];
}

function extractRepairEvidenceCatalog(snapshot: unknown): RepairEvidenceCatalog {
  if (snapshot === null || typeof snapshot !== "object" || Array.isArray(snapshot)) {
    return {
      allowed_evidence_ids: [],
      allowed_citation_ids: [],
      required_preferred_evidence_ids: [],
      required_least_evidence_ids: [],
      required_final_evidence_ids: [],
    };
  }
  const record = snapshot as Record<string, unknown>;
  const evidenceLedger = Array.isArray(record.evidenceLedger) ? record.evidenceLedger : [];
  const allowedEvidenceIds = evidenceLedger
    .flatMap((entry) => {
      if (entry === null || typeof entry !== "object" || Array.isArray(entry)) return [];
      const evidenceId = (entry as Record<string, unknown>).evidence_id;
      return typeof evidenceId === "string" ? [evidenceId] : [];
    })
    .sort();
  const ruleSource = record.allowedResearchRuleIds;
  const allowedResearchRuleIds =
    ruleSource instanceof Set
      ? [...ruleSource].filter((ruleId): ruleId is string => typeof ruleId === "string").sort()
      : Array.isArray(ruleSource)
        ? ruleSource.filter((ruleId): ruleId is string => typeof ruleId === "string").sort()
        : [];
  const directive =
    record.directive !== null &&
    typeof record.directive === "object" &&
    !Array.isArray(record.directive)
      ? (record.directive as Record<string, unknown>)
      : null;
  const directiveEvidence = (field: string): string[] => {
    const values = directive?.[field];
    return Array.isArray(values)
      ? [...new Set(values.filter((value): value is string => typeof value === "string"))].sort()
      : [];
  };
  return {
    allowed_evidence_ids: [...new Set(allowedEvidenceIds)],
    allowed_citation_ids: [...new Set(allowedResearchRuleIds)],
    required_preferred_evidence_ids: directiveEvidence("required_preferred_evidence_ids"),
    required_least_evidence_ids: directiveEvidence("required_least_preferred_evidence_ids"),
    required_final_evidence_ids: directiveEvidence("required_final_evidence_ids"),
  };
}

function zodIssues(error: z.ZodError): AgentContractIssue[] {
  return normalizeIssues(
    error.issues.map((issue) => ({
      validator: "zod_schema",
      reason_code: `ZOD_${issue.code.toUpperCase()}`,
      json_path: jsonPath(issue.path),
      message: issue.message,
    })),
  );
}

function exceptionIssues(cause: unknown): AgentContractIssue[] {
  if (cause instanceof z.ZodError) return zodIssues(cause);
  return [
    {
      validator: "structured_output",
      reason_code: "STRUCTURED_OUTPUT_INVALID",
      json_path: "$",
      message: cause instanceof Error ? cause.message : String(cause),
    },
  ];
}

function normalizeIssues(issues: ReadonlyArray<AgentContractIssue>): AgentContractIssue[] {
  return dedupeIssues(
    issues.map((issue) => ({
      validator: issue.validator.trim() || "unknown_validator",
      reason_code: issue.reason_code.trim() || "UNKNOWN_REASON",
      json_path: issue.json_path.trim() || "$",
      message: issue.message.trim() || issue.reason_code,
    })),
  );
}

function dedupeIssues(issues: ReadonlyArray<AgentContractIssue>): AgentContractIssue[] {
  const seen = new Set<string>();
  return issues.filter((issue) => {
    const fingerprint = issueFingerprint(issue);
    if (seen.has(fingerprint)) return false;
    seen.add(fingerprint);
    return true;
  });
}

function issueFingerprint(issue: AgentContractIssue): string {
  return `${issue.validator}:${issue.reason_code}:${issue.json_path}`;
}

function jsonPath(path: PropertyKey[]): string {
  if (path.length === 0) return "$";
  return `$${path.map((part) => (typeof part === "number" ? `[${part}]` : `.${String(part)}`)).join("")}`;
}

function rejectedError<T>(
  opts: StrictStructuredRunOptions<T>,
  hashes: Pick<AgentRunAudit, "prompt_hash" | "schema_hash" | "evidence_hash">,
  attempts: AgentAttemptAudit[],
  stopReason: "repair_budget_exhausted" | "duplicate_output" | "no_error_improvement",
): AgentRunContractError {
  const reasonCodes = [
    ...new Set(
      attempts.flatMap((attempt) => attempt.validation_issues.map((issue) => issue.reason_code)),
    ),
  ].sort();
  const audit = failedAudit(opts, hashes, attempts, "rejected", stopReason, reasonCodes);
  const reasonSummary = reasonCodes.length > 0 ? `: ${reasonCodes.join(",")}` : "";
  return new AgentRunContractError(
    `${opts.agent}/${opts.stage}: rejected after ${attempts.length} attempts (${stopReason})${reasonSummary}`,
    audit,
  );
}

function failedAudit<T>(
  opts: StrictStructuredRunOptions<T>,
  hashes: Pick<AgentRunAudit, "prompt_hash" | "schema_hash" | "evidence_hash">,
  attempts: AgentAttemptAudit[],
  status: "rejected" | "timeout" | "error",
  stopReason: AgentRunAudit["stop_reason"],
  reasonCodes: string[],
): AgentRunAudit {
  return {
    schema_version: "agent_run_audit_v1",
    run_id: opts.runId,
    agent: opts.agent,
    stage: opts.stage,
    status,
    output_source: "none",
    attempt_count: attempts.length,
    repair_count: Math.max(0, attempts.length - 1),
    stop_reason: stopReason,
    reason_codes: reasonCodes,
    ...hashes,
    output_hash: attempts.at(-1)?.output_hash ?? null,
    attempts,
  };
}

function classifyOperationalFailure(
  cause: unknown,
  signal?: AbortSignal,
): {
  status: "timeout" | "error";
  stopReason: "timeout" | "connection_error" | "model_service_error";
  reasonCode: string;
} | null {
  const message = cause instanceof Error ? `${cause.name}:${cause.message}`.toLowerCase() : "";
  if (signal?.aborted || /abort|timed?\s*out|timeout/.test(message)) {
    return { status: "timeout", stopReason: "timeout", reasonCode: "MODEL_TIMEOUT" };
  }
  if (/econn|connect|socket|network|fetch failed|dns|enotfound/.test(message)) {
    return {
      status: "error",
      stopReason: "connection_error",
      reasonCode: "MODEL_CONNECTION_ERROR",
    };
  }
  if (
    /bad request|too many requests|rate limit|internal server error|bad gateway|service unavailable|gateway timeout|overloaded/.test(
      message,
    ) ||
    /\b(?:http(?: status)?|status(?: code)?|response)\s*[:=]?\s*(?:400|429|500|502|503|504)\b/.test(
      message,
    )
  ) {
    return {
      status: "error",
      stopReason: "model_service_error",
      reasonCode: "MODEL_SERVICE_ERROR",
    };
  }
  return null;
}

function structuredEnvelope(value: unknown): { raw?: unknown; parsed: unknown } {
  if (value !== null && typeof value === "object" && "parsed" in value) {
    const envelope = value as { raw?: unknown; parsed: unknown };
    return { raw: envelope.raw, parsed: envelope.parsed };
  }
  return { parsed: value };
}

function safeJsonSchema<T>(schema: z.ZodType<T>): unknown {
  try {
    return z.toJSONSchema(schema);
  } catch {
    return { unavailable: true };
  }
}

function providerJsonSchema<T>(schema: z.ZodType<T>, evidenceSnapshot?: unknown): unknown {
  const providerSchema = omitUnsupportedProviderKeywords(
    applyProviderExtractionBounds(
      adaptStrictProviderJsonSchema(omitUnsupportedProviderKeywords(safeJsonSchema(schema))),
    ),
  );
  return bindProviderRuntimeCatalog(providerSchema, extractRepairEvidenceCatalog(evidenceSnapshot));
}

const PROVIDER_ARRAY_CAPS: Readonly<Record<string, number>> = {
  evidence_ids: 1,
  research_rule_refs: 1,
  claim_refs: 1,
  claim_refs_used: 1,
  claims: 2,
  channels: 1,
  key_drivers: 1,
  risks: 1,
  long_picks: 2,
  short_or_avoid_picks: 2,
  picks: 2,
};

export const STRICT_PROVIDER_EXTRACTION_DESCRIPTOR = Object.freeze({
  contract_version: "strict_provider_extraction_bounds_v3",
  array_caps: PROVIDER_ARRAY_CAPS,
  implicit_string_max_length: 320,
  implicit_open_object_max_properties: 12,
  tuple_policy: "EXACT_PREFIX_ITEMS_LENGTH_V1",
  component_claim_policy: "EXACT_ONE_INDEPENDENT_CLAIM_PER_COMPONENT_V1",
  runtime_catalog_binding:
    "ALL_COMPACT_CONTRACTS_EXACT_EVIDENCE_LEGS_AND_PERMITTED_CITATION_ENUM_V3",
  claim_kind_binding:
    "PRIMARY_COMPACT_CLAIMS_EXCLUDE_RISK_FLAG_AND_REQUIRE_CITATION_FOR_INTERPRETATION_V3",
  macro_optional_numeric_echo: "COMPACT_EXTRACTION_OMITS_OPTIONAL_NUMERIC_ECHO_V1",
});

class ProviderRuntimeBindingError extends Error {
  constructor(
    readonly reasonCode: "MACRO_RUNTIME_EVIDENCE_CATALOG_EMPTY" | "RUNTIME_EVIDENCE_CATALOG_EMPTY",
  ) {
    super(reasonCode);
    this.name = "ProviderRuntimeBindingError";
  }
}

const COMPACT_PROVIDER_CONTRACTS = new Set([
  "MACRO_COMPONENTS_COMPACT_V1",
  "MACRO_DIRECT_COMPACT_V1",
  "SECTOR_DIRECTION_RESEARCH_COMPACT_V3",
  "SECTOR_CONFLICT_REVIEW_COMPACT_V4",
  "SECTOR_SELECTED_COMPACT_V2",
  "RELATIONSHIP_MAPPER_COMPACT_V2",
  "SUPERINVESTOR_ABSTENTION_COMPACT_V2",
]);

function bindProviderRuntimeCatalog(value: unknown, catalog: RepairEvidenceCatalog): unknown {
  return bind(value, null);

  function bind(nested: unknown, activeContract: string | null, propertyName?: string): unknown {
    if (activeContract && propertyName === "evidence_id") {
      return { type: "string", enum: catalog.allowed_evidence_ids };
    }
    if (activeContract === "SECTOR_SELECTED_COMPACT_V2") {
      const requiredEvidenceByProperty: Readonly<Record<string, string[]>> = {
        preferred_evidence_ids: catalog.required_preferred_evidence_ids,
        least_preferred_evidence_ids: catalog.required_least_evidence_ids,
        final_evidence_ids: catalog.required_final_evidence_ids,
      };
      const exactEvidence = propertyName ? requiredEvidenceByProperty[propertyName] : undefined;
      if (exactEvidence) return exactStringTupleSchema(exactEvidence);
    }
    if (activeContract && propertyName === "research_rule_ref") {
      return catalog.allowed_citation_ids.length === 0
        ? { type: "null" }
        : {
            anyOf: [{ type: "null" }, { type: "string", enum: catalog.allowed_citation_ids }],
          };
    }
    if (
      activeContract &&
      propertyName === "claim_kind" &&
      catalog.allowed_citation_ids.length === 0
    ) {
      return { type: "string", enum: ["FACT", "EVENT"] };
    }
    if (Array.isArray(nested)) return nested.map((item) => bind(item, activeContract));
    if (nested === null || typeof nested !== "object") return nested;
    const record = nested as Record<string, unknown>;
    const properties =
      record.properties !== null &&
      typeof record.properties === "object" &&
      !Array.isArray(record.properties)
        ? (record.properties as Record<string, unknown>)
        : null;
    const providerContract = properties?.provider_contract;
    const providerContractConst =
      providerContract !== null &&
      typeof providerContract === "object" &&
      !Array.isArray(providerContract)
        ? (providerContract as Record<string, unknown>).const
        : null;
    const contract =
      activeContract ??
      (typeof providerContractConst === "string" &&
      COMPACT_PROVIDER_CONTRACTS.has(providerContractConst)
        ? providerContractConst
        : null);
    if (!activeContract && contract && catalog.allowed_evidence_ids.length === 0) {
      throw new ProviderRuntimeBindingError(
        providerContractConst === "MACRO_COMPONENTS_COMPACT_V1" ||
          providerContractConst === "MACRO_DIRECT_COMPACT_V1"
          ? "MACRO_RUNTIME_EVIDENCE_CATALOG_EMPTY"
          : "RUNTIME_EVIDENCE_CATALOG_EMPTY",
      );
    }
    return Object.fromEntries(
      Object.entries(record).map(([key, item]) => {
        if (
          key !== "properties" ||
          item === null ||
          typeof item !== "object" ||
          Array.isArray(item)
        ) {
          return [key, bind(item, contract)];
        }
        return [
          key,
          Object.fromEntries(
            Object.entries(item as Record<string, unknown>).map(([property, schema]) => [
              property,
              bind(schema, contract, property),
            ]),
          ),
        ];
      }),
    );
  }
}

function exactStringTupleSchema(values: readonly string[]): Record<string, unknown> {
  return {
    type: "array",
    prefixItems: values.map((value) => ({ type: "string", const: value })),
    items: false,
    minItems: values.length,
    maxItems: values.length,
  };
}

function applyProviderExtractionBounds(value: unknown, fieldName?: string): unknown {
  if (Array.isArray(value)) {
    return value.map((nested) => applyProviderExtractionBounds(nested, fieldName));
  }
  if (value === null || typeof value !== "object") return value;
  const record = value as Record<string, unknown>;
  const bounded = Object.fromEntries(
    Object.entries(record).map(([key, nested]) => {
      if (key === "properties" && nested !== null && typeof nested === "object") {
        return [
          key,
          Object.fromEntries(
            Object.entries(nested as Record<string, unknown>).map(([property, schema]) => [
              property,
              applyProviderExtractionBounds(schema, property),
            ]),
          ),
        ];
      }
      return [key, applyProviderExtractionBounds(nested, fieldName)];
    }),
  );
  const cap = fieldName ? PROVIDER_ARRAY_CAPS[fieldName] : undefined;
  if (bounded.type === "array" && Array.isArray(bounded.prefixItems)) {
    bounded.items = false;
    bounded.minItems = bounded.prefixItems.length;
    bounded.maxItems = bounded.prefixItems.length;
  }
  if (bounded.type === "array" && cap !== undefined) {
    const existing = typeof bounded.maxItems === "number" ? bounded.maxItems : cap;
    const minimum = typeof bounded.minItems === "number" ? bounded.minItems : 0;
    bounded.maxItems = Math.max(minimum, Math.min(existing, cap));
  }
  if (bounded.type === "string" && typeof bounded.maxLength !== "number") {
    bounded.maxLength = 320;
  }
  if (
    bounded.type === "object" &&
    bounded.additionalProperties !== undefined &&
    bounded.additionalProperties !== false &&
    typeof bounded.maxProperties !== "number"
  ) {
    bounded.maxProperties = 12;
  }
  if (
    bounded.type === "object" &&
    bounded.properties !== null &&
    typeof bounded.properties === "object" &&
    !Array.isArray(bounded.properties)
  ) {
    const properties = bounded.properties as Record<string, unknown>;
    const sourceProperties =
      record.properties !== null &&
      typeof record.properties === "object" &&
      !Array.isArray(record.properties)
        ? (record.properties as Record<string, unknown>)
        : {};
    if (properties.components && properties.claims) {
      const sourceClaims = sourceProperties.claims;
      const sourceComponents = sourceProperties.components;
      const sourceClaimLimit =
        sourceClaims !== null && typeof sourceClaims === "object"
          ? (sourceClaims as Record<string, unknown>).maxItems
          : undefined;
      const componentLimit =
        sourceComponents !== null && typeof sourceComponents === "object"
          ? (sourceComponents as Record<string, unknown>).maxItems
          : undefined;
      const claims = properties.claims as Record<string, unknown>;
      const independentClaimCapacity =
        typeof sourceClaimLimit === "number" && typeof componentLimit === "number"
          ? Math.min(sourceClaimLimit, componentLimit)
          : (sourceClaimLimit ?? componentLimit);
      if (typeof independentClaimCapacity === "number") {
        claims.minItems = independentClaimCapacity;
        claims.maxItems = independentClaimCapacity;
      }
    }
    const selectionStatus = schemaConst(properties.selection_status);
    const predictiveStatus = schemaConst(properties.predictive_graph_status);
    if (
      selectionStatus === "SELECTED" &&
      properties.preferred_direction &&
      properties.macro_input_attributions &&
      properties.claims
    ) {
      const sourceClaims = sourceProperties.claims;
      const sourceClaimLimit =
        sourceClaims !== null && typeof sourceClaims === "object"
          ? (sourceClaims as Record<string, unknown>).maxItems
          : undefined;
      if (typeof sourceClaimLimit === "number") {
        (properties.claims as Record<string, unknown>).maxItems = sourceClaimLimit;
      }
    }
    if ([selectionStatus, predictiveStatus].some((status) => status?.startsWith("NO_QUALIFIED"))) {
      const claims = properties.claims;
      if (claims !== null && typeof claims === "object" && !Array.isArray(claims)) {
        (claims as Record<string, unknown>).maxItems = 1;
      }
    }
  }
  return bounded;
}

function schemaConst(value: unknown): string | null {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return null;
  const constant = (value as Record<string, unknown>).const;
  return typeof constant === "string" ? constant : null;
}

function omitUnsupportedProviderKeywords(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(omitUnsupportedProviderKeywords);
  if (value === null || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .filter(([key]) => key !== "propertyNames" && key !== "uniqueItems")
      .map(([key, nested]) => [key, omitUnsupportedProviderKeywords(nested)]),
  );
}

export function canonicalHash(value: unknown): string {
  return canonicalJsonHash(value);
}

function projectEvidenceSnapshotForHash(value: unknown): unknown {
  if (value instanceof Set) {
    const values = [...value];
    if (!values.every((item): item is string => typeof item === "string")) {
      throw new Error("evidence snapshot sets must contain only strings");
    }
    return values.sort();
  }
  if (value instanceof Map) {
    const entries = [...value.entries()];
    if (!entries.every((entry): entry is [string, unknown] => typeof entry[0] === "string")) {
      throw new Error("evidence snapshot maps must use string keys");
    }
    entries.sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0));
    return Object.fromEntries(
      entries.map(([key, nested]) => [key, projectEvidenceSnapshotForHash(nested)]),
    );
  }
  if (Array.isArray(value)) return value.map((nested) => projectEvidenceSnapshotForHash(nested));
  if (value === null || typeof value !== "object") return value;
  if (Object.prototype.toString.call(value) !== "[object Object]") return value;
  return Object.fromEntries(
    Object.entries(value).map(([key, nested]) => [key, projectEvidenceSnapshotForHash(nested)]),
  );
}
