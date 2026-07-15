/** Compatibility exports for the code-generated uniform macro contract. */
import type { z } from "zod";
import type {
  CentralBankOutput,
  ChinaOutput,
  CommoditiesOutput,
  DollarOutput,
  GeopoliticalOutput,
  InstitutionalFlowOutput,
  MarketBreadthOutput,
  UsEconomyOutput,
  VolatilityOutput,
  YieldCurveOutput,
} from "../types.js";
import { createMacroOutputSchema, MACRO_OUTPUT_FIELD_NAMES } from "./_contracts.js";

export const ChinaSchema = createMacroOutputSchema("china");
export const UsEconomySchema = createMacroOutputSchema("us_economy");
export const CentralBankSchema = createMacroOutputSchema("central_bank");
export const DollarSchema = createMacroOutputSchema("dollar");
export const YieldCurveSchema = createMacroOutputSchema("yield_curve");
export const CommoditiesSchema = createMacroOutputSchema("commodities");
export const GeopoliticalSchema = createMacroOutputSchema("geopolitical");
export const VolatilitySchema = createMacroOutputSchema("volatility");
export const MarketBreadthSchema = createMacroOutputSchema("market_breadth");
export const InstitutionalFlowSchema = createMacroOutputSchema("institutional_flow");

export const CHINA_FIELD_NAMES = MACRO_OUTPUT_FIELD_NAMES;
export const US_ECONOMY_FIELD_NAMES = MACRO_OUTPUT_FIELD_NAMES;
export const CENTRAL_BANK_FIELD_NAMES = MACRO_OUTPUT_FIELD_NAMES;
export const DOLLAR_FIELD_NAMES = MACRO_OUTPUT_FIELD_NAMES;
export const YIELD_CURVE_FIELD_NAMES = MACRO_OUTPUT_FIELD_NAMES;
export const COMMODITIES_FIELD_NAMES = MACRO_OUTPUT_FIELD_NAMES;
export const GEOPOLITICAL_FIELD_NAMES = MACRO_OUTPUT_FIELD_NAMES;
export const VOLATILITY_FIELD_NAMES = MACRO_OUTPUT_FIELD_NAMES;
export const MARKET_BREADTH_FIELD_NAMES = MACRO_OUTPUT_FIELD_NAMES;
export const INSTITUTIONAL_FLOW_FIELD_NAMES = MACRO_OUTPUT_FIELD_NAMES;

type Shape<T, U> = T extends U ? true : never;
const guards: [
  Shape<z.infer<typeof ChinaSchema>, ChinaOutput>,
  Shape<z.infer<typeof UsEconomySchema>, UsEconomyOutput>,
  Shape<z.infer<typeof CentralBankSchema>, CentralBankOutput>,
  Shape<z.infer<typeof DollarSchema>, DollarOutput>,
  Shape<z.infer<typeof YieldCurveSchema>, YieldCurveOutput>,
  Shape<z.infer<typeof CommoditiesSchema>, CommoditiesOutput>,
  Shape<z.infer<typeof GeopoliticalSchema>, GeopoliticalOutput>,
  Shape<z.infer<typeof VolatilitySchema>, VolatilityOutput>,
  Shape<z.infer<typeof MarketBreadthSchema>, MarketBreadthOutput>,
  Shape<z.infer<typeof InstitutionalFlowSchema>, InstitutionalFlowOutput>,
] = [true, true, true, true, true, true, true, true, true, true];
void guards;
