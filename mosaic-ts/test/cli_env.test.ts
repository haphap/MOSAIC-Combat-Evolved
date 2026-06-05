import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { loadProjectEnv } from "../src/cli/env.js";

describe("loadProjectEnv", () => {
  const touched = new Set<string>();
  const original = new Map<string, string | undefined>();
  let root: string | undefined;

  afterEach(() => {
    if (root) rmSync(root, { recursive: true, force: true });
    for (const key of touched) {
      const value = original.get(key);
      if (value === undefined) {
        delete process.env[key];
      } else {
        process.env[key] = value;
      }
    }
    touched.clear();
    original.clear();
    root = undefined;
  });

  it("loads project .env values without overriding existing environment", () => {
    root = mkdtempSync(join(tmpdir(), "mosaic-env-test-"));
    mkdirSync(root, { recursive: true });
    writeFileSync(
      join(root, ".env"),
      [
        "MOSAIC_PROMPTS_REPO=/tmp/MOSAIC-Prompts",
        'MOSAIC_PROMPTS_ROOT="/tmp/direct prompts"',
        "MOSAIC_COMMENTED=/tmp/path # local clone",
        'MOSAIC_QUOTED_COMMENT="/tmp/direct # prompts" # note',
        "MOSAIC_EXISTING=from-file",
      ].join("\n"),
      "utf-8",
    );
    remember("MOSAIC_PROMPTS_REPO");
    remember("MOSAIC_PROMPTS_ROOT");
    remember("MOSAIC_COMMENTED");
    remember("MOSAIC_QUOTED_COMMENT");
    remember("MOSAIC_EXISTING");
    process.env.MOSAIC_EXISTING = "from-shell";

    loadProjectEnv(root);

    expect(process.env.MOSAIC_PROMPTS_REPO).toBe("/tmp/MOSAIC-Prompts");
    expect(process.env.MOSAIC_PROMPTS_ROOT).toBe("/tmp/direct prompts");
    expect(process.env.MOSAIC_COMMENTED).toBe("/tmp/path");
    expect(process.env.MOSAIC_QUOTED_COMMENT).toBe("/tmp/direct # prompts");
    expect(process.env.MOSAIC_EXISTING).toBe("from-shell");
  });

  function remember(key: string): void {
    touched.add(key);
    original.set(key, process.env[key]);
    delete process.env[key];
  }
});
