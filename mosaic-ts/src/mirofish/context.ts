/**
 * 7M Step 2: format a persisted MiroFish context into a prompt section for the
 * CIO decision agent (the ATLAS get_agent_context pathway, but open-source).
 *
 * Returns null when there's nothing usable (no context, or all fields empty) so
 * the caller appends nothing. Degrades cleanly on the None fields Step 1 locked
 * (hct_direction / tail_summary may be absent). Always carries the
 * "simulation only" disclaimer — these are rehearsed futures, not forecasts.
 * Labels follow the resolved prompt language (en → English, else Chinese).
 */

import type { LoaderLanguage } from "../agents/prompts/loader.js";
import type { MirofishContext } from "../bridge/types.js";

interface Labels {
  title: string;
  date: string;
  base: string;
  hct: string;
  tail: string;
  stress: string;
  meta: string;
  disclaimer: string;
}

const ZH: Labels = {
  title: "### 前瞻情景参考（MiroFish 模拟）",
  date: "情景日期",
  base: "基准情景",
  hct: "最高信念方向",
  tail: "尾部风险",
  stress: "持仓压力",
  meta: "情景元数据",
  disclaimer: "*以上为模拟情景,仅供参考,请结合你自己的分析判断,不构成确定性预测。*",
};

const EN: Labels = {
  title: "### Forward-Looking Context (MiroFish Simulations)",
  date: "Scenario date",
  base: "Base scenario",
  hct: "Highest-conviction direction",
  tail: "Tail risk",
  stress: "Position stress",
  meta: "Scenario metadata",
  disclaimer: "*Simulations, not certainties — weight alongside your own analysis.*",
};

const pct = (v: number | null | undefined): string => `${((v ?? 0) * 100).toFixed(1)}%`;

export function formatMirofishContext(
  ctx: MirofishContext | null | undefined,
  language: LoaderLanguage = "zh",
): string | null {
  if (!ctx || (ctx.regime == null && ctx.hct_direction == null && ctx.tail_summary == null)) {
    return null;
  }
  const L = language === "en" ? EN : ZH;
  const lines: string[] = ["", L.title];
  if (ctx.date) lines.push(`${L.date}: ${ctx.date}`);
  if (ctx.regime != null) {
    lines.push(`${L.base}: ${ctx.regime}（CSI300 ${pct(ctx.csi300_return)}）`);
  }
  if (ctx.hct_direction != null) {
    lines.push(
      `${L.hct}: ${ctx.hct_ticker} ${ctx.hct_direction}（CSI300 ${pct(ctx.hct_csi300_return)}）`,
    );
  }
  if (ctx.tail_summary != null) {
    lines.push(`${L.tail}: ${ctx.tail_summary}`);
  }
  if (ctx.position_stress && ctx.position_stress.length > 0) {
    const stress = ctx.position_stress
      .slice(0, 6)
      .map(
        (item) =>
          `${item.ticker} tail=${pct(item.tail_loss)} agree=${pct(item.scenario_agreement)} action=${item.suggested_action ?? "?"}`,
      )
      .join("; ");
    lines.push(`${L.stress}: ${stress}`);
  }
  const scenarioCount = ctx.scenario_count ?? ctx.n_scenarios;
  const horizon = ctx.horizon_days;
  const contextHash = ctx.context_hash;
  const asOfDate = ctx.as_of_date;
  const generatorVersion = ctx.generator_version;
  if (scenarioCount || horizon || contextHash || asOfDate || generatorVersion) {
    lines.push(
      `${L.meta}: scenarios=${scenarioCount ?? "?"}` +
        `${horizon ? ` horizon_days=${horizon}` : ""}` +
        `${asOfDate ? ` as_of_date=${asOfDate}` : ""}` +
        `${contextHash ? ` context_hash=${contextHash}` : ""}` +
        `${generatorVersion ? ` generator_version=${generatorVersion}` : ""}`,
    );
  }
  lines.push("", L.disclaimer, "");
  return lines.join("\n");
}
