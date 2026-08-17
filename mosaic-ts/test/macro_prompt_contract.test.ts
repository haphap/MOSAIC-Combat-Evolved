import { readdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  MACRO_AGENT_IDS,
  MACRO_PROMPT_COHORT_IDS,
  MACRO_ROLE_CONTRACTS,
  renderMacroPromptBody,
  TOMBSTONED_MACRO_AGENT_IDS,
} from "../src/agents/macro/_contracts.js";
import { renderBundledPrompt } from "../src/agents/prompts/bundled_prompt_renderer.js";
import { ALL_AGENTS, LAYER_BY_AGENT } from "../src/agents/prompts/cohorts.js";
import { RUNTIME_AGENT_SPECS } from "../src/agents/prompts/runtime_agent_spec.js";
import { upsertRuntimeEvidenceContract } from "../src/agents/prompts/runtime_evidence_contract.js";

const root = resolve(process.cwd(), "..", "prompts", "mosaic", "cohort_default", "macro");
const repositoryRoot = resolve(process.cwd(), "..");
const promptReleaseContractRef = JSON.parse(
  readFileSync(
    resolve(repositoryRoot, "registry", "prompt_checks", "prompt_release_contract_ref_v2.json"),
    "utf8",
  ),
) as { sources: { execution_behavior_release_archive: { path: string } } };
const executionRelease = JSON.parse(
  readFileSync(
    resolve(
      repositoryRoot,
      promptReleaseContractRef.sources.execution_behavior_release_archive.path,
    ),
    "utf8",
  ),
) as {
  schema_version: string;
  execution_behavior_release_id: string;
  execution_behavior_release_hash: string;
  execution_contracts: Array<{ agent_id: string; language: string }>;
};

function prompt(agent: string, language: "zh" | "en") {
  return readFileSync(join(root, `${agent}.${language}.md`), "utf8");
}

