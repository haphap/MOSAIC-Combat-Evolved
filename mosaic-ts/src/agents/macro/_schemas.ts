import { createMacroSubmissionSchema, MACRO_SUBMISSION_FIELD_NAMES } from "./_contracts.js";

export const ChinaSchema = createMacroSubmissionSchema("china");
export const UsEconomySchema = createMacroSubmissionSchema("us_economy");
export const EuEconomySchema = createMacroSubmissionSchema("eu_economy");
export const CentralBankSchema = createMacroSubmissionSchema("central_bank");
export const UsFinancialConditionsSchema = createMacroSubmissionSchema("us_financial_conditions");
export const EuroAreaFinancialConditionsSchema = createMacroSubmissionSchema(
  "euro_area_financial_conditions",
);
export const CommoditiesSchema = createMacroSubmissionSchema("commodities");
export const GeopoliticalSchema = createMacroSubmissionSchema("geopolitical");
export const MarketBreadthSchema = createMacroSubmissionSchema("market_breadth");
export const InstitutionalFlowSchema = createMacroSubmissionSchema("institutional_flow");

export const CHINA_FIELD_NAMES = MACRO_SUBMISSION_FIELD_NAMES;
export const US_ECONOMY_FIELD_NAMES = MACRO_SUBMISSION_FIELD_NAMES;
export const EU_ECONOMY_FIELD_NAMES = MACRO_SUBMISSION_FIELD_NAMES;
export const CENTRAL_BANK_FIELD_NAMES = MACRO_SUBMISSION_FIELD_NAMES;
export const US_FINANCIAL_CONDITIONS_FIELD_NAMES = MACRO_SUBMISSION_FIELD_NAMES;
export const EURO_AREA_FINANCIAL_CONDITIONS_FIELD_NAMES = MACRO_SUBMISSION_FIELD_NAMES;
export const COMMODITIES_FIELD_NAMES = MACRO_SUBMISSION_FIELD_NAMES;
export const GEOPOLITICAL_FIELD_NAMES = MACRO_SUBMISSION_FIELD_NAMES;
export const MARKET_BREADTH_FIELD_NAMES = MACRO_SUBMISSION_FIELD_NAMES;
export const INSTITUTIONAL_FLOW_FIELD_NAMES = MACRO_SUBMISSION_FIELD_NAMES;
