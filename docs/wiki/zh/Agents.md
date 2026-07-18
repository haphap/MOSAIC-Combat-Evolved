# 智能体

MOSAIC 由四层 28 个逻辑 Agent、29 个可接受或跳过的执行阶段组成。CIO 包含
proposal 与 final 两个阶段，其余逻辑 Agent 各一个阶段。标准 roster 来自
`AGENTS_BY_LAYER`，提交后的运行时合同是
`registry/prompt_checks/runtime_agent_manifest_v3.json`。

## 第一层：宏观（10）

`china`、`us_economy`、`eu_economy`、`central_bank`、
`us_financial_conditions`、`euro_area_financial_conditions`、`commodities`、
`geopolitical`、`market_breadth`、`institutional_flow`。

十个 accepted transmission 分别交给下游。`macro_input_gate` 要求十个命名输出全部
通过；系统不再生成 Macro consensus、stance 或因子组聚合。详见
[Macro Agent 职责合同](../../macro_agent_role_contracts.md)。

## 第二层：行业与关系（10）

九个标准行业 Agent 是 `semiconductor`、`technology`、`energy`、`biotech`、
`consumer`、`industrials`、`real_estate_construction`、`financials` 和
`agriculture`；第十个是 `relationship_mapper`。

标准行业 Agent 只比较冻结 PIT 股票池内已注册的细分方向。每次先做方向研究；只有
发生冲突时才进行一次复核；随后单独完成最终选择。accepted 输出包含一个最看好方向、
在确定性审计要求时的最不看好方向、受约束的 long/short-or-avoid 个股、驱动、风险、
claims/证据和十条 Macro attribution，不输出多行业综合分。细分行业 ETF 的价格与份额
变化只是补充确认；可选 ETF 证据缺失不能被解释为负面票。

## 第三层：投资哲学（4）

`druckenmiller`、`munger`、`burry`、`ackman` 使用不同投资哲学筛选运行时冻结的
候选域。它们只能调用 `get_superinvestor_candidate_snapshot`，不能扩展证券范围，
并输出有证据支持的候选或明确主动弃权。运行前机会集为空时直接跳过阶段，不产生
Darwinian 样本。

## 第四层：决策（4 个 Agent、5 个阶段）

固定顺序是：

`alpha_discovery → cio proposal → cro → autonomous_execution → cio final`。

各角色拥有专属快照和 outcome 合同。CIO proposal 冻结候选目标与 pre-CIO lineage；
CRO 只能审查该 proposal；Execution 只能判断经过 CRO 调整的订单意图；CIO final
不得加入新候选或替换 proposal 快照。四个 Decision Agent 参与 KNOT 演化评价，但没有
下游 Darwinian usage weight。

MiroFish 始终为 simulation-only。RKE 报告上下文始终为 `RKE_SHADOW`，不得进入生产图
state、候选域、accepted output、Decision 输入、label 或 Darwinian 更新。

## Prompt 与演化

生产 prompt 私有仓共 448 份：8 个 cohort × 28 个 Agent × 2 种语言。中文文件使用
中文自然语言，英文文件使用英文；cohort 保留不同压力测试视角，但不得编码方向先验。
公开 bundled prompt 仅用于 fake/offline。

execution-behavior release manifest 原子绑定全部 prompt hash、结构化输出阶段、工具策略、
provider/model 行为、16 个 active production roster 和 KNOT baseline。prompt 正文不暴露
research knobs、Darwinian 排名、label 公式或 KNOT 阈值。