describe("generated bundled macro prompts", () => {
  it("contains exactly eight bilingual current roles", () => {
    expect(
      readdirSync(root)
        .filter((file) => file.endsWith(".md"))
        .sort(),
    ).toEqual(MACRO_AGENT_IDS.flatMap((agent) => [`${agent}.en.md`, `${agent}.zh.md`]).sort());
  });

  it("pins the rebuilt execution behavior contracts", () => {
    expect(executionRelease.schema_version).toBe("execution_behavior_release_manifest_v4");
    expect(executionRelease.execution_contracts).toHaveLength(54);
    const releaseAgents = new Set(executionRelease.execution_contracts.map((row) => row.agent_id));
    expect(ALL_AGENTS.every((agent) => releaseAgents.has(agent))).toBe(true);
    expect(
      [...new Set(executionRelease.execution_contracts.map((row) => row.language))].sort(),
    ).toEqual(["en", "zh"]);
    expect(executionRelease.execution_behavior_release_id).toMatch(
      /^execution-behavior-release:[0-9a-f]{64}$/,
    );
    expect(executionRelease.execution_behavior_release_hash).toMatch(/^sha256:[0-9a-f]{64}$/);
    expect(TOMBSTONED_MACRO_AGENT_IDS).toEqual([
      "dollar",
      "yield_curve",
      "volatility",
      "emerging_markets",
      "news_sentiment",
      "geopolitical",
    ]);
  });

  it.each(MACRO_AGENT_IDS)("binds %s to one role-scoped tool and exact mode schema", (agent) => {
    for (const language of ["zh", "en"] as const) {
      const text = prompt(agent, language);
      const tools = [...new Set(text.match(/\bget_[a-z0-9_]+\b/g) ?? [])];
      expect(tools).toEqual(MACRO_ROLE_CONTRACTS[agent].requiredTools);
      expect(text).toContain(MACRO_ROLE_CONTRACTS[agent].responsibility[language]);
      expect(text).toContain(language === "zh" ? "运行时 schema" : "runtime schema");
      const block = text.match(
        /<!-- runtime-evidence-contract:start -->([\s\S]*?)<!-- runtime-evidence-contract:end -->/,
      )?.[1];
      expect(block).toBeDefined();
      const fieldLine = block
        ?.split("\n")
        .find((line) => /(?:输出字段包括|Output fields include)/u.test(line));
      expect(fieldLine).toBeDefined();
      expect(fieldLine).not.toContain("`claim_refs`");
      expect(block).toContain(
        language === "zh"
          ? "不得输出顶层 `claim_refs`"
          : "do not emit a top-level `claim_refs` field",
      );
      if (MACRO_ROLE_CONTRACTS[agent].mode === "DIRECT") {
        expect(fieldLine).toContain("`signal`");
        expect(block).toContain("`signal.claim_refs`");
        expect(fieldLine).not.toContain("`components`");
      } else {
        expect(fieldLine).toContain("`components`");
        expect(block).toContain("`components[].claim_refs`");
        expect(block).toContain(
          language === "zh" ? "不与其他组件共享的 claim" : "that no other component cites",
        );
        expect(block).toContain("`structured_conclusion.subject`");
        expect(block).toContain("`component` id");
        expect(fieldLine).not.toContain("`signal`");
      }
      expect(text).not.toMatch(
        /direction[^\n]+strength[^\n]+persistence_horizon[^\n]+evaluation_horizon_trading_days/,
      );
      expect(text).not.toContain("```json");
      expect(text).not.toContain("```research-knobs");
      expect(text).not.toMatch(/domain knob|knob influence/i);
      expect(text).not.toContain("retail_sentiment_score");
      expect(text).not.toContain("contrarian_flag");
      expect(text).not.toMatch(/required tools[^\n]*(get_news|get_caixin|get_xueqiu)/i);
    }
  });

  it.each(MACRO_AGENT_IDS)("keeps generated bundled %s prompts synchronized", (agent) => {
    const spec = RUNTIME_AGENT_SPECS.find((candidate) => candidate.agent === agent);
    expect(spec).toBeDefined();
    if (!spec) throw new Error(`missing runtime spec for ${agent}`);
    for (const language of ["zh", "en"] as const) {
      const expected = upsertRuntimeEvidenceContract(
        renderMacroPromptBody(agent, language, "cohort_default"),
        spec,
        language,
      );
      expect(prompt(agent, language)).toBe(expected);
    }
  });

  it("binds China components to PIT evidence and the independent 5D role-path outcome", () => {
    const spec = RUNTIME_AGENT_SPECS.find((candidate) => candidate.agent === "china");
    expect(spec).toBeDefined();
    if (!spec) throw new Error("missing china runtime spec");
    const zh = prompt("china", "zh");
    const en = prompt("china", "en");
    expect(zh).toBe(
      upsertRuntimeEvidenceContract(
        renderMacroPromptBody("china", "zh", "cohort_default"),
        spec,
        "zh",
      ),
    );
    expect(en).toBe(
      upsertRuntimeEvidenceContract(
        renderMacroPromptBody("china", "en", "cohort_default"),
        spec,
        "en",
      ),
    );
    expect(zh).toContain("get_china_macro_snapshot 是 PIT observations/releases，不是 A 股信号");
    expect(zh).toContain("actual、expected、previous 及 release/vintage/as-of");
    expect(zh).toContain("数值事实只能写入结构化 snapshot echo 字段，不得写入叙述");
    expect(zh).toContain("growth_production 将 production、investment、retail、employment");
    expect(zh).toContain("prices 将 CPI/PPI 传导到 nominal revenue、pricing power 与 margins");
    expect(zh).toContain("credit 将 TSF、loans 与 money impulse");
    expect(zh).toContain("不得判断 central-bank reaction");
    expect(zh).toContain("external_demand_trade 将 exports、imports 与 trade balance");
    expect(zh).toContain(
      "fiscal 将 revenue/spending impulse 传导到 infrastructure 与 domestic demand",
    );
    expect(zh).toContain("Property 仅在实际已注册 evidence 存在且相关时可选，绝非必需");
    expect(zh).toContain("每个组件必须使用精确 subject id");
    expect(zh).toContain("若证据不能支持全部五个精确组件");
    expect(zh).toContain("不得伪造 neutral");
    expect(zh).toContain("实际 get_china_macro_snapshot result event 的真实 evidence_id");
    expect(zh).toContain("当前证据不是已实现的 5D 结果");
    expect(zh).toContain("event-triggered、T+1 open 后 5 个交易日");
    expect(zh).toContain("按 PIT volatility 归一化的 A-share role-path outcome");
    expect(zh).toContain("半年一次的 component weights");
    expect(zh).not.toContain("KNOT");
    expect(zh).toContain("fallback=false 表示缺失证据必须拒绝");
    expect(zh).toContain("不得判断 PBOC reaction function");
    expect(en).toContain("PIT observations and releases, not an A-share signal");
    expect(en).toContain("numeric facts belong only in structured snapshot echo fields");
    expect(en).toContain("Every component must use its exact subject id");
    expect(en).toContain(
      "real evidence_id values from the actual get_china_macro_snapshot result event",
    );
    expect(en).toContain(
      "event-triggered A-share role-path outcome over 5 trading days after T+1 open",
    );
    expect(en).toContain("normalized by PIT volatility");
    expect(en).toContain("semiannual component weights");
    expect(en).not.toContain("KNOT");
    expect(en).toContain("fallback=false means missing evidence must be rejected");
    expect(renderMacroPromptBody("institutional_flow", "en", "cohort_default")).not.toContain(
      "semiannual component weights",
    );
  });

  it("binds Central Bank components to PIT policy evidence and the independent 5D role path", () => {
    const spec = RUNTIME_AGENT_SPECS.find((candidate) => candidate.agent === "central_bank");
    expect(spec).toBeDefined();
    if (!spec) throw new Error("missing central_bank runtime spec");
    const zh = prompt("central_bank", "zh");
    const en = prompt("central_bank", "en");
    expect(zh).toBe(
      upsertRuntimeEvidenceContract(
        renderMacroPromptBody("central_bank", "zh", "cohort_default"),
        spec,
        "zh",
      ),
    );
    expect(en).toBe(
      upsertRuntimeEvidenceContract(
        renderMacroPromptBody("central_bank", "en", "cohort_default"),
        spec,
        "en",
      ),
    );
    expect(zh).toContain("PIT PBOC/domestic-liquidity evidence，不是 A 股信号");
    expect(zh).toContain("仅在字段存在时使用 actual、expected、previous 与 release/vintage/as-of");
    expect(zh).toContain("数值事实只能写入结构化 snapshot echo 字段，不得写入叙述");
    expect(zh).toContain("pboc_policy_bias 只用 OMO、LPR 与官方政策 evidence");
    expect(zh).toContain("liquidity_money_market 只用 OMO liquidity 与 Shibor ON/3M");
    expect(zh).toContain("china_curve 只用 registered nominal CGB 2Y/10Y 及 slope");
    expect(zh).toContain("绝不得声称 real curve");
    expect(zh).toContain("credit_conditions 只用已注册 TSF/credit context");
    expect(zh).toContain("不得把 China macro LLM 当作 evidence");
    expect(zh).toContain("每个组件必须使用精确 subject id");
    expect(zh).toContain("若证据不能支持全部四个精确组件");
    expect(zh).toContain("实际 get_central_bank_snapshot result event 的真实 evidence_id");
    expect(zh).toContain("当前证据不是已实现的 5D 结果");
    expect(zh).toContain("event-triggered、T+1 open 后 5 个交易日");
    expect(zh).toContain("按 PIT volatility 归一化的 A-share role-path outcome");
    expect(zh).toContain("半年一次的 component weights");
    expect(zh).not.toContain("KNOT");
    expect(zh).toContain("fallback=false 表示缺失证据必须拒绝");
    expect(en).toContain("PIT PBOC and domestic-liquidity evidence, not an A-share signal");
    expect(en).toContain("OMO, LPR, and official policy evidence");
    expect(en).toContain("OMO liquidity and Shibor ON/3M");
    expect(en).toContain("registered nominal CGB 2Y/10Y and their slope");
    expect(en).toContain("registered TSF/credit context");
    expect(en).toContain(
      "real evidence_id values from the actual get_central_bank_snapshot result event",
    );
    expect(en).toContain("semiannual component weights");
    expect(en).not.toContain("KNOT");
    expect(renderMacroPromptBody("institutional_flow", "en", "cohort_default")).not.toContain(
      "registered nominal CGB 2Y/10Y and their slope",
    );
  });

  it("binds US Financial Conditions components to PIT evidence and the independent 5D role path", () => {
    const spec = RUNTIME_AGENT_SPECS.find(
      (candidate) => candidate.agent === "us_financial_conditions",
    );
    expect(spec).toBeDefined();
    if (!spec) throw new Error("missing us_financial_conditions runtime spec");
    const zh = prompt("us_financial_conditions", "zh");
    const en = prompt("us_financial_conditions", "en");
    expect(zh).toBe(
      upsertRuntimeEvidenceContract(
        renderMacroPromptBody("us_financial_conditions", "zh", "cohort_default"),
        spec,
        "zh",
      ),
    );
    expect(en).toBe(
      upsertRuntimeEvidenceContract(
        renderMacroPromptBody("us_financial_conditions", "en", "cohort_default"),
        spec,
        "en",
      ),
    );
    expect(zh).toContain("PIT US financial evidence，不是 A 股信号");
    expect(zh).toContain("仅在字段存在时使用 actual、expected、previous 与 release/vintage/as-of");
    expect(zh).toContain("数值事实只能写入结构化 snapshot echo 字段，不得写入叙述");
    expect(zh).toContain("fed_liquidity 只用 FOMC statement 与 EFFR/SOFR");
    expect(zh).toContain("不得重述 US growth");
    expect(zh).toContain("Tushare nominal 3M/2Y/10Y/30Y");
    expect(zh).toContain("ALFRED real 5Y/10Y/30Y");
    expect(zh).toContain("credit_financial_stress 只用 BAA10Y、NFCI 与 VIX");
    expect(zh).toContain("USDCNH.FXCM offshore CNH proxy");
    expect(zh).toContain("绝不得称为 onshore CNY fixing 或 settlement");
    expect(zh).toContain("us_economy deterministic context 仅作背景");
    expect(zh).toContain("不得成为第五个组件、替代 claim evidence 或读取其 LLM");
    expect(zh).toContain("每个组件必须使用精确 subject id");
    expect(zh).toContain("若证据不能支持全部四个精确组件");
    expect(zh).toContain(
      "实际 get_us_financial_conditions_snapshot result event 的真实 evidence_id",
    );
    expect(zh).toContain("当前证据不是已实现的 5D 结果");
    expect(zh).toContain("独立、fixed non-overlapping、T+1 open 后 5 个交易日");
    expect(zh).toContain("按 PIT volatility 归一化的 outcome");
    expect(zh).toContain("半年一次的 component weights");
    expect(zh).not.toContain("KNOT");
    expect(zh).toContain("fallback=false 表示缺失证据必须拒绝");
    expect(en).toContain("PIT US financial evidence, not an A-share signal");
    expect(en).toContain("FOMC statement and EFFR/SOFR");
    expect(en).toContain("Tushare nominal 3M/2Y/10Y/30Y");
    expect(en).toContain("ALFRED real 5Y/10Y/30Y");
    expect(en).toContain("BAA10Y, NFCI, and VIX");
    expect(en).toContain("actual USDCNH.FXCM offshore CNH proxy");
    expect(en).toContain("must never call it an onshore CNY fixing or settlement rate");
    expect(en).toContain(
      "real evidence_id values from the actual get_us_financial_conditions_snapshot result event",
    );
    expect(en).toContain("independent, fixed non-overlapping outcome");
    expect(en).toContain("semiannual component weights");
    expect(en).not.toContain("KNOT");
    expect(renderMacroPromptBody("institutional_flow", "en", "cohort_default")).not.toContain(
      "actual USDCNH.FXCM offshore CNH proxy",
    );
  });

  it("binds Euro Area Financial Conditions components to PIT evidence and the independent 5D role path", () => {
    const spec = RUNTIME_AGENT_SPECS.find(
      (candidate) => candidate.agent === "euro_area_financial_conditions",
    );
    expect(spec).toBeDefined();
    if (!spec) throw new Error("missing euro_area_financial_conditions runtime spec");
    const zh = prompt("euro_area_financial_conditions", "zh");
    const en = prompt("euro_area_financial_conditions", "en");
    expect(zh).toBe(
      upsertRuntimeEvidenceContract(
        renderMacroPromptBody("euro_area_financial_conditions", "zh", "cohort_default"),
        spec,
        "zh",
      ),
    );
    expect(en).toBe(
      upsertRuntimeEvidenceContract(
        renderMacroPromptBody("euro_area_financial_conditions", "en", "cohort_default"),
        spec,
        "en",
      ),
    );
    expect(zh).toContain("PIT ECB/euro financial evidence，不是 A 股信号");
    expect(zh).toContain("仅在字段存在时使用 actual、expected、previous 与 release/vintage/as-of");
    expect(zh).toContain("数值事实只能写入结构化 snapshot echo 字段，不得写入叙述");
    expect(zh).toContain("ecb_liquidity 只用 DFR、MRR 与 €STR");
    expect(zh).toContain("不得重述 EU growth");
    expect(zh).toContain("euro_area_curve 只用 registered AAA nominal 2Y/10Y");
    expect(zh).toContain("bank_credit 只用 euro-area NFC adjusted loan growth");
    expect(zh).toContain("corporation new-business loan rate");
    expect(zh).toContain("ECB USD/EUR reference、实际 EURUSD.FXCM");
    expect(zh).toContain("registered joint bank/sovereign default-probability stress indicators");
    expect(zh).toContain("不得虚构 RDF 的地域或机制");
    expect(zh).toContain("eu_economy deterministic context 仅作背景");
    expect(zh).toContain("不得成为第五个组件、替代 claim evidence 或读取其 LLM");
    expect(zh).toContain("不得纳入非欧元区央行或市场");
    expect(zh).toContain("每个组件必须使用精确 subject id");
    expect(zh).toContain("若证据不能支持全部四个精确组件");
    expect(zh).toContain(
      "实际 get_euro_area_financial_conditions_snapshot result event 的真实 evidence_id",
    );
    expect(zh).toContain("当前证据不是已实现的 5D 结果");
    expect(zh).toContain("独立、fixed non-overlapping、T+1 open 后 5 个交易日");
    expect(zh).toContain("半年一次的 component weights");
    expect(zh).not.toContain("KNOT");
    expect(zh).toContain("fallback=false 表示缺失证据必须拒绝");
    expect(en).toContain("PIT ECB and euro financial evidence, not an A-share signal");
    expect(en).toContain("DFR, MRR, and €STR");
    expect(en).toContain("registered AAA nominal 2Y/10Y");
    expect(en).toContain("euro-area NFC adjusted loan growth");
    expect(en).toContain("ECB USD/EUR reference rate, actual EURUSD.FXCM");
    expect(en).toContain("registered joint bank/sovereign default-probability stress indicators");
    expect(en).toContain("without inventing RDF geography or mechanisms");
    expect(en).toContain(
      "real evidence_id values from the actual get_euro_area_financial_conditions_snapshot result event",
    );
    expect(en).toContain("independent, fixed non-overlapping outcome");
    expect(en).toContain("semiannual component weights");
    expect(en).not.toContain("KNOT");
    expect(renderMacroPromptBody("institutional_flow", "en", "cohort_default")).not.toContain(
      "registered joint bank/sovereign default-probability stress indicators",
    );
  });

  it("binds Commodities components to registered families and the independent 5D role path", () => {
    const spec = RUNTIME_AGENT_SPECS.find((candidate) => candidate.agent === "commodities");
    expect(spec).toBeDefined();
    if (!spec) throw new Error("missing commodities runtime spec");
    const zh = prompt("commodities", "zh");
    const en = prompt("commodities", "en");
    expect(zh).toBe(
      upsertRuntimeEvidenceContract(
        renderMacroPromptBody("commodities", "zh", "cohort_default"),
        spec,
        "zh",
      ),
    );
    expect(en).toBe(
      upsertRuntimeEvidenceContract(
        renderMacroPromptBody("commodities", "en", "cohort_default"),
        spec,
        "en",
      ),
    );
    expect(zh).toContain("五个已登记 commodity families 的 PIT 合约、结算与库存 evidence");
    expect(zh).toContain("不得虚构 expected、surprise 或工具未提供的宏观因果");
    expect(zh).toContain("数值事实只能写入结构化 snapshot echo 字段，不得写入叙述");
    expect(zh).toContain("energy 只用 SC@INE 的原油期限结构与库存");
    expect(zh).toContain("industrial_metals 只用 CU@SHFE");
    expect(zh).toContain("gold 只用 AU@SHFE");
    expect(zh).toContain("不得超出工具实际字段声称宏观因果");
    expect(zh).toContain("agriculture_food 只用 C@DCE 与 M@DCE");
    expect(zh).toContain("实际两个合约的数据时，才可称 contango 或 backwardation");
    expect(zh).toContain("每个组件必须使用精确 subject id");
    expect(zh).toContain("冲突必须降低 confidence/strength");
    expect(zh).toContain("若证据不能支持全部四个精确组件");
    expect(zh).toContain("实际 get_commodity_conditions_snapshot result event 的真实 evidence_id");
    expect(zh).toContain("当前证据不是已实现的 5D 结果");
    expect(zh).toContain("独立、fixed non-overlapping、T+1 open 后 5 个交易日");
    expect(zh).toContain("半年一次的 component weights");
    expect(zh).not.toContain("KNOT");
    expect(zh).toContain("fallback=false 表示缺失证据必须拒绝");
    expect(en).toContain("five registered commodity families, not an A-share signal");
    expect(en).toContain("SC@INE crude-oil term structure and inventory");
    expect(en).toContain("CU@SHFE");
    expect(en).toContain("AU@SHFE");
    expect(en).toContain("C@DCE and M@DCE");
    expect(en).toContain("actual data for two contracts");
    expect(en).toContain(
      "real evidence_id values from the actual get_commodity_conditions_snapshot result event",
    );
    expect(en).toContain("independent, fixed non-overlapping outcome");
    expect(en).toContain("semiannual component weights");
    expect(en).not.toContain("KNOT");
    expect(renderMacroPromptBody("institutional_flow", "en", "cohort_default")).not.toContain(
      "SC@INE crude-oil term structure and inventory",
    );
  });

  it("binds Institutional Flow claims to fixed ETF shares and the independent 5D follow-through", () => {
    const spec = RUNTIME_AGENT_SPECS.find((candidate) => candidate.agent === "institutional_flow");
    expect(spec).toBeDefined();
    if (!spec) throw new Error("missing institutional_flow runtime spec");
    const zh = prompt("institutional_flow", "zh");
    const en = prompt("institutional_flow", "en");
    expect(zh).toBe(
      upsertRuntimeEvidenceContract(
        renderMacroPromptBody("institutional_flow", "zh", "cohort_default"),
        spec,
        "zh",
      ),
    );
    expect(en).toBe(
      upsertRuntimeEvidenceContract(
        renderMacroPromptBody("institutional_flow", "en", "cohort_default"),
        spec,
        "en",
      ),
    );
    expect(zh).toContain("159915.SZ、510050.SH、510300.SH、510500.SH、588000.SH");
    expect(zh).toContain("fd_share，单位为万份");
    expect(zh).toContain("只表示申购或赎回事实，只能作为配置/positioning 代理");
    expect(zh).toContain("不得称为资金净流入、北向资金、机构持仓所有权或主动买卖金额");
    expect(zh).toContain("缺少 price、NAV 与 cash 时不得计算资金流");
    expect(zh).toContain("不得声称份额变化导致未来价格");
    expect(zh).toContain("每只 ETF 的 accepted claim");
    expect(zh).toContain("实际 get_market_positioning_snapshot result event 的真实 evidence_id");
    expect(zh).toContain("当前证据不是已实现的未来 5D 结果");
    expect(zh).toContain("510500.SH 相对 benchmark、T+1 open 后 5 个交易日");
    expect(zh).toContain("按 PIT volatility 归一化");
    expect(zh).toContain("经济 signal 可诚实为 UNKNOWN");
    expect(zh).toContain("固定五只 ETF 任一缺失时按现有 stage contract 拒绝");
    expect(zh).toContain("fallback=false");
    expect(en).toContain("PIT fd_share observations, measured in ten-thousand shares");
    expect(en).toContain("creation or redemption only");
    expect(en).toContain("allocation/positioning proxy");
    expect(en).toContain(
      "never call it net fund inflow, northbound flow, institutional ownership, or active buy/sell amount",
    );
    expect(en).toContain("Without price, NAV, and cash, do not calculate fund flow");
    expect(en).toContain("Each ETF's accepted claim must separately cite a real evidence_id");
    expect(en).toContain("independent 510500.SH-relative-to-benchmark outcome");
    expect(en).toContain("5 trading days after T+1 open");
    expect(en).toContain("may honestly project an UNKNOWN economic signal");
    expect(en).toContain("If any of the five fixed ETFs is missing");
    expect(renderMacroPromptBody("commodities", "en", "cohort_default")).not.toContain(
      "independent 510500.SH-relative-to-benchmark outcome",
    );
  });

  it("binds US Economy components to PIT ALFRED evidence and the independent 5D role path", () => {
    const spec = RUNTIME_AGENT_SPECS.find((candidate) => candidate.agent === "us_economy");
    expect(spec).toBeDefined();
    if (!spec) throw new Error("missing us_economy runtime spec");
    const zh = prompt("us_economy", "zh");
    const en = prompt("us_economy", "en");
    expect(zh).toBe(
      upsertRuntimeEvidenceContract(
        renderMacroPromptBody("us_economy", "zh", "cohort_default"),
        spec,
        "zh",
      ),
    );
    expect(en).toBe(
      upsertRuntimeEvidenceContract(
        renderMacroPromptBody("us_economy", "en", "cohort_default"),
        spec,
        "en",
      ),
    );
    expect(zh).toContain("get_us_macro_snapshot 包含 PIT ALFRED real-economy observations");
    expect(zh).toContain("仅在字段存在时使用 actual、previous、expected 与 release/vintage/as-of");
    expect(zh).toContain("不得虚构缺失的 consensus 或 surprise");
    expect(zh).toContain("数值事实只能写入结构化 snapshot echo 字段");
    expect(zh).toContain("growth_production 将 real GDP 与 industrial production");
    expect(zh).toContain("US activity/import demand");
    expect(zh).toContain("prices 将 CPI、core CPI、PCE 与 core PCE");
    expect(zh).toContain("不得推断 Fed、USD、yield curve 或 credit conditions");
    expect(zh).toContain("employment 将 payrolls 与 unemployment");
    expect(zh).toContain("household income/consumption");
    expect(zh).toContain("demand_trade 将 retail sales 与 trade balance");
    expect(zh).toContain("US final demand/import absorption");
    expect(zh).toContain("每个组件必须使用精确 subject id");
    expect(zh).toContain("若证据不能支持全部四个精确组件");
    expect(zh).toContain("实际 get_us_macro_snapshot result event 的真实 evidence_id");
    expect(zh).toContain("当前证据不是已实现的 5D 结果");
    expect(zh).toContain("event-triggered、T+1 open 后 5 个交易日");
    expect(zh).toContain("按 PIT volatility 归一化的 A-share role-path outcome");
    expect(zh).toContain("半年一次的 component weights");
    expect(zh).not.toContain("KNOT");
    expect(zh).toContain("fallback=false 表示缺失证据必须拒绝");
    expect(zh).toContain("不得生成跨 Agent 结论");
    expect(en).toContain("PIT ALFRED real-economy observations, not an A-share signal");
    expect(en).toContain("only when those fields are present");
    expect(en).toContain("never invent missing consensus or surprise");
    expect(en).toContain("Every component must use its exact subject id");
    expect(en).toContain(
      "real evidence_id values from the actual get_us_macro_snapshot result event",
    );
    expect(en).toContain(
      "event-triggered A-share role-path outcome over 5 trading days after T+1 open",
    );
    expect(en).toContain("normalized by PIT volatility");
    expect(en).toContain("semiannual component weights");
    expect(en).not.toContain("KNOT");
    expect(en).toContain("fallback=false means missing evidence must be rejected");
    expect(renderMacroPromptBody("eu_economy", "en", "cohort_default")).not.toContain(
      "PIT ALFRED real-economy observations",
    );
  });

  it("binds EU Economy components to PIT EU-27 evidence and the independent 5D role path", () => {
    const spec = RUNTIME_AGENT_SPECS.find((candidate) => candidate.agent === "eu_economy");
    expect(spec).toBeDefined();
    if (!spec) throw new Error("missing eu_economy runtime spec");
    const zh = prompt("eu_economy", "zh");
    const en = prompt("eu_economy", "en");
    expect(zh).toBe(
      upsertRuntimeEvidenceContract(
        renderMacroPromptBody("eu_economy", "zh", "cohort_default"),
        spec,
        "zh",
      ),
    );
    expect(en).toBe(
      upsertRuntimeEvidenceContract(
        renderMacroPromptBody("eu_economy", "en", "cohort_default"),
        spec,
        "en",
      ),
    );
    expect(zh).toContain(
      "get_eu_macro_snapshot 包含 PIT registered EU-27 real-economy observations",
    );
    expect(zh).toContain("仅在字段存在时使用 actual、previous、expected 与 release/vintage/as-of");
    expect(zh).toContain("不得虚构缺失的 consensus 或 surprise");
    expect(zh).toContain("数值事实只能写入结构化 snapshot echo 字段");
    expect(zh).toContain("growth_production 将 EU GDP 与 industrial production");
    expect(zh).toContain("European activity/import demand");
    expect(zh).toContain("prices 将 HICP 经 European inflation 与 real purchasing power");
    expect(zh).toContain("不得推断 ECB、FX、curves、bank credit 或 financial stress");
    expect(zh).toContain("employment 将 unemployment 与 labour conditions");
    expect(zh).toContain("household income/consumption");
    expect(zh).toContain("demand_trade 将 imports、exports 与 household consumption");
    expect(zh).toContain("EU final demand/import absorption");
    expect(zh).toContain("范围仅限 EU-27；排除 UK、Switzerland、Norway 与 non-EU aggregation");
    expect(zh).toContain("每个组件必须使用精确 subject id");
    expect(zh).toContain("若证据不能支持全部四个精确组件");
    expect(zh).toContain("实际 get_eu_macro_snapshot result event 的真实 evidence_id");
    expect(zh).toContain("当前证据不是已实现的 5D 结果");
    expect(zh).toContain("event-triggered、T+1 open 后 5 个交易日");
    expect(zh).toContain("按 PIT volatility 归一化的 A-share role-path outcome");
    expect(zh).toContain("半年一次的 component weights");
    expect(zh).not.toContain("KNOT");
    expect(zh).toContain("fallback=false 表示缺失证据必须拒绝");
    expect(zh).toContain("不得生成跨 Agent 结论");
    expect(en).toContain("PIT registered EU-27 real-economy observations, not an A-share signal");
    expect(en).toContain("only when those fields are present");
    expect(en).toContain("never invent missing consensus or surprise");
    expect(en).toContain("Scope is EU-27 only; exclude the UK, Switzerland, Norway");
    expect(en).toContain("Every component must use its exact subject id");
    expect(en).toContain(
      "real evidence_id values from the actual get_eu_macro_snapshot result event",
    );
    expect(en).toContain(
      "event-triggered A-share role-path outcome over 5 trading days after T+1 open",
    );
    expect(en).toContain("normalized by PIT volatility");
    expect(en).toContain("semiannual component weights");
    expect(en).not.toContain("KNOT");
    expect(en).toContain("fallback=false means missing evidence must be rejected");
    expect(renderMacroPromptBody("institutional_flow", "en", "cohort_default")).not.toContain(
      "Scope is EU-27 only",
    );
  });

  it("keeps every generated non-Macro prompt synchronized with its runtime tool contract", () => {
    const bundledRoot = resolve(process.cwd(), "..", "prompts", "mosaic", "cohort_default");
    for (const spec of RUNTIME_AGENT_SPECS.filter((candidate) => candidate.layer !== "macro")) {
      for (const language of ["zh", "en"] as const) {
        const expected = upsertRuntimeEvidenceContract(
          renderBundledPrompt(spec.agent, language, "cohort_default"),
          spec,
          language,
        );
        expect(
          readFileSync(join(bundledRoot, spec.layer, `${spec.agent}.${language}.md`), "utf8"),
          `${spec.agent}:${language}`,
        ).toBe(expected);
      }
    }
  });

  it.each([
    "semiconductor",
    "technology",
    "energy",
    "biotech",
    "consumer",
    "industrials",
    "real_estate_construction",
    "financials",
    "agriculture",
  ])("binds %s tools to economic evidence and result-event lineage", (agent) => {
    const sectorRoot = resolve(
      process.cwd(),
      "..",
      "prompts",
      "mosaic",
      "cohort_default",
      "sector",
    );
    const spec = RUNTIME_AGENT_SPECS.find((candidate) => candidate.agent === agent);
    expect(spec).toBeDefined();
    if (!spec) throw new Error(`missing ${agent} runtime spec`);
    const zh = readFileSync(join(sectorRoot, `${agent}.zh.md`), "utf8");
    const en = readFileSync(join(sectorRoot, `${agent}.en.md`), "utf8");
    expect(zh).toBe(
      upsertRuntimeEvidenceContract(renderBundledPrompt(agent, "zh", "cohort_default"), spec, "zh"),
    );
    expect(en).toBe(
      upsertRuntimeEvidenceContract(renderBundledPrompt(agent, "en", "cohort_default"), spec, "en"),
    );
    if (agent === "semiconductor") {
      expect(zh).toContain("快照与三表与 broker research");
      expect(en).toContain("the snapshot, the three statements, and broker research");
    } else {
      expect(zh).toContain("快照与 broker research 只用于 fundamentals");
      expect(zh).not.toContain("三表");
      expect(en).toContain("use the snapshot and broker research only for fundamentals");
      expect(en).not.toContain("three statements");
    }
    expect(zh).toContain(
      "关键证据在 claim 中标记 UNKNOWN；若仍无法形成唯一 preferred/least，则 ABSTAIN/拒绝阶段",
    );
    expect(zh).toContain("按实际使用工具引用对应 result-event evidence_id");
    expect(en).toContain("Economic evidence duties:");
    expect(en).toContain(
      "Unresolved conflicts must lower confidence; mark missing critical evidence as UNKNOWN in the claim; if a unique preferred/least pair still cannot be formed, ABSTAIN/reject the stage",
    );
    expect(en).toContain("result-event evidence_id for each tool actually used");
    expect(en).toContain("keep the direction_research compact comparison contract unchanged");
    expect(renderBundledPrompt("druckenmiller", "en")).not.toContain("Economic evidence duties:");
  });

  it("keeps every public bundled prompt free of research-knob internals", () => {
    const bundledRoot = resolve(process.cwd(), "..", "prompts", "mosaic");
    const files = readdirSync(bundledRoot, { recursive: true, encoding: "utf8" }).filter((file) =>
      file.endsWith(".md"),
    );
    expect(files).toHaveLength(50);
    expect(files.every((file) => file.startsWith("cohort_default/"))).toBe(true);
    for (const file of files) {
      const text = readFileSync(join(bundledRoot, file), "utf8");
      expect(text).not.toContain("```research-knobs");
      expect(text).not.toMatch(/domain knob|knob influence/i);
      if (file.endsWith(".zh.md")) {
        expect(text).toContain("## 运行时证据输出合同");
        expect(text).not.toContain("## Runtime Evidence Output Contract");
      } else {
        expect(text).toContain("## Runtime Evidence Output Contract");
      }
    }
  });

  it("keeps restored RKE tools behind the shadow-only boundary", () => {
    const bundledRoot = resolve(process.cwd(), "..", "prompts", "mosaic", "cohort_default");
    const rkeSpecs = RUNTIME_AGENT_SPECS.filter((spec) =>
      spec.requiredTools.includes("get_rke_research_context"),
    );
    expect(rkeSpecs.length).toBeGreaterThan(0);
    for (const spec of rkeSpecs) {
      const zh = readFileSync(join(bundledRoot, spec.layer, `${spec.agent}.zh.md`), "utf8");
      const en = readFileSync(join(bundledRoot, spec.layer, `${spec.agent}.en.md`), "utf8");
      expect(zh).toContain("仅作为研究先验，不是当前数据，不能直接生成交易");
      expect(en).toContain(
        "only as a research prior, not current data; it cannot directly create trades",
      );
    }
  });

  it("allows authorized research tools only inside each frozen Superinvestor scope", () => {
    const bundledRoot = resolve(process.cwd(), "..", "prompts", "mosaic", "cohort_default");
    for (const spec of RUNTIME_AGENT_SPECS.filter(
      (candidate) => candidate.layer === "superinvestor",
    )) {
      const zh = readFileSync(join(bundledRoot, spec.layer, `${spec.agent}.zh.md`), "utf8");
      const en = readFileSync(join(bundledRoot, spec.layer, `${spec.agent}.en.md`), "utf8");
      expect(spec.requiredTools).toContain("get_stock_research");
      expect(spec.requiredTools).toContain("get_rke_research_context");
      expect(zh).toContain("政策和研报只能用于冻结候选及 as-of/PIT 时间窗");
      expect(zh).toContain("必须来自已授权工具");
      expect(zh).not.toContain("不得查询域外证券、新闻、政策搜索或研究报告");
      expect(en).toContain("only for the frozen candidate and as-of/PIT window");
      expect(en).toContain("through authorized tools");
      expect(en).not.toContain(
        "Do not query outside securities, news, policy search, or research reports",
      );
    }
  });

  it("binds Druckenmiller evidence duties to the frozen opportunity set and 21D outcome", () => {
    const bundledRoot = resolve(process.cwd(), "..", "prompts", "mosaic", "cohort_default");
    const spec = RUNTIME_AGENT_SPECS.find((candidate) => candidate.agent === "druckenmiller");
    expect(spec).toBeDefined();
    if (!spec) throw new Error("missing druckenmiller runtime spec");
    const zh = readFileSync(join(bundledRoot, "superinvestor", "druckenmiller.zh.md"), "utf8");
    const en = readFileSync(join(bundledRoot, "superinvestor", "druckenmiller.en.md"), "utf8");
    expect(zh).toBe(
      upsertRuntimeEvidenceContract(
        renderBundledPrompt("druckenmiller", "zh", "cohort_default"),
        spec,
        "zh",
      ),
    );
    expect(en).toBe(
      upsertRuntimeEvidenceContract(
        renderBundledPrompt("druckenmiller", "en", "cohort_default"),
        spec,
        "en",
      ),
    );
    expect(zh).toContain("候选快照只定义冻结机会集和上游 conviction lineage，不是买卖信号");
    expect(zh).toContain("stock_research 仅作 as-of 研究证据");
    expect(zh).toContain("按实际使用工具引用对应 result-event evidence_id");
    expect(zh).toContain("T+1 open 后 21 个交易日");
    expect(zh).not.toContain("KNOT");
    expect(zh).toContain("对八个 Macro Agent");
    expect(en).toContain("snapshot defines only the frozen opportunity set");
    expect(en).toContain("stock_research only as as-of research evidence");
    expect(en).toContain("result-event evidence_id for each tool actually used");
    expect(en).toContain("21 trading days after T+1 open");
    expect(en).not.toContain("KNOT");
    expect(en).toContain("eight Macro Agents");
  });

  it("binds Munger evidence duties without treating 21D as a long-term thesis outcome", () => {
    const bundledRoot = resolve(process.cwd(), "..", "prompts", "mosaic", "cohort_default");
    const spec = RUNTIME_AGENT_SPECS.find((candidate) => candidate.agent === "munger");
    expect(spec).toBeDefined();
    if (!spec) throw new Error("missing munger runtime spec");
    const zh = readFileSync(join(bundledRoot, "superinvestor", "munger.zh.md"), "utf8");
    const en = readFileSync(join(bundledRoot, "superinvestor", "munger.en.md"), "utf8");
    expect(zh).toBe(
      upsertRuntimeEvidenceContract(
        renderBundledPrompt("munger", "zh", "cohort_default"),
        spec,
        "zh",
      ),
    );
    expect(en).toBe(
      upsertRuntimeEvidenceContract(
        renderBundledPrompt("munger", "en", "cohort_default"),
        spec,
        "en",
      ),
    );
    expect(zh).toContain("候选快照只定义冻结机会集和上游 conviction lineage，不是买卖信号");
    expect(zh).toContain("fundamentals 用于 ROIC、盈利能力与估值");
    expect(zh).toContain("balance sheet、income statement 与 cashflow");
    expect(zh).toContain("stock_data 只用于价格、回撤与入场上下文，不能证明 moat");
    expect(zh).toContain("stock_research 仅作 as-of 护城河、竞争格局与盈利预期佐证");
    expect(zh).toContain("RKE 仅作先验");
    expect(zh).toContain("按实际使用工具引用真实 result-event evidence_id");
    expect(zh).toContain("holding_period 是 thesis horizon");
    expect(zh).toContain("T+1 open 后 21 个交易日 net excess return 只演进候选选择");
    expect(zh).toContain("不验证也不得演进 moat、ROIC 或 compounding 判据");
    expect(zh).not.toContain("KNOT");
    expect(en).toContain("fundamentals for ROIC, profitability, and valuation");
    expect(en).toContain("balance sheet, income statement, and cashflow");
    expect(en).toContain("result-event evidence_id values for each tool actually used");
    expect(en).toContain("21 trading days after T+1 open may evolve only candidate selection");
    expect(en).toContain("neither validates nor may evolve moat, ROIC, or compounding criteria");
    expect(en).not.toContain("KNOT");
    expect(en).toContain("eight Macro Agents");
    expect(renderBundledPrompt("druckenmiller", "en")).not.toContain(
      "whose long-term theses remain immature under the current contract",
    );
  });

  it("binds Burry evidence duties without treating 21D as intrinsic-value proof", () => {
    const bundledRoot = resolve(process.cwd(), "..", "prompts", "mosaic", "cohort_default");
    const spec = RUNTIME_AGENT_SPECS.find((candidate) => candidate.agent === "burry");
    expect(spec).toBeDefined();
    if (!spec) throw new Error("missing burry runtime spec");
    const zh = readFileSync(join(bundledRoot, "superinvestor", "burry.zh.md"), "utf8");
    const en = readFileSync(join(bundledRoot, "superinvestor", "burry.en.md"), "utf8");
    expect(zh).toBe(
      upsertRuntimeEvidenceContract(
        renderBundledPrompt("burry", "zh", "cohort_default"),
        spec,
        "zh",
      ),
    );
    expect(en).toBe(
      upsertRuntimeEvidenceContract(
        renderBundledPrompt("burry", "en", "cohort_default"),
        spec,
        "en",
      ),
    );
    expect(zh).toContain("候选快照只定义冻结机会集和上游 conviction lineage，不是买卖信号");
    expect(zh).toContain("fundamentals 用于估值错配、盈利能力与盈利质量");
    expect(zh).toContain("balance sheet 用于资产支持、杠杆、流动性与偿债能力");
    expect(zh).toContain("income statement 与 cashflow 用于盈利质量、现金消耗与再融资风险");
    expect(zh).toContain("stock_data 用于价格路径、波动、回撤与反身性反馈");
    expect(zh).toContain("stock_research 仅作 as-of 共识错配、催化与盈利预期佐证");
    expect(zh).toContain("RKE 仅作先验");
    expect(zh).toContain("按实际使用工具引用真实 result-event evidence_id");
    expect(zh).toContain("holding_period 是 thesis horizon");
    expect(zh).toContain("T+1 open 后 21 个交易日 net excess return 只演进候选选择");
    expect(zh).toContain("不能证明 intrinsic value 或 balance-sheet quality");
    expect(zh).not.toContain("KNOT");
    expect(en).toContain(
      "fundamentals for valuation dislocation, profitability, and earnings quality",
    );
    expect(en).toContain("balance sheet for asset support, leverage, liquidity, and debt service");
    expect(en).toContain("income statement and cashflow for earnings quality, cash burn");
    expect(en).toContain("result-event evidence_id values for each tool actually used");
    expect(en).toContain("21 trading days after T+1 open may evolve only candidate selection");
    expect(en).toContain("cannot prove intrinsic value or balance-sheet quality");
    expect(en).not.toContain("KNOT");
    expect(en).toContain("eight Macro Agents");
    for (const agent of ["munger", "druckenmiller"]) {
      expect(renderBundledPrompt(agent, "en")).not.toContain(
        "it cannot prove intrinsic value or balance-sheet quality",
      );
    }
  });

  it("binds Ackman evidence duties without treating 21D as governance proof", () => {
    const bundledRoot = resolve(process.cwd(), "..", "prompts", "mosaic", "cohort_default");
    const spec = RUNTIME_AGENT_SPECS.find((candidate) => candidate.agent === "ackman");
    expect(spec).toBeDefined();
    if (!spec) throw new Error("missing ackman runtime spec");
    const zh = readFileSync(join(bundledRoot, "superinvestor", "ackman.zh.md"), "utf8");
    const en = readFileSync(join(bundledRoot, "superinvestor", "ackman.en.md"), "utf8");
    expect(zh).toBe(
      upsertRuntimeEvidenceContract(
        renderBundledPrompt("ackman", "zh", "cohort_default"),
        spec,
        "zh",
      ),
    );
    expect(en).toBe(
      upsertRuntimeEvidenceContract(
        renderBundledPrompt("ackman", "en", "cohort_default"),
        spec,
        "en",
      ),
    );
    expect(zh).toContain("候选快照只定义冻结机会集和上游 conviction lineage，不是买卖信号");
    expect(zh).toContain("fundamentals 用于质量、盈利能力与估值");
    expect(zh).toContain("balance sheet、income statement 与 cashflow");
    expect(zh).toContain("资本结构、利润率与盈利稳定性、现金转化与资本配置");
    expect(zh).toContain("stock_data 只用于价格、回撤、催化反应与入场上下文");
    expect(zh).toContain("不能证明 governance improvement 或 durable quality");
    expect(zh).toContain("stock_research 仅作 as-of 治理、催化与盈利预期佐证");
    expect(zh).toContain("RKE 仅作先验");
    expect(zh).toContain("按实际使用工具引用真实 result-event evidence_id");
    expect(zh).toContain("holding_period 是 thesis horizon");
    expect(zh).toContain("T+1 open 后 21 个交易日 net excess return 只演进候选选择");
    expect(zh).not.toContain("KNOT");
    expect(en).toContain("fundamentals for quality, profitability, and valuation");
    expect(en).toContain("balance sheet, income statement, and cashflow");
    expect(en).toContain(
      "stock_data only for price, drawdown, catalyst reaction, and entry context",
    );
    expect(en).toContain("result-event evidence_id values for each tool actually used");
    expect(en).toContain("21 trading days after T+1 open may evolve only candidate selection");
    expect(en).toContain("cannot prove governance improvement or durable quality");
    expect(en).not.toContain("KNOT");
    expect(en).toContain("eight Macro Agents");
    for (const agent of ["munger", "burry", "druckenmiller"]) {
      expect(renderBundledPrompt(agent, "en")).not.toContain(
        "it cannot prove governance improvement or durable quality",
      );
    }
  });

  it("binds CRO evidence duties to frozen candidates and calibrated 5D risk", () => {
    const bundledRoot = resolve(process.cwd(), "..", "prompts", "mosaic", "cohort_default");
    const spec = RUNTIME_AGENT_SPECS.find((candidate) => candidate.agent === "cro");
    expect(spec).toBeDefined();
    if (!spec) throw new Error("missing cro runtime spec");
    const zh = readFileSync(join(bundledRoot, "decision", "cro.zh.md"), "utf8");
    const en = readFileSync(join(bundledRoot, "decision", "cro.en.md"), "utf8");
    expect(zh).toBe(
      upsertRuntimeEvidenceContract(renderBundledPrompt("cro", "zh", "cohort_default"), spec, "zh"),
    );
    expect(en).toBe(
      upsertRuntimeEvidenceContract(renderBundledPrompt("cro", "en", "cohort_default"), spec, "en"),
    );
    expect(zh).toContain("risk snapshot 只定义冻结 proposal candidates");
    expect(zh).toContain("current/proposed weights、portfolio exposure 与 policy limits");
    expect(zh).toContain("不是已实现风险状态");
    expect(zh).toContain("role_event 只用于 as-of 日历型风险催化");
    expect(zh).toContain("RKE 仅作先验");
    for (const action of [
      "VETO",
      "CAP_WEIGHT",
      "REDUCE_WEIGHT",
      "REQUIRE_REVIEW",
      "NO_OBJECTION",
    ]) {
      expect(zh).toContain(action);
    }
    expect(zh).toContain("correlated risks 与 black swan 风险绑定到真实 evidence");
    expect(zh).toContain("按实际使用工具引用真实 result-event evidence_id");
    expect(zh).toContain("当前证据不得冒充已实现的 5D risk");
    expect(zh).toContain("action precision、recall、specificity 与 probability calibration");
    expect(zh).not.toContain("KNOT");
    expect(zh).toContain("fallback=false 表示证据不完整时必须拒绝");
    expect(en).toContain("risk snapshot defines only frozen proposal candidates");
    expect(en).toContain("result-event evidence_id values for each tool actually used");
    expect(en).toContain("Current evidence must not be presented as realized 5D risk");
    expect(en).toContain("action precision, recall, specificity, and probability calibration");
    expect(en).not.toContain("KNOT");
    expect(en).toContain("fallback=false means incomplete evidence must be rejected");
    expect(en).toContain("eight Macro Agents");
    for (const agent of ["cio", "autonomous_execution"]) {
      expect(renderBundledPrompt(agent, "en")).not.toContain(
        "action precision, recall, specificity, and probability calibration",
      );
    }
  });

  it("binds Alpha Discovery evidence duties to frozen novel candidates and 5D utility", () => {
    const bundledRoot = resolve(process.cwd(), "..", "prompts", "mosaic", "cohort_default");
    const spec = RUNTIME_AGENT_SPECS.find((candidate) => candidate.agent === "alpha_discovery");
    expect(spec).toBeDefined();
    if (!spec) throw new Error("missing alpha_discovery runtime spec");
    const zh = readFileSync(join(bundledRoot, "decision", "alpha_discovery.zh.md"), "utf8");
    const en = readFileSync(join(bundledRoot, "decision", "alpha_discovery.en.md"), "utf8");
    expect(zh).toBe(
      upsertRuntimeEvidenceContract(
        renderBundledPrompt("alpha_discovery", "zh", "cohort_default"),
        spec,
        "zh",
      ),
    );
    expect(en).toBe(
      upsertRuntimeEvidenceContract(
        renderBundledPrompt("alpha_discovery", "en", "cohort_default"),
        spec,
        "en",
      ),
    );
    expect(zh).toContain(
      "snapshot 只定义冻结 novel candidates 与已排除的 upstream-selected tickers",
    );
    expect(zh).toContain("不得新增或替换 ticker、恢复 excluded ticker");
    expect(zh).toContain("role_event 仅用于 as-of 催化与风险，不能替代候选 lineage");
    expect(zh).toContain("RKE 仅作先验");
    expect(zh).toContain("novel_pick 必须逐一绑定 snapshot 中完全一致的 candidate_ref 与 ts_code");
    expect(zh).toContain("NONE_FOUND 必须由完整冻结候选证据支持");
    expect(zh).toContain("按实际使用工具引用真实 result-event evidence_id");
    expect(zh).toContain("当前证据不得冒充已实现的 5D alpha");
    expect(zh).toContain("selected-pick utility、incremental utility、missed opportunity");
    expect(zh).not.toContain("KNOT");
    expect(zh).toContain("fallback=false 表示证据缺失即拒绝");
    expect(en).toContain("snapshot defines only frozen novel candidates");
    expect(en).toContain("exact candidate_ref and ts_code from the snapshot");
    expect(en).toContain("NONE_FOUND requires complete frozen-candidate evidence");
    expect(en).toContain("result-event evidence_id values for each tool actually used");
    expect(en).toContain("Current evidence must not be presented as realized 5D alpha");
    expect(en).toContain(
      "selected-pick utility, incremental utility, missed opportunity, and confidence calibration",
    );
    expect(en).not.toContain("KNOT");
    expect(en).toContain("fallback=false means missing evidence must be rejected");
    expect(en).toContain("eight Macro Agents");
    for (const agent of ["cro", "cio", "autonomous_execution"]) {
      expect(renderBundledPrompt(agent, "en")).not.toContain(
        "selected-pick utility, incremental utility, missed opportunity",
      );
    }
  });

  it("binds Autonomous Execution duties to frozen intents and next-session outcomes", () => {
    const bundledRoot = resolve(process.cwd(), "..", "prompts", "mosaic", "cohort_default");
    const spec = RUNTIME_AGENT_SPECS.find(
      (candidate) => candidate.agent === "autonomous_execution",
    );
    expect(spec).toBeDefined();
    if (!spec) throw new Error("missing autonomous_execution runtime spec");
    const zh = readFileSync(join(bundledRoot, "decision", "autonomous_execution.zh.md"), "utf8");
    const en = readFileSync(join(bundledRoot, "decision", "autonomous_execution.en.md"), "utf8");
    expect(zh).toBe(
      upsertRuntimeEvidenceContract(
        renderBundledPrompt("autonomous_execution", "zh", "cohort_default"),
        spec,
        "zh",
      ),
    );
    expect(en).toBe(
      upsertRuntimeEvidenceContract(
        renderBundledPrompt("autonomous_execution", "en", "cohort_default"),
        spec,
        "en",
      ),
    );
    expect(zh).toContain("get_execution_snapshot 只定义 CIO proposal 与可选 CRO control");
    expect(zh).toContain("不是成交结果或执行批准");
    expect(zh).toContain("不得改变 side 或 requested_delta_weight");
    expect(zh).toContain("order_intent_ref、ts_code 与 requested_delta_weight");
    expect(zh).toContain("一对一覆盖冻结订单集合");
    expect(zh).toContain("get_role_event_snapshot 只用于 as-of 或 next-session");
    expect(zh).toContain("get_rke_research_context 仅作先验");
    for (const disposition of ["FEASIBLE", "PARTIAL", "BLOCKED"]) {
      expect(zh).toContain(disposition);
    }
    for (const constraint of [
      "max_slippage",
      "max_participation",
      "min_trade",
      "max_slice",
      "prohibited constraints",
    ]) {
      expect(zh).toContain(constraint);
    }
    expect(zh).toContain("NO_DELTA 必须由完整冻结证据证明确实没有 actionable order");
    expect(zh).toContain("按实际使用工具引用真实 result-event evidence_id");
    expect(zh).toContain("当前证据不得冒充已实现的 T+1 execution");
    expect(zh).toContain("normalized cost error 40%");
    expect(zh).toContain("feasibility classification 30%");
    expect(zh).toContain("target-delta attainment 20%");
    expect(zh).toContain("policy compliance 10%");
    expect(zh).not.toContain("KNOT");
    expect(zh).toContain("fallback=false 表示证据缺失即拒绝");
    expect(zh).toContain("不得直接读取、复述或归因 Macro gate 或八个 Macro 输出");
    expect(en).toContain("execution_snapshot defines only the frozen order intents");
    expect(en).toContain("cover the frozen order set one-to-one");
    expect(en).toContain("result-event evidence_id values for each tool actually used");
    expect(en).toContain("Current evidence must not be presented as realized T+1 execution");
    expect(en).toContain("normalized cost error at 40%");
    expect(en).not.toContain("KNOT");
    expect(en).toContain("fallback=false means missing evidence must be rejected");
    expect(en).toContain("Macro gate or eight Macro outputs");
    for (const agent of ["cro", "alpha_discovery", "cio"]) {
      expect(renderBundledPrompt(agent, "en")).not.toContain("normalized cost error at 40%");
    }
  });

  it("binds CIO proposal and final stages to one frozen lineage and final-only 5D outcome", () => {
    const bundledRoot = resolve(process.cwd(), "..", "prompts", "mosaic", "cohort_default");
    const spec = RUNTIME_AGENT_SPECS.find((candidate) => candidate.agent === "cio");
    expect(spec).toBeDefined();
    if (!spec) throw new Error("missing cio runtime spec");
    const zh = readFileSync(join(bundledRoot, "decision", "cio.zh.md"), "utf8");
    const en = readFileSync(join(bundledRoot, "decision", "cio.en.md"), "utf8");
    expect(zh).toBe(
      upsertRuntimeEvidenceContract(renderBundledPrompt("cio", "zh", "cohort_default"), spec, "zh"),
    );
    expect(en).toBe(
      upsertRuntimeEvidenceContract(renderBundledPrompt("cio", "en", "cohort_default"), spec, "en"),
    );
    expect(zh).toContain(
      "PROPOSAL：get_cio_decision_snapshot 只冻结八个 Macro transmission evidence",
    );
    expect(zh).toContain("Macro evidence 不是新增 ticker 的授权");
    expect(zh).toContain("候选只来自 snapshot 去重后的 accepted candidates 与 current positions");
    expect(zh).toContain("target_positions 只能使用冻结 ts_code");
    expect(zh).toContain("thesis_status 与 risk_flags");
    expect(zh).toContain("target weights 加 cash 必须等于 1");
    expect(zh).toContain(
      "max_total_target_weight、min_cash_weight、max_single_name_weight 与 restricted_ts_codes",
    );
    expect(zh).toContain("PROPOSAL 只形成候选 target，不是 CRO/Execution 后的最终组合");
    expect(zh).toContain("也没有独立 realized outcome");
    expect(zh).toContain("FINAL：snapshot 只冻结同一 accepted CIO proposal");
    expect(zh).toContain("final target portfolio 只能保持 proposal 或更保守");
    expect(zh).toContain(
      "control resolution 的 resolution 枚举只能是 COMPLIED 或 MORE_CONSERVATIVE",
    );
    expect(zh).toContain("cro_action_local_ref 与 execution_assessment_local_ref");
    expect(zh).toContain("不得放宽控制");
    expect(zh).toContain("HOLD_CURRENT 或 ALL_CASH 必须由完整冻结证据支持");
    expect(zh).toContain("get_rke_research_context 仅作先验，不能直接生成交易");
    expect(zh).toContain("按实际使用工具引用真实 result-event evidence_id");
    expect(zh).toContain("只有 accepted CIO_FINAL 有独立 T+1 open 后 5D outcome");
    expect(zh).toContain("relative return 50%、drawdown 25%、turnover cost 15%");
    expect(zh).toContain("constraint compliance 10%");
    expect(zh).toContain("PROPOSAL 没有单独 outcome");
    expect(zh).not.toContain("KNOT");
    expect(zh).toContain("fallback=false 表示证据缺失即拒绝");
    expect(en).toContain("PROPOSAL: get_cio_decision_snapshot freezes only eight Macro");
    expect(en).toContain("thesis_status, and risk_flags");
    expect(en).toContain(
      "max_total_target_weight, min_cash_weight, max_single_name_weight, and restricted_ts_codes",
    );
    expect(en).toContain("FINAL: the snapshot freezes only the same accepted CIO proposal");
    expect(en).toContain(
      "final target portfolio may only preserve the proposal or become more conservative",
    );
    expect(en).toContain("resolution enum may only be COMPLIED or MORE_CONSERVATIVE");
    expect(en).toContain(
      "through cro_action_local_ref or execution_assessment_local_ref, respectively",
    );
    expect(en).toContain("Only accepted CIO_FINAL has an independent 5D outcome after T+1 open");
    expect(en).toContain("relative return 50%, drawdown 25%, turnover cost 15%");
    expect(en).toContain("constraint compliance 10%");
    expect(en).toContain("PROPOSAL has no separate outcome");
    expect(en).not.toContain("KNOT");
    expect(en).toContain("eight Macro Agents");
    for (const agent of ["cro", "alpha_discovery", "autonomous_execution"]) {
      expect(renderBundledPrompt(agent, "en")).not.toContain("relative return 50%");
    }
  });

  it("fails closed instead of turning missing evidence into an empty non-Macro output", () => {
    const bundledRoot = resolve(process.cwd(), "..", "prompts", "mosaic", "cohort_default");
    const macroAgents = new Set<string>(MACRO_AGENT_IDS);
    for (const agent of ALL_AGENTS.filter((candidate) => !macroAgents.has(candidate))) {
      const layer = LAYER_BY_AGENT[agent];
      const zh = readFileSync(join(bundledRoot, String(layer), `${agent}.zh.md`), "utf8");
      const en = readFileSync(join(bundledRoot, String(layer), `${agent}.en.md`), "utf8");
      expect(zh).not.toContain("证据不足时，输出");
      expect(en).not.toContain("When evidence is insufficient, emit");
      if (layer === "decision") {
        expect(zh).toContain("必需证据缺失或无效时拒绝本阶段");
        expect(en).toMatch(
          /Reject the stage without (?:a CIO|an Agent) output when required evidence/,
        );
      }
    }
  });

  it("keeps all 25 default bundled agents bilingual and private cohorts absent", () => {
    const bundledRoot = resolve(process.cwd(), "..", "prompts", "mosaic");
    for (const agent of ALL_AGENTS) {
      const layer = LAYER_BY_AGENT[agent];
      expect(layer).toBeDefined();
      for (const language of ["zh", "en"] as const) {
        const text = readFileSync(
          join(bundledRoot, "cohort_default", String(layer), `${agent}.${language}.md`),
          "utf8",
        );
        if (language === "zh") {
          expect(text).toContain("## 运行时证据输出合同");
          expect(text).toMatch(/[\u3400-\u9fff]/u);
          expect(text).not.toContain("## Runtime Evidence Output Contract");
        } else {
          expect(text).toContain("## Runtime Evidence Output Contract");
          expect(text).not.toMatch(/[\u3400-\u9fff]/u);
          expect(text).not.toContain("## 运行时证据输出合同");
        }
      }
    }
    for (const cohort of MACRO_PROMPT_COHORT_IDS.filter(
      (candidate) => candidate !== "cohort_default",
    )) {
      const files = readdirSync(join(bundledRoot, cohort), {
        recursive: true,
        encoding: "utf8",
      });
      expect(
        files.filter((file) => file.endsWith(".md")),
        cohort,
      ).toEqual([]);
    }
  });

  it("fails closed when public renderers are asked for private cohort behavior", () => {
    for (const cohort of MACRO_PROMPT_COHORT_IDS.filter(
      (candidate) => candidate !== "cohort_default",
    )) {
      expect(() => renderMacroPromptBody("china", "en", cohort)).toThrow(
        "private cohort prompt generation is unavailable publicly",
      );
      expect(() => renderBundledPrompt("energy", "en", cohort)).toThrow(
        "private cohort prompt generation is unavailable publicly",
      );
    }
  });

  it("keeps Chinese prompt prose localized and rejects nonexistent Macro dispositions", () => {
    for (const agent of MACRO_AGENT_IDS) {
      const zh = prompt(agent, "zh");
      const en = prompt(agent, "en");
      expect(zh).toContain("## 运行时证据输出合同");
      expect(zh).not.toMatch(/^## (Runtime|Analysis|Cohort|Prohibited)/m);
      expect(zh).not.toContain("empty disposition");
      expect(zh).not.toContain("Layer-1");
      expect(en).not.toContain("empty disposition");
    }
  });

  it("removes search/social dependencies and old required-role mistakes", () => {
    const china = prompt("china", "en");
    const centralBank = prompt("central_bank", "en");
    const usFinancialConditions = prompt("us_financial_conditions", "en");
    const euEconomy = prompt("eu_economy", "en");
    expect(china).not.toMatch(/must[^\n]{0,40}property/i);
    expect(china).toContain("Do not require property");
    expect(centralBank).toContain("PBOC reaction function");
    expect(centralBank).toContain("Do not judge foreign central banks");
    expect(centralBank).not.toContain("PBOC/Fed");
    expect(usFinancialConditions).toContain("Fed, US curves, credit/financial stress, and USD/RMB");
    expect(usFinancialConditions).toContain("Do not split the Fed, dollar, and curve");
    expect(euEconomy).toContain("Do not include the UK, Switzerland, or Norway");
    for (const agent of MACRO_AGENT_IDS) {
      const text = `${prompt(agent, "zh")}\n${prompt(agent, "en")}`;
      expect(text).not.toContain("get_news");
      expect(text).not.toContain("get_caixin_sentiment");
      expect(text).not.toContain("get_xueqiu_heat");
      expect(text).not.toContain("Google Caixin");
    }
  });
});
