import { STANDARD_SECTOR_ROLE_CONTRACTS } from "../sector/_contracts.js";
import type { StandardSectorAgentId } from "../types.js";
import { renderCohortBehavior } from "./cohort_behavior.js";
import { AGENTS_BY_LAYER, LAYER_BY_AGENT, type Language } from "./cohorts.js";
import { assertPublicBundledCohort } from "./public_prompt_cohort.js";
import { RUNTIME_AGENT_SPEC_BY_AGENT } from "./runtime_agent_spec.js";

export const DEFAULT_COHORT_LENS: Readonly<{ zh: string; en: string }> = {
  zh: "不预设市场状态，只依据本次冻结证据判断。",
  en: "Assume no market regime; judge only the frozen evidence.",
};

const SUPER_GOALS: Record<string, { zh: string; en: string }> = {
  druckenmiller: {
    zh: "以宏观趋势、动量和非对称收益筛选冻结候选。",
    en: "Filter the frozen candidate set for macro trend, momentum, and asymmetric payoff.",
  },
  munger: {
    zh: "以护城河、资本回报和可预测复利筛选冻结候选。",
    en: "Filter the frozen candidate set for moats, returns on capital, and predictable compounding.",
  },
  burry: {
    zh: "以估值错配、资产负债表和反身性风险筛选冻结候选。",
    en: "Filter the frozen candidate set for valuation dislocation, balance-sheet support, and reflexive risk.",
  },
  ackman: {
    zh: "以高质量、治理改善和可验证催化筛选冻结候选。",
    en: "Filter the frozen candidate set for quality, governance improvement, and verifiable catalysts.",
  },
};

const DECISION_GOALS: Record<string, { zh: string; en: string }> = {
  alpha_discovery: {
    zh: "只在冻结的新颖候选域中寻找上游未选择的增量机会。",
    en: "Find incremental opportunities only inside the frozen novel-candidate domain.",
  },
  cro: {
    zh: "审查同一冻结 CIO proposal 的风险、约束和必要调整。",
    en: "Review risk, constraints, and required controls for the same frozen CIO proposal.",
  },
  autonomous_execution: {
    zh: "把 CRO 处理后的冻结订单意图转换为可执行性判断。",
    en: "Translate CRO-adjusted frozen order intents into feasibility decisions.",
  },
  cio: {
    zh: "proposal 阶段形成冻结目标，final 阶段只在同一 lineage 上整合 CRO 与执行结果。",
    en: "Freeze the target in proposal and integrate CRO/execution results on the same lineage in final.",
  },
};

