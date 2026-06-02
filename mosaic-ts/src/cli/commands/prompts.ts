/**
 * `pnpm dev prompts` — prompt asset operations.
 *
 * The private prompt repo is intentionally separate from the project repo.
 * Autoresearch will later write optimized prompts there instead of committing
 * them under the project `prompts/mosaic/**` tree.
 */

import type { Command } from "commander";
import pc from "picocolors";
import { BridgeApi, BridgeClient, RpcError } from "../../bridge/index.js";
import { redactSensitiveText } from "../../security/redaction.js";

interface InitPrivateRepoOpts {
  seedBaseline?: boolean;
}

export function registerPrompts(program: Command): void {
  const prompts = program.command("prompts").description("Manage prompt assets.");

  prompts
    .command("init-private-repo")
    .argument("<path>", "Path to an independent private prompt git repo")
    .description("Initialize a sparse private prompt repo outside the project checkout.")
    .option(
      "--seed-baseline",
      "Copy project baseline prompts into the private repo. Migration only; creates broad shadowing.",
      false,
    )
    .action(async (path: string, opts: InitPrivateRepoOpts) => {
      const client = new BridgeClient();
      const api = new BridgeApi(client);
      try {
        if (opts.seedBaseline) {
          console.warn(
            pc.yellow(
              "warning: --seed-baseline creates private overrides for all seeded prompts; future baseline fixes require drift sync.",
            ),
          );
        }
        await client.start();
        const result = await api.promptsInitPrivateRepo({
          path,
          seed_baseline: Boolean(opts.seedBaseline),
        });
        console.log(pc.green("private prompt repo initialized"));
        console.log(`repo: ${redactSensitiveText(result.repo_root, [result.repo_root])}`);
        console.log(`prompts: ${redactSensitiveText(result.prompts_root, [result.repo_root])}`);
        console.log(`commit: ${result.commit_hash}`);
        console.log(`mode: ${result.seeded ? "seeded baseline" : "sparse"}`);
      } catch (err) {
        reportError(err, client);
      } finally {
        await client.close();
      }
    });
}

function reportError(err: unknown, client: BridgeClient): void {
  if (err instanceof RpcError) {
    console.error(pc.red(`bridge error [${err.code}]: ${redactSensitiveText(err.message)}`));
  } else {
    console.error(pc.red(`error: ${redactSensitiveText((err as Error).message)}`));
  }
  const tail = client.stderrTail?.trim();
  if (tail) console.error(pc.dim(redactSensitiveText(tail).slice(-1500)));
  process.exitCode = 1;
}
