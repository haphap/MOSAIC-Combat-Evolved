/**
 * 7M Step 2: format a persisted MiroFish context into a prompt section for the
 * CIO decision agent (the ATLAS get_agent_context pathway, but open-source).
 *
 * Returns null when there's nothing usable (no context, or all fields empty) so
 * the caller appends nothing. Degrades cleanly on the None fields Step 1 locked
 * (hct_direction / tail_summary may be absent). Always carries the
 * "simulation only" disclaimer — these are rehearsed futures, not forecasts.
 */

import type { MirofishContext } from "../bridge/types.js";

export function formatMirofishContext(ctx: MirofishContext | null | undefined): string | null {
  if (!ctx || (ctx.regime == null && ctx.hct_direction == null && ctx.tail_summary == null)) {
    return null;
  }
  const lines: string[] = ["", "### 前瞻情景参考（MiroFish 模拟）"];
  if (ctx.date) lines.push(`情景日期: ${ctx.date}`);
  if (ctx.regime != null) {
    lines.push(`基准情景: ${ctx.regime}（CSI300 ${(ctx.csi300_return * 100).toFixed(1)}%）`);
  }
  if (ctx.hct_direction != null) {
    lines.push(
      `最高信念方向: ${ctx.hct_ticker} ${ctx.hct_direction}` +
        `（情景内 CSI300 ${(ctx.hct_csi300_return * 100).toFixed(1)}%）`,
    );
  }
  if (ctx.tail_summary != null) {
    lines.push(`尾部风险: ${ctx.tail_summary}`);
  }
  lines.push("", "*以上为模拟情景,仅供参考,请结合你自己的分析判断,不构成确定性预测。*", "");
  return lines.join("\n");
}
