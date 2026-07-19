import { createHash } from "node:crypto";
import { z } from "zod";
import type { ComponentWeightRuntimeResolution } from "../../autoresearch/production_variant.js";
import { ClaimSchemaV2 } from "../evidence_contract.js";
import { renderCohortBehavior } from "../prompts/cohort_behavior.js";
import { assertPublicBundledCohort } from "../prompts/public_prompt_cohort.js";
import type {
  AcceptedMacroTransmission,
  MacroAgentId,
  MacroAgentSubmission,
  MacroComponentCompositionAudit,
  MacroComponentSignal,
  MacroDirection,
  MacroPersistenceHorizon,
} from "../types.js";

export interface MacroRoleContract {
  agentId: MacroAgentId;
  mode: "DIRECT" | "COMPONENTS";
  responsibility: { zh: string; en: string };
  prohibited: { zh: ReadonlyArray<string>; en: ReadonlyArray<string> };
  requiredTools: readonly [string];
  components: Readonly<Record<string, number>>;
}

export const MACRO_AGENT_IDS = [
  "china",
  "us_economy",
  "eu_economy",
  "central_bank",
  "us_financial_conditions",
  "euro_area_financial_conditions",
  "commodities",
  "geopolitical",
  "market_breadth",
  "institutional_flow",
] as const satisfies ReadonlyArray<MacroAgentId>;

export const TOMBSTONED_MACRO_AGENT_IDS = [
  "dollar",
  "yield_curve",
  "volatility",
  "emerging_markets",
  "news_sentiment",
] as const;

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

export const DEFAULT_MACRO_COHORT_LENS: Readonly<{ zh: string; en: string }> = {
  zh: "不预设市场状态，只依据本次 PIT 快照判断。",
  en: "Assume no market regime; judge only from this PIT snapshot.",
};

const equalWeights = (...components: string[]): Readonly<Record<string, number>> =>
  Object.freeze(
    Object.fromEntries(components.map((component) => [component, 1 / components.length])),
  );

