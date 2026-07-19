import { describe, expect, it } from "vitest";
import { ALL_AGENTS } from "../src/agents/prompts/cohorts.js";
import {
  OUTCOME_LABEL_REGISTRY,
  OUTCOME_METRIC_SCHEMA_REGISTRY,
  outcomeRegistryHash,
  parseOutcomeRawMetrics,
  renderOutcomeContractManifestArtifact,
  validateOutcomeRegistry,
} from "../src/autoresearch/outcome_registry.js";

describe("28-Agent outcome registry", () => {
  it("covers every Agent once with a unique label and valid maturity path", () => {
    expect(validateOutcomeRegistry).not.toThrow();
    expect(Object.keys(OUTCOME_LABEL_REGISTRY).sort()).toEqual([...ALL_AGENTS].sort());
    expect(
      new Set(Object.values(OUTCOME_LABEL_REGISTRY).map((row) => row.primary_label_id)).size,
    ).toBe(28);
    expect(outcomeRegistryHash()).toMatch(/^sha256:[0-9a-f]{64}$/);
  });

  it("creates 24 usage tracks and four evolution-only Decision tracks", () => {
    const rows = Object.values(OUTCOME_LABEL_REGISTRY);
    expect(
      rows.filter((row) => row.darwin_application_mode === "DOWNSTREAM_USAGE_WEIGHT"),
    ).toHaveLength(24);
    expect(
      rows
        .filter((row) => row.darwin_application_mode === "EVOLUTION_ONLY")
        .map((row) => row.agent_id)
        .sort(),
    ).toEqual(["alpha_discovery", "autonomous_execution", "cio", "cro"]);
  });

  it("does not register tombstoned Macro identities", () => {
    for (const retired of [
      "dollar",
      "yield_curve",
      "volatility",
      "emerging_markets",
      "news_sentiment",
    ]) {
      expect(OUTCOME_LABEL_REGISTRY).not.toHaveProperty(retired);
    }
  });

  it("keeps each Macro in a self scope and Sector/Superinvestor in homogeneous peer scopes", () => {
    const macroRows = Object.values(OUTCOME_LABEL_REGISTRY).filter(
      (row) => row.metric_family === "MACRO_TRANSMISSION",
    );
    expect(new Set(macroRows.map((row) => row.rank_scope)).size).toBe(10);
    expect(OUTCOME_LABEL_REGISTRY.relationship_mapper?.rank_scope).toBe("sector_relationship");
    expect(OUTCOME_LABEL_REGISTRY.semiconductor?.rank_scope).toBe("sector_selection");
    expect(OUTCOME_LABEL_REGISTRY.munger?.rank_scope).toBe("superinvestor_selection");
  });

  it("freezes exactly seven Macro component composition contracts", () => {
    const componentRows = Object.values(OUTCOME_LABEL_REGISTRY).filter(
      (row) => row.component_composition_contract !== null,
    );
    expect(componentRows).toHaveLength(7);
    for (const row of componentRows) {
      expect(row.layer).toBe("MACRO");
      expect(row.component_composition_contract?.component_weight_contract_version).toBe(
        "macro_component_weights_v2",
      );
      expect(
        Object.values(row.component_composition_contract?.components ?? {}).reduce(
          (sum, weight) => sum + weight,
          0,
        ),
      ).toBeCloseTo(1, 12);
    }
  });

  it("freezes deterministic label, opportunity, schedule, and source contracts", () => {
    for (const row of Object.values(OUTCOME_LABEL_REGISTRY)) {
      expect(row.label_owner).toBe("DETERMINISTIC_RUNTIME");
      expect(row.fallback_allowed).toBe(false);
      expect(row.required_source_ids.length).toBeGreaterThan(0);
      expect(new Set(row.required_source_ids).size).toBe(row.required_source_ids.length);
      expect(row.maturity.trading_calendar_id).toBe("cn_a_share_trading_calendar_v1");
      expect(row.metric_schema_id).toMatch(/_v[23]$/);
      for (const value of Object.values(row.track_contract_dimensions)) {
        expect(["REQUIRED", "NULL"]).toContain(value);
      }
    }
    expect(OUTCOME_LABEL_REGISTRY.china?.sample_schedule.kind).toBe("EVENT_TRIGGERED");
    expect(OUTCOME_LABEL_REGISTRY.geopolitical?.sample_schedule.kind).toBe("EVENT_TRIGGERED");
    expect(OUTCOME_LABEL_REGISTRY.market_breadth?.sample_schedule.kind).toBe("FIXED_NON_OVERLAP");
  });

  it("binds every Standard Sector outcome to the active v4 PIT scoring snapshot", () => {
    const sectorRows = Object.values(OUTCOME_LABEL_REGISTRY).filter(
      (row) => row.metric_family === "STANDARD_SECTOR",
    );
    expect(sectorRows).toHaveLength(9);
    for (const row of sectorRows) {
      expect(row.metric_schema_id).toBe("standard_sector_direction_pick_metrics_v3");
      expect(row.required_source_ids).toContain("sector_research_snapshot_v4");
      expect(row.required_source_ids).not.toContain("sector_pit_direction_constituent_snapshot_v3");
    }
  });

  it("renders an exact 28/24/4 manifest", () => {
    const manifest = JSON.parse(renderOutcomeContractManifestArtifact());
    expect(manifest.contract_count).toBe(28);
    expect(manifest.usage_track_count).toBe(24);
    expect(manifest.evolution_only_track_count).toBe(4);
    expect(manifest.contracts).toHaveLength(28);
    expect(manifest.registry_hash).toBe(outcomeRegistryHash());
    expect(manifest.metric_schema_count).toBe(8);
    expect(Object.keys(manifest.metric_schemas).sort()).toEqual(
      Object.keys(OUTCOME_METRIC_SCHEMA_REGISTRY).sort(),
    );
    expect(manifest.metric_schemas_hash).toMatch(/^sha256:[0-9a-f]{64}$/);
  });

  it("enforces the closed Decision component tuple and weights", () => {
    const component = (component_id: string, component_weight: number) => ({
      component_id,
      component_weight,
      unit: "RATIO",
      direction: "HIGHER_IS_BETTER",
      unclipped_output_value: 0.5,
      unclipped_null_value: 0.1,
      scale: 1,
      output_utility: 0.5,
      null_utility: 0.1,
      utility_delta: 0.4,
      denominator_zero_rule_id: "NOT_APPLICABLE",
    });
    const fixture = {
      combined_output_utility: 0.5,
      combined_null_utility: 0.1,
      combined_utility_delta: 0.4,
      components: [
        component("COST_ERROR", 0.4),
        component("FEASIBILITY", 0.3),
        component("TARGET_DELTA", 0.2),
        component("POLICY_COMPLIANCE", 0.1),
      ],
      execution_mode: "PAPER",
      order_metrics: [
        {
          order_intent_ref: "order-1",
          ts_code: "600519.SH",
          requested_delta_weight: 0.01,
          predicted_feasibility: "FEASIBLE",
          predicted_feasibility_confidence: 0.8,
          realized_feasibility: "FEASIBLE",
          predicted_cost_bps: 8,
          realized_cost_bps: 9,
          pit_cost_scale_bps: 10,
          normalized_absolute_cost_error: 0.1,
          realized_delta_weight: 0.01,
          target_delta_attainment: 1,
          realized_policy_compliance: 1,
          outcome_evidence_ids: ["execution-evidence-1"],
        },
      ],
      mean_normalized_cost_error: 0.1,
      feasibility_classification_utility_delta: 0.4,
      target_delta_utility_delta: 0.4,
      policy_compliance_utility_delta: 0.4,
    };
    expect(() =>
      parseOutcomeRawMetrics("execution_feasibility_cost_metrics_v2", fixture),
    ).not.toThrow();
    const drifted = structuredClone(fixture);
    drifted.components.reverse();
    expect(() =>
      parseOutcomeRawMetrics("execution_feasibility_cost_metrics_v2", drifted),
    ).toThrow();
  });

  it("rejects a relationship empty-graph branch without the full abstention audit", () => {
    expect(() =>
      parseOutcomeRawMetrics("relationship_graph_validation_metrics_v2", {
        predictive_graph_status: "NO_QUALIFIED_PREDICTIVE_EDGE",
        edge_metrics: [
          {
            edge_candidate_id: "edge-1",
            materiality_weight: 1,
            realized_edge_state: "NO_ACTIVATION",
            matched_non_edge_lift: 0,
            candidate_counterfactual_best_utility: 0,
            activation_direction_brier_skill: 0,
            path_lift_utility_delta: 0,
            missed_edge_regret: 0,
            edge_utility_delta: 0,
            submitted: false,
            submitted_direction: null,
            submitted_model_confidence: 0,
          },
        ],
        weighted_edge_utility_delta: null,
        graph_abstention_forecast_probability: null,
        graph_abstention_warranted_label: null,
        graph_abstention_forecast_loss: null,
        graph_abstention_null_loss: null,
        graph_abstention_best_raw_opportunity_utility: null,
        graph_abstention_cardinality_adjusted_utility: null,
        graph_abstention_missed_opportunity_regret: null,
        combined_utility_delta: 0,
      }),
    ).toThrow(/complete abstention metrics/);
  });

  it("keeps Standard Sector directional and permits security abstention only for an empty leg", () => {
    const fixture = {
      output_confidence: 0.8,
      confidence_semantics: "DIRECTIONAL_UTILITY",
      direction_metrics: [
        {
          direction_id: "preferred-direction",
          realized_return_5d: 0.03,
          parent_sector_return_5d: 0.01,
          realized_scaled_path: 0.2,
          predicted_tilt: 0.8,
          selected_role: "PREFERRED",
        },
        {
          direction_id: "least-direction",
          realized_return_5d: -0.01,
          parent_sector_return_5d: 0.01,
          realized_scaled_path: -0.2,
          predicted_tilt: -0.8,
          selected_role: "LEAST_PREFERRED",
        },
      ],
      security_metrics: [
        {
          side: "PREFERRED",
          direction_id: "preferred-direction",
          ts_code: "600000.SH",
          action: "LONG",
          conviction: 0.8,
          net_alpha_5d: 0.02,
          realized_scaled_alpha: 0.2,
          predicted_position: 0.8,
        },
      ],
      security_leg_metrics: [
        {
          side: "PREFERRED",
          direction_id: "preferred-direction",
          security_status: "PICKS_PRESENT",
          shortlist_size: 1,
          side_security_utility_delta: 0.2,
        },
        {
          side: "LEAST_PREFERRED",
          direction_id: "least-direction",
          security_status: "NO_QUALIFIED_SECURITY_EMPTY_SHORTLIST",
          shortlist_size: 0,
          side_security_utility_delta: 0,
        },
      ],
      direction_forecast_loss: 0.1,
      direction_null_loss: 0.3,
      security_forecast_loss: 0.1,
      security_null_loss: 0.2,
      direction_utility_delta: 0.2,
      security_utility_delta: 0.1,
      combined_utility_delta: 0.15,
      unit_confidence_utility_delta: 0.1875,
      confidence_calibration_target: 1,
    };
    expect(() =>
      parseOutcomeRawMetrics("standard_sector_direction_pick_metrics_v3", fixture),
    ).not.toThrow();

    const legacyOverallAbstention = {
      ...fixture,
      confidence_semantics: "ABSTENTION_WARRANTED",
      abstention_forecast_loss: 0.1,
    };
    expect(() =>
      parseOutcomeRawMetrics("standard_sector_direction_pick_metrics_v3", legacyOverallAbstention),
    ).toThrow();

    const nonemptyAbstention = structuredClone(fixture);
    const firstLeg = nonemptyAbstention.security_leg_metrics[0];
    if (!firstLeg) throw new Error("missing Standard Sector fixture leg");
    firstLeg.security_status = "NO_QUALIFIED_SECURITY_NONEMPTY_SHORTLIST" as never;
    expect(() =>
      parseOutcomeRawMetrics("standard_sector_direction_pick_metrics_v3", nonemptyAbstention),
    ).toThrow();

    const emptyLegWithPick = structuredClone(fixture);
    const preferredMetric = emptyLegWithPick.security_metrics[0];
    if (!preferredMetric) throw new Error("missing Standard Sector fixture security metric");
    emptyLegWithPick.security_metrics.push({
      ...preferredMetric,
      side: "LEAST_PREFERRED",
      direction_id: "least-direction",
    });
    expect(() =>
      parseOutcomeRawMetrics("standard_sector_direction_pick_metrics_v3", emptyLegWithPick),
    ).toThrow(/security metrics must match/);
  });
});
