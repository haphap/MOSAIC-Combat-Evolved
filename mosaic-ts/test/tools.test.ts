import { describe, expect, it } from "vitest";
import {
  type BridgeApi,
  BridgeClient,
  bridgeToolFromMetadata,
  type JsonSchemaObject,
  jsonSchemaToZod,
  listBridgeTools,
  pickBridgeTools,
  type SignedAgentToolCapability,
  type ToolMetadata,
} from "../src/bridge/index.js";

const CAPABILITY = {
  manifest: {
    capability_contract_version: "agent_tool_capability_v1",
    capability_id: "cap_test",
    graph_run_id: "graph_test",
    run_slot_id: "slot_test",
    run_id: "run_test",
    node_id: "china:china",
    agent_id: "china",
    stage: "china",
    allowed_tools: ["get_china_macro_snapshot"],
    as_of: "2026-07-09",
    candidate_scope_hash: null,
    snapshot_bundle_id: "bundle_test",
    snapshot_bundle_hash: "sha256:test",
    issued_at: "2026-07-09T00:00:00Z",
    expires_at: "2026-07-09T01:00:00Z",
    nonce: "nonce",
  },
  signing_key_id: "test",
  signature: "hmac-sha256:test",
} satisfies SignedAgentToolCapability;

describe("jsonSchemaToZod", () => {
  it("parses Pydantic-style flat object schemas with required + optional fields", () => {
    const schema: JsonSchemaObject = {
      type: "object",
      properties: {
        series_id: { type: "string", description: "FRED series id" },
        start_date: { type: "string", description: "Start" },
        look_back_days: { type: "integer", description: "Days", default: 7 },
      },
      required: ["series_id", "start_date"],
    };
    const zod = jsonSchemaToZod(schema);
    expect(() => zod.parse({ series_id: "FEDFUNDS", start_date: "2024-01-01" })).not.toThrow();
    // Default applied
    const parsed = zod.parse({ series_id: "FEDFUNDS", start_date: "2024-01-01" });
    expect(parsed).toMatchObject({ look_back_days: 7 });
    // Required missing → throws
    expect(() => zod.parse({ series_id: "FEDFUNDS" })).toThrow();
    // Wrong type rejected
    expect(() => zod.parse({ series_id: 1, start_date: "2024-01-01" })).toThrow();
  });

  it("rejects unsupported features with an actionable error", () => {
    expect(() =>
      jsonSchemaToZod({
        type: "object",
        properties: { whatever: { type: "string", anyOf: [{ type: "string" }] } },
      }),
    ).toThrow(/anyOf/);
    expect(() =>
      jsonSchemaToZod({
        type: "object",
        // biome-ignore lint/suspicious/noExplicitAny: deliberately invalid input
        properties: { weird: { type: "array" as any } },
      }),
    ).toThrow(/unsupported type/);
  });

  it("handles Pydantic Optional[X] (anyOf: [type, null]) as nullable", () => {
    // This is the shape Pydantic emits for ``ticker: Annotated[Optional[str], ...]``
    // — exactly what get_xueqiu_heat in MOSAIC Phase 0 surfaces.
    const schema: JsonSchemaObject = {
      type: "object",
      properties: {
        ticker: {
          anyOf: [{ type: "string" }, { type: "null" }],
          default: null,
          description: "Optional 6-digit ticker.",
        },
      },
    };
    const zod = jsonSchemaToZod(schema);
    expect(() => zod.parse({})).not.toThrow();
    expect(() => zod.parse({ ticker: null })).not.toThrow();
    expect(() => zod.parse({ ticker: "600519" })).not.toThrow();
    expect(() => zod.parse({ ticker: 12345 })).toThrow();
  });
});

