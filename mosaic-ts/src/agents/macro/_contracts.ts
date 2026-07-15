import { z } from "zod";
import { LlmResearchClaimSchema } from "../evidence_contract.js";
import type { MacroAgentId, MacroAgentOutput } from "../types.js";

export interface MacroRoleContract {
  agentId: MacroAgentId;
  responsibility: { zh: string; en: string };
  prohibited: { zh: ReadonlyArray<string>; en: ReadonlyArray<string> };
  requiredTools: readonly [string];
}

export const MACRO_AGENT_IDS = [
  "china",
  "us_economy",
  "central_bank",
  "dollar",
  "yield_curve",
  "commodities",
  "geopolitical",
  "volatility",
  "market_breadth",
  "institutional_flow",
] as const satisfies ReadonlyArray<MacroAgentId>;

export const MACRO_PROMPT_COHORT_IDS = [
  "cohort_default",
  "cohort_bull_2007",
  "cohort_bull_2016",
  "cohort_crisis_2008",
  "cohort_crisis_covid",
  "cohort_euphoria_2021",
  "cohort_rate_tightening",
  "cohort_recovery_2020",
] as const;

export type MacroPromptCohortId = (typeof MACRO_PROMPT_COHORT_IDS)[number];

export const MACRO_COHORT_LENSES: Readonly<
  Record<MacroPromptCohortId, { zh: string; en: string }>
> = {
  cohort_default: {
    zh: "默认实时基线：不预设牛熊状态，由本角色快照中的当前 PIT 证据决定。",
    en: "Default live baseline: assume no bull or bear regime; let current PIT evidence in this role's snapshot decide.",
  },
  cohort_bull_2007: {
    zh: "流动性牛市与泡沫尾部压力测试：检验有利条件是扩大参与度，还是只放大杠杆与脆弱性。",
    en: "Liquidity-bull and bubble-tail stress test: distinguish broader participation from leverage-amplified fragility.",
  },
  cohort_bull_2016: {
    zh: "供给侧改革与周期修复压力测试：区分可持续的基本面改善与短暂的价格、库存或政策脉冲。",
    en: "Supply-side-reform and cyclical-repair stress test: separate durable fundamental improvement from temporary price, inventory, or policy impulses.",
  },
  cohort_crisis_2008: {
    zh: "信用危机压力测试：优先检查冲击是否通过融资、流动性、外需或资产负债表脆弱性被放大。",
    en: "Credit-crisis stress test: prioritize amplification through funding, liquidity, external demand, or balance-sheet fragility.",
  },
  cohort_crisis_covid: {
    zh: "疫情冲击压力测试：区分暂时停摆、持续需求损伤、供应约束与政策托底。",
    en: "Pandemic-shock stress test: separate temporary shutdowns, persistent demand damage, supply constraints, and policy backstops.",
  },
  cohort_euphoria_2021: {
    zh: "拥挤繁荣压力测试：降低单一叙事或单一渠道确认的可信度，并检查反转触发器。",
    en: "Crowded-boom stress test: discount single-narrative or single-channel confirmation and identify reversal triggers.",
  },
  cohort_rate_tightening: {
    zh: "利率与信用收紧压力测试：检查紧缩冲击的持续性、传导时滞与非对称影响。",
    en: "Rate- and credit-tightening stress test: examine persistence, transmission lags, and asymmetric effects of tightening shocks.",
  },
  cohort_recovery_2020: {
    zh: "早期复苏压力测试：区分低基数反弹、连续修复与能够延续的周期加速。",
    en: "Early-recovery stress test: distinguish low-base rebounds, sequential repair, and durable cyclical acceleration.",
  },
};

