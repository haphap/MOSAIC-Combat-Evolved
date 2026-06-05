export interface PromptSourceOverrideOptions {
  promptsRepo?: string;
  promptsRoot?: string;
}

export function applyPromptSourceOverrides(opts: PromptSourceOverrideOptions): void {
  if (opts.promptsRepo && opts.promptsRoot) {
    throw new Error("use either --prompts-repo or --prompts-root, not both");
  }

  if (opts.promptsRepo) {
    process.env.MOSAIC_PROMPTS_REPO = opts.promptsRepo;
    delete process.env.MOSAIC_PRIVATE_PROMPT_REPO;
    delete process.env.MOSAIC_PROMPTS_ROOT;
  }

  if (opts.promptsRoot) {
    process.env.MOSAIC_PROMPTS_ROOT = opts.promptsRoot;
    delete process.env.MOSAIC_PROMPTS_REPO;
    delete process.env.MOSAIC_PRIVATE_PROMPT_REPO;
  }
}
