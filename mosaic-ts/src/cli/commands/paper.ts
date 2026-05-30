/**
 * Phase 8 CLI: ``pnpm dev paper``.
 *
 * Paper-trading account over the bridge: auth, account/positions/trades,
 * buy/sell, and the signal→order suggestion. Fake money, local SQLite.
 */

import type { Command } from "commander";
import pc from "picocolors";
import { BridgeApi, BridgeClient, RpcError } from "../../bridge/index.js";
import { pad } from "../_format.js";

interface UserOpts {
  user?: string;
  db?: string;
}

function ids(opts: UserOpts): { user_id?: string; db_path?: string } {
  return { ...(opts.user ? { user_id: opts.user } : {}), ...(opts.db ? { db_path: opts.db } : {}) };
}

export function registerPaper(program: Command): void {
  const cmd = program.command("paper").description("Paper-trading account (Phase 8).");
  const userOpt = (c: Command) =>
    c
      .option("--user <name>", "Account user (default: session user)")
      .option("--db <path>", "SQLite db path");

  cmd
    .command("register")
    .argument("<username>")
    .argument("<password>")
    .option("--db <path>", "SQLite db path")
    .action(async (username: string, password: string, opts: { db?: string }) => {
      await withApi(async (api) => {
        const r = await api.paperRegister({
          username,
          password,
          ...(opts.db ? { db_path: opts.db } : {}),
        });
        console.log(pc.green(`registered '${r.username}'`));
      });
    });

  cmd
    .command("login")
    .argument("<username>")
    .argument("<password>")
    .option("--db <path>", "SQLite db path")
    .action(async (username: string, password: string, opts: { db?: string }) => {
      await withApi(async (api) => {
        const r = await api.paperLogin({
          username,
          password,
          ...(opts.db ? { db_path: opts.db } : {}),
        });
        console.log(r.ok ? pc.green(`logged in as '${r.username}'`) : pc.red("login failed"));
      });
    });

  cmd
    .command("logout")
    .option("--db <path>", "SQLite db path")
    .action(async (opts: { db?: string }) => {
      await withApi(async (api) => {
        const r = await api.paperLogout(opts.db ? { db_path: opts.db } : {});
        console.log(r.logged_out ? `logged out '${r.logged_out}'` : pc.dim("no active session"));
      });
    });

  userOpt(cmd.command("account").description("Show account summary.")).action(
    async (opts: UserOpts) => {
      await withApi(async (api) => {
        const a = await api.paperGetAccount(ids(opts));
        console.log(pc.bold(`\npaper account -- ${a.user_id}`));
        console.log(`  cash         ${a.cash.toFixed(2)}`);
        console.log(`  market_value ${a.market_value.toFixed(2)}`);
        console.log(`  total_assets ${a.total_assets.toFixed(2)}`);
        console.log(
          `  realized_pnl ${a.realized_pnl.toFixed(2)}  unrealized ${a.unrealized_pnl.toFixed(2)}`,
        );
      });
    },
  );

  userOpt(
    cmd
      .command("buy")
      .description("Buy a quantity (multiple of 100).")
      .argument("<ticker>")
      .argument("<quantity>"),
  ).action(async (ticker: string, quantity: string, opts: UserOpts) => {
    await withApi(async (api) => {
      const r = await api.paperBuy({
        ticker,
        quantity: Number.parseInt(quantity, 10),
        ...ids(opts),
      });
      console.log(
        pc.green(
          `buy ${r.quantity} ${r.ticker} @ ${r.price} = ${r.amount.toFixed(2)} (comm ${r.commission.toFixed(2)})`,
        ),
      );
    });
  });

  userOpt(
    cmd
      .command("sell")
      .description("Sell a quantity (multiple of 100).")
      .argument("<ticker>")
      .argument("<quantity>"),
  ).action(async (ticker: string, quantity: string, opts: UserOpts) => {
    await withApi(async (api) => {
      const r = await api.paperSell({
        ticker,
        quantity: Number.parseInt(quantity, 10),
        ...ids(opts),
      });
      console.log(
        pc.cyan(
          `sell ${r.quantity} ${r.ticker} @ ${r.price} = ${r.amount.toFixed(2)} (pnl ${(r.pnl ?? 0).toFixed(2)})`,
        ),
      );
    });
  });

  userOpt(cmd.command("positions").description("List open positions.")).action(
    async (opts: UserOpts) => {
      await withApi(async (api) => {
        const ps = await api.paperGetPositions(ids(opts));
        if (ps.length === 0) return void console.log(pc.dim("no positions"));
        console.log(
          pc.cyan(
            `\n  ${pad("ticker", 11)} ${pad("qty", 8)} ${pad("avail", 8)} ${pad("avg", 9)} ${pad("last", 9)} pnl%`,
          ),
        );
        for (const p of ps) {
          console.log(
            `  ${pad(p.ticker, 11)} ${pad(String(p.quantity), 8)} ${pad(String(p.available_qty), 8)} ` +
              `${pad(p.avg_cost.toFixed(3), 9)} ${pad(p.current_price.toFixed(3), 9)} ${p.pnl_pct.toFixed(2)}`,
          );
        }
      });
    },
  );

  userOpt(
    cmd.command("trades").description("Recent trades.").option("--limit <n>", "Rows (default 50)"),
  ).action(async (opts: UserOpts & { limit?: string }) => {
    await withApi(async (api) => {
      const ts = await api.paperGetTrades({
        ...ids(opts),
        ...(opts.limit ? { limit: Number.parseInt(opts.limit, 10) } : {}),
      });
      if (ts.length === 0) return void console.log(pc.dim("no trades"));
      console.log(
        pc.cyan(
          `\n  ${pad("date", 20)} ${pad("side", 5)} ${pad("ticker", 11)} ${pad("qty", 7)} price`,
        ),
      );
      for (const t of ts) {
        console.log(
          `  ${pad(t.created_at, 20)} ${pad(t.side, 5)} ${pad(t.ticker, 11)} ${pad(String(t.quantity), 7)} ${t.price}`,
        );
      }
    });
  });

  userOpt(
    cmd
      .command("suggest")
      .description("Suggest an order from a decision-state JSON (signal→order).")
      .argument("<ticker>")
      .argument("<state-json>"),
  ).action(async (ticker: string, stateJson: string, opts: UserOpts) => {
    await withApi(async (api) => {
      const state = JSON.parse(stateJson) as Record<string, unknown>;
      const s = await api.paperSuggestOrderFromSignal({ ticker, state, ...ids(opts) });
      console.log(
        s
          ? pc.bold(
              `suggest: ${s.side} ${s.quantity} ${s.ticker} @ ${s.price} (target ${s.target_weight_pct}%, ${s.rating})`,
            )
          : pc.dim("no actionable order"),
      );
    });
  });
}

async function withApi(fn: (api: BridgeApi) => Promise<void>): Promise<void> {
  const client = new BridgeClient();
  const api = new BridgeApi(client);
  try {
    await client.start();
    await fn(api);
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
}
