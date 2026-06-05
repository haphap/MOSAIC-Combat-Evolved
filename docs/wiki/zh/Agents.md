# 智能体

MOSAIC 跑 **4 层共 25 个智能体**,由 LangGraph.js(`mosaic-ts/src/graph/daily_cycle.ts`)装配成单次 daily cycle。各 agent 在 `mosaic-ts/src/agents/<layer>/`;每层工厂(`_factory.ts`)与 schema(`_schemas.ts`)共享。

状态按层经 `mosaic-ts/src/agents/state.ts` 的逐层 map 流转(`layer1_outputs` … `layer4_outputs`,加顶层 `portfolio_actions` 镜像)。

## 第 1 层 —— 宏观 (10)

`central_bank`、`china`、`commodities`、`dollar`、`emerging_markets`、`geopolitical`、`institutional_flow`、`news_sentiment`、`volatility`、`yield_curve`。(`_aggregator.ts` 汇总 Layer-1 输出。)

Layer-1 agent 调用 sidecar 工具(Tushare/akshare/FRED/雪球 等)—— 如 `volatility` 用 `get_ivx` + `get_realized_volatility` + `get_etf_indicator(510050.SH)`;`emerging_markets` 用 `get_etf_price_data`;`china` 用 `get_property_data`(国房景气指数) + `get_policy_uncertainty`(EPU)。macro 层共 20 个工具。

## 第 2 层 —— 行业 (7)

`biotech`、`consumer`、`energy`、`financials`、`industrials`、`semiconductor`、`relationship_mapper`。把宏观语境转成行业选择 → 候选标的池。

六个行业 agent 共享 8 个核心工具 —— `get_industry_policy`、`get_xueqiu_heat`、`get_lhb_ranking`、`get_broker_research`(行业研报)、`get_etf_holdings`、`get_stock_data`、`get_indicators`、`get_industry_moneyflow`。行业特定补充:`energy` 额外调 `get_fred_series`;`financials` 额外调 `get_yield_curve_cn`。

`relationship_mapper` 在个股层面工作,用 `get_lhb_ranking` + `get_stock_research`(个股研报)。

## 第 3 层 —— 投资哲学 (4)

`ackman`、`aschenbrenner`、`baker`、`druckenmiller`。各以一种投资哲学视角审视 Layer-2 候选池(只引用上游分析中出现的 ticker —— 绝不杜撰代码)。四者都调用 `get_stock_research`(个股研报)、`get_fundamentals`、`get_stock_data`、`get_indicators`。`ackman` 额外调 `get_income_statement` / `get_cashflow` / `get_balance_sheet`(三张财报);`baker` 调 `get_income_statement` / `get_cashflow`;`druckenmiller` 调 `get_yield_curve_cn`。各 agent 还从各自基础画像继承少量情绪/政策工具(`get_industry_policy`、`get_xueqiu_heat`、`get_lhb_ranking` 中的若干),故上面每个 agent 列出的是其区分性工具,并非完整集合。

## 第 4 层 —— 决策 (4)

`cro`、`alpha_discovery`、`autonomous_execution`、`cio`(`mosaic-ts/src/agents/decision/`)。第 4 层是**纯综合** —— 不调工具;各自读上游状态推理:

- **cro** —— 风控 / 否决。
- **alpha_discovery** —— alpha 综合。
- **autonomous_execution** —— 把决策转成交易(读 CRO + alpha + L3 + Darwinian 权重)。
- **cio** —— 最终组合。写 `layer4_outputs.cio` 并把 `portfolio_actions` 镜像到顶层(单写者)。CIO 可推荐宽基 ETF 也可推荐个股。

### MiroFish 上下文注入(opt-in)

当 `config.mirofish.inject_context` 为真时,**CIO** 提示词会被追加一段 MiroFish 前瞻信息(最新情景上下文,带「仅模拟」免责声明 + `as_of_date` 防前视边界)。默认关闭。见 `decision/_factory.ts` 的 `maybeAppendMirofishContext`。

## 提示词

提示词双语,按 cohort 版本化于 `prompts/mosaic/` —— `cohort_default` 加 7 个 regime cohort(`cohort_bull_2007`、`cohort_crisis_2008`、`cohort_bull_2016`、`cohort_crisis_covid`、`cohort_recovery_2020`、`cohort_euphoria_2021`、`cohort_rate_tightening`)。Autoresearch 在 git 分支上演化它们(见[自我改进](Self-Improvement.md))。

提示词语言跟随 `config.output_language`(`pickPromptLanguage`:Chinese | English | Bilingual)。
