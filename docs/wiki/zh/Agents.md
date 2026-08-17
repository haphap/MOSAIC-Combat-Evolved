# 智能体

MOSAIC 由四层 25 个逻辑 Agent、26 个可接受或跳过的执行阶段组成。CIO 包含
proposal 与 final 两个阶段，其余逻辑 Agent 各一个阶段。标准 stage roster 来自
`DAILY_CYCLE_STAGE_ROSTER`，提交后的运行时合同是
`registry/prompt_checks/runtime_agent_manifest_v5.json`。

## 第一层：宏观（8）

`china`、`us_economy`、`eu_economy`、`central_bank`、
`us_financial_conditions`、`euro_area_financial_conditions`、`commodities`、
`institutional_flow`。历史上的 `geopolitical` 和 `market_breadth` 已退休，
不在当前 roster 中。

八个 accepted transmission 分别交给下游。`macro_input_gate` 要求当前八个命名输出全部
通过；系统不再生成 Macro consensus、stance 或因子组聚合。详见
[Macro Agent 职责合同](../../macro_agent_role_contracts.md)。

## 第二层：行业（9）

九个标准行业 Agent 是 `semiconductor`、`technology`、`energy`、`biotech`、
`consumer`、`industrials`、`real_estate_construction`、`financials` 和
`agriculture`。历史上的 `relationship_mapper` 已退休，不在当前 roster 中。

标准行业 Agent 只比较冻结 PIT 股票池内已注册的细分方向。每次先做方向研究；只有
发生冲突时才进行一次复核；随后单独完成最终选择。accepted 输出始终包含一个最看好
方向和一个不同的最不看好方向、受约束的 long/short-or-avoid 个股、驱动、风险、
claims/证据、当前八个 Macro Agent 必需的 submission summary，以及适用的目标级 Macro
attribution。一次冲突复核后仍不能形成唯一最优/最差组合时，该阶段拒绝。输出不包含
多行业综合分。细分行业 ETF 的价格与份额变化只是补充确认；可选 ETF 证据缺失不能被
解释为负面票。

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
不得加入新候选或替换 proposal 快照。四个 Decision Agent 参与 Prompt 演化评价，但没有
下游 Darwinian usage weight。

MiroFish 始终为 simulation-only。RKE 报告上下文始终为 `RKE_SHADOW`，不得进入生产图
state、候选域、accepted output、Decision 输入、label 或 Darwinian 更新。

## Structured-smoke lineage

fixture-local 的 `structured-smoke:accepted:*` 引用与 runtime 的
`structured-smoke-accepted-output:*` 引用属于不同 identity domain。Sector 候选必须先在
fixture payload 内用自身 id/hash 自洽定位唯一 Sector Agent；随后通过
`STANDARD_SECTOR_SELECTION:<agent>` 关联 runtime state 的 accepted ref，并核验实际
accepted Layer-2 output 中存在该 ticker 的唯一 `LONG`。不能只按 ticker 匹配，也不能在两个
identity domain 之间直接 exact 比较 id/hash。

## 非生产验收记录

2025-06-17 structured-smoke 从精确空仓（`[]`）完成全部 25 个逻辑 Agent 和全部 26 个
stage。非生产决策为 `512480.SH` `BUY`/`ADD`，target weight 为 `0.04`、cash weight 为 `0.96`；
CRO 为 `NO_OBJECTION`，execution feasible，最终 gate 为 `PASS`，且
`production_eligible=false`。这是集成合同验收记录，不是实盘或纸上交易建议。

## Prompt 与演化

生产 prompt 私有仓共 400 份：8 个 cohort × 25 个 Agent × 2 种语言。中文文件使用
中文自然语言，英文文件使用英文；cohort 保留不同压力测试视角，但不得编码方向先验。
公库只保留 50 份双语 `cohort_default` fake/offline prompt；公开代码不能生成其余 7 个
私有 cohort 的观察镜头。

execution-behavior release manifest 原子绑定全部 prompt hash、结构化输出阶段、工具策略、
provider/model 行为、16 个 active production roster 和 Prompt execution baseline。
prompt 正文不暴露 mutator 策略、Darwinian 排名、label 公式或 promotion 阈值。
