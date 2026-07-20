#!/usr/bin/env node
/**
 * mosaic-ts CLI entry.
 *
 * The command surface covers bridge diagnostics, the Layer-1/2/3/4 cycle,
 * prompt releases, evaluation, paper trading, backtests, and the Ink TUI.
 */

import { Command } from "commander";
import { registerAutoresearch } from "./commands/autoresearch.js";
import { registerBacktest } from "./commands/backtest.js";
import { registerBacktestEvolve } from "./commands/backtest-evolve.js";
import { registerBacktestFill } from "./commands/backtest-fill.js";
import { registerBridgePing } from "./commands/bridge-ping.js";
import { registerDailyCycle } from "./commands/daily-cycle.js";
import { registerDarwinian } from "./commands/darwinian.js";
import { registerDashboard } from "./commands/dashboard.js";
import { registerData } from "./commands/data.js";
import { registerJanus } from "./commands/janus.js";
import { registerMirofish } from "./commands/mirofish.js";
import { registerPaper } from "./commands/paper.js";
import { registerPrism } from "./commands/prism.js";
import { registerPromptRelease } from "./commands/prompt-release.js";
import { registerPrompts } from "./commands/prompts.js";
import { registerRkeDarwinianCompute } from "./commands/rke-darwinian-compute.js";
import { registerRkeFixedBenchmark } from "./commands/rke-fixed-benchmark.js";
import { registerRkePaperPromotionEvidence } from "./commands/rke-paper-promotion-evidence.js";
import { registerRkePatchActivationEvidence } from "./commands/rke-patch-activation-evidence.js";
import { registerRkeProfileEvidence } from "./commands/rke-profile-evidence.js";
import { registerRkePromptMutationReleaseEvidence } from "./commands/rke-prompt-mutation-release-evidence.js";
import { registerRkePromptProvenanceEvidence } from "./commands/rke-prompt-provenance-evidence.js";
import { registerRkeRollbackRehearsalEvidence } from "./commands/rke-rollback-rehearsal-evidence.js";
import { registerRkeShadowReplay } from "./commands/rke-shadow-replay.js";
import { registerScorecard } from "./commands/scorecard.js";
import { registerToolLoop } from "./commands/tool-loop.js";
import { loadProjectEnv } from "./env.js";

loadProjectEnv();

const program = new Command();

program
  .name("mosaic")
  .description("MOSAIC TypeScript research and orchestration CLI")
  .version("0.1.0");

registerBridgePing(program);
registerToolLoop(program);
registerDailyCycle(program);
registerScorecard(program);
registerDarwinian(program);
registerBacktestFill(program);
registerBacktest(program);
registerBacktestEvolve(program);
registerAutoresearch(program);
registerPrism(program);
registerJanus(program);
registerMirofish(program);
registerPaper(program);
registerPrompts(program);
registerPromptRelease(program);
registerRkePatchActivationEvidence(program);
registerRkeProfileEvidence(program);
registerRkeDarwinianCompute(program);
registerRkeFixedBenchmark(program);
registerRkePaperPromotionEvidence(program);
registerRkePromptMutationReleaseEvidence(program);
registerRkePromptProvenanceEvidence(program);
registerRkeRollbackRehearsalEvidence(program);
registerRkeShadowReplay(program);
registerDashboard(program);
registerData(program);

await program.parseAsync(process.argv);
