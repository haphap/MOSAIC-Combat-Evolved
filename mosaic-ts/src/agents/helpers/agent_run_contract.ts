import { createHash } from "node:crypto";
import { appendFileSync, mkdirSync } from "node:fs";
import { basename, dirname, resolve } from "node:path";
import type { BaseChatModel } from "@langchain/core/language_models/chat_models";
import { HumanMessage, SystemMessage } from "@langchain/core/messages";
import { z } from "zod";
import { extractLlmTokenUsage } from "./runtime.js";

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
    | "model_service_error";
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
    evidence_hash: canonicalHash(opts.evidenceSnapshot),
  };
  let bound: { invoke: (input: unknown, options?: { signal?: AbortSignal }) => Promise<unknown> };
  try {
    // biome-ignore lint/suspicious/noExplicitAny: LangChain providers expose different generic signatures.
    bound = (opts.llm as any).withStructuredOutput(providerJsonSchema(opts.schema), {
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
  const cumulativeIssues: AgentContractIssue[] = [];
  let previousOutputHash: string | null = null;
  let previousFingerprints = new Set<string>();
  let noImprovementCount = 0;
  let previousRaw: unknown = null;

  for (let attempt = 0; attempt <= maxRepairs; attempt += 1) {
    const startedAt = Date.now();
    const kind = attempt === 0 ? "primary" : "repair";
    const input =
      attempt === 0
        ? opts.messages
        : buildRepairMessages({
            attempt,
            schema: opts.schema,
            originalMessages: opts.messages,
            originalOutput: previousRaw,
            cumulativeIssues,
            evidenceHash: hashes.evidence_hash,
          });
    let raw: unknown = null;
    let promptTokens = 0;
    let completionTokens = 0;
    let issues: AgentContractIssue[] = [];
    let candidate: T | null = null;
    try {
      const response = await bound.invoke(input, opts.signal ? { signal: opts.signal } : undefined);
      const envelope = structuredEnvelope(response);
      raw = envelope.parsed;
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
    previousRaw = raw;
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

function buildRepairMessages<T>(input: {
  attempt: number;
  schema: z.ZodType<T>;
  originalMessages: [SystemMessage, HumanMessage];
  originalOutput: unknown;
  cumulativeIssues: AgentContractIssue[];
  evidenceHash: string;
}): [SystemMessage, HumanMessage] {
  const issuePayload = dedupeIssues(input.cumulativeIssues);
  const contract = safeJsonSchema(input.schema);
  const originalUser = input.originalMessages[1].content;
  if (input.attempt === 1) {
    return [
      new SystemMessage(
        "Structured repair 1/3. Correct the complete prior object directly. Return a complete object; do not omit disposition fields or add prose. Copy exact evidence_id and allowed_research_rule_ids from the immutable catalog: every fact/inference claim needs evidence_refs, and every inference also needs research_rule_refs.",
      ),
      new HumanMessage(
        JSON.stringify({
          immutable_evidence_hash: input.evidenceHash,
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
        "Structured repair 2/3. Regenerate one complete object from the original immutable evidence. Satisfy every machine constraint and all cumulative errors. Use only exact catalog ids; fact/inference claims require evidence_refs and inference claims require research_rule_refs.",
      ),
      new HumanMessage(
        JSON.stringify({
          immutable_evidence_hash: input.evidenceHash,
          original_evidence_and_task: originalUser,
          cumulative_validation_errors: issuePayload,
          complete_json_schema: contract,
        }),
      ),
    ];
  }
  return [
    new SystemMessage(
      "FINAL structured repair 3/3. Rebuild the complete object under the strict contract. Use only exact catalog ids; fact/inference claims require evidence_refs and inference claims require research_rule_refs. You may choose an explicitly supported empty disposition, but disposition and conclusion references are mandatory. Return no prose.",
    ),
    new HumanMessage(
      JSON.stringify({
        immutable_evidence_hash: input.evidenceHash,
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
  return new AgentRunContractError(
    `${opts.agent}/${opts.stage}: rejected after ${attempts.length} attempts (${stopReason})`,
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
  if (/\b(400|429|500|502|503|504)\b|bad request|service unavailable|overloaded/.test(message)) {
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

function providerJsonSchema<T>(schema: z.ZodType<T>): unknown {
  return omitUnsupportedProviderKeywords(safeJsonSchema(schema));
}

function omitUnsupportedProviderKeywords(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(omitUnsupportedProviderKeywords);
  if (value === null || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .filter(([key]) => key !== "propertyNames")
      .map(([key, nested]) => [key, omitUnsupportedProviderKeywords(nested)]),
  );
}

export function canonicalHash(value: unknown): string {
  return `sha256:${createHash("sha256").update(stableJson(value)).digest("hex")}`;
}

function stableJson(value: unknown): string {
  if (value === undefined) return "null";
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  return `{${Object.entries(value as Record<string, unknown>)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, nested]) => `${JSON.stringify(key)}:${stableJson(nested)}`)
    .join(",")}}`;
}
