import { createHash } from "node:crypto";
import { z } from "zod";
import {
  MACRO_COMPONENT_WEIGHT_CONTRACT_VERSION,
  MACRO_ROLE_CONTRACTS,
} from "../agents/macro/_contracts.js";
import { ALL_AGENTS } from "../agents/prompts/cohorts.js";

export const DarwinApplicationModeSchema = z.enum(["DOWNSTREAM_USAGE_WEIGHT", "EVOLUTION_ONLY"]);
export type DarwinApplicationMode = z.infer<typeof DarwinApplicationModeSchema>;

export const OutcomeMetricFamilySchema = z.enum([
  "MACRO_TRANSMISSION",
  "STANDARD_SECTOR",
  "RELATIONSHIP",
  "SUPERINVESTOR",
  "CRO",
  "ALPHA",
  "EXECUTION",
  "CIO",
]);

export const OutcomeScheduleSchema = z.discriminatedUnion("kind", [
  z
    .object({
      kind: z.literal("FIXED_NON_OVERLAP"),
      trading_calendar_id: z.string().min(1),
      epoch: z.string().date(),
      step_trading_days: z.number().int().positive(),
    })
    .strict(),
  z
    .object({
      kind: z.literal("EVENT_TRIGGERED"),
      trading_calendar_id: z.string().min(1),
      event_registry_version: z.string().min(1),
      event_priority_version: z.string().min(1),
    })
    .strict(),
]);

const FiniteNumber = z.number().finite();
const Probability = FiniteNumber.min(0).max(1);
const NonNegativeFinite = FiniteNumber.min(0);
const PositiveFinite = FiniteNumber.positive();
const Sha256 = z.string().regex(/^sha256:[0-9a-f]{64}$/);
const NonEmptyId = z.string().trim().min(1);

export const COMPONENT_CALIBRATION_CONTRACT = Object.freeze({
  calibration_contract_version: "macro_component_calibration_v1",
  calibration_solver_version: "bounded_grid_001_half_up_v1",
  reference_cohort_id: "cohort_default",
  reference_language: "zh",
  maximum_lookback_trading_days: 1260,
  semiannual_slot_months: [6, 12],
  regularization_lambda: 1,
  component_weight_lower_bound: 0.15,
  component_weight_upper_bound: 0.35,
  maximum_component_delta: 0.05,
  solver_grid_step: 0.01,
  minimum_fit_samples: 60,
  minimum_production_samples: 100,
  minimum_rolling_folds: 5,
  minimum_validation_samples_per_fold: 12,
  purge_trading_days: 5,
  embargo_trading_days: 5,
  minimum_shadow_samples: 20,
  maximum_runs_per_half_year: 1,
  minimum_oos_mse_improvement_ratio: 0.05,
  maximum_regime_mse_degradation_ratio: 0.05,
  minimum_regime_validation_samples: 20,
  minimum_fold_adjustment_agreement_ratio: 0.75,
  maximum_bound_hit_fold_ratio: 0.5,
  minimum_diagnostic_paired_samples: 60,
  maximum_diagnostic_mse_degradation_ratio: 0.05,
} as const);

const ComponentCalibrationContractSchema = z
  .object({
    calibration_contract_version: z.string().min(1),
    calibration_solver_version: z.string().min(1),
    reference_cohort_id: z.string().min(1),
    reference_language: z.literal("zh"),
    maximum_lookback_trading_days: z.literal(1260),
    semiannual_slot_months: z.tuple([z.literal(6), z.literal(12)]),
    regularization_lambda: z.literal(1),
    component_weight_lower_bound: z.literal(0.15),
    component_weight_upper_bound: z.literal(0.35),
    maximum_component_delta: z.literal(0.05),
    solver_grid_step: z.literal(0.01),
    minimum_fit_samples: z.literal(60),
    minimum_production_samples: z.literal(100),
    minimum_rolling_folds: z.literal(5),
    minimum_validation_samples_per_fold: z.literal(12),
    purge_trading_days: z.literal(5),
    embargo_trading_days: z.literal(5),
    minimum_shadow_samples: z.literal(20),
    maximum_runs_per_half_year: z.literal(1),
    minimum_oos_mse_improvement_ratio: z.literal(0.05),
    maximum_regime_mse_degradation_ratio: z.literal(0.05),
    minimum_regime_validation_samples: z.literal(20),
    minimum_fold_adjustment_agreement_ratio: z.literal(0.75),
    maximum_bound_hit_fold_ratio: z.literal(0.5),
    minimum_diagnostic_paired_samples: z.literal(60),
    maximum_diagnostic_mse_degradation_ratio: z.literal(0.05),
  })
  .strict();

export const MacroTransmissionOutcomeRawMetricsSchema = z
  .object({
    direction_sign: z.union([z.literal(-1), z.literal(0), z.literal(1)]),
    strength: z.union([
      z.literal(0),
      z.literal(1),
      z.literal(2),
      z.literal(3),
      z.literal(4),
      z.literal(5),
    ]),
    confidence: Probability,
    role_path_metric: FiniteNumber,
    pit_volatility_scale: PositiveFinite,
    point_forecast: FiniteNumber.optional(),
    realized_scaled_path: FiniteNumber.min(-1).max(1).optional(),
    forecast_loss: NonNegativeFinite.optional(),
    null_loss: NonNegativeFinite.optional(),
    combined_utility_delta: FiniteNumber.optional(),
  })
  .strict()
  .superRefine((value, ctx) => {
    if ((value.direction_sign === 0) !== (value.strength === 0)) {
      ctx.addIssue({
        code: "custom",
        path: ["strength"],
        message: "neutral direction and zero strength must coincide",
      });
    }
  });

const StandardSectorDirectionOutcomeMetricSchema = z
  .object({
    direction_id: NonEmptyId,
    realized_return_5d: FiniteNumber,
    parent_sector_return_5d: FiniteNumber,
    realized_scaled_path: FiniteNumber.min(-1).max(1),
    predicted_tilt: FiniteNumber.min(-1).max(1),
    selected_role: z.enum(["PREFERRED", "LEAST_PREFERRED", "UNSELECTED"]),
  })
  .strict();

const StandardSectorSecurityOutcomeMetricSchema = z
  .object({
    side: z.enum(["PREFERRED", "LEAST_PREFERRED"]),
    direction_id: NonEmptyId,
    ts_code: NonEmptyId,
    action: z.enum(["LONG", "SHORT", "AVOID", "UNSELECTED"]),
    conviction: Probability,
    net_alpha_5d: FiniteNumber,
    realized_scaled_alpha: FiniteNumber.min(-1).max(1),
    predicted_position: FiniteNumber.min(-1).max(1),
  })
  .strict();

