import { describe, expect, it } from "vitest";
import {
  type AlphaDiscoverySubmission,
  type AutonomousExecutionSubmission,
  buildAcceptedAlphaDiscovery,
  buildAcceptedCioFinal,
  buildAcceptedCioProposal,
  buildAcceptedCroRiskReview,
  buildAcceptedExecutionAssessment,
  type CioFinalSubmission,
  type CioProposalSubmission,
  type CroAgentSubmission,
  modelVisibleAcceptedDecision,
} from "../src/agents/decision/accepted.js";
import {
  AutonomousExecutionSubmissionSchema,
  buildRuntimeAlphaDiscoverySubmissionSchema,
  CioFinalAllCashSubmissionSchema,
  CioFinalSubmissionSchema,
  CioFinalWithoutHoldSubmissionSchema,
  CioProposalAllCashSubmissionSchema,
  CioProposalWithoutHoldSubmissionSchema,
  CroSubmissionSchema,
} from "../src/agents/decision/submission_schemas.js";
import { MACRO_AGENT_IDS } from "../src/agents/macro/_contracts.js";

const behavior = {
  agent_contract_version: "decision_contract_v2",
  prompt_behavior_version: "decision_prompt_v2",
  execution_behavior_version: "decision_execution_v2",
  component_weight_contract_version: null,
  reliability_adapter_contract_version: "identity_v1",
  confidence_semantics_contract_version: "decision_confidence_v2",
};

const claim = {
  claim_id: "claim-1",
  claim_kind: "FACT" as const,
  statement: "A frozen input supports this structural test.",
  structured_conclusion: { status: "supported" },
  evidence_ids: ["evidence-1"],
  research_rule_refs: [],
};

const macroAttributions = MACRO_AGENT_IDS.map((agent_id) => ({
  agent_id,
  target_type: "SUBMISSION_SUMMARY" as const,
  target_local_ref: "$SUBMISSION" as const,
  claim_refs_used: [],
  effect: "NOT_MATERIAL" as const,
}));

function croSubmission(): CroAgentSubmission {
  return {
    agent_id: "cro",
    review_disposition: "REVIEW_ACTIONS",
    candidate_actions: [
      {
        action_local_id: "cro-local-1",
        candidate_ref: "candidate-1",
        ts_code: "600000.SH",
        action: "CAP_WEIGHT",
        predicted_risk_probability: 0.65,
        max_target_weight: 0.035,
        reason: "Concentration exceeds the frozen risk budget.",
        claim_refs: ["claim-1"],
      },
    ],
    correlated_risks: [],
    black_swan_scenarios: [],
    confidence: 0.7,
    claims: [claim],
    claim_refs: ["claim-1"],
    macro_input_attributions: macroAttributions,
  };
}

function executionSubmission(): AutonomousExecutionSubmission {
  return {
    agent_id: "autonomous_execution",
    execution_disposition: "ORDERS_ASSESSED",
    order_assessments: [
      {
        assessment_local_id: "execution-local-1",
        order_intent_ref: "intent-1",
        ts_code: "600000.SH",
        requested_delta_weight: 0.04,
        feasibility: "PARTIAL",
        feasibility_confidence: 0.8,
        predicted_cost_bps: 12,
        max_executable_delta_weight: 0.03,
        recommended_slice_count: 2,
        reason: "Available liquidity supports only a partial fill.",
        claim_refs: ["claim-1"],
      },
    ],
    confidence: 0.8,
    claims: [claim],
    claim_refs: ["claim-1"],
  };
}

function finalSubmission(): CioFinalSubmission {
  return {
    agent_id: "cio",
    decision_stage: "FINAL",
    decision_disposition: "TARGET_PORTFOLIO",
    target_positions: [
      {
        position_local_id: "position-1",
        ts_code: "600000.SH",
        target_weight: 0.03,
        position_decision: "ADD",
        holding_period: "WEEKS",
        thesis_status: "INTACT",
        risk_flags: [],
        claim_refs: ["claim-1"],
      },
    ],
    cash_weight: 0.97,
    decision_reason: "Respect both accepted controls.",
    cro_control_resolutions: [
      {
        cro_action_local_ref: "cro-local-1",
        resolution: "MORE_CONSERVATIVE",
        reason: "Final target is below the cap.",
        claim_refs: ["claim-1"],
      },
    ],
    execution_control_resolutions: [
      {
        execution_assessment_local_ref: "execution-local-1",
        resolution: "COMPLIED",
        reason: "Final delta matches executable capacity.",
        claim_refs: ["claim-1"],
      },
    ],
    confidence: 0.75,
    claims: [claim],
    claim_refs: ["claim-1"],
    macro_input_attributions: macroAttributions,
  };
}