export const MACRO_ROLE_CONTRACTS: Readonly<Record<MacroAgentId, MacroRoleContract>> = {
  china: {
    agentId: "china",
    mode: "COMPONENTS",
    responsibility: {
      zh: "判断中国增长、价格、信用、外需和财政脉冲对 A 股的传导。",
      en: "Assess how Chinese growth, prices, credit, external demand, and fiscal impulse transmit to A-shares.",
    },
    prohibited: {
      zh: ["不得把地产作为必选维度", "不得判断 PBOC 方向"],
      en: ["Do not require property in every analysis", "Do not infer a PBOC direction"],
    },
    requiredTools: ["get_china_macro_snapshot"],
    components: equalWeights(
      "growth_production",
      "prices",
      "credit",
      "external_demand_trade",
      "fiscal",
    ),
  },
  us_economy: {
    agentId: "us_economy",
    mode: "COMPONENTS",
    responsibility: {
      zh: "判断美国实体经济周期对中国出口、盈利和风险偏好的外部传导。",
      en: "Assess how the US real-economy cycle transmits to Chinese exports, earnings, and risk appetite.",
    },
    prohibited: {
      zh: ["不得判断 Fed、美元、收益率曲线或信用条件"],
      en: ["Do not judge the Fed, dollar, yield curve, or credit conditions"],
    },
    requiredTools: ["get_us_macro_snapshot"],
    components: equalWeights("growth_production", "prices", "employment", "demand_trade"),
  },
  eu_economy: {
    agentId: "eu_economy",
    mode: "COMPONENTS",
    responsibility: {
      zh: "判断欧盟实体经济周期对 A 股的外部传导。",
      en: "Assess how the EU real-economy cycle transmits to A-shares.",
    },
    prohibited: {
      zh: ["不得判断 ECB、汇率、曲线或金融压力", "不得纳入英国、瑞士或挪威"],
      en: [
        "Do not judge the ECB, FX, curves, or financial stress",
        "Do not include the UK, Switzerland, or Norway",
      ],
    },
    requiredTools: ["get_eu_macro_snapshot"],
    components: equalWeights("growth_production", "prices", "employment", "demand_trade"),
  },
  central_bank: {
    agentId: "central_bank",
    mode: "COMPONENTS",
    responsibility: {
      zh: "判断 PBOC 反应函数、流动性、中国货币市场、名义曲线和信用条件对 A 股的传导。",
      en: "Assess how the PBOC reaction function, liquidity, Chinese money markets, nominal curve, and credit conditions transmit to A-shares.",
    },
    prohibited: {
      zh: [
        "不得判断海外央行",
        "不得重复中国经济周期",
        "不得读取其他 Macro LLM 输出",
        "无注册数据时不得声称中国实际曲线",
      ],
      en: [
        "Do not judge foreign central banks",
        "Do not recast the China cycle",
        "Do not read other Macro LLM outputs",
        "Do not claim a Chinese real curve without registered data",
      ],
    },
    requiredTools: ["get_central_bank_snapshot"],
    components: equalWeights(
      "pboc_policy_bias",
      "liquidity_money_market",
      "china_curve",
      "credit_conditions",
    ),
  },
  us_financial_conditions: {
    agentId: "us_financial_conditions",
    mode: "COMPONENTS",
    responsibility: {
      zh: "统一判断 Fed、美国曲线、信用/金融压力和美元/人民币对 A 股的外部金融冲击。",
      en: "Jointly assess the A-share external financial shock from the Fed, US curves, credit/financial stress, and USD/RMB.",
    },
    prohibited: {
      zh: [
        "美国实体经济摘要仅作 CONTEXT_ONLY 背景，不得成为第五个组件、不得替代任何金融组件证据，也不得再投一张美国经济周期票",
        "不得读取 us_economy 的 LLM 输出",
        "不得把 Fed、美元、曲线拆成多票",
      ],
      en: [
        "The deterministic US real-economy summary is CONTEXT_ONLY: it is not a fifth component, cannot replace evidence for any financial component, and cannot cast another US-cycle vote",
        "Do not read the us_economy LLM output",
        "Do not split the Fed, dollar, and curve into separate votes",
      ],
    },
    requiredTools: ["get_us_financial_conditions_snapshot"],
    components: equalWeights("fed_liquidity", "us_curve", "credit_financial_stress", "usd_rmb"),
  },
  euro_area_financial_conditions: {
    agentId: "euro_area_financial_conditions",
    mode: "COMPONENTS",
    responsibility: {
      zh: "统一判断 ECB、欧元区曲线、银行信用和欧元/金融压力对 A 股的外部冲击。",
      en: "Jointly assess the A-share external shock from the ECB, euro-area curves, bank credit, and EUR/financial stress.",
    },
    prohibited: {
      zh: [
        "欧盟实体经济摘要仅作 CONTEXT_ONLY 背景，不得成为第五个组件、不得替代任何金融组件证据，也不得重复欧盟实体周期",
        "不得读取 eu_economy 的 LLM 输出",
        "不得纳入非欧元区央行或市场",
      ],
      en: [
        "The deterministic EU real-economy summary is CONTEXT_ONLY: it is not a fifth component, cannot replace evidence for any financial component, and cannot repeat the EU real-economy cycle",
        "Do not read the eu_economy LLM output",
        "Do not include non-euro-area central banks or markets",
      ],
    },
    requiredTools: ["get_euro_area_financial_conditions_snapshot"],
    components: equalWeights(
      "ecb_liquidity",
      "euro_area_curve",
      "bank_credit",
      "eur_financial_stress",
    ),
  },
  commodities: {
    agentId: "commodities",
    mode: "COMPONENTS",
    responsibility: {
      zh: "判断能源、工业金属、黄金和农产品/食品的输入性冲击。",
      en: "Assess input shocks from energy, industrial metals, gold, and agriculture/food.",
    },
    prohibited: {
      zh: ["无真实期限结构数据时不得声称 contango 或 backwardation"],
      en: ["Do not claim contango or backwardation without actual term-structure data"],
    },
    requiredTools: ["get_commodity_conditions_snapshot"],
    components: equalWeights("energy", "industrial_metals", "gold", "agriculture_food"),
  },
  geopolitical: {
    agentId: "geopolitical",
    mode: "DIRECT",
    responsibility: {
      zh: "判断已注册地缘事件的状态、传导渠道、严重度、期限和观察触发器。",
      en: "Assess registered geopolitical event state, channels, severity, horizon, and monitoring triggers.",
    },
    prohibited: {
      zh: ["不得虚构价格影响百分比", "财经日历不得替代事件状态证据"],
      en: [
        "Do not invent percentage price impacts",
        "Do not use an economic calendar as event-state evidence",
      ],
    },
    requiredTools: ["get_geopolitical_events_snapshot"],
    components: {},
  },
  market_breadth: {
    agentId: "market_breadth",
    mode: "DIRECT",
    responsibility: {
      zh: "解释 A 股参与度、趋势广度、成交广度、新高新低和集中度。",
      en: "Interpret A-share participation, trend breadth, turnover breadth, new highs/lows, and concentration.",
    },
    prohibited: {
      zh: ["不得读取新闻、财经日历、资金流或波动率", "不得自行重算快照指标"],
      en: [
        "Do not read news, calendars, flows, or volatility",
        "Do not recompute snapshot metrics",
      ],
    },
    requiredTools: ["get_market_breadth_snapshot"],
    components: {},
  },
  institutional_flow: {
    agentId: "institutional_flow",
    mode: "DIRECT",
    responsibility: {
      zh: "判断全市场资金、行业轮动、ETF 份额和拥挤度。",
      en: "Assess market-wide flows, sector rotation, ETF shares, and crowding.",
    },
    prohibited: {
      zh: ["不得读取财经日历", "龙虎榜只能作为辅助", "不得以抽样个股代表全市场"],
      en: [
        "Do not read the economic calendar",
        "Use Dragon-Tiger data only as supporting evidence",
        "Do not represent the market with sampled stocks",
      ],
    },
    requiredTools: ["get_market_positioning_snapshot"],
    components: {},
  },
};

