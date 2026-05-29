import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { BridgeStartupError } from "../src/bridge/errors.js";
import { resolvePython } from "../src/bridge/python.js";

interface FakeRepo {
  root: string;
  pythonPath: string;
  cleanup: () => void;
}

/** Build a temp dir that mimics the MOSAIC project layout: bridge marker + .venv/bin/python. */
function makeFakeRepo(opts: { withVenv?: boolean } = {}): FakeRepo {
  const root = mkdtempSync(join(tmpdir(), "mosaic-python-test-"));
  mkdirSync(join(root, "mosaic", "bridge"), { recursive: true });
  writeFileSync(join(root, "mosaic", "bridge", "__main__.py"), "");
  let pythonPath = "";
  if (opts.withVenv ?? true) {
    mkdirSync(join(root, ".venv", "bin"), { recursive: true });
    pythonPath = join(root, ".venv", "bin", "python");
    writeFileSync(pythonPath, "#!/bin/sh\necho fake\n");
  }
  return {
    root,
    pythonPath,
    cleanup: () => rmSync(root, { recursive: true, force: true }),
  };
}

describe("resolvePython", () => {
  let repo: FakeRepo;
  const originalEnv = process.env.MOSAIC_PYTHON;

  beforeEach(() => {
    delete process.env.MOSAIC_PYTHON;
  });
  afterEach(() => {
    if (repo) repo.cleanup();
    if (originalEnv === undefined) {
      delete process.env.MOSAIC_PYTHON;
    } else {
      process.env.MOSAIC_PYTHON = originalEnv;
    }
  });

  it("uses MOSAIC_PYTHON when set and the file exists", () => {
    repo = makeFakeRepo({ withVenv: true });
    // Create a separate fake python outside the venv to prove env wins.
    const customRoot = mkdtempSync(join(tmpdir(), "mosaic-python-override-"));
    const customPath = join(customRoot, "my-python");
    writeFileSync(customPath, "#!/bin/sh\necho custom\n");
    process.env.MOSAIC_PYTHON = customPath;
    try {
      const result = resolvePython(repo.root);
      expect(result.python).toBe(customPath);
      expect(result.source).toBe("env");
    } finally {
      rmSync(customRoot, { recursive: true, force: true });
    }
  });

  it("rejects MOSAIC_PYTHON pointing at a non-existent file (fail loud)", () => {
    repo = makeFakeRepo({ withVenv: true });
    process.env.MOSAIC_PYTHON = "/no/such/python";
    expect(() => resolvePython(repo.root)).toThrow(BridgeStartupError);
    expect(() => resolvePython(repo.root)).toThrow(/does not exist/);
  });

  it("falls back to .venv/bin/python when env is unset", () => {
    repo = makeFakeRepo({ withVenv: true });
    const result = resolvePython(repo.root);
    expect(result.python).toBe(repo.pythonPath);
    expect(result.source).toBe("venv-posix");
    expect(result.repoRoot).toBe(repo.root);
  });

  it("fails with an actionable message when neither env nor .venv exists", () => {
    repo = makeFakeRepo({ withVenv: false });
    try {
      resolvePython(repo.root);
      expect.fail("expected resolvePython to throw");
    } catch (err) {
      expect(err).toBeInstanceOf(BridgeStartupError);
      // Message must mention `uv venv` so the user knows how to fix it.
      expect((err as Error).message).toMatch(/uv venv/);
      expect((err as Error).message).toContain(repo.root);
    }
  });
});
