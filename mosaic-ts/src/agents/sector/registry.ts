import { createHash } from "node:crypto";
import { z } from "zod";
import type { StandardSectorAgentId } from "../types.js";

export const SECTOR_UNIVERSE_MANIFEST_VERSION = "sector_universe_manifest_v1";
export const SECTOR_DIRECTION_REGISTRY_VERSION = "sector_direction_registry_v3";
export const SECTOR_METRIC_REGISTRY_VERSION = "sector_direction_metric_registry_v1";

type ClassificationLevel = "l1_code" | "l2_code" | "l3_code";

interface ClassificationCode {
  level: ClassificationLevel;
  code: string;
}

interface DirectionDefinition {
  directionId: string;
  included: readonly ClassificationCode[];
  excluded?: readonly ClassificationCode[];
}

interface SectorRegistryEntry {
  universe: readonly ClassificationCode[];
  universeExcluded?: readonly ClassificationCode[];
  directions: readonly [DirectionDefinition, ...DirectionDefinition[]];
}

const code = (level: ClassificationLevel, value: string): ClassificationCode => ({
  level,
  code: value,
});
const l1 = (value: string): ClassificationCode => code("l1_code", value);
const l2 = (value: string): ClassificationCode => code("l2_code", value);

export const SECTOR_DIRECTION_REGISTRY = {
  semiconductor: {
    universe: [l2("801081.SI")],
    directions: [{ directionId: "semiconductor_core", included: [l2("801081.SI")] }],
  },
  technology: {
    universe: [l1("801080.SI"), l1("801750.SI"), l1("801760.SI"), l1("801770.SI")],
    universeExcluded: [l2("801081.SI")],
    directions: [
      {
        directionId: "electronics_non_semiconductor",
        included: [l1("801080.SI")],
        excluded: [l2("801081.SI")],
      },
      { directionId: "computer", included: [l1("801750.SI")] },
      { directionId: "media", included: [l1("801760.SI")] },
      { directionId: "communications", included: [l1("801770.SI")] },
    ],
  },
  energy: {
    universe: [
      l1("801950.SI"),
      l1("801960.SI"),
      l2("801161.SI"),
      l2("801735.SI"),
      l2("801736.SI"),
      l2("801737.SI"),
    ],
    directions: [
      { directionId: "coal", included: [l1("801950.SI")] },
      { directionId: "oil_gas", included: [l1("801960.SI")] },
      { directionId: "electric_power", included: [l2("801161.SI")] },
      { directionId: "solar", included: [l2("801735.SI")] },
      { directionId: "wind", included: [l2("801736.SI")] },
      { directionId: "battery_storage", included: [l2("801737.SI")] },
    ],
  },
  biotech: {
    universe: [l1("801150.SI")],
    directions: [{ directionId: "medicine_biotech", included: [l1("801150.SI")] }],
  },
  consumer: {
    universe: [
      l1("801110.SI"),
      l1("801120.SI"),
      l1("801130.SI"),
      l1("801140.SI"),
      l1("801200.SI"),
      l1("801210.SI"),
      l1("801980.SI"),
      l1("801880.SI"),
    ],
    directions: [
      { directionId: "home_appliances", included: [l1("801110.SI")] },
      { directionId: "food_beverage", included: [l1("801120.SI")] },
      { directionId: "textiles_apparel", included: [l1("801130.SI")] },
      { directionId: "light_manufacturing", included: [l1("801140.SI")] },
      { directionId: "retail", included: [l1("801200.SI")] },
      { directionId: "consumer_services", included: [l1("801210.SI")] },
      { directionId: "beauty_care", included: [l1("801980.SI")] },
      { directionId: "automobiles", included: [l1("801880.SI")] },
    ],
  },
  industrials: {
    universe: [
      l1("801030.SI"),
      l1("801040.SI"),
      l1("801050.SI"),
      l1("801890.SI"),
      l1("801740.SI"),
      l2("801731.SI"),
      l2("801733.SI"),
      l2("801738.SI"),
      l1("801170.SI"),
      l1("801970.SI"),
    ],
    directions: [
      { directionId: "basic_chemicals", included: [l1("801030.SI")] },
      { directionId: "steel", included: [l1("801040.SI")] },
      { directionId: "nonferrous_metals", included: [l1("801050.SI")] },
      { directionId: "machinery", included: [l1("801890.SI")] },
      { directionId: "defense", included: [l1("801740.SI")] },
      {
        directionId: "electrical_equipment_ex_renewables",
        included: [l2("801731.SI"), l2("801733.SI"), l2("801738.SI")],
      },
      { directionId: "transportation", included: [l1("801170.SI")] },
      { directionId: "environmental", included: [l1("801970.SI")] },
    ],
  },
  real_estate_construction: {
    universe: [l1("801180.SI"), l1("801710.SI"), l1("801720.SI")],
    directions: [
      { directionId: "real_estate", included: [l1("801180.SI")] },
      { directionId: "building_materials", included: [l1("801710.SI")] },
      { directionId: "construction_decoration", included: [l1("801720.SI")] },
    ],
  },
  financials: {
    universe: [l1("801780.SI"), l1("801790.SI")],
    directions: [
      { directionId: "banking", included: [l1("801780.SI")] },
      { directionId: "non_bank_finance", included: [l1("801790.SI")] },
    ],
  },
  agriculture: {
    universe: [l1("801010.SI")],
    directions: [
      { directionId: "crop_seed", included: [l2("801016.SI")] },
      {
        directionId: "livestock_aquaculture",
        included: [l2("801017.SI"), l2("801015.SI")],
      },
      {
        directionId: "feed_animal_health",
        included: [l2("801014.SI"), l2("801018.SI")],
      },
      {
        directionId: "forestry_processing_services",
        included: [l2("801011.SI"), l2("801012.SI"), l2("801019.SI")],
      },
    ],
  },
} as const satisfies Readonly<Record<StandardSectorAgentId, SectorRegistryEntry>>;