const ActiveStrengthSchema = z.union([
  z.literal(1),
  z.literal(2),
  z.literal(3),
  z.literal(4),
  z.literal(5),
]);

const MacroNarrativeTextSchema = (maxLength: number) =>
  z
    .string()
    .trim()
    .min(1)
    .max(maxLength)
    .regex(
      /^[^0-9０-９%％]*$/u,
      "numeric literals belong only in the structured snapshot echo fields",
    );

const signalTailFields = {
  persistence_horizon: z.enum(["DAYS", "WEEKS", "MONTHS"]),
  evaluation_horizon_trading_days: z.literal(5),
  confidence: z.number().min(0).max(1),
  channels: z.array(MacroNarrativeTextSchema(160)).min(1).max(8),
  claim_refs: z.array(z.string().trim().min(1)).min(1),
};

const DirectMacroSignalSchema = z.union([
  z
    .object({ direction: z.literal("NEUTRAL"), strength: z.literal(0), ...signalTailFields })
    .strict(),
  z
    .object({
      direction: z.enum(["SUPPORTIVE", "ADVERSE"]),
      strength: ActiveStrengthSchema,
      ...signalTailFields,
    })
    .strict(),
]);
const MacroComponentSignalSchema = z.union([
  z
    .object({
      component: z.string().trim().min(1),
      direction: z.literal("NEUTRAL"),
      strength: z.literal(0),
      ...signalTailFields,
    })
    .strict(),
  z
    .object({
      component: z.string().trim().min(1),
      direction: z.enum(["SUPPORTIVE", "ADVERSE"]),
      strength: ActiveStrengthSchema,
      ...signalTailFields,
    })
    .strict(),
]);