const StandardSectorSecurityAbstentionOutcomeMetricSchema = z
  .object({
    side: z.enum(["PREFERRED", "LEAST_PREFERRED"]),
    direction_id: NonEmptyId,
    security_status: z.enum([
      "PICKS_PRESENT",
      "NO_QUALIFIED_SECURITY_EMPTY_SHORTLIST",
      "NO_QUALIFIED_SECURITY_NONEMPTY_SHORTLIST",
    ]),
    shortlist_size: z.number().int().nonnegative(),
    raw_opportunity_utility: FiniteNumber.nullable(),
    cardinality_adjusted_opportunity_utility: FiniteNumber.nullable(),
    abstention_warranted_label: z.union([z.literal(0), z.literal(1)]).nullable(),
    abstention_forecast_probability: Probability.nullable(),
    abstention_null_probability: Probability.nullable(),
    abstention_forecast_loss: NonNegativeFinite.nullable(),
    abstention_null_loss: NonNegativeFinite.nullable(),
    missed_opportunity_regret: NonNegativeFinite.nullable(),
    side_security_utility_delta: FiniteNumber,
    abstention_base_rate_record_id: NonEmptyId.nullable(),
    abstention_base_rate_record_hash: Sha256.nullable(),
    opportunity_search_calibration_id: NonEmptyId.nullable(),
    opportunity_search_calibration_hash: Sha256.nullable(),
  })
  .strict()
  .superRefine((value, ctx) => {
    const empty = value.security_status === "NO_QUALIFIED_SECURITY_EMPTY_SHORTLIST";
    const nonemptyAbstention = value.security_status === "NO_QUALIFIED_SECURITY_NONEMPTY_SHORTLIST";
    if (empty !== (value.shortlist_size === 0)) {
      ctx.addIssue({
        code: "custom",
        path: ["shortlist_size"],
        message: "shortlist status mismatch",
      });
    }
    const abstentionFields = [
      value.raw_opportunity_utility,
      value.cardinality_adjusted_opportunity_utility,
      value.abstention_warranted_label,
      value.abstention_forecast_probability,
      value.abstention_null_probability,
      value.abstention_forecast_loss,
      value.abstention_null_loss,
      value.missed_opportunity_regret,
      value.abstention_base_rate_record_id,
      value.abstention_base_rate_record_hash,
      value.opportunity_search_calibration_id,
      value.opportunity_search_calibration_hash,
    ];
    if (nonemptyAbstention && abstentionFields.some((item) => item === null)) {
      ctx.addIssue({
        code: "custom",
        message: "non-empty security abstention requires full proper-loss audit",
      });
    }
    if (!nonemptyAbstention && abstentionFields.some((item) => item !== null)) {
      ctx.addIssue({
        code: "custom",
        message: "non-abstention security branch must not carry abstention audit",
      });
    }
  });

export const StandardSectorOutcomeRawMetricsSchema = z
  .object({
    output_confidence: Probability,
    confidence_semantics: z.enum(["DIRECTIONAL_UTILITY", "ABSTENTION_WARRANTED"]),
    least_preferred_eligibility_status: z.enum(["REQUIRED", "NOT_QUALIFIED", "NOT_APPLICABLE"]),
    direction_metrics: z.array(StandardSectorDirectionOutcomeMetricSchema).min(1),
    security_metrics: z.array(StandardSectorSecurityOutcomeMetricSchema),
    security_abstention_metrics: z.array(StandardSectorSecurityAbstentionOutcomeMetricSchema),
    direction_forecast_loss: NonNegativeFinite,
    direction_null_loss: NonNegativeFinite,
    security_forecast_loss: NonNegativeFinite,
    security_null_loss: NonNegativeFinite,
    direction_utility_delta: FiniteNumber,
    security_utility_delta: FiniteNumber,
    abstention_forecast_loss: NonNegativeFinite.nullable(),
    abstention_null_loss: NonNegativeFinite.nullable(),
    abstention_utility_delta: FiniteNumber.nullable(),
    abstention_warranted_label: z.union([z.literal(0), z.literal(1)]).nullable(),
    abstention_null_probability: Probability.nullable(),
    abstention_base_rate_record_id: NonEmptyId.nullable(),
    abstention_base_rate_record_hash: Sha256.nullable(),
    abstention_missed_opportunity_regret: NonNegativeFinite.nullable(),
    combined_utility_delta: FiniteNumber,
    unit_confidence_utility_delta: FiniteNumber.nullable(),
    abstention_raw_opportunity_utility: FiniteNumber.nullable(),
    abstention_opportunity_utility: FiniteNumber.nullable(),
    abstention_opportunity_search_calibration_id: NonEmptyId.nullable(),
    abstention_opportunity_search_calibration_hash: Sha256.nullable(),
    confidence_calibration_target: z.union([z.literal(0), z.literal(1)]),
  })
  .strict()
  .superRefine((value, ctx) => {
    const abstention = value.confidence_semantics === "ABSTENTION_WARRANTED";
    const branchFields = [
      value.abstention_forecast_loss,
      value.abstention_null_loss,
      value.abstention_utility_delta,
      value.abstention_warranted_label,
      value.abstention_null_probability,
      value.abstention_base_rate_record_id,
      value.abstention_base_rate_record_hash,
      value.abstention_missed_opportunity_regret,
      value.abstention_raw_opportunity_utility,
      value.abstention_opportunity_utility,
      value.abstention_opportunity_search_calibration_id,
      value.abstention_opportunity_search_calibration_hash,
    ];
    if (abstention && branchFields.some((item) => item === null)) {
      ctx.addIssue({
        code: "custom",
        message: "abstention branch requires complete proper-loss fields",
      });
    }
    if (!abstention && branchFields.some((item) => item !== null)) {
      ctx.addIssue({
        code: "custom",
        message: "selected branch cannot carry overall abstention fields",
      });
    }
    if (abstention !== (value.unit_confidence_utility_delta === null)) {
      ctx.addIssue({
        code: "custom",
        path: ["unit_confidence_utility_delta"],
        message: "confidence target branch mismatch",
      });
    }
  });

