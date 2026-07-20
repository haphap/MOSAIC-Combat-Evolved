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
  long 与 short-or-avoid 股票 picks、驱动、风险、claims、证据和 Macro attribution；只有
  对应冻结 shortlist 为空时，该侧才可输出 `NO_QUALIFIED_SECURITY`。
- 细分行业比较的核心技术面使用等权股票 basket；存在合法冻结 ETF family 时还必须纳入其
  PIT 走势、成交/资金与相对强弱。ETF 不可得不转换成负面票，也不得临时发明分类或用单只
  股票替代全行业。

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
  来源状态、去重和覆盖；任一必需路由/parser 或连续三十日 receipt 不完整时拒绝正式
  snapshot，不得转换为中性，也不能编造价格影响。
- 所有历史运行只接受 `released_at/vintage_at <= as_of` 的数据。

## 4. 输出与消费

所有 Agent 同时产生：

1. 严格 schema 校验的结构化 payload，供下游 Agent、审计与 outcome 系统消费；
2. 从已接受结构化结果确定性渲染的人可读解释，仅供 TUI 展示，不进入下游 prompt、
   Darwinian label 或交易决策。

十个 Macro 输出保持独立，不再压缩为六因子 bundle，也不生成统一 Macro stance。需要宏观
因果判断的 Sector、Relationship、Superinvestor、Alpha、CRO 与 CIO 消费者直接接收每个已接受
输出、证据 lineage、运行可靠度及该 Agent 的独立 Darwinian usage weight。`autonomous_execution`
是明确例外：它只消费冻结的 CIO proposal、CRO 控制、订单意图与执行证据，不得直接读取、
复述或归因 `macro_input_gate` 或十个 Macro 输出，也不得携带 Macro attribution。Decision Agent
的 outcome 只评价自身决策对象，CIO 总收益不得反向污染全部上游归因。

28 个 Agent 均必须绑定唯一的 `evaluation object → label → maturity horizon → rank scope`
合同。24 个上游 Agent 的成熟标签可进入 `DOWNSTREAM_USAGE_WEIGHT`；`cro`、
`alpha_discovery`、`autonomous_execution`、`cio` 四个 L4 角色只进行同角色
`EVOLUTION_ONLY` 排名。机会集成员必须匹配该 Agent 的冻结 evaluation-object 域；成熟时间
必须匹配权威 schedule slot。

日初 schedule 只规划 slot、maturity 和 readiness，不提前冻结依赖尚未产生的动态对象。L1/L2
在运行前由服务端重新物化角色工具快照，并逐字段、逐顺序比对 Macro event/path、Sector
shortlist/ticker 和 Relationship edge/materiality；EVENT_TRIGGERED Macro 必须绑定该 slot
已经验证的唯一 trigger event。四个 Superinvestor 在各自模型调用前，四个 Decision 角色在
各自 stage 调用前，分别由服务端现场物化候选/风险/订单/组合快照并冻结 exact domain；客户端
不能提交 member、伪造空集或替换 candidate。权威空集只对合同允许的角色形成 stage-skip，
否则失败关闭。冻结对象 ID/hash、source snapshot、candidate scope/universe 及 upstream accepted
refs hash 必须贯穿 capability、模型工具结果、accepted output 和 outcome maturation，任一缺失或
漂移均不得进入正式评分。服务端另在 append-only authority-event ledger 中记录机主时间和
自增 sequence，必须满足 opportunity freeze sequence 早于 accepted-output persistence sequence；
幂等重试不得改写首次 freeze 事件，墙钟时间不进入确定性 opportunity ID/hash。

私有 projection 只允许引用公库按 sample 唯一选择的 sealed
source batch ID/hash；realized metrics 不得由 projection 携带。公库使用当前服务端配置的
26-source authority registry 验证新 batch，并在同一写事务中封存不可变的 registry
snapshot；历史 batch 只按自身固定的 registry hash 从 append-only 历史中解析，不与当前 key
或 registry 比较。公库重验每份 domain-separated Ed25519 detached signature，并按照 source 对
realized schema 顶层字段的唯一 ownership 组装结果。只有 exact-source batch、receipt/batch
schema、registry/entry hash、SQLite 镜像列及完整 PIT 顺序均通过，才依次物化 observation、
eligibility 和 label；缺数据时保持未成熟或显式拒绝，不得伪造标签或回退到 CIO 总收益。

