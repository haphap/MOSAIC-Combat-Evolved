/**
 * `pnpm dev data` — refresh local qlib datasets (cn_data / cn_etf) via the
 * vendored Tushare collectors (Request #2).
 *
 *   data incremental --kind stock|etf --end YYYY-MM-DD   append latest days
 *   data validate    --kind stock|etf                    quality report
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
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function parseKind(kind: string | undefined): "stock" | "etf" {
  if (kind === "etf") return "etf";
  if (kind === undefined || kind === "stock") return "stock";
  throw new Error(`--kind must be 'stock' or 'etf', got '${kind}'`);
}

export function registerData(program: Command): void {
  const data = program.command("data").description("Refresh local qlib datasets (stock / ETF).");

  data
    .command("incremental")
    .description("Append the latest trading days to cn_data (stock) or cn_etf (etf).")
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
