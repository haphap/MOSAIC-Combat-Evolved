import { Command } from "commander";
import { afterEach, describe, expect, it, vi } from "vitest";
import { registerAutoresearch } from "../src/cli/commands/autoresearch.js";
import { registerPromptRelease } from "../src/cli/commands/prompt-release.js";

function programWith(register: (program: Command) => void): Command {
  const program = new Command().exitOverride();
  register(program);
  return program;
}

const previousExitCode = process.exitCode;

afterEach(() => {
  process.exitCode = previousExitCode;
  vi.restoreAllMocks();
});

describe("Gate D CLI transition freeze", () => {
  it.each([
    [
      "generate-candidate",
      [
        "autoresearch",
        "generate-candidate",
        "--request",
        "unused.json",
        "--private-cli",
        "unused.mjs",
        "--private-repo",
        "unused-repo",
        "--publication-remote",
        "origin",
        "--mutation-adapter",
        "unused-adapter.mjs",
      ],
    ],
    [
      "shadow-run",
      [
        "autoresearch",
        "shadow-run",
        "--plan",
        "unused.json",
        "--executor-adapter",
        "unused-executor.mjs",
        "--evaluator-adapter",
        "unused-evaluator.mjs",
      ],
    ],
  ])("blocks autoresearch %s before side effects", async (_name, args) => {
    const program = programWith(registerAutoresearch);
    await expect(program.parseAsync(args, { from: "user" })).rejects.toThrow(
      /KNOT evolution frozen until Gate D/,
    );
  });

  it("blocks prompt release staging before bridge access", async () => {
    const program = programWith(registerPromptRelease);
    await expect(
      program.parseAsync(
        [
          "prompt-release",
          "stage",
          "--candidate-id",
          "candidate:test",
          "--experiment-id",
          "experiment:test",
          "--promotion-policy",
          "unused.json",
          "--private-prompt-commit",
          "a".repeat(40),
          "--code-commit",
          "b".repeat(40),
          "--execution-behavior-release-ref",
          "unused-release.json",
          "--release-id",
          "release:test",
        ],
        { from: "user" },
      ),
    ).rejects.toThrow(/KNOT evolution frozen until Gate D/);
  });

  it.each([
    [
      "canary",
      [
        "prompt-release",
        "canary",
        "--release-id",
        "release:test",
        "--approved-by",
        "operator:test",
        "--reason",
        "test",
      ],
    ],
    [
      "activate",
      [
        "prompt-release",
        "activate",
        "--release-id",
        "release:test",
        "--approved-by",
        "operator:test",
        "--reason",
        "test",
        "--slo-artifact",
        "unused.json",
      ],
    ],
  ])("blocks prompt release %s before registry writes", async (_name, args) => {
    const error = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const program = programWith(registerPromptRelease);
    await program.parseAsync(args, { from: "user" });
    expect(error).toHaveBeenCalledWith(expect.stringMatching(/KNOT evolution frozen until Gate D/));
    expect(process.exitCode).toBe(1);
  });
});
