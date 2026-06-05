import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { formatPromptSourceLabel } from "../src/agents/prompts/cohorts.js";
import { applyPromptSourceOverrides } from "../src/cli/prompt-source.js";

const KEYS = ["MOSAIC_PROMPTS_REPO", "MOSAIC_PROMPTS_ROOT", "MOSAIC_PRIVATE_PROMPT_REPO"] as const;

describe("applyPromptSourceOverrides", () => {
  const original = new Map<(typeof KEYS)[number], string | undefined>();

  beforeEach(() => {
    for (const key of KEYS) {
      original.set(key, process.env[key]);
      delete process.env[key];
    }
  });

  afterEach(() => {
    for (const key of KEYS) {
      const value = original.get(key);
      if (value === undefined) {
        delete process.env[key];
      } else {
        process.env[key] = value;
      }
    }
    original.clear();
  });

  it("lets --prompts-repo override a root loaded from .env", () => {
    process.env.MOSAIC_PROMPTS_ROOT = "/tmp/stale-root";
    process.env.MOSAIC_PRIVATE_PROMPT_REPO = "/tmp/legacy-private";

    applyPromptSourceOverrides({ promptsRepo: "/tmp/MOSAIC-Prompts" });

    expect(process.env.MOSAIC_PROMPTS_REPO).toBe("/tmp/MOSAIC-Prompts");
    expect(process.env.MOSAIC_PROMPTS_ROOT).toBeUndefined();
    expect(process.env.MOSAIC_PRIVATE_PROMPT_REPO).toBeUndefined();
    expect(formatPromptSourceLabel()).toBe("private-repo:/tmp/MOSAIC-Prompts");
  });

  it("lets --prompts-root override repo env vars", () => {
    process.env.MOSAIC_PROMPTS_REPO = "/tmp/MOSAIC-Prompts";
    process.env.MOSAIC_PRIVATE_PROMPT_REPO = "/tmp/legacy-private";

    applyPromptSourceOverrides({ promptsRoot: "/tmp/direct-prompts-root" });

    expect(process.env.MOSAIC_PROMPTS_ROOT).toBe("/tmp/direct-prompts-root");
    expect(process.env.MOSAIC_PROMPTS_REPO).toBeUndefined();
    expect(process.env.MOSAIC_PRIVATE_PROMPT_REPO).toBeUndefined();
    expect(formatPromptSourceLabel()).toBe("private-root:/tmp/direct-prompts-root");
  });

  it("rejects both prompt source flags together", () => {
    expect(() =>
      applyPromptSourceOverrides({
        promptsRepo: "/tmp/MOSAIC-Prompts",
        promptsRoot: "/tmp/direct-prompts-root",
      }),
    ).toThrow(/either --prompts-repo or --prompts-root/);
  });
});
