/**
 * news_sentiment Layer-1 macro agent (Plan §5.1).
 *
 * Plan §5.1 tools: `get_xueqiu_heat` + `get_news` (opencli) +
 * `get_caixin_sentiment` (now available — Caixin/财新 via opencli, gap closed
 * §14 #8). `get_industry_policy` (policy-keyword filter over Tushare news)
 * retained as a corroborator.
 */

import type { NewsSentimentOutput } from "../types.js";
import {
  buildLayerOneAgentNode,
  type LayerOneAgentDeps,
  type LayerOneAgentNode,
  type LayerOneAgentSpec,
} from "./_factory.js";
import { NEWS_SENTIMENT_FIELD_NAMES, NewsSentimentSchema } from "./_schemas.js";

export const REQUIRED_TOOLS = [
  "get_xueqiu_heat",
  "get_news",
  "get_caixin_sentiment",
  "get_industry_policy",
] as const;

export const newsSentimentSpec: LayerOneAgentSpec<NewsSentimentOutput> = {
  agentId: "news_sentiment",
  schema: NewsSentimentSchema,
  fieldNames: NEWS_SENTIMENT_FIELD_NAMES,
  requiredTools: REQUIRED_TOOLS,
  render: renderNewsSentiment,
  fallback: fallbackNewsSentiment,
};

export function buildNewsSentimentNode(deps: LayerOneAgentDeps): LayerOneAgentNode {
  return buildLayerOneAgentNode(newsSentimentSpec, deps);
}

export function renderNewsSentiment(o: NewsSentimentOutput): string {
  const topics = (o.hot_topics ?? []).join(", ");
  const drivers = (o.key_drivers ?? []).map((d) => `  - ${d}`).join("\n");
  return (
    `news_sentiment analysis (confidence=${o.confidence.toFixed(2)})\n` +
    `  retail_sentiment_score: ${o.retail_sentiment_score.toFixed(2)}\n` +
    `  hot_topics:             ${topics}\n` +
    `  contrarian_flag:        ${o.contrarian_flag}\n` +
    `  key_drivers:\n${drivers}`
  );
}

export function fallbackNewsSentiment(text: string): NewsSentimentOutput {
  const trimmed = (text ?? "").trim();
  return {
    agent: "news_sentiment",
    retail_sentiment_score: 0,
    hot_topics: ["unknown"],
    contrarian_flag: false,
    key_drivers: trimmed ? [trimmed.slice(0, 80)] : ["analysis missing"],
    confidence: 0,
  };
}

export { NEWS_SENTIMENT_FIELD_NAMES, NewsSentimentSchema };
