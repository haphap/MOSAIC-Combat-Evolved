import { MACRO_ROLE_CONTRACTS } from "./_contracts.js";
import { buildLayerOneAgentNode, type LayerOneAgentDeps } from "./_factory.js";
import { US_FINANCIAL_CONDITIONS_FIELD_NAMES, UsFinancialConditionsSchema } from "./_schemas.js";
import { macroAgentSpec, renderMacroTransmission } from "./_spec.js";

export const REQUIRED_TOOLS = MACRO_ROLE_CONTRACTS.us_financial_conditions.requiredTools;
export const usFinancialConditionsSpec = macroAgentSpec(
  "us_financial_conditions",
  UsFinancialConditionsSchema,
);
export const buildUsFinancialConditionsNode = (deps: LayerOneAgentDeps) =>
  buildLayerOneAgentNode(usFinancialConditionsSpec, deps);
export const renderUsFinancialConditions = renderMacroTransmission;
export { US_FINANCIAL_CONDITIONS_FIELD_NAMES, UsFinancialConditionsSchema };
