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

interface AuditVersionsOpts {
  cohort?: string;
  status?: string;
  agent?: string;
  limit?: string;
}

interface VerifyReleaseOpts {
  versionId: string;
  allowUnkept?: boolean;
}

interface GcWorktreesOpts {
  repoTarget?: "project_git" | "private_git" | "all";
  maxAgeHours?: string;
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

  prompts
    .command("audit-versions")
    .description("List prompt version metadata without showing prompt content.")
    .option("--cohort <name>", "Filter by cohort")
    .option("--status <status>", "Filter by prompt version status")
    .option("--agent <name>", "Filter by agent")
    .option("--limit <n>", "Max rows (default 20)")
    .action(async (opts: AuditVersionsOpts) => {
      const client = new BridgeClient();
      const api = new BridgeApi(client);
      try {
        await client.start();
        const result = await api.promptsAuditVersions({
          ...(opts.cohort ? { cohort: opts.cohort } : {}),
          ...(opts.status ? { status: opts.status } : {}),
          ...(opts.agent ? { agent: opts.agent } : {}),
          ...(opts.limit ? { limit: Number.parseInt(opts.limit, 10) } : {}),
        });
        console.log(pc.bold("\nprompt versions"));
        if (result.versions.length === 0) {
          console.log(pc.dim("  no versions"));
        }
        for (const row of result.versions) {
          console.log(
            `  #${row.id} ${row.status} ${row.cohort}/${row.agent} ` +
              `prompt=${row.modification_commit_hash?.slice(0, 12) ?? "-"} ` +
              `code=${row.code_commit_hash?.slice(0, 12) ?? "-"}`,
          );
          console.log(
            pc.dim(
              `     repo=${row.prompt_repo_id ?? "-"} sha=${row.prompt_sha256?.slice(0, 12) ?? "-"} ` +
                `delta=${row.delta_sharpe ?? "n/a"} branch=${row.branch_name}`,
            ),
          );
        }
      } catch (err) {
        reportError(err, client);
      } finally {
        await client.close();
      }
    });

  prompts
    .command("verify-release")
    .requiredOption("--version-id <id>", "Prompt version id to verify")
    .option("--allow-unkept", "Do not require status=keep")
    .description("Verify prompt metadata, content hash, and compatibility before release.")
    .action(async (opts: VerifyReleaseOpts) => {
      const client = new BridgeClient();
      const api = new BridgeApi(client);
      try {
        await client.start();
        const result = await api.promptsVerifyRelease({
          version_id: Number.parseInt(opts.versionId, 10),
          require_kept: !opts.allowUnkept,
        });
        const color = result.ready ? pc.green : pc.red;
        console.log(color(`release ${result.ready ? "ready" : "blocked"}`));
        for (const [name, ok] of Object.entries(result.checks)) {
          console.log(`  ${ok ? pc.green("ok") : pc.red("no")} ${name}`);
        }
        console.log(
          pc.dim(
            `pin code=${result.pin.code_commit_hash?.slice(0, 12) ?? "-"} ` +
              `prompt=${result.pin.prompt_commit_hash?.slice(0, 12) ?? "-"} ` +
              `repo=${result.pin.prompt_repo_id ?? "-"} sha=${result.pin.prompt_sha256?.slice(0, 12) ?? "-"}`,
          ),
        );
        if (!result.ready) process.exitCode = 1;
      } catch (err) {
        reportError(err, client);
      } finally {
        await client.close();
      }
    });

  prompts
    .command("gc-worktrees")
    .description("Remove stale managed project/private prompt worktrees.")
    .option("--repo-target <target>", "project_git | private_git | all (default all)")
    .option("--max-age-hours <n>", "Remove worktrees older than this many hours (default 24)")
    .action(async (opts: GcWorktreesOpts) => {
      const client = new BridgeClient();
      const api = new BridgeApi(client);
      try {
        await client.start();
        const result = await api.autoresearchGcWorktrees({
          ...(opts.repoTarget ? { repo_target: opts.repoTarget } : {}),
          ...(opts.maxAgeHours ? { max_age_hours: Number(opts.maxAgeHours) } : {}),
        });
        for (const row of result.results) {
          console.log(
            `${row.repo_target}: removed=${row.removed.length} kept=${row.kept.length}` +
              (row.missing ? " (no worktree dir)" : ""),
          );
        }
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