公库不包含真实市场 realization producer 或任何 signing private key。默认公开 registry 标记为
`PROVISIONING_REQUIRED`，其 fail-closed enrollment placeholder 无对应私钥；部署前必须由各
source owner 在外部安全系统生成私钥、只向公库登记公钥并发布新的 registry hash。正式
append/read API 不接受 caller 指定的 registry 或 schema 路径；签名 key 窗口只按服务端
`ingested_at` 判定，不采信 signer 可回填的时间。测试只在
临时目录生成不可落盘的临时 keypair/ACTIVE registry。`ingested_at`、`sealed_at` 只取公库
server clock，producer/RPC 不得回填；batch append 必须自行取得 `BEGIN IMMEDIATE` 写锁后
重读当前 PENDING revision，再依次取 ingest/seal 时间，已有 caller transaction 一律拒绝。
这些 SQLite mirror/hash/append-only trigger 的威胁模型是拒绝非特权应用写入者的漂移，
不声称能对抗可删除 trigger 并重写整库的特权 DB 管理员；若部署威胁模型包含后者，
还必须将 server-signed seal 发布到数据库外的 append-only audit ledger。
私有 runtime 从 public Scorecard 读取不可变 schedule、
accepted-output context，向已登记 source adapter 获取 source-specific observation 与 evidence
artifact hash，提交签名 attestation；预测、置信度、loss、utility 与 normalization 仍全部由公库
使用封存 accepted output、冻结机会集和 verified realized-only observation 确定性派生。在
producer/worker 未部署、projection 文件缺失、sealed batch 未完成或任一 pin/lineage 不一致时，样本保持
`PENDING_INPUT_UNAVAILABLE`，正式 Darwinian publish 必须失败关闭；数据不可得或覆盖不健康
也不得伪装成 `ABSTAIN`。

Normalization 必须来自独立、版本化、append-only 的公库 PIT registry：冷启动 release 明确
注册为 unit scale，后续校准 release 只能使用其 `effective_at` 之前的成熟样本并前瞻生效。
每个 label 固定 registry、schema、entry hash、release effective time 与本次 opportunity cutoff；
不得接受 projection、caller 或当前批次即时提供的 scale，也不得在首个 release 前 fallback。

## 5. 私有 KNOT 边界

- 私有模型可见 prompt 只保留角色、证据使用、输出和 cohort behavior；不得嵌入
  research-knob、KNOT 参数、评分或晋级规则。
- 公库只保留 `cohort_default` 的 56 份双语 fake/offline baseline prompt；其余 7 个
  cohort 只保留空目录标记，公开 renderer/generator 不保存也不能生成其 behavior。
- 私库保存 KNOT runtime、domain/governance values、完整 KNOT 演化 projection、只含
  sealed batch 引用的最小 realized-outcome projection、私有合同、测试和 mutation audit。
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
- 28 Agent outcome 合同、权威 maturity schedule、机会成员域、确定性 label producer、24 条
  usage-weight track 与 4 条 L4 evolution-only track 端到端一致。
- 私有 realization producer/worker 覆盖八类 realized-only schema；collector 只生成逐 source
  observation/evidence hash，独立外部 signer 只签署 registry 构造的 attestation，公库在可写
  Scorecard transaction 中验证并原子封存 exact batch。私有 projection 只写 server 返回的
  batch ID/hash 与公开合同 pin；公库只从 accepted output、冻结机会域和 verified observation
  派生评分输入，缺少 producer、signer、ACTIVE enrollment 或 sealed batch 时发布保持阻断。
- 448 份私有双语 cohort prompt 的语言、角色/工具/schema 不变量与 cohort 差异通过检查。
- 公库 prompt 树严格为 56 份 `cohort_default` Markdown；非默认 cohort 没有模型可见正文。
- 公库扫描确认没有私有 KNOT manifest、domain catalog、evaluation contract、projection、
  参数值、实现源码或详细计划。
- 私库验证完整 KNOT runtime、28 Agent 当前 registry/projection、合同 hash 与私有测试。
- 公私 release pin 一致；私库缺失或 hash 漂移时生产失败关闭。
- 所有跨 Python/TypeScript 的 authority ID/hash 使用同一版本化 RFC 8785/JCS
  canonical JSON 合同，共享 golden corpus 覆盖指数边界、`-0` 和 UTF-16 key 排序。
- TypeScript、Python、prompt leak/private boundary、fake daily-cycle 和 `git diff --check`
  全部通过；RKE 保持 shadow-only。
