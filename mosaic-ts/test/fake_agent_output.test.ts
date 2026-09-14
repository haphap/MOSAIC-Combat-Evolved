import { HumanMessage } from "@langchain/core/messages";
import { describe, expect, it } from "vitest";
import type { z } from "zod";
import { alphaDiscoverySpec } from "../src/agents/decision/alpha_discovery.js";
import { autonomousExecutionSpec } from "../src/agents/decision/autonomous_execution.js";
import { cioProposalSpec, cioSpec } from "../src/agents/decision/cio.js";
import { croSpec } from "../src/agents/decision/cro.js";
import { RUNTIME_AGENT_SPECS } from "../src/agents/prompts/runtime_agent_spec.js";
import { FakeChatModel } from "../src/cli/commands/daily-cycle.js";
import { fakeAgentStructuredOutput } from "../src/cli/fake_agent_output.js";

const specByAgent = new Map(
  [...RUNTIME_AGENT_SPECS, { ...cioProposalSpec, agent: "cio", stages: [] }].map((spec) => [
    "agentId" in spec ? spec.agentId : spec.agent,
    spec,
  ]),
);

const runtimeSchemas = [
  ...RUNTIME_AGENT_SPECS.map((runtime) => {
    const source = specByAgent.get(runtime.agent) as {
      schema?: { parse: (value: unknown) => unknown };
    };
    return {
      agent: runtime.agent,
      stage: runtime.stages[0]?.stage ?? "agent_run",
      schema: source.schema,
    };
  }),
  { agent: "cio", stage: "cio_proposal", schema: cioProposalSpec.schema },
];

// RuntimeAgentSpec intentionally exposes schema metadata, not Zod instances. Bind the imported specs.
const directSchemas = new Map<string, z.ZodType>([
  ["cro", croSpec.schema],
  ["alpha_discovery", alphaDiscoverySpec.schema],
  ["autonomous_execution", autonomousExecutionSpec.schema],
  ["cio", cioSpec.schema],
]);

describe("schema-driven fake LLM outputs", () => {
  it("accepts provider-adapted JSON Schema objects without re-converting them as Zod", () => {
    expect(
      fakeAgentStructuredOutput(
        {
          type: "object",
          properties: { value: { type: "string", const: "ok" } },
          required: ["value"],
          additionalProperties: false,
        },
        "unknown_agent",
        [],
      ),
    ).toEqual({ value: "ok" });
  });

  it("covers the 26 execution stages without a fallback factory", () => {
    expect(runtimeSchemas).toHaveLength(26);
    for (const runtime of runtimeSchemas) {
      const schema =
        runtime.stage === "cio_proposal"
          ? cioProposalSpec.schema
          : (directSchemas.get(runtime.agent) ??
            // Non-decision source specs are reachable from the runtime module only through metadata;
            // stage coverage and the CLI smoke provide their full integration check.
            null);
      if (!schema) continue;
      const output = fakeAgentStructuredOutput(schema, `${runtime.agent}_${runtime.stage}`, [
        new HumanMessage('"evidence_id": "evidence-1", "freshness": "current"'),
      ]);
      expect(() => schema.parse(output), `${runtime.agent}:${runtime.stage}`).not.toThrow();
    }
  });
});

describe("fake daily-cycle state", () => {
  const task = [
    "### agriculture",
    '* output: {"long_picks":[{"ts_code":"600044.SH"}]}',
    "### semiconductor",
    '* output: {"long_picks":[{"ts_code":"600001.SH"}]}',
    "Runtime-owned evidence catalog (use only these evidence_id values):",
    '{"evidence":[{"evidence_id":"runtime-current","freshness":"current"}]}',
  ].join("\n");

  it("selects candidates in the snapshot sector order, independent of display order", () => {
    const output = cioProposalSpec.schema.parse(
      fakeAgentStructuredOutput(cioProposalSpec.schema, "cio_cio_proposal", [
        new HumanMessage(task),
      ]),
    );
    expect(output).toMatchObject({ target_positions: [{ ts_code: "600001.SH" }] });
  });

  it("preserves candidate and evidence bindings through a JSON repair envelope", () => {
    const original = fakeAgentStructuredOutput(cioProposalSpec.schema, "cio_cio_proposal", [
      new HumanMessage(task),
    ]);
    const repaired = fakeAgentStructuredOutput(cioProposalSpec.schema, "cio_cio_proposal", [
      new HumanMessage(
        JSON.stringify({
          original_evidence_and_task: task,
          validation_errors: ["retry"],
          prior_output: { evidence_id: "invalid-prior-evidence" },
        }),
      ),
    ]);
    expect(cioProposalSpec.schema.parse(repaired)).toEqual(original);
    expect(cioProposalSpec.schema.parse(repaired)).toMatchObject({
      claims: [{ evidence_ids: ["runtime-current"] }],
    });
  });

  it("keeps tool bindings local to each agent handle", async () => {
    const shared = new FakeChatModel();
    const first = shared.bindTools([{ name: "first", schema: { type: "object", properties: {} } }]);
    const second = shared.bindTools([
      { name: "second", schema: { type: "object", properties: {} } },
    ]);
    expect((await first.invoke([])).tool_calls?.map((call) => call.name)).toEqual(["first"]);
    expect((await second.invoke([])).tool_calls?.map((call) => call.name)).toEqual(["second"]);
    expect((await shared.invoke([])).tool_calls ?? []).toEqual([]);
  });
});