export const MACRO_ROLE_CONTRACTS: Readonly<Record<MacroAgentId, MacroRoleContract>> = {
  china: {
    agentId: "china",
    responsibility: {
      zh: "判断中国增长、价格、信用、外需与财政脉冲对 A 股的传导。",
      en: "Assess how Chinese growth, prices, credit, external demand, and fiscal impulse transmit to A-shares.",
    },
    prohibited: {
      zh: ["不得把地产作为每次分析的必选维度", "不得判断 PBOC 立场"],
      en: ["Do not require property in every analysis", "Do not infer a PBOC stance"],
    },
    requiredTools: ["get_china_macro_snapshot"],
  },
  us_economy: {
    agentId: "us_economy",
    responsibility: {
      zh: "判断美国增长、就业、通胀与需求周期对 A 股的传导。",
      en: "Assess how the US growth, employment, inflation, and demand cycle transmits to A-shares.",
    },
    prohibited: {
      zh: ["不得判断 Fed", "不得判断美元或收益率曲线"],
      en: ["Do not infer Fed policy", "Do not judge the dollar or yield curve"],
    },
    requiredTools: ["get_us_macro_snapshot"],
  },
  central_bank: {
    agentId: "central_bank",
    responsibility: {
      zh: "判断 PBOC/Fed 反应函数、政策倾向、流动性与政策分化。",
      en: "Assess PBOC/Fed reaction functions, policy bias, liquidity, and policy divergence.",
    },
    prohibited: {
      zh: ["不得重复给中美经济周期投票", "不得读取其他 Agent 输出"],
      en: ["Do not cast another China/US cycle vote", "Do not read another agent's output"],
    },
    requiredTools: ["get_central_bank_snapshot"],
  },
  dollar: {
    agentId: "dollar",
    responsibility: {
      zh: "判断广义美元、人民币状态、汇率压力与 A 股流动性传导。",
      en: "Assess the broad dollar, RMB state, FX pressure, and A-share liquidity transmission.",
    },
    prohibited: {
      zh: ["不得把广义美元指标冒充 DXY", "不得判断美国经济"],
      en: ["Do not label a broad-dollar index as DXY", "Do not judge the US economy"],
    },
    requiredTools: ["get_fx_conditions_snapshot"],
  },
  yield_curve: {
    agentId: "yield_curve",
    responsibility: {
      zh: "判断中美名义/实际曲线、货币市场、信用条件与久期定价。",
      en: "Assess Chinese/US nominal and real curves, money markets, credit conditions, and duration pricing.",
    },
    prohibited: {
      zh: ["不得输出衰退灯号", "不得输出央行政策结论"],
      en: ["Do not emit a recession traffic light", "Do not infer central-bank policy"],
    },
    requiredTools: ["get_rates_credit_snapshot"],
  },
  commodities: {
    agentId: "commodities",
    responsibility: {
      zh: "判断能源期限结构/库存、工业金属、黄金与通胀冲击。",
      en: "Assess energy term structure/inventories, industrial metals, gold, and inflation shocks.",
    },
    prohibited: {
      zh: ["无真实期限结构数据时不得声称 contango 或 backwardation"],
      en: ["Do not claim contango or backwardation without actual term-structure data"],
    },
    requiredTools: ["get_commodity_conditions_snapshot"],
  },
  geopolitical: {
    agentId: "geopolitical",
    responsibility: {
      zh: "判断事件状态、传导渠道、严重度、期限与观察触发器。",
      en: "Assess event status, transmission channels, severity, horizon, and monitoring triggers.",
    },
    prohibited: {
      zh: ["不得虚构价格影响百分比"],
      en: ["Do not invent percentage price impacts"],
    },
    requiredTools: ["get_geopolitical_events_snapshot"],
  },
  volatility: {
    agentId: "volatility",
    responsibility: {
      zh: "判断美国隐含波动、中国实现波动与跨市场压力。",
      en: "Assess US implied volatility, China realized volatility, and cross-market stress.",
    },
    prohibited: {
      zh: ["不得把实现波动率称为 iVX"],
      en: ["Do not call realized volatility iVX"],
    },
    requiredTools: ["get_volatility_snapshot"],
  },
  market_breadth: {
    agentId: "market_breadth",
    responsibility: {
      zh: "解释 A 股参与度、趋势广度、成交广度、新高新低与集中度的传导。",
      en: "Interpret A-share participation, trend breadth, turnover breadth, new highs/lows, and concentration.",
    },
    prohibited: {
      zh: ["不得读取新闻、资金流或波动率后重复判断", "不得自行重算快照指标"],
      en: [
        "Do not duplicate news, flow, or volatility judgments",
        "Do not recompute snapshot metrics",
      ],
    },
    requiredTools: ["get_market_breadth_snapshot"],
  },
  institutional_flow: {
    agentId: "institutional_flow",
    responsibility: {
      zh: "判断全市场资金、行业轮动、ETF 份额与拥挤度。",
      en: "Assess market-wide flows, sector rotation, ETF shares, and crowding.",
    },
    prohibited: {
      zh: ["龙虎榜只能作为辅助", "不得以抽样个股代表全市场"],
      en: [
        "Use Dragon-Tiger data only as supporting evidence",
        "Do not represent the market with sampled stocks",
      ],
    },
    requiredTools: ["get_market_positioning_snapshot"],
  },
};

