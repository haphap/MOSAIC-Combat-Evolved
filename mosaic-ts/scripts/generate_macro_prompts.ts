import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import {
  MACRO_AGENT_IDS,
  MACRO_ROLE_CONTRACTS,
  renderMacroRuntimeContract,
} from "../src/agents/macro/_contracts.js";
import { renderResearchKnobsFence } from "../src/agents/helpers/research_knobs.js";
import { buildRuntimeResearchKnobs, upsertRuntimeEvidenceContract } from "../src/agents/prompts/research_knobs_projection.js";
import { RUNTIME_AGENT_SPEC_BY_AGENT } from "../src/agents/prompts/runtime_agent_spec.js";

interface Target {
  root: string;
  cohorts: string[];
}

const targets = parseTargets(process.argv.slice(2));
if (targets.length === 0) {
  throw new Error("usage: generate_macro_prompts.ts <prompts/mosaic root>:<cohort,...> [...]");
}

for (const target of targets) {
  for (const cohort of target.cohorts) {
    const macroDir = resolve(target.root, cohort, "macro");
    mkdirSync(macroDir, { recursive: true });
    rmSync(join(macroDir, "emerging_markets.zh.md"), { force: true });
    rmSync(join(macroDir, "emerging_markets.en.md"), { force: true });
    rmSync(join(macroDir, "news_sentiment.zh.md"), { force: true });
    rmSync(join(macroDir, "news_sentiment.en.md"), { force: true });
    for (const agent of MACRO_AGENT_IDS) {
      const spec = RUNTIME_AGENT_SPEC_BY_AGENT.get(agent);
      if (!spec) throw new Error(`runtime spec missing for ${agent}`);
      const knobs = buildRuntimeResearchKnobs(spec);
      for (const language of ["zh", "en"] as const) {
        const base = [
          renderResearchKnobsFence(knobs),
          "",
          language === "zh" ? `# ${agent} — Layer-1 宏观传导` : `# ${agent} — Layer-1 macro transmission`,
          "",
          renderMacroRuntimeContract(agent, language),
          "",
          language === "zh" ? commonZh(agent) : commonEn(agent),
          "",
        ].join("\n");
        const prompt = upsertRuntimeEvidenceContract(base, spec, language);
        writeFileSync(join(macroDir, `${agent}.${language}.md`), prompt, "utf8");
      }
    }
  }
}

function commonZh(agent: (typeof MACRO_AGENT_IDS)[number]): string {
  const eventRule =
    agent === "china" || agent === "geopolitical"
      ? "Tushare major_news 与官方政策文件只能作为去重、发布时间过滤后的事件证据；不得形成独立新闻情绪票。"
      : "不得读取或推断新闻情绪；事件证据只属于 china 与 geopolitical。";
  return [
    "## 分析流程",
    "1. 必须调用唯一允许的角色快照；工具失败、PIT 状态无效或覆盖不足时拒绝该阶段，不得改写为中性市场。",
    "2. 逐项检查 released_at、vintage_at 与 as-of；比较实际值、前值、预期差和变化，明确冲突证据。",
    "3. 只解释本角色负责的传导渠道，并落到 A 股风险溢价、盈利、流动性或行业敏感度。",
    "4. 结论必须由非空 claims、结论级 claim_refs、key_drivers、channels 与 confidence 支持。",
    "",
    eventRule,
    "不得调用 OpenCLI、Google/财新搜索或实时雪球关注数。不得虚构来源、数值、百分比、时间戳或快照字段。",
    "commodities 仅在快照含真实期限结构时使用 contango/backwardation；volatility 必须区分美国隐含波动与中国实现波动。",
    "legacy emerging_markets/news_sentiment 仅供旧审计，状态为 legacy_unverified，不能作为当前证据或 Darwinian 先验。",
  ].join("\n");
}

function commonEn(agent: (typeof MACRO_AGENT_IDS)[number]): string {
  const eventRule =
    agent === "china" || agent === "geopolitical"
      ? "Tushare major_news and official policy documents are deduplicated, timestamp-filtered event evidence only; never cast a separate news-sentiment vote."
      : "Do not read or infer news sentiment; event evidence belongs only to china and geopolitical.";
  return [
    "## Analysis workflow",
    "1. Call the one allowed role snapshot. Reject the stage when the tool fails, PIT validity fails, or required coverage is insufficient; never turn missing data into a neutral market.",
    "2. Check released_at and vintage_at against as-of; compare actual, previous, expectation surprise, and changes, and expose conflicting evidence.",
    "3. Explain only this role's transmission into A-share risk premia, earnings, liquidity, or sector sensitivity.",
    "4. Support the conclusion with non-empty claims, conclusion-level claim_refs, key_drivers, channels, and confidence.",
    "",
    eventRule,
    "Never call OpenCLI, Google/Caixin search, or real-time Xueqiu follower counts. Never invent sources, values, percentages, timestamps, or snapshot fields.",
    "commodities may use contango/backwardation only with a real term structure; volatility must distinguish US implied volatility from China realized volatility.",
    "Legacy emerging_markets/news_sentiment outputs are audit-only legacy_unverified records and provide no current evidence or Darwinian prior.",
  ].join("\n");
}

function parseTargets(args: string[]): Target[] {
  return args.map((arg) => {
    const separator = arg.lastIndexOf(":");
    if (separator <= 0) throw new Error(`invalid target ${arg}`);
    const root = arg.slice(0, separator);
    const cohorts = arg
      .slice(separator + 1)
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    if (cohorts.length === 0) throw new Error(`target has no cohorts: ${arg}`);
    return { root, cohorts };
  });
}
