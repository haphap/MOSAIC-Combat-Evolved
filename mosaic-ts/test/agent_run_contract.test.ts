import { AIMessage, HumanMessage, SystemMessage } from "@langchain/core/messages";
import { describe, expect, it } from "vitest";
import { z } from "zod";
import {
  type AgentContractIssue,
  AgentRunContractError,
  assertStructuredOutputCapability,
  invokeStrictStructured,
} from "../src/agents/helpers/agent_run_contract.js";

const Schema = z.object({
  disposition: z.enum(["ITEMS", "NONE"]),
  items: z.array(z.string()),
  claim_refs: z.array(z.string()).min(1),
});

class SequenceLlm {
  readonly calls: unknown[] = [];
  readonly schemas: unknown[] = [];
  readonly structuredOptions: unknown[] = [];

  constructor(
    private readonly outputs: unknown[],
    private readonly constructionError?: Error,
  ) {}

  withStructuredOutput(
    schema: unknown,
    options: unknown,
  ): { invoke: (input: unknown) => Promise<unknown> } {
    if (this.constructionError) throw this.constructionError;
    this.schemas.push(schema);
    this.structuredOptions.push(options);
    return {
      invoke: async (input: unknown) => {
        this.calls.push(input);
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

function messages(): [SystemMessage, HumanMessage] {
  return [new SystemMessage("fixed prompt"), new HumanMessage("immutable evidence")];
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
    expect(JSON.stringify(llm.calls[1])).toContain("Structured repair 1/3");
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
    await expect(
      run(llm, {
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
      }),
    ).rejects.toMatchObject({
      audit: { stop_reason: "repair_budget_exhausted", attempt_count: 4, repair_count: 3 },
    });
    expect(llm.calls).toHaveLength(4);
  });

  it("stops immediately on byte-equivalent output", async () => {
    const invalid = { disposition: "ITEMS", items: [], claim_refs: ["claim-1"] };
    const llm = new SequenceLlm([invalid, invalid, invalid]);
    await expect(run(llm)).rejects.toMatchObject({
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

  it("terminates a private policy failure without replaying a consumed capability", async () => {
    const llm = new SequenceLlm([
      { disposition: "ITEMS", items: ["x"], claim_refs: ["claim-1"] },
      { disposition: "ITEMS", items: ["retry"], claim_refs: ["claim-1"] },
    ]);
    await expect(
      run(llm, {
        validate: (output: z.infer<typeof Schema>) => ({
          output,
          issues: [
            {
              validator: "private_knot_runtime_v1",
              reason_code: "PRIVATE_KNOT_POLICY_REJECTED",
              json_path: "$",
              message: "one-use private policy rejected the candidate",
            },
          ],
        }),
      }),
    ).rejects.toMatchObject({
      audit: {
        status: "error",
        stop_reason: "private_policy_failure",
        attempt_count: 1,
        reason_codes: ["PRIVATE_KNOT_POLICY_REJECTED"],
      },
    });
    expect(llm.calls).toHaveLength(1);
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
    expect(properties.claims?.maxItems).toBe(8);
  });
});