export const SECTOR_DIRECTION_REGISTRY_HASH = canonicalHash(SECTOR_DIRECTION_REGISTRY);

export const SECTOR_OVERLAP_PRECEDENCE = [
  "semiconductor",
  "technology",
  "energy",
  "biotech",
  "consumer",
  "industrials",
  "real_estate_construction",
  "financials",
  "agriculture",
] as const satisfies readonly StandardSectorAgentId[];

export function sectorDirectionIds(agentId: StandardSectorAgentId): readonly [string, ...string[]] {
  return SECTOR_DIRECTION_REGISTRY[agentId].directions.map(
    (direction) => direction.directionId,
  ) as [string, ...string[]];
}

type MetricFamily =
  | "FUNDAMENTALS"
  | "VALUATION"
  | "BASKET_PRICE_TREND"
  | "BASKET_BREADTH"
  | "BASKET_TURNOVER_FLOW"
  | "ETF_CONFIRMATION";
type MetricUnit = "RATIO" | "PERCENT" | "CNY" | "RETURN" | "VOLATILITY";
type LookbackKind = "TRADING_DAYS" | "REPORTED_QUARTERS" | "POINT_IN_TIME";

function metric(
  metricId: string,
  family: MetricFamily,
  formulaId: string,
  lookbackKind: LookbackKind,
  lookbackValue: number,
  unit: MetricUnit,
  required: boolean,
  minimumObservations: number,
  minimumCoverageRatio: number,
  basketWeighting: "PIT_EQUAL_WEIGHT" | "LAGGED_20D_MEDIAN_AMOUNT",
  benchmarkRole: "NONE" | "PARENT_SECTOR_BENCHMARK" | "DIRECTION_BASKET",
) {
  const content = {
    metric_id: metricId,
    metric_contract_version: "v1",
    metric_family: family,
    formula_id: formulaId,
    formula_version: "v1" as const,
    unit,
    lookback: { kind: lookbackKind, value: lookbackValue },
    required_for_direction_readiness: required,
    minimum_observations: minimumObservations,
    minimum_coverage_ratio: minimumCoverageRatio,
    basket_weighting: basketWeighting,
    benchmark_role: benchmarkRole,
    adjustment_contract_version: "pit_total_return_adjustment_v1",
    percentile_lookback_trading_days: 252,
    percentile_method: "EMPIRICAL_CDF_AVERAGE_TIE" as const,
    change_lookback_trading_days: 20,
  };
  return { ...content, metric_contract_hash: canonicalHash(content) };
}

