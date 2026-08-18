import { mkdtempSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { AIMessage, HumanMessage, SystemMessage } from "@langchain/core/messages";
import { describe, expect, it } from "vitest";
import { z } from "zod";
import { buildAutonomousExecutionProviderControlDirective } from "../src/agents/decision/_factory.js";
import {
  AlphaDiscoverySubmissionSchema,
  AutonomousExecutionSubmissionSchema,
  CioFinalSubmissionSchema,
  CioProposalNonEmptyCurrentSubmissionSchema,
  CioProposalSubmissionSchema,
  CroSubmissionSchema,
} from "../src/agents/decision/submission_schemas.js";
import {
  type AgentContractIssue,
  AgentRunContractError,
  assertStructuredOutputCapability,
  invokeStrictStructured,
} from "../src/agents/helpers/agent_run_contract.js";
import { MacroInputAttributionSubmissionArraySchema } from "../src/agents/helpers/macro_attribution.js";
import {
  canonicalStructuredRepairDirectiveManifest,
  STRUCTURED_REPAIR_DIRECTIVE_CONTRACT_VERSION,
} from "../src/agents/helpers/structured_repair_directives.js";
import { createMacroSubmissionSchema, MACRO_AGENT_IDS } from "../src/agents/macro/_contracts.js";
import { buildStandardSectorSchema } from "../src/agents/sector/_schemas.js";
import type { DailyCycleStateType } from "../src/agents/state.js";
import { buildRuntimeSuperinvestorSchema } from "../src/agents/superinvestor/_schemas.js";
import { macroSubmission } from "./helpers/macro.js";

const Schema = z.object({
  disposition: z.enum(["ITEMS", "NONE"]),
  items: z.array(z.string()),
  claim_refs: z.array(z.string()).min(1),
});

class SequenceLlm {
  readonly calls: unknown[] = [];
  readonly schemas: unknown[] = [];
  readonly structuredOptions: unknown[] = [];
  readonly structuredInvokeOptions: unknown[] = [];

  constructor(
    private readonly outputs: unknown[],
    private readonly constructionError?: Error,
  ) {}

  withStructuredOutput(
    schema: unknown,
    options: unknown,
  ): { invoke: (input: unknown, invokeOptions?: unknown) => Promise<unknown> } {
    if (this.constructionError) throw this.constructionError;
    this.schemas.push(schema);
    this.structuredOptions.push(options);
    return {
      invoke: async (input: unknown, invokeOptions?: unknown) => {
        this.calls.push(input);
        this.structuredInvokeOptions.push(invokeOptions);
        const next = this.outputs.shift();
        if (next instanceof Error) throw next;
        return {
          raw: new AIMessage(""),
          parsed: next,
        };
      },
    };
  }
}

class PromptJsonLlm {
  readonly promptCalls: unknown[] = [];
  structuredCalls = 0;

  constructor(
    private readonly promptOutputs: unknown[],
    private readonly structuredError = new Error(
      "400 invalid_request_error: this response_format type is unavailable now",
    ),
  ) {}

  withStructuredOutput(): { invoke: () => Promise<never> } {
    return {
      invoke: async () => {
        this.structuredCalls += 1;
        throw this.structuredError;
      },
    };
  }

  async invoke(input: unknown): Promise<AIMessage> {
    this.promptCalls.push(input);
    const next = this.promptOutputs.shift();
    if (next instanceof Error) throw next;
    return new AIMessage(typeof next === "string" ? next : JSON.stringify(next));
  }
}

function messages(): [SystemMessage, HumanMessage] {
  return [new SystemMessage("fixed prompt"), new HumanMessage("immutable evidence")];
}

function autonomousExecutionDirectiveState(
  darwinianRuntimeBinding: Record<string, unknown> | null = null,
): DailyCycleStateType {
  return {
    darwinian_runtime_binding: darwinianRuntimeBinding,
    outcome_opportunity_bindings: {},
    layer4_outputs: {
      runtime: {
        candidate_target_state: {
          candidate_target_hash: `sha256:${"1".repeat(64)}`,
          portfolio_actions: [{ ticker: "600001.SH", current_weight: 0, target_weight: 0.1 }],
        },
        cro_review_state: {
          review_hash: `sha256:${"2".repeat(64)}`,
          output: { required_adjustments: [] },
        },
      },
    },
  } as unknown as DailyCycleStateType;
}

function namedPropertySchemas(value: unknown, propertyName: string): Record<string, unknown>[] {
  if (Array.isArray(value)) {
    return value.flatMap((nested) => namedPropertySchemas(nested, propertyName));
  }
  if (value === null || typeof value !== "object") return [];
  const record = value as Record<string, unknown>;
  const properties =
    record.properties !== null &&
    typeof record.properties === "object" &&
    !Array.isArray(record.properties)
      ? (record.properties as Record<string, unknown>)
      : null;
  const own = properties?.[propertyName];
  return [
    ...(own !== null && typeof own === "object" && !Array.isArray(own)
      ? [own as Record<string, unknown>]
      : []),
    ...Object.values(record).flatMap((nested) => namedPropertySchemas(nested, propertyName)),
  ];
}

async function capturedProviderSchema(schema: z.ZodType<unknown>, name: string): Promise<unknown> {
  const llm = new SequenceLlm([new Error("400 Bad Request")]);
  await expect(
    invokeStrictStructured({
      llm: llm as never,
      schema,
      messages: messages(),
      agent: name,
      stage: "agent_run",
      runId: `provider-schema-${name}`,
      evidenceSnapshot:
        name === "cio_final"
          ? {
              cio_final_control_directive: {
                contract_version: "cio_final_provider_control_directive_v2",
                decision_reason_max_length: 160,
                cro_action_local_refs: [],
                execution_assessment_local_refs: [],
                target_bounds: [],
              },
            }
          : name === "autonomous_execution"
            ? {
                autonomous_execution_control_directive: {
                  schema_version: "execution_frozen_order_intent_set_v2",
                  frozen_object_set_id: "order-intent-set:structured-smoke",
                  frozen_object_set_hash: `sha256:${"1".repeat(64)}`,
                  intents: [
                    {
                      order_intent_ref: "order-intent:structured-smoke",
                      ts_code: "600001.SH",
                      requested_delta_weight: 0.1,
                    },
                  ],
                },
              }
            : {},
      onAttempt: () => {},
    }),
  ).rejects.toBeInstanceOf(AgentRunContractError);
  return llm.schemas[0];
}

function semanticIssues(output: z.infer<typeof Schema>): AgentContractIssue[] {
  if (
    (output.disposition === "ITEMS" && output.items.length > 0) ||
    (output.disposition === "NONE" && output.items.length === 0)
  ) {
    return [];
  }
  return [
    {
      validator: "domain_semantics",
      reason_code: "DISPOSITION_MISMATCH",
      json_path: "$.disposition",
      message: "disposition and items disagree",
    },
  ];
}

function run(llm: SequenceLlm, extra: Record<string, unknown> = {}) {
  return invokeStrictStructured({
    llm: llm as never,
    schema: Schema,
    messages: messages(),
    agent: "test_agent",
    stage: "agent_run",
    runId: "run-1",
    evidenceSnapshot: { snapshot: "fixed" },
    validate: (output) => ({ output, issues: semanticIssues(output) }),
    isAcceptedEmpty: (output) => output.disposition === "NONE",
    ...extra,
  });
}

describe("strict agent-run contract", () => {
  it("accepts primary structured output and records hashes", async () => {
    const llm = new SequenceLlm([{ disposition: "ITEMS", items: ["x"], claim_refs: ["claim-1"] }]);
    const result = await run(llm);
    expect(result.audit.status).toBe("accepted");
    expect(result.audit.output_source).toBe("structured_primary");
    expect(result.audit.attempt_count).toBe(1);
    expect(result.audit.prompt_hash).toMatch(/^sha256:/);
    expect(result.audit.evidence_hash).toMatch(/^sha256:/);
  });

  it("does not forward the agent timeout signal to structured provider invoke", async () => {
    const llm = new SequenceLlm([{ disposition: "ITEMS", items: ["x"], claim_refs: ["claim-1"] }]);
    await run(llm, { signal: new AbortController().signal });
    expect(llm.structuredInvokeOptions).toEqual([undefined]);
  });

  it("hashes runtime evidence maps and sets by their canonical JSON projection", async () => {
    const output = { disposition: "ITEMS", items: ["x"], claim_refs: ["claim-1"] };
    const first = await run(new SequenceLlm([output]), {
      evidenceSnapshot: {
        evidenceById: new Map([
          ["evidence:b", { evidence_id: "evidence:b", value: 2 }],
          ["evidence:a", { evidence_id: "evidence:a", value: 1 }],
        ]),
        evidenceLedger: [],
        allowedResearchRuleIds: new Set(["rule.b", "rule.a"]),
      },
    });
    const reordered = await run(new SequenceLlm([output]), {
      evidenceSnapshot: {
        evidenceById: new Map([
          ["evidence:a", { value: 1, evidence_id: "evidence:a" }],
          ["evidence:b", { value: 2, evidence_id: "evidence:b" }],
        ]),
        evidenceLedger: [],
        allowedResearchRuleIds: new Set(["rule.a", "rule.b"]),
      },
    });
    const changed = await run(new SequenceLlm([output]), {
      evidenceSnapshot: {
        evidenceById: new Map([
          ["evidence:a", { evidence_id: "evidence:a", value: 1 }],
          ["evidence:b", { evidence_id: "evidence:b", value: 3 }],
        ]),
        evidenceLedger: [],
        allowedResearchRuleIds: new Set(["rule.a", "rule.changed"]),
      },
    });

    expect(first.audit.evidence_hash).toBe(reordered.audit.evidence_hash);
    expect(changed.audit.evidence_hash).not.toBe(first.audit.evidence_hash);
  });

  it("combines schema and semantic validation across repairs and accepts a legal empty result", async () => {
    const llm = new SequenceLlm([
      { disposition: "NONE", items: [], claim_refs: [] },
      { disposition: "ITEMS", items: [], claim_refs: ["claim-1"] },
      { disposition: "NONE", items: [], claim_refs: ["claim-1"] },
    ]);
    const result = await run(llm);
    expect(result.audit.status).toBe("accepted_empty");
    expect(result.audit.output_source).toBe("structured_repair");
    expect(result.audit.repair_count).toBe(2);
    expect(result.audit.attempts[0]?.validation_issues[0]?.validator).toBe("zod_schema");
    expect(result.audit.attempts[1]?.validation_issues).toEqual([
      expect.objectContaining({ reason_code: "DISPOSITION_MISMATCH" }),
    ]);
    const repairDirectives = canonicalStructuredRepairDirectiveManifest();
    expect((llm.calls[1] as [SystemMessage, HumanMessage])[0].content).toBe(
      repairDirectives[0]?.system_message,
    );
    expect((llm.calls[2] as [SystemMessage, HumanMessage])[0].content).toBe(
      repairDirectives[1]?.system_message,
    );
    expect(repairDirectives).toHaveLength(3);
    expect(STRUCTURED_REPAIR_DIRECTIVE_CONTRACT_VERSION).toBe("structured_repair_directive_v7");
    for (const directive of repairDirectives) {
      expect(directive.system_message).toContain(
        "Evidence freshness rule: stale, missing, tool_failed, or unapproved fallback evidence may support only RISK_FLAG claims; FACT, EVENT, and INTERPRETATION claims require current, non-fallback evidence.",
      );
      expect(directive.system_message).toContain(
        "Claim support invariant: every non-empty recommendation/action output that requires claim support must reference at least one FACT, EVENT, or INTERPRETATION claim; only an empty disposition explicitly permitted by the runtime contract may be supported solely by RISK_FLAG claims.",
      );
      expect(directive.system_message).toContain(
        "Conclusion shape invariant: structured_conclusion must be a flat object whose values are only string, number, boolean, or null; arrays and nested objects are not allowed.",
      );
      expect(directive.system_message).toContain(
        "Decision reason invariant: decision_reason must be <=300 characters, leaving a safety margin below the 320-character schema maximum.",
      );
      expect(directive.system_message).toContain(
        "CRO action invariant: candidate_actions[].max_target_weight must be 0 for VETO, null for REQUIRE_REVIEW or NO_OBJECTION, and a number for CAP_WEIGHT or REDUCE_WEIGHT.",
      );
      expect(directive.system_message).toContain(
        "CRO action evidence invariant: when candidate_actions is non-empty, each candidate_actions[].claim_refs must include at least one FACT, EVENT, or INTERPRETATION claim; no candidate action may be supported only by RISK_FLAG claims.",
      );
      expect(directive.system_message).toContain(
        "Claim statement invariant: every claims[].statement must be <=3000 characters, leaving a safety margin below the 3200-character schema maximum.",
      );
      expect(directive.system_message).toContain(
        "Claim reference closure invariant: top-level claim_refs and every nested claim_refs may reference only claim_id values that actually exist in the same submission.claims; dangling claim_refs are forbidden.",
      );
      expect(directive.system_message).toContain(
        "CRO disposition invariant: CRO review_disposition must be determined by candidate_actions: empty -> NO_RISK_ACTION, all VETO -> BLOCK_ALL, all NO_OBJECTION -> NO_OBJECTION, otherwise -> REVIEW_ACTIONS.",
      );
      expect(directive.system_message).toContain(
        "CIO final CRO bound invariant: when a frozen CRO action is REDUCE_WEIGHT, the matching final target_positions[].target_weight must be <= that action's frozen max_target_weight for the same ticker; never retain a higher proposal target.",
      );
    }
    expect(JSON.stringify(llm.calls[2])).toContain("complete_json_schema");
  });

  it("places exact runtime evidence and opaque citation ids in every repair request", async () => {
    const llm = new SequenceLlm([
      { disposition: "ITEMS", items: [], claim_refs: ["claim-1"] },
      { disposition: "ITEMS", items: ["fixed"], claim_refs: ["claim-1"] },
    ]);
    await run(llm, {
      evidenceSnapshot: {
        evidenceLedger: [{ evidence_id: "evidence:allowed" }],
        allowedResearchRuleIds: new Set(["rule.allowed"]),
      },
    });
    const repairPayload = JSON.parse(
      String((llm.calls[1] as [SystemMessage, HumanMessage])[1].content),
    );
    expect(repairPayload.allowed_evidence_ids).toEqual(["evidence:allowed"]);
    expect(repairPayload.allowed_citation_ids).toEqual(["rule.allowed"]);
  });

  it("uses at most three repairs and revalidates new errors", async () => {
    const llm = new SequenceLlm([
      { disposition: "ITEMS", items: ["bad-1"], claim_refs: ["claim-1"] },
      { disposition: "ITEMS", items: ["bad-2"], claim_refs: ["claim-1"] },
      { disposition: "ITEMS", items: ["bad-3"], claim_refs: ["claim-1"] },
      { disposition: "ITEMS", items: ["bad-4"], claim_refs: ["claim-1"] },
    ]);
    const rejection = run(llm, {
      validate: (output: z.infer<typeof Schema>) => ({
        output,
        issues: [
          {
            validator: "changing_validator",
            reason_code: output.items[0]?.toUpperCase() ?? "MISSING",
            json_path: "$.items[0]",
            message: "new validation failure",
          },
        ],
      }),
    });
    await expect(rejection).rejects.toMatchObject({
      audit: { stop_reason: "repair_budget_exhausted", attempt_count: 4, repair_count: 3 },
    });
    await expect(rejection).rejects.toThrow("final=BAD-4@$.items[0]");
    expect(llm.calls).toHaveLength(4);
  });

  it("escalates one byte-equivalent repair to the schema-bearing repair directive", async () => {
    const invalid = { disposition: "ITEMS", items: [], claim_refs: ["claim-1"] };
    const valid = { disposition: "ITEMS", items: ["fixed"], claim_refs: ["claim-1"] };
    const llm = new SequenceLlm([invalid, invalid, valid]);
    await expect(run(llm)).resolves.toMatchObject({
      audit: { status: "accepted", attempt_count: 3, repair_count: 2 },
    });
    expect(llm.calls).toHaveLength(3);
    expect(JSON.stringify(llm.calls[2])).toContain("complete_json_schema");
  });

  it("stops on byte-equivalent output when the explicit repair budget is exhausted", async () => {
    const invalid = { disposition: "ITEMS", items: [], claim_refs: ["claim-1"] };
    const llm = new SequenceLlm([invalid, invalid]);
    await expect(run(llm, { maxRepairs: 1 })).rejects.toMatchObject({
      audit: { stop_reason: "duplicate_output", attempt_count: 2 },
    });
    expect(llm.calls).toHaveLength(2);
  });

  it("stops after two repairs eliminate none of the prior normalized errors", async () => {
    const llm = new SequenceLlm([
      { disposition: "ITEMS", items: [], claim_refs: ["a"] },
      { disposition: "ITEMS", items: [], claim_refs: ["b"] },
      { disposition: "ITEMS", items: [], claim_refs: ["c"] },
    ]);
    await expect(run(llm)).rejects.toMatchObject({
      audit: { stop_reason: "no_error_improvement", attempt_count: 3 },
    });
  });

  it.each([
    [new Error("request timed out"), "timeout", "MODEL_TIMEOUT"],
    [new Error("ECONNREFUSED"), "connection_error", "MODEL_CONNECTION_ERROR"],
    [new Error("400 Bad Request"), "model_service_error", "MODEL_SERVICE_ERROR"],
    [new Error("503 service unavailable"), "model_service_error", "MODEL_SERVICE_ERROR"],
  ])("terminates operational failures without repair: %s", async (error, stopReason, code) => {
    const llm = new SequenceLlm([error]);
    try {
      await run(llm);
      throw new Error("expected contract failure");
    } catch (caught) {
      expect(caught).toBeInstanceOf(AgentRunContractError);
      expect((caught as AgentRunContractError).audit.stop_reason).toBe(stopReason);
      expect((caught as AgentRunContractError).audit.reason_codes).toEqual([code]);
      expect((caught as AgentRunContractError).audit.attempt_count).toBe(1);
      expect(llm.calls).toHaveLength(1);
    }
  });

  it("fails preflight when structured output is unsupported", async () => {
    const llm = new SequenceLlm([], new Error("unsupported"));
    await expect(run(llm)).rejects.toMatchObject({
      audit: { stop_reason: "structured_output_unsupported", attempt_count: 0 },
    });
  });

  it("executes provider structured-output preflight", async () => {
    const llm = new SequenceLlm([{ preflight: "ok" }]);
    await expect(assertStructuredOutputCapability(llm as never)).resolves.toBeUndefined();
    expect(llm.calls).toHaveLength(1);
    expect(llm.structuredOptions).toEqual([
      expect.objectContaining({ includeRaw: true, method: "jsonSchema", strict: true }),
    ]);
  });

  it("falls back to strict prompt JSON when structured preflight raises Connection error", async () => {
    const llm = new PromptJsonLlm(
      [{ preflight: "ok" }, { disposition: "ITEMS", items: ["x"], claim_refs: ["claim-1"] }],
      new Error("Connection error"),
    );

    await expect(assertStructuredOutputCapability(llm as never)).resolves.toBeUndefined();
    const result = await invokeStrictStructured({
      llm: llm as never,
      schema: Schema,
      messages: messages(),
      agent: "test_agent",
      stage: "agent_run",
      runId: "run-prompt-json",
      evidenceSnapshot: { snapshot: "fixed" },
      validate: (output) => ({ output, issues: semanticIssues(output) }),
    });

    expect(result.audit.status).toBe("accepted");
    expect(llm.structuredCalls).toBe(1);
    expect(llm.promptCalls).toHaveLength(2);
    expect(JSON.stringify(llm.promptCalls[1])).toContain("JSON Schema");
  });

  it("fails closed when prompt JSON fallback returns invalid JSON", async () => {
    const llm = new PromptJsonLlm(["not-json"], new Error("Connection error"));

    await expect(assertStructuredOutputCapability(llm as never)).rejects.toThrow(
      "prompt-JSON fallback failed: provider returned no valid JSON object",
    );
    expect(llm.structuredCalls).toBe(1);
    expect(llm.promptCalls).toHaveLength(1);
  });

  it("attributes empty prompt JSON content at the root without usage", async () => {
    const llm = new PromptJsonLlm([{ preflight: "ok" }, ""], new Error("Connection error"));
    await expect(assertStructuredOutputCapability(llm as never)).resolves.toBeUndefined();
    await expect(
      invokeStrictStructured({
        llm: llm as never,
        schema: Schema,
        messages: messages(),
        agent: "test_agent",
        stage: "agent_run",
        runId: "run-empty-prompt-json",
        evidenceSnapshot: { snapshot: "fixed" },
        maxRepairs: 0,
      }),
    ).rejects.toMatchObject({
      audit: {
        attempts: [
          expect.objectContaining({
            validation_issues: [
              expect.objectContaining({
                validator: "structured_output",
                reason_code: "STRUCTURED_OUTPUT_INVALID",
                json_path: "$",
                message: "provider returned no valid JSON object",
              }),
            ],
            prompt_tokens: 0,
            completion_tokens: 0,
          }),
        ],
      },
    });
  });

  it("captures transformed prompt JSON atomically only when enabled and fails closed on write errors", async () => {
    const captureDir = mkdtempSync(join(tmpdir(), "mosaic-prompt-json-capture-"));
    const previousCaptureDir = process.env.MOSAIC_PROMPT_JSON_CAPTURE_DIR;
    delete process.env.MOSAIC_PROMPT_JSON_CAPTURE_DIR;
    try {
      const llm = new PromptJsonLlm(
        [{ preflight: "ok" }, { disposition: "ITEMS", items: ["x"], claim_refs: ["claim-1"] }],
        new Error("Connection error"),
      );
      await expect(assertStructuredOutputCapability(llm as never)).resolves.toBeUndefined();
      expect(readdirSync(captureDir)).toEqual([]);

      process.env.MOSAIC_PROMPT_JSON_CAPTURE_DIR = captureDir;
      await invokeStrictStructured({
        llm: llm as never,
        schema: Schema,
        messages: messages(),
        agent: "test_agent",
        stage: "agent_run",
        runId: "run-capture",
        evidenceSnapshot: { snapshot: "fixed" },
        onAttempt: () => {},
      });
      const [captureFile] = readdirSync(captureDir);
      expect(captureFile).toMatch(/^prompt-json-.*\.json$/);
      expect(statSync(join(captureDir, captureFile as string)).mode & 0o777).toBe(0o600);
      const capture = JSON.parse(readFileSync(join(captureDir, captureFile as string), "utf8"));
      expect(capture).toMatchObject({
        schema_version: "prompt_json_messages_capture_v1",
        binding_name: "test_agent_agent_run",
      });
      expect(capture.messages).toHaveLength(2);
      expect(JSON.stringify(capture.messages[0])).toContain("JSON Schema");
      expect(JSON.stringify(capture.messages[1])).toContain("immutable evidence");

      const blockedPath = join(captureDir, "blocked");
      writeFileSync(blockedPath, "not a directory", { mode: 0o600 });
      const failingLlm = new PromptJsonLlm(
        [{ preflight: "ok" }, { preflight: "ok" }],
        new Error("Connection error"),
      );
      delete process.env.MOSAIC_PROMPT_JSON_CAPTURE_DIR;
      await expect(assertStructuredOutputCapability(failingLlm as never)).resolves.toBeUndefined();
      process.env.MOSAIC_PROMPT_JSON_CAPTURE_DIR = blockedPath;
      await expect(
        invokeStrictStructured({
          llm: failingLlm as never,
          schema: Schema,
          messages: messages(),
          agent: "test_agent",
          stage: "agent_run",
          runId: "run-capture-write-error",
          evidenceSnapshot: { snapshot: "fixed" },
          maxRepairs: 0,
          onAttempt: () => {},
        }),
      ).rejects.toBeInstanceOf(AgentRunContractError);
      expect(failingLlm.promptCalls).toHaveLength(1);
    } finally {
      if (previousCaptureDir === undefined) delete process.env.MOSAIC_PROMPT_JSON_CAPTURE_DIR;
      else process.env.MOSAIC_PROMPT_JSON_CAPTURE_DIR = previousCaptureDir;
      rmSync(captureDir, { recursive: true, force: true });
    }
  });

  it("removes provider-unsupported propertyNames but retains full local validation", async () => {
    const RecordSchema = z.object({ values: z.record(z.string().startsWith("/"), z.number()) });
    const llm = new SequenceLlm([{ values: { invalid_key: 1 } }, { values: { "/score": 1 } }]);
    const result = await invokeStrictStructured({
      llm: llm as never,
      schema: RecordSchema,
      messages: messages(),
      agent: "record_agent",
      stage: "agent_run",
      runId: "run-record",
      evidenceSnapshot: {},
    });
    expect(JSON.stringify(llm.schemas[0])).not.toContain("propertyNames");
    expect(JSON.stringify(llm.schemas[0])).toContain("additionalProperties");
    expect(result.audit.repair_count).toBe(1);
    expect(result.output).toEqual({ values: { "/score": 1 } });
  });

  it("bounds high-volume extraction arrays without narrowing the domain schema", async () => {
    const CompactSchema = z.object({
      selection_status: z.literal("NO_QUALIFIED_GENERIC"),
      claims: z.array(z.string()).max(8),
      key_drivers: z.array(z.string()).max(5),
      picks: z.array(z.string()).max(10),
      candidate_actions: z.array(z.string()).max(10),
      free_text: z.string(),
      conclusion: z.record(z.string(), z.string()),
      empty_tuple: z.tuple([]),
      pair_tuple: z.tuple([z.string(), z.number()]),
    });
    const llm = new SequenceLlm([
      {
        selection_status: "NO_QUALIFIED_GENERIC",
        claims: [],
        key_drivers: [],
        picks: [],
        candidate_actions: [],
        free_text: "bounded provider text",
        conclusion: { state: "mixed" },
        empty_tuple: [],
        pair_tuple: ["pair", 1],
      },
    ]);
    await invokeStrictStructured({
      llm: llm as never,
      schema: CompactSchema,
      messages: messages(),
      agent: "compact_agent",
      stage: "agent_run",
      runId: "run-compact",
      evidenceSnapshot: {},
    });
    const properties = (llm.schemas[0] as { properties: Record<string, Record<string, unknown>> })
      .properties;
    expect(properties.claims?.maxItems).toBe(1);
    expect(properties.key_drivers?.maxItems).toBe(1);
    expect(properties.picks?.maxItems).toBe(2);
    expect(properties.candidate_actions?.maxItems).toBe(10);
    expect(properties.free_text?.maxLength).toBe(320);
    expect(properties.conclusion?.maxProperties).toBe(12);
    expect(properties.empty_tuple).toMatchObject({
      items: false,
      minItems: 0,
      maxItems: 0,
    });
    expect(properties.pair_tuple).toMatchObject({
      items: false,
      minItems: 2,
      maxItems: 2,
    });
    expect(
      CompactSchema.safeParse({
        selection_status: "NO_QUALIFIED_GENERIC",
        claims: Array(8).fill("claim"),
        key_drivers: Array(5).fill("driver"),
        picks: Array(10).fill("pick"),
        candidate_actions: Array(10).fill("action"),
        free_text: "x".repeat(500),
        conclusion: Object.fromEntries(
          Array.from({ length: 13 }, (_, index) => [`field_${index}`, "value"]),
        ),
        empty_tuple: [],
        pair_tuple: ["pair", 1],
      }).success,
    ).toBe(true);
  });

  it("retains the claim capacity required by exact component rosters", async () => {
    const ComponentSchema = z.object({
      components: z.array(z.string()).length(5),
      claims: z.array(z.string()).min(1).max(8),
    });
    const llm = new SequenceLlm([{ components: ["a", "b", "c", "d", "e"], claims: ["shared"] }]);
    await invokeStrictStructured({
      llm: llm as never,
      schema: ComponentSchema,
      messages: messages(),
      agent: "component_agent",
      stage: "agent_run",
      runId: "run-components",
      evidenceSnapshot: {},
    });
    const properties = (llm.schemas[0] as { properties: Record<string, Record<string, unknown>> })
      .properties;
    expect(properties.claims?.minItems).toBe(5);
    expect(properties.claims?.maxItems).toBe(5);
  });

  it("projects a four-component Macro contract without losing independent claim ownership", async () => {
    const schema = createMacroSubmissionSchema("us_economy");
    const base = macroSubmission("us_economy");
    if (base.mode !== "COMPONENTS") throw new Error("component fixture required");
    const evidenceId = `evidence:${"a".repeat(64)}`;
    const providerOutput = {
      provider_contract: "MACRO_COMPONENTS_COMPACT_V1",
      mode: "COMPONENTS",
      components: base.components.map((component) => ({
        component: component.component,
        signal: { direction: "NEUTRAL", strength: 0 },
        persistence_horizon: "WEEKS",
        confidence: 0.7,
        channel: "A-share risk premium",
        claim_kind: "RISK_FLAG",
        statement: "The component evidence supports a cautious assessment",
        state: "The component state is mixed",
        a_share_transmission: "The component has a balanced A-share transmission",
        evidence_id: evidenceId,
        research_rule_ref: null,
        snapshot_echo: null,
      })),
    };
    const invalidProviderOutput = structuredClone(providerOutput);
    (invalidProviderOutput.components[0] as { evidence_id: unknown }).evidence_id = 42;
    const llm = new SequenceLlm([invalidProviderOutput, providerOutput]);
    const result = await invokeStrictStructured({
      llm: llm as never,
      schema,
      messages: messages(),
      agent: "us_economy",
      stage: "agent_run",
      runId: "provider-macro-components",
      evidenceSnapshot: {
        evidenceLedger: [{ evidence_id: evidenceId }],
        allowedResearchRuleIds: new Set<string>(),
      },
      onAttempt: () => {},
    });
    expect(result.output.mode).toBe("COMPONENTS");
    expect(result.audit.repair_count).toBe(1);
    expect(JSON.stringify(llm.calls[1])).toContain(evidenceId);
    if (result.output.mode !== "COMPONENTS") throw new Error("component output required");
    expect(result.output.claims).toHaveLength(4);
    expect(
      new Set(result.output.components.flatMap((component) => component.claim_refs)).size,
    ).toBe(4);
    const providerSchema = llm.schemas[0] as {
      properties: {
        provider_contract: { const: string };
        components: {
          minItems: number;
          maxItems: number;
          prefixItems: Array<{ properties: Record<string, Record<string, unknown>> }>;
        };
      };
    };
    expect(providerSchema.properties.provider_contract.const).toBe("MACRO_COMPONENTS_COMPACT_V1");
    expect(providerSchema.properties).not.toHaveProperty("claims");
    expect(providerSchema.properties.components).toMatchObject({ minItems: 4, maxItems: 4 });
    for (const component of providerSchema.properties.components.prefixItems) {
      expect(component.properties.channel).toMatchObject({
        type: "string",
        maxLength: 96,
        pattern: "^[^0-9０-９%％\\r\\n]{1,96}$",
      });
      expect(component.properties.statement).toMatchObject({
        type: "string",
        maxLength: 160,
        pattern: "^[^0-9０-９%％\\r\\n]{1,160}$",
      });
      expect(component.properties.state).toMatchObject({
        type: "string",
        maxLength: 128,
        pattern: "^[^0-9０-９%％\\r\\n]{1,128}$",
      });
      expect(component.properties.a_share_transmission).toMatchObject({
        type: "string",
        maxLength: 160,
        pattern: "^[^0-9０-９%％\\r\\n]{1,160}$",
      });
      expect(component.properties.evidence_id).toMatchObject({
        type: "string",
        enum: [evidenceId],
      });
      expect(component.properties.research_rule_ref).toEqual({ type: "null" });
      expect(component.properties.claim_kind).toEqual({
        type: "string",
        enum: ["FACT", "EVENT", "RISK_FLAG"],
      });
      expect(component.properties.snapshot_echo).toEqual({ type: "null" });
    }
  });

  it("validates the compact provider payload before normalizing it into the domain schema", async () => {
    const evidenceId = `evidence:${"c".repeat(64)}`;
    const judgment = {
      signal: { direction: "NEUTRAL", strength: 0 },
      persistence_horizon: "DAYS",
      confidence: 0.5,
      channel: "ETF positioning remains mixed",
      statement: "The frozen ETF-share evidence supports a mixed positioning assessment",
      subject: "institutional flow",
      state: "ETF positioning remains mixed",
      a_share_transmission: "ETF positioning has not established a durable market impulse",
      evidence_id: evidenceId,
      research_rule_ref: null,
      snapshot_echo: null,
    };
    const llm = new SequenceLlm([
      {
        provider_contract: "MACRO_DIRECT_COMPACT_V1",
        mode: "DIRECT",
        judgment: { ...judgment, claim_kind: "RISK_FLAG" },
      },
      {
        provider_contract: "MACRO_DIRECT_COMPACT_V1",
        mode: "DIRECT",
        judgment: { ...judgment, claim_kind: "FACT" },
      },
    ]);

    const result = await invokeStrictStructured({
      llm: llm as never,
      schema: createMacroSubmissionSchema("institutional_flow"),
      messages: messages(),
      agent: "institutional_flow",
      stage: "agent_run",
      runId: "provider-macro-direct-local-schema",
      evidenceSnapshot: {
        evidenceLedger: [{ evidence_id: evidenceId }],
        allowedResearchRuleIds: new Set<string>(),
      },
      onAttempt: () => {},
    });

    expect(result.audit.repair_count).toBe(1);
    expect(result.output.claims[0]?.claim_kind).toBe("FACT");
    expect(JSON.stringify(llm.calls[1])).toContain("claim_kind");
  });

  it("validates nested Macro provider attributions before normalization and keeps canonical rows compatible", async () => {
    const canonicalAttributions = MACRO_AGENT_IDS.map((agent_id) => ({
      agent_id,
      target_type: "SUBMISSION_SUMMARY" as const,
      target_local_ref: "$SUBMISSION" as const,
      claim_refs_used: [],
      effect: "NOT_MATERIAL" as const,
    }));
    const invalidProviderOutput = {
      macro_input_attributions: {
        submission_summaries: Object.fromEntries(
          MACRO_AGENT_IDS.map((agentId) => [
            agentId,
            { claim_ref_used: null, effect: "NOT_MATERIAL" },
          ]),
        ),
        target_attributions: [
          {
            agent_id: "semiconductor",
            target_type: "PORTFOLIO_DECISION",
            target_local_ref: "cio",
            claim_ref_used: "claim-1",
            effect: "SUPPORTS",
          },
        ],
      },
    };
    const schema = z
      .object({
        macro_input_attributions: MacroInputAttributionSubmissionArraySchema,
      })
      .strict();
    const attempts: AgentContractIssue[][] = [];
    const llm = new SequenceLlm([
      invalidProviderOutput,
      { macro_input_attributions: canonicalAttributions },
    ]);

    const result = await invokeStrictStructured({
      llm: llm as never,
      schema,
      messages: messages(),
      agent: "cio",
      stage: "proposal",
      runId: "provider-macro-attribution-shape",
      evidenceSnapshot: {
        evidenceLedger: [],
        allowedResearchRuleIds: new Set<string>(),
      },
      onAttempt: (audit) => {
        attempts.push(audit.validation_issues);
      },
    });

    expect(attempts[0]?.some((issue) => issue.json_path.includes("target_attributions"))).toBe(
      true,
    );
    expect(attempts[0]?.some((issue) => issue.json_path === "$.macro_input_attributions")).toBe(
      false,
    );
    expect(result.audit.repair_count).toBe(1);
    expect(result.output.macro_input_attributions).toEqual(canonicalAttributions);

    const direct = await invokeStrictStructured({
      llm: new SequenceLlm([{ macro_input_attributions: canonicalAttributions }]) as never,
      schema,
      messages: messages(),
      agent: "cio",
      stage: "proposal",
      runId: "canonical-macro-attribution-array",
      evidenceSnapshot: {
        evidenceLedger: [],
        allowedResearchRuleIds: new Set<string>(),
      },
    });
    expect(direct.audit.repair_count).toBe(0);
    expect(direct.output.macro_input_attributions).toEqual(canonicalAttributions);
  });

  it("fails closed before provider invocation when Macro runtime evidence is empty", async () => {
    const llm = new SequenceLlm([]);
    await expect(
      invokeStrictStructured({
        llm: llm as never,
        schema: createMacroSubmissionSchema("institutional_flow"),
        messages: messages(),
        agent: "institutional_flow",
        stage: "agent_run",
        runId: "provider-macro-empty-evidence",
        evidenceSnapshot: { evidenceLedger: [], allowedResearchRuleIds: new Set<string>() },
        onAttempt: () => {},
      }),
    ).rejects.toMatchObject({
      audit: {
        stop_reason: "evidence_contract_failure",
        reason_codes: ["MACRO_RUNTIME_EVIDENCE_CATALOG_EMPTY"],
        attempt_count: 0,
      },
    });
    expect(llm.calls).toHaveLength(0);
    expect(llm.schemas).toHaveLength(0);
  });

  it("binds selected Sector evidence legs, citations, and security shortlists to the runtime directive", async () => {
    const preferredEvidence = `evidence:${"d".repeat(64)}`;
    const leastEvidence = `evidence:${"e".repeat(64)}`;
    const citation = "sector.semiconductor.soft.001";
    const directive = {
      selection_status: "SELECTED" as const,
      preferred_direction_id: "chip_design",
      least_preferred_direction_id: "discrete_devices",
      allowed_preferred_security_ids: ["600001.SH", "600002.SH"],
      allowed_least_preferred_security_ids: ["600003.SH"],
      required_preferred_evidence_ids: [preferredEvidence],
      required_least_preferred_evidence_ids: [leastEvidence],
      required_final_evidence_ids: [leastEvidence, preferredEvidence],
    };
    const schema = z
      .object({
        final_selection: buildStandardSectorSchema("semiconductor", "SELECTED", directive),
      })
      .strict();
    const llm = new SequenceLlm([new Error("400 Bad Request")]);

    await expect(
      invokeStrictStructured({
        llm: llm as never,
        schema,
        messages: messages(),
        agent: "semiconductor",
        stage: "final_selection",
        runId: "provider-sector-selected-runtime-binding",
        evidenceSnapshot: {
          evidenceLedger: [{ evidence_id: preferredEvidence }, { evidence_id: leastEvidence }],
          allowedResearchRuleIds: new Set([citation]),
          directive,
        },
        onAttempt: () => {},
      }),
    ).rejects.toBeInstanceOf(AgentRunContractError);

    const providerSchema = llm.schemas[0] as {
      properties: {
        final_selection: {
          properties: Record<string, Record<string, unknown>>;
        };
      };
    };
    const selected = providerSchema.properties.final_selection.properties;
    expect(selected.preferred_evidence_ids).toMatchObject({
      minItems: 1,
      maxItems: 1,
      prefixItems: [{ const: preferredEvidence }],
      items: false,
    });
    expect(selected.least_preferred_evidence_ids).toMatchObject({
      minItems: 1,
      maxItems: 1,
      prefixItems: [{ const: leastEvidence }],
      items: false,
    });
    expect(selected.research_rule_ref).toEqual({ type: "string", enum: [citation] });
    const preferredSecurity = selected.preferred_security as {
      properties: { picks: { items: unknown; maxItems: number } };
    };
    const leastPreferredSecurity = selected.least_preferred_security as {
      properties: { picks: { items: unknown; maxItems: number } };
    };
    expect(preferredSecurity.properties.picks.maxItems).toBe(1);
    expect(leastPreferredSecurity.properties.picks.maxItems).toBe(1);
    expect(preferredSecurity.properties.picks.items).toMatchObject({
      properties: { ts_code: { enum: directive.allowed_preferred_security_ids } },
    });
    expect(leastPreferredSecurity.properties.picks.items).toMatchObject({
      properties: { ts_code: { enum: directive.allowed_least_preferred_security_ids } },
    });
  });

  it("validates a nested selected Sector compact envelope before materialization", async () => {
    const preferredEvidence = `evidence:${"f".repeat(64)}`;
    const leastEvidence = `evidence:${"1".repeat(64)}`;
    const citation = "sector.semiconductor.soft.001";
    const directive = {
      selection_status: "SELECTED" as const,
      preferred_direction_id: "chip_design",
      least_preferred_direction_id: "discrete_devices",
      allowed_preferred_security_ids: [],
      allowed_least_preferred_security_ids: [],
      required_preferred_evidence_ids: [preferredEvidence],
      required_least_preferred_evidence_ids: [leastEvidence],
      required_final_evidence_ids: [leastEvidence, preferredEvidence],
    };
    const schema = z
      .object({
        final_selection: buildStandardSectorSchema("semiconductor", "SELECTED", directive),
      })
      .strict();
    const compact = {
      provider_contract: "SECTOR_SELECTED_COMPACT_V2",
      agent: "semiconductor",
      preferred_direction_id: "chip_design",
      preferred_direction_local_id: "chip_design",
      preferred_strength: 3,
      preferred_thesis: "Chip design has the strongest frozen evidence.",
      least_preferred_direction_id: "discrete_devices",
      least_preferred_direction_local_id: "discrete_devices",
      least_preferred_strength: 2,
      least_preferred_thesis: "Discrete devices has the weakest frozen evidence.",
      persistence_horizon: "WEEKS",
      confidence: 0.7,
      driver_summary: "The preferred direction leads across the frozen comparison.",
      risk_summary: "The frozen direction ordering may weaken as conditions change.",
      preferred_evidence_ids: [preferredEvidence],
      least_preferred_evidence_ids: [leastEvidence],
      research_rule_ref: citation,
      preferred_security: { status: "NO_QUALIFIED_SECURITY", abstention_confidence: 0.8 },
      least_preferred_security: { status: "NO_QUALIFIED_SECURITY", abstention_confidence: 0.8 },
      macro_input_attributions: {
        submission_summaries: Object.fromEntries(
          MACRO_AGENT_IDS.map((agentId) => [
            agentId,
            { claim_ref_used: null, effect: "NOT_MATERIAL" },
          ]),
        ),
        target_attributions: [],
      },
    };
    const attempts: AgentContractIssue[][] = [];
    const llm = new SequenceLlm([
      { final_selection: { ...compact, ignored_provider_field: true } },
      { final_selection: compact },
    ]);

    const result = await invokeStrictStructured({
      llm: llm as never,
      schema,
      messages: messages(),
      agent: "semiconductor",
      stage: "final_selection",
      runId: "provider-sector-selected-local-schema",
      evidenceSnapshot: {
        evidenceLedger: [{ evidence_id: preferredEvidence }, { evidence_id: leastEvidence }],
        allowedResearchRuleIds: new Set([citation]),
        directive,
      },
      onAttempt: (audit) => {
        attempts.push(audit.validation_issues);
      },
    });

    expect(result.audit.repair_count).toBe(1);
    expect(attempts[0]?.some((issue) => issue.validator === "zod_schema")).toBe(true);
    expect(result.output.final_selection.preferred_direction.direction_id).toBe("chip_design");
  });

  it("binds Superinvestor abstention evidence and citation to the runtime catalog", async () => {
    const evidence = `evidence:${"4".repeat(64)}`;
    const failedEvidence = `evidence:${"6".repeat(64)}`;
    const citation = `superinvestor-candidate-scope:${"5".repeat(64)}`;
    const llm = new SequenceLlm([new Error("400 Bad Request")]);

    await expect(
      invokeStrictStructured({
        llm: llm as never,
        schema: buildRuntimeSuperinvestorSchema("munger", []),
        messages: messages(),
        agent: "munger",
        stage: "agent_run",
        runId: "provider-superinvestor-runtime-binding",
        evidenceSnapshot: {
          evidenceLedger: [
            { evidence_id: evidence, freshness: "current", fallback: false },
            { evidence_id: failedEvidence, freshness: "tool_failed", fallback: false },
          ],
          allowedResearchRuleIds: new Set([citation]),
        },
        onAttempt: () => {},
      }),
    ).rejects.toBeInstanceOf(AgentRunContractError);

    const providerSchema = llm.schemas[0] as {
      properties: {
        evidence_id: Record<string, unknown>;
        research_rule_ref: Record<string, unknown>;
      };
    };
    expect(providerSchema.properties.evidence_id).toEqual({ type: "string", enum: [evidence] });
    expect(providerSchema.properties.research_rule_ref).toEqual({
      type: "string",
      enum: [citation],
    });

    const failedOnlyLlm = new SequenceLlm([new Error("400 Bad Request")]);
    await expect(
      invokeStrictStructured({
        llm: failedOnlyLlm as never,
        schema: buildRuntimeSuperinvestorSchema("munger", []),
        messages: messages(),
        agent: "munger",
        stage: "agent_run",
        runId: "provider-superinvestor-runtime-binding-empty",
        evidenceSnapshot: {
          evidenceLedger: [
            { evidence_id: failedEvidence, freshness: "tool_failed", fallback: false },
          ],
          allowedResearchRuleIds: new Set([citation]),
        },
        onAttempt: () => {},
      }),
    ).rejects.toThrow("SINGLE_EVIDENCE_RUNTIME_EVIDENCE_CATALOG_EMPTY");
  });

  it("binds full Decision claim evidence and citations to the runtime catalog", async () => {
    const evidence = `evidence:${"6".repeat(64)}`;
    const citation = `cio-candidate-universe:${"7".repeat(64)}`;
    const llm = new SequenceLlm([new Error("400 Bad Request")]);

    await expect(
      invokeStrictStructured({
        llm: llm as never,
        schema: CioProposalSubmissionSchema,
        messages: messages(),
        agent: "cio",
        stage: "cio_proposal",
        runId: "provider-cio-runtime-binding",
        evidenceSnapshot: {
          evidenceLedger: [{ evidence_id: evidence }],
          allowedResearchRuleIds: new Set([citation]),
        },
        onAttempt: () => {},
      }),
    ).rejects.toBeInstanceOf(AgentRunContractError);

    const providerSchema = llm.schemas[0];
    const evidenceArrays = namedPropertySchemas(providerSchema, "evidence_ids");
    const citationArrays = namedPropertySchemas(providerSchema, "research_rule_refs");
    expect(evidenceArrays.length).toBeGreaterThan(0);
    expect(citationArrays.length).toBeGreaterThan(0);
    expect(
      evidenceArrays.every((entry) =>
        expect.objectContaining({ type: "string", enum: [evidence] }).asymmetricMatch(entry.items),
      ),
    ).toBe(true);
    expect(
      citationArrays.every((entry) =>
        expect.objectContaining({ type: "string", enum: [citation] }).asymmetricMatch(entry.items),
      ),
    ).toBe(true);
  });

  it("selects the CIO non-empty-current union branch for nested Macro provider errors", async () => {
    const evidence = `evidence:${"8".repeat(64)}`;
    const claim = {
      claim_id: "cio-claim",
      claim_kind: "FACT" as const,
      statement: "The current position remains within the target allocation.",
      structured_conclusion: { state: "within target" },
      evidence_ids: [evidence],
      research_rule_refs: [],
    };
    const canonicalMacro = (agentId: string) => ({
      submission_summaries: Object.fromEntries(
        MACRO_AGENT_IDS.map((macroAgentId) => [
          macroAgentId,
          { claim_ref_used: null, effect: "NOT_MATERIAL" },
        ]),
      ),
      target_attributions: [
        {
          agent_id: agentId,
          target_type: "PORTFOLIO_DECISION",
          target_local_ref: "portfolio",
          claim_ref_used: "cio-claim",
          effect: "SUPPORTS",
        },
      ],
    });
    const providerOutput = (macroAgentId: string) => ({
      agent_id: "cio",
      decision_stage: "PROPOSAL",
      decision_disposition: "TARGET_PORTFOLIO",
      confidence: 0.7,
      cash_weight: 0.9,
      decision_reason: "Keep the current position within the target allocation.",
      target_positions: [
        {
          position_local_id: "position-1",
          ts_code: "600001.SH",
          target_weight: 0.1,
          position_decision: "HOLD",
          holding_period: "WEEKS",
          thesis_status: "INTACT",
          risk_flags: [],
          claim_refs: ["cio-claim"],
        },
      ],
      macro_input_attributions: canonicalMacro(macroAgentId),
      claims: [claim],
      claim_refs: ["cio-claim"],
    });
    const attempts: AgentContractIssue[][] = [];
    const llm = new SequenceLlm([providerOutput("semiconductor"), providerOutput("china")]);

    const result = await invokeStrictStructured({
      llm: llm as never,
      schema: CioProposalNonEmptyCurrentSubmissionSchema,
      messages: messages(),
      agent: "cio",
      stage: "cio_proposal",
      runId: "provider-cio-non-empty-current-union",
      evidenceSnapshot: {
        evidenceLedger: [{ evidence_id: evidence }],
        allowedResearchRuleIds: new Set<string>(),
      },
      onAttempt: (audit) => {
        attempts.push(audit.validation_issues);
      },
    });

    expect(attempts[0]).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          json_path: "$.macro_input_attributions.target_attributions[0].agent_id",
          reason_code: "ZOD_INVALID_VALUE",
        }),
      ]),
    );
    expect(attempts[0]?.some((issue) => issue.reason_code === "ZOD_INVALID_UNION")).toBe(false);
    expect(attempts[0]?.some((issue) => issue.json_path.includes("decision_disposition"))).toBe(
      false,
    );
    expect(result.audit.repair_count).toBe(1);
    expect(result.output.decision_disposition).toBe("TARGET_PORTFOLIO");
  });

  it("binds CIO final narrative and control resolutions to the runtime directive", async () => {
    const llm = new SequenceLlm([new Error("400 Bad Request")]);
    const directive = {
      contract_version: "cio_final_provider_control_directive_v2",
      decision_reason_max_length: 160,
      cro_action_local_refs: ["cro-action-a", "cro-action-b"],
      execution_assessment_local_refs: ["execution-assessment-a"],
      target_bounds: [
        {
          ts_code: "600001.SH",
          current_weight: 0.2,
          proposal_target_weight: 0.1,
          requested_delta_weight: -0.1,
          execution_status: "PARTIAL",
          max_executable_delta_weight: 0.08,
          direction: "DECREASE",
          target_weight_min: 0.12,
          target_weight_max: 0.2,
        },
      ],
    };

    await expect(
      invokeStrictStructured({
        llm: llm as never,
        schema: CioFinalSubmissionSchema,
        messages: messages(),
        agent: "cio",
        stage: "cio_final",
        runId: "provider-cio-final-control-binding",
        evidenceSnapshot: {
          evidenceLedger: [],
          allowedResearchRuleIds: new Set<string>(),
          cio_final_control_directive: directive,
        },
        onAttempt: () => {},
      }),
    ).rejects.toBeInstanceOf(AgentRunContractError);

    const providerSchema = llm.schemas[0];
    const decisionReasons = namedPropertySchemas(providerSchema, "decision_reason");
    expect(decisionReasons.length).toBeGreaterThan(0);
    expect(
      decisionReasons.every(
        (entry) =>
          entry.maxLength === directive.decision_reason_max_length &&
          String(entry.description).includes("160 Unicode characters"),
      ),
    ).toBe(true);

    const assertExactTuple = (
      propertyName: string,
      localRefField: string,
      expectedRefs: readonly string[],
    ) => {
      const arrays = namedPropertySchemas(providerSchema, propertyName);
      expect(arrays.length).toBeGreaterThan(0);
      for (const array of arrays) {
        expect(array.minItems).toBe(expectedRefs.length);
        expect(array.maxItems).toBe(expectedRefs.length);
        expect(array.items).toBe(false);
        const prefixItems = array.prefixItems as Array<{ properties: Record<string, unknown> }>;
        expect(
          prefixItems.map(
            (item) => (item.properties[localRefField] as { const?: unknown } | undefined)?.const,
          ),
        ).toEqual(expectedRefs);
      }
    };
    assertExactTuple(
      "cro_control_resolutions",
      "cro_action_local_ref",
      directive.cro_action_local_refs,
    );
    assertExactTuple(
      "execution_control_resolutions",
      "execution_assessment_local_ref",
      directive.execution_assessment_local_refs,
    );
    const targetPositions = namedPropertySchemas(providerSchema, "target_positions");
    const targetWeightSchemas = targetPositions.flatMap((entry) => {
      const items = entry.items;
      if (items === null || typeof items !== "object" || Array.isArray(items)) return [];
      const variants = (items as { anyOf?: unknown[] }).anyOf;
      if (!Array.isArray(variants)) return [];
      return variants.flatMap((variant) => {
        if (variant === null || typeof variant !== "object" || Array.isArray(variant)) return [];
        const properties = (variant as { properties?: unknown }).properties;
        if (properties === null || typeof properties !== "object" || Array.isArray(properties)) {
          return [];
        }
        const targetWeight = (properties as Record<string, unknown>).target_weight;
        return targetWeight !== null &&
          typeof targetWeight === "object" &&
          !Array.isArray(targetWeight)
          ? [targetWeight as Record<string, unknown>]
          : [];
      });
    });
    expect(targetWeightSchemas).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          minimum: 0.12,
          maximum: 0.2,
          description: expect.stringContaining("abs(target_weight-current_weight)"),
        }),
      ]),
    );
    const providerValidationSchema = z.fromJSONSchema(
      providerSchema as Parameters<typeof z.fromJSONSchema>[0],
    );
    const finalOutput = (targetWeight: number) => ({
      agent_id: "cio",
      decision_stage: "FINAL",
      decision_disposition: "TARGET_PORTFOLIO",
      confidence: 0.7,
      cash_weight: 0.9,
      decision_reason: "Reduce the position within the frozen execution capacity.",
      target_positions: [
        {
          position_local_id: "position-1",
          ts_code: "600001.SH",
          target_weight: targetWeight,
          position_decision: "REDUCE",
          holding_period: "WEEKS",
          thesis_status: "INTACT",
          risk_flags: [],
          claim_refs: ["claim-1"],
        },
      ],
      macro_input_attributions: {
        submission_summaries: Object.fromEntries(
          MACRO_AGENT_IDS.map((macroAgentId) => [
            macroAgentId,
            { claim_ref_used: null, effect: "NOT_MATERIAL" },
          ]),
        ),
        target_attributions: [
          {
            agent_id: MACRO_AGENT_IDS[0],
            target_type: "PORTFOLIO_DECISION",
            target_local_ref: "portfolio",
            claim_ref_used: "claim-1",
            effect: "SUPPORTS",
          },
        ],
      },
      claims: [
        {
          claim_id: "claim-1",
          claim_kind: "FACT",
          statement: "The frozen execution capacity supports the bounded reduction.",
          structured_conclusion: { status: "supported" },
          evidence_ids: ["evidence-1"],
          research_rule_refs: [],
        },
      ],
      claim_refs: ["claim-1"],
      cro_control_resolutions: [
        {
          cro_action_local_ref: "cro-action-a",
          resolution: "COMPLIED",
          reason: "The final target respects the CRO control.",
          claim_refs: ["claim-1"],
        },
        {
          cro_action_local_ref: "cro-action-b",
          resolution: "COMPLIED",
          reason: "The final target respects the second CRO control.",
          claim_refs: ["claim-1"],
        },
      ],
      execution_control_resolutions: [
        {
          execution_assessment_local_ref: "execution-assessment-a",
          resolution: "COMPLIED",
          reason: "The final target stays within the partial execution cap.",
          claim_refs: ["claim-1"],
        },
      ],
    });
    const rejected = providerValidationSchema.safeParse(finalOutput(0.1));
    expect(rejected.success).toBe(false);
    expect(providerValidationSchema.safeParse(finalOutput(0.12)).success).toBe(true);
  });

  it("seals empty CIO final control sets and rejects a missing directive", async () => {
    const emptyLlm = new SequenceLlm([new Error("400 Bad Request")]);
    await expect(
      invokeStrictStructured({
        llm: emptyLlm as never,
        schema: CioFinalSubmissionSchema,
        messages: messages(),
        agent: "cio",
        stage: "cio_final",
        runId: "provider-cio-final-empty-controls",
        evidenceSnapshot: {
          cio_final_control_directive: {
            contract_version: "cio_final_provider_control_directive_v2",
            decision_reason_max_length: 160,
            cro_action_local_refs: [],
            execution_assessment_local_refs: [],
            target_bounds: [],
          },
        },
        onAttempt: () => {},
      }),
    ).rejects.toBeInstanceOf(AgentRunContractError);
    for (const propertyName of [
      "cro_control_resolutions",
      "execution_control_resolutions",
    ] as const) {
      const arrays = namedPropertySchemas(emptyLlm.schemas[0], propertyName);
      expect(arrays.length).toBeGreaterThan(0);
      expect(
        arrays.every(
          (array) =>
            array.minItems === 0 &&
            array.maxItems === 0 &&
            array.items === false &&
            Array.isArray(array.prefixItems) &&
            array.prefixItems.length === 0,
        ),
      ).toBe(true);
    }

    const missingLlm = new SequenceLlm([new Error("must not invoke")]);
    await expect(
      invokeStrictStructured({
        llm: missingLlm as never,
        schema: CioFinalSubmissionSchema,
        messages: messages(),
        agent: "cio",
        stage: "cio_final",
        runId: "provider-cio-final-missing-controls",
        evidenceSnapshot: {},
        onAttempt: () => {},
      }),
    ).rejects.toThrow("CIO_FINAL_CONTROL_DIRECTIVE_MISSING");
    expect(missingLlm.schemas).toHaveLength(0);
  });

  it("binds AutoExec assessments to exact frozen intents and preserves BLOCKED zero control", async () => {
    const directive = {
      schema_version: "execution_frozen_order_intent_set_v2",
      frozen_object_set_id: "order-intent-set:structured-smoke",
      frozen_object_set_hash: `sha256:${"2".repeat(64)}`,
      intents: [
        {
          order_intent_ref: "order-intent:structured-smoke",
          ts_code: "600001.SH",
          requested_delta_weight: 0.1,
        },
      ],
    };
    const llm = new SequenceLlm([new Error("400 Bad Request")]);
    await expect(
      invokeStrictStructured({
        llm: llm as never,
        schema: AutonomousExecutionSubmissionSchema,
        messages: messages(),
        agent: "autonomous_execution",
        stage: "execution_feasibility",
        runId: "provider-autonomous-exact-intent-binding",
        evidenceSnapshot: { autonomous_execution_control_directive: directive },
        onAttempt: () => {},
      }),
    ).rejects.toBeInstanceOf(AgentRunContractError);

    const providerSchema = llm.schemas[0];
    const arrays = namedPropertySchemas(providerSchema, "order_assessments");
    const nonEmpty = arrays.filter((entry) => entry.minItems === 1);
    expect(nonEmpty.length).toBeGreaterThan(0);
    for (const array of nonEmpty) {
      const prefixItems = array.prefixItems as Array<{
        properties: Record<string, Record<string, unknown>>;
      }>;
      expect(prefixItems).toHaveLength(1);
      expect(prefixItems[0]?.properties.order_intent_ref).toMatchObject({
        const: "order-intent:structured-smoke",
      });
      expect(prefixItems[0]?.properties.ts_code).toMatchObject({ const: "600001.SH" });
      expect(prefixItems[0]?.properties.requested_delta_weight).toMatchObject({ const: 0.1 });
      expect(array.items).toBe(false);
      expect(array.maxItems).toBe(1);
    }

    const providerValidationSchema = z.fromJSONSchema(
      providerSchema as Parameters<typeof z.fromJSONSchema>[0],
    );
    const claim = {
      claim_id: "claim-1",
      claim_kind: "FACT",
      statement: "The frozen order intent is executable.",
      structured_conclusion: { status: "supported" },
      evidence_ids: ["evidence-1"],
      research_rule_refs: [],
    };
    const intent = directive.intents[0];
    if (!intent) throw new Error("expected a frozen order intent");
    const assessment = {
      assessment_local_id: "assessment-1",
      order_intent_ref: intent.order_intent_ref,
      ts_code: intent.ts_code,
      requested_delta_weight: intent.requested_delta_weight,
      feasibility: "FEASIBLE",
      feasibility_confidence: 0.5,
      predicted_cost_bps: 10,
      max_executable_delta_weight: 0.1,
      recommended_slice_count: 1,
      reason: "The frozen intent is executable.",
      claim_refs: ["claim-1"],
    };
    const valid = {
      agent_id: "autonomous_execution",
      execution_disposition: "ORDERS_ASSESSED",
      order_assessments: [assessment],
      confidence: 0.5,
      claims: [claim],
      claim_refs: ["claim-1"],
    };
    expect(providerValidationSchema.safeParse(valid).success).toBe(true);
    expect(
      providerValidationSchema.safeParse({
        ...valid,
        order_assessments: [{ ...assessment, order_intent_ref: "claim-1" }],
      }).success,
    ).toBe(false);
    expect(
      providerValidationSchema.safeParse({
        ...valid,
        order_assessments: [{ ...assessment, order_intent_ref: "candidate-1" }],
      }).success,
    ).toBe(false);
    expect(
      AutonomousExecutionSubmissionSchema.safeParse({
        ...valid,
        execution_disposition: "BLOCKED",
        order_assessments: [
          {
            ...assessment,
            feasibility: "BLOCKED",
            max_executable_delta_weight: 0,
            recommended_slice_count: 0,
          },
        ],
      }).success,
    ).toBe(true);
    expect(
      AutonomousExecutionSubmissionSchema.safeParse({
        ...valid,
        execution_disposition: "BLOCKED",
        order_assessments: [
          { ...assessment, feasibility: "BLOCKED", max_executable_delta_weight: 0.01 },
        ],
      }).success,
    ).toBe(false);
  });

  it("derives a deterministic structured-smoke AutoExec directive without an opportunity binding", () => {
    const state = autonomousExecutionDirectiveState();
    const first = buildAutonomousExecutionProviderControlDirective(state);
    const second = buildAutonomousExecutionProviderControlDirective(state);

    expect(first).toEqual(second);
    expect(first).toMatchObject({
      schema_version: "execution_frozen_order_intent_set_v2",
      frozen_object_set_id: expect.stringMatching(/^order-intent-set:/),
      frozen_object_set_hash: expect.stringMatching(/^sha256:[0-9a-f]{64}$/),
      intents: [
        {
          order_intent_ref: expect.any(String),
          ts_code: "600001.SH",
          requested_delta_weight: 0.1,
        },
      ],
    });
  });

  it("keeps production AutoExec fail-closed when its opportunity binding is missing", () => {
    expect(() =>
      buildAutonomousExecutionProviderControlDirective(
        autonomousExecutionDirectiveState({ production: true }),
      ),
    ).toThrow(
      "autonomous_execution provider directive requires frozen execution opportunity and state",
    );
  });

  it.each([
    ["cro", CroSubmissionSchema],
    ["alpha_discovery", AlphaDiscoverySubmissionSchema],
    ["autonomous_execution", AutonomousExecutionSubmissionSchema],
    ["cio_proposal", CioProposalSubmissionSchema],
    ["cio_final", CioFinalSubmissionSchema],
  ] as const)("publishes finite Decision provider bounds for %s", async (name, schema) => {
    const providerSchema = await capturedProviderSchema(schema, name);
    for (const field of ["claims", "claim_refs"] as const) {
      const fields = namedPropertySchemas(providerSchema, field);
      expect(fields.length).toBeGreaterThan(0);
      expect(
        fields.every(
          (entry) =>
            typeof entry.maxItems === "number" &&
            entry.maxItems > 0 &&
            entry.maxItems <= (field === "claims" ? 2 : 1),
        ),
      ).toBe(true);
    }
    for (const field of ["summary", "reason", "thesis", "decision_reason"] as const) {
      expect(
        namedPropertySchemas(providerSchema, field).every(
          (entry) => typeof entry.maxLength === "number" && entry.maxLength <= 320,
        ),
      ).toBe(true);
    }
    if (name === "autonomous_execution") {
      const assessments = namedPropertySchemas(providerSchema, "order_assessments");
      expect(assessments.length).toBeGreaterThanOrEqual(2);
      expect(
        assessments.some(
          (entry) => entry.type === "array" && entry.minItems === 0 && entry.maxItems === 0,
        ),
      ).toBe(true);
      expect(
        assessments.some(
          (entry) => entry.type === "array" && entry.minItems === 1 && entry.maxItems === 1,
        ),
      ).toBe(true);
      const costs = namedPropertySchemas(providerSchema, "predicted_cost_bps");
      expect(costs.length).toBeGreaterThan(0);
      expect(
        costs.every(
          (entry) => entry.type === "number" && entry.minimum === 0 && entry.maximum === 10_000,
        ),
      ).toBe(true);
      const slices = namedPropertySchemas(providerSchema, "recommended_slice_count");
      expect(slices.length).toBeGreaterThan(0);
      expect(
        slices.every(
          (entry) => entry.type === "integer" && entry.minimum === 0 && entry.maximum === 100,
        ),
      ).toBe(true);
    }
    if (name === "cro") {
      const dispositions = namedPropertySchemas(providerSchema, "review_disposition");
      expect(
        dispositions.some((entry) =>
          (entry.enum as unknown[] | undefined)?.includes("NO_RISK_ACTION"),
        ),
      ).toBe(true);
    }
    if (name === "autonomous_execution") {
      const dispositions = namedPropertySchemas(providerSchema, "execution_disposition");
      expect(
        dispositions.some(
          (entry) =>
            (entry.enum as unknown[] | undefined)?.includes("NO_EXECUTION_ACTION") ||
            entry.const === "NO_EXECUTION_ACTION",
        ),
      ).toBe(true);
    }
    if (name === "cio_proposal" || name === "cio_final") {
      const riskFlags = namedPropertySchemas(providerSchema, "risk_flags");
      expect(riskFlags.length).toBeGreaterThan(0);
      expect(
        riskFlags.every(
          (entry) =>
            entry.maxItems === 20 &&
            typeof entry.items === "object" &&
            (entry.items as Record<string, unknown>).maxLength === 128,
        ),
      ).toBe(true);
    }
  });
});