const RelationshipEdgeOutcomeMetricSchema = z.discriminatedUnion("submitted", [
  z
    .object({
      edge_candidate_id: NonEmptyId,
      materiality_weight: PositiveFinite,
      realized_edge_state: z.enum(["NO_ACTIVATION", "POSITIVE", "NEGATIVE", "MIXED"]),
      matched_non_edge_lift: FiniteNumber,
      candidate_counterfactual_best_utility: FiniteNumber,
      activation_direction_brier_skill: FiniteNumber,
      path_lift_utility_delta: FiniteNumber,
      missed_edge_regret: NonNegativeFinite,
      edge_utility_delta: FiniteNumber,
      submitted: z.literal(true),
      submitted_direction: z.enum(["POSITIVE", "NEGATIVE", "MIXED"]),
      submitted_model_confidence: Probability,
    })
    .strict(),
  z
    .object({
      edge_candidate_id: NonEmptyId,
      materiality_weight: PositiveFinite,
      realized_edge_state: z.enum(["NO_ACTIVATION", "POSITIVE", "NEGATIVE", "MIXED"]),
      matched_non_edge_lift: FiniteNumber,
      candidate_counterfactual_best_utility: FiniteNumber,
      activation_direction_brier_skill: FiniteNumber,
      path_lift_utility_delta: FiniteNumber,
      missed_edge_regret: NonNegativeFinite,
      edge_utility_delta: FiniteNumber,
      submitted: z.literal(false),
      submitted_direction: z.null(),
      submitted_model_confidence: z.literal(0),
    })
    .strict(),
]);

export const RelationshipOutcomeRawMetricsSchema = z
  .object({
    predictive_graph_status: z.enum(["EDGES_PRESENT", "NO_QUALIFIED_PREDICTIVE_EDGE"]),
    edge_metrics: z.array(RelationshipEdgeOutcomeMetricSchema).min(1),
    weighted_edge_utility_delta: FiniteNumber.nullable(),
    graph_abstention_forecast_probability: Probability.nullable(),
    graph_abstention_warranted_label: z.union([z.literal(0), z.literal(1)]).nullable(),
    graph_abstention_forecast_loss: NonNegativeFinite.nullable(),
    graph_abstention_null_loss: NonNegativeFinite.nullable(),
    graph_abstention_best_raw_opportunity_utility: FiniteNumber.nullable(),
    graph_abstention_cardinality_adjusted_utility: FiniteNumber.nullable(),
    graph_abstention_missed_opportunity_regret: NonNegativeFinite.nullable(),
    combined_utility_delta: FiniteNumber,
  })
  .strict()
  .superRefine((value, ctx) => {
    const emptyGraph = value.predictive_graph_status === "NO_QUALIFIED_PREDICTIVE_EDGE";
    const abstentionFields = [
      value.graph_abstention_forecast_probability,
      value.graph_abstention_warranted_label,
      value.graph_abstention_forecast_loss,
      value.graph_abstention_null_loss,
      value.graph_abstention_best_raw_opportunity_utility,
      value.graph_abstention_cardinality_adjusted_utility,
      value.graph_abstention_missed_opportunity_regret,
    ];
    if (
      emptyGraph &&
      (value.weighted_edge_utility_delta !== null || abstentionFields.some((item) => item === null))
    ) {
      ctx.addIssue({
        code: "custom",
        message: "empty graph requires complete abstention metrics only",
      });
    }
    if (
      !emptyGraph &&
      (value.weighted_edge_utility_delta === null || abstentionFields.some((item) => item !== null))
    ) {
      ctx.addIssue({ code: "custom", message: "edge graph requires weighted edge utility only" });
    }
  });

const SuperinvestorPickOutcomeMetricSchema = z
  .object({
    candidate_ref: NonEmptyId,
    ts_code: NonEmptyId,
    selected: z.boolean(),
    side: z.enum(["LONG", "SHORT", "AVOID", "UNSELECTED"]),
    conviction: Probability,
    realized_net_excess_return_21d: FiniteNumber,
    realized_scaled_utility: FiniteNumber.min(-1).max(1),
    downside_path_penalty: NonNegativeFinite,
    pick_utility_delta: FiniteNumber,
    missed_opportunity_utility: NonNegativeFinite,
  })
  .strict();

export const SuperinvestorOutcomeRawMetricsSchema = z
  .object({
    selection_disposition: z.enum(["CANDIDATES", "NO_QUALIFIED_CANDIDATES"]),
    output_confidence: Probability,
    pick_metrics: z.array(SuperinvestorPickOutcomeMetricSchema).min(1),
    selected_pick_utility_delta: FiniteNumber,
    missed_opportunity_utility: NonNegativeFinite,
    output_confidence_forecast_loss: NonNegativeFinite,
    output_confidence_null_loss: NonNegativeFinite,
    combined_utility_delta: FiniteNumber,
  })
  .strict();

const DecisionUtilityComponentIdSchema = z.enum([
  "PRECISION",
  "RECALL",
  "SPECIFICITY",
  "CALIBRATION",
  "SELECTED_PICK_UTILITY",
  "INCREMENTAL_OPPORTUNITY_UTILITY",
  "COST_ERROR",
  "FEASIBILITY",
  "TARGET_DELTA",
  "POLICY_COMPLIANCE",
  "RELATIVE_RETURN",
  "DRAWDOWN",
  "TURNOVER_COST",
  "CONSTRAINT_COMPLIANCE",
]);
const DecisionMetricUnitSchema = z.enum([
  "RATIO",
  "PROBABILITY_LOSS",
  "BASIS_POINTS",
  "PORTFOLIO_WEIGHT",
  "RETURN",
]);
const DecisionZeroRuleSchema = z.enum([
  "NOT_APPLICABLE",
  "ZERO_UTILITY_IF_NO_PREDICTED_POSITIVE",
  "ZERO_UTILITY_IF_NO_ACTUAL_POSITIVE",
  "ONE_IF_NO_ACTUAL_NEGATIVE",
  "EXOGENOUS_EXCLUSION_IF_EMPTY_OBJECT_SET",
]);

function decisionComponent<TId extends z.infer<typeof DecisionUtilityComponentIdSchema>>(
  componentId: TId,
  componentWeight: number,
) {
  return z
    .object({
      component_id: z.literal(componentId),
      component_weight: z.literal(componentWeight),
      unit: DecisionMetricUnitSchema,
      direction: z.enum(["HIGHER_IS_BETTER", "LOWER_IS_BETTER"]),
      unclipped_output_value: FiniteNumber,
      unclipped_null_value: FiniteNumber,
      scale: PositiveFinite,
      output_utility: FiniteNumber,
      null_utility: FiniteNumber,
      utility_delta: FiniteNumber,
      denominator_zero_rule_id: DecisionZeroRuleSchema,
    })
    .strict();
}

const DecisionOutcomeBaseShape = {
  combined_output_utility: FiniteNumber,
  combined_null_utility: FiniteNumber,
  combined_utility_delta: FiniteNumber,
};

const CroCandidateOutcomeMetricSchema = z
  .object({
    candidate_ref: NonEmptyId,
    ts_code: NonEmptyId,
    predicted_action: z.enum([
      "VETO",
      "CAP_WEIGHT",
      "REDUCE_WEIGHT",
      "REQUIRE_REVIEW",
      "NO_OBJECTION",
    ]),
    predicted_risk_probability: Probability,
    predicted_positive: z.boolean(),
    realized_risk_state: z.union([z.literal(0), z.literal(1)]),
    realized_risk_evidence_ids: z.tuple([NonEmptyId], NonEmptyId),
  })
  .strict();