function exactMacroComponentSignalSchema(component: string) {
  return z.union([
    z
      .object({
        component: z.literal(component),
        direction: z.literal("NEUTRAL"),
        strength: z.literal(0),
        ...signalTailFields,
      })
      .strict(),
    z
      .object({
        component: z.literal(component),
        direction: z.enum(["SUPPORTIVE", "ADVERSE"]),
        strength: ActiveStrengthSchema,
        ...signalTailFields,
      })
      .strict(),
  ]);
}

const MacroClaimSchema = ClaimSchemaV2.safeExtend({
  statement: MacroNarrativeTextSchema(320),
  structured_conclusion: z
    .object({
      conclusion_type: z.enum(["MACRO_FACT", "MACRO_EVENT", "MACRO_INTERPRETATION", "MACRO_RISK"]),
      subject: MacroNarrativeTextSchema(128),
      state: MacroNarrativeTextSchema(256),
      a_share_transmission: MacroNarrativeTextSchema(320),
      snapshot_echo_id: z.string().trim().min(1).max(256).nullable(),
      snapshot_metric: z.string().trim().min(1).max(96).nullable(),
      snapshot_value: z.number().finite().nullable(),
    })
    .strict()
    .superRefine((conclusion, ctx) => {
      const echoFields = [
        conclusion.snapshot_echo_id,
        conclusion.snapshot_metric,
        conclusion.snapshot_value,
      ];
      const populated = echoFields.filter((value) => value !== null).length;
      if (populated !== 0 && populated !== echoFields.length) {
        ctx.addIssue({
          code: "custom",
          path: ["snapshot_echo_id"],
          message:
            "snapshot_echo_id, snapshot_metric, and snapshot_value must be all null or all populated",
        });
      }
    }),
});

export const DIRECT_MACRO_SUBMISSION_FIELD_NAMES = [
  "mode",
  "claims",
  "key_drivers",
  "signal",
] as const;

export const COMPONENT_MACRO_SUBMISSION_FIELD_NAMES = [
  "mode",
  "claims",
  "key_drivers",
  "components",
] as const;

export function macroSubmissionFieldNames(agent: MacroAgentId): ReadonlyArray<string> {
  return MACRO_ROLE_CONTRACTS[agent].mode === "DIRECT"
    ? DIRECT_MACRO_SUBMISSION_FIELD_NAMES
    : COMPONENT_MACRO_SUBMISSION_FIELD_NAMES;
}

export function createMacroSubmissionSchema(agent: MacroAgentId): z.ZodType<MacroAgentSubmission> {
  const contract = MACRO_ROLE_CONTRACTS[agent];
  const expectedComponents = Object.keys(contract.components).sort();
  const exactComponents =
    expectedComponents.length > 0
      ? (z
          .array(
            z.union(
              expectedComponents.map(exactMacroComponentSignalSchema) as [
                ReturnType<typeof exactMacroComponentSignalSchema>,
                ReturnType<typeof exactMacroComponentSignalSchema>,
                ...Array<ReturnType<typeof exactMacroComponentSignalSchema>>,
              ],
            ),
          )
          .length(expectedComponents.length) as unknown as z.ZodType<
          z.infer<typeof MacroComponentSignalSchema>[]
        >)
      : z.tuple([]);
  const common = {
    claims: z.array(MacroClaimSchema).min(1).max(8),
    key_drivers: z.array(MacroNarrativeTextSchema(256)).min(1).max(8),
  };
  const schema =
    contract.mode === "DIRECT"
      ? z.object({ mode: z.literal("DIRECT"), ...common, signal: DirectMacroSignalSchema }).strict()
      : z
          .object({
            mode: z.literal("COMPONENTS"),
            ...common,
            components: exactComponents,
          })
          .strict();
  return schema.superRefine((submission, ctx) => {
    const claimIds = new Set(submission.claims.map((claim) => claim.claim_id));
    const refs =
      submission.mode === "DIRECT"
        ? submission.signal.claim_refs
        : submission.components.flatMap((component) => component.claim_refs);
    for (const ref of refs) {
      if (!claimIds.has(ref)) {
        ctx.addIssue({
          code: "custom",
          path: ["claim_refs"],
          message: `unknown claim_ref: ${ref}`,
        });
      }
    }
    if (submission.mode === "COMPONENTS") {
      const expected = expectedComponents;
      const actual = submission.components.map((component) => component.component).sort();
      if (actual.length !== new Set(actual).size || actual.join("\0") !== expected.join("\0")) {
        ctx.addIssue({
          code: "custom",
          path: ["components"],
          message: `components must equal ${expected.join(", ")} exactly once`,
        });
      }
    }
  }) as z.ZodType<MacroAgentSubmission>;
}

