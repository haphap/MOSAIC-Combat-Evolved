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
          ...([
            "semiconductor",
            "technology",
            "energy",
            "biotech",
            "consumer",
            "industrials",
            "real_estate_construction",
            "financials",
            "agriculture",
          ].includes(agent)
            ? [
                `经济证据职责：${agent === "semiconductor" ? "快照与三表与 broker research" : "快照与 broker research"} 只用于 fundamentals、valuation、盈利现金流和财务风险；broker research 只能作为 as-of 研究证据，不能替代真实价格或财报；ETF 持仓、stock_data、indicators 与 industry_moneyflow 只用于暴露、价格技术与 positioning；role events、policy 与 supply-chain 只用于 catalysts/risk；RKE 仅作先验。price/flow/technical 仅用于当前 5D 决策确认，fundamentals/valuation 用于中期 thesis/risk；中期证据不得冒充已实现 5D 结果。未解决冲突必须降低 confidence；关键证据在 claim 中标记 UNKNOWN；若仍无法形成唯一 preferred/least，则 ABSTAIN/拒绝阶段。最终进入 accepted output 的 claims 必须按实际使用工具引用对应 result-event evidence_id；direction_research 的 compact comparison contract 保持不变。`,
              ]
            : []),
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
          ...([
            "semiconductor",
            "technology",
            "energy",
            "biotech",
            "consumer",
            "industrials",
            "real_estate_construction",
            "financials",
            "agriculture",
          ].includes(agent)
            ? [
                `Economic evidence duties: use ${agent === "semiconductor" ? "the snapshot, the three statements, and broker research" : "the snapshot and broker research"} only for fundamentals, valuation, earnings/cash flow, and financial risk; broker research is only as-of research evidence and cannot replace real prices or filings; use ETF holdings, stock_data, indicators, and industry_moneyflow only for exposure, price/technicals, and positioning; use role events, policy, and supply-chain only for catalysts/risk; RKE is prior context only. Use price/flow/technicals only for current 5D decision confirmation, and fundamentals/valuation for the medium-term thesis/risk; medium-term evidence must not be presented as a realized 5D result. Unresolved conflicts must lower confidence; mark missing critical evidence as UNKNOWN in the claim; if a unique preferred/least pair still cannot be formed, ABSTAIN/reject the stage. Claims entering the accepted output must cite the result-event evidence_id for each tool actually used; keep the direction_research compact comparison contract unchanged.`,
              ]
            : []),
          "In final selection, obey the runtime directive and return one preferred direction and one distinct least-preferred direction, constrained security picks, drivers, risks, claims, and the required Macro summary and applicable target-level attributions.",
          "Use only as-of/PIT-valid evidence; reject the stage if direction evidence cannot establish a unique best/worst pair. A security leg may use NO_QUALIFIED_SECURITY only when runtime proves its frozen shortlist is empty; a non-empty shortlist requires picks.",
          "The runtime structured schema is authoritative.",
          "",
        ].join("\n");
  }
  if (agent === "relationship_mapper") {
    return language === "zh"
      ? `# relationship_mapper 关系图角色\n\n目标：在冻结的行业与证券域内识别可验证的供应链、所有权和传染关系。\n观察镜头：\n${renderCohortBehavior(lens)}\n\n工具：只调用 ${tools}；不得扩域或读取新闻。\n所有边、风险和结论必须满足 as-of/PIT 并引用真实 evidence_id。\n\`factual_edges\` 必须逐一且仅一次回显全部冻结事实元组，不得删减、新增、反转或改写关系类型。运行时从已验证快照投影最终事实字段，模型只附加 claim 引用；预测边可以弃权，事实边不得缩减。\n输出由运行时结构化 schema 强制。\n`
      : `# relationship_mapper graph role\n\nGoal: identify verifiable supply-chain, ownership, and contagion relationships inside the frozen domain.\nCohort lens:\n${renderCohortBehavior(lens)}\n\nTool: call only ${spec.requiredTools.join(", ")}; do not expand the domain or read news.\nEvery edge, risk, and conclusion must be as-of/PIT-valid and cite a real evidence_id.\n\`factual_edges\` must restate every frozen factual tuple exactly once: never omit, add, reverse, or retype one. The runtime projects accepted factual fields from the verified snapshot; the model only attaches claim references. Predictive edges may abstain, but factual edges may not be reduced.\nThe runtime structured schema is authoritative.\n`;
  }
  if (layer === "superinvestor") {
    const goal = SUPER_GOALS[agent];
    if (!goal) throw new Error(`superinvestor goal missing: ${agent}`);
    const evidenceBoundary =
      agent === "druckenmiller"
        ? language === "zh"
          ? "候选快照只定义冻结机会集和上游 conviction lineage，不是买卖信号。fundamentals 用于盈利质量与估值；stock_data 与 indicators 用于趋势、动量与波动；yield_curve 与 policy 用于宏观条件与催化；stock_research 仅作 as-of 研究证据，不能替代真实价格或财务数据；RKE 仅作先验。证据冲突必须降低 confidence；关键证据缺失时按运行时合同拒绝，不得伪造 empty candidate。最终进入 accepted output 的 claims 必须按实际使用工具引用对应 result-event evidence_id。当前证据不得冒充已实现的 21 日结果；Autoresearch 的独立标签为 T+1 open 后 21 个交易日。\n"
          : "The candidate snapshot defines only the frozen opportunity set and upstream conviction lineage; it is not a buy/sell signal. Use fundamentals for earnings quality and valuation; stock_data and indicators for trend, momentum, and volatility; yield_curve and policy for macro conditions and catalysts; stock_research only as as-of research evidence and never as a substitute for real prices or financial data; RKE as prior context only. Evidence conflicts must lower confidence; reject under the runtime contract when critical evidence is missing, and never fabricate an empty candidate set. Claims entering the accepted output must cite the result-event evidence_id for each tool actually used. Current evidence must not be presented as a realized 21-day result; Autoresearch uses an independent label over 21 trading days after T+1 open.\n"
        : agent === "munger"
          ? language === "zh"
            ? "候选快照只定义冻结机会集和上游 conviction lineage，不是买卖信号。fundamentals 用于 ROIC、盈利能力与估值；balance sheet、income statement 与 cashflow 分别用于资本结构、利润率与盈利稳定性、现金转化与资本开支；stock_data 只用于价格、回撤与入场上下文，不能证明 moat；stock_research 仅作 as-of 护城河、竞争格局与盈利预期佐证，不能替代真实财务或价格；RKE 仅作先验。证据冲突必须降低 confidence；关键证据缺失时按现有 runtime contract 拒绝，不得伪造 empty candidate。最终进入 accepted output 的 claims 必须按实际使用工具引用真实 result-event evidence_id。holding_period 是 thesis horizon；当前证据不得冒充已实现结果。Autoresearch 的独立 T+1 open 后 21 个交易日 net excess return 只演进候选选择、短期风险与入场、机会成本，不验证也不得演进 moat、ROIC 或 compounding 判据，这些长期 thesis 当前保持未成熟。\n"
            : "The candidate snapshot defines only the frozen opportunity set and upstream conviction lineage; it is not a buy/sell signal. Use fundamentals for ROIC, profitability, and valuation; the balance sheet, income statement, and cashflow for capital structure, margin and earnings stability, and cash conversion and capital expenditure, respectively; stock_data only for price, drawdown, and entry context, never as proof of a moat; stock_research only as as-of support for moat, competition, and earnings expectations, never as a substitute for real financial or price data; RKE as prior context only. Evidence conflicts must lower confidence; reject under the existing runtime contract when critical evidence is missing, and never fabricate an empty candidate set. Claims entering the accepted output must cite real result-event evidence_id values for each tool actually used. holding_period is the thesis horizon; current evidence must not be presented as a realized result. Autoresearch's independent net excess return over 21 trading days after T+1 open may evolve only candidate selection, short-term risk and entry, and opportunity cost; it neither validates nor may evolve moat, ROIC, or compounding criteria, whose long-term theses remain immature under the current contract.\n"
          : agent === "burry"
            ? language === "zh"
              ? "候选快照只定义冻结机会集和上游 conviction lineage，不是买卖信号。fundamentals 用于估值错配、盈利能力与盈利质量；balance sheet 用于资产支持、杠杆、流动性与偿债能力；income statement 与 cashflow 用于盈利质量、现金消耗与再融资风险；stock_data 用于价格路径、波动、回撤与反身性反馈，不能证明 intrinsic value；stock_research 仅作 as-of 共识错配、催化与盈利预期佐证，不能替代真实财务或价格；RKE 仅作先验。证据冲突必须降低 confidence；关键证据缺失时按现有 runtime contract 拒绝，不得伪造 empty candidate。最终进入 accepted output 的 claims 必须按实际使用工具引用真实 result-event evidence_id。holding_period 是 thesis horizon；当前证据不得冒充已实现结果。Autoresearch 的独立 T+1 open 后 21 个交易日 net excess return 只演进候选选择、短期 downside/reflexive path、催化兑现与入场、机会成本；它不能证明 intrinsic value 或 balance-sheet quality。\n"
              : "The candidate snapshot defines only the frozen opportunity set and upstream conviction lineage; it is not a buy/sell signal. Use fundamentals for valuation dislocation, profitability, and earnings quality; the balance sheet for asset support, leverage, liquidity, and debt service; the income statement and cashflow for earnings quality, cash burn, and refinancing risk; stock_data for price path, volatility, drawdown, and reflexive feedback, never as proof of intrinsic value; stock_research only as as-of support for consensus dislocation, catalysts, and earnings expectations, never as a substitute for real financial or price data; RKE as prior context only. Evidence conflicts must lower confidence; reject under the existing runtime contract when critical evidence is missing, and never fabricate an empty candidate set. Claims entering the accepted output must cite real result-event evidence_id values for each tool actually used. holding_period is the thesis horizon; current evidence must not be presented as a realized result. Autoresearch's independent net excess return over 21 trading days after T+1 open may evolve only candidate selection, short-term downside and reflexive path, catalyst realization and entry, and opportunity cost; it cannot prove intrinsic value or balance-sheet quality.\n"
            : agent === "ackman"
              ? language === "zh"
                ? "候选快照只定义冻结机会集和上游 conviction lineage，不是买卖信号。fundamentals 用于质量、盈利能力与估值；balance sheet、income statement 与 cashflow 分别用于资本结构、利润率与盈利稳定性、现金转化与资本配置；stock_data 只用于价格、回撤、催化反应与入场上下文，不能证明 governance improvement 或 durable quality；stock_research 仅作 as-of 治理、催化与盈利预期佐证，不能替代真实财务或价格；RKE 仅作先验。证据冲突必须降低 confidence；关键证据缺失时按现有 runtime contract 拒绝，不得伪造 empty candidate。最终进入 accepted output 的 claims 必须按实际使用工具引用真实 result-event evidence_id。holding_period 是 thesis horizon；当前证据不得冒充已实现结果。Autoresearch 的独立 T+1 open 后 21 个交易日 net excess return 只演进候选选择、短期 downside、催化兑现与入场、机会成本；它不能证明 governance improvement 或 durable quality。\n"
                : "The candidate snapshot defines only the frozen opportunity set and upstream conviction lineage; it is not a buy/sell signal. Use fundamentals for quality, profitability, and valuation; the balance sheet, income statement, and cashflow for capital structure, margin and earnings stability, and cash conversion and capital allocation, respectively; stock_data only for price, drawdown, catalyst reaction, and entry context, never as proof of governance improvement or durable quality; stock_research only as as-of support for governance, catalysts, and earnings expectations, never as a substitute for real financial or price data; RKE as prior context only. Evidence conflicts must lower confidence; reject under the existing runtime contract when critical evidence is missing, and never fabricate an empty candidate set. Claims entering the accepted output must cite real result-event evidence_id values for each tool actually used. holding_period is the thesis horizon; current evidence must not be presented as a realized result. Autoresearch's independent net excess return over 21 trading days after T+1 open may evolve only candidate selection, short-term downside, catalyst realization and entry, and opportunity cost; it cannot prove governance improvement or durable quality.\n"
              : "";
    return language === "zh"
      ? `# ${agent} 投资风格角色\n\n目标：${goal.zh}\n观察镜头：\n${renderCohortBehavior(lens)}\n\n工具：只调用 ${tools}；只能使用运行时冻结的 Macro、行业输出和候选域。\n不得查询域外证券或新闻；政策和研报只能用于冻结候选及 as-of/PIT 时间窗，且必须来自已授权工具。不得读取冻结输入之外的信息。\n${evidenceBoundary}逐 pick 输出 thesis、conviction、期限和 claim_refs；主动不选必须有证据。\n输出由运行时结构化 schema 强制。\n`
      : `# ${agent} investor-style role\n\nGoal: ${goal.en}\nCohort lens:\n${renderCohortBehavior(lens)}\n\nTool: call only ${spec.requiredTools.join(", ")}; use only frozen Macro, sector, and candidate inputs.\nDo not query out-of-domain securities or news. Use policy and research material only for the frozen candidate and as-of/PIT window through authorized tools. Do not read beyond the frozen inputs.\n${evidenceBoundary}Every pick needs a thesis, conviction, horizon, and claim_refs; evidence is required for active abstention.\nThe runtime structured schema is authoritative.\n`;
  }
  const goal = DECISION_GOALS[agent];
  if (!goal) throw new Error(`decision goal missing: ${agent}`);
  const executionBoundary =
    agent === "autonomous_execution"
      ? language === "zh"
        ? "只使用冻结的 CIO proposal、CRO 控制、订单意图与执行证据；不得直接读取、复述或归因 Macro gate 或八个 Macro 输出。\n"
        : "Use only the frozen CIO proposal, CRO controls, order intents, and execution evidence. Do not directly read, restate, or attribute the Macro gate or eight Macro outputs.\n"
      : "";
  const evidenceBoundary =
    agent === "cro"
      ? language === "zh"
        ? "CRO risk snapshot 只定义冻结 proposal candidates、current/proposed weights、portfolio exposure 与 policy limits，不是已实现风险状态；不得新增、删除或替换 ticker，也不得重算上游。role_event 只用于 as-of 日历型风险催化，不能替代 proposal、position 或 constraint；RKE 仅作先验。对每个冻结 candidate 必须决定 VETO、CAP_WEIGHT、REDUCE_WEIGHT、REQUIRE_REVIEW 或 NO_OBJECTION，并将 correlated risks 与 black swan 风险绑定到真实 evidence。证据缺口或冲突必须降低 confidence；关键证据缺失时按现有 runtime contract 拒绝，不得伪造空输入或空结果。最终进入 accepted output 的 claims 必须按实际使用工具引用真实 result-event evidence_id。当前证据不得冒充已实现的 5D risk。Autoresearch 的独立 5D realized-risk label 只评估 action precision、recall、specificity 与 probability calibration。fallback=false 表示证据不完整时必须拒绝，不得以替代或合成输出继续。\n"
        : "The CRO risk snapshot defines only frozen proposal candidates, current and proposed weights, portfolio exposure, and policy limits; it is not a realized risk state. Never add, remove, or replace a ticker or recompute upstream work. Use role_event only for as-of calendar risk catalysts, never as a substitute for the proposal, position, or constraint; use RKE as prior context only. Decide VETO, CAP_WEIGHT, REDUCE_WEIGHT, REQUIRE_REVIEW, or NO_OBJECTION for every frozen candidate, and bind correlated risks and black-swan risks to real evidence. Evidence gaps or conflicts must lower confidence; reject under the existing runtime contract when critical evidence is missing, and never fabricate empty inputs or results. Claims entering the accepted output must cite real result-event evidence_id values for each tool actually used. Current evidence must not be presented as realized 5D risk. Autoresearch's independent 5D realized-risk label evaluates only action precision, recall, specificity, and probability calibration; . fallback=false means incomplete evidence must be rejected, never continued through a substitute or synthetic output.\n"
      : agent === "alpha_discovery"
        ? language === "zh"
          ? "Alpha snapshot 只定义冻结 novel candidates 与已排除的 upstream-selected tickers，不是买卖信号；不得新增或替换 ticker、恢复 excluded ticker、查询域外证券或扩大 universe。role_event 仅用于 as-of 催化与风险，不能替代候选 lineage；RKE 仅作先验。每个 novel_pick 必须逐一绑定 snapshot 中完全一致的 candidate_ref 与 ts_code。NONE_FOUND 必须由完整冻结候选证据支持，不能因未调用工具或缺失证据而伪造。证据冲突必须降低 confidence；关键证据缺失时按现有 runtime contract 拒绝。最终进入 accepted output 的 claims 必须按实际使用工具引用真实 result-event evidence_id。当前证据不得冒充已实现的 5D alpha。Autoresearch 的独立 5D label 只评估 selected-pick utility、incremental utility、missed opportunity 与 confidence calibration。fallback=false 表示证据缺失即拒绝。\n"
          : "The Alpha snapshot defines only frozen novel candidates and excluded upstream-selected tickers; it is not a buy/sell signal. Never add or replace a ticker, restore an excluded ticker, query an out-of-domain security, or expand the universe. Use role_event only for as-of catalysts and risks, never as a substitute for candidate lineage; use RKE as prior context only. Every novel_pick must bind the exact candidate_ref and ts_code from the snapshot. NONE_FOUND requires complete frozen-candidate evidence and must never be fabricated because tools were not called or evidence is missing. Evidence conflicts must lower confidence; reject under the existing runtime contract when critical evidence is missing. Claims entering the accepted output must cite real result-event evidence_id values for each tool actually used. Current evidence must not be presented as realized 5D alpha. Autoresearch's independent 5D label evaluates only selected-pick utility, incremental utility, missed opportunity, and confidence calibration; . fallback=false means missing evidence must be rejected.\n"
        : agent === "autonomous_execution"
          ? language === "zh"
            ? "get_execution_snapshot 只定义 CIO proposal 与可选 CRO control 后冻结的 order intents、current/target/requested delta、execution mode、liquidity vintage 与 policy constraints，不是成交结果或执行批准。不得新增、删除或替换 ticker，不得改变 side 或 requested_delta_weight，也不得扩大 universe；每笔输出必须 exact 绑定 snapshot 的 order_intent_ref、ts_code 与 requested_delta_weight，并一对一覆盖冻结订单集合。get_role_event_snapshot 只用于 as-of 或 next-session 日历与运营执行风险，不能替代流动性、政策或订单证据；get_rke_research_context 仅作先验。对每个冻结 intent 必须按现有 runtime structured contract 给出 FEASIBLE、PARTIAL 或 BLOCKED、predicted cost bps 与 feasibility confidence，并遵守 max_slippage、max_participation、min_trade、max_slice 与 prohibited constraints。NO_DELTA 必须由完整冻结证据证明确实没有 actionable order；BLOCKED 必须是逐笔证据支持的执行判断，不能因工具未调用或证据缺失而伪造。关键证据缺失时按现有 contract 拒绝 stage；证据冲突必须降低 confidence。最终进入 accepted output 的 claims 必须按实际使用工具引用真实 result-event evidence_id。当前证据不得冒充已实现的 T+1 execution。Autoresearch 的独立 next-session outcome 只评估 normalized cost error 40%、feasibility classification 30%、target-delta attainment 20% 与 policy compliance 10%。fallback=false 表示证据缺失即拒绝。\n"
            : "get_execution_snapshot defines only the frozen order intents after the CIO proposal and optional CRO control, including current, target, and requested delta, execution mode, liquidity vintage, and policy constraints; it is not a fill result or execution approval. Never add, remove, or replace a ticker, change side or requested_delta_weight, or expand the universe. Every output row must exactly bind the snapshot order_intent_ref, ts_code, and requested_delta_weight and cover the frozen order set one-to-one. Use get_role_event_snapshot only for as-of or next-session calendar and operational execution risks, never as a substitute for liquidity, policy, or order evidence; use get_rke_research_context as prior context only. For every frozen intent, use the existing runtime structured contract to return FEASIBLE, PARTIAL, or BLOCKED, predicted cost bps, and feasibility confidence while obeying max_slippage, max_participation, min_trade, max_slice, and prohibited constraints. NO_DELTA requires complete frozen evidence proving there is no actionable order. BLOCKED must be an evidence-backed per-intent execution judgment and must never be fabricated because tools were not called or evidence is missing. Reject the stage under the existing contract when critical evidence is missing; evidence conflicts must lower confidence. Claims entering the accepted output must cite real result-event evidence_id values for each tool actually used. Current evidence must not be presented as realized T+1 execution. Autoresearch's independent next-session outcome evaluates only normalized cost error at 40%, feasibility classification at 30%, target-delta attainment at 20%, and policy compliance at 10%; . fallback=false means missing evidence must be rejected.\n"
          : agent === "cio"
            ? language === "zh"
              ? "PROPOSAL：get_cio_decision_snapshot 只冻结八个 Macro transmission evidence、九个 Sector accepted selections、四个 Superinvestor selections、Alpha novel picks、current positions、previous target 与 policy constraints；Macro evidence 不是新增 ticker 的授权。候选只来自 snapshot 去重后的 accepted candidates 与 current positions；不得新增或替换 ticker、重算上游或扩大 universe。target_positions 只能使用冻结 ts_code；每项必须用真实 claims 支持 position_decision、target_weight、holding_period、thesis_status 与 risk_flags，target weights 加 cash 必须等于 1，并遵守 max_total_target_weight、min_cash_weight、max_single_name_weight 与 restricted_ts_codes。PROPOSAL 只形成候选 target，不是 CRO/Execution 后的最终组合，也没有独立 realized outcome；不得把当前证据或自评 confidence 当作收益。FINAL：snapshot 只冻结同一 accepted CIO proposal、可选 CRO control、可选 Execution control、current positions、liquidity vintage 与 policy；不得回到上游重新选股或新增 ticker。final target portfolio 只能保持 proposal 或更保守；每一个 present CRO/Execution control resolution 的 resolution 枚举只能是 COMPLIED 或 MORE_CONSERVATIVE，并分别按 cro_action_local_ref 与 execution_assessment_local_ref 精确解析，不得放宽控制。target 与 cash 仍须满足冻结约束。HOLD_CURRENT 或 ALL_CASH 必须由完整冻结证据支持，不能因工具未调用或关键证据缺失而伪造；缺失时按现有 contract 拒绝 stage。两阶段共同：get_rke_research_context 仅作先验，不能直接生成交易；证据冲突必须降低 confidence。最终进入 accepted output 的 claims 必须按实际使用工具引用真实 result-event evidence_id。只有 accepted CIO_FINAL 有独立 T+1 open 后 5D outcome：relative return 50%、drawdown 25%、turnover cost 15%、constraint compliance 10%。PROPOSAL 没有单独 outcome，只能通过同 lineage 的 final 经济结果演进；当前证据不得冒充已实现的 5D 结果。fallback=false 表示证据缺失即拒绝。\n"
              : "PROPOSAL: get_cio_decision_snapshot freezes only eight Macro transmission evidence sets, nine Sector accepted selections, four Superinvestor selections, Alpha novel picks, current positions, the previous target, and policy constraints; Macro evidence is not authority to add a ticker. Candidates come only from deduplicated accepted candidates and current positions in the snapshot. Never add or replace a ticker, recompute upstream work, or expand the universe. target_positions may use only frozen ts_code values; real claims must support each position_decision, target_weight, holding_period, thesis_status, and risk_flags. Target weights plus cash must equal 1 and obey max_total_target_weight, min_cash_weight, max_single_name_weight, and restricted_ts_codes. PROPOSAL forms only a candidate target, not the final portfolio after CRO and Execution, and has no independent realized outcome; never treat current evidence or self-assessed confidence as return. FINAL: the snapshot freezes only the same accepted CIO proposal, optional CRO control, optional Execution control, current positions, liquidity vintage, and policy. Never return upstream to select securities or add a ticker. The final target portfolio may only preserve the proposal or become more conservative. For every present CRO or Execution control resolution, the resolution enum may only be COMPLIED or MORE_CONSERVATIVE and must resolve exactly through cro_action_local_ref or execution_assessment_local_ref, respectively; never loosen a control. Target and cash must still satisfy frozen constraints. HOLD_CURRENT or ALL_CASH requires complete frozen evidence and must never be fabricated because tools were not called or critical evidence is missing; reject the stage under the existing contract when evidence is missing. BOTH STAGES: use get_rke_research_context as prior context only; it cannot directly create trades. Evidence conflicts must lower confidence. Claims entering the accepted output must cite real result-event evidence_id values for each tool actually used. Only accepted CIO_FINAL has an independent 5D outcome after T+1 open: relative return 50%, drawdown 25%, turnover cost 15%, and constraint compliance 10%. PROPOSAL has no separate outcome and may evolve only through the economic result of the same-lineage final; current evidence must not be presented as a realized 5D result. fallback=false means missing evidence must be rejected.\n"
            : "";
  return language === "zh"
    ? `# ${agent} 决策角色\n\n目标：${goal.zh}\n观察镜头：\n${renderCohortBehavior(lens)}\n\n工具：只调用 ${tools}；所有上游、持仓、约束和候选域均由运行时冻结。\n${executionBoundary}${evidenceBoundary}不得扩域、重算上游结论或读取冻结输入之外的信息。\n严格引用同一 run/stage lineage；必需快照不完整时拒绝。\n输出由运行时结构化 schema 强制。\n`
    : `# ${agent} decision role\n\nGoal: ${goal.en}\nCohort lens:\n${renderCohortBehavior(lens)}\n\nTool: call only ${spec.requiredTools.join(", ")}; upstream inputs, positions, constraints, and candidate scope are runtime-frozen.\n${executionBoundary}${evidenceBoundary}Do not expand scope, recompute upstream conclusions, or read beyond the frozen inputs.\nBind every conclusion to the same run/stage lineage and reject incomplete required snapshots.\nThe runtime structured schema is authoritative.\n`;
}

export const NON_MACRO_BUNDLED_AGENTS = [
  ...AGENTS_BY_LAYER.sector,
  ...AGENTS_BY_LAYER.superinvestor,
  ...AGENTS_BY_LAYER.decision,
] as const;
