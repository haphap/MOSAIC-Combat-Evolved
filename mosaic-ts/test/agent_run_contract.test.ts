import { AIMessage, HumanMessage, SystemMessage } from "@langchain/core/messages";
import { describe, expect, it } from "vitest";
import { z } from "zod";
import {
  AlphaDiscoverySubmissionSchema,
  AutonomousExecutionSubmissionSchema,
  CioFinalSubmissionSchema,
  CioProposalSubmissionSchema,
  CroSubmissionSchema,
} from "../src/agents/decision/submission_schemas.js";
import {
  type AgentContractIssue,
  AgentRunContractError,
  assertStructuredOutputCapability,
  invokeStrictStructured,
} from "../src/agents/helpers/agent_run_contract.js";
import { canonicalStructuredRepairDirectiveManifest } from "../src/agents/helpers/structured_repair_directives.js";
import { createMacroSubmissionSchema, MACRO_AGENT_IDS } from "../src/agents/macro/_contracts.js";
import {
  buildStandardSectorSchema,
  RelationshipMapperSchema,
} from "../src/agents/sector/_schemas.js";
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

class PromptJsonLlm {
  readonly promptCalls: unknown[] = [];
  structuredCalls = 0;

  constructor(private readonly promptOutputs: unknown[]) {}

  withStructuredOutput(): { invoke: () => Promise<never> } {
    return {
      invoke: async () => {
        this.structuredCalls += 1;
        throw new Error("400 invalid_request_error: this response_format type is unavailable now");
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
                contract_version: "cio_final_provider_control_directive_v1",
                decision_reason_max_length: 160,
                cro_action_local_refs: [],
                execution_assessment_local_refs: [],
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

  it("negotiates strict prompt JSON when response_format is unavailable", async () => {
    const llm = new PromptJsonLlm([
      { preflight: "ok" },
      { disposition: "ITEMS", items: ["x"], claim_refs: ["claim-1"] },
    ]);

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
      channel: "Market participation remains mixed",
      statement: "The frozen breadth evidence supports a mixed market assessment",
      subject: "market breadth",
      state: "Participation remains mixed",
      a_share_transmission: "Broad participation has not established a durable market impulse",
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
      schema: createMacroSubmissionSchema("market_breadth"),
      messages: messages(),
      agent: "market_breadth",
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

  it("fails closed before provider invocation when Macro runtime evidence is empty", async () => {
    const llm = new SequenceLlm([]);
    await expect(
      invokeStrictStructured({
        llm: llm as never,
        schema: createMacroSubmissionSchema("geopolitical"),
        messages: messages(),
        agent: "geopolitical",
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

  it("binds Relationship compact evidence and citation to the runtime catalog", async () => {
    const evidence = `evidence:${"2".repeat(64)}`;
    const citation = `relationship-opportunity:${"3".repeat(64)}`;
    const llm = new SequenceLlm([new Error("400 Bad Request")]);

    await expect(
      invokeStrictStructured({
        llm: llm as never,
        schema: RelationshipMapperSchema,
        messages: messages(),
        agent: "relationship_mapper",
        stage: "agent_run",
        runId: "provider-relationship-runtime-binding",
        evidenceSnapshot: {
          evidenceLedger: [{ evidence_id: evidence }],
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
  });

  it("binds Superinvestor abstention evidence and citation to the runtime catalog", async () => {
    const evidence = `evidence:${"4".repeat(64)}`;
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
          evidenceLedger: [{ evidence_id: evidence }],
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

  it("binds CIO final narrative and control resolutions to the runtime directive", async () => {
    const llm = new SequenceLlm([new Error("400 Bad Request")]);
    const directive = {
      contract_version: "cio_final_provider_control_directive_v1",
      decision_reason_max_length: 160,
      cro_action_local_refs: ["cro-action-a", "cro-action-b"],
      execution_assessment_local_refs: ["execution-assessment-a"],
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
            contract_version: "cio_final_provider_control_directive_v1",
            decision_reason_max_length: 160,
            cro_action_local_refs: [],
            execution_assessment_local_refs: [],
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
      expect(assessments.length).toBeGreaterThan(0);
      expect(
        assessments.every(
          (entry) => entry.type === "array" && entry.minItems === 1 && entry.maxItems === 50,
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