export const SECTOR_DIRECTION_METRIC_REGISTRY = [
  metric(
    "REVENUE_GROWTH_TTM_YOY",
    "FUNDAMENTALS",
    "PIT_REVENUE_GROWTH_TTM_YOY_EQUAL_WEIGHT",
    "REPORTED_QUARTERS",
    8,
    "RATIO",
    true,
    8,
    0.9,
    "PIT_EQUAL_WEIGHT",
    "NONE",
  ),
  metric(
    "OPERATING_CASHFLOW_MARGIN_TTM",
    "FUNDAMENTALS",
    "PIT_OPERATING_CASHFLOW_MARGIN_TTM_EQUAL_WEIGHT",
    "REPORTED_QUARTERS",
    4,
    "RATIO",
    true,
    4,
    0.9,
    "PIT_EQUAL_WEIGHT",
    "NONE",
  ),
  metric(
    "EARNINGS_YIELD_TTM",
    "VALUATION",
    "PIT_EARNINGS_YIELD_TTM_EQUAL_WEIGHT",
    "POINT_IN_TIME",
    1,
    "RATIO",
    true,
    1,
    0.9,
    "PIT_EQUAL_WEIGHT",
    "NONE",
  ),
  metric(
    "BOOK_TO_PRICE_LF",
    "VALUATION",
    "PIT_BOOK_TO_PRICE_LF_EQUAL_WEIGHT",
    "POINT_IN_TIME",
    1,
    "RATIO",
    true,
    1,
    0.9,
    "PIT_EQUAL_WEIGHT",
    "NONE",
  ),
  metric(
    "RELATIVE_TOTAL_RETURN_5D",
    "BASKET_PRICE_TREND",
    "PIT_BASKET_RELATIVE_TOTAL_RETURN",
    "TRADING_DAYS",
    5,
    "RETURN",
    true,
    6,
    0.9,
    "PIT_EQUAL_WEIGHT",
    "PARENT_SECTOR_BENCHMARK",
  ),
  metric(
    "RELATIVE_TOTAL_RETURN_20D",
    "BASKET_PRICE_TREND",
    "PIT_BASKET_RELATIVE_TOTAL_RETURN",
    "TRADING_DAYS",
    20,
    "RETURN",
    true,
    21,
    0.9,
    "PIT_EQUAL_WEIGHT",
    "PARENT_SECTOR_BENCHMARK",
  ),
  metric(
    "RELATIVE_TOTAL_RETURN_60D",
    "BASKET_PRICE_TREND",
    "PIT_BASKET_RELATIVE_TOTAL_RETURN",
    "TRADING_DAYS",
    60,
    "RETURN",
    true,
    61,
    0.9,
    "PIT_EQUAL_WEIGHT",
    "PARENT_SECTOR_BENCHMARK",
  ),
  metric(
    "ABOVE_MA20_PCT",
    "BASKET_BREADTH",
    "PIT_CONSTITUENT_ABOVE_MOVING_AVERAGE_PCT",
    "TRADING_DAYS",
    20,
    "PERCENT",
    true,
    20,
    0.9,
    "PIT_EQUAL_WEIGHT",
    "NONE",
  ),
  metric(
    "ABOVE_MA60_PCT",
    "BASKET_BREADTH",
    "PIT_CONSTITUENT_ABOVE_MOVING_AVERAGE_PCT",
    "TRADING_DAYS",
    60,
    "PERCENT",
    true,
    60,
    0.9,
    "PIT_EQUAL_WEIGHT",
    "NONE",
  ),
  metric(
    "NEW_HIGH_LOW_20D_BALANCE",
    "BASKET_BREADTH",
    "PIT_NEW_HIGH_LOW_BALANCE",
    "TRADING_DAYS",
    20,
    "PERCENT",
    true,
    20,
    0.9,
    "PIT_EQUAL_WEIGHT",
    "NONE",
  ),
  metric(
    "TURNOVER_EXPANSION_20D_PCT",
    "BASKET_TURNOVER_FLOW",
    "PIT_TURNOVER_EXPANSION_PCT",
    "TRADING_DAYS",
    20,
    "PERCENT",
    true,
    21,
    0.9,
    "PIT_EQUAL_WEIGHT",
    "NONE",
  ),
  metric(
    "REALIZED_VOLATILITY_60D",
    "BASKET_PRICE_TREND",
    "PIT_BASKET_REALIZED_VOLATILITY",
    "TRADING_DAYS",
    60,
    "VOLATILITY",
    true,
    60,
    0.9,
    "PIT_EQUAL_WEIGHT",
    "NONE",
  ),
  metric(
    "CURRENT_DRAWDOWN_252D",
    "BASKET_PRICE_TREND",
    "PIT_BASKET_CURRENT_DRAWDOWN",
    "TRADING_DAYS",
    252,
    "RETURN",
    true,
    252,
    0.9,
    "PIT_EQUAL_WEIGHT",
    "NONE",
  ),
  metric(
    "ETF_RELATIVE_RETURN_5D",
    "ETF_CONFIRMATION",
    "PIT_ETF_FAMILY_RELATIVE_TOTAL_RETURN",
    "TRADING_DAYS",
    5,
    "RETURN",
    false,
    6,
    0.8,
    "LAGGED_20D_MEDIAN_AMOUNT",
    "DIRECTION_BASKET",
  ),
  metric(
    "ETF_RELATIVE_RETURN_20D",
    "ETF_CONFIRMATION",
    "PIT_ETF_FAMILY_RELATIVE_TOTAL_RETURN",
    "TRADING_DAYS",
    20,
    "RETURN",
    false,
    21,
    0.8,
    "LAGGED_20D_MEDIAN_AMOUNT",
    "DIRECTION_BASKET",
  ),
  metric(
    "ETF_RELATIVE_RETURN_60D",
    "ETF_CONFIRMATION",
    "PIT_ETF_FAMILY_RELATIVE_TOTAL_RETURN",
    "TRADING_DAYS",
    60,
    "RETURN",
    false,
    61,
    0.8,
    "LAGGED_20D_MEDIAN_AMOUNT",
    "DIRECTION_BASKET",
  ),
  metric(
    "ETF_ABOVE_MA20",
    "ETF_CONFIRMATION",
    "PIT_ETF_FAMILY_ABOVE_MOVING_AVERAGE",
    "TRADING_DAYS",
    20,
    "RATIO",
    false,
    20,
    0.8,
    "LAGGED_20D_MEDIAN_AMOUNT",
    "NONE",
  ),
  metric(
    "ETF_ABOVE_MA60",
    "ETF_CONFIRMATION",
    "PIT_ETF_FAMILY_ABOVE_MOVING_AVERAGE",
    "TRADING_DAYS",
    60,
    "RATIO",
    false,
    60,
    0.8,
    "LAGGED_20D_MEDIAN_AMOUNT",
    "NONE",
  ),
  metric(
    "ETF_TURNOVER_EXPANSION_20D",
    "ETF_CONFIRMATION",
    "PIT_ETF_FAMILY_TURNOVER_EXPANSION",
    "TRADING_DAYS",
    20,
    "PERCENT",
    false,
    21,
    0.8,
    "LAGGED_20D_MEDIAN_AMOUNT",
    "NONE",
  ),
  metric(
    "ETF_SHARE_CHANGE_1D",
    "ETF_CONFIRMATION",
    "PIT_ETF_FAMILY_SHARE_CHANGE",
    "TRADING_DAYS",
    1,
    "PERCENT",
    false,
    2,
    0.8,
    "LAGGED_20D_MEDIAN_AMOUNT",
    "NONE",
  ),
  metric(
    "ETF_SHARE_CHANGE_5D",
    "ETF_CONFIRMATION",
    "PIT_ETF_FAMILY_SHARE_CHANGE",
    "TRADING_DAYS",
    5,
    "PERCENT",
    false,
    6,
    0.8,
    "LAGGED_20D_MEDIAN_AMOUNT",
    "NONE",
  ),
  metric(
    "ETF_SHARE_CHANGE_20D",
    "ETF_CONFIRMATION",
    "PIT_ETF_FAMILY_SHARE_CHANGE",
    "TRADING_DAYS",
    20,
    "PERCENT",
    false,
    21,
    0.8,
    "LAGGED_20D_MEDIAN_AMOUNT",
    "NONE",
  ),
  metric(
    "ETF_ESTIMATED_CREATION_REDEMPTION_1D",
    "ETF_CONFIRMATION",
    "PIT_ETF_FAMILY_ESTIMATED_CREATION_REDEMPTION",
    "TRADING_DAYS",
    1,
    "CNY",
    false,
    2,
    0.8,
    "LAGGED_20D_MEDIAN_AMOUNT",
    "NONE",
  ),
  metric(
    "ETF_ESTIMATED_CREATION_REDEMPTION_5D",
    "ETF_CONFIRMATION",
    "PIT_ETF_FAMILY_ESTIMATED_CREATION_REDEMPTION",
    "TRADING_DAYS",
    5,
    "CNY",
    false,
    6,
    0.8,
    "LAGGED_20D_MEDIAN_AMOUNT",
    "NONE",
  ),
  metric(
    "ETF_ESTIMATED_CREATION_REDEMPTION_20D",
    "ETF_CONFIRMATION",
    "PIT_ETF_FAMILY_ESTIMATED_CREATION_REDEMPTION",
    "TRADING_DAYS",
    20,
    "CNY",
    false,
    21,
    0.8,
    "LAGGED_20D_MEDIAN_AMOUNT",
    "NONE",
  ),
  metric(
    "ETF_PREMIUM_DISCOUNT",
    "ETF_CONFIRMATION",
    "PIT_ETF_FAMILY_PREMIUM_DISCOUNT",
    "POINT_IN_TIME",
    1,
    "PERCENT",
    false,
    1,
    0.8,
    "LAGGED_20D_MEDIAN_AMOUNT",
    "NONE",
  ),
] as const;

