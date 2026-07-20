import type { BaseChatModel } from "@langchain/core/language_models/chat_models";
import { describe, expect, it } from "vitest";
import { z } from "zod";
import { bindStructured } from "../src/agents/helpers/structured_output.js";
import {
  renderCohortBehavior,
  replaceCohortBehavior,
} from "../src/agents/prompts/cohort_behavior.js";
import {
  assertPromptInvariants,
  assertPromptPairInvariants,
  buildMutationSchema,
  MAX_MUTATED_PROMPT_CHARACTERS,
  MAX_MUTATION_METADATA_CHARACTERS,
  MutationSchema,
} from "../src/autoresearch/mutator.js";

interface MutationJsonSchema {
  properties: {
    zh_prompt: { minLength: number; maxLength: number };
    en_prompt: { minLength: number; maxLength: number };
    modification_summary: { maxLength: number };
    rationale: { maxLength: number };
  };
  additionalProperties: false;
}

describe("autoresearch mutation model contract", () => {
  it("bounds every model-authored string in the canonical schema", () => {
    const schema = z.toJSONSchema(MutationSchema) as unknown as MutationJsonSchema;
    expect(schema.properties.zh_prompt.maxLength).toBe(MAX_MUTATED_PROMPT_CHARACTERS);
    expect(schema.properties.en_prompt.maxLength).toBe(MAX_MUTATED_PROMPT_CHARACTERS);
    expect(schema.properties.modification_summary.maxLength).toBe(MAX_MUTATION_METADATA_CHARACTERS);
    expect(schema.properties.rationale.maxLength).toBe(MAX_MUTATION_METADATA_CHARACTERS);
    expect(schema.additionalProperties).toBe(false);
  });

  it("narrows prompt lengths to the runtime ±40 percent interval", () => {
    const schema = buildMutationSchema("中".repeat(100), "e".repeat(50));
    const jsonSchema = z.toJSONSchema(schema) as unknown as MutationJsonSchema;
    expect(jsonSchema.properties.zh_prompt).toMatchObject({ minLength: 60, maxLength: 140 });
    expect(jsonSchema.properties.en_prompt).toMatchObject({ minLength: 30, maxLength: 70 });
    expect(jsonSchema.properties.modification_summary.maxLength).toBe(
      MAX_MUTATION_METADATA_CHARACTERS,
    );
  });

  it("intersects the runtime interval with the canonical cap", () => {
    const schema = buildMutationSchema("中".repeat(MAX_MUTATED_PROMPT_CHARACTERS), "english");
    const jsonSchema = z.toJSONSchema(schema) as unknown as MutationJsonSchema;
    expect(jsonSchema.properties.zh_prompt).toMatchObject({
      minLength: Math.ceil(MAX_MUTATED_PROMPT_CHARACTERS * 0.6),
      maxLength: MAX_MUTATED_PROMPT_CHARACTERS,
    });
  });

  it("fails before invocation only when the valid interval is above the canonical cap", () => {
    expect(() => buildMutationSchema("中".repeat(30_000), "english")).toThrow(
      "no valid rewrite length within the mutation cap",
    );
  });

  it("preserves the dynamic limits in the OpenAI provider JSON schema", () => {
    let captured: unknown;
    const llm = {
      _llmType: () => "openai",
      withStructuredOutput: (schema: unknown) => {
        captured = schema;
        return { invoke: async () => ({ parsed: {}, raw: {} }) };
      },
    } as unknown as BaseChatModel;
    const bound = bindStructured(
      llm,
      buildMutationSchema("中".repeat(100), "e".repeat(50)),
      "mutator:test",
    );
    expect(bound).not.toBeNull();
    const providerSchema = captured as MutationJsonSchema;
    expect(providerSchema.properties.zh_prompt).toMatchObject({ minLength: 60, maxLength: 140 });
    expect(providerSchema.properties.en_prompt).toMatchObject({ minLength: 30, maxLength: 70 });
    expect(providerSchema.properties.modification_summary.maxLength).toBe(
      MAX_MUTATION_METADATA_CHARACTERS,
    );
    expect(providerSchema.additionalProperties).toBe(false);
  });

  it("validates the language of the mutable cohort block instead of the immutable prompt", () => {
    const zh = `中文不可变契约\n${renderCohortBehavior("This behavior is entirely English prose.")}`;
    const en = `English immutable contract\n${renderCohortBehavior(
      "This behavior is valid English prose.",
    )}`;
    expect(() => assertPromptPairInvariants(zh, en)).toThrow(
      "Chinese cohort behavior must contain meaningful Chinese prose",
    );

    const validZh = `中文不可变契约\n${renderCohortBehavior("先核对证据冲突，再形成最终判断。")}`;
    const cyrillicEn = `English immutable contract\n${renderCohortBehavior(
      "Это полностью русский текст без английского языка.",
    )}`;
    expect(() => assertPromptPairInvariants(validZh, cyrillicEn)).toThrow(
      "English cohort behavior must contain meaningful English prose",
    );
  });

  it("rejects private KNOT policy content introduced inside a mutation", () => {
    const original = `immutable\n${renderCohortBehavior("先核对证据冲突，再形成最终判断。")}`;
    const rewritten = replaceCohortBehavior(
      original,
      "先核对达尔文权重，再检查证据冲突并形成判断。",
    );
    expect(() => assertPromptInvariants(original, rewritten)).toThrow(
      "rewrite exposed private KNOT policy content",
    );
  });
});
