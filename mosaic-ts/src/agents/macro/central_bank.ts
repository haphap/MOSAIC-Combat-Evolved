import { MACRO_ROLE_CONTRACTS } from "./_contracts.js";
import { buildLayerOneAgentNode, type LayerOneAgentDeps } from "./_factory.js";
import { CENTRAL_BANK_FIELD_NAMES, CentralBankSchema } from "./_schemas.js";
import { macroAgentSpec, renderMacroTransmission } from "./_spec.js";

export const REQUIRED_TOOLS = MACRO_ROLE_CONTRACTS.central_bank.requiredTools;
export const centralBankSpec = macroAgentSpec("central_bank", CentralBankSchema);
export const buildCentralBankNode = (deps: LayerOneAgentDeps) =>
  buildLayerOneAgentNode(centralBankSpec, deps);
export const renderCentralBank = renderMacroTransmission;
export { CENTRAL_BANK_FIELD_NAMES, CentralBankSchema };
