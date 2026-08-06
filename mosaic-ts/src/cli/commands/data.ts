/**
 * `pnpm dev data` — refresh local qlib datasets (cn_data / cn_etf) via the
 * vendored Tushare collectors (Request #2).
 *
 *   data incremental --kind stock|etf --end YYYY-MM-DD   append latest days
 *   data validate        --kind stock|etf                    quality report
 *   data source-status   --as-of DATE --route ROUTE          capture status
 *   data snapshot-status --as-of DATE --agent AGENT --stage STAGE
 *   data materialize     --dry-run --as-of DATE --agent AGENT --stage STAGE
 *
 * Needs the Python `ingest` (+ `data`, `backtest`) extras installed; missing
 * deps surface as a DATA_ERROR from the bridge.
 */

import type { Command } from "commander";
import pc from "picocolors";
import { BridgeApi, BridgeClient, RpcError } from "../../bridge/index.js";

interface DataOpts {
  kind?: string;
  end?: string;
  gapThreshold?: string;
  asOf?: string;
  route?: string;
  agent?: string;
  stage?: string;
  dryRun?: boolean;
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function parseKind(kind: string | undefined): "stock" | "etf" {
  if (kind === "etf") return "etf";
  if (kind === undefined || kind === "stock") return "stock";
  throw new Error(`--kind must be 'stock' or 'etf', got '${kind}'`);
}

function requireOption(value: string | undefined, option: string): string {
  if (value === undefined || value.trim() === "") {
    throw new Error(`${option} is required`);
  }
  return value.trim();
}

export function registerData(program: Command): void {
  const data = program
    .command("data")
    .description("Refresh datasets and inspect Agent data materialization status.");

  data
    .command("incremental")
    .description(
      "Append latest trading days to cn_data (stock) / cn_etf (etf). Long-running (minutes) — run as a cron, not alongside live RPCs.",
    )
    .option("--kind <kind>", "stock | etf", "stock")
    .option("--end <date>", "Fetch through YYYY-MM-DD (default: today)")
    .action(async (opts: DataOpts) => {
      const client = new BridgeClient();
      const api = new BridgeApi(client);
      try {
        const kind = parseKind(opts.kind);
        await client.start();
        const res = await api.dataIncremental({ kind, end: opts.end ?? todayIso() });
        if (res.ok) {
          console.log(pc.green(`✓ ${kind} incremental update ok → ${res.qlib_dir}`));
        } else {
          console.error(pc.red(`✗ ${kind} update failed (collector exit ${res.returncode})`));
          process.exitCode = 1;
        }
      } catch (err) {
        reportError(err, client);
      } finally {
        await client.close();
      }
    });

  data
    .command("validate")
    .description("Validate an ingested dataset + write the skip manifest.")
    .option("--kind <kind>", "stock | etf", "stock")
    .option("--gap-threshold <pct>", "Flag tickers with gap > this fraction (default 0.01)")
    .action(async (opts: DataOpts) => {
      const client = new BridgeClient();
      const api = new BridgeApi(client);
      try {
        const kind = parseKind(opts.kind);
        await client.start();
        const params: { kind: "stock" | "etf"; gap_threshold?: number } = { kind };
        if (opts.gapThreshold !== undefined) params.gap_threshold = Number(opts.gapThreshold);
        const report = await api.dataValidate(params);
        for (const [k, v] of Object.entries(report)) {
          console.log(`${k.padEnd(16)} ${String(v)}`);
        }
      } catch (err) {
        reportError(err, client);
      } finally {
        await client.close();
      }
    });

  data
    .command("source-status")
    .description("Read one Agent data route's sealed capture status.")
    .requiredOption("--as-of <date>", "Point-in-time date (YYYY-MM-DD)")
    .requiredOption("--route <route>", "Logical route id")
    .action(async (opts: DataOpts) => {
      const client = new BridgeClient();
      const api = new BridgeApi(client);
      try {
        await client.start();
        const status = await api.dataSourceStatus({
          as_of: requireOption(opts.asOf, "--as-of"),
          route_id: requireOption(opts.route, "--route"),
        });
        console.log(JSON.stringify(status, null, 2));
      } catch (err) {
        reportError(err, client);
      } finally {
        await client.close();
      }
    });

  data
    .command("snapshot-status")
    .description("Read frozen snapshot-build status for one Agent stage.")
    .requiredOption("--as-of <date>", "Point-in-time date (YYYY-MM-DD)")
    .requiredOption("--agent <agent>", "Agent id")
    .requiredOption("--stage <stage>", "Execution stage")
    .action(async (opts: DataOpts) => {
      const client = new BridgeClient();
      const api = new BridgeApi(client);
      try {
        await client.start();
        const status = await api.dataSnapshotStatus({
          as_of: requireOption(opts.asOf, "--as-of"),
          agent_id: requireOption(opts.agent, "--agent"),
          stage: requireOption(opts.stage, "--stage"),
        });
        console.log(JSON.stringify(status, null, 2));
      } catch (err) {
        reportError(err, client);
      } finally {
        await client.close();
      }
    });

  data
    .command("materialize")
    .description("Inspect the materialization plan; PR1 supports dry-run only.")
    .option("--dry-run", "Do not collect, build, write, or issue a capability")
    .requiredOption("--as-of <date>", "Point-in-time date (YYYY-MM-DD)")
    .requiredOption("--agent <agent>", "Agent id")
    .requiredOption("--stage <stage>", "Execution stage")
    .action(async (opts: DataOpts) => {
      const client = new BridgeClient();
      const api = new BridgeApi(client);
      try {
        if (opts.dryRun !== true) {
          throw new Error("data materialize currently requires --dry-run");
        }
        await client.start();
        const status = await api.dataMaterializeDryRun({
          as_of: requireOption(opts.asOf, "--as-of"),
          agent_id: requireOption(opts.agent, "--agent"),
          stage: requireOption(opts.stage, "--stage"),
          dry_run: true,
        });
        console.log(JSON.stringify(status, null, 2));
      } catch (err) {
        reportError(err, client);
      } finally {
        await client.close();
      }
    });
}

function reportError(err: unknown, client: BridgeClient): void {
  if (err instanceof RpcError) {
    console.error(pc.red(`bridge error [${err.code}]: ${err.message}`));
  } else {
    console.error(pc.red(`error: ${(err as Error).message}`));
  }
  const tail = client.stderrTail?.trim();
  if (tail) console.error(pc.dim(tail.slice(-1500)));
  process.exitCode = 1;
}
