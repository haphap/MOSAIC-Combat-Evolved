import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  readVerifiedPromptSourceFile,
  verifyPromptSourceCommit,
} from "../src/agents/prompts/prompt_source_provenance.js";

const roots: string[] = [];

afterEach(() => {
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});

describe("prompt source commit provenance", () => {
  it("accepts the pinned prompt tree while ignoring unrelated worktree changes", () => {
    const fixture = promptRepository();
    writeFileSync(join(fixture.root, "unrelated.txt"), "not part of the prompt tree\n", "utf8");

    expect(
      verifyPromptSourceCommit({
        promptsRoot: fixture.promptsRoot,
        commit: fixture.commit.slice(0, 12),
        source: "private",
      }),
    ).toMatchObject({
      promptsRoot: fixture.promptsRoot,
      repositoryRoot: fixture.root,
      commit: fixture.commit,
      source: "private",
    });
  });

  it("rejects tracked and untracked prompt content not represented by the pinned commit", () => {
    const fixture = promptRepository();
    writeFileSync(fixture.promptPath, "changed prompt\n", "utf8");
    expect(() =>
      verifyPromptSourceCommit({
        promptsRoot: fixture.promptsRoot,
        commit: fixture.commit,
        source: "private",
      }),
    ).toThrow("prompt_source_tree_drift:private");

    writeFileSync(fixture.promptPath, "committed prompt\n", "utf8");
    writeFileSync(join(fixture.promptsRoot, "untracked.md"), "untracked prompt\n", "utf8");
    expect(() =>
      verifyPromptSourceCommit({
        promptsRoot: fixture.promptsRoot,
        commit: fixture.commit,
        source: "private",
      }),
    ).toThrow("prompt_source_tree_untracked:private");
  });

  it("rejects a prior commit after the prompt tree changes in a later commit", () => {
    const fixture = promptRepository();
    writeFileSync(fixture.promptPath, "later committed prompt\n", "utf8");
    git(fixture.root, "add", "prompts/mosaic");
    git(fixture.root, "commit", "-m", "update prompt");

    expect(() =>
      verifyPromptSourceCommit({
        promptsRoot: fixture.promptsRoot,
        commit: fixture.commit,
        source: "bundled",
      }),
    ).toThrow("prompt_source_tree_drift:bundled");
  });

  it("reads prompt bytes from the verified commit rather than mutable worktree state", () => {
    const fixture = promptRepository();
    const verified = verifyPromptSourceCommit({
      promptsRoot: fixture.promptsRoot,
      commit: fixture.commit,
      source: "private",
    });
    writeFileSync(fixture.promptPath, "later worktree content\n", "utf8");

    expect(readVerifiedPromptSourceFile(verified, fixture.promptPath)).toBe("committed prompt\n");
  });
});

function promptRepository(): {
  root: string;
  promptsRoot: string;
  promptPath: string;
  commit: string;
} {
  const root = mkdtempSync(join(tmpdir(), "mosaic-prompt-source-"));
  roots.push(root);
  git(root, "init", "-b", "main");
  git(root, "config", "user.name", "Test");
  git(root, "config", "user.email", "test@example.com");
  const promptsRoot = join(root, "prompts", "mosaic");
  const promptPath = join(promptsRoot, "cohort_default", "macro", "china.zh.md");
  mkdirSync(join(promptsRoot, "cohort_default", "macro"), { recursive: true });
  writeFileSync(promptPath, "committed prompt\n", "utf8");
  git(root, "add", "prompts/mosaic");
  git(root, "commit", "-m", "seed prompt");
  return { root, promptsRoot, promptPath, commit: git(root, "rev-parse", "HEAD") };
}

function git(cwd: string, ...args: string[]): string {
  return execFileSync("git", ["-C", cwd, ...args], { encoding: "utf8" }).trim();
}
