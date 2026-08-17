import { z } from "zod";
import type { ComponentWeightRuntimeResolution } from "../../autoresearch/production_variant.js";
import { ClaimSchemaV2 } from "../evidence_contract.js";
import { canonicalJsonHash } from "../helpers/canonical_json.js";
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
  "institutional_flow",
] as const satisfies ReadonlyArray<MacroAgentId>;

export const TOMBSTONED_MACRO_AGENT_IDS = [
  "dollar",
  "yield_curve",
  "volatility",
  "emerging_markets",
  "news_sentiment",
  "geopolitical",
] as const;

export const MACRO_CONTEXT_SOURCE_ROLES = {
  central_bank: "china",
  us_financial_conditions: "us_economy",
  euro_area_financial_conditions: "eu_economy",
} as const satisfies Partial<Record<MacroAgentId, MacroAgentId>>;

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
  institutional_flow: {
    agentId: "institutional_flow",
    mode: "DIRECT",
    responsibility: {
      zh: "判断固定核心 ETF 份额增减：正值为申购，负值为赎回，并比较五只 ETF 的一致性与分化。",
      en: "Assess fixed core ETF share changes: positive means creation and negative means redemption; compare consistency and divergence across the five ETFs.",
    },
    prohibited: {
      zh: ["不得读取财经日历", "只使用固定核心 ETF 份额集合，不得扩展对象范围"],
      en: [
        "Do not read the economic calendar",
        "Use only the fixed core ETF share set; do not widen the object scope",
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

const EnglishNumericWordPattern =
  /\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|billion|trillion|decimal|percent|percentage|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth)\b/iu;
const ChineseNumericExpressionPattern =
  /(?:[零〇一二两三四五六七八九][零〇一二两三四五六七八九十百千万亿兆]+|十[零〇一二两三四五六七八九]|[零〇一二两三四五六七八九十百千万亿兆]+点[零〇一二两三四五六七八九十百千万亿兆]+|[零〇一二两三四五六七八九十百千万亿兆]+年期|(?:百分之|千分之|万分之)[零〇一二两三四五六七八九十百千万亿兆]+|第[零〇一二两三四五六七八九十百千万亿兆]+(?:期|阶段|轮|次)|[零〇一二两三四五六七八九十百千万亿兆]+(?:个百分点|个基点|基点|倍|成|季度|月份|交易日))/u;
const NarrativePlaceholderSet = new Set([
  "NEUTRAL",
  "SUPPORTIVE",
  "ADVERSE",
  "UNKNOWN",
  "N/A",
  "NA",
  "NONE",
  "NULL",
  "中性",
  "未知",
  "无",
]);

export function macroNarrativeIssue(
  value: string,
  maxLength: number,
): "NUMERIC_EXPRESSION" | "PLACEHOLDER" | "TRUNCATED" | null {
  if (EnglishNumericWordPattern.test(value) || ChineseNumericExpressionPattern.test(value)) {
    return "NUMERIC_EXPRESSION";
  }
  const normalized = value
    .trim()
    .replace(/[\s.,;:!?，。；：！？、]+/gu, "")
    .toUpperCase();
  if (NarrativePlaceholderSet.has(normalized)) return "PLACEHOLDER";
  if (
    /[,;:，；：]$/u.test(value) ||
    /\b(?:a|an|the|and|or|but|with|via|to|for|of|supporting)\s*$/iu.test(value) ||
    (value.length >= maxLength - 1 && !/[.!?。！？]$/u.test(value))
  ) {
    return "TRUNCATED";
  }
  return null;
}

const MacroNarrativeTextSchema = (maxLength: number) =>
  z
    .string()
    .trim()
    .min(1)
    .max(maxLength)
    .regex(
      /^[^0-9０-９%％]*$/u,
      "numeric literals belong only in the structured snapshot echo fields",
    )
    .superRefine((value, ctx) => {
      const issue = macroNarrativeIssue(value, maxLength);
      if (issue === "NUMERIC_EXPRESSION") {
        ctx.addIssue({
          code: "custom",
          message:
            "numeric facts must be omitted entirely; spelling a number in Chinese or English is forbidden",
        });
      } else if (issue === "PLACEHOLDER") {
        ctx.addIssue({
          code: "custom",
          message: "narrative fields require an actual state or transmission description",
        });
      } else if (issue === "TRUNCATED") {
        ctx.addIssue({
          code: "custom",
          message: "narrative text appears truncated or ends with a dangling fragment",
        });
      }
    });

const signalTailFields = {
  persistence_horizon: z.enum(["DAYS", "WEEKS", "MONTHS"]),
  evaluation_horizon_trading_days: z.literal(5),
  confidence: z.number().min(0).max(1),
  channels: z.array(MacroNarrativeTextSchema(96)).min(1).max(8),
  claim_refs: z.array(z.string().trim().min(1)).min(1).max(8),
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
  statement: MacroNarrativeTextSchema(160),
  structured_conclusion: z
    .object({
      conclusion_type: z.enum(["MACRO_FACT", "MACRO_EVENT", "MACRO_INTERPRETATION", "MACRO_RISK"]),
      subject: MacroNarrativeTextSchema(96),
      state: MacroNarrativeTextSchema(128),
      a_share_transmission: MacroNarrativeTextSchema(160),
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
    claims: z.array(MacroClaimSchema).min(Math.max(1, expectedComponents.length)).max(8),
    key_drivers: z.array(MacroNarrativeTextSchema(160)).min(1).max(8),
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
    const seenClaimIds = new Set<string>();
    submission.claims.forEach((claim, index) => {
      if (seenClaimIds.has(claim.claim_id)) {
        ctx.addIssue({
          code: "custom",
          path: ["claims", index, "claim_id"],
          message: `duplicate claim_id: ${claim.claim_id}`,
        });
      }
      seenClaimIds.add(claim.claim_id);
    });
    const claimIds = new Set(submission.claims.map((claim) => claim.claim_id));
    const refGroups =
      submission.mode === "DIRECT"
        ? [{ path: ["signal", "claim_refs"] as PropertyKey[], refs: submission.signal.claim_refs }]
        : submission.components.map((component, index) => ({
            path: ["components", index, "claim_refs"] as PropertyKey[],
            refs: component.claim_refs,
          }));
    for (const group of refGroups) {
      const seenRefs = new Set<string>();
      group.refs.forEach((ref, index) => {
        if (seenRefs.has(ref)) {
          ctx.addIssue({
            code: "custom",
            path: [...group.path, index],
            message: `duplicate claim_ref: ${ref}`,
          });
        }
        seenRefs.add(ref);
        if (!claimIds.has(ref)) {
          ctx.addIssue({
            code: "custom",
            path: [...group.path, index],
            message: `unknown claim_ref: ${ref}`,
          });
        }
      });
    }
    if (submission.mode === "COMPONENTS") {
      const claimById = new Map(submission.claims.map((claim) => [claim.claim_id, claim]));
      const usedComponentRefs = new Set<string>();
      submission.components.forEach((component, componentIndex) => {
        component.claim_refs.forEach((ref, refIndex) => {
          if (usedComponentRefs.has(ref)) {
            ctx.addIssue({
              code: "custom",
              path: ["components", componentIndex, "claim_refs", refIndex],
              message: `component claim_ref must be independently owned: ${ref}`,
            });
          }
          usedComponentRefs.add(ref);
          const claim = claimById.get(ref);
          if (claim && claim.structured_conclusion.subject !== component.component) {
            ctx.addIssue({
              code: "custom",
              path: ["components", componentIndex, "claim_refs", refIndex],
              message: `claim_ref ${ref} subject must equal component ${component.component}`,
            });
          }
        });
      });
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
  const requiresContextProjection = agent in MACRO_CONTEXT_SOURCE_ROLES;
  if (
    !/^sha256:[0-9a-f]{64}$/.test(sourceBinding.sourceSnapshotHash) ||
    (requiresContextProjection &&
      !/^sha256:[0-9a-f]{64}$/.test(sourceBinding.contextOnlyProjectionHash ?? "")) ||
    (!requiresContextProjection && sourceBinding.contextOnlyProjectionHash !== null)
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
  return canonicalJsonHash(value);
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
  const chinaBoundary =
    agent === "china"
      ? language === "zh"
        ? [
            "get_china_macro_snapshot 是 PIT observations/releases，不是 A 股信号。只根据 actual、expected、previous 及 release/vintage/as-of 建立变化与 surprise；数值事实只能写入结构化 snapshot echo 字段，不得写入叙述。经济职责必须按精确组件执行：growth_production 将 production、investment、retail、employment 与 GDP demand 传导到 broad earnings/cyclical beta；prices 将 CPI/PPI 传导到 nominal revenue、pricing power 与 margins，不得推断 PBOC direction；credit 将 TSF、loans 与 money impulse 传导到 financing、domestic demand 与 risk appetite，不得判断 central-bank reaction；external_demand_trade 将 exports、imports 与 trade balance 传导到 exporters、supply chains 与 earnings；fiscal 将 revenue/spending impulse 传导到 infrastructure 与 domestic demand。Property 仅在实际已注册 evidence 存在且相关时可选，绝非必需。每个组件必须使用精确 subject id，并分别拥有不与其他组件共享的真实 evidence；冲突必须降低 confidence/strength。若证据不能支持全部五个精确组件，按现有 stage contract 拒绝，不得伪造 neutral。Accepted claims 必须引用实际 get_china_macro_snapshot result event 的真实 evidence_id。当前证据不是已实现的 5D 结果。Autoresearch 只能依据独立的 event-triggered、T+1 open 后 5 个交易日、按 PIT volatility 归一化的 A-share role-path outcome，演进 prompt/tool interpretation 与半年一次的 component weights。fallback=false 表示缺失证据必须拒绝。不得生成跨 Agent 结论，也不得判断 PBOC reaction function。",
          ]
        : [
            "get_china_macro_snapshot contains PIT observations and releases, not an A-share signal. Establish change and surprise only from actual, expected, and previous values with release, vintage, and as-of context; numeric facts belong only in structured snapshot echo fields, never in narrative. Apply exact component duties: growth_production transmits production, investment, retail, employment, and GDP demand into broad earnings and cyclical beta; prices transmits CPI/PPI into nominal revenue, pricing power, and margins without inferring PBOC direction; credit transmits TSF, loans, and money impulse into financing, domestic demand, and risk appetite, not central-bank reaction; external_demand_trade transmits exports, imports, and the trade balance into exporters, supply chains, and earnings; fiscal transmits the revenue/spending impulse into infrastructure and domestic demand. Property is optional only when actual registered evidence exists and is relevant; it is never mandatory. Every component must use its exact subject id and independently own real evidence not shared with another component; conflicts must lower confidence/strength. If evidence cannot support all five exact components, reject under the existing stage contract instead of fabricating a neutral. Accepted claims must cite real evidence_id values from the actual get_china_macro_snapshot result event. Current evidence is not the realized 5D result. Autoresearch may evolve prompt/tool interpretation and semiannual component weights only against the independent event-triggered A-share role-path outcome over 5 trading days after T+1 open, normalized by PIT volatility. fallback=false means missing evidence must be rejected. Do not produce cross-Agent conclusions or judge the PBOC reaction function.",
          ]
      : [];
  const usEconomyBoundary =
    agent === "us_economy"
      ? language === "zh"
        ? [
            "get_us_macro_snapshot 包含 PIT ALFRED real-economy observations，不是 A 股信号。仅在字段存在时使用 actual、previous、expected 与 release/vintage/as-of；不得虚构缺失的 consensus 或 surprise，数值事实只能写入结构化 snapshot echo 字段。经济职责必须按精确组件执行：growth_production 将 real GDP 与 industrial production 经 US activity/import demand 传导到 China exporters、industrial earnings 与 cyclical A-share beta；prices 将 CPI、core CPI、PCE 与 core PCE 经 US inflation 与 real purchasing power 传导到 external demand 与 Chinese exporter margins，但不得推断 Fed、USD、yield curve 或 credit conditions；employment 将 payrolls 与 unemployment 经 household income/consumption 传导到 China export orders 与 risk appetite；demand_trade 将 retail sales 与 trade balance 经 US final demand/import absorption 传导到 Chinese exporters 与 supply chains。每个组件必须使用精确 subject id，并分别拥有不与其他组件共享的真实 evidence；冲突必须降低 confidence/strength。若证据不能支持全部四个精确组件，按现有 stage contract 拒绝，不得伪造 neutral。Accepted claims 必须引用实际 get_us_macro_snapshot result event 的真实 evidence_id；当前证据不是已实现的 5D 结果。Autoresearch 只能依据独立的 event-triggered、T+1 open 后 5 个交易日、按 PIT volatility 归一化的 A-share role-path outcome，演进 prompt/tool interpretation 与半年一次的 component weights。fallback=false 表示缺失证据必须拒绝。不得判断 Fed、dollar、yield curve 或 credit conditions，也不得生成跨 Agent 结论。",
          ]
        : [
            "get_us_macro_snapshot contains PIT ALFRED real-economy observations, not an A-share signal. Use actual, previous, expected, and release/vintage/as-of only when those fields are present; never invent missing consensus or surprise, and put numeric facts only in structured snapshot echo fields. Apply exact component duties: growth_production transmits real GDP and industrial production through US activity and import demand into China exporters, industrial earnings, and cyclical A-share beta; prices transmits CPI, core CPI, PCE, and core PCE through US inflation and real purchasing power into external demand and Chinese exporter margins, but never infers the Fed, USD, yield curve, or credit conditions; employment transmits payrolls and unemployment through household income and consumption into China export orders and risk appetite; demand_trade transmits retail sales and the trade balance through US final demand and import absorption into Chinese exporters and supply chains. Every component must use its exact subject id and independently own real evidence not shared with another component; conflicts must lower confidence/strength. If evidence cannot support all four exact components, reject under the existing stage contract instead of fabricating a neutral. Accepted claims must cite real evidence_id values from the actual get_us_macro_snapshot result event; current evidence is not the realized 5D result. Autoresearch may evolve prompt/tool interpretation and semiannual component weights only against the independent event-triggered A-share role-path outcome over 5 trading days after T+1 open, normalized by PIT volatility. fallback=false means missing evidence must be rejected. Do not judge the Fed, dollar, yield curve, or credit conditions or produce a cross-Agent conclusion.",
          ]
      : [];
  const euEconomyBoundary =
    agent === "eu_economy"
      ? language === "zh"
        ? [
            "get_eu_macro_snapshot 包含 PIT registered EU-27 real-economy observations，不是 A 股信号。仅在字段存在时使用 actual、previous、expected 与 release/vintage/as-of；不得虚构缺失的 consensus 或 surprise，数值事实只能写入结构化 snapshot echo 字段。经济职责必须按精确组件执行：growth_production 将 EU GDP 与 industrial production 经 European activity/import demand 传导到 Chinese exporters、manufacturing earnings 与 cyclical A-share beta；prices 将 HICP 经 European inflation 与 real purchasing power 传导到 external demand 与 Chinese exporter margins，但不得推断 ECB、FX、curves、bank credit 或 financial stress；employment 将 unemployment 与 labour conditions 经 household income/consumption 传导到 Chinese export orders 与 risk appetite；demand_trade 将 imports、exports 与 household consumption 经 EU final demand/import absorption 传导到 Chinese exporters 与 supply chains。范围仅限 EU-27；排除 UK、Switzerland、Norway 与 non-EU aggregation。每个组件必须使用精确 subject id，并分别拥有不与其他组件共享的真实 evidence；冲突必须降低 confidence/strength。若证据不能支持全部四个精确组件，按现有 stage contract 拒绝，不得伪造 neutral。Accepted claims 必须引用实际 get_eu_macro_snapshot result event 的真实 evidence_id；当前证据不是已实现的 5D 结果。Autoresearch 只能依据独立的 event-triggered、T+1 open 后 5 个交易日、按 PIT volatility 归一化的 A-share role-path outcome，演进 prompt/tool interpretation 与半年一次的 component weights。fallback=false 表示缺失证据必须拒绝。不得判断 ECB、FX、curves 或 financial stress，也不得生成跨 Agent 结论。",
          ]
        : [
            "get_eu_macro_snapshot contains PIT registered EU-27 real-economy observations, not an A-share signal. Use actual, previous, expected, and release/vintage/as-of only when those fields are present; never invent missing consensus or surprise, and put numeric facts only in structured snapshot echo fields. Apply exact component duties: growth_production transmits EU GDP and industrial production through European activity and import demand into Chinese exporters, manufacturing earnings, and cyclical A-share beta; prices transmits HICP through European inflation and real purchasing power into external demand and Chinese exporter margins, but never infers the ECB, FX, curves, bank credit, or financial stress; employment transmits unemployment and labour conditions through household income and consumption into Chinese export orders and risk appetite; demand_trade transmits imports, exports, and household consumption through EU final demand and import absorption into Chinese exporters and supply chains. Scope is EU-27 only; exclude the UK, Switzerland, Norway, and non-EU aggregation. Every component must use its exact subject id and independently own real evidence not shared with another component; conflicts must lower confidence/strength. If evidence cannot support all four exact components, reject under the existing stage contract instead of fabricating a neutral. Accepted claims must cite real evidence_id values from the actual get_eu_macro_snapshot result event; current evidence is not the realized 5D result. Autoresearch may evolve prompt/tool interpretation and semiannual component weights only against the independent event-triggered A-share role-path outcome over 5 trading days after T+1 open, normalized by PIT volatility. fallback=false means missing evidence must be rejected. Do not judge the ECB, FX, curves, or financial stress or produce a cross-Agent conclusion.",
          ]
      : [];
  const centralBankBoundary =
    agent === "central_bank"
      ? language === "zh"
        ? [
            "get_central_bank_snapshot 是 PIT PBOC/domestic-liquidity evidence，不是 A 股信号。仅在字段存在时使用 actual、expected、previous 与 release/vintage/as-of，不得虚构缺失的 expected 或 surprise；数值事实只能写入结构化 snapshot echo 字段，不得写入叙述。经济职责必须按精确组件执行：pboc_policy_bias 只用 OMO、LPR 与官方政策 evidence 判断反应函数及其 financing/valuation transmission，不得重述中国周期；liquidity_money_market 只用 OMO liquidity 与 Shibor ON/3M 判断银行间流动性及短端资金成本；china_curve 只用 registered nominal CGB 2Y/10Y 及 slope 判断 duration/discount-rate transmission，绝不得声称 real curve；credit_conditions 只用已注册 TSF/credit context 判断融资可得性与信用脉冲，不得把 China macro LLM 当作 evidence。每个组件必须使用精确 subject id，并分别拥有不与其他组件共享的真实 evidence；冲突必须降低 confidence/strength。若证据不能支持全部四个精确组件，按现有 stage contract 拒绝，不得伪造 neutral。Accepted claims 必须引用实际 get_central_bank_snapshot result event 的真实 evidence_id；当前证据不是已实现的 5D 结果。Autoresearch 只能依据独立的 event-triggered、T+1 open 后 5 个交易日、按 PIT volatility 归一化的 A-share role-path outcome，演进 prompt/tool interpretation 与半年一次的 component weights。fallback=false 表示缺失证据必须拒绝。不得生成跨 Agent 结论，也不得判断海外央行。",
          ]
        : [
            "get_central_bank_snapshot contains PIT PBOC and domestic-liquidity evidence, not an A-share signal. Use actual, expected, previous, and release/vintage/as-of only when those fields are present; never invent missing expected values or surprise, and put numeric facts only in structured snapshot echo fields, never in narrative. Apply exact component duties: pboc_policy_bias uses only OMO, LPR, and official policy evidence to judge the reaction function and its financing/valuation transmission, without restating the China cycle; liquidity_money_market uses only OMO liquidity and Shibor ON/3M to judge interbank liquidity and short-end funding costs; china_curve uses only registered nominal CGB 2Y/10Y and their slope to judge duration/discount-rate transmission and must never claim a real curve; credit_conditions uses only registered TSF/credit context to judge financing availability and credit impulse and must not treat the China macro LLM as evidence. Every component must use its exact subject id and independently own real evidence not shared with another component; conflicts must lower confidence/strength. If evidence cannot support all four exact components, reject under the existing stage contract instead of fabricating a neutral. Accepted claims must cite real evidence_id values from the actual get_central_bank_snapshot result event; current evidence is not the realized 5D result. Autoresearch may evolve prompt/tool interpretation and semiannual component weights only against the independent event-triggered A-share role-path outcome over 5 trading days after T+1 open, normalized by PIT volatility. fallback=false means missing evidence must be rejected. Do not produce cross-Agent conclusions or judge foreign central banks.",
          ]
      : [];
  const usFinancialConditionsBoundary =
    agent === "us_financial_conditions"
      ? language === "zh"
        ? [
            "get_us_financial_conditions_snapshot 是 PIT US financial evidence，不是 A 股信号。仅在字段存在时使用 actual、expected、previous 与 release/vintage/as-of，不得虚构缺失的 expected 或 surprise；数值事实只能写入结构化 snapshot echo 字段，不得写入叙述。经济职责必须按精确组件执行：fed_liquidity 只用 FOMC statement 与 EFFR/SOFR 判断政策、隔夜资金及其 global funding/valuation transmission，不得重述 US growth；us_curve 区分 Tushare nominal 3M/2Y/10Y/30Y 的 level/slope 与 ALFRED real 5Y/10Y/30Y 的 real-yield discount-rate/duration transmission；credit_financial_stress 只用 BAA10Y、NFCI 与 VIX 判断 credit spread、financial stress 与 volatility 对融资和 A 股 risk appetite 的传导；usd_rmb 只用 DTWEXBGS broad dollar 与实际 USDCNH.FXCM offshore CNH proxy 判断美元及离岸人民币压力，绝不得称为 onshore CNY fixing 或 settlement。us_economy deterministic context 仅作背景，不得成为第五个组件、替代 claim evidence 或读取其 LLM。每个组件必须使用精确 subject id，并分别拥有不与其他组件共享的真实 evidence；冲突必须降低 confidence/strength。若证据不能支持全部四个精确组件，按现有 stage contract 拒绝，不得伪造 neutral。Accepted claims 必须引用实际 get_us_financial_conditions_snapshot result event 的真实 evidence_id；当前证据不是已实现的 5D 结果。Autoresearch 只能依据独立、fixed non-overlapping、T+1 open 后 5 个交易日且按 PIT volatility 归一化的 outcome，演进 prompt/tool interpretation 与半年一次的 component weights。fallback=false 表示缺失证据必须拒绝。不得生成跨 Agent 结论。",
          ]
        : [
            "get_us_financial_conditions_snapshot contains PIT US financial evidence, not an A-share signal. Use actual, expected, previous, and release/vintage/as-of only when those fields are present; never invent missing expected values or surprise, and put numeric facts only in structured snapshot echo fields, never in narrative. Apply exact component duties: fed_liquidity uses only the FOMC statement and EFFR/SOFR to judge policy, overnight funding, and global funding/valuation transmission, without restating US growth; us_curve distinguishes the level/slope of Tushare nominal 3M/2Y/10Y/30Y from the real-yield discount-rate/duration transmission of ALFRED real 5Y/10Y/30Y; credit_financial_stress uses only BAA10Y, NFCI, and VIX to judge how credit spreads, financial stress, and volatility transmit into financing and A-share risk appetite; usd_rmb uses only the DTWEXBGS broad dollar and the actual USDCNH.FXCM offshore CNH proxy to judge dollar and offshore-renminbi pressure and must never call it an onshore CNY fixing or settlement rate. us_economy deterministic context is background only: it cannot become a fifth component, replace claim evidence, or permit reading its LLM output. Every component must use its exact subject id and independently own real evidence not shared with another component; conflicts must lower confidence/strength. If evidence cannot support all four exact components, reject under the existing stage contract instead of fabricating a neutral. Accepted claims must cite real evidence_id values from the actual get_us_financial_conditions_snapshot result event; current evidence is not the realized 5D result. Autoresearch may evolve prompt/tool interpretation and semiannual component weights only against the independent, fixed non-overlapping outcome over 5 trading days after T+1 open, normalized by PIT volatility. fallback=false means missing evidence must be rejected. Do not produce cross-Agent conclusions.",
          ]
      : [];
  const euroAreaFinancialConditionsBoundary =
    agent === "euro_area_financial_conditions"
      ? language === "zh"
        ? [
            "get_euro_area_financial_conditions_snapshot 是 PIT ECB/euro financial evidence，不是 A 股信号。仅在字段存在时使用 actual、expected、previous 与 release/vintage/as-of，不得虚构缺失的 expected 或 surprise；数值事实只能写入结构化 snapshot echo 字段，不得写入叙述。经济职责必须按精确组件执行：ecb_liquidity 只用 DFR、MRR 与 €STR 判断政策利率、短端资金及其 global funding/valuation transmission，不得重述 EU growth；euro_area_curve 只用 registered AAA nominal 2Y/10Y 的 level/slope 判断 duration/discount-rate transmission；bank_credit 只用 euro-area NFC adjusted loan growth 与 corporation new-business loan rate 判断 credit supply 与 funding cost；eur_financial_stress 只用 ECB USD/EUR reference、实际 EURUSD.FXCM 与 registered joint bank/sovereign default-probability stress indicators，判断 EUR/financial stress 对外部融资和 A 股 risk appetite 的传导，不得虚构 RDF 的地域或机制。eu_economy deterministic context 仅作背景，不得成为第五个组件、替代 claim evidence 或读取其 LLM；不得纳入非欧元区央行或市场。每个组件必须使用精确 subject id，并分别拥有不与其他组件共享的真实 evidence；冲突必须降低 confidence/strength。若证据不能支持全部四个精确组件，按现有 stage contract 拒绝，不得伪造 neutral。Accepted claims 必须引用实际 get_euro_area_financial_conditions_snapshot result event 的真实 evidence_id；当前证据不是已实现的 5D 结果。Autoresearch 只能依据独立、fixed non-overlapping、T+1 open 后 5 个交易日且按 PIT volatility 归一化的 outcome，演进 prompt/tool interpretation 与半年一次的 component weights。fallback=false 表示缺失证据必须拒绝。不得生成跨 Agent 结论。",
          ]
        : [
            "get_euro_area_financial_conditions_snapshot contains PIT ECB and euro financial evidence, not an A-share signal. Use actual, expected, previous, and release/vintage/as-of only when those fields are present; never invent missing expected values or surprise, and put numeric facts only in structured snapshot echo fields, never in narrative. Apply exact component duties: ecb_liquidity uses only DFR, MRR, and €STR to judge policy rates, short-end funding, and global funding/valuation transmission, without restating EU growth; euro_area_curve uses only the level/slope of registered AAA nominal 2Y/10Y to judge duration/discount-rate transmission; bank_credit uses only euro-area NFC adjusted loan growth and the corporation new-business loan rate to judge credit supply and funding cost; eur_financial_stress uses only the ECB USD/EUR reference rate, actual EURUSD.FXCM, and registered joint bank/sovereign default-probability stress indicators to judge how EUR and financial stress transmit into external financing and A-share risk appetite, without inventing RDF geography or mechanisms. eu_economy deterministic context is background only: it cannot become a fifth component, replace claim evidence, or permit reading its LLM output; exclude non-euro-area central banks and markets. Every component must use its exact subject id and independently own real evidence not shared with another component; conflicts must lower confidence/strength. If evidence cannot support all four exact components, reject under the existing stage contract instead of fabricating a neutral. Accepted claims must cite real evidence_id values from the actual get_euro_area_financial_conditions_snapshot result event; current evidence is not the realized 5D result. Autoresearch may evolve prompt/tool interpretation and semiannual component weights only against the independent, fixed non-overlapping outcome over 5 trading days after T+1 open, normalized by PIT volatility. fallback=false means missing evidence must be rejected. Do not produce cross-Agent conclusions.",
          ]
      : [];
  const commoditiesBoundary =
    agent === "commodities"
      ? language === "zh"
        ? [
            "get_commodity_conditions_snapshot 是五个已登记 commodity families 的 PIT 合约、结算与库存 evidence，不是 A 股信号。仅在字段存在时使用 actual、previous 与 as-of，不得虚构 expected、surprise 或工具未提供的宏观因果；数值事实只能写入结构化 snapshot echo 字段，不得写入叙述。经济职责必须按精确组件执行：energy 只用 SC@INE 的原油期限结构与库存判断能源成本及其对 A 股利润率的传导；industrial_metals 只用 CU@SHFE 判断工业需求与制造成本；gold 只用 AU@SHFE 判断避险与实际利率敏感的风险偏好，不得超出工具实际字段声称宏观因果；agriculture_food 只用 C@DCE 与 M@DCE 判断粮食及饲料成本。仅当对应 family 存在实际两个合约的数据时，才可称 contango 或 backwardation。每个组件必须使用精确 subject id，并分别拥有不与其他组件共享的真实 evidence；冲突必须降低 confidence/strength。若证据不能支持全部四个精确组件，按现有 stage contract 拒绝，不得伪造 neutral。Accepted claims 必须引用实际 get_commodity_conditions_snapshot result event 的真实 evidence_id；当前证据不是已实现的 5D 结果。Autoresearch 只能依据独立、fixed non-overlapping、T+1 open 后 5 个交易日且按 PIT volatility 归一化的 outcome，演进 prompt/tool interpretation 与半年一次的 component weights。fallback=false 表示缺失证据必须拒绝。不得生成跨 Agent 结论。",
          ]
        : [
            "get_commodity_conditions_snapshot contains PIT contract, settlement, and inventory evidence for the five registered commodity families, not an A-share signal. Use actual, previous, and as-of only when those fields are present; never invent expected values, surprise, or macro causality absent from the tool, and put numeric facts only in structured snapshot echo fields, never in narrative. Apply exact component duties: energy uses only the SC@INE crude-oil term structure and inventory to judge energy costs and their transmission into A-share margins; industrial_metals uses only CU@SHFE to judge industrial demand and manufacturing costs; gold uses only AU@SHFE to judge safe-haven and real-rate-sensitive risk appetite without claiming macro causality beyond actual tool fields; agriculture_food uses only C@DCE and M@DCE to judge grain and feed costs. Claim contango or backwardation only when the corresponding family has actual data for two contracts. Every component must use its exact subject id and independently own real evidence not shared with another component; conflicts must lower confidence/strength. If evidence cannot support all four exact components, reject under the existing stage contract instead of fabricating a neutral. Accepted claims must cite real evidence_id values from the actual get_commodity_conditions_snapshot result event; current evidence is not the realized 5D result. Autoresearch may evolve prompt/tool interpretation and semiannual component weights only against the independent, fixed non-overlapping outcome over 5 trading days after T+1 open, normalized by PIT volatility. fallback=false means missing evidence must be rejected. Do not produce cross-Agent conclusions.",
          ]
      : [];
  const institutionalFlowBoundary =
    agent === "institutional_flow"
      ? language === "zh"
        ? [
            "get_market_positioning_snapshot 只包含固定五只 ETF（159915.SZ、510050.SH、510300.SH、510500.SH、588000.SH）的 PIT fd_share，单位为万份。份额增加或减少只表示申购或赎回事实，只能作为配置/positioning 代理；不得称为资金净流入、北向资金、机构持仓所有权或主动买卖金额。缺少 price、NAV 与 cash 时不得计算资金流，也不得声称份额变化导致未来价格。每只 ETF 的 accepted claim 必须分别引用实际 get_market_positioning_snapshot result event 的真实 evidence_id。当前证据不是已实现的未来 5D 结果。Autoresearch 只能依据独立的 510500.SH 相对 benchmark、T+1 open 后 5 个交易日且按 PIT volatility 归一化的 outcome 演进 prompt/tool interpretation。经济 signal 可诚实为 UNKNOWN。固定五只 ETF 任一缺失时按现有 stage contract 拒绝；fallback=false，不得伪造 neutral。",
          ]
        : [
            "get_market_positioning_snapshot contains only PIT fd_share observations, measured in ten-thousand shares, for the five fixed ETFs (159915.SZ, 510050.SH, 510300.SH, 510500.SH, and 588000.SH). A share increase or decrease records creation or redemption only and may serve solely as an allocation/positioning proxy; never call it net fund inflow, northbound flow, institutional ownership, or active buy/sell amount. Without price, NAV, and cash, do not calculate fund flow or claim that share changes cause future prices. Each ETF's accepted claim must separately cite a real evidence_id from the actual get_market_positioning_snapshot result event. Current evidence is not the realized future 5D result. Autoresearch may evolve prompt/tool interpretation only against the independent 510500.SH-relative-to-benchmark outcome over 5 trading days after T+1 open, normalized by PIT volatility. It may honestly project an UNKNOWN economic signal. If any of the five fixed ETFs is missing, reject under the existing stage contract; fallback=false and do not fabricate a neutral.",
          ]
      : [];
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
      ...chinaBoundary,
      ...usEconomyBoundary,
      ...euEconomyBoundary,
      ...centralBankBoundary,
      ...usFinancialConditionsBoundary,
      ...euroAreaFinancialConditionsBoundary,
      ...commoditiesBoundary,
      ...institutionalFlowBoundary,
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
    ...chinaBoundary,
    ...usEconomyBoundary,
    ...euEconomyBoundary,
    ...centralBankBoundary,
    ...usFinancialConditionsBoundary,
    ...euroAreaFinancialConditionsBoundary,
    ...commoditiesBoundary,
    ...institutionalFlowBoundary,
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
