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
  "execution_disposition",
  "order_assessments",
  "confidence",
  "claims",
  "claim_refs",
] as const;

export const CIO_FIELD_NAMES = [
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