export const CroOutcomeRawMetricsSchema = z
  .object({
    ...DecisionOutcomeBaseShape,
    components: z.tuple([
      decisionComponent("PRECISION", 0.35),
      decisionComponent("RECALL", 0.35),
      decisionComponent("SPECIFICITY", 0.2),
      decisionComponent("CALIBRATION", 0.1),
    ]),
    candidate_metrics: z.tuple([CroCandidateOutcomeMetricSchema], CroCandidateOutcomeMetricSchema),
    true_positive_count: z.number().int().nonnegative(),
    false_positive_count: z.number().int().nonnegative(),
    true_negative_count: z.number().int().nonnegative(),
    false_negative_count: z.number().int().nonnegative(),
    precision: Probability,
    recall: Probability,
    specificity: Probability,
    forecast_brier_loss: NonNegativeFinite,
    null_brier_loss: NonNegativeFinite,
    precision_denominator_zero: z.boolean(),
    recall_denominator_zero: z.boolean(),
    specificity_denominator_zero: z.boolean(),
  })
  .strict();

const AlphaCandidateOutcomeMetricSchema = z
  .object({
    candidate_ref: NonEmptyId,
    ts_code: NonEmptyId,
    selected: z.boolean(),
    submitted_conviction: Probability,
    realized_net_excess_return_5d: FiniteNumber,
    realized_scaled_alpha: FiniteNumber.min(-1).max(1),
    missed_opportunity_utility: NonNegativeFinite,
  })
  .strict();

export const AlphaOutcomeRawMetricsSchema = z
  .object({
    ...DecisionOutcomeBaseShape,
    components: z.tuple([
      decisionComponent("SELECTED_PICK_UTILITY", 0.7),
      decisionComponent("INCREMENTAL_OPPORTUNITY_UTILITY", 0.3),
    ]),
    discovery_disposition: z.enum(["CANDIDATES", "NONE_FOUND"]),
    candidate_metrics: z.tuple(
      [AlphaCandidateOutcomeMetricSchema],
      AlphaCandidateOutcomeMetricSchema,
    ),
    selected_pick_utility_delta: FiniteNumber,
    incremental_candidate_utility_delta: FiniteNumber,
    output_confidence_forecast_loss: NonNegativeFinite,
    output_confidence_null_loss: NonNegativeFinite,
  })
  .strict();

const ExecutionOrderOutcomeMetricSchema = z
  .object({
    order_intent_ref: NonEmptyId,
    ts_code: NonEmptyId,
    requested_delta_weight: FiniteNumber.refine((value) => value !== 0),
    predicted_feasibility: z.enum(["FEASIBLE", "PARTIAL", "BLOCKED"]),
    predicted_feasibility_confidence: Probability,
    realized_feasibility: z.enum(["FEASIBLE", "PARTIAL", "BLOCKED"]),
    predicted_cost_bps: NonNegativeFinite,
    realized_cost_bps: NonNegativeFinite,
    pit_cost_scale_bps: PositiveFinite,
    normalized_absolute_cost_error: NonNegativeFinite,
    realized_delta_weight: FiniteNumber,
    target_delta_attainment: Probability,
    realized_policy_compliance: z.union([z.literal(0), z.literal(1)]),
    outcome_evidence_ids: z.tuple([NonEmptyId], NonEmptyId),
  })
  .strict();

export const ExecutionOutcomeRawMetricsSchema = z
  .object({
    ...DecisionOutcomeBaseShape,
    components: z.tuple([
      decisionComponent("COST_ERROR", 0.4),
      decisionComponent("FEASIBILITY", 0.3),
      decisionComponent("TARGET_DELTA", 0.2),
      decisionComponent("POLICY_COMPLIANCE", 0.1),
    ]),
    execution_mode: z.enum(["PAPER", "REAL"]),
    order_metrics: z.tuple([ExecutionOrderOutcomeMetricSchema], ExecutionOrderOutcomeMetricSchema),
    mean_normalized_cost_error: NonNegativeFinite,
    feasibility_classification_utility_delta: FiniteNumber,
    target_delta_utility_delta: FiniteNumber,
    policy_compliance_utility_delta: FiniteNumber,
  })
  .strict();

const CioPortfolioWeightMetricSchema = z
  .object({
    ts_code: NonEmptyId,
    pre_cio_weight: Probability,
    target_weight: Probability,
    realized_weight: Probability,
    realized_net_return_5d: FiniteNumber,
  })
  .strict();

export const CioOutcomeRawMetricsSchema = z
  .object({
    ...DecisionOutcomeBaseShape,
    components: z.tuple([
      decisionComponent("RELATIVE_RETURN", 0.5),
      decisionComponent("DRAWDOWN", 0.25),
      decisionComponent("TURNOVER_COST", 0.15),
      decisionComponent("CONSTRAINT_COMPLIANCE", 0.1),
    ]),
    decision_disposition: z.enum(["TARGET_PORTFOLIO", "HOLD_CURRENT", "ALL_CASH"]),
    portfolio_metrics: z.array(CioPortfolioWeightMetricSchema),
    pre_cio_cash_weight: Probability,
    target_cash_weight: Probability,
    realized_cash_weight: Probability,
    output_net_return_5d: FiniteNumber,
    null_net_return_5d: FiniteNumber,
    output_max_drawdown_5d: FiniteNumber.max(0),
    null_max_drawdown_5d: FiniteNumber.max(0),
    output_turnover_cost: NonNegativeFinite,
    null_turnover_cost: NonNegativeFinite,
    realized_constraint_compliance: z.union([z.literal(0), z.literal(1)]),
  })
  .strict();

export const OUTCOME_METRIC_SCHEMA_REGISTRY = Object.freeze({
  macro_transmission_metrics_v2: MacroTransmissionOutcomeRawMetricsSchema,
  standard_sector_direction_pick_metrics_v2: StandardSectorOutcomeRawMetricsSchema,
  relationship_graph_validation_metrics_v2: RelationshipOutcomeRawMetricsSchema,
  superinvestor_pick_utility_metrics_v2: SuperinvestorOutcomeRawMetricsSchema,
  cro_risk_control_metrics_v2: CroOutcomeRawMetricsSchema,
  alpha_discovery_incremental_metrics_v2: AlphaOutcomeRawMetricsSchema,
  execution_feasibility_cost_metrics_v2: ExecutionOutcomeRawMetricsSchema,
  cio_portfolio_utility_metrics_v2: CioOutcomeRawMetricsSchema,
});

