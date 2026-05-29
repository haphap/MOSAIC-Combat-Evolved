/**
 * Convert ``tools.list`` JSON Schemas into LangChain DynamicStructuredTools
 * whose ``invoke`` calls go through the bridge's ``tools.call`` RPC.
 *
 * Scope of the converter is intentionally narrow: it handles the shape
 * Pydantic v2 emits for our @tool functions (flat objects with primitive
 * properties + ``required`` + ``description``). Nested objects, unions,
 * and arrays are not used today and are explicitly rejected so we fail
 * loud if a future tool changes its schema.
 */

import type { StructuredToolInterface } from "@langchain/core/tools";
import { tool } from "@langchain/core/tools";
import { type ZodObject, type ZodTypeAny, z } from "zod";
import type {
  BridgeApi,
  JsonSchemaObject,
  JsonSchemaProperty,
  ToolCallContext,
  ToolMetadata,
} from "./types.js";

/** Convert one Pydantic-style JSON Schema property into a Zod type. */
function propertyToZod(name: string, prop: JsonSchemaProperty): ZodTypeAny {
  // Pydantic emits Optional[X] as ``anyOf: [{type: X}, {type: "null"}]``.
  // Recognise that exact shape and produce a nullable Zod type. Anything
  // beyond that (true unions, multiple non-null types) is rejected so we
  // fail loud if a future tool changes its schema.
  if (prop.anyOf && prop.anyOf.length > 0) {
    const nonNull = prop.anyOf.filter((entry) => entry.type !== "null");
    const hasNull = prop.anyOf.some((entry) => entry.type === "null");
    const innerType = nonNull[0]?.type;
    if (nonNull.length === 1 && hasNull && innerType) {
      let inner = primitiveToZod(name, innerType as JsonSchemaProperty["type"]).nullable();
      if (prop.description) {
        inner = inner.describe(prop.description);
      }
      return inner;
    }
    throw new Error(`Tool property '${name}' uses anyOf — not supported by the current converter.`);
  }

  let zodType = primitiveToZod(name, prop.type);
  if (prop.description) {
    zodType = zodType.describe(prop.description);
  }
  return zodType;
}

/** Map a primitive JSON Schema type onto its Zod counterpart. */
function primitiveToZod(name: string, type: JsonSchemaProperty["type"]): ZodTypeAny {
  switch (type) {
    case "string":
      return z.string();
    case "integer":
      return z.int();
    case "number":
      return z.number();
    case "boolean":
      return z.boolean();
    default:
      throw new Error(`Tool property '${name}' has unsupported type ${JSON.stringify(type)}`);
  }
}

/** Convert the top-level JSON Schema (always type=object) to a ZodObject. */
export function jsonSchemaToZod(schema: JsonSchemaObject): ZodObject {
  if (schema.type !== "object") {
    throw new Error(`Expected top-level schema type=object, got ${schema.type}`);
  }
  const required = new Set(schema.required ?? []);
  const shape: Record<string, ZodTypeAny> = {};
  for (const [name, prop] of Object.entries(schema.properties ?? {})) {
    let field = propertyToZod(name, prop);
    // Pydantic emits `default` even for fields that are also in `required`?
    // Treat presence of `default` as making the field optional with a default.
    if (prop.default !== undefined) {
      field = field.default(prop.default as never);
    } else if (!required.has(name)) {
      field = field.optional();
    }
    shape[name] = field;
  }
  return z.object(shape);
}

export interface BridgeToolFactoryOptions {
  /** Default backtest context to attach to every tool.invoke call. */
  context?: ToolCallContext;
}

/**
 * Build a LangChain tool that routes through the bridge.
 *
 * The returned tool's ``invoke({ ...args })`` performs a ``tools.call`` RPC
 * with the provided ``context`` (if any). The tool's output is the string
 * returned by the underlying Python @tool — exactly what the LLM expects.
 */
export function bridgeToolFromMetadata(
  api: BridgeApi,
  metadata: ToolMetadata,
  options: BridgeToolFactoryOptions = {},
): StructuredToolInterface {
  const schema = jsonSchemaToZod(metadata.args_schema);
  const ctx = options.context;
  return tool(
    async (input) => {
      const result = await api.toolsCall(metadata.name, input as Record<string, unknown>, ctx);
      return result.text;
    },
    {
      name: metadata.name,
      description: metadata.description,
      schema,
    },
  );
}

/** Convenience: pull tools.list and wrap each one. */
export async function listBridgeTools(
  api: BridgeApi,
  options: BridgeToolFactoryOptions = {},
): Promise<StructuredToolInterface[]> {
  const metadatas = await api.toolsList();
  return metadatas.map((m) => bridgeToolFromMetadata(api, m, options));
}

/** Subset variant: list only the named tools (preserves the requested order). */
export async function pickBridgeTools(
  api: BridgeApi,
  names: ReadonlyArray<string>,
  options: BridgeToolFactoryOptions = {},
): Promise<StructuredToolInterface[]> {
  const metadatas = await api.toolsList();
  const byName = new Map(metadatas.map((m) => [m.name, m] as const));
  const picked: StructuredToolInterface[] = [];
  const missing: string[] = [];
  for (const name of names) {
    const meta = byName.get(name);
    if (!meta) {
      missing.push(name);
      continue;
    }
    picked.push(bridgeToolFromMetadata(api, meta, options));
  }
  if (missing.length > 0) {
    throw new Error(
      `Bridge does not expose these tools: ${missing.join(", ")}. ` +
        `Available: ${[...byName.keys()].sort().join(", ")}`,
    );
  }
  return picked;
}
