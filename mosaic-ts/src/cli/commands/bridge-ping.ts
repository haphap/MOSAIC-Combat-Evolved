import type { Command } from "commander";
import pc from "picocolors";
import { BridgeApi, BridgeClient, resolvePython } from "../../bridge/index.js";

export function registerBridgePing(program: Command): void {
  program
    .command("bridge-ping")
    .description("Verify the Python sidecar starts and answers tools.list / config.get")
    .action(async () => {
      const python = resolvePython();
      console.log(pc.dim(`python:    ${python.python}`));
      console.log(pc.dim(`source:    ${python.source}`));
      console.log(pc.dim(`repo root: ${python.repoRoot}`));

      const client = new BridgeClient({ python });
      const api = new BridgeApi(client);
      try {
        await client.start();
        const tools = await api.toolsList();
        const config = await api.configGet();
        console.log(
          pc.green(
            `\nbridge ok: ${tools.length} tools, llm_provider=${String(config.llm_provider)}, ` +
              `deep=${String(config.deep_think_llm)}, output_language=${String(config.output_language)}, ` +
              `active_cohort=${String(config.active_cohort)}`,
          ),
        );
        console.log(
          pc.dim(
            `tools: ${tools
              .slice(0, 10)
              .map((t) => t.name)
              .join(", ")}${tools.length > 10 ? ", …" : ""}`,
          ),
        );
      } catch (err) {
        console.error(pc.red(`\nbridge failed: ${(err as Error).message}`));
        const tail = client.stderrTail.trim();
        if (tail) {
          console.error(pc.dim("\n--- bridge stderr (tail) ---"));
          console.error(pc.dim(tail.slice(-2000)));
        }
        process.exitCode = 1;
      } finally {
        await client.close();
      }
    });
}