function frozenProposal() {
  const base = finalSubmission();
  if (base.decision_disposition !== "TARGET_PORTFOLIO") {
    throw new Error("final fixture must contain a target portfolio");
  }
  const {
    cro_control_resolutions: _croResolutions,
    execution_control_resolutions: _executionResolutions,
    ...proposalBody
  } = base;
  const proposal: CioProposalSubmission = {
    ...proposalBody,
    decision_stage: "PROPOSAL",
    target_positions: [
      {
        ...base.target_positions[0],
        target_weight: 0.04,
      },
    ],
    cash_weight: 0.96,
  };
  return buildAcceptedCioProposal({
    submission: proposal,
    behavior,
    frozenPreCioInputId: "pre-cio-final-fixture",
    frozenPreCioInputHash: "sha256:pre-cio-final-fixture",
    alphaSource: {
      source_status: "NO_EVALUATION_OBJECT",
      agent_id: "alpha_discovery",
      accepted_output_id: null,
      accepted_output_hash: null,
      stage_skip_id: "skip-alpha-final-fixture",
      stage_skip_hash: "sha256:skip-alpha-final-fixture",
    },
    acceptedAlphaDiscovery: null,
    acceptedMacroInputAttributions: [],
  });
}

describe("Decision v2 submission and accepted contracts", () => {
  it("freezes Alpha picks to exact runtime candidate-ref/ticker pairs", () => {
    const schema = buildRuntimeAlphaDiscoverySubmissionSchema([
      { candidate_ref: "novel-candidate-1", ts_code: "600000.SH" },
      { candidate_ref: "novel-candidate-2", ts_code: "000001.SZ" },
    ]);
    const submission = {
      agent_id: "alpha_discovery" as const,
      discovery_disposition: "CANDIDATES" as const,
      novel_picks: [
        {
          pick_local_id: "alpha-pick-1",
          candidate_ref: "novel-candidate-1",
          ts_code: "600000.SH",
          conviction: 0.7,
          thesis: "The frozen candidate has incremental evidence.",
          claim_refs: ["claim-1"],
        },
      ],
      confidence: 0.7,
      key_drivers: [],
      risks: [],
      claims: [claim],
      claim_refs: ["claim-1"],
      macro_input_attributions: macroAttributions,
    };
    expect(schema.parse(submission).novel_picks[0]?.ts_code).toBe("600000.SH");
    expect(() =>
      schema.parse({
        ...submission,
        novel_picks: [
          {
            ...submission.novel_picks[0],
            candidate_ref: "novel-candidate-1",
            ts_code: "000001.SZ",
          },
        ],
      }),
    ).toThrow();

    const emptySchema = buildRuntimeAlphaDiscoverySubmissionSchema([]);
    expect(() => emptySchema.parse(submission)).toThrow();
    expect(
      emptySchema.parse({
        ...submission,
        discovery_disposition: "NONE_FOUND",
        novel_picks: [],
      }).discovery_disposition,
    ).toBe("NONE_FOUND");
  });

  it("records a deterministic proposal resolution for every accepted Alpha pick", () => {
    const alphaSubmission: AlphaDiscoverySubmission = {
      agent_id: "alpha_discovery",
      discovery_disposition: "CANDIDATES",
      novel_picks: [
        {
          pick_local_id: "alpha-pick-1",
          candidate_ref: "novel-candidate-1",
          ts_code: "600000.SH",
          conviction: 0.7,
          thesis: "Candidate one is incremental.",
          claim_refs: ["claim-1"],
        },
        {
          pick_local_id: "alpha-pick-2",
          candidate_ref: "novel-candidate-2",
          ts_code: "000001.SZ",
          conviction: 0.6,
          thesis: "Candidate two is incremental.",
          claim_refs: ["claim-1"],
        },
      ],
      confidence: 0.7,
      key_drivers: [],
      risks: [],
      claims: [claim],
      claim_refs: ["claim-1"],
      macro_input_attributions: macroAttributions,
    };
    const acceptedAlpha = buildAcceptedAlphaDiscovery({
      submission: alphaSubmission,
      behavior,
      frozenNovelCandidateUniverseId: "alpha-universe-1",
      frozenNovelCandidateUniverseHash: "sha256:alpha-universe",
      acceptedMacroInputAttributions: [],
    });
    const {
      cro_control_resolutions: _croResolutions,
      execution_control_resolutions: _executionResolutions,
      ...proposalBody
    } = finalSubmission();
    const proposal = {
      ...proposalBody,
      decision_stage: "PROPOSAL",
    } as CioProposalSubmission;
    const alphaSource = {
      source_status: "ACCEPTED_OUTPUT" as const,
      agent_id: "alpha_discovery" as const,
      accepted_output_id: acceptedAlpha.accepted_alpha_discovery_id,
      accepted_output_hash: acceptedAlpha.accepted_alpha_discovery_hash,
      stage_skip_id: null,
      stage_skip_hash: null,
    };
    const accepted = buildAcceptedCioProposal({
      submission: proposal,
      behavior,
      frozenPreCioInputId: "pre-cio-1",
      frozenPreCioInputHash: "sha256:pre-cio",
      alphaSource,
      acceptedAlphaDiscovery: acceptedAlpha,
      acceptedMacroInputAttributions: [],
    });
    expect(accepted.alpha_pick_resolutions).toEqual([
      {
        alpha_pick_local_ref: "alpha-pick-1",
        ts_code: "600000.SH",
        resolution: "INCLUDED",
        target_position_local_ref: "position-1",
        reason: "The proposal includes this frozen Alpha candidate.",
      },
      {
        alpha_pick_local_ref: "alpha-pick-2",
        ts_code: "000001.SZ",
        resolution: "NOT_INCLUDED",
        target_position_local_ref: null,
        reason: proposal.decision_reason,
      },
    ]);
    expect(() =>
      buildAcceptedCioProposal({
        submission: proposal,
        behavior,
        frozenPreCioInputId: "pre-cio-1",
        frozenPreCioInputHash: "sha256:pre-cio",
        alphaSource,
        acceptedAlphaDiscovery: null,
        acceptedMacroInputAttributions: [],
      }),
    ).toThrow(/source mismatch/);
  });

  it("enforces CRO action semantics and deterministic disposition", () => {
    expect(CroSubmissionSchema.parse(croSubmission())).toMatchObject({ agent_id: "cro" });
    expect(() =>
      CroSubmissionSchema.parse({
        ...croSubmission(),
        review_disposition: "NO_OBJECTION",
      }),
    ).toThrow(/deterministically derived/);
    expect(() =>
      CroSubmissionSchema.parse({
        ...croSubmission(),
        candidate_actions: [{ ...croSubmission().candidate_actions[0], max_target_weight: null }],
      }),
    ).toThrow(/numeric max_target_weight/);
  });

  it("enforces execution feasibility bounds before runtime acceptance", () => {
    expect(AutonomousExecutionSubmissionSchema.parse(executionSubmission())).toMatchObject({
      execution_disposition: "ORDERS_ASSESSED",
    });
    expect(() =>
      AutonomousExecutionSubmissionSchema.parse({
        ...executionSubmission(),
        order_assessments: [
          {
            ...executionSubmission().order_assessments[0],
            max_executable_delta_weight: 0.04,
          },
        ],
      }),
    ).toThrow(/strictly between/);
  });

  it("materializes persistent per-item refs and strips them from model views", () => {
    const proposal = frozenProposal();
    const cro = buildAcceptedCroRiskReview({
      submission: croSubmission(),
      behavior,
      frozenProposalId: proposal.proposal_id,
      frozenProposalHash: proposal.proposal_hash,
      frozenCandidateUniverseId: "candidate-set-1",
      frozenCandidateUniverseHash: "sha256:candidates",
      acceptedMacroInputAttributions: [],
    });
    const execution = buildAcceptedExecutionAssessment({
      submission: executionSubmission(),
      behavior,
      executionMode: "PAPER",
      frozenProposalId: proposal.proposal_id,
      frozenProposalHash: proposal.proposal_hash,
      croControlSource: {
        source_status: "ACCEPTED_OUTPUT",
        agent_id: "cro",
        accepted_output_id: cro.accepted_cro_review_id,
        accepted_output_hash: cro.accepted_cro_review_hash,
        stage_skip_id: null,
        stage_skip_hash: null,
      },
      frozenOrderIntentSetId: "intent-set-1",
      frozenOrderIntentSetHash: "sha256:intents",
    });
    const acceptedFinal = buildAcceptedCioFinal({
      submission: CioFinalSubmissionSchema.parse(finalSubmission()) as CioFinalSubmission,
      behavior,
      frozenProposal: proposal,
      frozenProposalId: proposal.proposal_id,
      frozenProposalHash: proposal.proposal_hash,
      croControlSource: {
        source_status: "ACCEPTED_OUTPUT",
        agent_id: "cro",
        accepted_output_id: cro.accepted_cro_review_id,
        accepted_output_hash: cro.accepted_cro_review_hash,
        stage_skip_id: null,
        stage_skip_hash: null,
      },
      executionControlSource: {
        source_status: "ACCEPTED_OUTPUT",
        agent_id: "autonomous_execution",
        accepted_output_id: execution.accepted_execution_assessment_id,
        accepted_output_hash: execution.accepted_execution_assessment_hash,
        stage_skip_id: null,
        stage_skip_hash: null,
      },
      acceptedCroReview: cro,
      acceptedExecutionAssessment: execution,
      acceptedMacroInputAttributions: [],
    });

    expect(acceptedFinal.cro_control_resolutions[0]?.cro_action_ref).toMatch(/^cro-action:/);
    expect(acceptedFinal.execution_control_resolutions[0]?.execution_assessment_ref).toMatch(
      /^execution-assessment:/,
    );
    expect(JSON.stringify(modelVisibleAcceptedDecision(cro))).not.toContain("cro_action_hash");
    expect(JSON.stringify(modelVisibleAcceptedDecision(execution))).not.toContain(
      "execution_assessment_hash",
    );
    expect(modelVisibleAcceptedDecision(acceptedFinal)).toEqual({
      agent_id: "cio",
      decision_stage: "FINAL",
      decision: acceptedFinal.decision,
    });
  });

  it("rejects omitted control resolutions and invalid portfolio totals", () => {
    expect(() =>
      CioFinalSubmissionSchema.parse({ ...finalSubmission(), cash_weight: 0.5 }),
    ).toThrow(/must equal 1/);

    const proposal = frozenProposal();
    const cro = buildAcceptedCroRiskReview({
      submission: croSubmission(),
      behavior,
      frozenProposalId: proposal.proposal_id,
      frozenProposalHash: proposal.proposal_hash,
      frozenCandidateUniverseId: "candidate-set-1",
      frozenCandidateUniverseHash: "sha256:candidates",
      acceptedMacroInputAttributions: [],
    });
    expect(() =>
      buildAcceptedCioFinal({
        submission: { ...finalSubmission(), cro_control_resolutions: [] },
        behavior,
        frozenProposal: proposal,
        frozenProposalId: proposal.proposal_id,
        frozenProposalHash: proposal.proposal_hash,
        croControlSource: {
          source_status: "ACCEPTED_OUTPUT",
          agent_id: "cro",
          accepted_output_id: cro.accepted_cro_review_id,
          accepted_output_hash: cro.accepted_cro_review_hash,
          stage_skip_id: null,
          stage_skip_hash: null,
        },
        executionControlSource: {
          source_status: "NO_EVALUATION_OBJECT",
          agent_id: "autonomous_execution",
          accepted_output_id: null,
          accepted_output_hash: null,
          stage_skip_id: "skip-execution-1",
          stage_skip_hash: "sha256:skip-execution",
        },
        acceptedCroReview: cro,
        acceptedExecutionAssessment: null,
        acceptedMacroInputAttributions: [],
      }),
    ).toThrow(/every non-NO_OBJECTION CRO action/);
  });

  it("revalidates FEASIBLE, PARTIAL, and BLOCKED execution outcomes in accepted payloads", () => {
    const proposal = frozenProposal();
    const skippedCro = {
      source_status: "NO_EVALUATION_OBJECT" as const,
      agent_id: "cro" as const,
      accepted_output_id: null,
      accepted_output_hash: null,
      stage_skip_id: "skip-cro-control-fixture",
      stage_skip_hash: "sha256:skip-cro-control-fixture",
    };
    const buildExecution = (
      feasibility: "FEASIBLE" | "PARTIAL" | "BLOCKED",
      maxExecutableDeltaWeight: number | null,
    ) =>
      buildAcceptedExecutionAssessment({
        submission: {
          ...executionSubmission(),
          order_assessments: [
            {
              ...executionSubmission().order_assessments[0],
              feasibility,
              max_executable_delta_weight: maxExecutableDeltaWeight,
            },
          ],
        },
        behavior,
        executionMode: "PAPER",
        frozenProposalId: proposal.proposal_id,
        frozenProposalHash: proposal.proposal_hash,
        croControlSource: skippedCro,
        frozenOrderIntentSetId: "intent-set-control-fixture",
        frozenOrderIntentSetHash: "sha256:intent-set-control-fixture",
      });
    const buildFinal = (
      execution: ReturnType<typeof buildExecution>,
      targetWeight: number,
      resolution: "COMPLIED" | "MORE_CONSERVATIVE",
    ) => {
      const base = finalSubmission();
      if (base.decision_disposition !== "TARGET_PORTFOLIO") {
        throw new Error("final fixture must contain a target portfolio");
      }
      const submission: CioFinalSubmission = {
        ...base,
        target_positions:
          targetWeight === 0 ? [] : [{ ...base.target_positions[0], target_weight: targetWeight }],
        decision_disposition: targetWeight === 0 ? "ALL_CASH" : "TARGET_PORTFOLIO",
        cash_weight: 1 - targetWeight,
        cro_control_resolutions: [],
        execution_control_resolutions: [
          {
            execution_assessment_local_ref: "execution-local-1",
            resolution,
            reason: "matches accepted execution capacity",
            claim_refs: ["claim-1"],
          },
        ],
      } as CioFinalSubmission;
      return buildAcceptedCioFinal({
        submission,
        behavior,
        frozenProposal: proposal,
        frozenProposalId: proposal.proposal_id,
        frozenProposalHash: proposal.proposal_hash,
        croControlSource: skippedCro,
        executionControlSource: {
          source_status: "ACCEPTED_OUTPUT",
          agent_id: "autonomous_execution",
          accepted_output_id: execution.accepted_execution_assessment_id,
          accepted_output_hash: execution.accepted_execution_assessment_hash,
          stage_skip_id: null,
          stage_skip_hash: null,
        },
        acceptedCroReview: null,
        acceptedExecutionAssessment: execution,
        acceptedMacroInputAttributions: [],
      });
    };

    const feasible = buildExecution("FEASIBLE", null);
    expect(buildFinal(feasible, 0.04, "COMPLIED").decision.target_positions[0]?.target_weight).toBe(
      0.04,
    );
    expect(() => buildFinal(feasible, 0.03, "MORE_CONSERVATIVE")).toThrow(
      /changed despite FEASIBLE execution/,
    );

    const partial = buildExecution("PARTIAL", 0.03);
    expect(buildFinal(partial, 0.03, "COMPLIED").decision.target_positions[0]?.target_weight).toBe(
      0.03,
    );
    expect(() => buildFinal(partial, 0.035, "MORE_CONSERVATIVE")).toThrow(
      /exceeds the accepted PARTIAL execution cap/,
    );

    const blocked = buildExecution("BLOCKED", 0);
    expect(buildFinal(blocked, 0, "COMPLIED").decision.decision_disposition).toBe("ALL_CASH");
    expect(() => buildFinal(blocked, 0.01, "MORE_CONSERVATIVE")).toThrow(
      /exceeds the accepted BLOCKED execution cap/,
    );
  });

  it("removes HOLD_CURRENT from structured CIO extraction when the portfolio is empty", () => {
    const final = finalSubmission();
    const {
      cro_control_resolutions: _croResolutions,
      execution_control_resolutions: _executionResolutions,
      ...proposalBase
    } = final;
    const emptyProposal = {
      ...proposalBase,
      decision_stage: "PROPOSAL",
      target_positions: [],
      cash_weight: 1,
    };
    const emptyFinal = {
      ...final,
      target_positions: [],
      cash_weight: 1,
    };

    expect(() =>
      CioProposalWithoutHoldSubmissionSchema.parse({
        ...emptyProposal,
        decision_disposition: "HOLD_CURRENT",
      }),
    ).toThrow();
    expect(() =>
      CioFinalWithoutHoldSubmissionSchema.parse({
        ...emptyFinal,
        decision_disposition: "HOLD_CURRENT",
      }),
    ).toThrow();
    expect(
      CioProposalWithoutHoldSubmissionSchema.parse({
        ...emptyProposal,
        decision_disposition: "ALL_CASH",
      }),
    ).toMatchObject({ decision_disposition: "ALL_CASH" });
    expect(
      CioFinalWithoutHoldSubmissionSchema.parse({
        ...emptyFinal,
        decision_disposition: "ALL_CASH",
      }),
    ).toMatchObject({ decision_disposition: "ALL_CASH" });
    expect(() => CioProposalAllCashSubmissionSchema.parse(finalSubmission())).toThrow();
    expect(() => CioFinalAllCashSubmissionSchema.parse(finalSubmission())).toThrow();
    expect(
      CioProposalAllCashSubmissionSchema.parse({
        ...emptyProposal,
        decision_disposition: "ALL_CASH",
      }),
    ).toMatchObject({ decision_disposition: "ALL_CASH" });
    expect(
      CioFinalAllCashSubmissionSchema.parse({
        ...emptyFinal,
        decision_disposition: "ALL_CASH",
      }),
    ).toMatchObject({ decision_disposition: "ALL_CASH" });
  });
});