export const MACRO_AGENT_CONTRACT_VERSION = "macro_agent_contract_v2";
export const MACRO_PROMPT_BEHAVIOR_VERSION = "macro_prompt_behavior_v2";
export const MACRO_EXECUTION_BEHAVIOR_VERSION = "macro_execution_behavior_v2";
export const MACRO_COMPONENT_WEIGHT_CONTRACT_VERSION = "macro_component_weights_v2";

export type MacroDataQualityInput =
  | { mode: "DIRECT"; dataQuality: number }
  | { mode: "COMPONENTS"; dataQualityByComponent: Readonly<Record<string, number>> };

export interface MacroAcceptedBehaviorBinding {
  agent_contract_version: string;
  prompt_behavior_version: string;
  execution_behavior_version: string;
  component_weight_contract_version: string | null;
}

export function composeAcceptedMacroTransmission(
  agent: MacroAgentId,
  submissionInput: unknown,
  quality: MacroDataQualityInput,
  behavior: MacroAcceptedBehaviorBinding = {
    agent_contract_version: MACRO_AGENT_CONTRACT_VERSION,
    prompt_behavior_version: MACRO_PROMPT_BEHAVIOR_VERSION,
    execution_behavior_version: MACRO_EXECUTION_BEHAVIOR_VERSION,
    component_weight_contract_version:
      MACRO_ROLE_CONTRACTS[agent].mode === "COMPONENTS"
        ? MACRO_COMPONENT_WEIGHT_CONTRACT_VERSION
        : null,
  },
  activeComponentWeights?: ComponentWeightRuntimeResolution,
): AcceptedMacroTransmission {
  const submission = createMacroSubmissionSchema(agent).parse(submissionInput);
  const contract = MACRO_ROLE_CONTRACTS[agent];
  if (submission.mode !== contract.mode || quality.mode !== contract.mode) {
    throw new Error(`${agent}: submission/data-quality mode does not match role contract`);
  }
  const expectedComponentVersion =
    contract.mode === "COMPONENTS"
      ? (activeComponentWeights?.component_weight_contract_version ??
        MACRO_COMPONENT_WEIGHT_CONTRACT_VERSION)
      : null;
  if (
    !behavior.agent_contract_version ||
    !behavior.prompt_behavior_version ||
    !behavior.execution_behavior_version ||
    behavior.component_weight_contract_version !== expectedComponentVersion
  ) {
    throw new Error(`${agent}: invalid accepted behavior binding`);
  }
  if (submission.mode === "DIRECT" && quality.mode === "DIRECT") {
    const dataQuality = qualityValue(quality.dataQuality, `${agent}:direct`);
    return {
      agent_id: agent,
      ...behavior,
      direction: submission.signal.direction,
      strength: submission.signal.strength,
      persistence_horizon: submission.signal.persistence_horizon,
      evaluation_horizon_trading_days: 5,
      model_confidence: submission.signal.confidence,
      deterministic_data_quality: dataQuality,
      confidence: clamp(submission.signal.confidence * dataQuality),
      channels: [...new Set(submission.signal.channels)],
      claims: submission.claims,
      claim_refs: [...new Set(submission.signal.claim_refs)],
      key_drivers: submission.key_drivers,
    };
  }
  if (submission.mode !== "COMPONENTS" || quality.mode !== "COMPONENTS") {
    throw new Error(`${agent}: invalid component composition mode`);
  }
  const components = submission.components;
  if (activeComponentWeights && activeComponentWeights.agent_id !== agent) {
    throw new Error(`${agent}: component weight resolution owner mismatch`);
  }
  const resolvedWeights = activeComponentWeights?.component_weights ?? contract.components;
  if (
    Object.keys(resolvedWeights).sort().join("\0") !==
      Object.keys(contract.components).sort().join("\0") ||
    !Object.values(resolvedWeights).every((weight) => Number.isFinite(weight) && weight > 0) ||
    Math.abs(sum(Object.values(resolvedWeights)) - 1) > 1e-12
  ) {
    throw new Error(`${agent}: invalid active component weights`);
  }
  const weighted = components.map((component) => {
    const preregisteredWeight = resolvedWeights[component.component];
    if (preregisteredWeight === undefined) throw new Error(`${agent}: unknown component`);
    const dataQuality = qualityValue(
      quality.dataQualityByComponent[component.component],
      `${agent}:${component.component}`,
    );
    const x = directionSign(component.direction) * (component.strength / 5);
    return {
      component,
      preregisteredWeight,
      dataQuality,
      x,
      b: preregisteredWeight * component.confidence * dataQuality,
      modelB: preregisteredWeight * component.confidence,
    };
  });
  const bSum = sum(weighted.map((item) => item.b));
  const modelBSum = sum(weighted.map((item) => item.modelB));
  if (bSum <= 0 || modelBSum <= 0) throw new Error(`${agent}: zero effective component weight`);
  const f = sum(weighted.map((item) => item.b * item.x)) / bSum;
  const modelF = sum(weighted.map((item) => item.modelB * item.x)) / modelBSum;
  const dispersion = sum(weighted.map((item) => item.b * Math.abs(item.x - f))) / bSum;
  const modelDispersion =
    sum(weighted.map((item) => item.modelB * Math.abs(item.x - modelF))) / modelBSum;
  const baseConfidence = sum(
    weighted.map((item) => item.preregisteredWeight * item.component.confidence * item.dataQuality),
  );
  const modelConfidence = clamp(
    sum(weighted.map((item) => item.preregisteredWeight * item.component.confidence)) *
      (1 - modelDispersion),
  );
  return {
    agent_id: agent,
    ...behavior,
    ...directionAndStrength(f),
    persistence_horizon: weightedHorizonMode(weighted),
    evaluation_horizon_trading_days: 5,
    model_confidence: modelConfidence,
    deterministic_data_quality: clamp(
      sum(weighted.map((item) => item.preregisteredWeight * item.dataQuality)),
    ),
    confidence: clamp(baseConfidence * (1 - dispersion)),
    channels: [...new Set(components.flatMap((component) => component.channels))],
    claims: submission.claims,
    claim_refs: [...new Set(components.flatMap((component) => component.claim_refs))],
    key_drivers: submission.key_drivers,
  };
}

