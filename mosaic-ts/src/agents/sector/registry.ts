import { z } from "zod";
import { canonicalJsonHash } from "../helpers/canonical_json.js";
import type { StandardSectorAgentId } from "../types.js";

export const SECTOR_UNIVERSE_MANIFEST_VERSION = "sector_universe_manifest_v1";
export const SECTOR_DIRECTION_REGISTRY_VERSION = "sector_direction_registry_v4";
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
  directions: readonly [
    DirectionDefinition,
    DirectionDefinition,
    DirectionDefinition,
    ...DirectionDefinition[],
  ];
}

const code = (level: ClassificationLevel, value: string): ClassificationCode => ({
  level,
  code: value,
});
const l1 = (value: string): ClassificationCode => code("l1_code", value);
const l2 = (value: string): ClassificationCode => code("l2_code", value);
const l3 = (value: string): ClassificationCode => code("l3_code", value);

export const SECTOR_DIRECTION_REGISTRY = deepFreeze({
  semiconductor: {
    universe: [
      l3("850812.SI"),
      l3("850813.SI"),
      l3("850814.SI"),
      l3("850815.SI"),
      l3("850816.SI"),
      l3("850817.SI"),
      l3("850818.SI"),
    ],
    directions: [
      {
        directionId: "chip_design",
        included: [l3("850814.SI"), l3("850815.SI")],
      },
      {
        directionId: "wafer_manufacturing_packaging",
        included: [l3("850816.SI"), l3("850817.SI")],
      },
      {
        directionId: "semiconductor_equipment_materials",
        included: [l3("850813.SI"), l3("850818.SI")],
      },
      { directionId: "discrete_devices", included: [l3("850812.SI")] },
    ],
  },
  technology: {
    universe: [
      l2("801082.SI"),
      l2("801083.SI"),
      l2("801084.SI"),
      l2("801085.SI"),
      l2("801086.SI"),
      l1("801750.SI"),
      l1("801760.SI"),
      l1("801770.SI"),
    ],
    directions: [
      {
        directionId: "electronics_non_semiconductor",
        included: [
          l2("801082.SI"),
          l2("801083.SI"),
          l2("801084.SI"),
          l2("801085.SI"),
          l2("801086.SI"),
        ],
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
    universe: [
      l2("801151.SI"),
      l2("801155.SI"),
      l2("801152.SI"),
      l2("801154.SI"),
      l2("801153.SI"),
      l2("801156.SI"),
    ],
    directions: [
      { directionId: "chemical_pharmaceuticals", included: [l2("801151.SI")] },
      { directionId: "traditional_chinese_medicine", included: [l2("801155.SI")] },
      { directionId: "biological_products", included: [l2("801152.SI")] },
      { directionId: "pharmaceutical_commerce", included: [l2("801154.SI")] },
      { directionId: "medical_devices", included: [l2("801153.SI")] },
      { directionId: "medical_services", included: [l2("801156.SI")] },
    ],
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
    universe: [
      l2("801782.SI"),
      l2("801783.SI"),
      l2("801784.SI"),
      l2("801785.SI"),
      l2("801786.SI"),
      l2("801193.SI"),
      l2("801194.SI"),
      l2("801191.SI"),
    ],
    directions: [
      {
        directionId: "banking",
        included: [
          l2("801782.SI"),
          l2("801783.SI"),
          l2("801784.SI"),
          l2("801785.SI"),
          l2("801786.SI"),
        ],
      },
      { directionId: "securities", included: [l2("801193.SI")] },
      { directionId: "insurance", included: [l2("801194.SI")] },
      { directionId: "diversified_financials", included: [l2("801191.SI")] },
    ],
  },
  agriculture: {
    universe: [
      l2("801016.SI"),
      l2("801017.SI"),
      l2("801015.SI"),
      l2("801014.SI"),
      l2("801018.SI"),
      l2("801011.SI"),
      l2("801012.SI"),
      l2("801019.SI"),
    ],
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
} as const satisfies Readonly<Record<StandardSectorAgentId, SectorRegistryEntry>>);

validateDirectionPartitions(SECTOR_DIRECTION_REGISTRY);

export const SECTOR_DIRECTION_REGISTRY_HASH = canonicalHash(SECTOR_DIRECTION_REGISTRY);

export const SECTOR_OVERLAP_PRECEDENCE = deepFreeze([
  "semiconductor",
  "technology",
  "energy",
  "biotech",
  "consumer",
  "industrials",
  "real_estate_construction",
  "financials",
  "agriculture",
] as const satisfies readonly StandardSectorAgentId[]);

export function sectorDirectionIds(
  agentId: StandardSectorAgentId,
): readonly [string, string, string, ...string[]] {
  return SECTOR_DIRECTION_REGISTRY[agentId].directions.map(
    (direction) => direction.directionId,
  ) as [string, string, string, ...string[]];
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

export const SECTOR_DIRECTION_METRIC_REGISTRY = deepFreeze([
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
] as const);

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
  comparison_contract_id: "sector_direction_comparison_v3",
  comparison_contract_version: "sector_direction_comparison_v3",
  core_criteria: ["FUNDAMENTALS", "VALUATION", "BASKET_TECHNICALS", "RISK_ASYMMETRY"],
  coverage_gated_criteria: ["MACRO_EVENT_FIT", "CATALYSTS"],
  optional_etf_criteria: ["ETF_PRICE_CONFIRMATION", "ETF_SHARE_FLOW_CONFIRMATION"],
  pair_coverage: "ALL_ELIGIBLE_UNORDERED_PAIRS",
  reducer: "UNIQUE_CONDORCET_WINNER_AND_LOSER_THEN_SINGLE_CONFLICT_REVIEW_ELSE_REJECT",
  core_vote_weight: 1,
  available_coverage_gated_vote_weight: 1,
  optional_etf_vote_weight: 0.5,
  minimum_base_support_count: 2,
  minimum_weighted_support_margin: 1,
  maximum_conflict_review_rounds: 1,
  coverage_binding: "EXACT_RUNTIME_ROLE_EVENT_DIRECTIVE",
});

export const SECTOR_DIRECTION_CONFLICT_RESOLVER_CONTRACT = freezeContract({
  resolver_contract_id: "sector_direction_conflict_resolver",
  resolver_contract_version: "sector_direction_conflict_resolver_v1",
  conflict_set_rule:
    "IF_UNIQUE_CONDORCET_WINNER_AND_LOSER_THEN_EMPTY_ELSE_SORTED_UNION_OF_CYCLE_NO_EDGE_AND_NONUNIQUE_EXTREME_COPELAND_TIES",
  review_scope_rule: "EXACT_COMPLETE_PAIRWISE_MATRIX_OVER_FROZEN_CONFLICT_SET",
  review_round_limit: 1,
  recomputation_rule: "REPLACE_CONFLICT_INTERNAL_PAIRS_THEN_REDUCE_COMPLETE_MATRIX",
  acceptance_rule: "UNIQUE_CONDORCET_WINNER_AND_UNIQUE_CONDORCET_LOSER",
  unresolved_rule: "REJECT_STAGE_AFTER_SINGLE_REVIEW",
});

export const SECTOR_SECURITY_SCORING_CONTRACT = freezeContract({
  scoring_contract_id: "sector_security_scoring_v2",
  scoring_contract_version: "sector_security_scoring_v2",
  candidate_source: "PIT_DIRECTION_ELIGIBLE_SECURITY_SCORE_ROWS",
  scoring_features: [
    "ADJUSTED_RETURN_20D",
    "REALIZED_VOLATILITY_20D",
    "MEDIAN_AMOUNT_20D_CNY",
    "NET_MONEYFLOW_20D_CNY",
  ],
  required_source_endpoints: ["daily", "adj_factor", "moneyflow"],
  required_observation_count: 20,
  required_adjusted_close_observation_count: 21,
  minimum_coverage_ratio: 1,
  adjusted_return_formula: "LATEST_ADJUSTED_CLOSE_DIV_LAG_20_ADJUSTED_CLOSE_MINUS_ONE",
  realized_volatility_formula: "SAMPLE_STDDEV_OF_20_ADJUSTED_SIMPLE_RETURNS_ANNUALIZED_SQRT_252",
  median_amount_formula: "MEDIAN_LATEST_20_DAILY_AMOUNT_TIMES_1000_CNY",
  net_moneyflow_formula: "SUM_LATEST_20_NET_MF_AMOUNT_TIMES_10000_CNY",
  availability_rule: "ALL_20_RETURN_INTERVALS_HAVE_DAILY_ADJ_FACTOR_AND_MONEYFLOW",
  shortlist_order: "MEDIAN_AMOUNT_20D_CNY_DESC_THEN_TS_CODE_ASC",
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
    const entry: SectorRegistryEntry = SECTOR_DIRECTION_REGISTRY[agentId];
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
    const directions: SectorRegistryEntry["directions"] =
      SECTOR_DIRECTION_REGISTRY[agentId].directions;
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
    direction_conflict_resolver_contract: SECTOR_DIRECTION_CONFLICT_RESOLVER_CONTRACT,
    security_scoring_contract: SECTOR_SECURITY_SCORING_CONTRACT,
    flow_coverage_contract: SECTOR_FLOW_COVERAGE_CONTRACT,
  };
  return { ...base, manifest_hash: canonicalHash(base) };
}

const Sha256 = z.string().regex(/^sha256:[0-9a-f]{64}$/);
const SectorAgentIdSchema = z.enum(SECTOR_OVERLAP_PRECEDENCE);
const ClassificationCodeSchema = z.string().regex(/^(?:801|850)\d{3}\.SI$/);
const MembershipBranchSchema = z.discriminatedUnion("parameter", [
  z
    .object({
      endpoint: z.literal("index_member_all"),
      parameter: z.literal("l1_code"),
      classification_code: z.string().regex(/^801\d{3}\.SI$/),
      is_new: z.enum(["Y", "N"]),
    })
    .strict(),
  z
    .object({
      endpoint: z.literal("index_member_all"),
      parameter: z.literal("l2_code"),
      classification_code: z.string().regex(/^801\d{3}\.SI$/),
      is_new: z.enum(["Y", "N"]),
    })
    .strict(),
  z
    .object({
      endpoint: z.literal("index_member_all"),
      parameter: z.literal("l3_code"),
      classification_code: z.string().regex(/^850\d{3}\.SI$/),
      is_new: z.enum(["Y", "N"]),
    })
    .strict(),
]);

const MetricContractSchema = z
  .object({
    metric_id: z.string().min(1),
    metric_contract_version: z.literal("v1"),
    metric_family: z.enum([
      "FUNDAMENTALS",
      "VALUATION",
      "BASKET_PRICE_TREND",
      "BASKET_BREADTH",
      "BASKET_TURNOVER_FLOW",
      "ETF_CONFIRMATION",
    ]),
    formula_id: z.string().min(1),
    formula_version: z.literal("v1"),
    unit: z.enum(["RATIO", "PERCENT", "CNY", "RETURN", "VOLATILITY"]),
    lookback: z
      .object({
        kind: z.enum(["TRADING_DAYS", "REPORTED_QUARTERS", "POINT_IN_TIME"]),
        value: z.number().int().positive(),
      })
      .strict(),
    required_for_direction_readiness: z.boolean(),
    minimum_observations: z.number().int().positive(),
    minimum_coverage_ratio: z.number().min(0).max(1),
    basket_weighting: z.enum(["PIT_EQUAL_WEIGHT", "LAGGED_20D_MEDIAN_AMOUNT"]),
    benchmark_role: z.enum(["NONE", "PARENT_SECTOR_BENCHMARK", "DIRECTION_BASKET"]),
    adjustment_contract_version: z.literal("pit_total_return_adjustment_v1"),
    percentile_lookback_trading_days: z.literal(252),
    percentile_method: z.literal("EMPIRICAL_CDF_AVERAGE_TIE"),
    change_lookback_trading_days: z.literal(20),
    metric_contract_hash: Sha256,
  })
  .strict();

const MembershipQueryPlanSchema = z
  .object({
    query_plan_id: z.string().regex(/^sector-membership:[a-z_]+$/),
    query_plan_version: z.literal("sector_membership_query_v1"),
    sector_agent_id: SectorAgentIdSchema,
    branches: z.array(MembershipBranchSchema).min(2),
    merge_key: z
      .array(z.enum(["l1_code", "l2_code", "l3_code", "ts_code", "in_date", "out_date"]))
      .length(6),
    post_filter_excluded_codes: z.array(ClassificationCodeSchema),
    query_plan_hash: Sha256,
  })
  .strict();

const DirectionContractSchema = z
  .object({
    sector_agent_id: SectorAgentIdSchema,
    direction_id: z.string().regex(/^[a-z][a-z0-9_]*$/),
    included_classification_codes: z.array(ClassificationCodeSchema).min(1),
    excluded_classification_codes: z.array(ClassificationCodeSchema),
    direction_contract_version: z.literal("sector_direction_registry_v4"),
    direction_partition_definition_hash: Sha256,
    direction_return_benchmark_contract_id: z
      .string()
      .regex(/^direction-return:[a-z_]+:[a-z0-9_]+$/),
    parent_sector_benchmark_contract_id: z.string().regex(/^parent-sector:[a-z_]+$/),
    candidate_eligibility_contract_version: z.literal("sector_candidate_eligibility_v1"),
    membership_query_plan_id: z.string().regex(/^sector-membership:[a-z_]+$/),
    membership_query_plan_hash: Sha256,
    direction_contract_hash: Sha256,
  })
  .strict();

const DirectionComparisonContractSchema = z
  .object({
    comparison_contract_id: z.literal("sector_direction_comparison_v3"),
    comparison_contract_version: z.literal("sector_direction_comparison_v3"),
    core_criteria: z
      .array(z.enum(["FUNDAMENTALS", "VALUATION", "BASKET_TECHNICALS", "RISK_ASYMMETRY"]))
      .length(4),
    coverage_gated_criteria: z.array(z.enum(["MACRO_EVENT_FIT", "CATALYSTS"])).length(2),
    optional_etf_criteria: z
      .array(z.enum(["ETF_PRICE_CONFIRMATION", "ETF_SHARE_FLOW_CONFIRMATION"]))
      .length(2),
    pair_coverage: z.literal("ALL_ELIGIBLE_UNORDERED_PAIRS"),
    reducer: z.literal("UNIQUE_CONDORCET_WINNER_AND_LOSER_THEN_SINGLE_CONFLICT_REVIEW_ELSE_REJECT"),
    core_vote_weight: z.literal(1),
    available_coverage_gated_vote_weight: z.literal(1),
    optional_etf_vote_weight: z.literal(0.5),
    minimum_base_support_count: z.literal(2),
    minimum_weighted_support_margin: z.literal(1),
    maximum_conflict_review_rounds: z.literal(1),
    coverage_binding: z.literal("EXACT_RUNTIME_ROLE_EVENT_DIRECTIVE"),
    comparison_contract_hash: Sha256,
  })
  .strict();

const DirectionConflictResolverContractSchema = z
  .object({
    resolver_contract_id: z.literal("sector_direction_conflict_resolver"),
    resolver_contract_version: z.literal("sector_direction_conflict_resolver_v1"),
    conflict_set_rule: z.literal(
      "IF_UNIQUE_CONDORCET_WINNER_AND_LOSER_THEN_EMPTY_ELSE_SORTED_UNION_OF_CYCLE_NO_EDGE_AND_NONUNIQUE_EXTREME_COPELAND_TIES",
    ),
    review_scope_rule: z.literal("EXACT_COMPLETE_PAIRWISE_MATRIX_OVER_FROZEN_CONFLICT_SET"),
    review_round_limit: z.literal(1),
    recomputation_rule: z.literal("REPLACE_CONFLICT_INTERNAL_PAIRS_THEN_REDUCE_COMPLETE_MATRIX"),
    acceptance_rule: z.literal("UNIQUE_CONDORCET_WINNER_AND_UNIQUE_CONDORCET_LOSER"),
    unresolved_rule: z.literal("REJECT_STAGE_AFTER_SINGLE_REVIEW"),
    resolver_contract_hash: Sha256,
  })
  .strict();

const SecurityScoringContractSchema = z
  .object({
    scoring_contract_id: z.literal("sector_security_scoring_v2"),
    scoring_contract_version: z.literal("sector_security_scoring_v2"),
    candidate_source: z.literal("PIT_DIRECTION_ELIGIBLE_SECURITY_SCORE_ROWS"),
    scoring_features: z
      .array(
        z.enum([
          "ADJUSTED_RETURN_20D",
          "REALIZED_VOLATILITY_20D",
          "MEDIAN_AMOUNT_20D_CNY",
          "NET_MONEYFLOW_20D_CNY",
        ]),
      )
      .length(4),
    required_source_endpoints: z.array(z.enum(["daily", "adj_factor", "moneyflow"])).length(3),
    required_observation_count: z.literal(20),
    required_adjusted_close_observation_count: z.literal(21),
    minimum_coverage_ratio: z.literal(1),
    adjusted_return_formula: z.literal("LATEST_ADJUSTED_CLOSE_DIV_LAG_20_ADJUSTED_CLOSE_MINUS_ONE"),
    realized_volatility_formula: z.literal(
      "SAMPLE_STDDEV_OF_20_ADJUSTED_SIMPLE_RETURNS_ANNUALIZED_SQRT_252",
    ),
    median_amount_formula: z.literal("MEDIAN_LATEST_20_DAILY_AMOUNT_TIMES_1000_CNY"),
    net_moneyflow_formula: z.literal("SUM_LATEST_20_NET_MF_AMOUNT_TIMES_10000_CNY"),
    availability_rule: z.literal("ALL_20_RETURN_INTERVALS_HAVE_DAILY_ADJ_FACTOR_AND_MONEYFLOW"),
    shortlist_order: z.literal("MEDIAN_AMOUNT_20D_CNY_DESC_THEN_TS_CODE_ASC"),
    shortlist_maximum_size_per_direction: z.literal(50),
    model_pick_domain: z.literal("EXACT_FROZEN_SCORING_SHORTLIST"),
    maximum_picks_per_side: z.literal(5),
    duplicate_ticker_policy: z.literal("REJECT_ACROSS_WHOLE_SUBMISSION"),
    conviction_lower_bound_exclusive: z.literal(0),
    conviction_upper_bound_inclusive: z.literal(1),
    conviction_budget_per_side: z.literal(1),
    scoring_contract_hash: Sha256,
  })
  .strict();

const FlowCoverageContractSchema = z
  .object({
    contract_id: z.literal("sector_constituent_flow_v1"),
    contract_version: z.literal("sector_flow_coverage_v1"),
    source_endpoint: z.literal("moneyflow"),
    source_net_flow_field: z.literal("net_mf_amount"),
    denominator: z.literal("FROZEN_CANDIDATE_20D_MEDIAN_TURNOVER"),
    minimum_coverage_ratio: z.literal(0.9),
    coverage_weighting: z.literal("PIT_CONSTITUENT_20D_MEDIAN_TURNOVER"),
    aggregation: z.literal("OBSERVED_CONSTITUENT_NET_FLOW_PER_OBSERVED_MEDIAN_TURNOVER"),
    ths_industry_flow_usage: z.literal("OPTIONAL_DIAGNOSTIC_ONLY"),
    contract_hash: Sha256,
  })
  .strict();

const SectorUniverseManifestStructuralSchema = z
  .object({
    schema_version: z.literal("sector_universe_manifest_v1"),
    sector_count: z.literal(9),
    direction_count: z.literal(47),
    metric_count: z.literal(26),
    taxonomy_provider: z.literal("SW2021"),
    taxonomy_structure_hash: Sha256,
    direction_registry_version: z.literal("sector_direction_registry_v4"),
    direction_metric_registry_version: z.literal("sector_direction_metric_registry_v1"),
    direction_metric_registry_hash: Sha256,
    direction_metric_registry: z.array(MetricContractSchema).length(26),
    overlap_precedence: z.array(SectorAgentIdSchema).length(9),
    membership_query_plans: z.array(MembershipQueryPlanSchema).length(9),
    direction_contracts: z.array(DirectionContractSchema).length(47),
    direction_comparison_contract: DirectionComparisonContractSchema,
    direction_conflict_resolver_contract: DirectionConflictResolverContractSchema,
    security_scoring_contract: SecurityScoringContractSchema,
    flow_coverage_contract: FlowCoverageContractSchema,
    manifest_hash: Sha256,
  })
  .strict();

export const SectorUniverseManifestSchema = SectorUniverseManifestStructuralSchema.superRefine(
  (value, context) => {
    if (canonicalHash(value) === canonicalHash(buildSectorUniverseManifest())) return;
    context.addIssue({
      code: "custom",
      message: "Sector universe manifest must exactly match the generated contract source",
    });
  },
);

function uniqueCodes(values: readonly ClassificationCode[]): ClassificationCode[] {
  return [...new Map(values.map((value) => [`${value.level}:${value.code}`, value])).values()].sort(
    (left, right) => `${left.level}:${left.code}`.localeCompare(`${right.level}:${right.code}`),
  );
}

function validateDirectionPartitions(
  registry: Readonly<Record<StandardSectorAgentId, SectorRegistryEntry>>,
): void {
  const globallyOwned = new Map<string, StandardSectorAgentId>();
  for (const [agentId, entry] of Object.entries(registry) as Array<
    [StandardSectorAgentId, SectorRegistryEntry]
  >) {
    if (entry.directions.length < 3) {
      throw new Error(`${agentId}: every standard Sector role requires at least three directions`);
    }
    const universeKeys = new Set(entry.universe.map(classificationKey));
    if (universeKeys.size !== entry.universe.length || universeKeys.size === 0) {
      throw new Error(`${agentId}: parent universe codes must be non-empty and unique`);
    }
    const directionIds = new Set<string>();
    const partitionOwners = new Map<string, string>();
    for (const direction of entry.directions) {
      if (!direction.directionId || directionIds.has(direction.directionId)) {
        throw new Error(`${agentId}: direction ids must be non-empty and unique`);
      }
      directionIds.add(direction.directionId);
      if (direction.included.length === 0) {
        throw new Error(`${agentId}/${direction.directionId}: partition cannot be empty`);
      }
      for (const classification of direction.included) {
        const key = classificationKey(classification);
        const priorDirection = partitionOwners.get(key);
        if (priorDirection) {
          throw new Error(
            `${agentId}: ${key} overlaps ${priorDirection} and ${direction.directionId}`,
          );
        }
        partitionOwners.set(key, direction.directionId);
      }
      for (const classification of direction.excluded ?? []) {
        if (!direction.included.some((included) => included.level === classification.level)) {
          throw new Error(
            `${agentId}/${direction.directionId}: exclusions require a same-level parent code`,
          );
        }
      }
    }
    const partitionKeys = new Set(partitionOwners.keys());
    if (
      partitionKeys.size !== universeKeys.size ||
      [...universeKeys].some((key) => !partitionKeys.has(key))
    ) {
      throw new Error(`${agentId}: directions must fully partition the frozen parent universe`);
    }
    for (const key of universeKeys) {
      const priorAgent = globallyOwned.get(key);
      if (priorAgent) throw new Error(`${key} is owned by both ${priorAgent} and ${agentId}`);
      globallyOwned.set(key, agentId);
    }
  }
}

function classificationKey(value: ClassificationCode): string {
  return `${value.level}:${value.code}`;
}

function freezeContract<T extends Record<string, unknown>>(value: T): T & Record<string, string> {
  const hashKey =
    Object.keys(value)
      .find((key) => key.endsWith("_id"))
      ?.replace(/_id$/, "_hash") ?? "contract_hash";
  return deepFreeze({ ...value, [hashKey]: canonicalHash(value) }) as T & Record<string, string>;
}

function deepFreeze<T>(value: T): T {
  if (value !== null && typeof value === "object" && !Object.isFrozen(value)) {
    for (const nested of Object.values(value)) deepFreeze(nested);
    Object.freeze(value);
  }
  return value;
}

function canonicalHash(value: unknown): string {
  return canonicalJsonHash(value);
}
