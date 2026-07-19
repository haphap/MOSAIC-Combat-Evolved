import { MACRO_ROLE_CONTRACTS } from "./_contracts.js";
import { buildLayerOneAgentNode, type LayerOneAgentDeps } from "./_factory.js";
import {
  EURO_AREA_FINANCIAL_CONDITIONS_FIELD_NAMES,
  EuroAreaFinancialConditionsSchema,
} from "./_schemas.js";
import { macroAgentSpec, renderMacroTransmission } from "./_spec.js";

export const REQUIRED_TOOLS = MACRO_ROLE_CONTRACTS.euro_area_financial_conditions.requiredTools;
export const euroAreaFinancialConditionsSpec = macroAgentSpec(
  "euro_area_financial_conditions",
  EuroAreaFinancialConditionsSchema,
);
export const buildEuroAreaFinancialConditionsNode = (deps: LayerOneAgentDeps) =>
  buildLayerOneAgentNode(euroAreaFinancialConditionsSpec, deps);
export const renderEuroAreaFinancialConditions = renderMacroTransmission;
export { EURO_AREA_FINANCIAL_CONDITIONS_FIELD_NAMES, EuroAreaFinancialConditionsSchema };