const STRENGTH = z.union([
  z.literal(0),
  z.literal(1),
  z.literal(2),
  z.literal(3),
  z.literal(4),
  z.literal(5),
]);

export const MACRO_OUTPUT_FIELD_NAMES = [
  "direction",
  "strength",
  "horizon",
  "channels",
  "key_drivers",
  "confidence",
  "claims",
  "claim_refs",
] as const;

export function createMacroOutputSchema<TAgent extends MacroAgentId>(agent: TAgent) {
  return z
    .object({
      agent: z.literal(agent),
      direction: z.enum(["SUPPORTIVE", "NEUTRAL", "ADVERSE"]),
      strength: STRENGTH,
      horizon: z.enum(["DAYS", "WEEKS", "MONTHS"]),
      channels: z.array(z.string().min(1)).min(1).max(8),
      key_drivers: z.array(z.string().min(1)).min(1).max(8),
      confidence: z.number().min(0).max(1),
      declared_knob_influence_ids: z.array(z.string().min(1)).optional(),
      declared_influence_rationale: z.string().min(1).optional(),
      claims: z.array(LlmResearchClaimSchema).min(1),
      claim_refs: z.array(z.string().min(1)).min(1),
    })
    .superRefine((output, ctx) => {
      if (output.direction === "NEUTRAL" && output.strength !== 0) {
        ctx.addIssue({
          code: "custom",
          path: ["strength"],
          message: "NEUTRAL requires strength=0",
        });
      }
      if (output.direction !== "NEUTRAL" && output.strength === 0) {
        ctx.addIssue({
          code: "custom",
          path: ["strength"],
          message: "non-neutral direction requires strength in 1..5",
        });
      }
    }) as unknown as z.ZodType<Extract<MacroAgentOutput, { agent: TAgent }>>;
}

export function renderMacroRuntimeContract(agent: MacroAgentId, language: "zh" | "en"): string {
  const role = MACRO_ROLE_CONTRACTS[agent];
  const prohibited = role.prohibited[language].map((item) => `- ${item}`).join("\n");
  if (language === "zh") {
    return [
      "## 运行时职责与工具合同（代码生成）",
      role.responsibility.zh,
      "",
      "禁区：",
      prohibited,
      "",
      `只允许调用：${role.requiredTools.join(", ")}。`,
      "以运行时 JSON Schema 为唯一输出字段与约束来源，不使用手写 JSON 示例。",
      "检查 as-of 时间有效性、变化/预期差、证据冲突与 A 股传导。不得输出空壳、模糊空数组、跨角色结论或无证据百分比。",
      "structured_conclusion 回显观测数值时必须带 series_id 或 evidence_id，且数值必须与固定快照完全一致。",
      "direction=NEUTRAL 时 strength 必须为 0；否则 strength 必须为 1–5。claims、claim_refs、key_drivers、channels 均不得为空。",
    ].join("\n");
  }
  return [
    "## Runtime role and tool contract (generated from code)",
    role.responsibility.en,
    "",
    "Prohibited:",
    prohibited,
    "",
    `Only call: ${role.requiredTools.join(", ")}.`,
    "Treat the runtime JSON Schema as the sole output-field contract; do not use hand-written JSON examples.",
    "Check as-of validity, changes versus expectations, evidence conflicts, and A-share transmission. Reject hollow answers, vague empty arrays, cross-role conclusions, and unsupported percentages.",
    "Any observed number echoed in structured_conclusion must carry its series_id or evidence_id and exactly match the fixed snapshot.",
    "direction=NEUTRAL requires strength=0; otherwise strength must be 1–5. claims, claim_refs, key_drivers, and channels must all be non-empty.",
  ].join("\n");
}

