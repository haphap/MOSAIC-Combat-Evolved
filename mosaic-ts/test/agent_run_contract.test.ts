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
});
