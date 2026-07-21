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
import { createMacroSubmissionSchema } from "../src/agents/macro/_contracts.js";
import { buildStandardSectorSchema } from "../src/agents/sector/_schemas.js";
import { RelationshipMapperSchema } from "../src/agents/sector/relationship_mapper.js";
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

async function capturedProviderSchema(
  schema: z.ZodType<unknown>,
  name: string,
  evidenceSnapshot: unknown = {
    evidenceLedger: [{ evidence_id: `evidence:${"a".repeat(64)}` }],
    allowedResearchRuleIds: new Set<string>(),
  },
): Promise<unknown> {
  const llm = new SequenceLlm([new Error("400 Bad Request")]);
  await expect(
    invokeStrictStructured({
      llm: llm as never,
      schema,
      messages: messages(),
      agent: name,
      stage: "agent_run",
      runId: `provider-schema-${name}`,
      evidenceSnapshot,
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

  it("repairs provider JSON parse failures without mistaking a character position for HTTP 429", async () => {
    const llm = new SequenceLlm([
      new SyntaxError("Expected double-quoted property name in JSON at position 429"),
      { disposition: "ITEMS", items: ["fixed"], claim_refs: ["claim-1"] },
    ]);
    const result = await run(llm);
    expect(result.audit.output_source).toBe("structured_repair");
    expect(result.audit.repair_count).toBe(1);
    expect(result.audit.attempts[0]?.validation_issues).toEqual([
      expect.objectContaining({ reason_code: "STRUCTURED_OUTPUT_INVALID" }),
    ]);
    expect(llm.calls).toHaveLength(2);
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

  it("removes adapter-added uniqueItems before provider binding", async () => {
    const providerSchema = await capturedProviderSchema(
      RelationshipMapperSchema,
      "relationship_mapper",
    );
    expect(JSON.stringify(providerSchema)).not.toContain("uniqueItems");
  });

  it("binds compact Sector final evidence legs to the exact runtime directive", async () => {
    const mainEvidence = `evidence:${"a".repeat(64)}`;
    const coverageEvidence = "coverage-evidence-1";
    const schema = z
      .object({
        final_selection: buildStandardSectorSchema("energy", "SELECTED", {
          selection_status: "SELECTED",
          preferred_direction_id: "coal",
          least_preferred_direction_id: "oil_gas",
          allowed_preferred_security_ids: [],
          allowed_least_preferred_security_ids: [],
        }),
      })
      .strict();
    const providerSchema = (await capturedProviderSchema(schema, "energy", {
      evidenceLedger: [{ evidence_id: mainEvidence }, { evidence_id: coverageEvidence }],
      allowedResearchRuleIds: new Set<string>(),
      directive: {
        required_preferred_evidence_ids: [mainEvidence, coverageEvidence],
        required_least_preferred_evidence_ids: [mainEvidence],
        required_final_evidence_ids: [mainEvidence, coverageEvidence],
      },
    })) as {
      properties: {
        final_selection: {
          properties: Record<string, { prefixItems?: Array<{ const: string }> }>;
        };
      };
    };
    const final = providerSchema.properties.final_selection.properties;
    expect(final.preferred_evidence_ids?.prefixItems?.map((item) => item.const)).toEqual([
      coverageEvidence,
      mainEvidence,
    ]);
    expect(final.least_preferred_evidence_ids?.prefixItems?.map((item) => item.const)).toEqual([
      mainEvidence,
    ]);
    expect(final.final_evidence_ids?.prefixItems?.map((item) => item.const)).toEqual([
      coverageEvidence,
      mainEvidence,
    ]);
    expect(final.research_rule_ref).toEqual({ type: "null" });
    expect(final.claim_kind).toEqual({ type: "string", enum: ["FACT", "EVENT"] });
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
        claim_kind: "FACT",
        statement: "The component evidence supports a cautious assessment",
        state: "The component state is mixed",
        a_share_transmission: "The component has a balanced A-share transmission",
        evidence_id: evidenceId,
        research_rule_ref: null,
        snapshot_echo: null,
      })),
    };
    const llm = new SequenceLlm([providerOutput]);
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
        minLength: 12,
        maxLength: 96,
        pattern: "^[^0-9０-９%％\\r\\n]{12,96}$",
      });
      expect(component.properties.statement).toMatchObject({
        type: "string",
        minLength: 24,
        maxLength: 160,
        pattern: "^[^0-9０-９%％\\r\\n]{24,160}$",
      });
      expect(component.properties.state).toMatchObject({
        type: "string",
        minLength: 16,
        maxLength: 128,
        pattern: "^[^0-9０-９%％\\r\\n]{16,128}$",
      });
      expect(component.properties.a_share_transmission).toMatchObject({
        type: "string",
        minLength: 24,
        maxLength: 160,
        pattern: "^[^0-9０-９%％\\r\\n]{24,160}$",
      });
      expect(component.properties.evidence_id).toMatchObject({
        type: "string",
        enum: [evidenceId],
      });
      expect(component.properties.research_rule_ref).toEqual({ type: "null" });
      expect(component.properties.claim_kind).toEqual({
        type: "string",
        enum: ["FACT", "EVENT"],
      });
      expect(component.properties.snapshot_echo).toEqual({ type: "null" });
    }
  });

  it("reuses the evidence-bound Macro provider schema during structured repair", async () => {
    const schema = createMacroSubmissionSchema("us_economy");
    const base = macroSubmission("us_economy");
    if (base.mode !== "COMPONENTS") throw new Error("component fixture required");
    const evidenceId = `evidence:${"b".repeat(64)}`;
    const repairedOutput = {
      provider_contract: "MACRO_COMPONENTS_COMPACT_V1",
      mode: "COMPONENTS",
      components: base.components.map((component) => ({
        component: component.component,
        signal: { direction: "NEUTRAL", strength: 0 },
        persistence_horizon: "WEEKS",
        confidence: 0.7,
        channel: "A-share risk premium",
        claim_kind: "FACT",
        statement: "The component evidence supports a cautious assessment",
        state: "The component state is mixed",
        a_share_transmission: "The component has a balanced A-share transmission",
        evidence_id: evidenceId,
        research_rule_ref: null,
        snapshot_echo: null,
      })),
    };
    const llm = new SequenceLlm([
      { provider_contract: "MACRO_COMPONENTS_COMPACT_V1", mode: "COMPONENTS", components: [] },
      repairedOutput,
    ]);

    const result = await invokeStrictStructured({
      llm: llm as never,
      schema,
      messages: messages(),
      agent: "us_economy",
      stage: "agent_run",
      runId: "provider-macro-components-repair",
      evidenceSnapshot: {
        evidenceLedger: [{ evidence_id: evidenceId }],
        allowedResearchRuleIds: new Set<string>(),
      },
      onAttempt: () => {},
    });

    expect(result.audit.output_source).toBe("structured_repair");
    expect(result.audit.repair_count).toBe(1);
    expect(JSON.stringify(llm.calls[1])).toContain(evidenceId);
    expect(JSON.stringify(llm.calls[1])).toContain("fixed prompt");
  });

  it("canonicalizes named Macro tenors without accepting numeric facts generally", async () => {
    const schema = createMacroSubmissionSchema("central_bank");
    const base = macroSubmission("central_bank");
    if (base.mode !== "COMPONENTS") throw new Error("component fixture required");
    const evidenceId = `evidence:${"c".repeat(64)}`;
    const providerOutput = {
      provider_contract: "MACRO_COMPONENTS_COMPACT_V1",
      mode: "COMPONENTS",
      components: base.components.map((component, index) => ({
        component: component.component,
        signal: { direction: "NEUTRAL", strength: 0 },
        persistence_horizon: "WEEKS",
        confidence: 0.7,
        channel: "Long-term rates transmit through equity discount rates.",
        claim_kind: "FACT",
        statement:
          index === 0
            ? "十年期美债曲线显示长端利率压力仍然存在。"
            : "Current policy evidence supports a cautious assessment.",
        state: "The observed component state remains mixed.",
        a_share_transmission: "The component has a balanced A-share transmission.",
        evidence_id: evidenceId,
        research_rule_ref: null,
        snapshot_echo: null,
      })),
    };
    const result = await invokeStrictStructured({
      llm: new SequenceLlm([providerOutput]) as never,
      schema,
      messages: messages(),
      agent: "central_bank",
      stage: "agent_run",
      runId: "provider-macro-tenor-canonicalization",
      evidenceSnapshot: {
        evidenceLedger: [{ evidence_id: evidenceId }],
        allowedResearchRuleIds: new Set<string>(),
      },
      onAttempt: () => {},
    });

    expect(result.audit.output_source).toBe("structured_primary");
    expect(result.output.claims[0]?.statement).toContain("长期美债曲线");
    expect(result.output.claims[0]?.statement).not.toContain("十年期");
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
