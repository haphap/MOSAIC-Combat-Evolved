# Macro Agent 中国视角职责、数据与直接下游消费重构计划（公开版）

日期：2026-07-18

状态：实施中

## 1. 公开范围

本文只记录可公开的 Agent roster、职责、数据边界、结构化输出和交付要求。
KNOT/research-knob 的具体定义、参数、评分、调度、配对、晋级、回滚、私有
projection 和实现代码属于私有资产，不得进入本仓库、公开 PR、CI artifact 或模型可见
prompt。

私有规范位于 `MOSAIC-Prompts` 的同名文件。公开代码固定以下私有规范文本的 opaque 审计
hash：

`sha256:974eeab60fde565efa4cd99f63f614792b190094af2671b103464b6e6e65e551`

该 hash 只闭合跨仓规范审计，不是 runtime source of truth。生产权威仍是
`registry/prompt_checks/knot_runtime_contract_ref_v2.json` 与
`registry/prompt_checks/private_knot_assets_ref_v1.json` 中版本化的 opaque runtime/assets refs。

生产运行必须从固定的私有 commit 加载并验证这些资产；缺失、版本不符或 hash 不符时失败
关闭。bundled prompt 和公开 fake mode 不包含生产 KNOT 内容，也不得成为生产 champion。

## 2. Agent roster 与职责

运行时保留 28 个逻辑 Agent、29 个执行阶段：10 Macro、10 Sector/Relationship、
4 Superinvestor、4 Decision。

Macro Agent：

- `china`：中国增长、价格、信用、外需和财政脉冲。
- `us_economy`：美国实体经济周期及其对 A 股外需的传导。
- `eu_economy`：欧盟实体经济条件及其对中国出口和风险偏好的影响。
- `central_bank`：仅从中国视角分析 PBOC、人民币流动性与中国利率曲线。
- `us_financial_conditions`：统一分析 Fed、美元、美国曲线、信用与跨境金融冲击。
- `euro_area_financial_conditions`：欧元区货币、利率、信用与金融压力传导。
- `commodities`：能源、工业金属、黄金、库存/期限结构与输入成本冲击。
- `geopolitical`：事件状态、传导渠道、严重度、期限与观察触发器。
- `market_breadth`：A 股参与度、趋势/成交广度、新高新低与集中度。
- `institutional_flow`：全市场资金、行业轮动、ETF 份额和拥挤度。

Sector/Relationship Agent：

- `semiconductor`、`technology`、`energy`（含新能源）、`biotech`、`consumer`
  （含汽车）、`industrials`（含有色、黑色、钢铁和化工）、
  `real_estate_construction`、`financials`、`agriculture`、`relationship_mapper`。
- 标准 Sector 必须在注册的细分行业全集中比较，输出最看好和最不看好的方向、
  long/short 股票 picks、驱动、风险、claims、证据和 Macro attribution。
- 细分行业比较必须纳入对应 ETF 的 PIT 走势、成交/资金与相对强弱；不得临时发明
  分类或用单只股票替代全行业。

Superinvestor Agent 为 `druckenmiller`、`munger`、`burry`、`ackman`。Decision Agent 为
`cro`、`alpha_discovery`、`autonomous_execution`、`cio`；CIO 有 proposal/final 两个阶段。

## 3. 数据边界

- Tushare 是中国宏观、行情、资金、期货、外汇、利率与 `eco_cal` 的主要来源。
- 美国关键宏观历史修订按预注册官方/ALFRED 映射补全，不允许隐式 fallback。
- 欧盟使用已确认的 Eurostat、ECB、欧盟委员会及 World Bank 补充数据；World Bank
  只补低频结构数据，不替代及时的官方周期数据。
- `eco_cal` 是可供多个 Agent 使用的共享事件源，但每个 Agent 只能消费职责相关事件。
- 无权限的 Tushare `major_news`、`npr`、`monetary_policy`、`news` 不属于生产依赖。
- Geopolitical 使用可审计的公开官方/多源事件适配器，必须记录发布时间、抓取时间、
  来源状态、去重和覆盖；缺少及时证据时降低 readiness，不能编造价格影响。
- 所有历史运行只接受 `released_at/vintage_at <= as_of` 的数据。

## 4. 输出与消费

所有 Agent 同时产生：

1. 严格 schema 校验的结构化 payload，供下游 Agent、审计与 outcome 系统消费；
2. 从已接受结构化结果确定性渲染的人可读解释，仅供 TUI 展示，不进入下游 prompt、
   Darwinian label 或交易决策。

十个 Macro 输出保持独立，不再压缩为六因子 bundle，也不生成统一 Macro stance。下游直接
接收每个已接受输出、证据 lineage、运行可靠度及该 Agent 的独立 Darwinian usage weight。
Decision Agent 的 outcome 只评价自身决策对象，CIO 总收益不得反向污染全部上游归因。

## 5. 私有 KNOT 边界

- 私有模型可见 prompt 只保留角色、证据使用、输出和 cohort behavior；不得嵌入
  research-knob、KNOT 参数、评分或晋级规则。
- 公库只保留 `cohort_default` 的 56 份双语 fake/offline baseline prompt；其余 7 个
  cohort 只保留空目录标记，公开 renderer/generator 不保存也不能生成其 behavior。
- 私库保存 KNOT runtime、domain/governance values、完整 projection、私有合同、测试和
  mutation audit。
- 公库保存 Agent/output/tool/outcome 的公开合同，以及私有资产的相对路径、版本和 hash；
  不保存私有值或实现。
- 公库 fake/offline 路径不生成 KNOT projection，并明确 `production_eligible=false`；生产
  projection 只由私有 runtime 在边界内加载。
- KNOT 与 Darwinian 的公开关系只保留所有权边界：Darwinian 评价/usage weight 不直接改
  prompt；KNOT 不修改公开角色、工具、schema、outcome label 或组件权重。组件初始/当前
  权重属于版本化 runtime contract，只能由独立的半年度 shadow calibration 流程以前瞻
  生效、append-only 且可回滚的 release 更新，不读取或暴露私有 KNOT 内容。

## 6. 验收

- 28 Agent/29 stage roster、工具白名单、output schema、PIT/readiness 和下游 DTO 一致。
- 448 份私有双语 cohort prompt 的语言、角色/工具/schema 不变量与 cohort 差异通过检查。
- 公库 prompt 树严格为 56 份 `cohort_default` Markdown；非默认 cohort 没有模型可见正文。
- 公库扫描确认没有私有 KNOT manifest、domain catalog、evaluation contract、projection、
  参数值、实现源码或详细计划。
- 私库验证完整 KNOT runtime、28 Agent 当前 registry/projection、合同 hash 与私有测试。
- 公私 release pin 一致；私库缺失或 hash 漂移时生产失败关闭。
- TypeScript、Python、prompt leak/private boundary、fake daily-cycle 和 `git diff --check`
  全部通过；RKE 保持 shadow-only。