export type OutcomeMetricSchemaId = keyof typeof OUTCOME_METRIC_SCHEMA_REGISTRY;

export function parseOutcomeRawMetrics(metricSchemaId: string, value: unknown): unknown {
  const schema = OUTCOME_METRIC_SCHEMA_REGISTRY[metricSchemaId as OutcomeMetricSchemaId];
  if (!schema) throw new Error(`unknown_outcome_metric_schema:${metricSchemaId}`);
  return schema.parse(value);
}

export const AcceptedEvaluationOutputKindSchema = z.enum([
  "MACRO_TRANSMISSION",
  "STANDARD_SECTOR_SELECTION",
  "RELATIONSHIP_GRAPH",
  "SUPERINVESTOR_SELECTION",
  "CRO_RISK_REVIEW",
  "ALPHA_DISCOVERY",
  "EXECUTION_ASSESSMENT",
  "CIO_FINAL",
]);

export const EvaluationObjectTypeSchema = z.enum([
  "MACRO_TRANSMISSION",
  "SECTOR_TILT_PICKS",
  "RELATIONSHIP_EDGES",
  "SUPERINVESTOR_PICKS",
  "CRO_FROZEN_RISK_ACTIONS",
  "ALPHA_FROZEN_NOVEL_PICKS",
  "EXECUTION_FROZEN_ORDER_INTENT",
  "CIO_FROZEN_FINAL_PORTFOLIO",
]);

export const OutcomeContractSchema = z
  .object({
    agent_id: z.string().min(1),
    layer: z.enum(["MACRO", "SECTOR", "SUPERINVESTOR", "DECISION"]),
    evaluation_object: z.string().min(1),
    evaluation_object_type: EvaluationObjectTypeSchema,
    evaluation_object_schema_version: z.string().min(1),
    accepted_output_kind: AcceptedEvaluationOutputKindSchema,
    primary_label_id: z.string().min(1),
    metric_schema_id: z.string().min(1),
    maturity_horizon: z.enum(["T1_CLOSE", "TRADING_DAYS_5", "TRADING_DAYS_20", "TRADING_DAYS_21"]),
    maturity: z
      .object({
        entry_semantics: z.enum(["T_PLUS_1_OPEN", "NEXT_SESSION_EXECUTION"]),
        horizon_trading_days: z.union([z.literal(1), z.literal(5), z.literal(20), z.literal(21)]),
        trading_calendar_id: z.string().min(1),
      })
      .strict(),
    sample_schedule: OutcomeScheduleSchema,
    rank_scope: z.string().min(1),
    darwin_application_mode: DarwinApplicationModeSchema,
    metric_family: OutcomeMetricFamilySchema,
    outcome_contract_version: z.string().min(1),
    scoring_contract_version: z.string().min(1),
    sample_schedule_contract_version: z.string().min(1),
    rank_scope_contract_version: z.string().min(1),
    opportunity_set_contract_version: z.string().min(1),
    normalization_contract_version: z.string().min(1),
    required_source_ids: z.array(z.string().min(1)).min(1),
    fallback_allowed: z.literal(false),
    label_owner: z.literal("DETERMINISTIC_RUNTIME"),
    component_composition_contract: z
      .object({
        component_weight_contract_version: z.string().min(1),
        components: z.record(z.string().min(1), PositiveFinite),
        calibration_contract: ComponentCalibrationContractSchema,
      })
      .strict()
      .nullable(),
    track_contract_dimensions: z
      .object({
        component_weight_contract: z.enum(["REQUIRED", "NULL"]),
        reliability_adapter_contract: z.enum(["REQUIRED", "NULL"]),
        confidence_semantics_contract: z.enum(["REQUIRED", "NULL"]),
      })
      .strict(),
  })
  .strict()
  .superRefine((contract, ctx) => {
    const required = contract.track_contract_dimensions.component_weight_contract === "REQUIRED";
    if (required !== (contract.component_composition_contract !== null)) {
      ctx.addIssue({
        code: "custom",
        path: ["component_composition_contract"],
        message: "component composition presence must match track dimensions",
      });
    }
    const components = contract.component_composition_contract?.components;
    if (components) {
      const total = Object.values(components).reduce((sum, weight) => sum + weight, 0);
      if (Object.keys(components).length < 2 || Math.abs(total - 1) > 1e-12) {
        ctx.addIssue({
          code: "custom",
          path: ["component_composition_contract", "components"],
          message: "component weights must contain at least two rows and sum to one",
        });
      }
    }
  });

export type OutcomeContract = z.infer<typeof OutcomeContractSchema>;

const TRADING_CALENDAR_ID = "cn_a_share_trading_calendar_v1";
const FIXED_SCHEDULE_EPOCH = "2010-01-04";
const COMMON_A_SHARE_PATH_SOURCES = [
  "cn_a_share_t_plus_1_total_return_path_v1",
  "cn_a_share_pit_volatility_scale_v1",
] as const;

function fixedSchedule(step_trading_days: number): z.infer<typeof OutcomeScheduleSchema> {
  return {
    kind: "FIXED_NON_OVERLAP",
    trading_calendar_id: TRADING_CALENDAR_ID,
    epoch: FIXED_SCHEDULE_EPOCH,
    step_trading_days,
  };
}

function eventSchedule(agent_id: string): z.infer<typeof OutcomeScheduleSchema> {
  return {
    kind: "EVENT_TRIGGERED",
    trading_calendar_id: TRADING_CALENDAR_ID,
    event_registry_version: `${agent_id}_verified_event_registry_v2`,
    event_priority_version: `${agent_id}_event_priority_v2`,
  };
}

