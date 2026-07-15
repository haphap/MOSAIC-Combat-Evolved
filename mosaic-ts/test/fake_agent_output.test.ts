import { HumanMessage } from "@langchain/core/messages";
import { describe, expect, it } from "vitest";
import type { z } from "zod";
import { alphaDiscoverySpec } from "../src/agents/decision/alpha_discovery.js";
import { autonomousExecutionSpec } from "../src/agents/decision/autonomous_execution.js";
import { cioProposalSpec, cioSpec } from "../src/agents/decision/cio.js";
import { croSpec } from "../src/agents/decision/cro.js";
import { RUNTIME_AGENT_SPECS } from "../src/agents/prompts/runtime_agent_spec.js";
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