export function buildMacroComponentCompositionAudit(
  agent: MacroAgentId,
  submissionInput: unknown,
  quality: MacroDataQualityInput,
  accepted: AcceptedMacroTransmission,
  sourceBinding: {
    sourceSnapshotHash: string;
    contextOnlyProjectionHash: string | null;
  },
  activeComponentWeights?: ComponentWeightRuntimeResolution,
): MacroComponentCompositionAudit {
  const submission = createMacroSubmissionSchema(agent).parse(submissionInput);
  const contract = MACRO_ROLE_CONTRACTS[agent];
  if (
    contract.mode !== "COMPONENTS" ||
    submission.mode !== "COMPONENTS" ||
    quality.mode !== "COMPONENTS"
  ) {
    throw new Error(`${agent}: component composition audit requires component mode`);
  }
  if (accepted.agent_id !== agent) {
    throw new Error(`${agent}: component composition audit accepted owner mismatch`);
  }
  if (activeComponentWeights && activeComponentWeights.agent_id !== agent) {
    throw new Error(`${agent}: component weight resolution owner mismatch`);
  }
  const isFinancialContextRole =
    agent === "us_financial_conditions" || agent === "euro_area_financial_conditions";
  if (
    !/^sha256:[0-9a-f]{64}$/.test(sourceBinding.sourceSnapshotHash) ||
    (isFinancialContextRole &&
      !/^sha256:[0-9a-f]{64}$/.test(sourceBinding.contextOnlyProjectionHash ?? "")) ||
    (!isFinancialContextRole && sourceBinding.contextOnlyProjectionHash !== null)
  ) {
    throw new Error(`${agent}: invalid source snapshot/context projection binding`);
  }
  const componentWeights = activeComponentWeights?.component_weights ?? contract.components;
  const componentVersion =
    activeComponentWeights?.component_weight_contract_version ??
    MACRO_COMPONENT_WEIGHT_CONTRACT_VERSION;
  if (
    accepted.component_weight_contract_version !== componentVersion ||
    Object.keys(componentWeights).sort().join("\0") !==
      Object.keys(contract.components).sort().join("\0") ||
    !Object.values(componentWeights).every((weight) => Number.isFinite(weight) && weight > 0) ||
    Math.abs(sum(Object.values(componentWeights)) - 1) > 1e-12
  ) {
    throw new Error(`${agent}: invalid component composition audit binding`);
  }
  const body = {
    schema_version: "macro_component_composition_audit_v1" as const,
    agent_id: agent,
    component_weight_contract_version: componentVersion,
    component_weights: Object.fromEntries(
      Object.entries(componentWeights).sort(([left], [right]) => left.localeCompare(right)),
    ),
    source_snapshot_hash: sourceBinding.sourceSnapshotHash,
    context_only_projection_hash: sourceBinding.contextOnlyProjectionHash,
    components: submission.components
      .map((component) => ({
        ...component,
        channels: [...component.channels],
        claim_refs: [...component.claim_refs],
        deterministic_data_quality: qualityValue(
          quality.dataQualityByComponent[component.component],
          `${agent}:${component.component}`,
        ),
      }))
      .sort((left, right) => left.component.localeCompare(right.component)),
    composed_payload_hash: canonicalHash(accepted),
  };
  return {
    ...body,
    component_composition_hash: canonicalHash(body),
  };
}