const macro = (
  agent_id: string,
  primary_label_id: string,
  schedule: z.infer<typeof OutcomeScheduleSchema>,
  roleSourceId: string,
): OutcomeContract => {
  const roleContract = MACRO_ROLE_CONTRACTS[agent_id as keyof typeof MACRO_ROLE_CONTRACTS];
  const componentEntries = Object.entries(roleContract.components);
  return {
    agent_id,
    layer: "MACRO",
    evaluation_object: "AcceptedMacroTransmission",
    evaluation_object_type: "MACRO_TRANSMISSION",
    evaluation_object_schema_version: "accepted_macro_transmission_v2",
    accepted_output_kind: "MACRO_TRANSMISSION",
    primary_label_id,
    metric_schema_id: "macro_transmission_metrics_v2",
    maturity_horizon: "TRADING_DAYS_5",
    maturity: {
      entry_semantics: "T_PLUS_1_OPEN",
      horizon_trading_days: 5,
      trading_calendar_id: TRADING_CALENDAR_ID,
    },
    sample_schedule: schedule,
    rank_scope: `macro_${agent_id}`,
    darwin_application_mode: "DOWNSTREAM_USAGE_WEIGHT",
    metric_family: "MACRO_TRANSMISSION",
    outcome_contract_version: "macro_transmission_outcome_v2",
    scoring_contract_version: `score_${primary_label_id}_v1`,
    sample_schedule_contract_version: "macro_non_overlapping_role_opportunity_v2",
    rank_scope_contract_version: `self_macro_${agent_id}_v2`,
    opportunity_set_contract_version: `${agent_id}_macro_opportunity_set_v2`,
    normalization_contract_version: `${primary_label_id}_normalization_v1`,
    required_source_ids: [roleSourceId, ...COMMON_A_SHARE_PATH_SOURCES],
    fallback_allowed: false,
    label_owner: "DETERMINISTIC_RUNTIME",
    component_composition_contract:
      componentEntries.length > 0
        ? {
            component_weight_contract_version: MACRO_COMPONENT_WEIGHT_CONTRACT_VERSION,
            components: Object.fromEntries(componentEntries),
            calibration_contract: {
              ...COMPONENT_CALIBRATION_CONTRACT,
              semiannual_slot_months: [
                ...COMPONENT_CALIBRATION_CONTRACT.semiannual_slot_months,
              ] as [6, 12],
            },
          }
        : null,
    track_contract_dimensions: {
      component_weight_contract: ["geopolitical", "market_breadth", "institutional_flow"].includes(
        agent_id,
      )
        ? "NULL"
        : "REQUIRED",
      reliability_adapter_contract: "NULL",
      confidence_semantics_contract: "NULL",
    },
  };
};

const sector = (agent_id: string): OutcomeContract => ({
  agent_id,
  layer: "SECTOR",
  evaluation_object: "AcceptedSectorSelection",
  evaluation_object_type: "SECTOR_TILT_PICKS",
  evaluation_object_schema_version: "accepted_sector_selection_v3",
  accepted_output_kind: "STANDARD_SECTOR_SELECTION",
  primary_label_id: `${agent_id}_direction_pick_alpha_5d`,
  metric_schema_id: "standard_sector_direction_pick_metrics_v2",
  maturity_horizon: "TRADING_DAYS_5",
  maturity: {
    entry_semantics: "T_PLUS_1_OPEN",
    horizon_trading_days: 5,
    trading_calendar_id: TRADING_CALENDAR_ID,
  },
  sample_schedule: fixedSchedule(5),
  rank_scope: "sector_selection",
  darwin_application_mode: "DOWNSTREAM_USAGE_WEIGHT",
  metric_family: "STANDARD_SECTOR",
  outcome_contract_version: "sector_direction_pick_outcome_v2",
  scoring_contract_version: `score_${agent_id}_direction_pick_v2`,
  sample_schedule_contract_version: "sector_fixed_non_overlapping_5d_v2",
  rank_scope_contract_version: "sector_selection_peer_scope_v2",
  opportunity_set_contract_version: `${agent_id}_sector_opportunity_set_v2`,
  normalization_contract_version: "sector_opportunity_adjusted_utility_normalization_v2",
  required_source_ids: [
    "sector_universe_manifest_v1",
    "sector_pit_direction_constituent_snapshot_v3",
    "cn_a_share_security_outcome_path_v2",
  ],
  fallback_allowed: false,
  label_owner: "DETERMINISTIC_RUNTIME",
  component_composition_contract: null,
  track_contract_dimensions: {
    component_weight_contract: "NULL",
    reliability_adapter_contract: "REQUIRED",
    confidence_semantics_contract: "REQUIRED",
  },
});

const superinvestor = (agent_id: string): OutcomeContract => ({
  agent_id,
  layer: "SUPERINVESTOR",
  evaluation_object: "AcceptedSuperinvestorSelection",
  evaluation_object_type: "SUPERINVESTOR_PICKS",
  evaluation_object_schema_version: "accepted_superinvestor_selection_v2",
  accepted_output_kind: "SUPERINVESTOR_SELECTION",
  primary_label_id: `${agent_id}_pick_utility_21d`,
  metric_schema_id: "superinvestor_pick_utility_metrics_v2",
  maturity_horizon: "TRADING_DAYS_21",
  maturity: {
    entry_semantics: "T_PLUS_1_OPEN",
    horizon_trading_days: 21,
    trading_calendar_id: TRADING_CALENDAR_ID,
  },
  sample_schedule: fixedSchedule(21),
  rank_scope: "superinvestor_selection",
  darwin_application_mode: "DOWNSTREAM_USAGE_WEIGHT",
  metric_family: "SUPERINVESTOR",
  outcome_contract_version: "superinvestor_selection_outcome_v2",
  scoring_contract_version: `score_${agent_id}_pick_utility_v2`,
  sample_schedule_contract_version: "superinvestor_fixed_non_overlapping_21d_v2",
  rank_scope_contract_version: "superinvestor_selection_peer_scope_v2",
  opportunity_set_contract_version: `${agent_id}_frozen_layer2_candidate_set_v2`,
  normalization_contract_version: "superinvestor_pick_utility_normalization_v2",
  required_source_ids: ["accepted_sector_layer_snapshot_v2", "cn_a_share_security_outcome_path_v2"],
  fallback_allowed: false,
  label_owner: "DETERMINISTIC_RUNTIME",
  component_composition_contract: null,
  track_contract_dimensions: {
    component_weight_contract: "NULL",
    reliability_adapter_contract: "REQUIRED",
    confidence_semantics_contract: "REQUIRED",
  },
});

