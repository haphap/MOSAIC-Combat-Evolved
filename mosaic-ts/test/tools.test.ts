import { describe, expect, it } from "vitest";
import {
  BridgeApi,
  BridgeClient,
  bridgeToolFromMetadata,
  type JsonSchemaObject,
  jsonSchemaToZod,
  listBridgeTools,
  pickBridgeTools,
  type ToolMetadata,
} from "../src/bridge/index.js";

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
    const tool = bridgeToolFromMetadata(fakeApi, meta);
    expect(tool.name).toBe("demo_tool");
    expect(tool.description).toBe("A demo tool");
  });

  it("invoking the tool routes through BridgeApi.toolsCall and returns the text", async () => {
    const calls: Array<{ name: string; args: unknown; ctx: unknown }> = [];
    const fakeApi = {
      toolsCall: async (name: string, args: unknown, ctx: unknown) => {
        calls.push({ name, args, ctx });
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
      context: { mode: "backtest", as_of_date: "2024-06-01" },
    });
    const result = await tool.invoke({ series_id: "FEDFUNDS" });
    expect(result).toBe("ok:echo");
    expect(calls).toHaveLength(1);
    expect(calls[0]?.name).toBe("echo");
    expect(calls[0]?.args).toEqual({ series_id: "FEDFUNDS" });
    expect(calls[0]?.ctx).toEqual({ mode: "backtest", as_of_date: "2024-06-01" });
  });
});

describe("listBridgeTools / pickBridgeTools against real sidecar", () => {
  it("converts every Pydantic schema returned by tools.list into a usable tool", async () => {
    const client = new BridgeClient();
    const api = new BridgeApi(client);
    try {
      await client.start();
      const tools = await listBridgeTools(api);
      expect(tools.length).toBeGreaterThanOrEqual(8); // Phase 0 macro tool surface
      const names = tools.map((t) => t.name).sort();
      // Spot-check Phase 0 macro tools
      expect(names).toContain("get_fred_series");
      expect(names).toContain("get_pboc_ops");
      expect(names).toContain("get_north_capital_flow");
      expect(names).toContain("get_yield_curve_cn");
      // Research-report tools (行业研报 + 个股研报)
      expect(names).toContain("get_broker_research");
      expect(names).toContain("get_stock_research");
      // Every tool must have a non-empty schema (input validation works)
      for (const tool of tools) {
        expect(tool.name).toBeTypeOf("string");
        expect(tool.description).toBeTypeOf("string");
      }
    } finally {
      await client.close();
    }
  });

  it("pickBridgeTools surfaces missing names with the available list", async () => {
    const client = new BridgeClient();
    const api = new BridgeApi(client);
    try {
      await client.start();
      await expect(pickBridgeTools(api, ["get_fred_series", "fake_tool"])).rejects.toThrow(
        /fake_tool/,
      );
    } finally {
      await client.close();
    }
  });
});
