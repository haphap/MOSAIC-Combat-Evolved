import type { Command } from "commander";
import pc from "picocolors";
import { BridgeApi, BridgeClient, RpcError } from "../../bridge/index.js";

export function registerToolCall(program: Command): void {
  program
    .command("tool-call <name> [argsJson]")
    .description("Invoke a bridge tool directly. Args is a JSON object string.")
    .option("--as-of-date <date>", "Backtest mode: clamp date arguments to this YYYY-MM-DD")
    .action(async (name: string, argsJson: string | undefined, opts: { asOfDate?: string }) => {
      const args: Record<string, unknown> = argsJson ? JSON.parse(argsJson) : {};
      const client = new BridgeClient();
      const api = new BridgeApi(client);
      try {
        await client.start();
        const result = await api.toolsCall(
          name,
          args,
          opts.asOfDate ? { mode: "backtest", as_of_date: opts.asOfDate } : undefined,
        );
        console.log(result.text);
      } catch (err) {
        if (err instanceof RpcError) {
          console.error(pc.red(`tool error [${err.code}]: ${err.message}`));
        } else {
          console.error(pc.red(`error: ${(err as Error).message}`));
        }
        process.exitCode = 1;
      } finally {
        await client.close();
      }
    });
}
