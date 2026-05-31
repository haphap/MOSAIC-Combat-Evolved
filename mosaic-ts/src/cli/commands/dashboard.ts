/**
 * Phase 9B CLI: ``pnpm dev dashboard`` — render the read-only Ink dashboard
 * (manual-refresh view aggregating existing read RPCs).
 */

import type { Command } from "commander";
import { render } from "ink";
import pc from "picocolors";
import { createElement } from "react";
import { BridgeApi, BridgeClient, RpcError } from "../../bridge/index.js";
import { Dashboard } from "../../tui/Dashboard.js";

interface DashboardOpts {
  cohort?: string;
  user?: string;
}

export function registerDashboard(program: Command): void {
  program
    .command("dashboard")
    .description("TUI: today / winrate / skill / paper / cohorts / mirofish / settings.")
    .option("--cohort <name>", "Cohort for the skill tab (default cohort_default)")
    .option("--user <name>", "Paper account user (default: session user)")
    .action(async (opts: DashboardOpts) => {
      const client = new BridgeClient();
      const api = new BridgeApi(client);
      try {
        await client.start();
        const app = render(
          createElement(Dashboard, {
            api,
            cohort: opts.cohort ?? "cohort_default",
            ...(opts.user ? { user: opts.user } : {}),
          }),
        );
        await app.waitUntilExit();
      } catch (err) {
        if (err instanceof RpcError) {
          console.error(pc.red(`bridge error [${err.code}]: ${err.message}`));
        } else {
          console.error(pc.red(`error: ${(err as Error).message}`));
        }
        process.exitCode = 1;
      } finally {
        await client.close();
      }
    });
}