describe("bridgeToolFromMetadata (unit)", () => {
  it("creates a structured tool whose name/description match metadata", () => {
    const fakeApi = {
      toolsCall: async () => ({ text: "irrelevant" }),
    } as unknown as BridgeApi;
    const meta: ToolMetadata = {
      name: "demo_tool",
      description: "A demo tool",
      args_schema: {
        type: "object",
        properties: { series_id: { type: "string" } },
        required: ["series_id"],
      },
    };
    const tool = bridgeToolFromMetadata(fakeApi, meta, { capability: CAPABILITY });
    expect(tool.name).toBe("demo_tool");
    expect(tool.description).toBe("A demo tool");
  });

  it("invoking the tool routes through BridgeApi.toolsCall and returns the text", async () => {
    const calls: Array<{ name: string; args: unknown; capability: unknown }> = [];
    const fakeApi = {
      toolsCall: async (name: string, args: unknown, capability: unknown) => {
        calls.push({ name, args, capability });
        return { text: `ok:${name}` };
      },
    } as unknown as BridgeApi;
    const meta: ToolMetadata = {
      name: "echo",
      description: "echo",
      args_schema: {
        type: "object",
        properties: { series_id: { type: "string" } },
        required: ["series_id"],
      },
    };
    const tool = bridgeToolFromMetadata(fakeApi, meta, {
      capability: CAPABILITY,
    });
    const result = await tool.invoke({ series_id: "FEDFUNDS" });
    expect(result).toBe("ok:echo");
    expect(calls).toHaveLength(1);
    expect(calls[0]?.name).toBe("echo");
    expect(calls[0]?.args).toEqual({ series_id: "FEDFUNDS" });
    expect(calls[0]?.capability).toBe(CAPABILITY);
  });
});

describe("pickBridgeTools (unit)", () => {
  const args_schema: JsonSchemaObject = {
    type: "object",
    properties: { q: { type: "string" } },
    required: ["q"],
  };
  const metadatas: ToolMetadata[] = [
    "get_rke_research_context",
    "get_news",
    "get_xueqiu_heat",
    "get_industry_policy",
  ].map((name) => ({ name, description: name, args_schema }));

  it("returns only names requested from the capability-scoped list", async () => {
    const api = { toolsList: async () => metadatas } as unknown as BridgeApi;
    const tools = await pickBridgeTools(
      api,
      ["get_rke_research_context", "get_news", "get_xueqiu_heat", "get_industry_policy"],
      { capability: CAPABILITY },
    );

    expect(tools.map((t) => t.name)).toEqual([
      "get_rke_research_context",
      "get_news",
      "get_xueqiu_heat",
      "get_industry_policy",
    ]);
  });

  it("passes the out-of-band capability to tools.list", async () => {
    let observed: SignedAgentToolCapability | undefined;
    const api = { toolsList: async () => metadatas } as unknown as BridgeApi;
    api.toolsList = async (capability) => {
      observed = capability;
      return metadatas;
    };
    const tools = await pickBridgeTools(api, ["get_news", "get_xueqiu_heat"], {
      capability: CAPABILITY,
    });

    expect(tools.map((t) => t.name)).toEqual(["get_news", "get_xueqiu_heat"]);
    expect(observed).toBe(CAPABILITY);
  });
});

describe("listBridgeTools / pickBridgeTools against real sidecar", () => {
  it("rejects tools.list without an issued capability", async () => {
    const client = new BridgeClient();
    try {
      await client.start();
      await expect(client.call("tools.list", {})).rejects.toThrow(/capability/i);
    } finally {
      await client.close();
    }
  });

  it("listBridgeTools converts capability-scoped zero-argument metadata", async () => {
    const api = {
      toolsList: async () => [
        {
          name: "demo_tool",
          description: "demo",
          args_schema: { type: "object", properties: {}, required: [] },
        },
      ],
    } as unknown as BridgeApi;
    const tools = await listBridgeTools(api, { capability: CAPABILITY });
    expect(tools.map((tool) => tool.name)).toEqual(["demo_tool"]);
  });
});