export const SECTOR_FLOW_COVERAGE_CONTRACT = freezeContract({
  contract_id: "sector_constituent_flow_v1",
  contract_version: "sector_flow_coverage_v1",
  source_endpoint: "moneyflow",
  source_net_flow_field: "net_mf_amount",
  denominator: "FROZEN_CANDIDATE_20D_MEDIAN_TURNOVER",
  minimum_coverage_ratio: 0.9,
  coverage_weighting: "PIT_CONSTITUENT_20D_MEDIAN_TURNOVER",
  aggregation: "OBSERVED_CONSTITUENT_NET_FLOW_PER_OBSERVED_MEDIAN_TURNOVER",
  ths_industry_flow_usage: "OPTIONAL_DIAGNOSTIC_ONLY",
});

export const SECTOR_DIRECTION_COMPARISON_CONTRACT = freezeContract({
  comparison_contract_id: "sector_direction_comparison_v2",
  comparison_contract_version: "sector_direction_comparison_v2",
  core_criteria: ["FUNDAMENTALS", "VALUATION", "BASKET_TECHNICALS", "RISK_ASYMMETRY"],
  coverage_gated_criteria: ["MACRO_EVENT_FIT", "CATALYSTS"],
  optional_etf_criteria: ["ETF_PRICE_CONFIRMATION", "ETF_SHARE_FLOW_CONFIRMATION"],
  pair_coverage: "ALL_ELIGIBLE_UNORDERED_PAIRS",
  reducer: "CONDORCET_THEN_SINGLE_CONFLICT_REVIEW_ELSE_ABSTAIN",
  core_vote_weight: 1,
  available_coverage_gated_vote_weight: 1,
  optional_etf_vote_weight: 0.5,
  minimum_base_support_count: 2,
  minimum_weighted_support_margin: 1,
  maximum_conflict_review_rounds: 1,
});

