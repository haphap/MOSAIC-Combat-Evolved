# 智能体

MOSAIC 跑 **4 层共 25 个智能体**,由 LangGraph.js(`mosaic-ts/src/graph/daily_cycle.ts`)装配成单次 daily cycle。各 agent 在 `mosaic-ts/src/agents/<layer>/`;每层工厂(`_factory.ts`)与 schema(`_schemas.ts`)共享。
Canonical roster 为 `AGENTS_BY_LAYER`，其分阶段 committed form 是
`registry/prompt_checks/runtime_agent_manifest_v2.json`。

状态按层经 `mosaic-ts/src/agents/state.ts` 的逐层 map 流转(`layer1_outputs` … `layer4_outputs`,加顶层 `portfolio_actions` 镜像)。

## 第 1 层 —— 宏观 (10)

`china`、`us_economy`、`central_bank`、`dollar`、`yield_curve`、
`commodities`、`geopolitical`、`volatility`、`market_breadth`、
`institutional_flow`。`emerging_markets` 与 `news_sentiment` 仅保留为
`legacy_unverified` 审计记录。(`_aggregator.ts` 汇总 Layer-1 输出。)

每个 Layer-1 角色只读取一个职责限定的 PIT 快照。Tushare 是结构化主来源；
美国历史修订只使用预注册的 ALFRED/官方 vintage，不做隐式 fallback。新闻仅作为
`china` 与 `geopolitical` 的事件证据。`market_breadth` 读取确定性生成的等权
A 股广度指标，模型不自行计算。详见
[Macro Agent 职责合同](../../macro_agent_role_contracts.md)。

## 第 2 层 —— 行业 (7)

`biotech`、`consumer`、`energy`、`financials`、`industrials`、`semiconductor`、`relationship_mapper`。把宏观语境转成行业选择 → 候选标的池。

六个行业 agent 共享 8 个核心工具 —— `get_industry_policy`、`get_xueqiu_heat`、`get_lhb_ranking`、`get_broker_research`(行业研报)、`get_etf_holdings`、`get_stock_data`、`get_indicators`、`get_industry_moneyflow`。行业特定补充:`energy` 额外调 `get_fred_series`;`financials` 额外调 `get_yield_curve_cn`。

`relationship_mapper` 在个股层面工作,用 `get_lhb_ranking` + `get_stock_research`(个股研报)。

## 第 3 层 —— 投资哲学 (4)

`ackman`、`burry`、`druckenmiller`、`munger`。各以一种投资哲学视角审视 Layer-2 候选池(只引用上游分析中出现的 ticker —— 绝不杜撰代码)。四者都调用 `get_stock_research`(个股研报)、`get_fundamentals`、`get_stock_data`、`get_indicators`。`ackman` 和 `munger` 额外调 `get_income_statement` / `get_cashflow` / `get_balance_sheet`(三张财报);`burry` 调同样的财报工具，并结合情绪/资金流检查逆向语境;`druckenmiller` 调 `get_yield_curve_cn`。各 agent 还从各自基础画像继承少量情绪/政策工具(`get_industry_policy`、`get_xueqiu_heat`、`get_lhb_ranking` 中的若干),故上面每个 agent 列出的是其区分性工具,并非完整集合。

## 第 4 层 —— 决策 (4)

`cro`、`alpha_discovery`、`autonomous_execution`、`cio`(`mosaic-ts/src/agents/decision/`)。第 4 层是**纯综合** —— 不调工具;各自读上游状态推理:

- **cro** —— 风控 / 否决。
- **alpha_discovery** —— alpha 综合。
- **autonomous_execution** —— 把决策转成交易(读 CRO + alpha + L3 + Darwinian 权重)。
- **cio** —— 最终组合。写 `layer4_outputs.cio` 并把 `portfolio_actions` 镜像到顶层(单写者)。CIO 可推荐宽基 ETF 也可推荐个股。

### MiroFish 上下文注入

当 `config.mirofish.inject_context` 为真(默认开启)时,第 4 层 **CRO**、**autonomous_execution** 和 **CIO** 在同一次 run 中共享同一段追加的 MiroFish 前瞻信息(最新情景上下文,带「仅模拟」免责声明、context hash 和 `as_of_date` 防前视边界)。成功执行 `mirofish generate` 或非 dry-run 的 `mirofish train` 会自动刷新 context。context 必须带 `scenario_count`、`horizon_days`、`as_of_date`、`context_hash` 和 `generator_version`;字段不完整或 lookahead 的 context 会在 prompt injection 前禁用。MiroFish 仍是 simulation-only:不能替代当前账户或当前市场证据,受其影响的持仓变更也必须通过 L4 position validator。autonomous_execution 节点还会在输出进入 CIO 前,对已激活的最小交易 delta、滑点上限和流动性下限 execution cards 做运行时校验。见 `decision/_factory.ts` 的 `maybeAppendMirofishContext` 和 L4 validators。

RKE report context 仍是 shadow-only research prior。若 portfolio action 声明的
影响来源只有 RKE prior 和/或 MiroFish simulation context,CIO 校验会拒绝。
当 CIO action 覆盖已激活的 `max_single_name_weight` guard 时,L4 position
validator 还要求同时提供 `override_reason` 和 `cro_risk_override` risk flag。
若 stop-loss 已触发但仍 `HOLD`,还必须在 decision reason 或 dissent notes
中给出明确反证。

## 提示词

提示词双语,按 cohort 版本化于 `prompts/mosaic/` —— `cohort_default` 加 7 个 regime cohort(`cohort_bull_2007`、`cohort_crisis_2008`、`cohort_bull_2016`、`cohort_crisis_covid`、`cohort_recovery_2020`、`cohort_euphoria_2021`、`cohort_rate_tightening`)。Autoresearch 在 git 分支上演化它们(见[自我改进](Self-Improvement.md))。

提示词语言跟随 `config.output_language`(`pickPromptLanguage`:Chinese | English | Bilingual)。
