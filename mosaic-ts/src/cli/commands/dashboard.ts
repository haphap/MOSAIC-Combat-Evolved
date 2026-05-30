/**
 * Phase 9B CLI: ``pnpm dev dashboard`` — render the read-only Ink dashboard.
 */

import type { Command } from "commander";
import { render } from "ink";
import { createElement } from "react";
import { BridgeApi, BridgeClient } from "../../bridge/index.js";
import { Dashboard } from "../../tui/Dashboard.js";

interface DashboardOpts {
  cohort?: string;
  user?: string;
}

export function registerDashboard(program: Command): void {
  program
    .command("dashboard")
    .description("Read-only TUI: skill / paper / cohorts (Phase 9B).")
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
      } finally {
        await client.close();
      }
    });
}