function canonicalHash(value: unknown): string {
  return `sha256:${createHash("sha256")
    .update(JSON.stringify(canonicalize(value)))
    .digest("hex")}`;
}

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, nested]) => [key, canonicalize(nested)]),
    );
  }
  return value;
}

export function renderMacroRuntimeContract(agent: MacroAgentId, language: "zh" | "en"): string {
  const role = MACRO_ROLE_CONTRACTS[agent];
  const prohibited = role.prohibited[language].map((item) => `- ${item}`).join("\n");
  const components = Object.keys(role.components);
  if (language === "zh") {
    return [
      "## 运行时职责与工具合同（代码生成）",
      role.responsibility.zh,
      "",
      "禁区：",
      prohibited,
      "",
      `只允许调用：${role.requiredTools[0]}。`,
      `固定提交模式：${role.mode}。`,
      ...(components.length > 0 ? [`组件必须恰好为：${components.join("、")}。`] : []),
      "以运行时 JSON Schema 为唯一输出合同；不得输出 accepted lineage、权重或数据质量字段。",
      "检查 as-of、变化/预期差、证据冲突与 A 股传导；所有 claim 必须引用真实 evidence_id。",
    ].join("\n");
  }
  return [
    "## Runtime role and tool contract (generated)",
    role.responsibility.en,
    "",
    "Prohibited:",
    prohibited,
    "",
    `Only call: ${role.requiredTools[0]}.`,
    `Fixed submission mode: ${role.mode}.`,
    ...(components.length > 0 ? [`Components must be exactly: ${components.join(", ")}.`] : []),
    "Treat the runtime JSON Schema as the only output contract; do not emit accepted lineage, weights, or data-quality fields.",
    "Check as-of validity, changes/surprises, evidence conflicts, and A-share transmission; every claim must cite a real evidence_id.",
  ].join("\n");
}