export const OUTCOME_LABEL_REGISTRY: Readonly<Record<string, OutcomeContract>> = Object.freeze({
  china: macro(
    "china",
    "china_macro_transmission_a_share_path_5d",
    eventSchedule("china"),
    "china_verified_macro_release_event_v2",
  ),
  us_economy: macro(
    "us_economy",
    "us_economic_cycle_a_share_path_5d",
    eventSchedule("us_economy"),
    "us_verified_macro_release_event_v2",
  ),
  eu_economy: macro(
    "eu_economy",
    "eu_economic_cycle_a_share_path_5d",
    eventSchedule("eu_economy"),
    "eu27_verified_macro_release_event_v2",
  ),
  central_bank: macro(
    "central_bank",
    "pboc_rate_liquidity_a_share_path_5d",
    eventSchedule("central_bank"),
    "pboc_verified_policy_liquidity_event_v2",
  ),
  us_financial_conditions: macro(
    "us_financial_conditions",
    "us_financial_conditions_a_share_path_5d",
    fixedSchedule(5),
    "us_financial_conditions_path_v2",
  ),
  euro_area_financial_conditions: macro(
    "euro_area_financial_conditions",
    "euro_area_financial_conditions_a_share_path_5d",
    fixedSchedule(5),
    "euro_area_financial_conditions_path_v2",
  ),
  commodities: macro(
    "commodities",
    "commodity_a_share_transmission_path_5d",
    fixedSchedule(5),
    "commodity_market_transmission_path_v2",
  ),
  geopolitical: macro(
    "geopolitical",
    "geopolitical_transmission_a_share_path_5d",
    eventSchedule("geopolitical"),
    "verified_geopolitical_event_lifecycle_v2",
  ),
  market_breadth: macro(
    "market_breadth",
    "market_breadth_confirmation_5d",
    fixedSchedule(5),
    "market_breadth_composite_path_v2",
  ),
  institutional_flow: macro(
    "institutional_flow",
    "institutional_flow_followthrough_5d",
    fixedSchedule(5),
    "institutional_flow_followthrough_path_v2",
  ),
  semiconductor: sector("semiconductor"),
  technology: sector("technology"),
  energy: sector("energy"),
  biotech: sector("biotech"),
  consumer: sector("consumer"),
  industrials: sector("industrials"),
  real_estate_construction: sector("real_estate_construction"),
  financials: sector("financials"),
  agriculture: sector("agriculture"),
  relationship_mapper: {
    agent_id: "relationship_mapper",
    layer: "SECTOR",
    evaluation_object: "AcceptedRelationshipGraph",
    evaluation_object_type: "RELATIONSHIP_EDGES",
    evaluation_object_schema_version: "accepted_relationship_graph_v2",
    accepted_output_kind: "RELATIONSHIP_GRAPH",
    primary_label_id: "relationship_graph_validation_20d",
    metric_schema_id: "relationship_graph_validation_metrics_v2",
    maturity_horizon: "TRADING_DAYS_20",
    maturity: {
      entry_semantics: "T_PLUS_1_OPEN",
      horizon_trading_days: 20,
      trading_calendar_id: TRADING_CALENDAR_ID,
    },
    sample_schedule: fixedSchedule(20),
    rank_scope: "sector_relationship",
    darwin_application_mode: "DOWNSTREAM_USAGE_WEIGHT",
    metric_family: "RELATIONSHIP",
    outcome_contract_version: "relationship_graph_outcome_v2",
    scoring_contract_version: "score_relationship_graph_validation_v2",
    sample_schedule_contract_version: "relationship_fixed_non_overlapping_20d_v2",
    rank_scope_contract_version: "self_sector_relationship_v2",
    opportunity_set_contract_version: "relationship_edge_candidate_opportunity_set_v2",
    normalization_contract_version: "relationship_edge_validation_normalization_v2",
    required_source_ids: [
      "relationship_graph_candidate_snapshot_v2",
      "relationship_edge_realized_path_v2",
      "relationship_matched_non_edge_sample_v2",
    ],
    fallback_allowed: false,
    label_owner: "DETERMINISTIC_RUNTIME",
    component_composition_contract: null,
    track_contract_dimensions: {
      component_weight_contract: "NULL",
      reliability_adapter_contract: "REQUIRED",
      confidence_semantics_contract: "REQUIRED",
    },
  },
  druckenmiller: superinvestor("druckenmiller"),
  munger: superinvestor("munger"),
  burry: superinvestor("burry"),
  ackman: superinvestor("ackman"),
  cro: {
    agent_id: "cro",
    layer: "DECISION",
    evaluation_object: "AcceptedCroRiskActions",
    evaluation_object_type: "CRO_FROZEN_RISK_ACTIONS",
    evaluation_object_schema_version: "accepted_cro_risk_review_v2",
    accepted_output_kind: "CRO_RISK_REVIEW",
    primary_label_id: "cro_risk_control_calibration_5d",
    metric_schema_id: "cro_risk_control_metrics_v2",
    maturity_horizon: "TRADING_DAYS_5",
    maturity: {
      entry_semantics: "T_PLUS_1_OPEN",
      horizon_trading_days: 5,
      trading_calendar_id: TRADING_CALENDAR_ID,
    },
    sample_schedule: fixedSchedule(5),
    rank_scope: "decision_cro",
    darwin_application_mode: "EVOLUTION_ONLY",
    metric_family: "CRO",
    outcome_contract_version: "cro_outcome_v2",
    scoring_contract_version: "score_cro_risk_control_v2",
    sample_schedule_contract_version: "decision_fixed_non_overlapping_5d_v2",
    rank_scope_contract_version: "self_decision_cro_v2",
    opportunity_set_contract_version: "cro_pre_cro_candidate_opportunity_set_v2",
    normalization_contract_version: "cro_risk_control_normalization_v2",
    required_source_ids: ["pre_cro_candidate_set_v2", "realized_risk_state_path_v2"],
    fallback_allowed: false,
    label_owner: "DETERMINISTIC_RUNTIME",
    component_composition_contract: null,
    track_contract_dimensions: {
      component_weight_contract: "NULL",
      reliability_adapter_contract: "NULL",
      confidence_semantics_contract: "NULL",
    },
  },
  alpha_discovery: {
    agent_id: "alpha_discovery",
    layer: "DECISION",
    evaluation_object: "AcceptedAlphaDiscovery",
    evaluation_object_type: "ALPHA_FROZEN_NOVEL_PICKS",
    evaluation_object_schema_version: "accepted_alpha_discovery_v2",
    accepted_output_kind: "ALPHA_DISCOVERY",
    primary_label_id: "alpha_discovery_incremental_alpha_5d",
    metric_schema_id: "alpha_discovery_incremental_metrics_v2",
    maturity_horizon: "TRADING_DAYS_5",
    maturity: {
      entry_semantics: "T_PLUS_1_OPEN",
      horizon_trading_days: 5,
      trading_calendar_id: TRADING_CALENDAR_ID,
    },
    sample_schedule: fixedSchedule(5),
    rank_scope: "decision_alpha",
    darwin_application_mode: "EVOLUTION_ONLY",
    metric_family: "ALPHA",
    outcome_contract_version: "alpha_discovery_outcome_v2",
    scoring_contract_version: "score_alpha_discovery_v2",
    sample_schedule_contract_version: "decision_fixed_non_overlapping_5d_v2",
    rank_scope_contract_version: "self_decision_alpha_v2",
    opportunity_set_contract_version: "alpha_novel_candidate_opportunity_set_v2",
    normalization_contract_version: "alpha_incremental_utility_normalization_v2",
    required_source_ids: [
      "frozen_layer3_novel_candidate_set_v2",
      "cn_a_share_security_outcome_path_v2",
    ],
    fallback_allowed: false,
    label_owner: "DETERMINISTIC_RUNTIME",
    component_composition_contract: null,
    track_contract_dimensions: {
      component_weight_contract: "NULL",
      reliability_adapter_contract: "NULL",
      confidence_semantics_contract: "NULL",
    },
  },
  autonomous_execution: {
    agent_id: "autonomous_execution",
    layer: "DECISION",
    evaluation_object: "AcceptedExecutionFeasibility",
    evaluation_object_type: "EXECUTION_FROZEN_ORDER_INTENT",
    evaluation_object_schema_version: "accepted_execution_assessment_v2",
    accepted_output_kind: "EXECUTION_ASSESSMENT",
    primary_label_id: "execution_feasibility_cost_t1",
    metric_schema_id: "execution_feasibility_cost_metrics_v2",
    maturity_horizon: "T1_CLOSE",
    maturity: {
      entry_semantics: "NEXT_SESSION_EXECUTION",
      horizon_trading_days: 1,
      trading_calendar_id: TRADING_CALENDAR_ID,
    },
    sample_schedule: fixedSchedule(1),
    rank_scope: "decision_execution",
    darwin_application_mode: "EVOLUTION_ONLY",
    metric_family: "EXECUTION",
    outcome_contract_version: "execution_outcome_v2",
    scoring_contract_version: "score_execution_feasibility_cost_v2",
    sample_schedule_contract_version: "decision_t1_execution_opportunity_v2",
    rank_scope_contract_version: "self_decision_execution_v2",
    opportunity_set_contract_version: "execution_frozen_order_intent_opportunity_set_v2",
    normalization_contract_version: "execution_cost_feasibility_normalization_v2",
    required_source_ids: ["cio_approved_order_intent_set_v2", "next_session_execution_outcome_v2"],
    fallback_allowed: false,
    label_owner: "DETERMINISTIC_RUNTIME",
    component_composition_contract: null,
    track_contract_dimensions: {
      component_weight_contract: "NULL",
      reliability_adapter_contract: "NULL",
      confidence_semantics_contract: "NULL",
    },
  },
  cio: {
    agent_id: "cio",
    layer: "DECISION",
    evaluation_object: "AcceptedCioFinal",
    evaluation_object_type: "CIO_FROZEN_FINAL_PORTFOLIO",
    evaluation_object_schema_version: "accepted_cio_final_v2",
    accepted_output_kind: "CIO_FINAL",
    primary_label_id: "cio_portfolio_utility_5d",
    metric_schema_id: "cio_portfolio_utility_metrics_v2",
    maturity_horizon: "TRADING_DAYS_5",
    maturity: {
      entry_semantics: "T_PLUS_1_OPEN",
      horizon_trading_days: 5,
      trading_calendar_id: TRADING_CALENDAR_ID,
    },
    sample_schedule: fixedSchedule(5),
    rank_scope: "decision_cio",
    darwin_application_mode: "EVOLUTION_ONLY",
    metric_family: "CIO",
    outcome_contract_version: "cio_final_outcome_v2",
    scoring_contract_version: "score_cio_portfolio_utility_v2",
    sample_schedule_contract_version: "decision_fixed_non_overlapping_5d_v2",
    rank_scope_contract_version: "self_decision_cio_v2",
    opportunity_set_contract_version: "cio_pre_cio_portfolio_opportunity_set_v2",
    normalization_contract_version: "cio_portfolio_utility_normalization_v2",
    required_source_ids: ["pre_cio_portfolio_and_constraints_v2", "realized_portfolio_path_v2"],
    fallback_allowed: false,
    label_owner: "DETERMINISTIC_RUNTIME",
    component_composition_contract: null,
    track_contract_dimensions: {
      component_weight_contract: "NULL",
      reliability_adapter_contract: "NULL",
      confidence_semantics_contract: "NULL",
    },
  },
});

