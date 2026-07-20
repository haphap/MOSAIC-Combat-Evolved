import { execFileSync, spawnSync } from "node:child_process";
import { relative, resolve } from "node:path";

export interface PromptSourceProvenanceInput {
  promptsRoot: string;
  commit: string;
  source: "private" | "bundled";
}

export interface VerifiedPromptSourceCommit {
  promptsRoot: string;
  repositoryRoot: string;
  commit: string;
  source: PromptSourceProvenanceInput["source"];
}

/**
 * Resolve a prompt source commit and prove that the model-visible prompt tree
 * being measured is byte-for-byte represented by that commit. Changes outside
 * the prompt tree do not affect the proof.
 */
export function verifyPromptSourceCommit(
  input: PromptSourceProvenanceInput,
): VerifiedPromptSourceCommit {
  const promptsRoot = resolve(input.promptsRoot);
  const repositoryRoot = gitText(promptsRoot, input.source, ["rev-parse", "--show-toplevel"]);
  const commit = gitText(repositoryRoot, input.source, [
    "rev-parse",
    "--verify",
    `${input.commit.trim()}^{commit}`,
  ]);
  if (!/^[0-9a-f]{40}$/.test(commit)) {
    throw new Error(`prompt_source_commit_invalid:${input.source}`);
  }

  const relativeRoot = relative(repositoryRoot, promptsRoot).replaceAll("\\", "/") || ".";
  if (relativeRoot === ".." || relativeRoot.startsWith("../")) {
    throw new Error(`prompt_source_root_outside_repository:${input.source}`);
  }

  const diff = spawnSync(
    "git",
    ["-C", repositoryRoot, "diff", "--quiet", "--no-ext-diff", commit, "--", relativeRoot],
    { encoding: "utf8" },
  );
  if (diff.status === 1) {
    throw new Error(`prompt_source_tree_drift:${input.source}`);
  }
  if (diff.status !== 0) {
    throw new Error(`prompt_source_git_error:${input.source}:diff`);
  }

  const untracked = gitText(repositoryRoot, input.source, [
    "ls-files",
    "--others",
    "--",
    relativeRoot,
  ]);
  if (untracked) {
    throw new Error(`prompt_source_tree_untracked:${input.source}`);
  }
  return {
    promptsRoot,
    repositoryRoot,
    commit,
    source: input.source,
  };
}

/** Read model-visible bytes from the verified Git object, never the worktree. */
export function readVerifiedPromptSourceFile(
  verified: VerifiedPromptSourceCommit,
  path: string,
): string {
  const absolutePath = resolve(path);
  const relativePromptPath = relative(verified.promptsRoot, absolutePath).replaceAll("\\", "/");
  if (relativePromptPath === ".." || relativePromptPath.startsWith("../")) {
    throw new Error(`prompt_source_file_outside_root:${verified.source}`);
  }
  const repositoryPath = relative(verified.repositoryRoot, absolutePath).replaceAll("\\", "/");
  try {
    return execFileSync("git", [
      "-C",
      verified.repositoryRoot,
      "show",
      `${verified.commit}:${repositoryPath}`,
    ]).toString("utf8");
  } catch {
    throw new Error(`prompt_source_file_missing_at_commit:${verified.source}`);
  }
}

function gitText(
  cwd: string,
  source: PromptSourceProvenanceInput["source"],
  args: string[],
): string {
  try {
    return execFileSync("git", ["-C", cwd, ...args], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    }).trim();
  } catch {
    throw new Error(`prompt_source_git_error:${source}:${args[0] ?? "unknown"}`);
  }
}
