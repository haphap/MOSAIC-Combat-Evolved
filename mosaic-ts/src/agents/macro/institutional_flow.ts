import type { InstitutionalFlowOutput } from "../types.js";
import { MACRO_ROLE_CONTRACTS } from "./_contracts.js";
import { buildLayerOneAgentNode, type LayerOneAgentDeps } from "./_factory.js";
import { INSTITUTIONAL_FLOW_FIELD_NAMES, InstitutionalFlowSchema } from "./_schemas.js";
import { macroAgentSpec, renderMacroTransmission } from "./_spec.js";

export const REQUIRED_TOOLS = MACRO_ROLE_CONTRACTS.institutional_flow.requiredTools;
export const institutionalFlowSpec = macroAgentSpec<InstitutionalFlowOutput>(
  "institutional_flow",
  InstitutionalFlowSchema,
);
export const buildInstitutionalFlowNode = (deps: LayerOneAgentDeps) =>
  buildLayerOneAgentNode(institutionalFlowSpec, deps);
export const renderInstitutionalFlow = renderMacroTransmission;
export { INSTITUTIONAL_FLOW_FIELD_NAMES, InstitutionalFlowSchema };