export const SECTOR_SECURITY_SCORING_CONTRACT = freezeContract({
  scoring_contract_id: "sector_security_scoring_v1",
  scoring_contract_version: "sector_security_scoring_v1",
  candidate_source: "PIT_DIRECTION_ELIGIBLE_SECURITIES",
  shortlist_order: "LAGGED_20D_MEDIAN_AMOUNT_DESC_THEN_TS_CODE_ASC",
  shortlist_maximum_size_per_direction: 50,
  model_pick_domain: "EXACT_FROZEN_SCORING_SHORTLIST",
  maximum_picks_per_side: 5,
  duplicate_ticker_policy: "REJECT_ACROSS_WHOLE_SUBMISSION",
  conviction_lower_bound_exclusive: 0,
  conviction_upper_bound_inclusive: 1,
  conviction_budget_per_side: 1,
});

export function buildSectorUniverseManifest() {
  const membershipQueryPlans = SECTOR_OVERLAP_PRECEDENCE.map((agentId) => {
    const entry = SECTOR_DIRECTION_REGISTRY[agentId];
    const branches = uniqueCodes([
      ...entry.universe,
      ...("universeExcluded" in entry ? entry.universeExcluded : []),
      ...entry.directions.flatMap((direction) => [
        ...direction.included,
        ...("excluded" in direction ? (direction.excluded ?? []) : []),
      ]),
    ]).flatMap((classification) =>
      (["Y", "N"] as const).map((isNew) => ({
        endpoint: "index_member_all" as const,
        parameter: classification.level,
        classification_code: classification.code,
        is_new: isNew,
      })),
    );
    const content = {
      query_plan_id: `sector-membership:${agentId}`,
      query_plan_version: "sector_membership_query_v1",
      sector_agent_id: agentId,
      branches,
      merge_key: ["l1_code", "l2_code", "l3_code", "ts_code", "in_date", "out_date"],
      post_filter_excluded_codes:
        "universeExcluded" in entry ? entry.universeExcluded.map((item) => item.code) : [],
    };
    return { ...content, query_plan_hash: canonicalHash(content) };
  });
  const directionContracts = SECTOR_OVERLAP_PRECEDENCE.flatMap((agentId) => {
    const directions = SECTOR_DIRECTION_REGISTRY[agentId].directions;
    const plan = membershipQueryPlans.find((row) => row.sector_agent_id === agentId);
    if (!plan) throw new Error(`missing membership plan for ${agentId}`);
    return directions.map((direction) => {
      const partition = {
        sector_agent_id: agentId,
        direction_id: direction.directionId,
        included_classification_codes: direction.included.map((item) => item.code),
        excluded_classification_codes:
          "excluded" in direction ? (direction.excluded ?? []).map((item) => item.code) : [],
      };
      const content = {
        ...partition,
        direction_contract_version: SECTOR_DIRECTION_REGISTRY_VERSION,
        direction_partition_definition_hash: canonicalHash(partition),
        direction_return_benchmark_contract_id: `direction-return:${agentId}:${direction.directionId}`,
        parent_sector_benchmark_contract_id: `parent-sector:${agentId}`,
        single_direction_null_benchmark_contract_id:
          directions.length === 1 ? `single-null:${agentId}` : null,
        candidate_eligibility_contract_version: "sector_candidate_eligibility_v1",
        membership_query_plan_id: plan.query_plan_id,
        membership_query_plan_hash: plan.query_plan_hash,
      };
      return { ...content, direction_contract_hash: canonicalHash(content) };
    });
  });
  const base = {
    schema_version: SECTOR_UNIVERSE_MANIFEST_VERSION,
    sector_count: 9,
    direction_count: directionContracts.length,
    metric_count: SECTOR_DIRECTION_METRIC_REGISTRY.length,
    taxonomy_provider: "SW2021",
    taxonomy_structure_hash: canonicalHash(
      uniqueCodes(
        Object.values(SECTOR_DIRECTION_REGISTRY).flatMap((entry) => [
          ...entry.universe,
          ...entry.directions.flatMap((direction) => direction.included),
        ]),
      ),
    ),
    direction_registry_version: SECTOR_DIRECTION_REGISTRY_VERSION,
    direction_metric_registry_version: SECTOR_METRIC_REGISTRY_VERSION,
    direction_metric_registry_hash: canonicalHash(SECTOR_DIRECTION_METRIC_REGISTRY),
    direction_metric_registry: SECTOR_DIRECTION_METRIC_REGISTRY,
    overlap_precedence: SECTOR_OVERLAP_PRECEDENCE,
    membership_query_plans: membershipQueryPlans,
    direction_contracts: directionContracts,
    direction_comparison_contract: SECTOR_DIRECTION_COMPARISON_CONTRACT,
    security_scoring_contract: SECTOR_SECURITY_SCORING_CONTRACT,
    flow_coverage_contract: SECTOR_FLOW_COVERAGE_CONTRACT,
  };
  return { ...base, manifest_hash: canonicalHash(base) };
}

