import { STANDARD_SECTOR_ROLE_CONTRACTS } from "../sector/_contracts.js";
import type { StandardSectorAgentId } from "../types.js";
import { renderCohortBehavior } from "./cohort_behavior.js";
import { AGENTS_BY_LAYER, LAYER_BY_AGENT, type Language } from "./cohorts.js";
import { RUNTIME_AGENT_SPEC_BY_AGENT } from "./runtime_agent_spec.js";

export const COHORT_LENSES: Readonly<Record<string, { zh: string; en: string }>> = {
  cohort_default: {
    zh: "不预设市场状态，只依据本次冻结证据判断。",
    en: "Assume no market regime; judge only the frozen evidence.",
  },
  cohort_bull_2007: {
    zh: "检验景气扩张中的持续性、拥挤和反转风险。",
    en: "Test persistence, crowding, and reversal risk during expansion.",
  },
  cohort_crisis_2008: {
    zh: "优先检验融资压力、相关性跃升和资产负债表脆弱性。",
    en: "Prioritize funding stress, correlation jumps, and balance-sheet fragility.",
  },
  cohort_bull_2016: {
    zh: "检验供给侧变化、周期盈利和政策传导的可持续性。",
    en: "Test supply-side change, cyclical earnings, and policy transmission durability.",
  },
  cohort_recovery_2020: {
    zh: "区分复苏基数效应、真实需求和政策退出敏感度。",
    en: "Separate recovery base effects, real demand, and policy-exit sensitivity.",
  },
  cohort_euphoria_2021: {
    zh: "提高对估值拥挤、叙事外推和流动性逆转的反证要求。",
    en: "Raise the burden of proof for valuation crowding, narrative extrapolation, and liquidity reversal.",
  },
  cohort_crisis_covid: {
    zh: "优先检验停摆、供应链断裂和政策对冲的时效。",
    en: "Prioritize shutdown, supply-chain disruption, and policy-offset timing.",
  },
  cohort_rate_tightening: {
    zh: "检验久期、融资成本、汇率和盈利下修的联动。",
    en: "Test duration, funding cost, FX, and earnings-revision interactions.",
  },
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
  const layer = LAYER_BY_AGENT[agent];
  if (!layer || layer === "macro") throw new Error(`unsupported bundled renderer agent: ${agent}`);
  const spec = RUNTIME_AGENT_SPEC_BY_AGENT.get(agent);
  if (!spec) throw new Error(`runtime spec missing for ${agent}`);
  const tools = spec.requiredTools.join("、");
  const lens = COHORT_LENSES[cohort]?.[language];
  if (!lens) throw new Error(`unsupported bundled cohort: ${cohort}`);
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
          "最终阶段严格服从运行时 selection directive，输出唯一 preferred、合格时的 least、受约束证券 picks、drivers、risks、claims 和十条 Macro attribution。",
          "所有数据必须满足 as-of/PIT；证据不足时按运行时合同拒绝或弃权，不得伪造中性结论。",
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
          "In final selection, obey the runtime directive and return one preferred direction, an eligible least-preferred direction, constrained security picks, drivers, risks, claims, and ten Macro attributions.",
          "Use only as-of/PIT-valid evidence; reject or abstain under the runtime contract when evidence is insufficient.",
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
      ? `# ${agent} 投资风格角色\n\n目标：${goal.zh}\n观察镜头：\n${renderCohortBehavior(lens)}\n\n工具：只调用 ${tools}；只能使用运行时冻结的 Macro、行业输出和候选域。\n不得查询域外证券、新闻、政策搜索或研究报告；不得看到原始权重或排名。\n逐 pick 输出 thesis、conviction、期限和 claim_refs；主动不选必须有证据。\n输出由运行时结构化 schema 强制。\n`
      : `# ${agent} investor-style role\n\nGoal: ${goal.en}\nCohort lens:\n${renderCohortBehavior(lens)}\n\nTool: call only ${spec.requiredTools.join(", ")}; use only frozen Macro, sector, and candidate inputs.\nDo not query outside securities, news, policy search, research reports, raw weights, or ranks.\nEvery pick needs a thesis, conviction, horizon, and claim_refs; evidence is required for active abstention.\nThe runtime structured schema is authoritative.\n`;
  }
  const goal = DECISION_GOALS[agent];
  if (!goal) throw new Error(`decision goal missing: ${agent}`);
  return language === "zh"
    ? `# ${agent} 决策角色\n\n目标：${goal.zh}\n观察镜头：\n${renderCohortBehavior(lens)}\n\n工具：只调用 ${tools}；所有上游、持仓、约束和候选域均由运行时冻结。\n不得扩域、重算上游结论或读取原始权重、排名和演化状态。\n严格引用同一 run/stage lineage；必需快照不完整时拒绝。\n输出由运行时结构化 schema 强制。\n`
    : `# ${agent} decision role\n\nGoal: ${goal.en}\nCohort lens:\n${renderCohortBehavior(lens)}\n\nTool: call only ${spec.requiredTools.join(", ")}; upstream inputs, positions, constraints, and candidate scope are runtime-frozen.\nDo not expand scope, recompute upstream conclusions, or read raw weights, ranks, or evolution state.\nBind every conclusion to the same run/stage lineage and reject incomplete required snapshots.\nThe runtime structured schema is authoritative.\n`;
}

export const NON_MACRO_BUNDLED_AGENTS = [
  ...AGENTS_BY_LAYER.sector,
  ...AGENTS_BY_LAYER.superinvestor,
  ...AGENTS_BY_LAYER.decision,
] as const;