export function renderBundledPrompt(
  agent: string,
  language: Language,
  cohort = "cohort_default",
): string {
  assertPublicBundledCohort(cohort);
  const layer = LAYER_BY_AGENT[agent];
  if (!layer || layer === "macro") throw new Error(`unsupported bundled renderer agent: ${agent}`);
  const spec = RUNTIME_AGENT_SPEC_BY_AGENT.get(agent);
  if (!spec) throw new Error(`runtime spec missing for ${agent}`);
  const tools = spec.requiredTools.join("、");
  const lens = DEFAULT_COHORT_LENS[language];
  if (layer === "sector" && agent !== "relationship_mapper") {
    const role = STANDARD_SECTOR_ROLE_CONTRACTS[agent as StandardSectorAgentId];
    const prohibited = role.prohibited[language].map((item) => `- ${item}`).join("\n");
    return language === "zh"
      ? [
          `# ${agent} 行业研究角色`,
          "",
          `目标：${role.responsibility.zh}`,
          "观察镜头：",
          renderCohortBehavior(lens),
          "",
          "禁区：",
          prohibited,
          "",
          `工具：只调用 ${tools}；候选域、方向和日期由运行时冻结，不得扩域。`,
          "研究阶段只比较快照注册方向并逐项引用证据；不得自造方向、ETF、技术指标或总体行业分数。",
          "最终阶段严格服从运行时 selection directive，输出唯一 preferred 和一个不同的 least、受约束证券 picks、drivers、risks、claims，以及必需的 Macro 汇总归因与适用的目标级归因。",
          "所有数据必须满足 as-of/PIT；方向证据不足或无法形成唯一首尾方向时拒绝阶段。仅当运行时证明对应冻结 shortlist 为空时允许该证券 leg 使用 NO_QUALIFIED_SECURITY；shortlist 非空必须输出 picks。",
          "输出由运行时结构化 schema 强制。",
          "",
        ].join("\n")
      : [
          `# ${agent} sector research role`,
          "",
          `Goal: ${role.responsibility.en}`,
          "Cohort lens:",
          renderCohortBehavior(lens),
          "",
          "Prohibited:",
          prohibited,
          "",
          `Tool: call only ${spec.requiredTools.join(", ")}; the runtime freezes date, directions, and candidate domain.`,
          "In research, compare only registered directions and cite evidence per criterion; do not invent directions, ETFs, indicators, or an overall sector score.",
          "In final selection, obey the runtime directive and return one preferred direction and one distinct least-preferred direction, constrained security picks, drivers, risks, claims, and the required Macro summary and applicable target-level attributions.",
          "Use only as-of/PIT-valid evidence; reject the stage if direction evidence cannot establish a unique best/worst pair. A security leg may use NO_QUALIFIED_SECURITY only when runtime proves its frozen shortlist is empty; a non-empty shortlist requires picks.",
          "The runtime structured schema is authoritative.",
          "",
        ].join("\n");
  }
  if (agent === "relationship_mapper") {
    return language === "zh"
      ? `# relationship_mapper 关系图角色\n\n目标：在冻结的行业与证券域内识别可验证的供应链、所有权和传染关系。\n观察镜头：\n${renderCohortBehavior(lens)}\n\n工具：只调用 ${tools}；不得扩域或读取新闻。\n所有边、风险和结论必须满足 as-of/PIT 并引用真实 evidence_id。\n输出由运行时结构化 schema 强制。\n`
      : `# relationship_mapper graph role\n\nGoal: identify verifiable supply-chain, ownership, and contagion relationships inside the frozen domain.\nCohort lens:\n${renderCohortBehavior(lens)}\n\nTool: call only ${spec.requiredTools.join(", ")}; do not expand the domain or read news.\nEvery edge, risk, and conclusion must be as-of/PIT-valid and cite a real evidence_id.\nThe runtime structured schema is authoritative.\n`;
  }
  if (layer === "superinvestor") {
    const goal = SUPER_GOALS[agent];
    if (!goal) throw new Error(`superinvestor goal missing: ${agent}`);
    return language === "zh"
      ? `# ${agent} 投资风格角色\n\n目标：${goal.zh}\n观察镜头：\n${renderCohortBehavior(lens)}\n\n工具：只调用 ${tools}；只能使用运行时冻结的 Macro、行业输出和候选域。\n不得查询域外证券、新闻、政策搜索或研究报告，也不得读取冻结输入之外的信息。\n逐 pick 输出 thesis、conviction、期限和 claim_refs；主动不选必须有证据。\n输出由运行时结构化 schema 强制。\n`
      : `# ${agent} investor-style role\n\nGoal: ${goal.en}\nCohort lens:\n${renderCohortBehavior(lens)}\n\nTool: call only ${spec.requiredTools.join(", ")}; use only frozen Macro, sector, and candidate inputs.\nDo not query outside securities, news, policy search, or research reports, and do not read beyond the frozen inputs.\nEvery pick needs a thesis, conviction, horizon, and claim_refs; evidence is required for active abstention.\nThe runtime structured schema is authoritative.\n`;
  }
  const goal = DECISION_GOALS[agent];
  if (!goal) throw new Error(`decision goal missing: ${agent}`);
  return language === "zh"
    ? `# ${agent} 决策角色\n\n目标：${goal.zh}\n观察镜头：\n${renderCohortBehavior(lens)}\n\n工具：只调用 ${tools}；所有上游、持仓、约束和候选域均由运行时冻结。\n不得扩域、重算上游结论或读取冻结输入之外的信息。\n严格引用同一 run/stage lineage；必需快照不完整时拒绝。\n输出由运行时结构化 schema 强制。\n`
    : `# ${agent} decision role\n\nGoal: ${goal.en}\nCohort lens:\n${renderCohortBehavior(lens)}\n\nTool: call only ${spec.requiredTools.join(", ")}; upstream inputs, positions, constraints, and candidate scope are runtime-frozen.\nDo not expand scope, recompute upstream conclusions, or read beyond the frozen inputs.\nBind every conclusion to the same run/stage lineage and reject incomplete required snapshots.\nThe runtime structured schema is authoritative.\n`;
}

export const NON_MACRO_BUNDLED_AGENTS = [
  ...AGENTS_BY_LAYER.sector,
  ...AGENTS_BY_LAYER.superinvestor,
  ...AGENTS_BY_LAYER.decision,
] as const;
