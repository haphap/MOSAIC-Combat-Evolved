/**
 * Decision model-submission schemas.
 *
 * Accepted IDs, hashes, lineage, calibration, and runtime freeze fields are
 * deliberately absent: the runtime materializes those only after validating a
 * model-authored submission against its frozen object set.
 */

export {
  AlphaDiscoverySubmissionSchema as AlphaDiscoverySchema,
  AutonomousExecutionSubmissionSchema as AutonomousExecutionSchema,
  CioFinalSubmissionSchema as CioFinalSchema,
  CioFinalSubmissionSchema as CioSchema,
  CioProposalSubmissionSchema as CioProposalSchema,
  CroSubmissionSchema as CroSchema,
} from "./submission_schemas.js";

export const CRO_FIELD_NAMES = [
  "agent_id",
  "review_disposition",
  "candidate_actions",
  "correlated_risks",
  "black_swan_scenarios",
  "confidence",
  "claims",
  "claim_refs",
  "macro_input_attributions",
] as const;

export const ALPHA_DISCOVERY_FIELD_NAMES = [
  "agent_id",
  "discovery_disposition",
  "novel_picks",
  "key_drivers",
  "risks",
  "confidence",
  "claims",
  "claim_refs",
  "macro_input_attributions",
] as const;

export const AUTONOMOUS_EXECUTION_FIELD_NAMES = [
  "agent_id",
  "execution_disposition",
  "order_assessments",
  "confidence",
  "claims",
  "claim_refs",
] as const;

export const CIO_PROPOSAL_FIELD_NAMES = [
  "agent_id",
  "decision_stage",
  "decision_disposition",
  "target_positions",
  "cash_weight",
  "decision_reason",
  "confidence",
  "claims",
  "claim_refs",
  "macro_input_attributions",
] as const;

export const CIO_FINAL_FIELD_NAMES = [
  "agent_id",
  "decision_stage",
  "decision_disposition",
  "target_positions",
  "cash_weight",
  "decision_reason",
  "cro_control_resolutions",
  "execution_control_resolutions",
  "confidence",
  "claims",
  "claim_refs",
  "macro_input_attributions",
] as const;

/** All fields that may appear across the two CIO runtime stages. */
export const CIO_FIELD_NAMES = CIO_FINAL_FIELD_NAMES;