export function validateOutcomeRegistry(): void {
  const roster = [...ALL_AGENTS].sort();
  const registered = Object.keys(OUTCOME_LABEL_REGISTRY).sort();
  if (registered.join("\0") !== roster.join("\0")) {
    throw new Error("outcome_registry_must_cover_exact_28_agent_roster");
  }
  const labels = new Set<string>();
  for (const [agent, contract] of Object.entries(OUTCOME_LABEL_REGISTRY)) {
    OutcomeContractSchema.parse(contract);
    if (contract.agent_id !== agent) throw new Error(`outcome_registry_agent_mismatch:${agent}`);
    if (labels.has(contract.primary_label_id))
      throw new Error(`duplicate_primary_label:${contract.primary_label_id}`);
    labels.add(contract.primary_label_id);
    if (contract.darwin_application_mode === "EVOLUTION_ONLY" && contract.layer !== "DECISION") {
      throw new Error(`evolution_only_must_be_decision:${agent}`);
    }
    if (
      contract.darwin_application_mode === "DOWNSTREAM_USAGE_WEIGHT" &&
      contract.layer === "DECISION"
    ) {
      throw new Error(`decision_must_not_have_usage_weight:${agent}`);
    }
    if (!(contract.metric_schema_id in OUTCOME_METRIC_SCHEMA_REGISTRY)) {
      throw new Error(`unknown_metric_schema:${agent}:${contract.metric_schema_id}`);
    }
  }
}

export function outcomeRegistryHash(): string {
  validateOutcomeRegistry();
  const canonical = JSON.stringify(
    Object.fromEntries(
      Object.entries(OUTCOME_LABEL_REGISTRY).sort(([a], [b]) => a.localeCompare(b)),
    ),
  );
  return `sha256:${createHash("sha256").update(canonical).digest("hex")}`;
}

export function renderOutcomeContractManifestArtifact(): string {
  validateOutcomeRegistry();
  const contracts = Object.values(OUTCOME_LABEL_REGISTRY).sort((a, b) =>
    a.agent_id.localeCompare(b.agent_id),
  );
  const metricSchemas = Object.fromEntries(
    Object.entries(OUTCOME_METRIC_SCHEMA_REGISTRY).map(([schemaId, schema]) => [
      schemaId,
      z.toJSONSchema(schema, { target: "draft-7" }),
    ]),
  );
  return `${JSON.stringify(
    {
      manifest_version: "agent_outcome_contract_manifest_v2",
      contract_count: contracts.length,
      usage_track_count: contracts.filter(
        (row) => row.darwin_application_mode === "DOWNSTREAM_USAGE_WEIGHT",
      ).length,
      evolution_only_track_count: contracts.filter(
        (row) => row.darwin_application_mode === "EVOLUTION_ONLY",
      ).length,
      registry_hash: outcomeRegistryHash(),
      metric_schema_count: Object.keys(metricSchemas).length,
      metric_schemas_hash: canonicalHash(metricSchemas),
      metric_schemas: metricSchemas,
      contracts,
    },
    null,
    2,
  )}\n`;
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
        .map(([key, item]) => [key, canonicalize(item)]),
    );
  }
  return value;
}

validateOutcomeRegistry();