export function renderMacroPromptBody(
  agent: MacroAgentId,
  language: "zh" | "en",
  cohort: MacroPromptCohortId,
): string {
  assertPublicBundledCohort(cohort);
  const role = MACRO_ROLE_CONTRACTS[agent];
  const lens = DEFAULT_MACRO_COHORT_LENS[language];
  const prohibited = role.prohibited[language].map((item) => `- ${item}`).join("\n");
  const components = Object.keys(role.components);
  if (language === "zh") {
    return [
      `# ${agent} 宏观研究角色`,
      "",
      "## 职责",
      role.responsibility.zh,
      "",
      "## 禁区",
      prohibited,
      "",
      "## 当前 cohort 观察镜头",
      renderCohortBehavior(lens),
      "",
      "## 分析要求",
      `必须调用且只能调用 ${role.requiredTools[0]}，严格使用 as-of 可见数据。`,
      "检查变化、预期差、证据冲突和对 A 股的传导。",
      `按运行时 schema 提交 mode=${role.mode}。`,
      ...(components.length > 0 ? [`components 必须恰好为：${components.join("、")}。`] : []),
      "不得生成跨 Agent 综合结论；只提交本角色的模型输出。",
      "",
    ].join("\n");
  }
  return [
    `# ${agent} macro research role`,
    "",
    "## Responsibility",
    role.responsibility.en,
    "",
    "## Prohibited",
    prohibited,
    "",
    "## Cohort lens",
    renderCohortBehavior(lens),
    "",
    "## Analysis requirements",
    `Call ${role.requiredTools[0]} and no other tool; use only as-of-visible data.`,
    "Check changes, surprises, evidence conflicts, and A-share transmission.",
    `Submit mode=${role.mode} under the runtime schema.`,
    ...(components.length > 0 ? [`components must be exactly: ${components.join(", ")}.`] : []),
    "Do not produce a cross-agent conclusion; submit only this role's model output.",
    "",
  ].join("\n");
}

function qualityValue(value: number | undefined, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > 1) {
    throw new Error(`${label}: deterministic data quality must be in [0,1]`);
  }
  return value;
}

function directionSign(direction: MacroDirection): -1 | 0 | 1 {
  return direction === "SUPPORTIVE" ? 1 : direction === "ADVERSE" ? -1 : 0;
}

function directionAndStrength(score: number): {
  direction: MacroDirection;
  strength: 0 | 1 | 2 | 3 | 4 | 5;
} {
  if (Math.abs(score) < 0.1) return { direction: "NEUTRAL", strength: 0 };
  const strength = Math.max(1, Math.min(5, Math.floor(5 * Math.abs(score) + 0.5))) as
    | 1
    | 2
    | 3
    | 4
    | 5;
  return { direction: score > 0 ? "SUPPORTIVE" : "ADVERSE", strength };
}

const HORIZON_ORDER: Readonly<Record<MacroPersistenceHorizon, number>> = {
  DAYS: 0,
  WEEKS: 1,
  MONTHS: 2,
};

function weightedHorizonMode(
  weighted: ReadonlyArray<{
    component: MacroComponentSignal;
    b: number;
  }>,
): MacroPersistenceHorizon {
  const totals: Record<MacroPersistenceHorizon, number> = { DAYS: 0, WEEKS: 0, MONTHS: 0 };
  for (const item of weighted) totals[item.component.persistence_horizon] += item.b;
  return (Object.keys(totals) as MacroPersistenceHorizon[]).sort(
    (left, right) => totals[right] - totals[left] || HORIZON_ORDER[left] - HORIZON_ORDER[right],
  )[0] as MacroPersistenceHorizon;
}

function clamp(value: number): number {
  return Math.max(0, Math.min(1, value));
}

function sum(values: ReadonlyArray<number>): number {
  return values.reduce((total, value) => total + value, 0);
}
