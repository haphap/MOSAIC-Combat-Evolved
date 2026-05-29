#!/usr/bin/env node
/**
 * mosaic-ts CLI entry.
 *
 * Phase 1 commands prove the bridge plumbing end-to-end. They are not the
 * eventual user-facing commands — the full surface (Layer-1/2/3/4 cycle,
 * cohort switch, autoresearch trigger, scorecard view, paper trading,
 * backtest, Ink TUI) lands in Phases 2–9.
 */

import { Command } from "commander";
import { registerAutoresearch } from "./commands/autoresearch.js";
import { registerBacktest } from "./commands/backtest.js";
import { registerBacktestFill } from "./commands/backtest-fill.js";
import { registerBridgePing } from "./commands/bridge-ping.js";
import { registerDailyCycle } from "./commands/daily-cycle.js";
import { registerDarwinian } from "./commands/darwinian.js";
import { registerJanus } from "./commands/janus.js";
import { registerPrism } from "./commands/prism.js";
import { registerScorecard } from "./commands/scorecard.js";
import { registerToolCall } from "./commands/tool-call.js";
import { registerToolLoop } from "./commands/tool-loop.js";

const program = new Command();

program
  .name("mosaic")
  .description("MOSAIC TypeScript CLI (Phase 1: bridge plumbing)")
  .version("0.1.0");

registerBridgePing(program);
registerToolCall(program);
registerToolLoop(program);
registerDailyCycle(program);
registerScorecard(program);
registerDarwinian(program);
registerBacktestFill(program);
registerBacktest(program);
registerAutoresearch(program);
registerPrism(program);
registerJanus(program);

await program.parseAsync(process.argv);