export function renderMacroPromptBody(
  agent: MacroAgentId,
  language: "zh" | "en",
  cohort: MacroPromptCohortId,
): string {
  const lens = MACRO_COHORT_LENSES[cohort][language];
  const acceptsEvents = agent === "china" || agent === "geopolitical";
  if (language === "zh") {
    return [
      `# ${agent} — 第一层宏观传导`,
      "",
      renderMacroRuntimeContract(agent, "zh"),
      "",
      "## 情景压力测试视角",
      lens,
      "该视角不是先验或结论，不得改变职责、工具、输出模式（schema）、PIT 门槛或固定快照语义；仅使用本角色允许的快照证据，当前证据冲突时以当前证据为准。",
      "",
      "## 分析流程",
      "1. 必须调用唯一允许的角色快照；工具失败、PIT 状态无效或覆盖不足时拒绝该阶段，不得改写为中性市场。",
      "2. 逐项检查 `released_at`、`vintage_at` 与 `as_of`；比较实际值、前值、预期差和变化，明确冲突证据。",
      "3. 只解释本角色负责的传导渠道，并落到 A 股风险溢价、盈利、流动性或行业敏感度。",
      "4. 结论必须由非空 `claims`、结论级 `claim_refs`、`key_drivers`、`channels` 与 `confidence` 支持。",
      "",
      acceptsEvents
        ? "Tushare `major_news` 与官方政策文件只能作为去重、发布时间过滤后的事件证据，不得形成独立新闻情绪票。"
        : "不得读取 `major_news` 或推断新闻情绪；新闻事件证据只属于 `china` 与 `geopolitical`。",
      "不得调用 OpenCLI、Google/财新搜索或实时雪球关注数。不得虚构来源、数值、百分比、时间戳或快照字段。",
      "旧 `emerging_markets` 与 `news_sentiment` 输出仅供审计，状态为 `legacy_unverified`，不能作为当前证据或 Darwinian 先验。",
      "",
    ].join("\n");
  }
  return [
    `# ${agent} — Layer-1 macro transmission`,
    "",
    renderMacroRuntimeContract(agent, "en"),
    "",
    "## Cohort stress-test lens",
    lens,
    "This lens is neither a prior nor a conclusion. It cannot change the role, tool, schema, PIT gate, or fixed-snapshot semantics; use only this role's allowed snapshot evidence, and let current evidence override the lens when they conflict.",
    "",
    "## Analysis workflow",
    "1. Call the one allowed role snapshot. Reject the stage when the tool fails, PIT validity fails, or required coverage is insufficient; never turn missing data into a neutral market.",
    "2. Check `released_at`, `vintage_at`, and `as_of`; compare actual, previous, expectation surprise, and changes, and expose conflicting evidence.",
    "3. Explain only this role's transmission into A-share risk premia, earnings, liquidity, or sector sensitivity.",
    "4. Support the conclusion with non-empty `claims`, conclusion-level `claim_refs`, `key_drivers`, `channels`, and `confidence`.",
    "",
    acceptsEvents
      ? "Tushare `major_news` and official policy documents are deduplicated, timestamp-filtered event evidence only; never cast a separate news-sentiment vote."
      : "Do not read `major_news` or infer news sentiment; news-event evidence belongs only to `china` and `geopolitical`.",
    "Never call OpenCLI, Google/Caixin search, or real-time Xueqiu follower counts. Never invent sources, values, percentages, timestamps, or snapshot fields.",
    "Legacy `emerging_markets` and `news_sentiment` outputs are audit-only `legacy_unverified` records and provide no current evidence or Darwinian prior.",
    "",
  ].join("\n");
}