const Sha256 = z.string().regex(/^sha256:[0-9a-f]{64}$/);
const MembershipBranchSchema = z
  .object({
    endpoint: z.literal("index_member_all"),
    parameter: z.enum(["l1_code", "l2_code", "l3_code"]),
    classification_code: z.string().regex(/^801\d{3}\.SI$/),
    is_new: z.enum(["Y", "N"]),
  })
  .strict();

export const SectorUniverseManifestSchema = z
  .object({
    schema_version: z.literal("sector_universe_manifest_v1"),
    sector_count: z.literal(9),
    direction_count: z.literal(37),
    metric_count: z.literal(26),
    taxonomy_provider: z.literal("SW2021"),
    taxonomy_structure_hash: Sha256,
    direction_registry_version: z.literal("sector_direction_registry_v3"),
    direction_metric_registry_version: z.literal("sector_direction_metric_registry_v1"),
    direction_metric_registry_hash: Sha256,
    direction_metric_registry: z
      .array(z.looseObject({ metric_id: z.string(), metric_contract_hash: Sha256 }))
      .length(26),
    overlap_precedence: z.array(z.string()).length(9),
    membership_query_plans: z
      .array(
        z
          .object({
            query_plan_id: z.string().min(1),
            query_plan_version: z.literal("sector_membership_query_v1"),
            sector_agent_id: z.string().min(1),
            branches: z.array(MembershipBranchSchema).min(2),
            merge_key: z.array(z.string()).length(6),
            post_filter_excluded_codes: z.array(z.string()),
            query_plan_hash: Sha256,
          })
          .strict(),
      )
      .length(9),
    direction_contracts: z
      .array(
        z.looseObject({
          sector_agent_id: z.string().min(1),
          direction_id: z.string().min(1),
          direction_contract_hash: Sha256,
          direction_partition_definition_hash: Sha256,
          membership_query_plan_hash: Sha256,
        }),
      )
      .length(37),
    direction_comparison_contract: z.looseObject({
      comparison_contract_hash: Sha256,
      core_vote_weight: z.literal(1),
      optional_etf_vote_weight: z.literal(0.5),
      minimum_base_support_count: z.literal(2),
      minimum_weighted_support_margin: z.literal(1),
      maximum_conflict_review_rounds: z.literal(1),
    }),
    security_scoring_contract: z.looseObject({
      scoring_contract_hash: Sha256,
      shortlist_maximum_size_per_direction: z.literal(50),
      maximum_picks_per_side: z.literal(5),
      conviction_budget_per_side: z.literal(1),
    }),
    flow_coverage_contract: z.looseObject({
      contract_hash: Sha256,
      source_endpoint: z.literal("moneyflow"),
      source_net_flow_field: z.literal("net_mf_amount"),
      minimum_coverage_ratio: z.literal(0.9),
      ths_industry_flow_usage: z.literal("OPTIONAL_DIAGNOSTIC_ONLY"),
    }),
    manifest_hash: Sha256,
  })
  .strict();

function uniqueCodes(values: readonly ClassificationCode[]): ClassificationCode[] {
  return [...new Map(values.map((value) => [`${value.level}:${value.code}`, value])).values()].sort(
    (left, right) => `${left.level}:${left.code}`.localeCompare(`${right.level}:${right.code}`),
  );
}

function freezeContract<T extends Record<string, unknown>>(value: T): T & Record<string, string> {
  const hashKey =
    Object.keys(value)
      .find((key) => key.endsWith("_id"))
      ?.replace(/_id$/, "_hash") ?? "contract_hash";
  return { ...value, [hashKey]: canonicalHash(value) } as T & Record<string, string>;
}

function canonicalHash(value: unknown): string {
  return `sha256:${createHash("sha256")
    .update(JSON.stringify(canonicalize(value)))
    .digest("hex")}`;
}

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, entry]) => [key, canonicalize(entry)]),
    );
  }
  return value;
}
