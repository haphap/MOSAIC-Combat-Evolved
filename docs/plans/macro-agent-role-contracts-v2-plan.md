# Macro Agent 中国视角职责、共享事件与直接下游消费重构计划

日期：2026-07-16

状态：待实施

## 1. 目标与不变量

本计划统一此前关于 Macro Agent 职责、欧盟数据、Tushare
`eco_cal`、行业拆分（农业、非半导体科技、地产建筑和工业材料）、prompt 和
Darwinian 可靠度的设计。

目标：

1. 所有宏观结论采用中国投资者和 A 股传导视角。
2. 将美国拆分为“实体经济周期”和“外部金融条件”，将欧盟实体经济与欧元区
   金融条件分开，避免 Fed、美元、收益率曲线和经济周期重复投票。
3. 将 Tushare `eco_cal` 建成跨层共享事件基础设施，而不是某个 Agent
   私有的数据工具。
4. 欧盟使用已确认的官方数据源，并明确历史 vintage 的能力边界。
5. World Bank 只补跨国可比和结构性背景，不作为核心数据缺失时的隐式
   fallback。
6. 保持结构化 accepted output、Darwinian 可靠度、证据可追溯、PIT 可审计和
   缺失数据失败关闭；不再生成六因子或 Macro stance。
7. 将 `geopolitical` 从临时新闻检索改为有覆盖范围、来源健康、事件生命周期和
   publication-to-capture 时效审计的持续事件管线。
8. 为全部 28 个 Agent 冻结零参数角色快照、数据来源和 required failure semantics，
   由 bridge 服务端 capability 强制权限，不依赖 prompt 自律。
9. Sector、Superinvestor 和 Decision 使用冻结候选域及专属 PIT 数据；每个标准 Sector
   输出一个 preferred、至多一个由确定性 eligibility audit 决定的 least-preferred、受约束股票 picks、驱动/风险、
   claims/evidence 和 Macro attribution，并用同构成分股技术卡及可得的细分行业 ETF 价格/
   份额/估算申赎半票确认完成全 pair 对比；事件覆盖缺失的 criterion 不投票，不生成多行业总分；RKE/report context 与 production
   交易图物理隔离。
10. 将 Darwinian 拆成覆盖全部 28 个 Agent 的评价/演化轨和仅覆盖 24 个上游信息源的
    下游使用权重轨；该 28/24 基数按每个 active production cohort/language variant 独立
    建立。四个 Decision Agent 只作 `EVOLUTION_ONLY`，不得用连续权重改变权限、
    硬约束、订单或最终组合。
11. 所有正式/KNOT accepted payload 统一由 namespace-safe accepted record 持久化，graph
    state 只保存 ID/hash，operational/outcome/组件校准按同一 record 精确连接；fake/offline
    smoke 禁止写入任何正式样本或评分 store。

必须保持：

- 10 个 Macro Agent。
- 10 个 Sector Agent。
- 4 个 Superinvestor Agent。
- 4 个 Decision Agent。
- 共 28 个逻辑 Agent、29 个执行阶段；CIO proposal/final 仍为两个阶段。
- RKE 继续 shadow-only，不影响生产交易决策。
- 128K context、GPU utilization `0.85`、空闲显存门槛 `256 MiB` 原样
  保留。
- 不运行 100 日测试。

## 2. 目标 Agent 拓扑

### 2.1 Macro Agent

| Agent | 唯一职责 | 明确禁止 |
| --- | --- | --- |
| `china` | 中国增长、价格、信用、外需和财政脉冲及其 A 股传导 | 地产不得成为必选维度；不判断 PBOC 方向 |
| `us_economy` | 美国增长、就业、通胀和需求周期对中国出口、盈利及风险偏好的外部传导 | 不判断 Fed、美元、收益率曲线或信用条件 |
| `eu_economy` | 欧盟增长、就业、价格、消费、生产与外需周期对 A 股的传导 | 不判断 ECB、汇率、曲线或金融压力；不将英国、瑞士、挪威纳入欧盟主体 |
| `central_bank` | PBOC 反应函数、政策倾向、流动性，以及中国货币市场、名义曲线和信用条件 | 不判断 Fed、ECB 或其他海外央行；不重复中国经济周期；不读取其他 Macro LLM 输出；无注册数据时不得声称中国实际曲线 |
| `us_financial_conditions` | Fed、美国名义/实际曲线、货币市场、信用利差、美元/人民币、美国金融压力和波动率对 A 股的统一外部冲击 | 不再投一张美国经济周期票；不得把美元、Fed、曲线拆成多票 |
| `euro_area_financial_conditions` | ECB、欧元区利率曲线、信用/货币、欧元和金融压力对 A 股的统一外部冲击 | 不重复欧盟实体周期；不把非欧元区成员的央行或市场纳入主体；不分析英国、瑞士、挪威 |
| `commodities` | 能源期限结构/库存、工业金属、黄金、农产品和输入性通胀冲击 | 无真实期限结构时不得声称 contango/backwardation |
| `geopolitical` | 事件状态、传导渠道、严重度、期限和观察触发器 | 不虚构价格影响百分比；财经日历不能替代事件状态证据 |
| `market_breadth` | A 股参与度、趋势广度、成交广度、新高新低和集中度 | 不读取新闻、财经日历、资金流或波动率后重复判断 |
| `institutional_flow` | 全市场资金、行业轮动、ETF 份额和拥挤度 | 不读取财经日历；龙虎榜仅作辅助，不以抽样个股代表市场 |

ID 迁移：

- `us_financial_conditions`、`eu_economy` 和
  `euro_area_financial_conditions` 是全新的稳定 Agent ID 和行为轨道，不是旧 ID 的
  rename/alias，也不得继承旧样本、Darwinian weight 或 prompt 先验。
- `dollar`、`yield_curve`、`volatility`、`emerging_markets` 和
  `news_sentiment` 全部 tombstone；旧输出仅供审计，统一标记
  `legacy_unverified`。
- 旧数据字段按所有权重新路由而不迁移 Agent 身份：中国曲线进入 `central_bank`；
  Fed、美国曲线、美元/人民币和美国隐含波动进入 `us_financial_conditions`；欧元区
  金融压力进入 `euro_area_financial_conditions`；中国实现波动只进入 CRO 风险状态。
- migration manifest 必须分别记录 `tombstoned_agent_ids`、`new_agent_ids` 和
  `data_field_routes`；禁止出现 `yield_curve -> euro_area_financial_conditions` 或
  `volatility -> eu_economy` 这类错误的身份映射。

### 2.2 Sector Agent

目标 Sector roster：

1. `semiconductor`
2. `technology`
3. `energy`
4. `biotech`
5. `consumer`
6. `industrials`
7. `real_estate_construction`
8. `financials`
9. `agriculture`
10. `relationship_mapper`

其中九个标准 Sector 的边界固定如下：

- `semiconductor` 只负责申万电子中的半导体二级行业，不覆盖其他电子、计算机或通信。
- `technology` 负责剔除半导体后的电子，以及计算机、通信和传媒；不得把
  `semiconductor` 重新纳入，也不得以海外科技股表现代替 A 股行业分析。
- `energy` 负责煤炭、石油石化、电力，以及光伏、风电、电池/储能等新能源产业链；
  新能源汽车整车仍属于 `consumer`，基础化工、钢铁和有色金属仍属于 `industrials`。
- `biotech` 负责医药生物。
- `consumer` 负责家电、食品饮料、纺织服饰、轻工制造、商贸零售、社会服务、
  美容护理和汽车；汽车明确按耐用消费品处理，不再进入 `industrials`。
- `industrials` 负责基础化工、钢铁/黑色金属、有色金属、机械设备、国防军工、
  电机/其他电源/电网设备、交通运输和环保；光伏、风电和电池不得重复纳入。
  商品价格只能作为投入/产出传导证据，不重复
  `commodities` 的宏观冲击结论。
- `real_estate_construction` 负责房地产、建筑材料、建筑装饰及其产业链传导；不得让
  地产重新成为 `china` 的必选维度，也不得判断 PBOC 方向。
- `financials` 负责银行和非银金融。
- `agriculture` 负责农林牧渔及农业产业链。

九个标准 Sector 不是把所辖行业逐项输出一遍，也不生成一个会把相反观点抵消掉的总行业
分数。每次运行先完成冻结方向的研究：多方向走全 pair comparison，单方向走注册 null
qualification；若 runtime reducer/qualification 形成唯一合格 winner，
最终 selection 必须在 `SectorDirectionContract` 中提交且只提交一个当前最看好的
`preferred_direction`，并按最终 pair matrix 的确定性 eligibility audit 提交至多一个相对
最不看好的 `least_preferred_direction`；例如中东供应冲击下，`energy` 必须在煤炭、
石油石化、电力和新能源方向间比较，可能选择 `oil_gas` 或 `coal`，而不是把全部能源
子行业一起输出。least-preferred 表示
相对低配/回避，不自动等于绝对下跌或可做空；audit 判定不合格或不适用时必须使用
`NO_QUALIFIED_AVOID_DIRECTION`。只有连 preferred 也不成立时才允许
`NO_QUALIFIED_DIRECTION`。两者仍是一份 Sector selection、共享一个 Darwin weight，不能
拆成两张行业票；其余方向只能作为比较证据出现在 claims 中。

`agriculture` 负责种植、种业、养殖、饲料、渔业、农业服务、粮食安全、
天气疫病、库存价格和投入成本。它必须：

- 将商品或宏观事件解释为农业行业、产业链和公司层面的传导。
- 不重复 `commodities` 的宏观冲击票。
- 不把单一农产品价格外推为整个农业行业。
- 不虚构产量、库存、天气损失或证券代码。

Sector ID/合同迁移规则：`technology`、`real_estate_construction` 和 `agriculture` 是新的
稳定 Agent ID，不是 `semiconductor`、`industrials` 或其他旧角色的 alias。九个标准 Sector
因统一改为“一个最佳方向 +
一个可弃权的最不看好方向”selection/output/outcome 合同，全部发布新的 agent、prompt、execution、outcome 和 scoring
contract version；`relationship_mapper` 也因证券域/输入 scope 变化发布新版本。上述十条
Sector-layer 新轨道均不得继承旧 outcome、Darwinian weight 或 KNOT paired sample。

### 2.3 Superinvestor Agent

四个 Superinvestor 都只能在冻结的 Layer-2 accepted 候选域中做选择，不得自行搜索、
引入域外证券或把个人风格变成固定多空先验：

| Agent | 唯一职责 | 明确禁止 |
| --- | --- | --- |
| `druckenmiller` | 结合宏观流动性、趋势、催化和风险收益不对称选择顺势候选 | 不把单一宏观观点机械映射为个股；不越过冻结候选域 |
| `munger` | 评估商业质量、护城河、资本配置、估值与长期复利条件 | 不以“好公司”替代价格纪律、证据或可交易性检查 |
| `burry` | 寻找市场预期错配、反身性、资产负债表风险和非对称反转机会 | 不因逆向风格而默认反对共识；不虚构隐蔽风险或做空可行性 |
| `ackman` | 选择少数高质量、可解释且有明确催化/治理改善路径的集中候选 | 不假设未公开的激进治理行动；不把集中度偏好变成跳过风险约束 |

四个角色输出各自独立的 selection 和 Darwinian 轨道，但共享同一冻结候选域、PIT
证据边界和 21 交易日成熟合同；风格差异只能影响研究顺序和证据权衡，不能改变
schema、工具、候选域或 outcome label。冻结候选域为空时四个角色各自生成确定性
stage-skip，不调用模型、不生成 accepted output 或 Darwinian 样本；非空域上的主动弃权
才是可评价的 `NO_QUALIFIED_CANDIDATES`。

### 2.4 Decision Agent

| Agent | 唯一职责 | 明确禁止 |
| --- | --- | --- |
| `cro` | 对 CIO proposal 冻结的完整 pre-CRO 目标组合逐一给出风险动作、上限、复核要求和组合级硬风险约束 | 不生成 alpha 排名，不因 Darwinian/KNOT 表现放松硬约束 |
| `alpha_discovery` | 在冻结 novel universe 中寻找 Layer-3 尚未选中的增量候选或明确弃权，供 CIO proposal 纳入后统一接受 CRO 审查 | 不重排既有候选，不引入域外证券，不读取尚未发生的同轮 CRO 结果或绕过后续 CRO |
| `autonomous_execution` | 评估已批准 order intent 的可执行性、成本、切片和时点 | 不形成投资 thesis，不读取 Macro 方向，不把 paper planning 冒充真实成交 |
| `cio` | 在 proposal/final 两阶段整合全部 required 上游 slot（accepted output 或获准 Superinvestor stage skip）、CRO 和 Execution 控制，形成唯一正式目标组合 | 不省略控制 resolution，不把 proposal 重复计分，不把最终 PnL 反向归因给全部上游 |

四个 Decision Agent 都进入 `EVOLUTION_ONLY` evaluation/KNOT 体系，但不生成下游 usage
weight；CIO proposal/final 是同一逻辑 Agent 的两个执行阶段，因此总数仍为 28 个逻辑
Agent、29 个执行阶段。CRO/Alpha/Execution 因冻结对象为空而 deterministic skip 时仍保留
该阶段的 stage-skip 审计，但不调用模型、不生成 accepted output 或 Darwinian 样本。
五个 Decision 执行阶段的唯一顺序固定为：
`alpha_discovery -> cio(PROPOSAL) -> cro -> autonomous_execution -> cio(FINAL)`。
Alpha 可读取冻结上游、novel universe 及市场/财务/催化快照，但风险控制输入只允许
生效中的静态风险/资格约束，不能读取同轮 CRO；CIO proposal 必须显式绑定 Alpha
accepted/skip 来源并把采纳的 Alpha 候选纳入完整目标组合；CRO 随后审查该完整 proposal，Execution
只评估经 CRO 约束后的冻结订单意图，CIO final 最后解析 CRO/Execution 控制。任何并行、
倒序或让 Alpha 新候选在 CRO 后直接进入 final 的图都属于合同失败。

## 3. 输出合同

模型提交和运行时接受结果使用两个不同合同。模型可以为 `DIRECT` 路径提交信号级
`confidence`，但不能直接生成组件合成后的 accepted confidence、runtime lineage、
`evidence_bundle_ids` 或 `causal_dedupe_keys`：

```ts
type MacroAgentId =
  | "china"
  | "us_economy"
  | "eu_economy"
  | "central_bank"
  | "us_financial_conditions"
  | "euro_area_financial_conditions"
  | "commodities"
  | "geopolitical"
  | "market_breadth"
  | "institutional_flow";

type ComponentMacroAgentId = Exclude<
  MacroAgentId,
  "geopolitical" | "market_breadth" | "institutional_flow"
>;

interface DirectMacroSignal {
  direction: "SUPPORTIVE" | "NEUTRAL" | "ADVERSE";
  strength: 0 | 1 | 2 | 3 | 4 | 5;
  persistence_horizon: "DAYS" | "WEEKS" | "MONTHS";
  evaluation_horizon_trading_days: 5;
  confidence: number;
  channels: string[];
  claim_refs: string[];
}

type MacroAgentSubmission =
  | {
      mode: "DIRECT";
      claims: Claim[];
      key_drivers: string[];
      signal: DirectMacroSignal;
    }
  | {
      mode: "COMPONENTS";
      claims: Claim[];
      key_drivers: string[];
      components: MacroComponentSignal[];
    };

interface AcceptedMacroTransmission {
  agent_id: MacroAgentId;
  agent_contract_version: string;
  prompt_behavior_version: string;
  execution_behavior_version: string;
  component_weight_contract_version: string | null;
  direction: "SUPPORTIVE" | "NEUTRAL" | "ADVERSE";
  strength: 0 | 1 | 2 | 3 | 4 | 5;
  persistence_horizon: "DAYS" | "WEEKS" | "MONTHS";
  evaluation_horizon_trading_days: 5;
  model_confidence: number;
  deterministic_data_quality: number;
  confidence: number;
  channels: string[];
  claims: Claim[];
  claim_refs: string[];
  key_drivers: string[];
}

interface ModelVisibleAcceptedMacroTransmission {
  direction: "SUPPORTIVE" | "NEUTRAL" | "ADVERSE";
  strength: 0 | 1 | 2 | 3 | 4 | 5;
  persistence_horizon: "DAYS" | "WEEKS" | "MONTHS";
  evaluation_horizon_trading_days: 5;
  confidence: number;
  channels: string[];
  claims: Claim[];
  claim_refs: string[];
  key_drivers: string[];
}
```

唯一 `Claim` 合同由 TypeScript Zod 定义，不再只在 prose 中约定：

```ts
const ClaimSchemaV2 = z
  .object({
    claim_id: z.string().trim().min(1),
    claim_kind: z.enum(["FACT", "EVENT", "INTERPRETATION", "RISK_FLAG"]),
    statement: z.string().trim().min(1),
    structured_conclusion: z
      .record(z.string().min(1), z.unknown())
      .refine((value) => Object.keys(value).length > 0, {
        message: "structured_conclusion must not be empty",
      }),
    evidence_ids: z.array(z.string().trim().min(1)).min(1),
    research_rule_refs: z.array(z.string().trim().min(1)),
  })
  .strict()
  .superRefine((claim, ctx) => {
    if (
      claim.claim_kind === "INTERPRETATION" &&
      claim.research_rule_refs.length === 0
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["research_rule_refs"],
        message: "INTERPRETATION requires an allowed research rule",
      });
    }
  });

type Claim = z.infer<typeof ClaimSchemaV2>;
```

运行时把 claim 绑定到 accepted output 的 `run_id/snapshot_hash` 和证据目录，不允许模型
提交这些 lineage 字段。FACT/EVENT 的数值、时间和状态必须与快照逐字段一致；
RISK_FLAG 必须引用快照中的确定性 trigger；无法验证的内容只能是 INTERPRETATION，
不能伪装成不降权事实。`research_rule_refs` 只能引用 runtime 提供的闭集；FACT、EVENT
和 RISK_FLAG 可以为空，INTERPRETATION 必须非空。

现有 `mosaic-ts/src/agents/evidence_contract.ts` 的
`ResearchClaimSchema(claim_type/evidence_refs/structured_conclusion)` 必须原地迁移为
`ClaimSchemaV2`，不得并存第二套生产 Claim。迁移映射固定为：

- `evidence_refs -> evidence_ids`，`research_rule_refs/statement/structured_conclusion`
  原样保留；
- 旧 `fact` 只有在确定性观测校验后映射为 `FACT` 或 `EVENT`，不得仅凭字符串猜测；
- 旧 `inference -> INTERPRETATION`；
- 旧 `uncertainty` 只有存在确定性 trigger 时映射为 `RISK_FLAG`，否则映射为
  `INTERPRETATION` 的前提是旧记录已携带可解析到允许闭集的 research rule；缺少该信息时
  只能保留为 `legacy_unverified`，不得由迁移器补造 evidence 或 research rule；
- 旧 `snapshot_hash` 迁移到 runtime-owned accepted-output/claim-graph envelope，不再是
  LLM claim 字段。

旧 schema 的历史产物只读并标记 `legacy_unverified`；cutover 后任何
`claim_type/evidence_refs` 输入均 schema reject，不能静默双读或按 cohort 选择合同。

约束：

- `NEUTRAL` 必须对应 `strength=0`。
- 非中性 `strength` 必须为 1–5。
- `confidence` 必须在 `[0, 1]`；DIRECT signal、每个 component 和 accepted
  transmission 的 `channels/claim_refs` 均不得为空。
- submission 必须包含非空 `claims/key_drivers`；DIRECT 的结论级 refs 固定为
  `signal.claim_refs`，COMPONENTS 的每个组件各自提交非空 `claim_refs`，accepted
  transmission 的结论级 `claim_refs` 由 runtime 对全部有效组件 refs 去重合并。
  DIRECT submission 还必须包含 `signal.confidence`。
- 数值、事件、政策状态和 surprise 必须引用 snapshot 中已有的
  `evidence_id`。
- 模型只解释传导，不自行计算、抓取或补造数据。
- 运行时从 accepted payload 中已验证的 `claim_refs` 解析并去重 lineage，再包裹
  `EvidenceLineageEnvelope`；模型回显 lineage 字段时拒绝。
- `china`、`us_economy`、`eu_economy`、`central_bank`、
  `us_financial_conditions`、`euro_area_financial_conditions` 和
  `commodities` 必须使用 `mode=COMPONENTS`；其余 Macro Agent 必须使用
  `mode=DIRECT`。
- DIRECT 的 `model_confidence` 是通过语义校验后的 `signal.confidence`；运行时按
  `DirectAgentDataQualityContract` 计算 `deterministic_data_quality`，并令 accepted
  `confidence=model_confidence*deterministic_data_quality`。COMPONENTS 的三个字段均由
  下述确定性 composer 生成，模型不能回显或覆盖 accepted 字段。
- `mode=DIRECT` 的 accepted `component_weight_contract_version` 必须为 `null`；
  `mode=COMPONENTS` 必须为非空且与 composer 实际使用的版本完全一致。submission mode、
  Agent 固定 mode 与 accepted version 三者不一致时拒绝。
- COMPONENTS submission 必须与本节权重表中的组件集合完全相等，每个组件恰好
  一次；缺失、重复或额外组件均拒绝。

多地区或多组件 Agent 额外输出诊断组件：

```ts
interface MacroComponentSignal {
  component: string;
  direction: "SUPPORTIVE" | "NEUTRAL" | "ADVERSE";
  strength: 0 | 1 | 2 | 3 | 4 | 5;
  persistence_horizon: "DAYS" | "WEEKS" | "MONTHS";
  evaluation_horizon_trading_days: 5;
  confidence: number;
  channels: string[];
  claim_refs: string[];
}
```

组件只在 Agent 内部合成一次。组件不形成独立下游输入、不拥有独立 Darwinian
权重，也不因为一个 Agent 包含多个组件而增加信息份额。模型输出组件和证据，
运行时按以下规则生成并校验最终 transmission：

```text
x_j = component_direction_sign * component_strength / 5
q_j = component_confidence_j * deterministic_data_quality_j
b_j = preregistered_component_weight_j * q_j
F   = sum(b_j * x_j) / sum(b_j)

if abs(F) < 0.1:
    direction = NEUTRAL
    strength = 0
else:
    direction = SUPPORTIVE if F > 0 else ADVERSE
    strength = clamp(floor(5 * abs(F) + 0.5), 1, 5)

base_confidence = sum(preregistered_component_weight_j * q_j)
dispersion = sum(b_j * abs(x_j - F)) / sum(b_j)
confidence = clamp(base_confidence * (1 - dispersion), 0, 1)

model_b_j = preregistered_component_weight_j * component_confidence_j
model_F = sum(model_b_j * x_j) / sum(model_b_j)
model_dispersion = sum(model_b_j * abs(x_j - model_F)) / sum(model_b_j)
model_confidence = clamp(
    sum(preregistered_component_weight_j * component_confidence_j)
    * (1 - model_dispersion),
    0,
    1,
)
deterministic_data_quality = sum(
    preregistered_component_weight_j * deterministic_data_quality_j
)
```

`sum(b_j)=0` 或 `sum(model_b_j)=0` 时该 Agent 拒绝。top-level
`model_confidence/deterministic_data_quality` 只用于分别审计模型判断与数据质量；组件路径的
effective `confidence` 必须使用含 dispersion 的正式 composer，不能把两个 top-level 诊断值
再次相乘。最终 `persistence_horizon` 取按 `b_j` 加权的众数；并列时
选择更短期限。最终 channels 和 claim refs 是所有有效组件的去重并集。组件权重
必须版本化、总和为 1、跨 cohort 不变：

| Agent | 组件及权重 |
| --- | --- |
| `china` | 增长/生产、价格、信用、外需/贸易、财政各 0.20 |
| `us_economy` | 增长/生产、价格、就业、需求/贸易各 0.25 |
| `eu_economy` | 增长/生产、价格、就业、需求/贸易各 0.25 |
| `central_bank` | PBOC 政策倾向、流动性/货币市场、中国曲线、信用条件各 0.25 |
| `us_financial_conditions` | Fed/流动性、美国曲线、信用/金融压力、美元/人民币各 0.25 |
| `euro_area_financial_conditions` | ECB/流动性、欧元区曲线、银行信用、欧元/金融压力各 0.25 |
| `commodities` | 能源、工业金属、黄金、农产品/食品各 0.25 |

`evaluation_horizon_trading_days=5` 是所有 Macro Agent 的固定预测与评分窗口：
从 `as_of` 后首个 A 股可交易开盘到第 5 个 A 股交易日收盘。`direction`、
`strength`、`confidence` 和 Darwinian label 都只对应这个窗口。
`persistence_horizon` 只描述冲击预计持续多久，供下游设置观察触发器，不改变
track、label 或样本成熟时间。runtime 拒绝缺少固定 literal、把持续期当成评分期，
或试图用 `MONTHS` 规避五日成熟标签的输出。

每个组件拥有版本化的 `ComponentDataQualityContract`，三个 DIRECT Macro 各自拥有唯一
`DirectAgentDataQualityContract`。两类合同都为每个输入预注册
`series_id`、输入权重、required 状态、PIT/freshness/parse/reconciliation
要求和公式版本；同一组件或 DIRECT Agent 合同内输入权重总和必须为 1：

```ts
interface ComponentDataQualityContract {
  contract_version: string;
  agent_id: ComponentMacroAgentId;
  component: string;
  inputs: Array<{
    series_id: string;
    input_weight: number;
    required: boolean;
    required_fields: string[];
    freshness_contract_version: string;
    reconciliation_required: boolean;
  }>;
}

interface DirectAgentDataQualityContract {
  contract_version: string;
  agent_id: "geopolitical" | "market_breadth" | "institutional_flow";
  inputs: ComponentDataQualityContract["inputs"];
  aggregation: "WEIGHTED_ELIGIBILITY_SUM";
}
```

```text
eligible_k = 1 only if:
  PIT valid
  and fresh under the series freshness contract
  and all fields required by the input contract parsed or deterministically validated
  and conflict_status != CONFLICT
  and (reconciliation not required or reconciliation accepted)
otherwise eligible_k = 0

deterministic_data_quality_j = sum(input_weight_k * eligible_k)
```

`deterministic_data_quality_j` 必须在 `[0, 1]`。任一 required 输入的
`eligible_k=0` 时整个 Agent 阶段拒绝；optional 输入不触发拒绝，但按其权重降低
数据质量。允许的 reconciliation 状态只有 `EXACT`、`WITHIN_TOLERANCE` 和
`EXPECTED_REVISION`；预注册为单一权威来源且 `reconciliation_required=false`
的输入不因缺少第二来源而失败。质量计算只使用确定性快照元数据，模型不得输出
或覆盖结果；合同版本必须进入运行审计，并用共享 fixture 验证 TS/Python 一致。
三个 DIRECT Macro 使用完全相同的 eligibility 规则在整份快照上计算一个
`deterministic_data_quality`；required 分支失败仍拒绝，optional 分支不可用按预注册权重
降质。accepted `confidence`、第 9 节 usage share 和第 10 节 forecast loss 只使用这个
effective confidence，`model_confidence` 仅供审计与校准诊断。

九个标准 Sector 统一使用“一个 preferred + 一个可弃权 least-preferred”选择合同：

```ts
interface SectorSecurityPickSubmission {
  pick_local_id: string;
  ts_code: string;
  direction_local_id: string;
  position_action: "LONG" | "SHORT" | "AVOID";
  conviction: number;
  thesis: string;
  claim_refs: string[];
}

interface SectorDriverSubmission {
  driver_local_id: string;
  summary: string;
  claim_refs: string[];
}

interface SectorRiskSubmission {
  risk_local_id: string;
  summary: string;
  claim_refs: string[];
}

interface PreferredSectorDirectionSubmission {
  selection_role: "PREFERRED";
  direction_local_id: string;
  direction_id: string;
  allocation_action: "OVERWEIGHT";
  strength: 1 | 2 | 3 | 4 | 5;
  thesis: string;
  claim_refs: string[];
}

interface LeastPreferredSectorDirectionSubmission {
  selection_role: "LEAST_PREFERRED";
  direction_local_id: string;
  direction_id: string;
  allocation_action: "UNDERWEIGHT";
  strength: 1 | 2 | 3 | 4 | 5;
  thesis: string;
  claim_refs: string[];
}

interface NoQualifiedAvoidDirectionSubmission {
  status: "NO_QUALIFIED_AVOID_DIRECTION";
  reason:
    | "SINGLE_ELIGIBLE_DIRECTION"
    | "PREFERRED_NOT_QUALIFIED"
    | "NO_UNIQUE_CONDORCET_LOSER"
    | "NO_VERIFIABLE_NON_ETF_DECISIVE_EVIDENCE";
}

type OptionalLeastPreferredDirection =
  | LeastPreferredSectorDirectionSubmission
  | NoQualifiedAvoidDirectionSubmission;

type SectorAgentSubmission =
  | {
      selection_status: "SELECTED";
      preferred_direction: PreferredSectorDirectionSubmission;
      least_preferred_direction: OptionalLeastPreferredDirection;
      persistence_horizon: "DAYS" | "WEEKS" | "MONTHS";
      confidence: number;
      key_drivers: SectorDriverSubmission[];
      risks: SectorRiskSubmission[];
      claims: Claim[];
      claim_refs: string[];
      preferred_security_status: "PICKS_PRESENT" | "NO_QUALIFIED_SECURITY";
      preferred_security_abstention_confidence: number | null;
      long_picks: SectorSecurityPickSubmission[];
      least_preferred_security_status:
        | "PICKS_PRESENT"
        | "NO_QUALIFIED_SECURITY"
        | "NOT_APPLICABLE";
      least_preferred_security_abstention_confidence: number | null;
      short_or_avoid_picks: SectorSecurityPickSubmission[];
      macro_input_attributions: MacroInputAttributionSubmission[];
    }
  | {
      selection_status: "NO_QUALIFIED_DIRECTION";
      preferred_direction: { status: "NO_QUALIFIED_DIRECTION" };
      least_preferred_direction: NoQualifiedAvoidDirectionSubmission;
      persistence_horizon: "DAYS" | "WEEKS" | "MONTHS";
      confidence: number;
      key_drivers: SectorDriverSubmission[];
      risks: SectorRiskSubmission[];
      claims: Claim[];
      claim_refs: string[];
      preferred_security_status: "NO_QUALIFIED_SECURITY";
      preferred_security_abstention_confidence: null;
      long_picks: [];
      least_preferred_security_status: "NOT_APPLICABLE";
      least_preferred_security_abstention_confidence: null;
      short_or_avoid_picks: [];
      macro_input_attributions: MacroInputAttributionSubmission[];
    };

type CoreSectorComparisonCriterion =
  | "FUNDAMENTALS"
  | "VALUATION"
  | "BASKET_TECHNICALS"
  | "RISK_ASYMMETRY";

type CoverageGatedSectorComparisonCriterion =
  | "MACRO_EVENT_FIT"
  | "CATALYSTS";

type VotingSectorComparisonCriterion =
  | CoreSectorComparisonCriterion
  | CoverageGatedSectorComparisonCriterion;

type OptionalEtfSectorComparisonCriterion =
  | "ETF_PRICE_CONFIRMATION"
  | "ETF_SHARE_FLOW_CONFIRMATION";

type SectorComparisonCriterion =
  | VotingSectorComparisonCriterion
  | OptionalEtfSectorComparisonCriterion;

type ComparableSectorCriterionVerdict =
  | "FAVORS_A"
  | "FAVORS_B"
  | "NEUTRAL";

type CoreDirectionCriterionResultSubmission = {
  criterion: CoreSectorComparisonCriterion;
  comparison_status: "COMPARABLE";
  verdict: ComparableSectorCriterionVerdict;
  claim_refs: string[];
};

type MacroEventFitCriterionResultSubmission =
  | {
      criterion: "MACRO_EVENT_FIT";
      coverage_state: "AVAILABLE_MATERIAL_EVENTS";
      comparison_status: "COMPARABLE";
      verdict: ComparableSectorCriterionVerdict;
      claim_refs: string[];
      coverage_evidence_ids: string[];
    }
  | {
      criterion: "MACRO_EVENT_FIT";
      coverage_state: "COVERAGE_CONFIRMED_NO_MATERIAL_EVENT";
      comparison_status: "COMPARABLE";
      verdict: "NEUTRAL";
      claim_refs: string[];
      coverage_evidence_ids: string[];
    }
  | {
      criterion: "MACRO_EVENT_FIT";
      coverage_state: "SOURCE_UNAVAILABLE";
      comparison_status: "UNAVAILABLE";
      verdict: "NO_VOTE";
      claim_refs: [];
      coverage_evidence_ids: string[];
    };

type SectorCatalystCriterionResultSubmission =
  | {
      criterion: "CATALYSTS";
      coverage_state: "AVAILABLE_MATERIAL_CATALYSTS";
      comparison_status: "COMPARABLE";
      verdict: ComparableSectorCriterionVerdict;
      claim_refs: string[];
      coverage_evidence_ids: string[];
    }
  | {
      criterion: "CATALYSTS";
      coverage_state: "COVERAGE_CONFIRMED_NO_MATERIAL_CATALYST";
      comparison_status: "COMPARABLE";
      verdict: "NEUTRAL";
      claim_refs: string[];
      coverage_evidence_ids: string[];
    }
  | {
      criterion: "CATALYSTS";
      coverage_state: "SOURCE_UNAVAILABLE";
      comparison_status: "UNAVAILABLE";
      verdict: "NO_VOTE";
      claim_refs: [];
      coverage_evidence_ids: string[];
    };

type CoverageGatedDirectionCriterionResultSubmission =
  | MacroEventFitCriterionResultSubmission
  | SectorCatalystCriterionResultSubmission;

type OptionalEtfDirectionCriterionResultSubmission =
  | {
      criterion: OptionalEtfSectorComparisonCriterion;
      comparison_status: "COMPARABLE";
      verdict: ComparableSectorCriterionVerdict;
      claim_refs: string[];
    }
  | {
      criterion: OptionalEtfSectorComparisonCriterion;
      comparison_status: "INCOMPARABLE";
      verdict: "INCOMPARABLE";
      claim_refs: string[];
    };

type DirectionCriterionResultSubmission =
  | CoreDirectionCriterionResultSubmission
  | CoverageGatedDirectionCriterionResultSubmission
  | OptionalEtfDirectionCriterionResultSubmission;

interface DirectionPairwiseComparisonSubmission {
  comparison_local_id: string;
  direction_a_id: string;
  direction_b_id: string;
  criterion_results: DirectionCriterionResultSubmission[];
  claim_refs: string[];
}

type ResolvedDirectionPairVerdict = "A" | "B" | "NO_CLEAR_WINNER";

interface AcceptedDirectionPairResolution {
  comparison_local_id: string;
  direction_a_id: string;
  direction_b_id: string;
  resolved_verdict: ResolvedDirectionPairVerdict;
  base_support_count_a: number;
  base_support_count_b: number;
  optional_etf_support_weight_a: number;
  optional_etf_support_weight_b: number;
  weighted_support_a: number;
  weighted_support_b: number;
  decisive_voting_criteria: SectorComparisonCriterion[];
  qualifying_non_etf_criteria: VotingSectorComparisonCriterion[];
  resolution_reason:
    | "WEIGHTED_SUPPORT_MARGIN_A"
    | "WEIGHTED_SUPPORT_MARGIN_B"
    | "INSUFFICIENT_BASE_SUPPORT"
    | "INSUFFICIENT_WEIGHTED_MARGIN";
  source_submission_hash: string;
}

interface SingleDirectionQualificationSubmission {
  qualification_local_id: string;
  direction_id: string;
  null_benchmark_contract_id: string;
  criterion_results: DirectionCriterionResultSubmission[];
  claim_refs: string[];
}

type SectorDirectionResearchSubmission =
  | {
      research_mode: "PAIRWISE";
      comparison_claims: Claim[];
      direction_comparisons: DirectionPairwiseComparisonSubmission[];
      single_direction_qualification: null;
    }
  | {
      research_mode: "SINGLE_DIRECTION_QUALIFICATION";
      comparison_claims: Claim[];
      direction_comparisons: [];
      single_direction_qualification:
        SingleDirectionQualificationSubmission;
    };

interface SectorConflictReviewSubmission {
  review_round: 1;
  comparison_claims: Claim[];
  revised_comparisons: DirectionPairwiseComparisonSubmission[];
}

interface SectorFinalSelectionRuntimeDirective {
  selection_status: "SELECTED" | "NO_QUALIFIED_DIRECTION";
  preferred_direction_id: string | null;
  least_preferred_status: "REQUIRED" | "NOT_QUALIFIED" | "NOT_APPLICABLE";
  least_preferred_direction_id: string | null;
  least_preferred_reason: LeastPreferredEligibilityAudit["reason"];
  preferred_security_shortlist_id: string | null;
  preferred_security_shortlist_hash: string | null;
  least_preferred_security_shortlist_id: string | null;
  least_preferred_security_shortlist_hash: string | null;
  security_scoring_contract_version: string;
  security_scoring_contract_hash: string;
  allowed_preferred_security_ids: string[];
  allowed_least_preferred_security_ids: string[];
  required_final_evidence_ids: string[];
}

interface ModelVisibleSectorFinalSelectionDirective {
  selection_status: "SELECTED" | "NO_QUALIFIED_DIRECTION";
  preferred_direction_id: string | null;
  least_preferred_status: "REQUIRED" | "NOT_QUALIFIED" | "NOT_APPLICABLE";
  least_preferred_direction_id: string | null;
  least_preferred_reason: LeastPreferredEligibilityAudit["reason"];
  allowed_preferred_security_ids: string[];
  allowed_least_preferred_security_ids: string[];
  required_final_evidence_ids: string[];
}

interface SectorFinalSelectionSubmission {
  final_selection: SectorAgentSubmission;
}

interface LeastPreferredEligibilityAudit {
  least_preferred_eligibility_audit_id: string;
  least_preferred_eligibility_audit_hash: string;
  status: "REQUIRED" | "NOT_QUALIFIED" | "NOT_APPLICABLE";
  reason:
    | "UNIQUE_CONDORCET_LOSER"
    | "SINGLE_ELIGIBLE_DIRECTION"
    | "PREFERRED_NOT_QUALIFIED"
    | "NO_UNIQUE_CONDORCET_LOSER"
    | "NO_VERIFIABLE_NON_ETF_DECISIVE_EVIDENCE";
  eligible_direction_ids: string[];
  least_preferred_direction_id: string | null;
  qualifying_comparison_local_ids: string[];
  qualifying_claim_refs: string[];
  finalized_pair_matrix_hash: string;
  qualification_contract_version: string;
}

interface SingleDirectionQualificationAudit {
  single_direction_qualification_audit_id: string;
  single_direction_qualification_audit_hash: string;
  direction_id: string;
  null_benchmark_contract_id: string;
  null_benchmark_universe_hash: string;
  status: "QUALIFIED" | "NOT_QUALIFIED";
  base_support_count_direction: number;
  base_support_count_null: number;
  optional_etf_support_weight_direction: number;
  optional_etf_support_weight_null: number;
  weighted_support_direction: number;
  weighted_support_null: number;
  decisive_voting_criteria: SectorComparisonCriterion[];
  qualifying_non_etf_criteria: VotingSectorComparisonCriterion[];
  required_final_evidence_ids: string[];
  source_submission_hash: string;
  qualification_contract_version: string;
}

interface SectorDirectionComparisonAudit {
  direction_comparison_audit_id: string;
  direction_comparison_audit_hash: string;
  run_id: string;
  sector_agent_id: StandardSectorAgentId;
  research_mode: "PAIRWISE" | "SINGLE_DIRECTION_QUALIFICATION";
  snapshot_bundle_hash: string;
  initial_pair_matrix_hash: string;
  conflict_type:
    | "NONE"
    | "CYCLE"
    | "TIE"
    | "NO_EDGE"
    | "MULTIPLE";
  conflict_direction_ids: string[];
  conflict_set_hash: string | null;
  conflict_review_id: string | null;
  conflict_review_input_hash: string | null;
  conflict_review_status: "NOT_REQUIRED" | "COMPLETED";
  preferred_resolution_status:
    | "INITIAL_UNIQUE"
    | "REVIEW_RESOLVED"
    | "UNRESOLVED"
    | "SINGLE_DIRECTION_QUALIFIED"
    | "SINGLE_DIRECTION_NOT_QUALIFIED";
  least_resolution_status:
    | "INITIAL_UNIQUE"
    | "REVIEW_RESOLVED"
    | "UNRESOLVED"
    | "NOT_APPLICABLE";
  finalized_pair_matrix_hash: string;
  condorcet_winner_direction_id: string | null;
  condorcet_loser_direction_id: string | null;
  reducer_contract_version: string;
  least_preferred_eligibility_audit_id: string;
  least_preferred_eligibility_audit_hash: string;
  single_direction_qualification_audit_id: string | null;
  single_direction_qualification_audit_hash: string | null;
}

interface SectorInferenceBudgetContract {
  inference_budget_contract_version: string;
  direction_research_output_token_cap: number;
  conflict_review_output_token_reserve: number;
  final_selection_output_token_cap: number;
  total_stage_input_token_cap: number;
  total_stage_output_token_cap: number;
  maximum_model_subcalls: 3;
  review_reserve_transfer_policy: "NON_TRANSFERABLE";
  budget_breach_policy: "STAGE_REJECT";
}

interface KnotResearchScoreContract {
  research_score_contract_id: string;
  research_score_contract_version: string;
  research_score_contract_hash: string;
  normalized_inference_cost_formula:
    "HALF_INPUT_CAP_RATIO_PLUS_HALF_OUTPUT_CAP_RATIO";
  input_token_cost_weight: 0.5;
  output_token_cost_weight: 0.5;
  sector_inference_cost_penalty_per_unit: 0.2;
  sector_conflict_review_penalty: 0.05;
  maximum_sector_success_penalty: 0.25;
  sector_success_score_range: readonly [-1.25, 1];
  non_sector_success_score_range: readonly [-1, 1];
  agent_failure_score: -2;
  promotion_mean_delta_floor: 0.05;
  rollback_mean_delta_ceiling: -0.05;
}

interface KnotRuntimeContractManifest {
  knot_runtime_contract_manifest_id: string;
  knot_runtime_contract_manifest_version: string;
  knot_runtime_contract_manifest_hash: string;
  research_score_contract: KnotResearchScoreContract;
  scheduler_contract_id: string;
  scheduler_contract_version: string;
  scheduler_contract_hash: string;
}

interface SectorInferenceCostAuditBase {
  inference_cost_audit_id: string;
  inference_cost_audit_hash: string;
  production_variant_roster_id: string;
  production_variant_roster_revision_id: string;
  sector_agent_id: StandardSectorAgentId;
  snapshot_bundle_hash: string;
  inference_budget_contract_version: string;
  research_score_contract_id: string;
  research_score_contract_version: string;
  research_score_contract_hash: string;
  model_subcall_count: number;
  last_attempted_stage:
    | "PRE_MODEL"
    | "DIRECTION_RESEARCH"
    | "CONFLICT_REVIEW"
    | "FINAL_SELECTION"
    | "COMPLETED";
  conflict_review_triggered: boolean;
  input_tokens: number;
  output_tokens: number;
}

type SectorInferenceCostAuditOrigin =
  | {
      sample_origin: "PRODUCTION_ACTIVE";
      knot_pair_id: null;
      pair_side: null;
    }
  | {
      sample_origin:
        | "KNOT_RESEARCH_SHADOW"
        | "KNOT_POST_PROMOTION_CHAMPION_SHADOW";
      knot_pair_id: string;
      pair_side: "CHAMPION" | "CANDIDATE";
    };

type SectorInferenceCostAudit = SectorInferenceCostAuditOrigin &
  (
  | (SectorInferenceCostAuditBase & {
      disposition: "SUCCESS";
      model_subcall_count: 2 | 3;
      last_attempted_stage: "COMPLETED";
      normalized_inference_cost: number;
      budget_compliant: true;
      failure_reason: null;
    })
  | (SectorInferenceCostAuditBase & {
      disposition: "AGENT_FAILURE";
      normalized_inference_cost: number | null;
      budget_compliant: boolean;
      failure_reason:
        | "PRE_MODEL_CONTRACT_FAILURE"
        | "DIRECTION_RESEARCH_FAILURE"
        | "CONFLICT_REVIEW_FAILURE"
        | "FINAL_SELECTION_FAILURE"
        | "UNAUTHORIZED_EXTRA_SUBCALL"
        | "INPUT_TOKEN_CAP_EXCEEDED"
        | "OUTPUT_TOKEN_CAP_EXCEEDED"
        | "MODEL_SUBCALL_CAP_EXCEEDED";
    })
  );

interface KnotResearchScoreRecordBase {
  knot_research_score_record_id: string;
  knot_research_score_record_hash: string;
  knot_pair_id: string;
  pair_side: "CHAMPION" | "CANDIDATE";
  production_variant_roster_id: string;
  production_variant_roster_revision_id: string;
  execution_behavior_release_id: string;
  cohort_id: string;
  language: "en" | "zh";
  scheduled_sample_id: string;
  snapshot_bundle_hash: string;
  agent_id: AgentId;
  prompt_behavior_version: string;
  execution_behavior_version: string;
  knot_runtime_contract_manifest_id: string;
  knot_runtime_contract_manifest_version: string;
  knot_runtime_contract_manifest_hash: string;
  research_score_contract_id: string;
  research_score_contract_version: string;
  research_score_contract_hash: string;
  scheduler_contract_id: string;
  scheduler_contract_version: string;
  scheduler_contract_hash: string;
  operational_opportunity_audit_id: string;
  operational_opportunity_audit_hash: string;
  evaluation_object_hash: string | null;
  sector_inference_cost_audit_id: string | null;
  sector_inference_cost_audit_hash: string | null;
}

type KnotResearchScoreRecord =
  | (KnotResearchScoreRecordBase & {
      disposition: "SCORE";
      agent_kind: "STANDARD_SECTOR";
      outcome_label_id: string;
      outcome_label_hash: string;
      normalized_score: number;
      normalized_inference_cost: number;
      sector_cost_adjusted_score: number;
      raw_research_score: number;
      research_comparison_score: number;
      evaluation_object_hash: string;
    })
  | (KnotResearchScoreRecordBase & {
      disposition: "SCORE";
      agent_kind: "NON_SECTOR";
      outcome_label_id: string;
      outcome_label_hash: string;
      normalized_score: number;
      normalized_inference_cost: null;
      sector_cost_adjusted_score: null;
      raw_research_score: number;
      research_comparison_score: number;
      evaluation_object_hash: string;
      sector_inference_cost_audit_id: null;
      sector_inference_cost_audit_hash: null;
    })
  | (KnotResearchScoreRecordBase & {
      disposition: "AGENT_FAILURE";
      agent_kind: "STANDARD_SECTOR";
      outcome_label_id: null;
      outcome_label_hash: null;
      normalized_score: null;
      normalized_inference_cost: number | null;
      sector_cost_adjusted_score: null;
      raw_research_score: -2;
      research_comparison_score: -2;
      evaluation_object_hash: null;
      sector_inference_cost_audit_id: string;
      sector_inference_cost_audit_hash: string;
    })
  | (KnotResearchScoreRecordBase & {
      disposition: "AGENT_FAILURE";
      agent_kind: "NON_SECTOR";
      outcome_label_id: null;
      outcome_label_hash: null;
      normalized_score: null;
      normalized_inference_cost: null;
      sector_cost_adjusted_score: null;
      raw_research_score: -2;
      research_comparison_score: -2;
      evaluation_object_hash: null;
      sector_inference_cost_audit_id: null;
      sector_inference_cost_audit_hash: null;
    });

type AcceptedSectorSelectionPayload =
  | {
      selection_status: "SELECTED";
      preferred_direction: PreferredSectorDirectionSubmission;
      least_preferred_direction: OptionalLeastPreferredDirection;
      persistence_horizon: "DAYS" | "WEEKS" | "MONTHS";
      key_drivers: SectorDriverSubmission[];
      risks: SectorRiskSubmission[];
      claims: Claim[];
      claim_refs: string[];
      preferred_security_status: "PICKS_PRESENT" | "NO_QUALIFIED_SECURITY";
      long_picks: SectorSecurityPickSubmission[];
      least_preferred_security_status:
        | "PICKS_PRESENT"
        | "NO_QUALIFIED_SECURITY"
        | "NOT_APPLICABLE";
      short_or_avoid_picks: SectorSecurityPickSubmission[];
    }
  | {
      selection_status: "NO_QUALIFIED_DIRECTION";
      preferred_direction: { status: "NO_QUALIFIED_DIRECTION" };
      least_preferred_direction: NoQualifiedAvoidDirectionSubmission;
      persistence_horizon: "DAYS" | "WEEKS" | "MONTHS";
      key_drivers: SectorDriverSubmission[];
      risks: SectorRiskSubmission[];
      claims: Claim[];
      claim_refs: string[];
      preferred_security_status: "NO_QUALIFIED_SECURITY";
      long_picks: [];
      least_preferred_security_status: "NOT_APPLICABLE";
      short_or_avoid_picks: [];
    };

interface AcceptedSectorSelection {
  sector_agent_id: StandardSectorAgentId;
  agent_contract_version: string;
  prompt_behavior_version: string;
  execution_behavior_version: string;
  sector_direction_registry_version: string;
  sector_direction_registry_hash: string;
  selection: AcceptedSectorSelectionPayload;
  accepted_macro_input_attributions: AcceptedMacroInputAttribution[];
  direction_comparison_audit_id: string;
  direction_comparison_audit_hash: string;
  least_preferred_eligibility_audit_id: string;
  least_preferred_eligibility_audit_hash: string;
  single_direction_qualification_audit_id: string | null;
  single_direction_qualification_audit_hash: string | null;
  preferred_security_shortlist_id: string | null;
  preferred_security_shortlist_hash: string | null;
  least_preferred_security_shortlist_id: string | null;
  least_preferred_security_shortlist_hash: string | null;
  security_scoring_contract_version: string;
  security_scoring_contract_hash: string;
  inference_cost_audit_id: string;
  inference_cost_audit_hash: string;
  preferred_security_abstention_confidence: number | null;
  least_preferred_security_abstention_confidence: number | null;
  model_confidence: number;
  directional_confidence: number;
  abstention_confidence: number;
}

interface RelationshipFactualEdgeSubmission {
  edge_local_id: string;
  source_entity: string;
  target_entity: string;
  edge_type: string;
  claim_refs: string[];
}

interface RelationshipPredictiveEdgeSubmission {
  edge_local_id: string;
  edge_candidate_id: string;
  source_entity: string;
  target_entity: string;
  edge_type: string;
  transmission_direction: "POSITIVE" | "NEGATIVE" | "MIXED";
  activation_trigger: string;
  evaluation_horizon_trading_days: 20;
  model_confidence: number;
  claim_refs: string[];
}

interface RelationshipGraphSubmissionBase {
  factual_edges: RelationshipFactualEdgeSubmission[];
  key_drivers: SectorDriverSubmission[];
  risks: SectorRiskSubmission[];
  claims: Claim[];
  claim_refs: string[];
  macro_input_attributions: MacroInputAttributionSubmission[];
}

type RelationshipGraphSubmission =
  | (RelationshipGraphSubmissionBase & {
      predictive_graph_status: "EDGES_PRESENT";
      predictive_edges: [
        RelationshipPredictiveEdgeSubmission,
        ...RelationshipPredictiveEdgeSubmission[],
      ];
      predictive_graph_abstention_confidence: null;
    })
  | (RelationshipGraphSubmissionBase & {
      predictive_graph_status: "NO_QUALIFIED_PREDICTIVE_EDGE";
      predictive_edges: [];
      predictive_graph_abstention_confidence: number;
    });

interface AcceptedRelationshipFactualEdge {
  edge_id: string;
  edge_hash: string;
  source_entity: string;
  target_entity: string;
  edge_type: string;
  claim_refs: string[];
}

interface AcceptedRelationshipPredictiveEdge {
  edge_id: string;
  edge_hash: string;
  edge_candidate_id: string;
  source_entity: string;
  target_entity: string;
  edge_type: string;
  transmission_direction: "POSITIVE" | "NEGATIVE" | "MIXED";
  activation_trigger: string;
  evaluation_horizon_trading_days: 20;
  model_confidence: number;
  calibrated_confidence: number;
  calibration_state_id: string;
  calibration_state_effective_at: string;
  claim_refs: string[];
}

interface ModelVisibleRelationshipFactualEdge {
  source_entity: string;
  target_entity: string;
  edge_type: string;
  claim_refs: string[];
}

interface ModelVisibleRelationshipPredictiveEdge {
  source_entity: string;
  target_entity: string;
  edge_type: string;
  transmission_direction: "POSITIVE" | "NEGATIVE" | "MIXED";
  activation_trigger: string;
  evaluation_horizon_trading_days: 20;
  calibrated_confidence: number;
  claim_refs: string[];
}

interface AcceptedRelationshipGraph {
  relationship_agent_id: "relationship_mapper";
  agent_contract_version: string;
  prompt_behavior_version: string;
  execution_behavior_version: string;
  factual_edges: AcceptedRelationshipFactualEdge[];
  predictive_edges: AcceptedRelationshipPredictiveEdge[];
  predictive_graph_status:
    | "EDGES_PRESENT"
    | "NO_QUALIFIED_PREDICTIVE_EDGE";
  predictive_graph_abstention_confidence: number | null;
  key_drivers: SectorDriverSubmission[];
  risks: SectorRiskSubmission[];
  claims: Claim[];
  claim_refs: string[];
  accepted_macro_input_attributions: AcceptedMacroInputAttribution[];
  directional_confidence: number;
}

interface ModelVisibleAcceptedRelationshipGraph {
  relationship_agent_id: "relationship_mapper";
  factual_edges: ModelVisibleRelationshipFactualEdge[];
  predictive_edges: ModelVisibleRelationshipPredictiveEdge[];
  predictive_graph_status:
    | "EDGES_PRESENT"
    | "NO_QUALIFIED_PREDICTIVE_EDGE";
  key_drivers: SectorDriverSubmission[];
  risks: SectorRiskSubmission[];
  claims: Claim[];
  claim_refs: string[];
  directional_confidence: number;
}
```

`relationship_mapper` 必须提交非空 claims/claim refs、drivers 和 risks；每条 factual 或
predictive edge 的 refs 必须解析到本 submission 的 claim。factual edge 不允许模型自报
confidence，必须由 runtime 按当时可见证据验证后接受；predictive edge 必须给出固定 20
交易日 horizon、可检验 activation trigger 和 `[0,1]` `model_confidence`，并绑定运行前
冻结机会集中的唯一 `edge_candidate_id`。同一 candidate 不得重复提交，source/target/type
必须与 candidate 逐字段一致，候选域外预测边拒绝。`EDGES_PRESENT` 必须至少一条预测边且
graph abstention confidence 为 `null`；`NO_QUALIFIED_PREDICTIVE_EDGE` 必须为空数组并提交
`[0,1]` 概率，表示冻结机会集中不存在 material predictive edge。runtime 在验收后把
`edge_local_id` 解析为权威 `edge_id/hash`，accepted output 去除 raw
macro attribution 并保存解析后的 accepted attribution，同时使用 `as_of` 前有效的 edge
calibration state 生成 `calibrated_confidence`。Darwinian edge outcome 评分使用模型当时提交的
`model_confidence`；下游可靠度适配和 model-visible DTO 只使用
`calibrated_confidence`，并去除全部
edge ID/hash/candidate ID、raw edge/graph confidence、calibration state、behavior/version、
归因和验证审计字段。空 predictive edge 允许但令
`directional_confidence=0`；factual graph 仍完整传递，不能为了获得方向份额而把事实边伪装成
预测边，也不能靠永久提交空图逃避第 10.3 节的 missed-edge/abstention 评分。

`SELECTED` 时 preferred `direction_id` 必须解析到该 Agent 冻结 registry 中唯一且有效的
方向。least-preferred 若存在也必须来自同一 registry，且不得等于 preferred；它表达相对
`UNDERWEIGHT/AVOID`，不能仅因弱于 preferred 就声称绝对负收益。运行时在最终 pair matrix
冻结后生成 `LeastPreferredEligibilityAudit`：只有先存在唯一 Condorcet winner，且同时有且
只有一个 Condorcet loser、每条指向该 loser 的胜边至少有一个可验证并支持胜方的 decisive
non-ETF voting criterion 时才为
`REQUIRED`，模型必须提交该方向；只有一个 eligible
方向时无论 qualification 是否通过都为
`NOT_APPLICABLE/SINGLE_ELIGIBLE_DIRECTION`；多方向下没有唯一 loser 或没有可验证的
non-ETF decisive evidence 时为 `NOT_QUALIFIED`；preferred 本身未唯一确定时 least 固定
`NOT_QUALIFIED/PREFERRED_NOT_QUALIFIED`。最后一条只适用于 `research_mode=PAIRWISE`，
不得覆盖单方向的 `NOT_APPLICABLE`。模型必须使用匹配 reason 的
`NO_QUALIFIED_AVOID_DIRECTION`。模型不能用自报 confidence 选择评分目标或省略已被审计为
`REQUIRED` 的 least-preferred。`REQUIRED` audit 的 qualifying comparison/claim refs 必须
非空并完整覆盖 loser 对其余方向的每条败边；其他状态两数组必须为空。

`long_picks` 必须属于 preferred 在 `as_of` 已冻结的精确 scoring shortlist，且全部
`position_action=LONG`；`short_or_avoid_picks` 必须属于 least-preferred，且只能为
`SHORT/AVOID`。每侧最多五只、`pick_local_id/ts_code` 在整份 submission 内不得重复、
每只 `conviction` 必须大于零且同侧 conviction 之和不得超过 1。宽泛 PIT candidate domain
只用于生成运行前 shortlist，不能直接作为模型的 pick 许可域。`PICKS_PRESENT` 必须至少一只对应证券，`NO_QUALIFIED_SECURITY` 或
`NOT_APPLICABLE` 必须为空数组。`AVOID` 只传递给配置/风控，不生成订单；`SHORT` 也只有在
Execution 的 broker/品种可卖空合同通过后才可转为订单。方向成立但没有合格个股时仍保留
方向，只把对应选股状态设为 `NO_QUALIFIED_SECURITY`。合法 shortlist 被证明为空时该状态是
确定性空域；shortlist 非空时模型也可以弃选，但必须接受第 10.3 节独立的 security-abstention
proper loss 和 missed-opportunity regret，不能以空 picks 免费取得与证券 null 相同的零分。
每个实际 side 的 security abstention confidence 使用独立字段：`PICKS_PRESENT`、
`NOT_APPLICABLE` 或被证明为空的 shortlist 必须为 `null`；非空 shortlist 上提交
`NO_QUALIFIED_SECURITY` 时必须为 `[0,1]` 的数值，表示“该 side 确实没有 material security
opportunity”的概率。它不能复用顶层 confidence，也不进入下游 usage share；runtime 把两侧
字段从 accepted selection payload 中剥离后单独保存到 `AcceptedSectorSelection`，供 outcome
label 使用，model-visible Sector DTO 不暴露它们。submission 顶层 `confidence` 和
每个 pick 的 `conviction` 都必须在 `[0,1]`。

禁止输出多个 preferred、多个 least-preferred、完整方向排名表、总体 `sector_score`、跨注册
方向自造主题或模型自造 direction ID。`SELECTED` submission 顶层 `confidence` 的唯一语义是
“整份最终 preferred/审计决定的 least-preferred/picks 相对确定性 null policy 具有正组合
效用”的模型概率，不随方向腿数改变；`NO_QUALIFIED_DIRECTION` 分支的 confidence 则唯一
表示“冻结机会集中不存在达到 materiality floor 的合格方向/证券调用”的概率。运行时按分支
校准同一个顶层字段：前者生成整份 submission 唯一的 `directional_confidence` 和 usage share，
后者令 `directional_confidence=0` 并只生成独立 `abstention_confidence`。preferred 与
least-preferred 不再拥有独立 confidence 或 Darwin weight。两种状态都必须包含非空结构化 drivers、risks、claims 和结论级
`claim_refs`；每个 driver/risk/pick 的 refs 必须解析到本 submission 的非空 claim，FACT/
EVENT/RISK_FLAG claim 必须带快照中可验证的 `evidence_ids`。每个 pick 还必须给出 thesis。

`macro_input_attributions` 必须遵守第 9 节统一合同：无论 SELECTED 还是 abstain，都对十个
Macro Agent 各输出且只输出一条 `SUBMISSION_SUMMARY`。SELECTED 时，preferred 和存在的
least-preferred 分别使用 `target_type=SECTOR_THESIS/target_local_ref=direction_local_id`，
证券级归因使用
`target_type=SECURITY_PICK/target_local_ref=pick_local_id`；运行时验收并冻结对象后解析为
权威 target ref/hash 和 usage share。引用的 Macro claim 必须来自对应 accepted Macro output，
模型不得回显 runtime hash、权重或份额。
完整 `SectorAgentSubmission` 只进入 submission audit；runtime 验收后将去除 raw
`confidence/macro_input_attributions` 的 `AcceptedSectorSelectionPayload` 与解析完成的
`accepted_macro_input_attributions` 分开持久化，不能把 local refs 重新嵌回 accepted
selection。

模型第一阶段通过 structured-output channel 提交 `SectorDirectionResearchSubmission`。当
`n>=2` 时必须使用 `research_mode=PAIRWISE`，对 snapshot 中全部 eligible directions 的每个
无序 pair 恰好提交一条比较，且 `single_direction_qualification=null`；每条 pair 的
`criterion_results` 必须恰好覆盖四个 core criterion、两个 coverage-gated criterion 和两个
ETF criterion。四个 core criterion 必须为 `comparison_status=COMPARABLE` 且 verdict 只能是
`FAVORS_A/FAVORS_B/NEUTRAL`。`MACRO_EVENT_FIT` 只服从共同
`RoleEventCoverageSummary`：只有完整覆盖下的
`AVAILABLE_MATERIAL_EVENTS` 才允许三种 verdict，完整覆盖且明确为
`COVERAGE_CONFIRMED_NO_MATERIAL_EVENT` 时必须为 `NEUTRAL`；覆盖不完整时即使保留了部分
material projections，也必须 `SOURCE_UNAVAILABLE/UNAVAILABLE/NO_VOTE`。`CATALYSTS` 只服从两侧
`SectorCatalystCoverageSummary`：两侧 source 均健康且至少一侧有 material catalyst 时为
`AVAILABLE_MATERIAL_CATALYSTS` 并允许三种 verdict；两侧均健康且均无 material catalyst
时为 `COVERAGE_CONFIRMED_NO_MATERIAL_CATALYST/NEUTRAL`；任一侧 source unavailable 时
固定 `SOURCE_UNAVAILABLE/UNAVAILABLE/NO_VOTE`。两项 criterion 的 coverage state 都由
runtime 根据 card 确定，模型只能回显，不能用一项 coverage 替代另一项。所有 coverage
状态必须引用非空 `coverage_evidence_ids`；可比较状态还必须引用非空 comparison claim，
unavailable 状态的 `claim_refs` 必须为空。ETF criterion 在任一侧不可比时必须显式为
`comparison_status/verdict=INCOMPARABLE`，两侧对应 ETF block 都可比时则必须
`COMPARABLE` 且不得使用 `INCOMPARABLE`。
模型不得提交 pair 总体 winner、`INCOMPARABLE` 总结或 decisive list。运行时先对四个 core
和 coverage 可用的两项各计一票，得到 `base_support_count_a/b`；coverage unavailable 的
`NO_VOTE` 不进入分母，也不惩罚任一方向。两个 ETF criterion 只有各自两侧 block 都可比时
才进入解析，每项支持权重固定为 `0.5`，否则权重为零。于是
`weighted_support=base_support+optional_etf_support_weight`。一侧只有同时满足
`base_support_count>=2` 且 `weighted_support` 至少领先另一侧 `1.0` 时才解析为 A/B 胜边，
否则固定为 `NO_CLEAR_WINNER`。该规则允许 ETF 在基础证据打平或边缘领先时提供有限确认/
反证，但 ETF 永远不能单独建立胜边，缺失也不会降低基础支持。两项 ETF 的总权重上界恰为
`1.0`：因此它最多打破 base tie 或消除/确认一票 base margin，不能反转大于一票的非 ETF
优势；`minimum_base_support_count=2` 又排除了 ETF-only winner。
runtime 从支持胜方且实际计票的 results 确定性生成 `decisive_voting_criteria`，并另外保存
非 ETF 的 `qualifying_non_etf_criteria`；least-preferred 资格仍要求每条 loser 败边至少有
一个非 ETF qualifying criterion，不能只靠 ETF。每个可比较 verdict 必须引用非空
`comparison_claims`，未知、悬空或与 verdict 冲突的 claim 均拒绝。core/coverage claim 只能
引用对应 comparison-card branch；ETF evidence 只能进入两个 ETF criterion，不能借
`BASKET_TECHNICALS` 等 core 名义取得一票。该解析规则、基础最小支持数 `2`、ETF 半票和
加权票差 `1.0` 属于 comparison contract，不得由 final submission confidence、cohort 或
prompt 改写。A/B 胜边的两类 decisive arrays 必须非空且与计票结果完全一致；
`NO_CLEAR_WINNER` 时两数组必须为空，不能用事后挑选的“决定性证据”暗示不存在的 edge。

当 `n=1` 时必须使用 `research_mode=SINGLE_DIRECTION_QUALIFICATION`，pair 数组固定为空，并
对唯一 direction 与其注册的 single-direction null 提交恰好一条
`SingleDirectionQualificationSubmission`。此分支中 `FAVORS_A` 固定表示支持 direction，
`FAVORS_B` 固定表示支持 null；runtime 使用相同 core/coverage/ETF 半票与
`minimum_base_support_count=2/minimum_weighted_support_margin=1` 生成
`SingleDirectionQualificationAudit`。direction 满足门槛才为 `QUALIFIED` 并进入 final
selection；否则 final directive 为 `NO_QUALIFIED_DIRECTION`。qualification 的 direction/
null benchmark ID、universe hash、criterion、claims 和 evidence 必须来自同一
`SingleDirectionQualificationCard`，模型不得换用宽基、跳过 null 或把 ETF-only 支持当成
qualification。该 audit 的 decisive evidence 是 `n=1` final evidence 的唯一来源。
`required_final_evidence_ids` 在 `QUALIFIED/NOT_QUALIFIED` 两种状态都必须非空：
前者至少包含一个支持 direction 的 non-ETF voting evidence；后者包含确定性导致未达门槛的
non-ETF null-support/neutral evidence。coverage `NO_VOTE`、内部票数或 ETF-only evidence
不能单独满足该数组。

运行时把 A/B 解析结果解释为有向胜边，把 `NO_CLEAR_WINNER` 解释为无边；preferred 只有在
某方向击败其余全部 eligible directions 时才是唯一 Condorcet winner，least-preferred 只有在
某方向输给其余全部方向时才是唯一 Condorcet loser。没有严格 winner/loser 时，冲突集合固定为
所有强连通分量大小大于 1 的方向、所有 `NO_CLEAR_WINNER` pair 端点，以及 Copeland 最大/
最小分并列的方向之并集，其中 `copeland_score=outdegree-indegree`，无边不计胜负。运行时以
初始 matrix hash、排序后的冲突方向、snapshot bundle hash、comparison contract version 和
run/agent ID
确定性生成 review ID，并只允许一次使用相同 snapshot bundle 的
`SectorConflictReviewSubmission`；它必须恰好重提冲突集合内部全部 pair，集合外 pair
字节不变。review row 替换对应 initial row 后重算严格 Condorcet；仍不唯一时 preferred
对应整份 `NO_QUALIFIED_DIRECTION`，仅 least 不唯一时使用
`NO_QUALIFIED_AVOID_DIRECTION`。review ID 唯一约束使重试幂等，禁止第二轮复核、数组顺序、
direction ID 字典序、Copeland 分数或模型自报总分破同分。发生复核时首次提交的
comparison 只进审计，review 后的 matrix 才可冻结；未发生复核时直接冻结首次 matrix。
`SINGLE_DIRECTION_QUALIFICATION` 永远不得触发 conflict review；
`SectorDirectionComparisonAudit.single_direction_qualification_audit_id/hash` 必须非空且
pair-matrix winner/loser 字段为空；`conflict_type=NONE`、conflict direction 数组为空、
review ID/input hash 为空、review status 为 `NOT_REQUIRED`，initial/final matrix hash 均为
同一 canonical empty-matrix hash；preferred resolution status 必须与 qualification audit
严格对应为 `SINGLE_DIRECTION_QUALIFIED/SINGLE_DIRECTION_NOT_QUALIFIED`。`PAIRWISE`
不得使用这两个 status，且两个 single-direction audit 字段必须为空，
防止同一运行同时使用两种选择依据。

pair matrix、唯一 conflict review 和 `LeastPreferredEligibilityAudit` 全部完成后，runtime
才生成 `SectorFinalSelectionRuntimeDirective`。它把 preferred/least 对应的 exact shortlist
ID/hash 与 security scoring contract version/hash 绑定在运行时；发送给模型的
`ModelVisibleSectorFinalSelectionDirective` 只保留方向、允许的证券代码和 required
evidence，不暴露 hash、分数或内部权重。随后进行独立的最终
selection structured-output 调用。模型只能提交 `SectorFinalSelectionSubmission`：
preferred/least 状态和方向必须逐字段服从 directive，picks 必须来自 directive 中对应的精确
scoring shortlist，结论级 claims 必须引用至少一个 `required_final_evidence_ids`。该数组在
SELECTED/n>=2 时来自 winner 胜边的 decisive voting evidence，且至少包含一个非 ETF
qualifying evidence；ETF 参与打破基础平局或形成最终 margin 时，对应 ETF decisive evidence
也必须进入数组。`n=1` 时来自 qualification，
abstain 时来自最终 unresolved/no-clear-winner evidence；不得包含 pair 分数、内部 hash 或
ETF-only evidence。模型在 comparison/review 阶段提前提交 selection，或在 final 阶段重新
提交/修改 pair verdict，均为 schema 拒绝。由此 final model call 不需要猜测尚未生成的
reducer 或 least eligibility 状态。
directive 为 `NO_QUALIFIED_DIRECTION` 时 preferred/least IDs 和两侧 allowed security
arrays 以及两侧 shortlist ID/hash 必须为空。若 `research_mode=PAIRWISE`，least
status/reason 必须为 `NOT_QUALIFIED/PREFERRED_NOT_QUALIFIED`；若
`research_mode=SINGLE_DIRECTION_QUALIFICATION`，则必须为
`NOT_APPLICABLE/SINGLE_ELIGIBLE_DIRECTION`，并引用匹配的 qualification audit。
`SELECTED` 时 preferred ID 和对应 shortlist
ID/hash、允许证券集合必须存在且从 hash 匹配的同一冻结对象生成；least status 为
`REQUIRED` 时 least ID/shortlist ID/hash 必须存在，否则 least ID/array/shortlist ID/hash
必须为空。accepted output 必须原样保存这些 runtime binding 和 scoring contract version/hash；
outcome label 只能引用同一绑定，任何运行后重建、只比 ticker 数组不比 shortlist hash、或
accepted/outcome contract 不闭合都失败。任何不满足该 discriminated invariant 的 directive
在调用模型前即为 runtime 合同失败。

comparison、可选 review 和 final-selection 是同一 Sector graph stage 内的有序 subcall，
共享同一预物化 root snapshot bundle 和运行槽位；只有 direction research 持有一次性
tool capability，review/final 只接收从该 bundle 确定性生成的无工具投影，不得共享或重放
capability。整个阶段只产生一份 accepted output、一次 operational-reliability 机会和一个
Darwinian evaluation object；它们不增加逻辑 Agent 数或
29 阶段计数。每个标准 Sector 必须绑定同一
`SectorInferenceBudgetContract`：direction research、review reserve 和 final 各有固定 token cap，
总输入/输出 token 与最多三次 subcall 同时受限；review reserve 不得转给无冲突路径或 final，
超预算即阶段拒绝。每次运行保存 `SectorInferenceCostAudit`，记录是否触发 review、call 数、
token、最后尝试阶段和 disposition。成功分支必须有归一化成本；
production audit 固定
`sample_origin=PRODUCTION_ACTIVE/knot_pair_id=null/pair_side=null`；KNOT research 或
post-promotion champion shadow audit 必须保存对应非空 pair ID/side。两类 origin 不得互换，
正式运行不能伪造 KNOT pair，KNOT score 也不能引用 production cost audit。
成功时 `model_subcall_count=2` 当且仅当 `conflict_review_triggered=false`，为 `3` 当且
仅当其为 true；single-direction 路径必须为 `2/false`。失败分支保存实际的
`model_subcall_count=0/1/2/3/>3` 和精确 reason。cost audit 在推理结束时
append-only 写入，不等待未来 outcome，因此不得内嵌尚未成熟的 normalized/research score。
后续 `KnotResearchScoreRecord` 在成功 label 成熟后 join 该 audit 计算两种 research score；
Agent failure 则不生成 label，并在 score record 中固定两种 research score 为 `-2`。任一
subcall 失败则整个 Sector stage 失败，不能保留半成品
selection。review 是确定性冲突集合触发的受限复核，不形成第二份 accepted output或
Darwinian 样本；其额外资源在 KNOT 配对中按第 10.6 节计入成本调整，不能作为免费推理预算。

只有一个 eligible direction 时 pair matrix 为空，该方向必须通过上述可重放的
`SingleDirectionQualificationAudit=QUALIFIED` 才能成为 preferred，且 least-preferred
eligibility 固定 `NOT_APPLICABLE/SINGLE_ELIGIBLE_DIRECTION`；audit 为 `NOT_QUALIFIED` 时
只能输出整份 `NO_QUALIFIED_DIRECTION`。没有 eligible direction 时 Sector stage 拒绝，不能把 required 数据或
universe 失败转换成 `NO_QUALIFIED_DIRECTION`。final claims 只覆盖最终方向、picks、drivers
和 risks，不能复制全部比较
观点；`SELECTED/n>=2` 的 evidence lineage 必须与 winner 胜边的 runtime decisive voting
evidence 相交，并至少命中一个 qualifying non-ETF evidence；`SELECTED/n=1` 时与
qualified single-direction evidence 相交；`NO_QUALIFIED_DIRECTION/n>=2` 必须与导致
unresolved/no-clear-winner 的最终 comparison evidence 相交，
`NO_QUALIFIED_DIRECTION/n=1` 则必须与
`SingleDirectionQualificationAudit=NOT_QUALIFIED` 的 required evidence 相交。四种分支都
不得与最终 comparison/qualification 审计语义冲突。完整
initial/review matrix、comparison claims、冲突集合、
`LeastPreferredEligibilityAudit` 和 reducer trace 只保存到 runtime audit；正式下游只携带
净化后的最终选择，不把所有方向变成多张下游行业票。

四个 Superinvestor 使用同样明确的 submission/accepted/model-view 分层，不再只在 prose 中
约定输出：

```ts
type SuperinvestorAgentId = "druckenmiller" | "munger" | "burry" | "ackman";

interface SuperinvestorSecurityPickSubmission {
  pick_local_id: string;
  ts_code: string;
  position_action: "LONG" | "AVOID";
  conviction: number;
  thesis: string;
  claim_refs: string[];
}

type SuperinvestorAgentSubmission =
  | {
      selection_status: "SELECTED";
      confidence: number;
      holding_period: "WEEKS" | "MONTHS" | "YEARS";
      picks: SuperinvestorSecurityPickSubmission[];
      key_drivers: SectorDriverSubmission[];
      risks: SectorRiskSubmission[];
      claims: Claim[];
      claim_refs: string[];
      macro_input_attributions: MacroInputAttributionSubmission[];
    }
  | {
      selection_status: "NO_QUALIFIED_CANDIDATES";
      confidence: number;
      holding_period: "WEEKS" | "MONTHS" | "YEARS";
      picks: [];
      key_drivers: SectorDriverSubmission[];
      risks: SectorRiskSubmission[];
      claims: Claim[];
      claim_refs: string[];
      macro_input_attributions: MacroInputAttributionSubmission[];
    };

type AcceptedSuperinvestorSelectionPayload =
  | {
      selection_status: "SELECTED";
      holding_period: "WEEKS" | "MONTHS" | "YEARS";
      picks: SuperinvestorSecurityPickSubmission[];
      key_drivers: SectorDriverSubmission[];
      risks: SectorRiskSubmission[];
      claims: Claim[];
      claim_refs: string[];
    }
  | {
      selection_status: "NO_QUALIFIED_CANDIDATES";
      holding_period: "WEEKS" | "MONTHS" | "YEARS";
      picks: [];
      key_drivers: SectorDriverSubmission[];
      risks: SectorRiskSubmission[];
      claims: Claim[];
      claim_refs: string[];
    };

interface AcceptedSuperinvestorSelection {
  superinvestor_agent_id: SuperinvestorAgentId;
  agent_contract_version: string;
  prompt_behavior_version: string;
  execution_behavior_version: string;
  selection: AcceptedSuperinvestorSelectionPayload;
  accepted_macro_input_attributions: AcceptedMacroInputAttribution[];
  model_confidence: number;
  directional_confidence: number;
  abstention_confidence: number;
}
```

Superinvestor 的 raw submission 只进入 submission audit。runtime 验收冻结目标后，把
`macro_input_attributions` 解析成 `accepted_macro_input_attributions`；accepted output
不得继续嵌入未解析的 local refs。`SELECTED` 必须有 1–10 只来自冻结 Layer-2 candidate
domain 的唯一 ticker，每只 conviction 大于零且总和不超过 1；`NO_QUALIFIED_CANDIDATES`
必须为空，且只允许用于非空冻结 candidate domain 上的主动弃权。冻结 candidate domain
为空时不调用模型、不生成 submission/accepted output，只生成下述
`NoEvaluationObjectStageSkipRecord`。模型声明的 holding period 只作 thesis/诊断字段，
不能改变第 10 节固定 21 日 outcome。

四个 Decision Agent 同样必须使用显式 submission/accepted/model-view 合同；不能沿用现有
松散 Layer-4 对象或只在 prompt/prose 中约定字段：

```ts
type DecisionAgentId =
  | "cro"
  | "alpha_discovery"
  | "autonomous_execution"
  | "cio";

interface CroCandidateRiskActionSubmission {
  action_local_id: string;
  candidate_ref: string;
  ts_code: string;
  action:
    | "VETO"
    | "CAP_WEIGHT"
    | "REDUCE_WEIGHT"
    | "REQUIRE_REVIEW"
    | "NO_OBJECTION";
  predicted_risk_probability: number;
  max_target_weight: number | null;
  reason: string;
  claim_refs: string[];
}

interface CroRiskReviewPayload {
  review_disposition: "REVIEW_ACTIONS" | "NO_OBJECTION" | "BLOCK_ALL";
  candidate_actions: CroCandidateRiskActionSubmission[];
  correlated_risks: SectorRiskSubmission[];
  black_swan_scenarios: SectorRiskSubmission[];
  claims: Claim[];
  claim_refs: string[];
}

interface CroAgentSubmission extends CroRiskReviewPayload {
  agent_id: "cro";
  confidence: number;
  macro_input_attributions: MacroInputAttributionSubmission[];
}

interface AcceptedCroRiskAction extends CroCandidateRiskActionSubmission {
  cro_action_ref: string;
  cro_action_hash: string;
}

interface AcceptedCroRiskReviewPayload
  extends Omit<CroRiskReviewPayload, "candidate_actions"> {
  candidate_actions: AcceptedCroRiskAction[];
}

interface AcceptedCroRiskReview {
  agent_id: "cro";
  agent_contract_version: string;
  prompt_behavior_version: string;
  execution_behavior_version: string;
  accepted_cro_review_id: string;
  accepted_cro_review_hash: string;
  frozen_proposal_id: string;
  frozen_proposal_hash: string;
  frozen_candidate_universe_id: string;
  frozen_candidate_universe_hash: string;
  review: AcceptedCroRiskReviewPayload;
  accepted_macro_input_attributions: AcceptedMacroInputAttribution[];
  model_confidence: number;
}

interface AlphaNovelPickSubmission {
  pick_local_id: string;
  candidate_ref: string;
  ts_code: string;
  conviction: number;
  thesis: string;
  claim_refs: string[];
}

type AlphaDiscoveryPayload =
  | {
      discovery_disposition: "CANDIDATES";
      novel_picks: [AlphaNovelPickSubmission, ...AlphaNovelPickSubmission[]];
      key_drivers: SectorDriverSubmission[];
      risks: SectorRiskSubmission[];
      claims: Claim[];
      claim_refs: string[];
    }
  | {
      discovery_disposition: "NONE_FOUND";
      novel_picks: [];
      key_drivers: SectorDriverSubmission[];
      risks: SectorRiskSubmission[];
      claims: Claim[];
      claim_refs: string[];
    };

type AlphaDiscoverySubmission = AlphaDiscoveryPayload & {
  agent_id: "alpha_discovery";
  confidence: number;
  macro_input_attributions: MacroInputAttributionSubmission[];
};

interface AcceptedAlphaDiscovery {
  agent_id: "alpha_discovery";
  agent_contract_version: string;
  prompt_behavior_version: string;
  execution_behavior_version: string;
  accepted_alpha_discovery_id: string;
  accepted_alpha_discovery_hash: string;
  frozen_novel_candidate_universe_id: string;
  frozen_novel_candidate_universe_hash: string;
  selection: AlphaDiscoveryPayload;
  accepted_macro_input_attributions: AcceptedMacroInputAttribution[];
  model_confidence: number;
}

interface ExecutionOrderAssessmentSubmission {
  assessment_local_id: string;
  order_intent_ref: string;
  ts_code: string;
  requested_delta_weight: number;
  feasibility: "FEASIBLE" | "PARTIAL" | "BLOCKED";
  feasibility_confidence: number;
  predicted_cost_bps: number;
  max_executable_delta_weight: number | null;
  recommended_slice_count: number;
  reason: string;
  claim_refs: string[];
}

type ExecutionAssessmentPayload =
  | {
      execution_disposition: "ORDERS_ASSESSED";
      order_assessments: [
        ExecutionOrderAssessmentSubmission,
        ...ExecutionOrderAssessmentSubmission[],
      ];
      claims: Claim[];
      claim_refs: string[];
    }
  | {
      execution_disposition: "BLOCKED";
      order_assessments: [
        ExecutionOrderAssessmentSubmission,
        ...ExecutionOrderAssessmentSubmission[],
      ];
      claims: Claim[];
      claim_refs: string[];
    };

type AutonomousExecutionSubmission = ExecutionAssessmentPayload & {
  agent_id: "autonomous_execution";
  confidence: number;
};

interface AcceptedExecutionOrderAssessment
  extends ExecutionOrderAssessmentSubmission {
  execution_assessment_ref: string;
  execution_assessment_hash: string;
}

type AcceptedExecutionAssessmentPayload =
  | {
      execution_disposition: "ORDERS_ASSESSED";
      order_assessments: [
        AcceptedExecutionOrderAssessment,
        ...AcceptedExecutionOrderAssessment[],
      ];
      claims: Claim[];
      claim_refs: string[];
    }
  | {
      execution_disposition: "BLOCKED";
      order_assessments: [
        AcceptedExecutionOrderAssessment,
        ...AcceptedExecutionOrderAssessment[],
      ];
      claims: Claim[];
      claim_refs: string[];
    };

interface AcceptedExecutionAssessment {
  agent_id: "autonomous_execution";
  agent_contract_version: string;
  prompt_behavior_version: string;
  execution_behavior_version: string;
  accepted_execution_assessment_id: string;
  accepted_execution_assessment_hash: string;
  execution_mode: "PAPER" | "REAL";
  frozen_proposal_id: string;
  frozen_proposal_hash: string;
  cro_control_source: DecisionControlSourceRef<"cro">;
  frozen_order_intent_set_id: string;
  frozen_order_intent_set_hash: string;
  assessment: AcceptedExecutionAssessmentPayload;
  model_confidence: number;
}

interface CioTargetPositionSubmission {
  position_local_id: string;
  ts_code: string;
  target_weight: number;
  position_decision: "HOLD" | "ADD" | "REDUCE" | "EXIT";
  holding_period: "DAYS" | "WEEKS" | "MONTHS";
  thesis_status: "INTACT" | "WEAKENED" | "BROKEN" | "EXPIRED";
  risk_flags: string[];
  claim_refs: string[];
}

type CioPortfolioDecisionPayload =
  | {
      decision_disposition: "TARGET_PORTFOLIO";
      target_positions: [
        CioTargetPositionSubmission,
        ...CioTargetPositionSubmission[],
      ];
      cash_weight: number;
      decision_reason: string;
      claims: Claim[];
      claim_refs: string[];
    }
  | {
      decision_disposition: "HOLD_CURRENT";
      target_positions: CioTargetPositionSubmission[];
      cash_weight: number;
      decision_reason: string;
      claims: Claim[];
      claim_refs: string[];
    }
  | {
      decision_disposition: "ALL_CASH";
      target_positions: [];
      cash_weight: 1;
      decision_reason: string;
      claims: Claim[];
      claim_refs: string[];
    };

type CioProposalSubmission = CioPortfolioDecisionPayload & {
  agent_id: "cio";
  decision_stage: "PROPOSAL";
  confidence: number;
  macro_input_attributions: MacroInputAttributionSubmission[];
};

interface CioCroControlResolutionSubmission {
  cro_action_local_ref: string;
  resolution: "COMPLIED" | "MORE_CONSERVATIVE";
  reason: string;
  claim_refs: string[];
}

interface CioExecutionControlResolutionSubmission {
  execution_assessment_local_ref: string;
  resolution: "COMPLIED" | "MORE_CONSERVATIVE";
  reason: string;
  claim_refs: string[];
}

interface AcceptedCioCroControlResolution {
  cro_action_ref: string;
  cro_action_hash: string;
  resolution: "COMPLIED" | "MORE_CONSERVATIVE";
  reason: string;
  claim_refs: string[];
}

interface AcceptedCioExecutionControlResolution {
  execution_assessment_ref: string;
  execution_assessment_hash: string;
  resolution: "COMPLIED" | "MORE_CONSERVATIVE";
  reason: string;
  claim_refs: string[];
}

type CioFinalSubmission = CioPortfolioDecisionPayload & {
  agent_id: "cio";
  decision_stage: "FINAL";
  confidence: number;
  cro_control_resolutions: CioCroControlResolutionSubmission[];
  execution_control_resolutions: CioExecutionControlResolutionSubmission[];
  macro_input_attributions: MacroInputAttributionSubmission[];
};

interface AcceptedCioProposal {
  agent_id: "cio";
  decision_stage: "PROPOSAL";
  agent_contract_version: string;
  prompt_behavior_version: string;
  execution_behavior_version: string;
  frozen_pre_cio_input_id: string;
  frozen_pre_cio_input_hash: string;
  alpha_source: DecisionStageSourceRef<"alpha_discovery">;
  proposal_id: string;
  proposal_hash: string;
  decision: CioPortfolioDecisionPayload;
  accepted_macro_input_attributions: AcceptedMacroInputAttribution[];
  model_confidence: number;
}

interface AcceptedCioFinal {
  agent_id: "cio";
  decision_stage: "FINAL";
  agent_contract_version: string;
  prompt_behavior_version: string;
  execution_behavior_version: string;
  frozen_proposal_id: string;
  frozen_proposal_hash: string;
  cro_control_source: DecisionControlSourceRef<"cro">;
  execution_control_source: DecisionControlSourceRef<"autonomous_execution">;
  final_portfolio_id: string;
  final_portfolio_hash: string;
  decision: CioPortfolioDecisionPayload;
  cro_control_resolutions: AcceptedCioCroControlResolution[];
  execution_control_resolutions: AcceptedCioExecutionControlResolution[];
  accepted_macro_input_attributions: AcceptedMacroInputAttribution[];
  model_confidence: number;
}

type AcceptedDecisionOutput =
  | AcceptedCroRiskReview
  | AcceptedAlphaDiscovery
  | AcceptedExecutionAssessment
  | AcceptedCioProposal
  | AcceptedCioFinal;

type DecisionStageSkipAgentId =
  | "cro"
  | "alpha_discovery"
  | "autonomous_execution";

type NoEvaluationObjectStageSkipAgentId =
  | SuperinvestorAgentId
  | DecisionStageSkipAgentId;

interface NoEvaluationObjectStageSkipRecord<
  A extends NoEvaluationObjectStageSkipAgentId =
    NoEvaluationObjectStageSkipAgentId,
> {
  stage_skip_id: string;
  stage_skip_hash: string;
  agent_id: A;
  skip_reason: "NO_EVALUATION_OBJECT";
  frozen_object_set_id: string;
  frozen_object_set_hash: string;
  member_count: 0;
  model_invoked: false;
  eligibility_audit_id: string;
  eligibility_audit_revision_id: string;
  eligibility_audit_revision_hash: string;
  evidence_ids: [string, ...string[]];
  causal_dedupe_key: string;
}

interface KnotControlNoEvaluationObjectStageSkipRecord<
  A extends DecisionStageSkipAgentId = DecisionStageSkipAgentId,
> {
  stage_skip_id: string;
  stage_skip_hash: string;
  agent_id: A;
  sample_origin: "KNOT_CONTROL_SHADOW";
  skip_reason: "NO_EVALUATION_OBJECT";
  frozen_object_set_id: string;
  frozen_object_set_hash: string;
  member_count: 0;
  model_invoked: false;
  operational_opportunity_audit_id: string;
  operational_opportunity_audit_hash: string;
  evidence_ids: [string, ...string[]];
  causal_dedupe_key: string;
}

type DecisionStageSourceRef<A extends DecisionStageSkipAgentId> =
  | {
      source_status: "ACCEPTED_OUTPUT";
      agent_id: A;
      accepted_output_id: string;
      accepted_output_hash: string;
      stage_skip_id: null;
      stage_skip_hash: null;
    }
  | {
      source_status: "NO_EVALUATION_OBJECT";
      agent_id: A;
      accepted_output_id: null;
      accepted_output_hash: null;
      stage_skip_id: string;
      stage_skip_hash: string;
    };

type DecisionControlSourceRef<
  A extends "cro" | "autonomous_execution",
> = DecisionStageSourceRef<A>;

interface ModelVisibleNoEvaluationObjectStageSkipRecord<
  A extends NoEvaluationObjectStageSkipAgentId =
    NoEvaluationObjectStageSkipAgentId,
> {
  agent_id: A;
  skip_reason: "NO_EVALUATION_OBJECT";
  member_count: 0;
}

// 同一 model-visible DTO 可由 production/KNOT outcome stage skip 或 control-only
// stage skip 生成；模型看不到两类 audit 外键。
interface ModelVisibleAcceptedCroRiskReview {
  agent_id: "cro";
  review: CroRiskReviewPayload;
}

interface ModelVisibleAcceptedAlphaDiscovery {
  agent_id: "alpha_discovery";
  selection: AlphaDiscoveryPayload;
}

interface ModelVisibleAcceptedExecutionAssessment {
  agent_id: "autonomous_execution";
  execution_mode: "PAPER" | "REAL";
  assessment: ExecutionAssessmentPayload;
}

interface ModelVisibleAcceptedCioProposal {
  agent_id: "cio";
  decision_stage: "PROPOSAL";
  decision: CioPortfolioDecisionPayload;
}

interface ModelVisibleAcceptedCioFinal {
  agent_id: "cio";
  decision_stage: "FINAL";
  decision: CioPortfolioDecisionPayload;
}
```

普通 production/KNOT outcome stage skip 必须引用最终
`NO_EVALUATION_OBJECT` eligibility audit revision；`KnotControlNoEvaluationObjectStageSkipRecord`
只供 CIO 配对的 Alpha/CRO/Execution 控制依赖使用，并必须引用同一 final
`KNOT_CONTROL_SHADOW` operational audit ID/hash。`DecisionStageSourceRef` 的 skip ID/hash
在 production 图只能解析到前者，在 CIO KNOT control 子图只能解析到后者；两类记录共享
model-visible DTO，但不能互换 audit 外键或复制同一 skip ID。为避免循环 hash，control
operational audit 先保存预分配的 `stage_skip_id` 且固定 `stage_skip_hash=null`，其 final
hash 生成后再创建 control skip；control skip hash 覆盖该 operational ID/hash。普通
outcome stage skip 仍由 eligibility revision 单向引用，不采用这条 control 顺序。
`source_status=ACCEPTED_OUTPUT` 的 ID/hash 则必须解析到 owner、accepted kind、
graph/source run、origin、variant 和 payload 均匹配的 `AcceptedAgentOutputRecord`，不能
引用 payload 内部的 `accepted_*_id/hash`、裸 payload 或其他 namespace 的 latest record。

Decision 合同的语义校验必须同时保证：

- 所有顶层 confidence、逐候选 risk probability、pick conviction 和 feasibility confidence
  都是 `[0,1]` 有限数；预测成本非负，requested delta 位于 `[-1,1]` 且非零，
  slice count 为非负整数。模型不能使用 `NaN/Infinity` 或越界值等待 runtime 裁剪。
- CRO `candidate_actions` 与 pre-CRO frozen universe 一一对应，每个 candidate 恰好一条；
  `AcceptedCroRiskReview.frozen_proposal_id/hash` 必须匹配本 run 唯一 CIO proposal，
  frozen candidate universe 必须从该 proposal 的完整目标组合确定性派生，不能从 Alpha、
  Sector 或 Superinvestor 另加候选。
  frozen universe 为空时不调用模型、不生成 `CroAgentSubmission/AcceptedCroRiskReview`，
  只写 stage-skip 与
  `EXOGENOUS_EXCLUSION/NO_EVALUATION_OBJECT` audit，不能生成中性或正向 outcome。
  `NO_OBJECTION` 的 `max_target_weight=null`，`VETO` 为 `0`，`CAP_WEIGHT/REDUCE_WEIGHT`
  为 `[0,1]`，`REQUIRE_REVIEW` 为 `null`。顶层 disposition 必须由逐候选 action
  确定性推导，不能与 action 集合冲突。
- Alpha pick 必须来自 frozen novel universe，ticker/candidate ref 唯一；`CANDIDATES`
  为 1–10 个 pick，`NONE_FOUND` 必须为空。frozen novel universe 为空时不调用模型、
  不生成 `AlphaDiscoverySubmission/AcceptedAlphaDiscovery`，只写 deterministic stage-skip
  和 `NO_EVALUATION_OBJECT` audit；只有非空 universe 上的 `NONE_FOUND` 才是可评价弃权。
- Execution assessment 必须与 frozen order-intent set 一一对应；`PARTIAL` 必须给出严格位于
  `0` 与请求绝对 delta 之间的 executable delta，`BLOCKED` 固定为 `0`，`FEASIBLE`
  不得小于请求绝对 delta；`FEASIBLE/PARTIAL` 的 slice count 至少为 1，`BLOCKED` 固定为 0。
  `AcceptedExecutionAssessment.frozen_proposal_id/hash` 必须与 CRO 绑定的 proposal 一致，
  `cro_control_source` 必须引用本 run 的 CRO accepted/skip 分支；frozen order-intent
  set hash 必须由该 proposal 与 CRO source 共同确定。
  frozen order-intent set 必须由 runtime 从 CIO proposal 在确定性应用 CRO
  `VETO/CAP_WEIGHT/REDUCE_WEIGHT` 后生成；`REQUIRE_REVIEW` 未解除的 intent 不得进入，
  `NO_OBJECTION` 原样保留。模型不得自行把 raw proposal delta 重新加入。
  frozen intent set 为空时不调用模型、不生成
  `AutonomousExecutionSubmission/AcceptedExecutionAssessment`，只写 deterministic stage-skip
  和 `NO_EVALUATION_OBJECT` audit；存在 intent 却全部 blocked 时使用 `BLOCKED`，不能删除订单。
- CIO 的 `target_positions` 是完整目标组合而不是增量 action 列表，ticker 唯一、
  `target_weight` 非负且 `sum(target_weight)+cash_weight=1`。`HOLD_CURRENT`
  必须逐项等于冻结当前组合，`ALL_CASH` 必须为空仓且 cash 为 1；`EXIT` 必须
  `target_weight=0`，其他 action/当前权重/目标权重关系由冻结
  `cio_risk_cost_v1` validator 确定性校验。
- CIO final 必须逐一解析所有非 `NO_OBJECTION` CRO action 和全部 Execution assessment；
  只能 `COMPLIED` 或更保守，不能越过 `VETO/CAP_WEIGHT/REDUCE_WEIGHT`、提高
  `PARTIAL/BLOCKED` 的可执行量，或通过省略 resolution 绕过控制。
  若对应 control source 为 `NO_EVALUATION_OBJECT`，resolution 数组必须为空并引用唯一
  hash 匹配的 stage-skip record；若为 `ACCEPTED_OUTPUT`，则必须引用并完整覆盖该 accepted
  output。两种 source 互斥，不能用 skip record 掩盖非空候选/订单集合。
  模型只提交 action/assessment local ref；runtime 验收后必须解析为唯一 persistent ref/hash，
  accepted final 不得保留未解析 local ref。
- runtime 在接受 CRO/Execution 顶层输出时，必须按
  `accepted_review_or_assessment_id + local_id + canonical item payload` 为每个 item
  生成稳定的 persistent ref/hash，并分别物化 `AcceptedCroRiskAction` 和
  `AcceptedExecutionOrderAssessment`。顶层 accepted hash 必须覆盖按 local ID 排序的这些
  per-item ref/hash。local ID 重复、ref/hash 无法重算、CIO 引用不存在/已被替换的 item，
  或 resolution 的 persistent hash 与 frozen accepted review/assessment 不一致时，
  CIO final 整体拒绝。`AcceptedCioFinal.final_portfolio_hash` 还必须覆盖两个互斥
  `DecisionControlSourceRef`，并通过 `frozen_proposal_hash` 间接覆盖 proposal 的
  pre-CIO input hash、`alpha_source`、decision 和 accepted Macro attribution；accepted
  source 与 skip source 互换、漏 hash、引用其他 run 的 skip
  record、Execution assessment 绑定不同 proposal/CRO source，或 final 绕过 proposal
  直接加入 Alpha 候选时拒绝。model-view DTO 只暴露原始 local ID 和净化业务字段，
  不暴露 persistent ref/hash。
- CRO、Alpha、CIO submission 必须各自满足十条 Macro `SUBMISSION_SUMMARY`
  attribution；Execution 不读取 Macro，因此 schema 中不存在 Macro attribution。
- `AcceptedCioProposal.alpha_source` 必须与本 run 唯一
  `AcceptedAlphaDiscovery` 或 `NoEvaluationObjectStageSkipRecord<"alpha_discovery">`
  一致。accepted Alpha source 时 proposal 必须证明已逐项考虑全部 novel picks；
  skip source 时只能证明 frozen novel universe 为空，不能掩盖非空 universe 或已接受
  Alpha 输出。`proposal_hash` 必须覆盖 `frozen_pre_cio_input_id/hash`、`alpha_source`、
  完整 decision 和 accepted Macro attribution，从而使后续 CRO 审查与 final 重新核对的
  pre-CRO 目标组合及其证据边界不可脱离原始来源重建。
- 所有 Decision submission 的顶层 `claims/claim_refs` 非空，逐对象 refs 必须解析到本
  submission 的 claim。模型不能提交 accepted IDs/hash、lineage、可靠度或 Darwinian 字段；
  accepted/model-view DTO 只能由 runtime 从对应 submission 和冻结对象生成。
- `AcceptedCioProposal` 只用于冻结候选、CRO 和 Execution，不生成 Darwinian outcome；
  同一运行只有 `AcceptedCioFinal` 形成 CIO evaluation object。五类 accepted Decision
  output 均使用显式 `EvidenceLineageEnvelope`，不得用一个可选字段大对象在 proposal/final
  或不同 Agent 间互相反序列化。

所有 Macro、Sector、Superinvestor 和 Decision 跨层交接统一包裹运行时 lineage：

```ts
interface EvidenceLineageEnvelope<T> {
  payload: T;
  evidence_bundle_ids: [string, ...string[]];
  causal_dedupe_keys: [string, ...string[]];
}

interface ModelVisibleEvidenceLineageEnvelope<T> {
  payload: T;
  causal_dedupe_keys: [string, ...string[]];
}

interface CausalEvidenceContributionResolution {
  causal_dedupe_key: string;
  evidence_bundle_ids: [string, ...string[]];
  independent_evidence_count: 1;
  contributing_agent_ids: [AgentId, ...AgentId[]];
  contributing_claim_refs: string[];
  interpretation_state:
    | "CONSISTENT"
    | "CONFLICTING"
    | "FACT_ONLY";
  cross_layer_confidence_reducer: "NONE";
}

interface SourceLayerSnapshotRef {
  source_layer: "MACRO" | "SECTOR" | "SUPERINVESTOR" | "DECISION";
  source_layer_snapshot_id: string;
  source_layer_snapshot_hash: string;
}

interface CausalEvidenceResolutionSet {
  resolution_set_id: string;
  resolution_set_hash: string;
  consumer_agent_id: AgentId;
  consumer_input_snapshot_id: string;
  consumer_input_snapshot_hash: string;
  ordered_source_layer_snapshot_refs: [
    SourceLayerSnapshotRef,
    ...SourceLayerSnapshotRef[],
  ];
  resolutions: [
    CausalEvidenceContributionResolution,
    ...CausalEvidenceContributionResolution[],
  ];
}

type ModelVisibleCausalEvidenceContributionResolution = Omit<
  CausalEvidenceContributionResolution,
  "evidence_bundle_ids"
>;
```

模型只提交原始 payload；运行时按该 payload 合同中的 `claim_refs` 从证据目录
生成 envelope。Macro accepted record 的正式跨层 payload 类型为
`EvidenceLineageEnvelope<AcceptedMacroTransmission>`；graph state 只保存该 record 的
ID/hash，调用边界再解析并投影 envelope。CIO、
Superinvestor 和 Decision 合并候选时，同一 `causal_dedupe_key` 的独立证据数固定为 1，
但所有角色解释、claims、各自层内 usage share 和归因必须保留。Macro effective
confidence、Sector/Relationship directional confidence 与 Superinvestor confidence 的目标
不同，CRO/Alpha/CIO 的 action/decision confidence 也具有不同目标；禁止跨层比较大小、
取最大值、求和或选“赢家”。runtime 在每个消费者调用前先冻结
该消费者实际获准读取的全部 source-layer snapshot，生成唯一
`consumer_input_snapshot_id/hash` 和与其同 hash 边界的
`CausalEvidenceResolutionSet`，其中每个
`CausalEvidenceContributionResolution` 的同向解释标为 `CONSISTENT`，相反解释标为
`CONFLICTING` 并完整传给下游；同一 causal key 关联的全部 bundle ID 排序去重后保留，
但 `independent_evidence_count` 仍固定为 1。model view 必须使用显式
`ModelVisibleEvidenceLineageEnvelope<T>`，其 schema 从定义上不存在
`evidence_bundle_ids`；不得复用内部 envelope 后在序列化时动态删除字段。模型仍可看到
causal key、全部 contributing Agent/claim、冲突状态和唯一独立证据计数。
任何显式 evidence-count reducer 只能消费
`independent_evidence_count=1`，不能把多个解释当成多个独立事实。所有现有 Sector、Superinvestor 和
Decision accepted payload 都必须作为 `AcceptedAgentOutputRecord.output` 使用该
envelope，graph state/persistence 只保存 record ID/hash；Superinvestor/Decision stage-skip
的 runtime transport 也必须使用同一 envelope/resolution-set 边界，
但不伪装成 accepted output。每次 consumer invocation 及其输入审计必须增加匹配的
consumer-input/resolution-set ID/hash。模型 submission schema 不得包含 envelope 或
resolution 字段。

### 3.1 组件权重校准

组件基础权重不由 KNOT/Darwinian 在线修改。组件层使用独立、低频、离线、
强约束的校准器；KNOT/Darwinian 只调整组件合成后的最终 Agent 可靠度。

只有命中该 Agent 预注册 sample schedule、已在运行前成功冻结
`scheduled_sample_id/EvaluationOpportunitySet` 且组件输出被接受的运行，才追加不可变的
组件校准信号记录：

```ts
interface ComponentCalibrationSignal {
  component_calibration_signal_id: string;
  component_calibration_signal_hash: string;
  sample_origin: "PRODUCTION_ACTIVE";
  graph_run_id: string;
  run_slot_id: string;
  run_id: string;
  scheduled_sample_id: string;
  accepted_output_id: string;
  accepted_output_hash: string;
  operational_opportunity_audit_id: string;
  operational_opportunity_audit_hash: string;
  production_variant_roster_id: string;
  production_variant_roster_revision_id: string;
  execution_behavior_release_id: string;
  cohort_id: string;
  language: "en" | "zh";
  calibration_sample_role: "FIT_REFERENCE" | "CROSS_VARIANT_DIAGNOSTIC";
  agent_id: ComponentMacroAgentId;
  track_key_hash: string;
  agent_contract_version: string;
  prompt_behavior_version: string;
  execution_behavior_version: string;
  component_weight_contract_version: string;
  outcome_contract_version: string;
  scoring_contract_version: string;
  primary_label_id: PrimaryLabelId;
  sample_schedule_contract_version: string;
  rank_scope_contract_version: string;
  rank_scope: OutcomeRankScope;
  as_of: string;
  component: string;
  signal: number;
  model_confidence: number;
  deterministic_data_quality: number;
  effective_confidence: number;
  live_persistence_horizon: "DAYS" | "WEEKS" | "MONTHS";
  evaluation_horizon_trading_days: 5;
  evidence_bundle_ids: [string, ...string[]];
  outcome_due_at: string;
}

interface ComponentOutcomeContract {
  outcome_contract_version: string;
  scoring_contract_version: string;
  agent_id: ComponentMacroAgentId;
  primary_label_id: PrimaryLabelId;
  role_path_contract_version: string;
  evaluation_horizon_trading_days: 5;
  trading_calendar_id: string;
  sample_schedule_contract_version: string;
  rank_scope_contract_version: string;
  rank_scope: OutcomeRankScope;
}
```

这里的 `PrimaryLabelId` 由第 10.1 节 `OUTCOME_LABEL_REGISTRY` 生成，组件合同不得
自行声明另一个字符串 label ID。

组件校准不再持久化第二套不完整的 `ComponentOutcomeLabel`。
`ComponentCalibrationSignal` 通过
`accepted_output_id/hash + operational_opportunity_audit_id/hash + graph_run_id + run_slot_id +
run_id + scheduled_sample_id + production_variant_roster_id + agent_id +
prompt_behavior_version + execution_behavior_version + track_key_hash`
精确连接第 10.1 节唯一的 `AgentOutcomeLabel`；`component_calibration_target()`
只从该主标签的强类型 `raw_metrics`、成熟窗口和注册的
`outcome_contract_version` 确定性重建 `target`。找不到唯一主标签、主标签未成熟、
版本不匹配或重建值与审计缓存不一致时，该校准样本无效。signal ID/hash 必须可从
immutable record 重算；`accepted_output_id/hash` 必须解析到
`sample_origin=PRODUCTION_ACTIVE/accepted_output_kind=MACRO_TRANSMISSION` 且 Agent
匹配的 `AcceptedAgentOutputRecord`，operational ID/hash 必须解析到引用同一 accepted
record 的 final `ACCEPTED` audit。KNOT shadow、裸 payload、proposal 式中间态或跨
graph/run/slot/variant 引用不得进入组件拟合。

普通 daily-cycle 如果没有命中固定槽位或没有被 event registry 选择，不生成
`ComponentCalibrationSignal`；其 accepted transmission 仍可供当日下游消费，但只能写入
不参与拟合的运行诊断。事件驱动 Agent 只有 verified event 通过 priority/重叠选择并在
运行前生成 `scheduled_sample_id` 后才可写入信号。禁止为非计划运行事后补造 schedule ID、
`outcome_due_at` 或机会集，也不增加带 nullable schedule 字段的第二种校准记录。

其中 `signal=x_j`，`effective_confidence=q_j`。模型置信度和确定性数据质量必须
分别保存，不能只保存乘积。校准器在结果成熟后，将这些记录与同一 Agent、同一
合同版本的 append-only outcome label 进行 PIT join；不回写原始信号记录。

组件权重是跨 cohort/language 的运行时结构参数。版本化
`COMPONENT_CALIBRATION_REFERENCE_VARIANT` 固定 stable
`production_variant_roster_id=canonical(cohort_default, zh)`；只有运行时属于该 stable roster、且其
roster revision/release 当时为 current 的信号可以标记
`calibration_sample_role=FIT_REFERENCE` 并进入正式拟合，每个
`agent_id/as_of` 最多计一个样本。其余 15 个 active production variant 的信号必须标记
`CROSS_VARIANT_DIAGNOSTIC`，分别保留且不能合并进训练样本、不能把同一经济事件重复计数。
候选权重仍在所有具备足够样本的 production variant 上分别验证，但全部
cohort/language 在同一生效日使用同一权重版本。全局 release/roster revision 变化本身不
切断样本；是否可合并只由该 Component Agent 的完整 track key 和校准合同决定。
只有 stable reference cohort/language 变化时才发布新的 reference-variant 合同，不能在拟合时
临时选择表现更好的语言或 cohort。

同一 Agent 的全部组件必须使用第 10 节为该 Agent 预注册的同一个
`primary_label_id`，不能让每个组件选择各自有利的市场标签，也不能另用通用 A 股
收益替代 role-matched outcome。利率、信用、汇率或行业路径可保存为诊断标签，
但不能分别作为该 Agent 各组件的优化目标。校准 horizon 固定为五个 A 股交易日，
独立于 accepted `persistence_horizon`（复制到校准信号时命名为
`live_persistence_horizon`）和候选组件权重，避免候选权重改变自身评价标签。

共同目标使用从 `as_of` 后下一 A 股交易日开盘到第五个交易日收盘的该 Agent
role path：

```text
role_path_t = deterministic realized metric registered by primary_label_id
scale_t     = max(PIT trailing-252d std of non-overlapping 5d role paths,
                  label_specific_scale_floor)
y_t         = clamp(role_path_t / scale_t, -1, 1)
```

role path 的 series、代理篮子、基准、PIT 股票池、复权、方向和 scale floor 必须由
第 10 节同一个 outcome contract 注册，`ComponentOutcomeContract` 只引用它，不能
复制另一套定义。股票池沿用第 11 节无幸存者偏差规则。所有 scale 只使用 `as_of`
时已经结束的窗口，不能被后续修订刷新。`outcome_due_at` 对该次运行的全部组件
相同，固定为第五个交易日收盘；未到期不得生成 label。需要股票篮子的 outcome 在
`as_of` 冻结合格股票池，之后上市的股票不加入；停牌按上一可用价格持有，退市使用
最后可交易价格或已知现金对价结算。五日历史窗口的非重叠分组锚定预注册交易日历
epoch，不能为改善结果而改变起点。

正式校准样本沿用该 Agent `primary_label_id` 的 sample schedule。固定槽位 label
使用其 epoch 起每五个 A 股交易日的 `cohort_default/zh` reference variant 运行；事件驱动 label 使用同一
event registry、priority 和重叠窗口选择规则。槽位运行失败或事件输出未验收时留空，
不得用相邻日期补位；被重叠规则排除的事件也不能进入组件校准。这样组件拟合和最终
Darwinian 评分使用同一评价机会，且不能根据事后结果挑选样本。`sum(q_j)=0` 的运行
不进入校准。

校准样本必须同时满足：

- outcome 已成熟，且信号、证据、数据质量和 label 均满足 PIT；
- Agent、prompt behavior、组件集合、组件权重合同和评分合同版本精确匹配；
- 角色匹配、五日 outcome 窗口不重叠，并执行五个交易日 purge/embargo；
- 不含 fallback、未解决冲突、人工补值或不完整 required component；
- 每个组件达到预注册覆盖门槛。

少于 60 个有效样本时不得拟合；60–99 个样本只能生成 shadow 候选；至少
100 个样本后才可申请正式晋级。校准最多每半年执行一次，不能因短期市场表现
临时触发。

候选权重使用共同 outcome `y_t in [-1, 1]` 和以下目标函数生成：

```text
compose_t(w) -> F_t(w), direction_t(w), strength_t(w), confidence_t(w)
x_t(w) = direction_sign_t(w) * strength_t(w) / 5
p_t(w) = confidence_t(w) * x_t(w)

minimize mean((p_t(w) - y_t)^2)
       + lambda * sum((w_j - previous_weight_j)^2)

subject to:
  sum(w_j) = 1
  0.15 <= w_j <= 0.35
  abs(w_j - previous_weight_j) <= 0.05
```

初始 `lambda=1.0`，使用截至训练截止日最近五年的合格样本。任何 lambda、标签、
窗口或校准器算法变更都必须生成新合同版本，不能由单次运行或 cohort prompt
修改。验证至少使用五个按时间滚动的样本外 fold，每个验证 fold 至少 12 个样本，
并执行五个交易日 purge/embargo。

方向函数固定为：`v>=0.1` 是 SUPPORTIVE，`v<=-0.1` 是 ADVERSE，其余是
NEUTRAL；方向命中率按生产 composer 的
`direction_t(w)==direction(y_t)` 计算。regime 只使用
`as_of` 时可见数据：若 A 股宽基 20 日实现波动率高于其截至当日 252 日滚动
80 分位则为 `STRESS`，否则为 `NORMAL`。候选权重只有同时满足以下条件才进入
shadow：

- 相对当前权重的样本外均方损失改善至少 5%；
- 样本外方向命中率不下降；
- `NORMAL` 或 `STRESS` 中任一具备至少 20 个验证样本的 regime，其样本外损失
  恶化不超过 5%；
- 每个发生变化的组件在至少 75% fold 中具有相同调整方向；
- 任一组件在超过 50% fold 中贴住上下限时拒绝候选。

其他 production variant 不进入样本计数；诊断 eligibility 和截止日在候选拟合前冻结，并对同一
`agent_id/as_of/input snapshot/outcome label` 分别运行当前权重和候选权重形成 paired
loss。某 production variant 拥有至少 60 个这种合格 paired 诊断样本时，其 paired 样本外损失恶化
不得超过 5%，否则候选拒绝。不能只保留两侧都表现好的日期，单侧无法确定性 compose
视为候选失败；少于 60 个诊断样本的 variant 只留审计，既不放行也不单独阻止候选。

校准输出必须记录旧/新权重、训练截止日、样本数、排除原因、样本外指标、
约束、校准器版本、状态和内容哈希。候选权重先 shadow；累积至少 20 个新的、
成熟且非重叠 shadow 样本并继续通过上述门槛后，才可从未来指定日期发布新的
`component_weight_contract_version`。发布不追溯改写历史，旧版本保持可审计，
所有 cohort 在同一生效日使用同一版本，并支持回滚到上一版本。

`compose_t(w)` 必须调用与生产完全相同、按版本冻结的 neutral 阈值、strength
四舍五入、dispersion penalty、confidence clamp 和 tie-break；校准器不得用连续
`F_t(w)` 近似真正部署的离散化 `p_t(w)`。训练损失、候选门、滚动样本外 fold 和
shadow 比较全部使用相同的 `p_t(w)` forecast loss，`F_t(w)` 只作诊断。
求解器、浮点精度、初值、收敛容差和 tie-break 写入
`calibration_solver_version`，相同输入必须生成字节一致的候选权重。

## 4. 统一观测、事件与证据合同

### 4.1 宏观观测

```ts
interface MacroObservation {
  series_id: string;
  observation_period_start: string;
  observation_period_end: string;
  first_released_at: string;
  released_at: string;
  vintage_at: string;
  source_updated_at?: string;
  retrieved_at: string;
  raw_actual: string | null;
  raw_previous: string | null;
  raw_expected: string | null;
  actual: number | null;
  previous: number | null;
  expected: number | null;
  actual_parse_status: "PARSED" | "FAILED" | "EMPTY";
  previous_parse_status: "PARSED" | "FAILED" | "EMPTY";
  expected_parse_status: "PARSED" | "FAILED" | "EMPTY";
  unit: string;
  source: string;
  pit_status: "VERIFIED" | "UNVERIFIED" | "REJECTED";
  availability_proof: "OFFICIAL_VINTAGE" | "LOCAL_CAPTURE";
  conflict_status: "CLEAR" | "CONFLICT" | "RESOLVED";
  conflict_fields: Array<"ACTUAL" | "PREVIOUS" | "EXPECTED">;
  conflict_resolution_evidence_ids: string[];
  reconciliation_status:
    | "EXACT"
    | "WITHIN_TOLERANCE"
    | "EXPECTED_REVISION"
    | "CONFLICT"
    | "UNVERIFIED";
  revision_seq: number;
  is_preliminary: boolean;
  release_stage?: string;
  evidence_id: string;
  evidence_bundle_id: string;
}
```

历史运行只接受 `released_at <= as_of` 且 `vintage_at <= as_of` 的版本。对于
`LOCAL_CAPTURE` 还必须满足 `retrieved_at <= as_of`；对于
`OFFICIAL_VINTAGE`，允许之后才下载，但必须保存官方 release/vintage 目录证据，
证明该版本当时已经公开。无法证明当时可见的数据不得用于历史运行。
`CLEAR` 必须对应空 `conflict_fields/conflict_resolution_evidence_ids`；
`CONFLICT` 必须列出未解决字段；`RESOLVED` 必须列出原冲突字段和非空解决证据。

### 4.2 财经日历事件

Tushare `eco_cal` 返回：

- `date`
- `time`
- `currency`
- `country`
- `event`
- `value`
- `pre_value`
- `fore_value`

规范化后形成：

```ts
interface EconomicCalendarEvent {
  calendar_event_id: string;
  event_revision_id: string;
  supersedes_revision_id: string | null;
  retrieval_batch_id: string;
  country: string;
  currency: string | null;
  normalized_event: string;
  raw_date: string;
  raw_time: string | null;
  reference_period: string | null;
  release_stage: string;
  occurrence_key: string;
  occurrence_anchor_date: string;
  scheduled_at: string | null;
  released_at: string | null;
  timezone: string | null;
  time_status: "VERIFIED" | "UNVERIFIED";
  raw_actual: string | null;
  raw_previous: string | null;
  raw_forecast: string | null;
  actual: number | null;
  previous: number | null;
  forecast: number | null;
  unit: string | null;
  actual_parse_status: "PARSED" | "FAILED" | "EMPTY";
  previous_parse_status: "PARSED" | "FAILED" | "EMPTY";
  forecast_parse_status: "PARSED" | "FAILED" | "EMPTY";
  event_phase: "SCHEDULED" | "RELEASED" | "REVISED";
  conflict_status: "CLEAR" | "CONFLICT" | "RESOLVED";
  conflict_fields: Array<"ACTUAL" | "PREVIOUS" | "FORECAST">;
  conflict_resolution_evidence_ids: string[];
  reconciliation_status:
    | "EXACT"
    | "WITHIN_TOLERANCE"
    | "EXPECTED_REVISION"
    | "CONFLICT"
    | "UNVERIFIED";
  retrieved_at: string;
  last_seen_at: string;
  valid_from: string;
  valid_to: string | null;
  raw_row_hashes: [string, ...string[]];
  source_evidence_id: string;
  evidence_bundle_id: string;
}
```

`eco_cal` 没有稳定事件 ID、来源更新时间或完整 revision 链，因此：

- `calendar_event_id` 是一次逻辑发布的稳定 ID，由国家、货币、规范化事件、
  reference period、release stage 和 `occurrence_key` 生成，绝不包含可能变化的
  scheduled/released time。reference period 能从官方目录验证时，
  `occurrence_key=REFERENCE_PERIOD:<period>`；否则使用首次 PIT 采集时的原始日期形成
  `FIRST_SEEN_DATE:<date>:<sequence>`，其中 sequence 由同一来源响应中规范化后的稳定
  行排序确定。`occurrence_anchor_date` 和 sequence 一经建立不得因改期重算；之后才
  验证出的 reference period 作为 revision/alias 证据保存，不重算既有 ID。
- 原始 `date/time` 必须原样保存；即使时区未验证、无法形成 `scheduled_at`，也不能
  丢弃原始字段。相同名称且 reference period 为空的月度/周度重复事件必须得到不同
  occurrence key，不能折叠成一条无限 revision 链。
- 改期只能通过预注册 alias/matching 合同，把新行连接到已经存在的 occurrence：要求
  国家、货币、规范化事件、release stage 相等，并有官方改期证据或在允许窗口内与旧
  scheduled row 一一匹配。无法唯一匹配时创建新 occurrence 并标记人工审计，不能靠
  最近日期猜测或重用 ID。
- 每次 API 调用生成唯一 `retrieval_batch_id/retrieved_at`；同一批次内的所有
  原始行共享该 ID。`event_revision_id` 由 `calendar_event_id`、规范化内容和
  排序后的原始行哈希生成，不包含轮询时间。
- 不同 retrieval batch 各自只有一组唯一一致值时，改期、actual 更新或 forecast
  更新按 `retrieved_at` 形成新 revision，并通过 `supersedes_revision_id` 连接。
  当前响应不能证明某个值在更早时间可见，绝不反推 revision 时间。
- 同一 retrieval batch 内若 actual、previous 或 forecast 各自存在多个不一致值，
  因 Tushare 不提供行级更新时间而不能排序，该字段和 revision 标记
  `CONFLICT`，不得任意取最后一行。只有相同 reference period、release stage、
  单位且发布时间不晚于 `as_of` 的官方记录才能解决 actual/previous 冲突；forecast
  只能由发布前已保存的唯一一致快照解决，发布后数据不得回填历史 forecast。
  全部冲突字段都有合格证据解决后标记 `RESOLVED`，并保存非空
  `conflict_resolution_evidence_ids`；部分解决仍为 `CONFLICT`。
- 完全相同行在 batch 内先去重。重复轮询不修改 revision 行，而是追加
  `EventRetrievalObservation(retrieval_batch_id,event_revision_id,retrieved_at)`；
  `last_seen_at` 从观察记录计算，`valid_to` 从下一 revision 的 `valid_from` 派生，
  二者均不是可原地修改的事实字段。
- surprise 只在发布前已经采集到唯一一致的 forecast、且 actual 在
  `as_of` 时已经可见时，由确定性代码计算。
- 原始字符串和规范化数值同时保留；actual、previous、forecast 分别记录 parse
  status，任一字段失败不能掩盖其他字段已经成功解析的事实。
- 文档未明确的时区不得由模型猜测；未完成官方日历校验时
  `scheduled_at/timezone` 为空且 `time_status=UNVERIFIED`，该事件不能用于
  surprise、risk timing 或 execution timing。
- 采集范围是预注册的中国、美国、欧盟/欧元区、欧盟成员国和全球商品事件，
  不声称覆盖未注册的全球事件。
- 单次最多 100 行。按日期和国家/货币分片后，返回恰好 100 行的叶查询必须
  继续按事件族细分；无法继续细分或任何叶仍为 100 行时，当日覆盖拒绝。
- 当前响应不能用于重建过去尚未采集的 forecast。
- reconciliation 只比较相同 reference period、release stage、季调口径和
  规范化单位的值，并使用预注册的 series-specific tolerance。首报与首报在
  tolerance 内为 `WITHIN_TOLERANCE`；官方后续修订形成新 vintage 并标记
  `EXPECTED_REVISION`，不得反向否定当时 PIT 合法的首报；只有同发布阶段且
  超出 tolerance 的不可解释差异才是 `CONFLICT`。

### 4.3 共享事件投影

原始 `eco_cal` 事件不直接暴露给 Agent。运行时生成角色限定投影：

```ts
interface AgentEventProjection {
  calendar_event_id: string;
  event_revision_id: string;
  evidence_bundle_id: string;
  source_evidence_ids: [string, ...string[]];
  fact_owner: "economic_calendar_pipeline";
  signal_owner: AgentId;
  consumer_agent: AgentId;
  usage_mode: "PRIMARY" | "CONTEXT_ONLY";
  signal_scope: "MACRO_FACTOR" | "SECTOR_THESIS" | "DECISION_CONTROL";
  allowed_purpose:
    | "SIGNAL"
    | "TRANSMISSION"
    | "CATALYST"
    | "RISK_TIMING"
    | "EXECUTION_TIMING";
  materiality_tier: 1 | 2 | 3;
  normalized_event: string;
  reference_period: string | null;
  release_stage: string;
  scheduled_at: string | null;
  released_at: string | null;
  event_phase: "SCHEDULED" | "RELEASED" | "REVISED";
  actual: number | null;
  previous: number | null;
  forecast: number | null;
  surprise: number | null;
  unit: string | null;
  time_status: "VERIFIED" | "UNVERIFIED";
  conflict_status: "CLEAR" | "CONFLICT" | "RESOLVED";
  reconciliation_status:
    | "EXACT"
    | "WITHIN_TOLERANCE"
    | "EXPECTED_REVISION"
    | "CONFLICT"
    | "UNVERIFIED";
  causal_dedupe_key: string;
}

interface RoleEventCoverageSummary {
  coverage_state:
    | "AVAILABLE_MATERIAL_EVENTS"
    | "COVERAGE_CONFIRMED_NO_MATERIAL_EVENT"
    | "SOURCE_UNAVAILABLE";
  event_presence_state:
    | "MATERIAL_EVENTS_PRESENT"
    | "NO_MATERIAL_EVENT_OBSERVED";
  coverage_completeness: "COMPLETE" | "INCOMPLETE";
  coverage_as_of: string;
  query_complete: boolean;
  required_route_ids: [string, ...string[]];
  healthy_route_ids: string[];
  unhealthy_route_ids: string[];
  coverage_evidence_ids: [string, ...string[]];
  material_event_revision_ids: string[];
  coverage_contract_version: string;
}

interface SectorCatalystCoverageSummary {
  coverage_state:
    | "AVAILABLE_MATERIAL_CATALYSTS"
    | "COVERAGE_CONFIRMED_NO_MATERIAL_CATALYST"
    | "SOURCE_UNAVAILABLE";
  catalyst_presence_state:
    | "MATERIAL_CATALYSTS_PRESENT"
    | "NO_MATERIAL_CATALYST_OBSERVED";
  coverage_completeness: "COMPLETE" | "INCOMPLETE";
  coverage_as_of: string;
  query_complete: boolean;
  catalyst_source_registry_version: string;
  catalyst_source_registry_hash: string;
  required_source_ids: [string, ...string[]];
  healthy_source_ids: string[];
  unhealthy_source_ids: string[];
  coverage_evidence_ids: [string, ...string[]];
  material_catalyst_claim_refs: string[];
  coverage_contract_version: string;
}
```

硬约束：

- 事实采集和 reconciliation 统一由 `fact_owner` 负责；Tushare 与每个官方
  来源保留独立 `source_evidence_id`，共同挂到 `evidence_bundle_id`。
- 在 `MACRO_FACTOR` scope 内，同一 `evidence_bundle_id` 只能有一个
  `PRIMARY` signal owner，确保只形成一张 Macro 票。
- Sector-specific 事件可以在各自 `SECTOR_THESIS` scope 中作为 PRIMARY
  证据；广义宏观事件仍只能是 CONTEXT_ONLY。
- Decision scope 不产生方向票，只允许 catalyst/risk/execution timing。
- 下游合并按 `causal_dedupe_key=evidence_bundle_id` 检测共同因果来源，不能
  因 Macro 和 Sector 同时引用而叠加独立置信度。
- `CONTEXT_ONLY` 事件不得成为方向结论的唯一证据。
- 同一事件的官方时间序列核验进入同一 bundle，但保留自己的 source evidence
  和 vintage，不形成重复 Macro 方向来源。
- Agent 不能扩大事件查询范围或读取其他角色的投影。
- 投影必须携带模型解释所需的净化事实，而不是只给 opaque ID。`surprise` 仅在发布前已
  保存唯一 forecast、actual 已在 `as_of` 可见、时间已验证且无未解决冲突时生成；否则为
  `null`。`CONFLICT/UNVERIFIED` 事实可用于风险提示，但不能伪装成确定 surprise。
- `RoleEventCoverageSummary` 由 runtime 根据白名单 route、查询完整性、freshness 和 materiality
  contract 生成，模型不得自报。`event_presence_state` 只描述当前查询中是否观察到 material
  projection，`coverage_completeness` 单独描述 required route 是否完整；两者不得互相代替。
  三个 route 数组必须各自排序去重，`healthy_route_ids` 与 `unhealthy_route_ids` 不相交且
  并集恰好等于 `required_route_ids`，不能通过省略失败 route 缩小分母。
  只有 `query_complete=true`、排序去重后的 `healthy_route_ids` 与
  `required_route_ids` 完全相等且 `unhealthy_route_ids` 为空时才是 `COMPLETE`。任何 required
  route 缺失、stale、schema drift、权限失败或查询截断都必须为 `INCOMPLETE`。
  `coverage_state` 是这两个字段的确定性派生值：`COMPLETE+MATERIAL_EVENTS_PRESENT` 为
  `AVAILABLE_MATERIAL_EVENTS`；`COMPLETE+NO_MATERIAL_EVENT_OBSERVED` 为
  `COVERAGE_CONFIRMED_NO_MATERIAL_EVENT`；所有 `INCOMPLETE` 组合都为
  `SOURCE_UNAVAILABLE`，即使已经观察到部分 material events。
  三种状态都必须有非空 coverage evidence。`material_event_revision_ids` 必须始终与
  projections 中 material event revision IDs 的排序去重集合完全一致：
  `NO_MATERIAL_EVENT_OBSERVED` 时为空，`MATERIAL_EVENTS_PRESENT` 时非空。因此
  `SOURCE_UNAVAILABLE` 可以保留已观察到的部分事件，但这些事件只能作为
  `RISK_FLAG/CONTEXT_ONLY` 审计事实，不能使 coverage-gated criterion 投票，也不能证明
  “已覆盖全部重大事件”。
- `SectorCatalystCoverageSummary` 与财经日历 coverage 分开生成。它覆盖已注册的行业运营
  数据、官方产业政策目录、公司/行业公告和其他 Sector snapshot catalyst source；
  required source 闭集必须来自 hash 匹配的版本化 catalyst source registry，且每个
  Sector 至少有一个 required source；不能由本次成功响应反推分母。三个 source 数组必须
  排序去重，healthy/unhealthy 不相交且并集恰好等于 required。只有
  `query_complete=true`、全部 required 健康且 unhealthy 为空时才是 `COMPLETE`；
  权限失败、stale、schema drift、查询截断或漏掉 required source 均为 `INCOMPLETE`。
  `coverage_evidence_ids` 在三种状态下都必须非空。
  `material_catalyst_claim_refs` 必须与本次 catalyst card 中通过 materiality validator 的
  claim refs 排序去重集合完全一致；presence 为 PRESENT 时非空，NO_MATERIAL 时为空。
  `AVAILABLE_MATERIAL_CATALYSTS` 只能由
  `COMPLETE+MATERIAL_CATALYSTS_PRESENT` 派生；
  `COVERAGE_CONFIRMED_NO_MATERIAL_CATALYST` 只能由
  `COMPLETE+NO_MATERIAL_CATALYST_OBSERVED` 派生；所有 INCOMPLETE 组合固定为
  `SOURCE_UNAVAILABLE`，即使观察到部分 catalyst。财经日历无事件不能推出“无行业催化”，
  行业目录不可用也不能改变 `MACRO_EVENT_FIT` coverage。

## 5. eco_cal 跨 Agent 使用矩阵

### 5.1 Macro

| Agent | 模式 | 允许内容 |
| --- | --- | --- |
| `china` | PRIMARY | 中国 GDP、价格、就业、生产、消费、贸易、信用和财政发布 |
| `us_economy` | PRIMARY | 美国增长、就业、价格、生产、消费与贸易发布 |
| `eu_economy` | PRIMARY | 欧盟增长、就业、价格、生产、消费和贸易发布 |
| `central_bank` | PRIMARY | PBOC 决议、政策利率和职责内流动性事件 |
| `us_financial_conditions` | PRIMARY | Fed 决议、美国利率/信用/金融条件事件；美国实体数据仅 CONTEXT_ONLY |
| `euro_area_financial_conditions` | PRIMARY | ECB 决议及欧元区金融条件事件；实体数据仅 CONTEXT_ONLY |
| `commodities` | PRIMARY | 能源库存、供给、商品和预注册农业报告 |
| `geopolitical` | CONTEXT_ONLY | 已映射经贸事件的触发时间，不替代事件库 |
| `market_breadth` | DENY | 禁止读取 |
| `institutional_flow` | DENY | 禁止读取 |

### 5.2 Sector

以下 Sector 只能读取 `event_to_sector_map` 命中的投影。行业专属运营事件可在
该 Agent 的 `SECTOR_THESIS` scope 内作为 PRIMARY；广义宏观事件只能是
CONTEXT_ONLY：

- `semiconductor`：生产、贸易、科技周期和下游需求。
- `technology`：电子（不含半导体）、计算机、通信和传媒的生产、软件/通信需求、
  科技投资与贸易事件。
- `energy`：EIA 等行业库存/供给以及已注册的新能源装机、发电、利用率、光伏/风电/
  电池产业事件可为 Sector PRIMARY；能源价格和工业需求等广义宏观事件为 CONTEXT_ONLY。
- `consumer`：通胀、零售、收入、汽车耐用品周期和消费信心。
- `industrials`：工业生产、PMI、资本开支、基础材料需求和贸易。
- `real_estate_construction`：房地产销售/投资、施工、竣工和建材需求；广义信用与
  PBOC 事件只能为 CONTEXT_ONLY。
- `financials`：政策利率、曲线、信贷和流动性。
- `agriculture`：预注册农业供需/库存报告可为 Sector PRIMARY；通胀、贸易和
  广义商品事件为 CONTEXT_ONLY。

这些 Agent 只能解释行业传导，不能重述或重投 Macro 方向。

`biotech` 与 `relationship_mapper` 默认没有直接 `eco_cal` 权限。新增
权限必须通过合同版本变更，不能由 prompt 临时扩大。

### 5.3 Decision 与 Superinvestor

| Agent | 用途 |
| --- | --- |
| `cro` | 只接收未来重大事件的 `RISK_TIMING` 投影 |
| `alpha_discovery` | 只接收 `CATALYST` 投影 |
| `autonomous_execution` | 只接收 `EXECUTION_TIMING` 投影 |
| `cio` | 不直接读取 `eco_cal`/role-event 投影；消费冻结的上游带证据结论 |
| 四个 Superinvestor | 不直接读取 `eco_cal`；消费 Macro/Sector 输出 |

## 6. 数据源与角色快照

### 6.1 目标快照

保留或新增：

- `get_china_macro_snapshot`
- `get_us_macro_snapshot`
- `get_eu_macro_snapshot`
- `get_central_bank_snapshot`
- `get_us_financial_conditions_snapshot`
- `get_euro_area_financial_conditions_snapshot`
- `get_commodity_conditions_snapshot`
- `get_geopolitical_events_snapshot`
- `get_market_breadth_snapshot`
- `get_market_positioning_snapshot`

Macro 事件投影嵌入上述角色快照。获准的 Sector 和 Decision Agent 统一使用
零参数 `get_role_event_snapshot()`；该工具不接受 `agent_id`、事件范围或用途
参数，调用者身份由 LangGraph node/runtime capability 绑定，模型无法伪造：

```ts
interface RoleEventSnapshot {
  role_event_snapshot_id: string;
  role_event_snapshot_hash: string;
  consumer_agent: AgentId;
  as_of: string;
  contract_version: string;
  coverage: RoleEventCoverageSummary;
  projections: AgentEventProjection[];
}
```

运行时只为第 5 节白名单内的调用者注册该工具，并根据绑定身份确定
`usage_mode/signal_scope/allowed_purpose`。`biotech`、`relationship_mapper`、
`cio`、Superinvestor、`market_breadth` 和 `institutional_flow` 的工具表中不得
出现它。`eco_cal` 只由共享采集层获取；任何 Agent 都不能直接调用 Tushare
原始接口或传入另一个 Agent 的身份。

标准 Sector 不依赖模型是否实际调用 optional event tool 来决定 criterion coverage。runtime
在任何 Sector model call 前都物化一次 `RoleEventSnapshot`，将完全相同的
`coverage/projections` 嵌入 `get_sector_research_snapshot()` 的 comparison context；独立
`get_role_event_snapshot()` 只提供同一 bundle 中的详细视图，不能改变 coverage 或获取更新
数据。未调用 optional tool 仍使用已物化状态，调用与否不得把
`SOURCE_UNAVAILABLE` 改成 no-event，也不得改变 pair resolver。
`role_event_snapshot_hash` 覆盖 consumer、as-of、contract version、coverage 与按稳定键排序的
projections；comparison card、single-direction null card 和 optional tool response 必须引用
相同 ID/hash，任一字节漂移都使 Sector stage 失败。

Tushare endpoint 必须由版本化权限注册表控制，不能因为 SDK 中存在方法就注册工具：

```ts
const TUSHARE_ENDPOINT_REGISTRY = {
  eco_cal: { status: "PRECHECK_REQUIRED" },
  cn_pmi: { status: "PRECHECK_REQUIRED" },
  cn_gdp: { status: "PRECHECK_REQUIRED" },
  cn_cpi: { status: "PRECHECK_REQUIRED" },
  cn_ppi: { status: "PRECHECK_REQUIRED" },
  shibor: { status: "PRECHECK_REQUIRED" },
  shibor_quote: { status: "PRECHECK_REQUIRED" },
  yc_cb: { status: "PRECHECK_REQUIRED" },
  us_tycr: { status: "PRECHECK_REQUIRED" },
  trade_cal: { status: "PRECHECK_REQUIRED" },
  stock_basic: { status: "PRECHECK_REQUIRED" },
  stock_st: { status: "PRECHECK_REQUIRED" },
  daily: { status: "PRECHECK_REQUIRED" },
  daily_basic: { status: "PRECHECK_REQUIRED" },
  adj_factor: { status: "PRECHECK_REQUIRED" },
  suspend_d: { status: "PRECHECK_REQUIRED" },
  stk_limit: { status: "PRECHECK_REQUIRED" },
  index_basic: { status: "PRECHECK_REQUIRED" },
  index_classify: { status: "PRECHECK_REQUIRED" },
  index_member_all: { status: "PRECHECK_REQUIRED" },
  index_daily: { status: "PRECHECK_REQUIRED" },
  index_weight: { status: "PRECHECK_REQUIRED" },
  fund_basic: { status: "PRECHECK_REQUIRED" },
  etf_index: { status: "PRECHECK_REQUIRED" },
  fund_daily: { status: "PRECHECK_REQUIRED" },
  fund_adj: { status: "PRECHECK_REQUIRED" },
  fund_nav: { status: "PRECHECK_REQUIRED" },
  fund_share: { status: "PRECHECK_REQUIRED" },
  fund_portfolio: { status: "PRECHECK_REQUIRED" },
  fut_basic: { status: "PRECHECK_REQUIRED" },
  fut_daily: { status: "PRECHECK_REQUIRED" },
  fx_obasic: { status: "PRECHECK_REQUIRED" },
  fx_daily: { status: "PRECHECK_REQUIRED" },
  moneyflow: { status: "PRECHECK_REQUIRED" },
  moneyflow_ind_ths: { status: "PRECHECK_REQUIRED" },
  top_list: { status: "PRECHECK_REQUIRED" },
  top10_holders: { status: "PRECHECK_REQUIRED" },
  top10_floatholders: { status: "PRECHECK_REQUIRED" },
  stock_company: { status: "PRECHECK_REQUIRED" },
  fina_indicator: { status: "PRECHECK_REQUIRED" },
  forecast: { status: "PRECHECK_REQUIRED" },
  express: { status: "PRECHECK_REQUIRED" },
  income: { status: "PRECHECK_REQUIRED" },
  balancesheet: { status: "PRECHECK_REQUIRED" },
  cashflow: { status: "PRECHECK_REQUIRED" },
  fina_mainbz: { status: "PRECHECK_REQUIRED" },
  disclosure_date: { status: "PRECHECK_REQUIRED" },
  research_report: { status: "PRECHECK_REQUIRED" },
  major_news: { status: "DISABLED_PERMISSION_DENIED" },
  news: { status: "DISABLED_PERMISSION_DENIED" },
  npr: { status: "DISABLED_PERMISSION_DENIED" },
  monetary_policy: { status: "DISABLED_PERMISSION_DENIED" },
} as const;

type TushareEndpointId = keyof typeof TUSHARE_ENDPOINT_REGISTRY;

interface TushareEndpointRegistration {
  endpoint: TushareEndpointId;
  status: "ACTIVE_VERIFIED" | "PRECHECK_REQUIRED" | "DISABLED_PERMISSION_DENIED";
  permission_checked_at: string | null;
  permission_evidence_id: string | null;
  schema_contract_version: string | null;
  runtime_client_enabled: boolean;
  agent_tool_exposed: false;
}
```

当前权限事实固定为：

| Tushare endpoint | 状态 | 正式替代路径 |
| --- | --- | --- |
| `major_news` | `DISABLED_PERMISSION_DENIED` | GDELT 只做发现，事件状态由中国及国际官方源确认 |
| `news` | `DISABLED_PERMISSION_DENIED` | 同上；不得用另一个新闻接口静默替代 |
| `npr`（National Policy Repository） | `DISABLED_PERMISSION_DENIED` | 国务院、PBOC、商务部及相关部委官方发布目录 |
| `monetary_policy` | `DISABLED_PERMISSION_DENIED` | PBOC 官方货币政策报告、政策公告、公开市场操作和利率数据 |

这四个 endpoint 必须满足 `runtime_client_enabled=false`，不得出现在 Agent tool
whitelist、bridge handler、采集 job、历史 replay 或 fallback chain 中。启动 preflight
只验证禁用记录存在，不允许通过重试探测权限；未来确实取得权限时，也必须提供新的
permission evidence、发布新 registry version 并先走 shadow，不能原地改状态。
不存在“其余 endpoint 默认值”。运行时、series map、bridge、fixture 或文档引用的每个
Tushare endpoint 必须是 `TushareEndpointId`；未在该封闭注册表中的字符串一律
`DENY_UNKNOWN_ENDPOINT`。注册表由 `mosaic/dataflows/tushare_catalog.py` 中本计划标为
runtime-required 的条目、所有角色 source map 和实际 bridge/采集调用的引用并集做静态
一致性检查：引用集合不得超出注册表，
删除最后一个引用后才可另行退役记录。`PRECHECK_REQUIRED` 只有在真实权限、非空响应、
schema 和 PIT 时间字段 smoke 通过并写入 evidence 后才可发布为 `ACTIVE_VERIFIED`；接口
错误、合法空响应和权限拒绝必须使用不同状态，均不得自动晋级或 fallback。
`PRECHECK_REQUIRED/DISABLED_PERMISSION_DENIED` 必须
`runtime_client_enabled=false`；只有对应 registry revision 已发布为 `ACTIVE_VERIFIED`
时采集 client 才能启用，且原始 endpoint 仍不得作为 Agent tool 暴露。

#### 6.1.1 运行时能力边界与 28-Agent 工具矩阵

模型可调用工具与运行时注入输入必须分开。模型工具全部是零参数角色快照；
`graph_run_id/run_slot_id/agent_id/as_of/run_id/candidate universe/stage` 由运行时绑定，模型不能传入 ticker、
日期、角色或任意查询条件来扩大范围。accepted 上游输出、冻结候选域、当前持仓、现金、
约束和前次目标属于带 hash 的不可变 runtime input，不伪装成工具。

每次普通节点执行，或每个 KNOT champion/candidate paired attempt，先在任何模型调用之前
物化一次不可变快照 bundle，再为相关 node 分别签发只指向该 bundle 的 capability。
collector 在节点或 paired attempt 执行期间不得热更新 bundle：

```ts
type SectorAgentId = StandardSectorAgentId | "relationship_mapper";

type AgentId =
  | MacroAgentId
  | SectorAgentId
  | SuperinvestorAgentId
  | DecisionAgentId;

type AgentExecutionStageId =
  | Exclude<AgentId, "cio">
  | "cio_proposal"
  | "cio_final";

type AgentToolId =
  | "get_china_macro_snapshot"
  | "get_us_macro_snapshot"
  | "get_eu_macro_snapshot"
  | "get_central_bank_snapshot"
  | "get_us_financial_conditions_snapshot"
  | "get_euro_area_financial_conditions_snapshot"
  | "get_commodity_conditions_snapshot"
  | "get_geopolitical_events_snapshot"
  | "get_market_breadth_snapshot"
  | "get_market_positioning_snapshot"
  | "get_sector_research_snapshot"
  | "get_role_event_snapshot"
  | "get_relationship_graph_snapshot"
  | "get_superinvestor_candidate_snapshot"
  | "get_cro_risk_snapshot"
  | "get_alpha_candidate_snapshot"
  | "get_execution_snapshot"
  | "get_cio_decision_snapshot";

interface AgentSnapshotBundle {
  snapshot_bundle_id: string;
  snapshot_bundle_hash: string;
  snapshot_bundle_contract_version: string;
  materialization_request_id: string;
  agent_id: AgentId;
  stage: AgentExecutionStageId;
  as_of: string;
  candidate_scope_hash: string | null;
  runtime_input_hash: string;
  tool_payload_hashes: Readonly<Partial<Record<AgentToolId, string>>>;
  materialized_at: string;
}

interface AgentToolCapability {
  capability_id: string;
  graph_run_id: string;
  run_slot_id: string;
  run_id: string;
  node_id: string;
  agent_id: AgentId;
  stage: AgentExecutionStageId;
  allowed_tools: readonly AgentToolId[];
  as_of: string;
  candidate_scope_hash: string | null;
  snapshot_bundle_id: string;
  snapshot_bundle_hash: string;
  issued_at: string;
  expires_at: string;
  nonce: string;
}

interface SignedAgentToolCapability {
  manifest: AgentToolCapability;
  signing_key_id: string;
  signature: string;
}
```

bundle 是独立于单次 champion/candidate node 的不可变内容工件；
`graph_run_id/run_slot_id/run_id/node_id` 只绑定 capability，不进入 bundle，因此同一
KNOT 配对可以合法复用同一个 bundle。每个 capability
的 `allowed_tools` 必须与 bundle 的 `tool_payload_hashes` key 集合完全相等；缺少、额外或
hash 不匹配均拒绝签发。该集合必须非空并严格来自上述封闭 `AgentToolId`；角色矩阵中
没有列出的组合无法通过类型/manifest 生成器获得 capability。
`AgentExecutionStageId` 必须恰有 29 个成员：非 CIO Agent 的 `stage` 必须与自身
`agent_id` 相等，CIO 只能绑定 `cio_proposal/cio_final`；bundle/capability 的 Agent、stage
交叉错配在签发前拒绝，`snapshot_bundle_hash` 必须覆盖 stage，不能用自由字符串增加
隐形阶段或让 proposal bundle 冒充 final bundle。

签名覆盖 canonical manifest 的全部字段；私钥只在 runtime，模型只获得 out-of-band
capability handle，不能修改 manifest。bridge 服务端必须校验 key ID/signature、
graph/run slot/run/node/agent/stage、`issued_at/expires_at`、nonce、候选域 hash 和 snapshot bundle hash；
`tools.list` 只返回该 capability 的工具，`tools.call` 没有匹配 capability 时拒绝。
服务端从 bundle 返回已物化 payload，不在 `tools.call` 中重新采集。使用账本以
`(capability_id, tool_id)` 原子记录一次成功调用；同一节点可各调用每个获准工具一次，
但跨节点、跨 session、重复 tool call 或已终结 capability 的 replay 必须拒绝。bundle、
capability 和使用账本均 append-only 留审计；节点结束后 capability 立即终结，即使尚未过期。
只在 prompt 中写 whitelist 不构成权限控制。原始 Tushare/Eurostat/ECB/ALFRED/官方目录
client、任意 ticker 工具和 collector handler 永远不能注册为 model-callable tool。

标准 Sector 的三次可能模型调用仍只算一个 Agent 执行阶段，但工具能力必须进一步收口：
只有 `DIRECTION_RESEARCH` 可获得本节 Sector 工具表对应的 capability；该 subcall 完成后
capability 立即终结。`CONFLICT_REVIEW` 只接收 runtime 从同一 root bundle 投影出的冻结冲突
pair，`FINAL_SELECTION` 只接收净化 directive、scoring shortlist 和冻结 Macro 输入；后二者
不得获得任何 tool capability，也不得复用/重放第一阶段 handle。它们不是新的
`AgentExecutionStageId`，不增加 29-stage 计数。runtime 投影必须引用同一 root bundle
ID/hash，不能为了取消工具而重新采集或热更新数据。

Macro 工具合同：

| Agent | 唯一 model-callable tool | runtime 注入 | 明确禁止 |
| --- | --- | --- | --- |
| `china` | `get_china_macro_snapshot()` | 无 | 其他角色 snapshot、原始数据工具 |
| `us_economy` | `get_us_macro_snapshot()` | 无 | Fed/曲线/美元工具 |
| `eu_economy` | `get_eu_macro_snapshot()` | 无 | ECB/欧元/曲线工具 |
| `central_bank` | `get_central_bank_snapshot()` | 无 | `china` LLM 输出、Fed/ECB snapshot |
| `us_financial_conditions` | `get_us_financial_conditions_snapshot()` | 无 | 任意独立美元/收益率/波动工具 |
| `euro_area_financial_conditions` | `get_euro_area_financial_conditions_snapshot()` | 无 | 非欧元区央行/市场工具 |
| `commodities` | `get_commodity_conditions_snapshot()` | 无 | 任意合约代码查询、新闻搜索 |
| `geopolitical` | `get_geopolitical_events_snapshot()` | 无 | Tushare 新闻、OpenCLI、搜索引擎 |
| `market_breadth` | `get_market_breadth_snapshot()` | 无 | 新闻、资金流、波动率工具 |
| `institutional_flow` | `get_market_positioning_snapshot()` | 无 | 新闻和抽样个股替代全市场工具 |

Sector 工具合同：

| Agent | 唯一 model-callable tool | 可附加事件工具 | runtime 注入 |
| --- | --- | --- | --- |
| `semiconductor` | `get_sector_research_snapshot()` | `get_role_event_snapshot()` | 十个 accepted Macro、冻结半导体候选域 |
| `technology` | `get_sector_research_snapshot()` | `get_role_event_snapshot()` | 十个 accepted Macro、冻结非半导体科技候选域 |
| `energy` | `get_sector_research_snapshot()` | `get_role_event_snapshot()` | 十个 accepted Macro、冻结能源候选域 |
| `biotech` | `get_sector_research_snapshot()` | 无 | 十个 accepted Macro、冻结医药生物候选域 |
| `consumer` | `get_sector_research_snapshot()` | `get_role_event_snapshot()` | 十个 accepted Macro、冻结消费候选域 |
| `industrials` | `get_sector_research_snapshot()` | `get_role_event_snapshot()` | 十个 accepted Macro、冻结工业候选域 |
| `real_estate_construction` | `get_sector_research_snapshot()` | `get_role_event_snapshot()` | 十个 accepted Macro、冻结地产建筑候选域 |
| `financials` | `get_sector_research_snapshot()` | `get_role_event_snapshot()` | 十个 accepted Macro、冻结金融候选域 |
| `agriculture` | `get_sector_research_snapshot()` | `get_role_event_snapshot()` | 十个 accepted Macro、冻结农业候选域 |
| `relationship_mapper` | `get_relationship_graph_snapshot()` | 无 | 十个 accepted Macro、九个标准 Sector 的冻结候选域 |

`get_sector_research_snapshot()` 虽同名，但由 capability 中的 `agent_id` 选择固定 sector
schema、候选域和 source projection；模型不能传 sector/ticker。旧的
`get_industry_policy_digest` 不再是 required 工具：官方政策目录在 collector 层进入相应
sector snapshot，cutover 后删除其 prompt/whitelist/bridge 引用。它不存在时不得产生
“工具缺失后继续运行”的隐式降级。

Superinvestor 工具合同：

| Agent | 唯一 model-callable tool | runtime 注入 | 范围 |
| --- | --- | --- | --- |
| `druckenmiller` | `get_superinvestor_candidate_snapshot()` | Macro、Sector accepted 输出 | 冻结 Layer-2 accepted 候选域 |
| `munger` | `get_superinvestor_candidate_snapshot()` | Macro、Sector accepted 输出 | 冻结 Layer-2 accepted 候选域 |
| `burry` | `get_superinvestor_candidate_snapshot()` | 同上 | 同上 |
| `ackman` | `get_superinvestor_candidate_snapshot()` | 同上 | 同上 |

同一底层 PIT 数据按四种已注册哲学生成确定性视图，但四个 Agent 均不能请求候选域外证券、
事件流、行业政策或 RKE。候选域为空时不得调用模型或伪造 abstention accepted output，
runtime 必须从同一冻结机会集与 eligibility audit 生成唯一
`NoEvaluationObjectStageSkipRecord`；只有非空候选域上的主动不选才是
`NO_QUALIFIED_CANDIDATES`。快照缺 required 分支则阶段拒绝，不能让模型自行搜索补齐。

Decision 工具合同：

| Agent | model-callable tools | runtime 注入 | 失败语义 |
| --- | --- | --- | --- |
| `alpha_discovery` | `get_alpha_candidate_snapshot()`、`get_role_event_snapshot()` | required 上游 slot（accepted output 或获准 Superinvestor stage skip）、生效中的静态风险/资格约束，以及 Layer-3 未选且满足 novel 资格的冻结候选域 | 不得引入候选域外证券或读取同轮尚未生成的 CRO output；required market/fundamental/catalyst 分支缺失即拒绝 |
| `cro` | `get_cro_risk_snapshot()`、`get_role_event_snapshot()` | `AcceptedCioProposal`、其冻结的完整 pre-CRO 目标组合和 required 上游 lineage | 中国风险状态、持仓、相关性、流动性或约束任一 required 分支缺失即拒绝 |
| `autonomous_execution` | `get_execution_snapshot()`、`get_role_event_snapshot()` | CIO frozen order intents、CRO accepted control 或无对象 stage-skip | 无可证实时 quote/OMS 时只允许 deterministic paper 模式；真实执行直接拒绝 |
| `cio` | `get_cio_decision_snapshot()` | proposal phase：required 上游、Alpha accepted/skip、持仓/现金/约束；final phase：字节相同的 pre-CIO 上游/Macro source-layer snapshot、同一 frozen proposal、CRO accepted/skip、Execution accepted/skip | 任一 required ledger/constraint/upstream/source snapshot 不一致，或 final 直接重选 Alpha/上游候选即拒绝 |

`cio` 不读取新闻或任意原始市场工具；`autonomous_execution` 不读取十个 Macro 快照。
Decision runtime 必须按
`alpha_discovery -> cio(PROPOSAL) -> cro -> autonomous_execution -> cio(FINAL)`
签发 capability；阶段输入若引用未来阶段、旧 run 或不同 proposal hash 必须在模型调用前拒绝。
所有 runtime input 都保存 `input_snapshot_hash`，同一阶段重试必须得到完全相同的输入；
若上游变更则创建新 run/stage attempt，而不是在模型调用中热更新。

工具出现在 whitelist 不等于可忽略其覆盖状态：每个 Macro 的唯一 snapshot 是 required；
标准 Sector 的 `get_role_event_snapshot()` 是 optional context，覆盖不可用时仍可分析固定
行业数据，但不得声明“无事件”或引用该日历事件作为催化。其 coverage 状态必须由 runtime 注入
comparison card：`AVAILABLE_MATERIAL_EVENTS` 允许 `MACRO_EVENT_FIT` 正常投票，
`COVERAGE_CONFIRMED_NO_MATERIAL_EVENT` 只允许该项 `NEUTRAL`，
`SOURCE_UNAVAILABLE` 则该项固定 `NO_VOTE`；后者不使 Sector readiness 失败，也不能被当成
负面票；其中保留的部分 material projections 也只能作为不计票的风险上下文。`CATALYSTS`
始终读取独立的 `SectorCatalystCoverageSummary`，不随
`get_role_event_snapshot()` 调用或财经日历状态改变。CRO、Alpha 和 Execution 的角色事件投影
分别是风险、催化和执行时点的 required coverage branch，只有
`coverage_completeness=COMPLETE` 才可运行；`SOURCE_UNAVAILABLE` 时无论是否观察到部分事件
都必须拒绝。
健康覆盖下的无 material 事件状态是合法
`COVERAGE_CONFIRMED_NO_MATERIAL_EVENT`，不等于工具失败。

#### 6.1.2 Sector、Relationship 与 Superinvestor 数据合同

标准 Sector 的证券域只使用申万 2021 分类，不再在运行时从“申万/中信/其他官方分类”中
任选。Tushare `index_classify(src=SW2021)+index_member_all` 的申万 2021 分类/分级成分通过 preflight 后
生成唯一可编辑的
`SECTOR_UNIVERSE_REGISTRY`；代码中不得维护第二份行业列表：

```ts
type StandardSectorAgentId =
  | "semiconductor"
  | "technology"
  | "energy"
  | "biotech"
  | "consumer"
  | "industrials"
  | "real_estate_construction"
  | "financials"
  | "agriculture";

interface SectorMembershipQueryBranch {
  endpoint: "index_member_all";
  parameter: "l1_code" | "l2_code" | "l3_code";
  classification_code: string;
  is_new: "Y" | "N";
}

interface SectorMembershipQueryPlan {
  query_plan_id: string;
  query_plan_version: string;
  query_plan_hash: string;
  sector_agent_id: StandardSectorAgentId;
  branches: SectorMembershipQueryBranch[];
  merge_key: readonly [
    "l1_code",
    "l2_code",
    "l3_code",
    "ts_code",
    "in_date",
    "out_date",
  ];
  post_filter_excluded_codes: string[];
}

interface FrozenPeerBasketEntry {
  basket_registry_id: string;
  ts_code: string;
  valid_from: string;
  valid_to: string | null;
  known_at: string;
  source_evidence_id: string;
}

interface FrozenPeerBasketRegistry {
  basket_registry_id: string;
  basket_registry_version: string;
  basket_registry_hash: string;
  weighting: "PIT_EQUAL_WEIGHT";
  entries: FrozenPeerBasketEntry[];
}

type SectorBenchmarkUniverseQueryPlan =
  | {
      query_kind: "SW2021_MEMBERSHIP";
      query_plan_id: string;
      query_plan_version: string;
      query_plan_hash: string;
      membership_query_plan_id: string;
      membership_query_plan_hash: string;
    }
  | {
      query_kind: "DIRECTION_PARTITION_PIT";
      query_plan_id: string;
      query_plan_version: string;
      query_plan_hash: string;
      direction_id: string;
      direction_partition_definition_hash: string;
      membership_query_plan_id: string;
      membership_query_plan_hash: string;
      partition_transform:
        "INTERSECT_INCLUDED_CODES_MINUS_EXCLUDED_CODES";
    }
  | {
      query_kind: "REGISTERED_INDEX_PIT";
      query_plan_id: string;
      query_plan_version: string;
      query_plan_hash: string;
      endpoint: "index_weight";
      index_code: string;
      constituent_code_field: "con_code";
      effective_date_field: "trade_date";
      first_known_at_field: "first_seen_at";
      post_filter_excluded_direction_ids: string[];
      valid_from: string;
      valid_to: string | null;
    }
  | {
      query_kind: "FROZEN_PEER_BASKET";
      query_plan_id: string;
      query_plan_version: string;
      query_plan_hash: string;
      basket_registry_id: string;
      basket_registry_hash: string;
      constituent_valid_interval_fields: readonly ["valid_from", "valid_to"];
      constituent_known_at_field: "known_at";
      post_filter_excluded_direction_ids: string[];
      valid_from: string;
      valid_to: string | null;
    };

interface SectorFlowCoverageContract {
  contract_id: string;
  contract_version: string;
  contract_hash: string;
  source_endpoint: "moneyflow";
  source_net_flow_field: "net_mf_amount";
  denominator: "FROZEN_CANDIDATE_20D_MEDIAN_TURNOVER";
  minimum_coverage_ratio: 0.9;
  coverage_weighting: "PIT_CONSTITUENT_20D_MEDIAN_TURNOVER";
  aggregation: "OBSERVED_CONSTITUENT_NET_FLOW_PER_OBSERVED_MEDIAN_TURNOVER";
  ths_industry_flow_usage: "OPTIONAL_DIAGNOSTIC_ONLY";
}

interface SectorBenchmarkContractBase {
  benchmark_contract_id: string;
  benchmark_contract_version: string;
  benchmark_contract_hash: string;
  universe_query_plan_id: string;
  universe_query_plan_hash: string;
  weighting: "PIT_EQUAL_WEIGHT";
  return_field: "TOTAL_RETURN_ADJUSTED";
  snapshot_return_semantics: "TRAILING_CLOSE_TO_CLOSE";
  outcome_entry_semantics: "T_PLUS_1_OPEN_TO_HORIZON_CLOSE";
  valid_from: string;
  valid_to: string | null;
}

type SectorBenchmarkContract =
  | (SectorBenchmarkContractBase & {
      benchmark_role: "DIRECTION_RETURN";
      universe_query_kind: "DIRECTION_PARTITION_PIT";
      bound_direction_id: string;
      required_disjoint_direction_id: null;
    })
  | (SectorBenchmarkContractBase & {
      benchmark_role: "PARENT_SECTOR";
      universe_query_kind: "SW2021_MEMBERSHIP";
      bound_direction_id: null;
      required_disjoint_direction_id: null;
    })
  | (SectorBenchmarkContractBase & {
      benchmark_role: "SINGLE_DIRECTION_NULL";
      universe_query_kind: "REGISTERED_INDEX_PIT" | "FROZEN_PEER_BASKET";
      bound_direction_id: null;
      required_disjoint_direction_id: string;
    });

interface SectorDirectionContract {
  direction_id: string;
  direction_contract_version: string;
  direction_contract_hash: string;
  sector_agent_id: StandardSectorAgentId;
  included_classification_codes: string[];
  excluded_classification_codes: string[];
  direction_partition_definition_hash: string;
  direction_return_benchmark_contract_id: string;
  parent_sector_benchmark_contract_id: string;
  single_direction_null_benchmark_contract_id: string | null;
  candidate_eligibility_contract_version: string;
}

interface SectorTrackedIndexContract {
  tracked_index_code: string;
  tracked_index_contract_version: string;
  tracked_index_contract_hash: string;
  direction_id: string;
  direction_partition_definition_hash: string;
  constituent_source: "INDEX_WEIGHT_PIT";
  constituent_effective_date_field: "trade_date";
  constituent_first_known_at_field: "first_seen_at";
  exact_match_rule:
    "PIT_CONSTITUENT_SET_EQUALS_DIRECTION_PARTITION_UNIVERSE";
  valid_from: string;
  valid_to: string | null;
}

interface SectorDirectionEtfMapEntryBase {
  map_entry_id: string;
  map_contract_version: string;
  map_entry_hash: string;
  direction_id: string;
  etf_ts_code: string;
  valid_from: string;
  valid_to: string | null;
  mapping_evidence_id: string;
}

type SectorDirectionEtfMapEntry =
  | (SectorDirectionEtfMapEntryBase & {
      mapping_basis: "TRACKED_INDEX_EXACT";
      tracked_index_code: string;
      tracked_index_contract_version: string;
      tracked_index_contract_hash: string;
      tracked_index_direction_match_hash: string;
      holdings_disclosure_published_at: null;
      holdings_disclosure_effective_at: null;
      verified_direction_exposure: null;
      verified_holdings_coverage_ratio: null;
      minimum_direction_exposure: null;
      minimum_holdings_coverage_ratio: null;
      maximum_holdings_age_calendar_days: null;
      mapping_refresh_interval_days: null;
    })
  | (SectorDirectionEtfMapEntryBase & {
      mapping_basis: "HOLDINGS_EXPOSURE_VERIFIED";
      tracked_index_code: null;
      tracked_index_contract_version: null;
      tracked_index_contract_hash: null;
      tracked_index_direction_match_hash: null;
      holdings_disclosure_published_at: string;
      holdings_disclosure_effective_at: string;
      verified_direction_exposure: number;
      verified_holdings_coverage_ratio: number;
      minimum_direction_exposure: 0.8;
      minimum_holdings_coverage_ratio: 0.9;
      maximum_holdings_age_calendar_days: 120;
      mapping_refresh_interval_days: 30;
    });

interface SectorDirectionComparisonContract {
  comparison_contract_id: string;
  comparison_contract_version: string;
  comparison_contract_hash: string;
  core_criteria: readonly [
    "FUNDAMENTALS",
    "VALUATION",
    "BASKET_TECHNICALS",
    "RISK_ASYMMETRY",
  ];
  coverage_gated_criteria: readonly [
    "MACRO_EVENT_FIT",
    "CATALYSTS",
  ];
  optional_etf_criteria: readonly [
    "ETF_PRICE_CONFIRMATION",
    "ETF_SHARE_FLOW_CONFIRMATION",
  ];
  pair_coverage: "ALL_ELIGIBLE_UNORDERED_PAIRS";
  reducer: "CONDORCET_THEN_SINGLE_CONFLICT_REVIEW_ELSE_ABSTAIN";
  pair_resolution:
    "BASE_ONE_OPTIONAL_ETF_HALF_MIN_BASE_TWO_WEIGHTED_MARGIN_ONE";
  optional_etf_resolution_effect:
    "HALF_WEIGHT_SUPPLEMENTAL_WHEN_BOTH_SIDES_COMPARABLE";
  core_vote_weight: 1;
  available_coverage_gated_vote_weight: 1;
  optional_etf_vote_weight: 0.5;
  unavailable_coverage_gated_effect: "NO_VOTE";
  confirmed_no_event_result: "COMPARABLE_NEUTRAL";
  source_unavailable_result: "UNAVAILABLE_NO_VOTE";
  minimum_base_support_count: 2;
  minimum_weighted_support_margin: 1;
  edge_semantics: "RUNTIME_A_OR_B_OR_NO_CLEAR_WINNER_NO_EDGE";
  winner_rule: "OUTDEGREE_EQUALS_N_MINUS_1";
  loser_rule: "INDEGREE_EQUALS_N_MINUS_1";
  copeland_rule: "OUTDEGREE_MINUS_INDEGREE";
  conflict_set_rule:
    "SCC_GT1_UNION_NO_EDGE_ENDPOINTS_UNION_TIED_COPELAND_EXTREMES";
  maximum_conflict_review_rounds: 1;
  conflict_review_scope: "ALL_UNORDERED_PAIRS_WITHIN_CONFLICT_SET";
  unresolved_rule: "ABSTAIN_CORRESPONDING_SELECTION_LEG";
  least_preferred_qualification:
    "UNIQUE_WINNER_AND_LOSER_WITH_VERIFIABLE_NON_ETF_VOTING_EVIDENCE";
}

interface SingleDirectionQualificationContract {
  qualification_contract_id: string;
  qualification_contract_version: string;
  qualification_contract_hash: string;
  comparison_contract_id: string;
  comparison_contract_hash: string;
  comparison_target:
    "ONLY_ELIGIBLE_DIRECTION_VS_REGISTERED_SINGLE_DIRECTION_NULL";
  criterion_set: "SAME_AS_SECTOR_DIRECTION_COMPARISON_CONTRACT";
  pair_resolution:
    "BASE_ONE_OPTIONAL_ETF_HALF_MIN_BASE_TWO_WEIGHTED_MARGIN_ONE";
  minimum_base_support_count: 2;
  minimum_weighted_support_margin: 1;
  qualified_rule:
    "DIRECTION_MEETS_MIN_BASE_AND_WEIGHTED_MARGIN_AGAINST_NULL";
  not_qualified_rule: "NO_QUALIFIED_DIRECTION";
}

interface SectorSecurityScoringContract {
  scoring_contract_id: string;
  scoring_contract_version: string;
  scoring_contract_hash: string;
  candidate_source: "PIT_DIRECTION_ELIGIBLE_SECURITIES";
  shortlist_order:
    "LAGGED_20D_MEDIAN_AMOUNT_DESC_THEN_TS_CODE_ASC";
  shortlist_maximum_size_per_direction: 50;
  model_pick_domain: "EXACT_FROZEN_SCORING_SHORTLIST";
  maximum_picks_per_side: 5;
  duplicate_ticker_policy: "REJECT_ACROSS_WHOLE_SUBMISSION";
  conviction_lower_bound_exclusive: 0;
  conviction_upper_bound_inclusive: 1;
  conviction_budget_per_side: 1;
}

interface FrozenSectorSecurityScoringShortlist {
  shortlist_id: string;
  shortlist_hash: string;
  run_id: string;
  as_of: string;
  sector_agent_id: StandardSectorAgentId;
  direction_id: string;
  scoring_contract_id: string;
  scoring_contract_version: string;
  scoring_contract_hash: string;
  candidate_universe_hash: string;
  ordered_ts_codes: string[];
  generated_before_agent_call: true;
}

interface SectorUniverseContract {
  sector_agent_id: StandardSectorAgentId;
  contract_version: string;
  included_classification_codes: string[];
  excluded_classification_codes: string[];
  membership_query_plan_id: string;
  membership_query_plan_hash: string;
  sector_flow_coverage_contract_id: string;
  sector_flow_coverage_contract_version: string;
  sector_flow_coverage_contract_hash: string;
  direction_comparison_contract_id: string;
  direction_comparison_contract_version: string;
  direction_comparison_contract_hash: string;
  security_scoring_contract_id: string;
  security_scoring_contract_version: string;
  security_scoring_contract_hash: string;
  candidate_eligibility_contract_version: string;
}

interface SectorUniverseManifest {
  manifest_version: string;
  manifest_hash: string;
  taxonomy_provider: "SW2021";
  taxonomy_structure_hash: string;
  benchmark_registry_version: string;
  benchmark_registry_hash: string;
  direction_metric_registry_version: string;
  direction_metric_registry_hash: string;
  overlap_precedence: readonly StandardSectorAgentId[];
  sector_contracts: SectorUniverseContract[];
  membership_query_plans: SectorMembershipQueryPlan[];
  peer_basket_registries: FrozenPeerBasketRegistry[];
  benchmark_universe_query_plans: SectorBenchmarkUniverseQueryPlan[];
  benchmark_contracts: SectorBenchmarkContract[];
  direction_contracts: SectorDirectionContract[];
  tracked_index_contracts: SectorTrackedIndexContract[];
  direction_etf_map: SectorDirectionEtfMapEntry[];
  direction_comparison_contract: SectorDirectionComparisonContract;
  single_direction_qualification_contract:
    SingleDirectionQualificationContract;
  security_scoring_contract: SectorSecurityScoringContract;
  opportunity_search_calibration_contract:
    SectorOpportunitySearchCalibrationContract;
  inference_budget_contract: SectorInferenceBudgetContract;
  knot_research_score_contract_id: string;
  knot_research_score_contract_version: string;
  knot_research_score_contract_hash: string;
  flow_coverage_contract: SectorFlowCoverageContract;
}
```

初始 exact-code 范围固定如下。本节 universe 与 direction 两张表合计引用的 44 个唯一
SW2021 code 已于 2026-07-16 通过 Tushare `index_classify(src=SW2021)` 非空 metadata
响应核对：

| Sector | SW2021 codes（`index_member_all` 参数） |
| --- | --- |
| `semiconductor` | L2 `801081.SI`（半导体） |
| `technology` | L1 `801080.SI`（电子）剔除 L2 `801081.SI`（半导体）；L1 `801750.SI`（计算机）、L1 `801760.SI`（传媒）、L1 `801770.SI`（通信） |
| `energy` | L1 `801950.SI`（煤炭）、L1 `801960.SI`（石油石化）、L2 `801161.SI`（电力）、L2 `801735.SI`（光伏设备）、L2 `801736.SI`（风电设备）、L2 `801737.SI`（电池，含储能产业链传导） |
| `biotech` | L1 `801150.SI`（医药生物） |
| `consumer` | L1 `801110.SI`、`801120.SI`、`801130.SI`、`801140.SI`、`801200.SI`、`801210.SI`、`801980.SI`、`801880.SI`（家用电器、食品饮料、纺织服饰、轻工制造、商贸零售、社会服务、美容护理、汽车） |
| `industrials` | L1 `801030.SI`、`801040.SI`、`801050.SI`、`801890.SI`、`801740.SI`、L2 `801731.SI`、`801733.SI`、`801738.SI`、L1 `801170.SI`、`801970.SI`（基础化工、钢铁/黑色金属、有色金属、机械设备、国防军工、电机、其他电源设备、电网设备、交通运输、环保） |
| `real_estate_construction` | L1 `801180.SI`、`801710.SI`、`801720.SI`（房地产、建筑材料、建筑装饰） |
| `financials` | L1 `801780.SI`、`801790.SI`（银行、非银金融） |
| `agriculture` | L1 `801010.SI`（农林牧渔） |

同一 exact universe 再确定性划分为以下可选方向；方向可以包含多个高度同因果的行业代码，
但每个有效证券在同一 Sector 内只能属于一个方向：

| Sector | 初始 `direction_id` → SW2021 范围 |
| --- | --- |
| `semiconductor` | `semiconductor_core` → `801081.SI` |
| `technology` | `electronics_non_semiconductor` → `801080.SI` 排除 `801081.SI`；`computer` → `801750.SI`；`media` → `801760.SI`；`communications` → `801770.SI` |
| `energy` | `coal` → `801950.SI`；`oil_gas` → `801960.SI`；`electric_power` → `801161.SI`；`solar` → `801735.SI`；`wind` → `801736.SI`；`battery_storage` → `801737.SI` |
| `biotech` | `medicine_biotech` → `801150.SI` |
| `consumer` | `home_appliances` → `801110.SI`；`food_beverage` → `801120.SI`；`textiles_apparel` → `801130.SI`；`light_manufacturing` → `801140.SI`；`retail` → `801200.SI`；`consumer_services` → `801210.SI`；`beauty_care` → `801980.SI`；`automobiles` → `801880.SI` |
| `industrials` | `basic_chemicals` → `801030.SI`；`steel` → `801040.SI`；`nonferrous_metals` → `801050.SI`；`machinery` → `801890.SI`；`defense` → `801740.SI`；`electrical_equipment_ex_renewables` → `801731.SI+801733.SI+801738.SI`（电机、其他电源设备和电网设备，明确排除光伏/风电/电池）；`transportation` → `801170.SI`；`environmental` → `801970.SI` |
| `real_estate_construction` | `real_estate` → `801180.SI`；`building_materials` → `801710.SI`；`construction_decoration` → `801720.SI` |
| `financials` | `banking` → `801780.SI`；`non_bank_finance` → `801790.SI` |
| `agriculture` | `crop_seed` → `801016.SI`（种植业，含种业）；`livestock_aquaculture` → `801017.SI+801015.SI`（养殖业、渔业）；`feed_animal_health` → `801014.SI+801018.SI`（饲料、动物保健Ⅱ）；`forestry_processing_services` → `801011.SI+801012.SI+801019.SI`（林业Ⅱ、农产品加工、农业综合Ⅱ） |

上述八个农业 L2 code 已于 2026-07-16 通过
`index_classify(level=L2,src=SW2021,parent_code=110000)` 和
`index_member_all(l1_code=801010.SI)` 非空响应核对，四个方向不是 prose 分类或未来可选项。
实现仍须把 literal code 数组、provider metadata hash 和 PIT coverage fixture 写入唯一
TypeScript registry，并验证八个 L2 分区无重叠且完整覆盖 `801010.SI` 的历史/当前有效成员；
`is_pub=0` 的 `801011.SI/801019.SI` 不能因此被删除，必须按 `in_date/out_date` 保留其有效期。
上述 registry 与 coverage fixture 未验收前，`agriculture` 与全 roster 均不得 READY。
禁止以 `agriculture_total` 单方向临时上线。

每个 `SectorDirectionContract` 的 codes/exclusions 必须是所属 `SectorUniverseContract` 的
子集；同一 Sector 的全部方向须无重叠并完整覆盖其 exact universe，单方向 Sector 允许该
唯一方向等于完整 Sector universe。方向 benchmark、
候选资格、PIT 成分和有效区间全部由 registry 冻结。增加、合并或拆分 direction ID 属于
output/outcome 行为合同变更，必须创建新 execution/KNOT/Darwinian track，不能让模型在
运行时用新闻主题临时组篮子。只有一个方向的 Sector 必须另行注册非同一成分的 A 股宽基/
同层 peer null benchmark，禁止用方向自身减自身产生恒零评价。每个方向都必须同时解析到
自身 return benchmark 和所属完整 Sector benchmark；只有一个 eligible direction 时
`single_direction_null_benchmark_contract_id` 必须非空，多方向时必须为 `null`。运行时重算
三类 benchmark 的 PIT universe hash，并拒绝 single-direction null 与方向自身或 parent
Sector 使用相同成分集合。

每个 benchmark 的 `universe_query_plan_id/hash` 必须解析到 manifest 中唯一且
`universe_query_kind` 一致的 tagged query plan。direction return 只能使用
`DIRECTION_PARTITION_PIT`：先按所属 Sector 的 `SW2021_MEMBERSHIP` 重放当日 PIT universe，
再按 `SectorDirectionContract.included/excluded_classification_codes` 做固定
`INTERSECT_INCLUDED_CODES_MINUS_EXCLUDED_CODES` 分区。query plan 的 `direction_id`、
`direction_partition_definition_hash`、membership plan ID/hash 必须与 direction contract
逐字段相等；benchmark 的 `bound_direction_id` 也必须等于被评价方向。parent Sector 只能
使用所属完整 Sector 的 `SW2021_MEMBERSHIP` 且 `bound_direction_id=null`。
single-direction null 只能使用
`REGISTERED_INDEX_PIT` 或 `FROZEN_PEER_BASKET`，不能复用绑定单一 Sector 的
membership plan。注册指数逐期保存 constituent effective date 和本地首次可见时间；peer
basket 的每个成分必须同时满足 `known_at<=as_of` 与有效区间。single-direction null 的
`required_disjoint_direction_id` 必须等于被评价 direction，query plan 的
`post_filter_excluded_direction_ids` 必须包含且只包含该 ID，并在每个历史日期先按当日 PIT
direction universe 排除重叠证券后再计算 benchmark；其 `bound_direction_id=null`。其他
benchmark 的 `required_disjoint_direction_id/post_filter_excluded_direction_ids` 分别为
`null/[]`。任一 query plan 无法 PIT
重放、内容 hash 不符、成分为空、与 direction/parent 重叠超过 scoring contract 允许的零
容忍度，或使用今天的指数/peer 成分回填历史时，single-direction evaluation 失败关闭。
snapshot 比较卡只使用 `TRAILING_CLOSE_TO_CLOSE`；五日 outcome 只使用
`T_PLUS_1_OPEN_TO_HORIZON_CLOSE`。两种 return semantics 共用 universe/复权合同但不得
混用价格端点或从 outcome 窗口回填 snapshot 指标。

每个 direction 的 broad candidate domain 在模型调用前按
`SectorSecurityScoringContract` 过滤，并以截至 `as_of` 的前 20 日 median amount 降序、
`ts_code` 升序确定性截断为至多 50 只，生成
`FrozenSectorSecurityScoringShortlist`。comparison、final directive、accepted picks 和
outcome security denominator 必须引用同一 shortlist ID/hash；模型只能从其中选取每侧至多
五只，不能从 broad candidate domain 补选。shortlist 合法为空时对应 security status 可为
`NO_QUALIFIED_SECURITY`；数据失败、hash 不一致或运行后重建 shortlist 不是合法空集合。

运行时为每个 eligible direction 生成同构比较卡，LLM 不自行计算技术指标：

```ts
type DirectionComparisonMetricId =
  | "REVENUE_GROWTH_TTM_YOY"
  | "OPERATING_CASHFLOW_MARGIN_TTM"
  | "EARNINGS_YIELD_TTM"
  | "BOOK_TO_PRICE_LF"
  | "RELATIVE_TOTAL_RETURN_5D"
  | "RELATIVE_TOTAL_RETURN_20D"
  | "RELATIVE_TOTAL_RETURN_60D"
  | "ABOVE_MA20_PCT"
  | "ABOVE_MA60_PCT"
  | "NEW_HIGH_LOW_20D_BALANCE"
  | "TURNOVER_EXPANSION_20D_PCT"
  | "REALIZED_VOLATILITY_60D"
  | "CURRENT_DRAWDOWN_252D"
  | "ETF_RELATIVE_RETURN_5D"
  | "ETF_RELATIVE_RETURN_20D"
  | "ETF_RELATIVE_RETURN_60D"
  | "ETF_ABOVE_MA20"
  | "ETF_ABOVE_MA60"
  | "ETF_TURNOVER_EXPANSION_20D"
  | "ETF_SHARE_CHANGE_1D"
  | "ETF_SHARE_CHANGE_5D"
  | "ETF_SHARE_CHANGE_20D"
  | "ETF_ESTIMATED_CREATION_REDEMPTION_1D"
  | "ETF_ESTIMATED_CREATION_REDEMPTION_5D"
  | "ETF_ESTIMATED_CREATION_REDEMPTION_20D"
  | "ETF_PREMIUM_DISCOUNT";

type SectorDirectionMetricFormulaId =
  | "PIT_REVENUE_GROWTH_TTM_YOY_EQUAL_WEIGHT"
  | "PIT_OPERATING_CASHFLOW_MARGIN_TTM_EQUAL_WEIGHT"
  | "PIT_EARNINGS_YIELD_TTM_EQUAL_WEIGHT"
  | "PIT_BOOK_TO_PRICE_LF_EQUAL_WEIGHT"
  | "PIT_BASKET_RELATIVE_TOTAL_RETURN"
  | "PIT_CONSTITUENT_ABOVE_MOVING_AVERAGE_PCT"
  | "PIT_NEW_HIGH_LOW_BALANCE"
  | "PIT_TURNOVER_EXPANSION_PCT"
  | "PIT_BASKET_REALIZED_VOLATILITY"
  | "PIT_BASKET_CURRENT_DRAWDOWN"
  | "PIT_ETF_FAMILY_RELATIVE_TOTAL_RETURN"
  | "PIT_ETF_FAMILY_ABOVE_MOVING_AVERAGE"
  | "PIT_ETF_FAMILY_TURNOVER_EXPANSION"
  | "PIT_ETF_FAMILY_SHARE_CHANGE"
  | "PIT_ETF_FAMILY_ESTIMATED_CREATION_REDEMPTION"
  | "PIT_ETF_FAMILY_PREMIUM_DISCOUNT";

type SectorDirectionMetricLookback =
  | {
      kind: "TRADING_DAYS";
      value: 1 | 5 | 20 | 60 | 252;
    }
  | {
      kind: "REPORTED_QUARTERS";
      value: 4 | 8;
    }
  | {
      kind: "POINT_IN_TIME";
      value: 1;
    };

interface SectorDirectionMetricContract {
  metric_id: DirectionComparisonMetricId;
  metric_contract_version: string;
  metric_contract_hash: string;
  metric_family:
    | "FUNDAMENTALS"
    | "VALUATION"
    | "BASKET_PRICE_TREND"
    | "BASKET_BREADTH"
    | "BASKET_TURNOVER_FLOW"
    | "ETF_CONFIRMATION";
  formula_id: SectorDirectionMetricFormulaId;
  formula_version: "v1";
  unit: "RATIO" | "PERCENT" | "CNY" | "RETURN" | "VOLATILITY";
  lookback: SectorDirectionMetricLookback;
  required_for_direction_readiness: boolean;
  minimum_observations: number;
  minimum_coverage_ratio: number;
  basket_weighting:
    | "PIT_EQUAL_WEIGHT"
    | "LAGGED_20D_MEDIAN_AMOUNT";
  benchmark_role:
    | "NONE"
    | "DIRECTION_RETURN_BENCHMARK"
    | "PARENT_SECTOR_BENCHMARK"
    | "DIRECTION_BASKET";
  adjustment_contract_version: string;
  percentile_lookback_trading_days: 252;
  percentile_method: "EMPIRICAL_CDF_AVERAGE_TIE";
  change_lookback_trading_days: 20 | null;
}

interface DirectionComparisonMetric {
  metric_id: DirectionComparisonMetricId;
  metric_contract_version: string;
  metric_contract_hash: string;
  lookback: SectorDirectionMetricLookback;
  value: number | null;
  observation_count: number;
  coverage_ratio: number;
  own_history_percentile: number | null;
  own_history_percentile_status:
    | "AVAILABLE"
    | "INSUFFICIENT_HISTORY"
    | "SOURCE_UNAVAILABLE";
  sector_cross_section_percentile: number | null;
  sector_cross_section_percentile_status:
    | "AVAILABLE"
    | "NOT_APPLICABLE_SINGLE_DIRECTION"
    | "SOURCE_UNAVAILABLE";
  change: number | null;
  status: "AVAILABLE" | "INSUFFICIENT_HISTORY" | "SOURCE_UNAVAILABLE";
  evidence_id: string | null;
}

interface DirectionEtfTechnicalConfirmation {
  status: "AVAILABLE" | "NO_REGISTERED_ETF" | "INSUFFICIENT_HISTORY" | "SOURCE_UNAVAILABLE";
  eligible_etf_ids: string[];
  etf_family_weights_hash: string | null;
  price_trend_metrics: DirectionComparisonMetric[];
  turnover_expansion_metrics: DirectionComparisonMetric[];
  share_change_metrics: DirectionComparisonMetric[];
  estimated_creation_redemption_metrics: DirectionComparisonMetric[];
  premium_discount_metrics: DirectionComparisonMetric[];
}

interface SectorDirectionComparisonCard {
  direction_id: string;
  direction_contract_hash: string;
  direction_universe_hash: string;
  eligibility: "ELIGIBLE" | "REJECTED";
  fundamentals: DirectionComparisonMetric[];
  valuation: DirectionComparisonMetric[];
  basket_price_trend: DirectionComparisonMetric[];
  basket_breadth: DirectionComparisonMetric[];
  basket_turnover_flow: DirectionComparisonMetric[];
  etf_confirmation: DirectionEtfTechnicalConfirmation;
  role_event_snapshot_id: string;
  role_event_snapshot_hash: string;
  role_event_coverage: RoleEventCoverageSummary;
  role_event_projections: AgentEventProjection[];
  sector_catalyst_coverage: SectorCatalystCoverageSummary;
  macro_event_projection_refs: string[];
  catalyst_claim_refs: string[];
  risk_claim_refs: string[];
  deterministic_data_quality: number;
}

interface SingleDirectionNullComparisonCard {
  null_benchmark_contract_id: string;
  null_benchmark_universe_hash: string;
  fundamentals: DirectionComparisonMetric[];
  valuation: DirectionComparisonMetric[];
  basket_price_trend: DirectionComparisonMetric[];
  basket_breadth: DirectionComparisonMetric[];
  basket_turnover_flow: DirectionComparisonMetric[];
  etf_confirmation: DirectionEtfTechnicalConfirmation;
  role_event_snapshot_id: string;
  role_event_snapshot_hash: string;
  role_event_coverage: RoleEventCoverageSummary;
  role_event_projections: AgentEventProjection[];
  sector_catalyst_coverage: SectorCatalystCoverageSummary;
  catalyst_claim_refs: string[];
  deterministic_data_quality: number;
}

interface SingleDirectionQualificationCard {
  direction_card: SectorDirectionComparisonCard;
  null_card: SingleDirectionNullComparisonCard;
  qualification_contract_id: string;
  qualification_contract_hash: string;
}
```

闭集 registry 的 v1 行必须恰好如下；`R/O` 分别表示 required/optional，任何新增、删除或
参数变化都必须发布新的 metric registry、execution behavior 和 outcome track：
实现时这些行必须逐字段写入 TypeScript Zod `as const` registry，下面表格由该 registry
生成并只作计划中的可读冻结清单；runtime 不解析 Markdown，也不允许另写 Python 表。

| metric ID | family / formula ID | lookback | unit | R/O | min obs / coverage | weighting / benchmark |
| --- | --- | --- | --- | --- | --- | --- |
| `REVENUE_GROWTH_TTM_YOY` | FUNDAMENTALS / `PIT_REVENUE_GROWTH_TTM_YOY_EQUAL_WEIGHT` | 8 reported quarters | RATIO | R | 8 / 0.90 | PIT equal / NONE |
| `OPERATING_CASHFLOW_MARGIN_TTM` | FUNDAMENTALS / `PIT_OPERATING_CASHFLOW_MARGIN_TTM_EQUAL_WEIGHT` | 4 reported quarters | RATIO | R | 4 / 0.90 | PIT equal / NONE |
| `EARNINGS_YIELD_TTM` | VALUATION / `PIT_EARNINGS_YIELD_TTM_EQUAL_WEIGHT` | point in time | RATIO | R | 1 / 0.90 | PIT equal / NONE |
| `BOOK_TO_PRICE_LF` | VALUATION / `PIT_BOOK_TO_PRICE_LF_EQUAL_WEIGHT` | point in time | RATIO | R | 1 / 0.90 | PIT equal / NONE |
| `RELATIVE_TOTAL_RETURN_5D` | BASKET_PRICE_TREND / `PIT_BASKET_RELATIVE_TOTAL_RETURN` | 5 trading days | RETURN | R | 6 / 0.90 | PIT equal / PARENT_SECTOR_BENCHMARK |
| `RELATIVE_TOTAL_RETURN_20D` | BASKET_PRICE_TREND / `PIT_BASKET_RELATIVE_TOTAL_RETURN` | 20 trading days | RETURN | R | 21 / 0.90 | PIT equal / PARENT_SECTOR_BENCHMARK |
| `RELATIVE_TOTAL_RETURN_60D` | BASKET_PRICE_TREND / `PIT_BASKET_RELATIVE_TOTAL_RETURN` | 60 trading days | RETURN | R | 61 / 0.90 | PIT equal / PARENT_SECTOR_BENCHMARK |
| `ABOVE_MA20_PCT` | BASKET_BREADTH / `PIT_CONSTITUENT_ABOVE_MOVING_AVERAGE_PCT` | 20 trading days | PERCENT | R | 20 / 0.90 | PIT equal / NONE |
| `ABOVE_MA60_PCT` | BASKET_BREADTH / `PIT_CONSTITUENT_ABOVE_MOVING_AVERAGE_PCT` | 60 trading days | PERCENT | R | 60 / 0.90 | PIT equal / NONE |
| `NEW_HIGH_LOW_20D_BALANCE` | BASKET_BREADTH / `PIT_NEW_HIGH_LOW_BALANCE` | 20 trading days | PERCENT | R | 20 / 0.90 | PIT equal / NONE |
| `TURNOVER_EXPANSION_20D_PCT` | BASKET_TURNOVER_FLOW / `PIT_TURNOVER_EXPANSION_PCT` | current + 20 prior trading days | PERCENT | R | 21 / 0.90 | PIT equal / NONE |
| `REALIZED_VOLATILITY_60D` | BASKET_PRICE_TREND / `PIT_BASKET_REALIZED_VOLATILITY` | 60 trading days | VOLATILITY | R | 60 / 0.90 | PIT equal / NONE |
| `CURRENT_DRAWDOWN_252D` | BASKET_PRICE_TREND / `PIT_BASKET_CURRENT_DRAWDOWN` | 252 trading days | RETURN | R | 252 / 0.90 | PIT equal / NONE |
| `ETF_RELATIVE_RETURN_5D` | ETF_CONFIRMATION / `PIT_ETF_FAMILY_RELATIVE_TOTAL_RETURN` | 5 trading days | RETURN | O | 6 / 0.80 | lagged amount / DIRECTION_BASKET |
| `ETF_RELATIVE_RETURN_20D` | ETF_CONFIRMATION / `PIT_ETF_FAMILY_RELATIVE_TOTAL_RETURN` | 20 trading days | RETURN | O | 21 / 0.80 | lagged amount / DIRECTION_BASKET |
| `ETF_RELATIVE_RETURN_60D` | ETF_CONFIRMATION / `PIT_ETF_FAMILY_RELATIVE_TOTAL_RETURN` | 60 trading days | RETURN | O | 61 / 0.80 | lagged amount / DIRECTION_BASKET |
| `ETF_ABOVE_MA20` | ETF_CONFIRMATION / `PIT_ETF_FAMILY_ABOVE_MOVING_AVERAGE` | 20 trading days | RATIO | O | 20 / 0.80 | lagged amount / NONE |
| `ETF_ABOVE_MA60` | ETF_CONFIRMATION / `PIT_ETF_FAMILY_ABOVE_MOVING_AVERAGE` | 60 trading days | RATIO | O | 60 / 0.80 | lagged amount / NONE |
| `ETF_TURNOVER_EXPANSION_20D` | ETF_CONFIRMATION / `PIT_ETF_FAMILY_TURNOVER_EXPANSION` | current + 20 prior trading days | PERCENT | O | 21 / 0.80 | lagged amount / NONE |
| `ETF_SHARE_CHANGE_1D` | ETF_CONFIRMATION / `PIT_ETF_FAMILY_SHARE_CHANGE` | 1 trading day | PERCENT | O | 2 / 0.80 | lagged amount / NONE |
| `ETF_SHARE_CHANGE_5D` | ETF_CONFIRMATION / `PIT_ETF_FAMILY_SHARE_CHANGE` | 5 trading days | PERCENT | O | 6 / 0.80 | lagged amount / NONE |
| `ETF_SHARE_CHANGE_20D` | ETF_CONFIRMATION / `PIT_ETF_FAMILY_SHARE_CHANGE` | 20 trading days | PERCENT | O | 21 / 0.80 | lagged amount / NONE |
| `ETF_ESTIMATED_CREATION_REDEMPTION_1D` | ETF_CONFIRMATION / `PIT_ETF_FAMILY_ESTIMATED_CREATION_REDEMPTION` | 1 trading day | CNY | O | 2 / 0.80 | lagged amount / NONE |
| `ETF_ESTIMATED_CREATION_REDEMPTION_5D` | ETF_CONFIRMATION / `PIT_ETF_FAMILY_ESTIMATED_CREATION_REDEMPTION` | 5 trading days | CNY | O | 6 / 0.80 | lagged amount / NONE |
| `ETF_ESTIMATED_CREATION_REDEMPTION_20D` | ETF_CONFIRMATION / `PIT_ETF_FAMILY_ESTIMATED_CREATION_REDEMPTION` | 20 trading days | CNY | O | 21 / 0.80 | lagged amount / NONE |
| `ETF_PREMIUM_DISCOUNT` | ETF_CONFIRMATION / `PIT_ETF_FAMILY_PREMIUM_DISCOUNT` | point in time | PERCENT | O | 1 / 0.80 | lagged amount / NONE |

v1 公式同样闭合：

```text
# 财务只使用 ann_date/f_ann_date/first_seen_at <= as_of 的最新可见报表。
# source fields 固定为 income.revenue、income.n_income_attr_p、
# cashflow.n_cashflow_act、balancesheet.total_hldr_eqy_exc_min_int 和
# daily_basic.total_mv；进入公式前统一换算为 CNY。
stock_revenue_growth_ttm_yoy =
    sum(revenue_latest_4_quarters) / sum(revenue_prior_year_same_4_quarters) - 1
    # prior-year denominator <= 0 -> constituent missing
stock_operating_cashflow_margin_ttm =
    sum(net_operating_cashflow_latest_4_quarters) /
    sum(revenue_latest_4_quarters)
    # revenue denominator <= 0 -> constituent missing
stock_earnings_yield_ttm =
    sum(parent_net_profit_latest_4_quarters) / total_market_value_as_of
stock_book_to_price_lf =
    latest_visible_parent_equity / total_market_value_as_of
    # non-positive market value or equity -> constituent missing

# 四个财务/估值指标先按 as_of 截面的 nearest-rank 1%/99% 分位 winsorize，
# 再对 direction 的 PIT eligible constituents 等权平均；missing 仍留在 coverage 分母。

adjusted_close_i,t = close_i,t * pit_adjustment_factor_i,t
stock_total_return_i(t,w) = adjusted_close_i,t / adjusted_close_i,t-w - 1
direction_return(t,w) =
    mean_equal_weight(stock_total_return_i(t,w) over PIT eligible/observed i)
relative_total_return(t,w) =
    direction_return(t,w) - parent_sector_return(t,w)

above_ma_w_pct =
    count(adjusted_close_i,t > mean(adjusted_close_i,t-w+1..t)) / observed_count
new_high_low_20d_balance =
    (count(adjusted_close_i,t == max_20d_i) -
     count(adjusted_close_i,t == min_20d_i)) / observed_count
turnover_expansion_20d_pct =
    count(amount_i,t > 1.2 * median(amount_i,t-20..t-1)) / observed_count

direction_daily_return_t =
    mean_equal_weight(stock_total_return_i(t,1) over that day's PIT eligible/observed i)
realized_volatility_60d = sample_std(direction_daily_return_last_60) * sqrt(252)
direction_wealth_t = chain(1 + direction_daily_return_t)
current_drawdown_252d =
    direction_wealth_t / max(direction_wealth_t-251..t) - 1

# ETF family 权重 w_e 在 as_of 前冻结为各 ETF 前 20 日 median amount 占比；
# 同一指标窗口内不因事后表现重算。
etf_adjusted_close_e,t = fund_daily.close_e,t * pit_fund_adj_factor_e,t
etf_total_return_e(t,w) =
    etf_adjusted_close_e,t / etf_adjusted_close_e,t-w - 1
etf_family_return(t,w) = sum(w_e * etf_total_return_e(t,w))
etf_relative_return(t,w) = etf_family_return(t,w) - direction_return(t,w)
family_wealth_t = chain(1 + sum(w_e * etf_total_return_e(t,1)))
etf_above_ma_w = 1 if family_wealth_t > mean(family_wealth_t-w+1..t) else 0
etf_turnover_expansion_20d =
    sum(amount_e,t) / median(sum(amount_e,h) for h=t-20..t-1) - 1
etf_share_change(t,w) =
    sum(w_e * (adjusted_shares_e,t / adjusted_shares_e,t-w - 1))
estimated_creation_redemption(t,w) =
    sum((adjusted_shares_e,t - adjusted_shares_e,t-w) *
        pit_nav_e,t_or_close_basis)
etf_premium_discount =
    sum(w_e * (close_e,t / pit_nav_e,t - 1))
```

财务累计/单季字段必须先通过版本化 statement-normalization contract 转为不重叠季度流量；
ETF price total return 必须使用 `fund_daily+fund_adj`，且只接受
`fund_adj.trade_date/first_seen_at<=as_of` 的 PIT 因子；缺少合法因子时相应 ETF price
confirmation 为 `SOURCE_UNAVAILABLE`，不得退化为未复权 close return。
ETF `family_price/family_amount/adjusted_family_shares` 的权重、份额单位和 corporate action
调整也必须由同一 map/adjustment hash 重算。`fund_adj` 只解决价格复权，份额单位变化、
拆并份、基金合并和代码迁移仍由独立 share/corporate-action contract 处理，不能混为一项。
`change` 唯一表示当前 metric value 减去 20 个
交易日前按同一合同重算的 value；point-in-time 财务/估值指标若 20 日前无合法快照则为
`null`。不得为某个 cohort、Sector 或语言增加第二套公式。

`SECTOR_DIRECTION_METRIC_REGISTRY` 是 fundamentals、valuation、成分股技术和 ETF 确认指标的
唯一可编辑闭集，并生成 TypeScript union、Python enum、JSON Schema 和公式 dispatch；
snapshot 不能提交任意 `metric_id/unit`。每个值必须解析到 hash 匹配的 metric contract，
窗口、单位、公式、复权、benchmark、篮子权重、最小观察数、coverage 和分位算法均从合同
派生；同一 card 内每个合同要求的 metric 恰好出现一次，重复、缺失或额外 ID 均拒绝。
`status=AVAILABLE` 时 value/evidence 必须非空并满足 observation/coverage，其他状态 value
必须为 `null` 且 percentile status 同步不可用。自身历史分位固定使用截至 `as_of` 的最近
252 个合法观测和 average-tie empirical
CDF；未达到该 metric 的 `minimum_observations` 时只把历史分位标为
`INSUFFICIENT_HISTORY`。同 Sector 截面只有一个 eligible direction 时必须为
`NOT_APPLICABLE_SINGLE_DIRECTION`，不得伪造 0、0.5 或 1。

共同必需技术基座使用 direction 当日 PIT 等权成分股篮子，至少确定性计算 5/20/60 日相对
所属 Sector benchmark 收益、MA20/MA60 上方比例、20 日新高新低、20 日成交扩张、60 日
实现波动和当前回撤；所有收益、复权、停复牌和 eligible universe 沿用同一
direction/universe hash。这保证没有专属 ETF 的方向仍可公平比较，但不得把成分股篮子冒称
ETF。所有 `required_for_direction_readiness=true` 的共同指标都必须 `AVAILABLE`、达到各自
最小 observation 和 coverage；核心成分股技术 coverage floor 固定为 90%。任一失败即令该
direction `REJECTED`，不能由 optional ETF 或模型解释补齐。

ETF 确认层只使用 `SectorDirectionEtfMapEntry` 中 `as_of` 有效、已上市未退市、至少 60 个
交易日历史且价格/份额 PIT 合法的 ETF。一个方向有多只 ETF 时，按各 ETF 在 `as_of` 前 20
个交易日 median amount 的滞后权重合成 family return，权重和输入 hash 固定，禁止模型挑一只
表现最好的 ETF。至少计算 ETF family 的 5/20/60 日收益及相对 direction basket 路径、
MA20/MA60、成交额扩张、1/5/20 日份额变化，以及估算申赎金额。估算值固定标记
`ESTIMATED_CREATION_REDEMPTION`：优先使用当日已公开 NAV 乘份额变化，没有 PIT NAV 时使用
收盘价并记录 basis，绝不能称为交易所确认的净资金流；premium/discount 只有 PIT NAV 可用时
才生成。

同一 ETF 在重叠有效区间内只能映射到一个 direction；跨方向共享映射直接拒绝，不用重复
价格/份额证据支持多个方向。`TRACKED_INDEX_EXACT` 的 holdings 字段必须全部为 `null`；
同时必须提供 tracked index code、版本化 index contract/hash 和
`tracked_index_direction_match_hash`。runtime 必须用 `as_of` 当时可见的 tracked-index 定义/
成分与 direction partition 重算 match hash，证明 ETF 跟踪标的与该方向合同精确一致；
只有名称相似、当前网页说明、ETF 代码约定或无法 PIT 重放的 index mapping 不能标记为
`TRACKED_INDEX_EXACT`。
`HOLDINGS_EXPOSURE_VERIFIED` 必须使用在 `as_of` 已公开且已生效的持仓披露，按已识别净资产
权重计算 direction exposure，披露覆盖率至少 90%、direction exposure 至少 80%，披露账龄
不得超过 120 个自然日，并至少每 30 日重算 mapping；否则 map entry 不生效。阈值或刷新周期
变化必须发布新 map contract。ETF 份额单位变更、拆并份、基金合并和代码迁移必须先经过版本化 corporate-
action adjustment contract；无法归一化时 share-change 和估算申赎指标为
`SOURCE_UNAVAILABLE`，不能制造跳变。

ETF 是 optional supplemental confirmation，不改变 Sector required readiness。无注册 ETF、历史不足、
份额/NAV 过期或接口不可用时，ETF block 必须显示对应 unavailable 状态；pairwise 比较的两个
方向只要任一 ETF block 不可比，`ETF_PRICE_CONFIRMATION/ETF_SHARE_FLOW_CONFIRMATION`
criterion 就必须显式标为 `INCOMPARABLE`，不能省略，也不能把“没有 ETF”当成资金流出或
技术面落后。两侧均可比时，每项 ETF criterion 只按 comparison contract 的 `0.5` 半票进入
加权 resolver；它可确认/反证基础证据或打破基础平局，但不能弥补 winner 少于两个非 ETF
基础支持。ETF unavailable 的票权为零，因此缺失不会降低 direction readiness 或支持数。
成分股篮子必需技术基座缺失则该 direction `REJECTED`，不能靠 ETF 反向补齐。

调用 `index_member_all` 时 L1 code 必须进入 `l1_code`、L2 code 必须进入 `l2_code`；
禁止把行业代码误作证券 `ts_code` 或使用旧 `index_member` 接口。`technology` 的电子范围
先取 `l1_code=801080.SI`，再按同一 PIT 成员行的 `l2_code` 排除 `801081.SI`。
新能源车整车继续由 `consumer` 的 `801880.SI` 捕获；电池公司由 `energy` 的
`801737.SI` 捕获；锂、钴等上游矿业公司仍按 `industrials` 的 `801050.SI` 捕获。
每个 code 的 `SectorMembershipQueryPlan` 必须显式生成 `is_new=Y` 与 `is_new=N` 两个
branch，并按合同中的 literal merge key 合并去重；只使用默认 `is_new=Y` 不能证明历史成员，
历史 readiness 必须失败关闭。实现和审计读取 query plan 内容并重算 hash，不能只保存
无法重放的 opaque hash。

仅上述 exact-code 范围属于九个标准 Sector；申万“综合”等未列行业不能被模型临时纳入。
电子 L1 成分必须先按当日有效 L2 成员剔除 `801081.SI`，钢铁/黑色金属只能按申万钢铁
成员捕获，不能手工追加发行人。发布时必须再次验证 preflight 官方响应与上述
non-empty exact codes 完全相同，并将 codes、官方名称、层级、structure hash 和有效区间
连同结构化 `is_new=Y/N` 查询计划及其 hash 提交到 registry；名称歧义、code/name/level 不匹配、
缺失或 taxonomy drift 时拒绝 READY，
不允许字符串模糊匹配或自动换码。

同一证券同时命中多个范围时按 registry 冻结的 precedence 只进入一个标准 Sector；初始顺序为
`semiconductor > technology > energy > agriculture > real_estate_construction > financials > biotech > consumer > industrials`。
标准 Sector 的 required 行业资金不再从 `moneyflow_ind_ths` 映射，因为该接口只提供
同花顺行业整体现值，无法识别 SW Sector 与 THS 行业交集的真实净流入；把同一 THS 行业
净流入按 SW→THS turnover 权重重新分配会重复使用整笔流量，不能形成可审计的 Sector 值。
正式资金值改为对冻结 PIT candidate universe 的全部可得个股 `moneyflow` 行确定性聚合，
不是抽样个股代理。

具体公式冻结为：令证券 `i` 的前 20 日 median turnover 为 `t_i`，`O` 为当日具有 schema
合法、币种已归一且 `trade_date<=as_of` 的个股资金行集合，`T=sum_i(t_i)`，
`T_obs=sum_{i in O}(t_i)`，`F_obs=sum_{i in O}(signed_net_flow_i)`，则
`coverage_ratio=T_obs/T`，正式
`sector_flow_intensity=F_obs/T_obs`。`signed_net_flow_i` 唯一使用经 registry/preflight
固定的 Tushare `moneyflow.net_mf_amount` 并从万元统一换算为合同币种；官方说明该净额基于
L2 主动买卖单，不能用大小单买卖分项简单相减重建。模型不得选择字段或自行计算。
`T=0`、`T_obs=0`、重复证券行、单位不一致、行不属于冻结 universe
或 `coverage_ratio<0.9` 均拒绝。缺失证券保留在 coverage 分母，不能为过门槛删除。
`moneyflow_ind_ths` 只可作为独立、明确标记的行业轮动诊断，不能进入 Sector required
readiness、direction comparison、formal composite 或补齐缺失个股流量。财务 90%
覆盖率的分母是在行业成员、上市/退市、60 交易日历史、当日停牌与上述去重规则之后冻结的
candidate universe；缺财务的证券保留在分母并带 missing flag，不得为通过门槛而事后删除。
同一冻结 universe/hash 同时供 snapshot、missed-opportunity outcome 和 ETF/资金覆盖使用。

九个标准 Sector 的 `get_sector_research_snapshot()` 共享以下数据基座，随后按角色追加固定
overlay。只有标为 required 的分支参与 readiness；任一 required 分支不完整时该 Sector
拒绝：

| 分支 | required | 固定数据源 | PIT/用途 |
| --- | --- | --- | --- |
| 证券与行业域 | 是 | Tushare `stock_basic`；申万 2021 `index_classify(src=SW2021)+index_member_all`；唯一 `SECTOR_UNIVERSE_REGISTRY` | 成分必须有 `valid_from/valid_to`；不得以今日行业分类回填历史 |
| 市场与可交易性 | 是 | `daily+adj_factor+daily_basic+suspend_d+stk_limit` | 只用 `as_of` 前可见复权因子、停复牌和涨跌停状态；确定性生成流动性/收益特征 |
| 公司与核心财务 | 是 | `stock_company+fina_indicator+income+balancesheet+cashflow` | 最新可见核心财务覆盖率至少 90%；财报按实际公告时间生效，报告期不能充当发布时间 |
| 预告/快报/产品结构 | 否 | `forecast+express`；`fina_mainbz(type=P)` | 仅在实际公告后作事件/结构诊断；缺少不转换成负面事实 |
| 行业资金 | 是 | 冻结全部 PIT 行业成员的 Tushare `moneyflow`；`moneyflow_ind_ths` 仅作 optional diagnostic | 以 20 日 median turnover 计算 observed coverage，低于 90% 拒绝；不得用抽样个股或 THS 整行业流量替代 |
| ETF/基金诊断 | 否 | `fund_basic+etf_index+fund_daily+fund_adj+fund_share+fund_nav+fund_portfolio` | 按 direction 注册 ETF 合成价格/成交/份额/估算申赎确认；价格只使用截至 as_of 可见的 `fund_adj`，NAV 和持仓仅在实际公告日后可见 |
| 研究 | 否，且 production 不投影 | Tushare `research_report` 只供独立 `RKE_SHADOW` collector | 不进入 production Sector snapshot、候选域或证据；原文和摘要不进入公开 artifact |
| 政策 | 否 | 国务院/发改委及对应主管部委官方目录的角色投影 | append-only，保留发布时间/hash/parser version；不调用缺失的通用政策工具 |

这里的 Sector ETF/基金分支始终是 optional supplemental confirmation，与
`get_market_positioning_snapshot` 为 `institutional_flow` 定义的 required ETF universe/
share-adjusted-price 分支是两个不同 snapshot 合同；后者的 readiness 不能反向提高 Sector ETF 为
required，Sector 未注册 ETF 或 ETF 数据缺失也不能解释为“无资金”。Sector ETF block 只
确认对应 direction 的技术面，不读取或复制 `institutional_flow` 的全市场方向结论；若复用
同一 ETF 观测，必须沿用相同 evidence bundle/causal key。

角色 overlay 冻结为：

| Sector | required overlay | optional official event/context |
| --- | --- | --- |
| `semiconductor` | 电子/半导体 PIT 成分、公司产品结构、盈利/估值、行情与行业资金 | 工信部、海关总署、商务部与出口管制官方发布 |
| `technology` | 电子剔除半导体后的 PIT 成分，以及计算机/传媒/通信公司、财务、行情与行业资金 | 工信部、国家网信办、广电总局和主管部门已预注册发布 |
| `energy` | 煤炭/石油石化/电力及光伏/风电/电池 PIT 成分、公司/行情/资金；复用 `commodities` 同一 causal bundle 的能源确定性投影 | 国家能源局新能源装机/发电/利用率、国家统计局电力、工信部光伏/电池以及发改委/EIA 已预注册发布 |
| `biotech` | 医药生物 PIT 成分、公司/财务/行情/资金 | NMPA 药品批准、CDE 审评、国家医保局目录；事件工具仍不向模型开放 |
| `consumer` | 可选/必选消费和汽车 PIT 成分、公司/财务/行情/资金 | 国家统计局零售/CPI、乘用车/耐用品及主管部委发布 |
| `industrials` | 基础化工、钢铁/黑色金属、有色金属、机械、军工、电机/其他电源/电网设备、运输和环保冻结子域及公司/财务/行情/资金 | 国家统计局工业/投资、海关与主管部委发布；不得重复光伏/风电/电池子域 |
| `real_estate_construction` | 房地产、建筑材料、建筑装饰 PIT 成分及公司/财务/行情/资金 | 国家统计局房地产销售/投资/施工/竣工、住建部与主管部委发布 |
| `financials` | 银行/非银 PIT 成分、公司/财务/行情/资金；复用 PBOC 中国利率/信用价格的确定性背景投影 | 金融监管总局、证监会、PBOC 官方发布 |
| `agriculture` | 农林牧渔 PIT 成分、公司/财务/行情/资金；`fut_basic+fut_daily` 的冻结粮食与养殖投入链投影 | 农业农村部供需/价格/疫病、国家统计局农业和中国气象局官方发布 |

overlay 复用 Macro 数据时必须沿用原 `evidence_bundle_id/causal_dedupe_key`，只解释行业
敏感度，不产生第二张 Macro 票。optional source 未 READY 时不使 required 基座失败，
但模型不得声称对应事实；若某 overlay 被标为 required，其 adapter、freshness 和 coverage
必须先独立晋级并写入 contract version。

`get_relationship_graph_snapshot()` 的 required 输入是 frozen Sector 候选域、上述 PIT
市场基座、官方交易所/公司公告中的可验证供应链关系、`top10_holders+top10_floatholders`
和 `fund_portfolio` 共同持有关系；所有持有关系按实际披露时间生效。无法验证的文本关系
只能进入 shadow candidate edges，不进入 accepted graph 或生产 Darwinian label。

`get_superinvestor_candidate_snapshot()` 对 frozen Layer-2 accepted 候选域使用同一市场、
财务、公司和披露基座；四个哲学视图只改变模型解释任务，不改变底层候选域或 PIT 可见性。
`research_report` 和任何 RKE-derived context 均不进入 production 快照，也不能成为候选
入域条件；若要评估报告增量价值，只能在第 6.1.5 节隔离 shadow 中运行。

#### 6.1.3 Decision 专属数据合同

| 快照 | required 分支 | 固定来源/算法 |
| --- | --- | --- |
| `get_alpha_candidate_snapshot()` | frozen novel universe、生效中的静态风险/资格约束、市场/可交易性、财务、催化覆盖状态与基准 | `stock_basic+stock_st+daily+adj_factor+daily_basic+suspend_d+stk_limit`、财务六表/预告/快报、官方公司/交易所公告；候选资格由非 LLM 规则冻结；健康覆盖下可以是 confirmed no catalyst；不得注入同轮 CRO output |
| `get_cro_risk_snapshot()` | `AcceptedCioProposal` 及其完整 pre-CRO 目标组合、当前持仓/现金、硬约束、中国实现波动、相关/协方差、流动性/停牌/涨跌停、未来风险事件 | 版本化 portfolio/constraint ledger；Tushare `daily+adj_factor+daily_basic+suspend_d+stk_limit`；仅用 `as_of` 前价格确定性计算 realized volatility/covariance；candidate universe hash 必须由 proposal 确定性派生 |
| `get_execution_snapshot()` | 从同一 CIO proposal 确定性应用 CRO control 后的 frozen intents、持仓/现金、CRO accepted control 或无对象 stage-skip、最新可见价格/成交/流动性/停牌/涨跌停、费用和冲击模型 | Tushare 日线基座只支持 paper planning；paper fill/cost 为版本化确定性模型；真实订单状态、quote、fill、fee 只来自已注册 broker OMS/exchange adapter；raw proposal intents 不得绕过 CRO 重新进入 |
| `get_cio_decision_snapshot()` | proposal：持仓/现金、约束、前次目标、required 上游与 Alpha accepted/skip；final：与 proposal 字节相同的 pre-CIO 上游/Macro source-layer snapshot、同一 frozen proposal、CRO accepted/skip、Execution accepted/skip、成本和风险状态 | 版本化 ledger/constraint store；accepted upstream/skip 只由本 run runtime input 注入，不在工具中重复；proposal/final 使用不同 phase schema，final 可重新核对同一冻结证据并形成最终 attribution，但不重新注入 Alpha 或任何 proposal 外候选 |

上述“确定性算法”不得留作实现时自由选择。新增唯一
`DECISION_SNAPSHOT_ALGORITHM_REGISTRY`；v1 闭集必须恰好冻结以下五项：

- `cro_risk_v1`：证券收益使用截至 `as_of` 可见的后复权日收盘，20/60 日实现波动率；
  协方差使用最近 60 个 A 股交易日、每对至少 40 个共同有效收益，固定 20% 向对角矩阵
  shrink，并以稳定 `ts_code` 顺序输出。停牌日从最后可见价格产生零收益但另带 liquidity
  flag；不足 40 个共同观测的 pair 标为 unavailable，不能由零相关填充。若持仓或 frozen
  pre-CRO 候选存在 unavailable pair，snapshot 拒绝，除非 scoring contract 已预注册且验证
  一个保守的 sector-volatility replacement；不得运行时临时 fallback。
- `alpha_novel_universe_v1`：从 pre-CIO Layer-3 frozen universe 中排除已经被 Layer-3 accepted
  pick 选中的证券；要求截至 `as_of` 已上市至少 60 个交易日、最近 20 日至少 18 个有效行情、
  当日非停牌、非 ST/退市整理、最新核心财务 PIT 合法，且 20 日 median amount 不低于同一
  PIT universe 的 20 分位。通过者按 median amount 降序、`ts_code` 破同分截断到 200；
  非 ST 状态必须来自按 `trade_date` 查询并通过权限/schema preflight 的 Tushare
  `stock_st`，不能从当前证券名称或今日 `stock_basic` 状态反推。该接口历史起点为
  2016-01-01；preflight 必须验证 `type/type_name` 枚举能够识别合同要求的 ST 与退市整理
  状态。若接口枚举不覆盖退市整理，必须另行注册交易所风险警示/退市整理 adapter，不能把
  `stock_st` 的非命中当作证明。更早 `as_of` 若没有独立、预注册且 PIT 可证的风险警示档案，
  机会集生成失败关闭。catalyst coverage 只决定事件字段是否可用，不得在 outcome 后改变
  eligibility。
- `paper_execution_v1`：planning 只使用 `as_of` 前 20 日 median volume/amount 和已注册的
  effective-dated fee schedule；outcome 在下一交易日使用日线 amount/volume 得到 deterministic
  VWAP。停牌、买入封涨停或卖出封跌停为 `BLOCKED`；单笔最多成交下一日成交量的 10%，
  其余为 `PARTIAL`。成交价为 VWAP 加订单方向的
  `5bps + 10bps*sqrt(participation/10%)` 冲击，再加当日有效佣金、印花税和过户费；零成交量
  不得生成 fill。单位换算、复权、四舍五入和费用生效区间全部进入 contract fixture。
- `cro_adjusted_order_intents_v1`：以同一 `AcceptedCioProposal` 的目标/当前权重差为原始
  intent，按稳定 ticker 顺序确定性应用本 run CRO action；`VETO` 删除 intent，
  `CAP_WEIGHT/REDUCE_WEIGHT` 将目标裁剪到更保守上限，`REQUIRE_REVIEW` 在未解除时删除，
  `NO_OBJECTION` 保留。零 delta 删除，剩余 intent 集合及 hash 是
  `get_execution_snapshot()` 和 Execution outcome 的唯一 frozen order-intent source。
- `cio_risk_cost_v1`：proposal/final 使用与 `cro_risk_v1` 字节相同的 covariance hash、与
  `paper_execution_v1` 相同的 planning cost/fee contract，以及同一 ledger/constraint version；
  任一 hash 不一致时拒绝，不得由 CIO prompt 重新估算风险或成本。

阈值、公式、有效日期、缺失值规则和 fixture hash 均属于算法合同版本；任何变更都创建新的
`execution_behavior_version`、outcome/scoring contract 和独立评价轨。TypeScript 与 Python
必须读取同一生成注册表并通过字节一致 fixture，不能各自重写公式。

没有 broker/exchange intraday quote 与 OMS preflight 时，`execution_mode=REAL` 必须失败；
日线收盘价不得冒充实时可成交价。真实 fill label 只由 OMS 回报生成，LLM 不生成 fill。
CRO 的硬约束和 CIO 的持仓/现金 ledger 不受 Darwinian score、成熟状态、KNOT 结果或模型
置信度缩放。

#### 6.1.4 统一公告时间与可见性

财务、基金和研究数据不能用报告期代替发布时间。统一规则为：

```text
released_at = registered_release_field(endpoint)
knowledge_at = released_at
               if availability_proof == OFFICIAL_VINTAGE
                  && official_archive_proof_valid
               else first_seen_at
visible(as_of) = released_at <= as_of
                 && knowledge_at <= as_of
                 && (vintage_effective_at == null || vintage_effective_at <= as_of)
```

后来下载的 official archive 只有在 document/series ID、官方发布时间、当时有效 revision
和 archive provenance 均可证明时才可令 `knowledge_at=released_at`；普通当前 API 响应、
Tushare current row 或第三方镜像一律走 `first_seen_at`，不能因页面自称历史数据而回填。

| endpoint family | 注册 release field | 禁止替代 |
| --- | --- | --- |
| `stock_basic/stock_company/index_member_all` | 可证明的 `list_date/delist_date/in_date/out_date` 只控制有效区间；其他可变属性从 `first_seen_at` 生效 | 今日状态、今日行业分类 |
| `stock_st` | 仅接受接口返回的逐 `trade_date` 风险警示状态且 `trade_date/first_seen_at<=as_of`；2016 年以前无预注册档案则 unavailable | 当前名称包含 ST、今日风险警示状态回填历史 |
| `income/balancesheet/cashflow/fina_indicator` | `f_ann_date`，缺失时才用 `ann_date`；两者语义须经 endpoint schema 验证 | `end_date` |
| `fina_mainbz` | 连接当时已观察到的 `disclosure_date.actual_date/modify_date` 并由交易所公告 document/time 核验；无法证明时用 `first_seen_at` | `end_date`、今日查询到的披露日期 |
| `forecast/express` | `ann_date` | 报告期 |
| `fund_portfolio` | `ann_date` | `end_date` |
| `fund_adj` | `trade_date` 只表示因子适用日；仅有 official archive proof 时可按该日可见，否则从 append-only `first_seen_at` 生效 | 今日下载的完整因子序列回填历史 |
| `disclosure_date` | 当时已观察到的 `actual_date/modify_date` 或交易所公告时间 | 今日查询到的计划/实际日期反填历史 |
| `research_report` | 经 preflight 证明为首次公开日的发布字段；否则只从 `first_seen_at` 可见 | 标题中的日期、报告期 |
| `top10_holders/top10_floatholders` | 经 endpoint schema 验证的 `ann_date` | `end_date` |

注册 release field 缺失或语义不确定时只能从 append-only `first_seen_at` 起可见；不得猜测、
回填或用相邻 endpoint 的日期。所有 snapshot semantic validator 必须拒绝晚于 `as_of`
的公告、成分、复权因子、停牌/涨跌停状态和后续修订。

#### 6.1.5 RKE shadow 隔离

`get_rke_research_context` 不属于上述 28-Agent production 工具矩阵。它只允许出现在
`execution_mode=RKE_SHADOW` 的独立 shadow node/replay，使用单独 capability、state、
accepted-output namespace 和 scorecard；其输出不得进入 production graph state、候选域、
accepted transmission、Decision input、Darwinian outcome 或权重更新。production prompt、
tool manifest 和 prompt checker 遇到该工具名必须失败。RKE 的 roster/字段迁移只保证新角色
可做隔离研究，不构成将 report-derived signal 晋级到交易决策。

### 6.2 中国

主来源：

- Tushare 中经第 6.1 节权限/schema preflight 后标为 `ACTIVE_VERIFIED` 的国内宏观、
  `eco_cal`、利率、外汇、期货、资金流和市场行情 endpoint；不包含四个禁用接口。
- PBOC、国务院及相关部委官方政策和操作数据。
- 官方政策文件进入事件库，经发布时间过滤、内容去重和来源标记后供
  `china`、`geopolitical` 使用。
- 上述四个无权限接口按第 6.1 节统一禁用；不得把失败请求转换成空数据、新闻平静、
  政策不变或触发隐式替代源。

`get_china_macro_snapshot` 的五个 required 组件不能只写成职责名称。实现前冻结如下
`CHINA_MACRO_SERIES_MAP`；所有官方目录 adapter 都必须追加保存
`published_at/first_seen_at/retrieved_at`、内容 hash、parser/schema version 和 revision，
Tushare endpoint 只有进入 `ACTIVE_VERIFIED` 后才可被对应 series 引用：

| `china` 组件 | required series family | 固定来源与最小输入 | 所有权与失败语义 |
| --- | --- | --- | --- |
| 增长/生产 | `china_growth_production` | Tushare `cn_gdp+cn_pmi`；国家统计局“国家数据”中的工业增加值、固定资产投资、社会消费品零售总额及城镇调查失业率/就业发布 append-only release adapter | `china` PRIMARY；GDP、PMI 与月度生产/需求/就业发布均须具备 PIT 时间，不能用地产补缺 |
| 价格 | `china_prices` | Tushare `cn_cpi+cn_ppi`，并以国家统计局同批官方发布目录核验 period/unit/release time | `china` PRIMARY；CPI、PPI 任一缺失即该组件拒绝 |
| 信用 | `china_credit_impulse_quantity` | 第 6.2 节 `pboc_credit_money` 同一冻结发布中的社融增量/存量、人民币贷款和货币存量 | `china` 是信用数量/增速/脉冲唯一 PRIMARY owner；缺任一预注册数量分支即拒绝 |
| 外需/贸易 | `china_external_demand_trade` | 海关总署月度统计公报的进出口总额、贸易伙伴和主要商品表；`eco_cal` 只提供计划时点 | `china` PRIMARY；当前最新表不能回填旧 vintage，发布修订追加保存 |
| 财政 | `china_fiscal_impulse` | 财政部“全国财政收支情况/财政数据”月度目录中的一般公共预算和政府性基金收支 | `china` PRIMARY；累计值转单月和同比公式版本化，正文/发布日期不可由 `eco_cal` 替代 |

固定官方入口为：国家统计局 `https://data.stats.gov.cn/easyquery.htm`，海关总署月度公报
`https://english.customs.gov.cn/statics/report/monthly.html`，财政部全国财政收支目录
`https://www.mof.gov.cn/zhengwuxinxi/redianzhuanti/quanguocaizhengshouzhiqingkuang/`。
入口移动、分页失败、报告期与发布时间无法区分或当前值缺少可证明 vintage 时，保持
`PREFLIGHT_REQUIRED/REJECTED`，不得改用搜索结果、World Bank 或日历 forecast。

`central_bank` 只读取确定性裁剪后的中国增长、价格、就业、信用摘要，以及
PBOC 操作、中国曲线和货币市场；不得读取 `china` 的 LLM 结论。
其中就业摘要只从 `china_growth_production` 同一官方发布的确定性 projection 生成，
在 `central_bank` 中固定为 `CONTEXT_ONLY`；`china` 仍是该就业/增长 release 的唯一
PRIMARY signal owner，PBOC Agent 不得据此单独定向。
其 required policy mapping 只接受 PBOC 官方货币政策报告/执行报告、政策公告、公开市场
操作、政策利率与流动性数据，以及经权限验证的独立利率/曲线 endpoint；`eco_cal` 只能
提供排期或发布时间上下文，不能替代政策正文。`npr/monetary_policy` 不得出现在 required
或 optional series map。官方 PBOC adapter 缺失、过期或 PIT 不可证时
`get_central_bank_snapshot` 拒绝，不能输出“政策不变”或 `NEUTRAL`。

信用证据允许两个 Agent 读取，但只允许一个方向所有者。字段级路由固定为：

| 信用投影 | 可见字段 | signal scope | 禁止 |
| --- | --- | --- | --- |
| `china_credit_impulse_quantity` | 社融/贷款/货币数量、增速、流量归一化与其 deterministic surprise | `china=PRIMARY` | `central_bank` 不得据此再生成一张经济周期或信用脉冲方向票 |
| `pboc_credit_conditions_price_access` | 政策利率、LPR、SHIBOR、曲线、流动性操作，以及信用发布的确定性背景摘要 | `central_bank=PRIMARY` 仅限 PBOC 反应函数、融资价格与传导可得性 | 不得把信用数量变化重复解释为独立政策支持/收紧；无 PBOC/价格证据时不能定向 |

两种投影引用同一发布时必须共享 `causal_dedupe_key`。信用数量 release 的 PRIMARY
signal owner 是 `china`；`central_bank` 中该 release 本身为 `CONTEXT_ONLY`，只有独立
PBOC action/rate/liquidity evidence 才能形成其组件方向。semantic validator 对同一
release 的两次数量方向计分直接拒绝。

PBOC required 数据不能只写成“官方源”。实现前冻结以下 source map；每个 adapter 都要
保存原始发布目录 URL、document/action ID、`published_at`、`effective_at`、本地
`first_seen_at/retrieved_at`、内容 hash、parser/schema version 和 append-only revision：

| source ID | 固定官方目录 URL |
| --- | --- |
| `pboc_omo_catalog` | `https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125431/index.html` |
| `pboc_lpr_catalog` | `https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125440/index.html` |
| `pboc_mpc_meeting_catalog` | `https://www.pbc.gov.cn/zhengcehuobisi/125207/3870933/3870936/index.html` |
| `pboc_monetary_policy_report_catalog` | `https://www.pbc.gov.cn/zhengcehuobisi/125207/125227/125957/index.html` |
| `pboc_statistics_release_catalog` | `https://www.pbc.gov.cn/diaochatongjisi/116219/116225/index.html` |

| series family | 固定 adapter / 官方目录 | 频率与 PIT | `central_bank` 用途 |
| --- | --- | --- | --- |
| `pboc_omo_operations` | 复用并收敛 `mosaic/dataflows/pboc_ops.py`；`pboc_omo_catalog` 及其已登记子目录 | 每个 PBOC 工作日采集；仅 `published_at/first_seen_at<=as_of` 可见；下一 PBOC 工作日后 2 个工作日未成功即 stale | 净投放、到期和工具结构，required |
| `pboc_lpr` | `pboc_lpr_catalog` 中的“贷款市场报价利率（LPR）”公告 | 月频，按公告发布时间生效；40 个自然日 hard cap | 政策/贷款定价状态，required |
| `pboc_policy_stance` | `pboc_mpc_meeting_catalog` 与 `pboc_monetary_policy_report_catalog` | 两个独立季度/事件分支；按正文首次公开时间形成 vintage；各使用已注册 PBOC expected-release calendar，下一预期发布后 15 个自然日 grace、最近正文首次公开后 150 个自然日 hard cap | 反应函数和措辞变化，required |
| `pboc_credit_money` | `pboc_statistics_release_catalog` 中的金融统计与社会融资规模月度发布 | 月频；报告期不能代替发布时间；50 个自然日 hard cap | PBOC 反应函数的 required 背景；数量/脉冲为 `CONTEXT_ONLY`，信用条件方向须由独立价格/政策证据支持 |
| `china_money_market_curve` | 仅使用统一 Tushare registry 中已为 `ACTIVE_VERIFIED` 的 `shibor`、`shibor_quote`、`yc_cb`；替代源必须另建明确 adapter | 日频；按当日 observation/retrieval 和交易日历 freshness | 货币市场与中国名义曲线，required |

`pboc_policy_stance` 的 MPC 例会和执行报告是两个独立 required 分支，各按自身最近计划
发布机会检查 freshness，不能相互替代。两者唯一 canonical freshness 均为
`expires_at=min(expected_next_release_at+15 calendar days,
first_published_at+150 calendar days)`；`expected_next_release_at` 必须来自带版本和证据的
PBOC expected-release calendar，不能由最近一次 retrieval、季度均值或另一分支推断。
`pboc_credit_money` 必须同时解析金融统计和社融
增量/存量的当期发布，缺一个分支即 family 不完整。`china_money_market_curve` 的最小
required 集为 `shibor+yc_cb`，其中 SHIBOR overnight 与 3M、同一已冻结中国政府债名义
曲线的 2Y 与 10Y 必须同日可见；`shibor_quote` 只作 optional 交叉诊断。

`yc_cb` 不能在运行时按模糊名称任选。真实权限/schema smoke 必须从返回 metadata 中确定
唯一中国政府债曲线 `ts_code/curve_type`，写入带有效区间的
`CHINA_CURVE_INSTRUMENT_MAP`，并固定 2Y/10Y term code、单位和日历。确切 instrument 未经
真实响应验证前该 map 为 `PREFLIGHT_REQUIRED`，`central_bank` 不得 READY；不得猜 code、
改用企业债曲线或由 LLM 挑期限。

上述 PBOC 目录必须在独立 China/PBOC 数据阶段完成 URL 层级、分页、
历史覆盖、发布时间解析和 schema preflight 后才能写入生产 `series_id`。目录移动只能由新
adapter revision 处理，不能用站内搜索结果或 `eco_cal` 静默补位。任何 required family
缺失、stale、目录被截断或 PIT 不可证时 snapshot 拒绝；可选的国务院/部委文件只能增加
事件证据，不能填补上述 required family。

### 6.3 美国

- `eco_cal` 为事件排期、当时可见 previous/forecast 和低延迟 provisional actual 的共享
  来源；正式 actual、revision/vintage 以预注册 ALFRED/官方 release 为权威，surprise 只在
  两者 PIT reconciliation 通过后由确定性代码生成。
- GDP、就业、CPI/PCE 等历史修订继续使用预注册 ALFRED/官方 series map。
- `us_economy` 拥有实体经济周期。
- `us_financial_conditions` 可读取确定性美国宏观摘要，但必须标记
  `CONTEXT_ONLY`；其最终方向必须由 Fed、曲线、信用、美元/人民币或金融压力
  等金融证据支持。

美国实体经济 series map 固定如下。ALFRED series ID 必须在实现阶段通过官方 metadata
验证频率、单位、季调、release 和 vintage；验证失败不能临时换 series：

| `us_economy` 组件 | required series map | 事件/PIT |
| --- | --- | --- |
| 增长/生产 | ALFRED `GDPC1`、`INDPRO` | `eco_cal` 给计划/预期；actual 与 revision 由 ALFRED/官方 release vintage 决定 |
| 价格 | ALFRED `CPIAUCSL`、`CPILFESL`、`PCEPI`、`PCEPILFE` | CPI 与 PCE 两个 release family 都 required，不能互相替代 |
| 就业 | ALFRED `PAYEMS`、`UNRATE` | payroll 与失业率必须来自同一可见 vintage |
| 需求/贸易 | ALFRED `RSAFS`、`BOPGSTB` | 零售与贸易 family 均 required；forecast 不可冒充 actual |

`us_financial_conditions` 不依赖笼统的“美国市场数据”。四个 required 组件和明确
adapter 固定为：

| 组件 | required source/series | 约束 |
| --- | --- | --- |
| Fed/流动性 | Federal Reserve FOMC 官方 calendar/statement；New York Fed EFFR、SOFR 官方数据 adapter | statement 按首次公开时间；日频 observation 按纽约工作日；缺正文不能从 `eco_cal` 推断 Fed 方向 |
| 美国曲线 | Tushare `us_tycr` 名义国债曲线；ALFRED `DFII5/DFII10/DFII30` 实际利率 | 名义与实际两分支均 required；不得输出“衰退灯号”，不得用 Fed 方向替代曲线证据 |
| 信用/金融压力 | ALFRED `BAA10Y`、`NFCI`、`VIXCLS` | credit spread、综合压力和隐含波动均进入同一组件；VIX 不再形成独立 Macro 票 |
| 广义美元/人民币 | ALFRED `DTWEXBGS`（Fed broad dollar，明确不是 DXY）；第 6.5 节注册的 `USD_CNY` Tushare `fx_obasic+fx_daily` pair | 两分支均 required；不得以 EUR pair 或模型自算未注册交叉盘补缺 |

FOMC、NY Fed、ALFRED 和 Tushare adapter 各自独立注册，不构成隐式 fallback。
`us_tycr` 或任一 required 市场/官方 series 权限、schema、发布/观察时间、历史覆盖未通过
preflight 时 snapshot 拒绝；若未来改用 US Treasury 等官方替代源，必须发布新 source map、
component data-quality 和 scoring contract，不能运行时切换。`us_economy` 的确定性摘要
进入本快照时全部标记 `CONTEXT_ONLY`，不得贡献组件 `b_j`。

### 6.4 欧盟

已经确认的正式来源：

- Eurostat REST/SDMX API：EU27 增长、需求、HICP、就业、工业生产、零售和
  贸易；欧元区数据只作解释共同货币传导所需的补充。
- ECB Data Portal SDMX API：政策利率、€STR、曲线、银行信贷、融资成本、
  汇率和金融压力；使用 `includeHistory=true` 获取可用历史版本。
- Eurostat 官方发布日历和 Euro indicators。

`EU_SERIES_MAP` 不再保留抽象占位符。以下 key/dimension 已于 2026-07-16 通过官方
Eurostat/ECB API 非空响应验证；实现仍须保存 metadata/data-structure hash，并在结构 hash
变化时失败关闭而不是猜测新维度：

| `eu_economy` required series branch | 官方 dataset 与固定 dimensions | 计算与 PIT |
| --- | --- | --- |
| EU27 实际 GDP | Eurostat `namq_10_gdp`：`geo=EU27_2020,na_item=B1GQ,unit=CLV10_MEUR,s_adj=SCA,freq=Q` | level 进入证据，QoQ/YoY 由确定性代码计算；release calendar + 可用官方 vintage/本地 append-only |
| EU27 HICP | Eurostat `prc_hicp_minr`：`geo=EU27_2020,coicop18=TOTAL,unit=RCH_A,freq=M` | 2026 ECOICOP v2 合同；旧 `prc_hicp_manr/coicop=CP00` 只作迁移核验，不与新 key 静默拼接 |
| EU27 失业 | Eurostat `une_rt_m`：`geo=EU27_2020,age=TOTAL,sex=T,unit=PC_ACT,s_adj=SA,freq=M` | 明确使用 dataset 当前 `TOTAL`，不得沿用已无数据的 `Y15-74` 参数 |
| EU27 工业生产 | Eurostat `sts_inpr_m`：`geo=EU27_2020,indic_bt=PRD,nace_r2=B-D,unit=I21,s_adj=SCA,freq=M` | index level 和变化由确定性代码生成；imputed/status flag 原样保留并进入质量计算 |
| EU27 零售量 | Eurostat `sts_trtu_m`：`geo=EU27_2020,indic_bt=VOL_SLS,nace_r2=G47,unit=I21,s_adj=SCA,freq=M` | index level 和 MoM/YoY 由确定性代码生成；不得用名义营业额替代零售量 |
| EU27 域外贸易 | Eurostat `ext_st_eu27_2020sitc`：`geo=EU27_2020,partner=EXT_EU27_2020,sitc06=TOTAL,indic_et=TRD_VAL_SCA,stk_flow=EXP,freq=M`，以及同维度的 `stk_flow=IMP` | 出口和进口两条 flow 均 required；增长、净出口/贸易余额只由确定性代码计算，dataset metadata 中的单位和 status 原样保存 |

四个组件与六个 required series branch 的映射固定为：增长/生产同时要求 GDP 与工业生产，
价格要求 HICP，就业要求失业率，需求/贸易同时要求零售量以及域外出口、进口两条 flow。
任一 required branch 缺失都拒绝 `eu_economy` 阶段，不能用另一个组件、成员国分项或
World Bank 年频值补缺。EU 成员国分项仅为 optional/context，必须另行注册完整 dimensions
后才可启用。HICP 2026 数据结构切换必须建立显式 `series_lineage`、重叠期 reconciliation
和新 contract version；不能把 archived key 与 current key 当作同一原始 series。对于启用日
前没有官方 vintage 的序列，只能生成 latest-data 诊断，不能进入历史 Darwinian replay。

固定 `geo=EU27_2020` 与 Eurostat PEEI vintage 的 changing-composition EU aggregate 是两个
不同 series lineage。每条 Eurostat observation 必须新增 `geo_composition_at_vintage` 和
`geo_composition_contract_version`。只有 metadata 明确证明该 vintage 本身就是
`EU27_2020` 时，aggregate row 才能进入上述 required components；EU15/EU25/EU27_2007/
EU28 或其他随 revision date 变化的聚合只作 `CONTEXT_ONLY`，不得与当前 `EU27_2020`
拼接、计算增长率或生成 Darwinian label。若未来从成员国 vintage 重建固定 EU27，必须先
发布独立的 member-weight、chain-link、季调和缺失值方法合同及 reconciliation fixture；
没有该合同不得自行求和。因而初始实现中六个 required series branch 的官方 aggregate
vintage 只在 metadata 可证明固定 `EU27_2020` 口径时进入正式 PIT 历史；否则主要用于
revision 审计，正式历史从可证明口径一致的 observation 或本地 append-only 启用日开始，
冷启动不能由 changing-composition vintage 加速。

`EURO_AREA_FINANCIAL_SERIES_MAP` 固定为：

| required 维度 | ECB/市场固定 series | 最小完整性 |
| --- | --- | --- |
| ECB 政策状态 | ECB 决议/statement；`FM.B.U2.EUR.4F.KR.DFR.LEV`（deposit facility）和 `FM.B.U2.EUR.4F.KR.MRR_FR.LEV`（MRO fixed rate） | 最近决议正文、DFR、MRO 三者齐全；series observation 不能替代决议语义 |
| €STR | `EST.B.EU000A2X2A25.WT` | 最新 TARGET2/€STR 工作日 observation 与状态 flag |
| 欧元区主权曲线 | `YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y` 与 `YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y` | AAA nominal spot 2Y/10Y 同日可见；曲线斜率由确定性代码计算 |
| 银行信用/融资成本 | `BSI.M.U2.Y.U.A20T.A.I.U2.2240.Z01.A`（adjusted NFC loans annual growth）与 `MIR.M.U2.B.A2A.A.R.A.2240.EUR.N`（NFC new-business loan rate） | 信用数量和融资价格两分支均 required；provisional status 保留 |
| 欧元/金融压力 | `EXR.D.USD.EUR.SP00.A`、`CISS.D.U2.Z0Z.4F.EC.SS_CIN.IDX`，以及第 6.5 节已验证 `EUR_CNY` pair | EUR/USD、CISS、EUR/CNY 三分支均 required；不得用非欧元区指数或模型交叉盘补缺 |

这里的 `U2` 是欧元区 changing composition，不是 EU27。曲线 key 明确是 ECB AAA
nominal fitted spot curve，不能描述成“全欧元区平均主权收益率”。每个 ECB key 均保存
完整 series title、单位、频率、status、structure hash 和 release calendar；请求
`includeHistory=true` 后只有实际返回并可解释版本维度的 observation 才具有历史 vintage，
否则遵循本地 append-only 边界。任一 key 被 ECB 退役、返回空、结构漂移或 publication
time 不可证时对应 required 维度拒绝，不能用相邻期限/利率/国家 series 热切换。

PIT 限制：

- Eurostat 通用数据库只保留最新版本。
- Eurostat 官方 vintage 数据仅覆盖 GDP、工业生产和失业率，且发布进入
  vintage 库存在延迟。
- 这些官方 vintage 的 EU aggregate 采用 revision date 当时的 changing composition；
  未证明为 `EU27_2020` 的行不能进入固定 EU27 required history。
- 其他 Eurostat 序列从采集启用日起写入本地 append-only 快照。
- 无法证明历史版本的数据不得用于启用日前的回放。

本计划不采集或分析日本经济、BOJ、日元或日本金融条件。英国、瑞士、挪威也不
属于欧盟分析主体。欧盟非欧元区成员的实体数据可进入 `eu_economy`，其本国
央行政策和金融市场不属于 `euro_area_financial_conditions` 主体，只保留在
共享事件库中供审计，不进入任何 Macro 方向票。

### 6.5 外汇、商品与市场定位

#### 6.5.1 外汇

Tushare `fx_obasic` 先对用途角色发现并冻结 pair ID，再允许 `fx_daily` 进入
series map。`FX_PAIR_ROLE_MAP` 至少分别注册 `USD_CNY`、`EUR_CNY` 和 `EUR_USD`：
`USD_CNY` 只供 `us_financial_conditions`，EUR 两类只供
`euro_area_financial_conditions`。每条映射保存 instrument ID、quote/base、交易日历、
有效区间和 source-map version；未确认的货币对必须标记 `unavailable`，不得：

- 冒充 DXY。
- 静默改用另一数据源。
- 由 LLM 自行拼接交叉汇率。

允许确定性代码从已注册且 PIT 合法的输入派生交叉汇率，但必须引用全部输入
`source_evidence_id`，生成独立的派生证据并挂到同一 `evidence_bundle_id`，
同时服从 signal scope 和 causal dedupe 规则。

#### 6.5.2 商品与市场定位

`get_commodity_conditions_snapshot` 的四个组件均以 Tushare
`fut_basic+fut_daily` 中预注册的中国可交易合约族为市场主路径；合约代码、交易所、
品种、到期日、主力选择和连续合约拼接规则冻结在 `COMMODITY_CONTRACT_MAP`：

| 组件 | required 最小覆盖 | optional/诊断 |
| --- | --- | --- |
| 能源 | 原油/燃料相关至少一个连续可交易族及 PIT 成交/持仓 | EIA 官方库存 release；`eco_cal` 仅作发布时间 |
| 工业金属 | 铜及至少一个预注册基础金属族 | 交易所库存或官方产量 release，未通过 adapter preflight 前不计 required |
| 黄金 | 黄金可交易族及 PIT 行情 | 注册后的海外黄金/实际利率只作同因果 bundle 诊断 |
| 农产品/食品 | 至少两个预注册、分属粮食与养殖投入链的可交易族 | 农业供需/库存官方报告投影；不能由一个品种代表农业整体 |

初始 `COMMODITY_CONTRACT_MAP` 不再留到运行时任选：能源 required family 为
`SC@INE`，`FU@SHFE` 为 optional；工业金属 required family 为 `CU@SHFE`，
`AL@SHFE` 为 optional；黄金 required family 为 `AU@SHFE`；农产品 required families
为粮食 `C@DCE` 与养殖投入 `M@DCE`。`fut_code@exchange` 只标识品种族，具体 `ts_code`
必须从当时可见 `fut_basic` 的 `list_date/delist_date` 集合生成，不能把今天的主力代码写死。

连续路径使用版本化 deterministic roll：候选合约须在 `as_of` 已上市、未到期、至少有
20 个交易日历史，且距最后交易日不少于 10 个交易日；按过去 5 个可见交易日的 median
open interest 排序，依次以 median volume、较近到期和 `ts_code` 破同分。新合约连续 3 个
交易日胜出后在下一交易日切换；roll 前后的收益分别用各自结算价计算，不做价格差回填。
`fut_basic` 缺最后交易日字段时，以已验证的 `delist_date` 规则代替并降低数据质量；两者
都不可证则该品种族拒绝。阈值、tie-break、roll effective date 和 source rows hash 都写入
`commodity_contract_map_version`，模型不得选择主力或改 roll。

只有同一品种在 `as_of` 同时存在至少两个已知 expiry、流动性达标的真实合约时，确定性
代码才生成期限结构和 contango/backwardation 字段；否则字段为 `UNAVAILABLE`，模型不得
补写。四个 required 市场组件任一缺失或 coverage 不足时阶段拒绝。

`get_market_positioning_snapshot` 的 required source map 固定为：全市场资金
`moneyflow`、行业轮动 `moneyflow_ind_ths`、ETF PIT universe
`fund_basic+etf_index`、ETF 份额/复权价格
`fund_share+fund_daily+fund_adj`。ETF 份额还必须通过与 Sector ETF 相同的版本化
share/corporate-action adjustment contract 处理拆并份、基金合并、份额单位和代码迁移。
缺少 PIT 合法的 `fund_adj` 时 price 分支 unavailable，份额无法归一化时 share 分支
unavailable；两者都不能退化为原始 close 或伪造资金跳变。`fund_portfolio`、
`fund_nav`、`top_list` 和股东数据只在实际披露时间可证时作 optional crowding/持仓诊断；
龙虎榜永远不能替代全市场或 ETF required 分支。全市场、行业、ETF universe、ETF
share/adjusted-price 四个分支均需通过权限、覆盖、复权和 corporate-action PIT preflight；
任一 required 分支失败时
`institutional_flow` 拒绝，不输出中性。拥挤度只由版本化 deterministic feature 计算，
LLM 不得从抽样个股或新闻推断。

### 6.6 World Bank 补充层

World Bank 不作为隐式 fallback。预注册：

- Global Economic Monitor，source 15：月/季频 CPI、GDP、工业生产、零售、
  贸易、失业、REER/NEER、储备和市场指标。
- World Development Indicators，source 2：年度产业结构、贸易依存度、
  经常账户、FDI、人口、能源和金融深度。
- Quarterly External Debt Statistics：季度外债和结构。

全部 World Bank 观测固定：

- `usage_mode=CONTEXT_ONLY`。
- `required=false`。
- 不提高角色 snapshot 的 required coverage。
- 不作为 event forecast 或政策事实。
- 只有本地采集后形成的 append-only 版本可用于 PIT 回放。

### 6.7 Outcome 代理篮子与关系验证数据

美国/欧盟需求暴露篮子的主输入固定为 Tushare `fina_mainbz(type=D)` 地区主营收入，
并与对应报告期的实际公告时间、A 股历史证券主表和行情复权数据连接。地区文本只能
通过版本化的 `geography_alias_map` 映射到 `US`、`EU27` 或其他区域；欧盟成员表
必须按 `as_of` 冻结，不能用今天的成员关系回填历史。若 `fina_mainbz` 行无法证明
实际公告时间，则只能从本地首次采集日起使用，不能用报告期或计划披露日期代替
`released_at`。

PIT join 固定为 `(ts_code,end_date)` 的 `fina_mainbz(type=D)` 行连接 Tushare
`disclosure_date` 的 `actual_date/modify_date`，并交叉核验上交所、深交所、北交所官方
公告索引中的 document ID 和公开时间。`disclosure_date` 是可修订的披露计划表：只有
本地 append-only capture 在 `as_of` 前已观察到的 `actual_date/modify_date`，或官方交易所
当时可见的公告时间，才可证明 `released_at`；今天查询到的 actual date 不能反向证明旧
`as_of` 已知。历史区间若没有本地 vintage 或官方公告元数据，一律从 `first_seen_at`
开始可用，不得用计划日期、报告期、当前表值或 `fina_mainbz` 行本身推断发布时间。
现有用于 US/EU 收入暴露的 collector 若错误使用 `type="P"`，必须显式迁移并测试为地区
口径 `type="D"`；Sector 产品结构诊断仍保留独立、角色限定的 `type="P"` 路径。产品口径
不得进入 US/EU 暴露 label，地区口径也不得替代 Sector 产品结构。

每个代理篮子必须注册：

- `exposure_source_contract_version`、原始行 hash 和地理映射版本；
- 证券纳入阈值、收入暴露计算、缺失/负收入处理和权重上限；
- `constituent_valid_from/valid_to`、冻结日、基准、复权和再平衡频率；
- Tushare 权限预检、历史覆盖率和许可边界；
- 对无法分类或只有产品口径而没有地区口径的公司，不得由 LLM 推断地域收入。

美国/欧元区外部金融条件篮子在上述暴露篮子之外，只允许使用预注册、可 PIT 重建的
高久期、外部流动性和金融压力敏感特征。特征定义、截面排序、winsorization、权重和
再平衡日全部版本化；模型不能选择成分或阈值。

`relationship_mapper` 的 factual 供应链、持股簇和传染边在 accepted-output 阶段仍
必须由当时可见证据验证。其 Darwinian outcome 不再依赖未定义的“参考边数据库”：
只评价结构化预测边在随后 20 个交易日的激活、残差共振和共回撤相对 PIT 匹配非边的
lift。匹配非边只能用 `as_of` 时可见的行业、规模、流动性和历史 beta 进行匹配；
匹配算法、距离、负样本数和随机种子写入 scoring contract。所需市场路径使用
Tushare PIT 行情；所有权/基金共同持有事实可使用 Tushare 前十大股东、前十大流通
股东和 `fund_portfolio`，但只按实际公告/披露时间生效。RKE report-derived 边保持
shadow-only，不能进入生产 Darwinian label 或权重。

每次运行前必须冻结完整而有限的预测机会集，不能只评价模型主动提交的边：

```ts
const RelationshipMaterialityWeightSchema = z
  .number()
  .finite()
  .positive()
  .brand<"RelationshipMaterialityWeight">();
type RelationshipMaterialityWeight = z.infer<
  typeof RelationshipMaterialityWeightSchema
>;

interface RelationshipPredictionOpportunity {
  edge_candidate_id: string;
  source_entity: string;
  target_entity: string;
  edge_type: string;
  materiality_weight: RelationshipMaterialityWeight;
  matched_non_edge_set_id: string;
  matched_non_edge_set_hash: string;
}

interface FrozenRelationshipPredictionOpportunitySet {
  opportunity_set_id: string;
  opportunity_set_hash: string;
  run_id: string;
  as_of: string;
  candidate_generation_contract_version: string;
  scoring_contract_version: string;
  ordered_opportunities: [
    RelationshipPredictionOpportunity,
    ...RelationshipPredictionOpportunity[],
  ];
}
```

候选生成器必须冻结实体资格、pair 排序/截断、edge-type 闭集、materiality weight、匹配距离、
负样本数和随机种子。每个 `materiality_weight` 必须为有限严格正数，全部权重之和也必须为
有限正数；零、负数、`NaN`、无穷值、重复 candidate ID 或排序不稳定均在 Agent 调用前拒绝。
accepted predictive edge 只能绑定其中一个 candidate；未提交 candidate
仍保留在 outcome 分母。机会集为空属于 required-data unavailable，不创建
`FrozenRelationshipPredictionOpportunitySet`，不得伪装成模型正确空图。

以上 source map、权限和最小历史覆盖未验证前，相应 labeler 和 Darwinian roster
不得为 `READY`，也不得用手工今日成分、CIO 持仓或通用 CSI300 收益替代。

### 6.8 Geopolitical 事件源、可得性与时效

`geopolitical` 不使用财经日历或单一新闻流冒充完整事件库。新增持续采集的
`GeopoliticalEventRegistry`，把“发现事件”和“确认可交易状态”分开：

- `OFFICIAL_PRIMARY`：中国外交部、商务部/出口管制公告、国务院及相关监管机构；
  UN Security Council sanctions list/press release；美国 OFAC SLS/recent actions、
  BIS/Federal Register、USTR；EU Council、Official Journal/EUR-Lex 和 Commission
  sanctions resources。只有完成 schema、许可、发布时间和采集 preflight 的 adapter
  才能进入 required source registry。
- `STRUCTURED_DISCOVERY`：GDELT 2.0 Event/GKG。它只负责
  低延迟发现、别名扩展和触发官方复核；在官方确认或两个相互独立、内容去重后的
  approved domain 交叉确认前，只能生成 `RISK_FLAG/CONTEXT_ONLY`，不能单独决定
  `direction/strength`。聚合转载、同一通讯社镜像和同一官方稿的二次发布只算一个源。
- `OPTIONAL_CONTEXT`：许可和历史覆盖通过审计后的冲突、航运或供应链数据集。
  它们不得成为 production readiness 的隐式 fallback。禁止 OpenCLI、Google/Caixin
  搜索和实时雪球数据进入正式事件发现或确认链。

```ts
interface GeopoliticalEventRecord {
  geopolitical_event_id: string;
  event_revision_id: string;
  supersedes_revision_id: string | null;
  event_type:
    | "SANCTION"
    | "EXPORT_CONTROL"
    | "TARIFF_TRADE_RESTRICTION"
    | "ARMED_CONFLICT"
    | "SHIPPING_DISRUPTION"
    | "DIPLOMATIC_ESCALATION"
    | "DIPLOMATIC_DEESCALATION"
    | "OTHER_REGISTERED";
  lifecycle_status:
    | "DISCOVERED"
    | "ANNOUNCED"
    | "EFFECTIVE"
    | "ESCALATED"
    | "DEESCALATED"
    | "RESOLVED"
    | "EXPIRED";
  verification_status:
    | "OFFICIAL_CONFIRMED"
    | "MULTISOURCE_CONFIRMED"
    | "UNCONFIRMED"
    | "CONFLICT";
  actors: [string, ...string[]];
  affected_regions: string[];
  affected_channels: [string, ...string[]];
  published_at: string | null;
  effective_at: string | null;
  first_seen_at: string;
  retrieved_at: string;
  time_status: "VERIFIED" | "UNVERIFIED";
  primary_source_tier: "OFFICIAL_PRIMARY" | "STRUCTURED_DISCOVERY" | "OPTIONAL_CONTEXT";
  source_evidence_ids: [string, ...string[]];
  evidence_bundle_id: string;
  causal_dedupe_key: string;
  normalized_content_hash: string;
}

interface GeopoliticalSourceRegistrationBase {
  source_id: string;
  provider_kind: "OFFICIAL_PRIMARY" | "STRUCTURED_DISCOVERY" | "OPTIONAL_CONTEXT";
  registration_status: "ACTIVE" | "PREFLIGHT_REQUIRED" | "DISABLED_CONTRACT";
  source_contract_version: string;
  adapter_contract_id: string;
  adapter_contract_hash: string;
  required: boolean;
  required_for_event_types: GeopoliticalEventRecord["event_type"][];
  publisher_organization_id: string;
  upstream_origin_family: string;
}

type GeopoliticalSourceRegistration =
  | (GeopoliticalSourceRegistrationBase & {
      source_backend: "DIRECT";
      tushare_endpoint_id: null;
    })
  | (GeopoliticalSourceRegistrationBase & {
      source_backend: "TUSHARE";
      tushare_endpoint_id: TushareEndpointId;
    });

interface GeopoliticalSourceAdapterContract {
  adapter_contract_id: string;
  adapter_contract_version: string;
  adapter_contract_hash: string;
  source_id: string;
  canonical_url_or_api: string;
  retrieval_mode: "API" | "RSS" | "HTML_DIRECTORY" | "FILE_FEED";
  pagination_or_cursor_contract: string;
  continuous_scope_query_template: string;
  covered_actor_ids: string[];
  covered_region_ids: string[];
  global_scope_capable: boolean;
  covered_event_types: GeopoliticalEventRecord["event_type"][];
  source_time_zone: string;
  published_at_field: string;
  license_classification: string;
  expected_poll_interval_minutes: number;
  max_capture_age_minutes: number;
  truncation_detection_contract: string;
  no_event_claim_capable: boolean;
}

type GeopoliticalRouteApplicabilityReasonCode =
  | "MATERIAL_A_SHARE_TRANSMISSION_SCOPE"
  | "ISSUER_OR_TARGET_WATCHLIST_SCOPE"
  | "REGION_WATCHLIST_SCOPE"
  | "NO_REGISTERED_MATERIAL_LINK";

interface GeopoliticalCoverageRouteBase {
  coverage_route_id: string;
  coverage_route_hash: string;
  event_type: GeopoliticalEventRecord["event_type"];
}

type GeopoliticalCoverageRouteSubject =
  | (GeopoliticalCoverageRouteBase & {
      subject_type: "ACTOR";
      actor_id: string;
      region_id: null;
      actor_official_source_id: string | null;
    })
  | (GeopoliticalCoverageRouteBase & {
      subject_type: "REGION";
      actor_id: null;
      region_id: string;
      actor_official_source_id: null;
    })
  | (GeopoliticalCoverageRouteBase & {
      subject_type: "GLOBAL";
      actor_id: null;
      region_id: null;
      actor_official_source_id: null;
    });

type GeopoliticalCoverageRoute = GeopoliticalCoverageRouteSubject &
  (
    | {
        applicability: "APPLICABLE";
        applicability_reason_code: Exclude<
          GeopoliticalRouteApplicabilityReasonCode,
          "NO_REGISTERED_MATERIAL_LINK"
        >;
        required_source_ids: [string, ...string[]];
        no_event_evidence_source_ids: [string, ...string[]];
        route_status:
          | "ACTIVE_VERIFIED"
          | "PREFLIGHT_REQUIRED"
          | "COVERAGE_UNAVAILABLE";
      }
    | {
        applicability: "NOT_APPLICABLE";
        applicability_reason_code: "NO_REGISTERED_MATERIAL_LINK";
        required_source_ids: [];
        no_event_evidence_source_ids: [];
        route_status: "NOT_APPLICABLE";
      }
  );

interface GeopoliticalCoverageScopeContract {
  coverage_scope_version: string;
  coverage_scope_hash: string;
  watchlist_actor_ids: string[];
  watchlist_region_ids: string[];
  coverage_routes: GeopoliticalCoverageRoute[];
}

interface GeopoliticalRouteSourceCoverageBase {
  coverage_query_key: string;
  coverage_route_id: string;
  coverage_route_hash: string;
  event_type: GeopoliticalEventRecord["event_type"];
  source_id: string;
  source_family: string;
  scope_query_hash: string;
  required: boolean;
  poll_started_at: string;
  poll_completed_at: string | null;
  last_successful_poll_at: string | null;
  expected_poll_interval_minutes: number;
  max_capture_age_minutes: number;
  observed_publication_lag_minutes: number | null;
  status: "HEALTHY" | "STALE" | "UNAVAILABLE" | "SCHEMA_DRIFT";
  coverage_evidence_id: string;
}

type GeopoliticalRouteSourceCoverage =
  | (GeopoliticalRouteSourceCoverageBase & {
      subject_type: "ACTOR";
      actor_id: string;
      region_id: null;
    })
  | (GeopoliticalRouteSourceCoverageBase & {
      subject_type: "REGION";
      actor_id: null;
      region_id: string;
    })
  | (GeopoliticalRouteSourceCoverageBase & {
      subject_type: "GLOBAL";
      actor_id: null;
      region_id: null;
    });

interface GeopoliticalEventTypeCoverage {
  event_type: GeopoliticalEventRecord["event_type"];
  watchlist_scope_hash: string;
  required_query_keys: [string, ...string[]];
  healthy_query_keys: string[];
  unhealthy_query_keys: string[];
  required_source_ids: [string, ...string[]];
  healthy_source_ids: string[];
  no_event_evidence_source_ids: [string, ...string[]];
  no_event_evidence_query_keys: [string, ...string[]];
  query_complete: boolean;
  status: "EVENTS_PRESENT" | "COVERAGE_CONFIRMED_NO_EVENT" | "COVERAGE_UNAVAILABLE";
  coverage_evidence_ids: [string, ...string[]];
}

interface GeopoliticalEventsSnapshot {
  as_of: string;
  event_registry_version: string;
  source_registry_version: string;
  coverage_scope_version: string;
  source_coverage_contract_version: string;
  coverage_scope_hash: string;
  active_event_types: GeopoliticalEventRecord["event_type"][];
  registrations: GeopoliticalSourceRegistration[];
  route_source_coverage: GeopoliticalRouteSourceCoverage[];
  coverage_by_event_type: GeopoliticalEventTypeCoverage[];
  events: GeopoliticalEventRecord[];
  empty_state:
    | "EVENTS_PRESENT"
    | "COVERAGE_CONFIRMED_NO_MATERIAL_EVENT"
    | "COVERAGE_INCOMPLETE";
  readiness: "READY" | "REJECTED";
}
```

注册语义校验要求 `source_backend="TUSHARE"` 时 `tushare_endpoint_id` 非空且唯一
Tushare registry 中该 endpoint 为 `ACTIVE_VERIFIED`；`source_backend="DIRECT"` 时该
字段必须为 `null`。`required_for_event_types` 必须是 snapshot
`active_event_types` 的子集，不能用一个未激活类型扩大 readiness 或无事件声明。
每个 registration 必须解析到唯一、hash 匹配的 `GeopoliticalSourceAdapterContract`；URL、
cursor/query、actor/region、时间、许可、轮询和截断字段只能来自该强类型合同，不能由
collector 默认值或 prose 补齐。每个 watchlist actor/event pair 和
watchlist region/event pair 都必须解析到唯一、hash 可重算的
`GeopoliticalCoverageRoute`；全局 event-family source 必须解析到显式 `GLOBAL` route。
`APPLICABLE` route 的 `required_source_ids` 必须非空，且全部 adapter 必须按
`subject_type` 显式覆盖对应 actor、region 或 `global_scope_capable=true`；其
`no_event_evidence_source_ids` 也必须非空、
是 required sources 的子集，且每个引用 adapter 都必须
`no_event_claim_capable=true`。`NOT_APPLICABLE` route 的两个 source 数组必须为空，只能使用覆盖范围合同登记的
`NO_REGISTERED_MATERIAL_LINK` 且 `route_status=NOT_APPLICABLE`，不能运行时省略 pair 或用自由文本跳过；前三个 reason code
只能用于 `APPLICABLE`；`REGION_WATCHLIST_SCOPE` 只能用于 REGION route，
`ISSUER_OR_TARGET_WATCHLIST_SCOPE` 只能用于 ACTOR route，GLOBAL route 只能使用
`MATERIAL_A_SHARE_TRANSMISSION_SCOPE`。readiness 只接受
`ACTIVE_VERIFIED` 的 applicable route。每个 applicable route 的每个 required source 必须
物化一条 `GeopoliticalRouteSourceCoverage`；event-family 全局源必须在 manifest 中注册为
显式 GLOBAL route，不能绕过 route 粒度。`coverage_query_key` 固定为
`coverage_route_id + source_id + scope_query_hash` 的 canonical hash，三者任一变化都产生
新 query key。一个 source 对多个 actor/region/scope query 的成功不能互相替代，也不能因
source-level 最近一次成功就把其他 route 标为健康。

每个 `GeopoliticalEventTypeCoverage.required_query_keys` 必须等于该 event type 全部
applicable ACTOR/REGION/GLOBAL route 的 required query key 排序去重集合；healthy/unhealthy 必须
不相交且并集恰好等于 required query keys。
`required_source_ids/healthy_source_ids` 只作为按 query 聚合后的诊断集合，不能作为 readiness
分母；`no_event_evidence_source_ids` 必须等于全部 applicable route 的同名集合并集，
`no_event_evidence_query_keys` 必须等于这些 route/source 实际物化且具备 no-event
能力的 query key 排序去重集合。
collector 或模型不能删去失败 query/source 来获得 no-event 状态。
`COVERAGE_CONFIRMED_NO_EVENT` 只在全部 required query 健康、query complete、没有匹配事件，
且 `no_event_evidence_query_keys` 恰好覆盖每个 route 的 no-event evidence query、全部健康并
通过 adapter capability/hash 校验时成立；
发现事件时 no-event evidence 数组仍保留作 coverage audit，但不得改变 `EVENTS_PRESENT`。

`geopolitical_event_id` 优先使用官方 action/legal instrument/reference number；没有官方
编号时，由注册 event type、规范化 actor、target/scope 和首次可见日期生成 provisional
ID。标题、抓取时间和后续影响描述不进稳定 ID。provisional cluster 被官方记录确认时用
append-only alias/supersession 连接，不能原地合并或让两个独立事件因共享关键词碰撞。
`normalized_content_hash` 先去模板、跟踪参数和转载前缀，再做内容去重。
每次轮询都追加不可变 `GeopoliticalSourcePollObservation`，至少保存
`coverage_route_id/coverage_route_hash/source_id/scope_query_hash/coverage_query_key`、
actor/region scope、started/completed time、HTTP/API status、row count、
pagination/truncation、schema hash、response content hash、parse result 和 error class；
`GeopoliticalRouteSourceCoverage` 只能从同一 query key 的观察记录确定性派生，不能用同
source 的其他 query 成功覆盖失败，也不能原地把失败轮询改成成功。

事件 verification 也必须由 evidence catalog 确定性派生：
`OFFICIAL_CONFIRMED` 至少解析到一个覆盖该 actor/region/event route、当时
`ACTIVE_VERIFIED` 的 `OFFICIAL_PRIMARY` source；`MULTISOURCE_CONFIRMED` 至少解析到两个
通过下述 publisher/upstream/content 独立性检查的 approved source；否则只能为
`UNCONFIRMED/CONFLICT`。`primary_source_tier` 必须等于全部有效 source 中最高的 tier，
不能由 collector 或模型自报。`time_status=VERIFIED` 必须同时有非空 `published_at` 和
可回查的发布时间证据；缺一即为 `UNVERIFIED`。这些字段与 source evidence 不一致时
snapshot 拒绝，不能只在 prompt 中提醒。

Geopolitical registry 不复制 Tushare 权限状态。当前四个无权限 endpoint 只存在于第
6.1 节唯一 Tushare registry，且不创建 Geopolitical registration；未来若某个 Tushare
endpoint 获准加入事件层，registration 只保存 `tushare_endpoint_id: TushareEndpointId`
外键，权限和启用状态仍从唯一 registry 派生，禁止两处各自改状态。

上线 source matrix 固定为：

| event family | required 连续覆盖 | 允许确认事件 | 允许声明无事件的条件 |
| --- | --- | --- | --- |
| 制裁、出口管制、关税/贸易限制 | 中国外交部/商务部；UN；OFAC/BIS/USTR；EU Council/Official Journal 中与冻结 actor/watchlist 匹配的官方目录；GDELT discovery | 官方 action/legal instrument，或两个独立 approved publisher | 该 event family 全部 applicable ACTOR/REGION/GLOBAL route 的 required query 健康、未截断、freshness 合格且无匹配记录；不要求每个受制裁 actor 自己发布公告 |
| 航运中断 | MARAD Maritime Security Communications with Industry advisories、UKMTO advisories，以及 GDELT discovery | MARAD/UKMTO 官方 advisory；或两个独立 approved publisher | 该 event family 全部 applicable route 的 required query 健康、未截断且无匹配记录；适用 REGION route 必须物化 manifest 登记的 MARAD、UKMTO 和 GDELT scope query |
| 武装冲突 | GDELT discovery、UN 官方连续发布源，以及已经通过 preflight 的 actor 政府安全公告 | actor/UN 官方公告；或两个独立 approved publisher | 该 event family 全部 applicable route 的 required query 健康、未截断且无匹配记录；actor 官方 adapter 只有在对应 route 登记为 required 时才要求健康 |
| 外交升级/缓和 | 中国外交部、EEAS、US State、已验证 actor 外交目录和 GDELT discovery | actor 官方公告；或两个独立 approved publisher | 该 event family 全部 applicable route 的 required query 健康、未截断且无匹配记录；不得以某一个 actor route 健康替代其余 route |

上述表只有在一个可提交、版本化的 `GEOPOLITICAL_INITIAL_SOURCE_MANIFEST` 中解析为 exact
registration、adapter contract 和 actor/region/global event coverage route 后才算“固定”。初始
production source closure 必须恰好逐行登记
`cn_mfa_releases`、`cn_mofcom_export_control`、`un_sc_sanctions`、`ofac_recent_actions`、
`bis_federal_register`、`ustr_actions`、`eu_council_sanctions`、`eurlex_official_journal`、
`marad_msci`、`ukmto_advisories`、`gdelt_event_gkg`、`un_conflict_releases`、
`us_state_releases` 和 `eeas_releases`。registration 只保存身份、provider、外键和来源独立性
字段；canonical URL/API、分页或增量 cursor、continuous query、
actor/region/global/event coverage、
时区、发布时间字段、许可、poll interval、截断检测及 `no_event_claim_capable` 必须全部进入
其引用的 `GeopoliticalSourceAdapterContract`。manifest 必须同时提交这些强类型 adapter、
逐 actor/region/global event route、content hash 和 30 日 preflight 结果；只列 source ID，或只在 Markdown/
fixture 中写 adapter 默认值，都不代表 READY。
除下文显式登记为 `OPTIONAL_CONTEXT/PREFLIGHT_REQUIRED` 的 OCHA 外，初始 manifest
不得增加未列 source；后续增加 required/discovery source 必须发布新的 source/coverage
contract 和完整 route closure，不能只向数组追加 ID。

初始 `coverage_scope_version` 必须显式提交 actor/jurisdiction 和 region，而不能运行时解释
“相关 actor”。最低 actor/jurisdiction 集合固定为中国、美国、欧盟、俄罗斯、乌克兰、伊朗、
以色列、朝鲜和韩国；最低 region 集合固定为台海、南海、红海/曼德海峡、霍尔木兹海峡、
黑海及朝鲜半岛。每个 actor/event pair 和 region/event pair 必须在
`GeopoliticalCoverageScopeContract` 中各有一条明确的 applicable/not-applicable continuous
coverage route；不得只把 region 写入 adapter metadata 而不进入 route closure。route 可以由
GDELT actor/region query、UN/发行司法辖区官方目录和已经验证的 actor 官方 adapter 组成，
但不能只有一次性搜索。actor 自身官方 adapter 是优先
确认源，不再是所有 actor 的全局 readiness 前提；route 缺失或所列 required source 未通过
preflight 时只使对应 event type fail closed，不能被未登记来源替代。初始 manifest 必须逐项
证明上述九个 actor、六个 region 在七个 active event type 中所有 applicable/not-applicable
组合的 route closure，并登记 event-family GLOBAL route，不能仅列 source ID。
approved publisher registry 也必须作为 manifest 的子表提交 exact domain、组织所有者、
允许 event family 和 upstream 识别规则；未登记 domain 永远不能成为第二确认源。

初始 `active_event_types` 只包含上表七个具名类型，不包含 `OTHER_REGISTERED`。
`OTHER_REGISTERED` 的 adapter 默认 `no_event_claim_capable=false`，只能保存 context/risk record，
不能扩大“无事件”的含义，也不参与全局 no-event reducer。它只有在发布新 event-type
contract、required 连续 source family、watchlist scope、event priority，并将至少一个
adapter contract 明确设为 `no_event_claim_capable=true` 后，才可作为具名子类型加入 active
集合；不能直接用 catch-all 字符串加入。每个 active event type 必须恰有一条 coverage
行；新增类型若缺 required contract，snapshot 构建直接失败，不得沿用其他类型健康状态。

OCHA ReliefWeb API V2 只预注册为武装冲突/人道事件的
`OPTIONAL_CONTEXT/PREFLIGHT_REQUIRED`：当前 API 要求预先获批的 `appname`，且报告正文
沿用原始信息伙伴的版权。取得 appname、完成 30 日覆盖/延迟与许可审计前，不创建生产
client，不计 required coverage、两源确认或“无事件”证明；即使启用也只保存元数据、
source URL、时间和 hash，不把许可正文写入公开 artifact。

两个来源只有在 `publisher_organization_id` 不同、`upstream_origin_family` 不同，且
canonical URL、官方 reference/action ID 和 `normalized_content_hash` 均未显示转载/共同
上游时才算独立。聚合站、同一通讯社、同一官方稿镜像和引用同一 advisory 的二次发布
全部归为一个 origin family；判不清时不计第二个确认源。approved-domain registry 必须
为每个 publisher 保存组织所有者、允许的 event family、上游识别规则和生效版本。

可得性和时效规则：

1. `coverage_scope_version` 冻结对 A 股有实质传导可能的 actor/watchlist、event type、
   region 和 channel；“无重大事件”只表示该注册范围内未发现，不声称覆盖全世界。
   required family 必须逐项满足上表，不能只覆盖制裁/出口管制后推断冲突、航运或外交
   也平静。任何 required source `STALE/UNAVAILABLE/SCHEMA_DRIFT`、watchlist
   actor/event 或 region/event 无 ACTIVE coverage route、GLOBAL route 缺失或 query 被截断时，
   对应 event type 为 `COVERAGE_UNAVAILABLE`，snapshot
   拒绝，缺失不能转换成 `NEUTRAL`。
2. provider 是否“实时”不能靠文档假定。上线前对每个 adapter 做至少 30 个自然日
   preflight，记录成功率、schema drift、`first_seen_at-published_at` 的 p50/p95/p99 和
   时区可解析率。只有 p95 publication-to-capture lag、轮询成功率和 schema 稳定性均
   通过版本化 SLO 的源才可 required；未达标的源降为 discovery/context 或拒绝上线。
3. 初始采集目标不是 provider 保证：GDELT 按其 15 分钟文件节奏每 15 分钟轮询，
   `max_capture_age=30` 分钟；官方机器可读列表/RSS/API 每 15 分钟轮询，HTML/公告目录
   每 30 分钟轮询，A 股交易时段及隔夜全球风险窗口的初始 max capture age 为 60 分钟。
   30 日 preflight 后必须冻结实际合同值；正式运行只能收紧，放宽需新合同和重新
   shadow。Tushare `major_news/news` 不参加 preflight，因为权限已明确拒绝；任何代码
   路径发起调用都是合同失败。
4. `published_at` 不可靠时保存原始时间并令 `time_status=UNVERIFIED`；该记录可触发
   人工/官方复核，但不能证明事件在某个 `as_of` 已公开。historical replay 只接受
   `first_seen_at<=as_of` 的 `LOCAL_CAPTURE`，或具备当时官方目录/版本证据的
   `OFFICIAL_VINTAGE`；后来下载的 GDELT/新闻回填不得伪造历史及时性。
5. 事件 revision append-only。公告、实施、升级、降级、解除分别形成有 effective
   time 的状态迁移；后续报道不能回写首次发现时间。冲突状态不得支持方向输出。
6. “没有重大事件”也是有覆盖条件的结论：只有每个 `active_event_types` 成员都恰有一条
   `COVERAGE_CONFIRMED_NO_EVENT`、全部 required source 健康、查询未截断、去重/解析
   成功且 freshness 合格时，才允许全局 `COVERAGE_CONFIRMED_NO_MATERIAL_EVENT`。
   有事件时对应 event type 必须为 `EVENTS_PRESENT`；任一类型为
   `COVERAGE_UNAVAILABLE` 时全局为 `COVERAGE_INCOMPLETE` 且阶段拒绝，而不是输出
   空数组或中性。
7. `geopolitical` 的 EVENT claim 必须来自 `OFFICIAL_CONFIRMED` 或
   `MULTISOURCE_CONFIRMED`；未确认项只能是带观察触发器的 `RISK_FLAG`。模型不得
   虚构影响百分比、把“发现时间”当“生效时间”，或把 `eco_cal` 触发时间当事件状态。
8. 原始新闻正文与许可内容只保存在本地私有 cache；公开 artifact 只保留 schema、
   哈希、source/time/status 元数据、脱敏 fixture 和 coverage 审计。

`geopolitical` 的 event-triggered Darwinian 样本只由 verified 事件创建；同一
`causal_dedupe_key` 的多次转载不增加样本。事件窗口重叠时仍按第 10.1 节冻结 priority
选择，`UNCONFIRMED/CONFLICT` 或 source coverage 不健康只产生 eligibility exclusion，
不能事后在市场路径已知后补成评分样本。

## 7. 数据就绪门与失败语义

每个 series map 必须预注册：

- 数据集/series 代码。
- 来源与频率。
- 单位与季调状态。
- 发布时间来源。
- revision/vintage 能力。
- `required`。
- `owner_agent`。
- 频率感知 freshness。
- `release_calendar_id` 与 `trading_calendar_id`；不适用的一项显式为 `null`。

运行时：

1. `get_china_macro_snapshot` 必须具备已注册的中国增长、价格、信用、外需和财政
   required 维度；`get_central_bank_snapshot` 必须具备第 6.2 节五个 PBOC/中国利率
   required family，其中 `china_money_market_curve` 至少要求已验证的 `shibor` 与
   `yc_cb`，`shibor_quote` 只作 optional 交叉诊断。任一维度缺失不得由政策日历、LLM
   摘要或相邻 endpoint 替代。
2. `get_us_macro_snapshot` 必须同时具备第 6.3 节增长/生产、价格、就业、需求/贸易
   四个 required 组件；`get_us_financial_conditions_snapshot` 必须同时具备 Fed/流动性、
   美国名义与实际曲线、信用/金融压力、广义美元/人民币四个 required 组件。实体摘要
   不能补金融组件，金融市场路径也不能补实体 release。
3. 欧盟实体经济 snapshot 必须同时具备四个 required 组件、六个 required series branch：
   增长/生产要求 EU27 实际 GDP 与工业生产，价格要求 EU27 HICP，就业要求 EU27
   失业率，需求/贸易要求 EU27 零售量以及域外出口、进口两条 flow。
4. 欧元区金融条件 snapshot 必须同时具备以下五个 required 维度：
   ECB 当前政策利率/最近决议、€STR、欧元区主权曲线、欧元区银行信用/融资
   成本，以及欧元汇率/官方金融压力。
5. 欧盟经济只在四个 required 组件及其六个 series branch 全部 PIT 合法时为 READY；欧元区金融条件只
   在五个 required 维度全部 PIT 合法时为 READY。欧元区数据不能替代缺失的
   EU27 实体维度，非欧元区数据也不能替代 ECB/欧元区金融维度。
6. `get_commodity_conditions_snapshot` 的能源、工业金属、黄金、农产品/食品四个
   required 市场组件必须全部 PIT 合法；`get_market_positioning_snapshot` 的全市场资金、
   行业轮动、ETF universe、ETF share/adjusted-price 四个 required 分支必须全部 PIT 合法，
   并通过 `fund_adj` 与 share/corporate-action adjustment 校验。
   `get_market_breadth_snapshot` 还须满足第 11 节 90% 核心 coverage。optional 库存、
   持仓或龙虎榜不能补 required 缺口。
7. freshness 使用 series map 中预注册的 `expected_next_release_at`、grace 和
   hard cap。统计发布序列以当前 reference period 的 `first_released_at` 为
   hard-cap 锚点，后续 revision/vintage/retrieval 不刷新该锚点；日频市场序列
   以最新 observation date 和下一预期交易日为锚点；ECB/Fed policy state 以最近决议
   effective time 和下一已排期决议为锚点，PBOC MPC/执行报告分别以各自正文
   `first_published_at` 和已注册 `expected_next_release_at` 为锚点。
8. 当 `as_of > expected_next_release_at + grace` 或超过 hard cap 任一条件成立
   时即过期，即
   `expires_at=min(expected_next_release_at+grace, freshness_anchor+hard_cap)`。
   日频默认 grace/hard cap 必须由 series 自身日历解释，禁止全局套用欧盟工作日：

   | series family | calendar | 默认 grace / hard cap |
   | --- | --- | --- |
   | 中国市场/PBOC 日频 | `CN_A_SHARE` 或 `PBOC_WORKDAY` | 下一相应工作日后 2 / 3 个相应工作日 |
   | 美国 rates/FX/market 日频 | `US_FEDERAL_RESERVE`、`US_TREASURY` 或 instrument 注册日历 | 下一相应工作日后 2 / 3 个相应工作日 |
   | 欧元区 rates/market 日频 | `TARGET2`/ECB 注册日历 | 下一相应工作日后 2 / 3 个相应工作日 |
   | 中国期货/ETF/股票行情 | 对应交易所日历 | 下一交易日后 1 / 2 个交易日 |
   | 月频统计发布 | 对应官方 release calendar | 下一预期发布后 10 个自然日 / 首发后 75 个自然日 |
   | 季频统计发布 | 对应官方 release calendar | 下一预期发布后 15 个自然日 / 首发后 150 个自然日 |
   | PBOC MPC/货币政策执行报告 state | 已注册 PBOC expected-release calendar | 下一预期发布后 15 个自然日 / 最近正文首次公开后 150 个自然日 |
   | ECB/Fed policy decision state | 对应央行决议日历 | 下一决议后 5 个自然日 / 最近决议后 90 个自然日 |

   上表是 family 默认值；第 6.2 节 `pboc_policy_stance` 两个分支显式采用其中 PBOC 行，
   不得再套用 ECB/Fed 的 90 日上限。series 可更严格但不能更宽松；官方改期必须形成带来源的 calendar revision，不能
   静默延长。日历闭市/节假日由冻结 calendar version 决定，不能把自然日或另一区域
   工作日临时当交易日。
   required 发布序列无法得到 PIT 合法的 `expected_next_release_at` 时 snapshot
   不得 READY；不能只依赖最近一次 retrieval 或 revision 时间推断 freshness。
9. `eco_cal` 检查查询截断、时区、冲突、forecast 可见性和官方核验。
10. `geopolitical` 按每个 active event type 检查 required source 的最近成功轮询、schema、
   scope query、截断、publication-to-capture lag 和 max capture age；未通过时不能借用
   另一 event family 的 coverage 或以空事件集表示平静。
11. 网络失败只允许使用 `as_of` 前已缓存、同源且未过期的版本。
12. World Bank 或其他 `CONTEXT_ONLY` 数据不能填补 required 缺口。
13. required 数据缺失、过期、冲突或 PIT 不可证明时，该 Agent 阶段拒绝。
14. 缺失数据绝不转换成 `NEUTRAL`。
15. 任一 Macro Agent 未接受时不得生成正式下游 Macro 输入；缺失角色不能转换为
    `NEUTRAL`、零权重或被其他角色替代。
16. 现有“读取本地 JSON 且 evidence 非空即成功”的通用 snapshot loader 只能保留为
    fake fixture adapter。production READY 必须逐组件校验 source-map ID、required coverage、
    release/vintage/freshness、schema hash 和 evidence lineage；一个任意 evidence row 或手写
    snapshot 文件不能满足任何 required matrix。

## 8. 波动率重新归属

- VIX、美国隐含波动和美国金融压力进入
  `us_financial_conditions`。
- 欧元区已注册的 CISS 金融压力进入 `euro_area_financial_conditions`；初始 source map
  不包含未注册的欧元区隐含波动序列。
- 中国实现波动率只进入 `cro` 风险状态，不形成 Macro 方向票；Execution 只消费已解析的
  CRO control、CRO-adjusted frozen intents 和批准约束，不再独立读取波动率形成第二次判断。
- 不再把中国实现波动率称为 iVX。
- 不再保留独立 `volatility` Darwinian 角色。

## 9. 直接下游消费

不生成六因子、综合分数或 Macro stance。十个
`AcceptedAgentOutputRecord` 的 `accepted_output_id/hash` 作为十个独立的命名
graph-state 引用保存；每个引用必须解析到同一 `graph_run_id/cohort_id/language/as_of` 下对应
Agent 的 `MACRO_TRANSMISSION` record，各自的 Agent execution `run_id` 可以不同且必须
作为 `source_agent_run_id` 保留。不存在新的持久化 Macro bundle；运行时只在
调用下游节点时从这些 record 的 `EvidenceLineageEnvelope<AcceptedMacroTransmission>`
构造传输数组，并在模型边界逐项投影为
`ModelVisibleEvidenceLineageEnvelope<ModelVisibleAcceptedMacroTransmission>`，不能把内部 accepted
record 或 accepted 对象原样序列化给模型。graph state 中出现裸 envelope、payload 或
“latest accepted”查询均为合同失败。

现有 `aggregate_l1` 替换为非 LLM 的 `macro_input_gate`。它只负责等待并验证
十个命名输出、解析 PIT 合法的 Darwinian 记录、计算下述使用比例并放行
下游；不生成新的 Macro 语义输出、分数或 stance。该确定性门不是逻辑
Agent，不计入 28 个逻辑 Agent 或 29 个 Agent 执行阶段。

每个直接输入附加统一可靠度元数据：

```ts
type DirectionalSourceLayer = "MACRO" | "SECTOR" | "SUPERINVESTOR";
type DirectionalSourceLayerSignalState =
  | "SIGNAL_SET_READY"
  | "NO_DIRECTIONAL_SIGNAL";

interface DownstreamWeightedAgentInput<L extends DirectionalSourceLayer, T> {
  graph_run_id: string;
  source_agent_run_id: string;
  cohort_id: string;
  language: "en" | "zh";
  as_of: string;
  accepted_output_id: string;
  accepted_output_hash: string;
  source_layer: L;
  source_entry_status: "ACCEPTED_OUTPUT";
  source_layer_signal_state: DirectionalSourceLayerSignalState;
  agent_id: string;
  output: EvidenceLineageEnvelope<T>;
  darwin_weight: number;
  operational_reliability: number;
  effective_reliability: number;
  usage_share: number;
  darwin_weight_record_id: string;
  darwin_weight_effective_at: string;
  operational_reliability_record_id: string;
  operational_reliability_effective_at: string;
  operational_reliability_contract_version: string;
  reliability_adapter_contract_version: string | null;
  calibration_state_id: string | null;
  calibration_state_effective_at: string | null;
  darwinian_contract_version: string;
  darwinian_snapshot_id: string;
  source_layer_snapshot_id: string;
  source_layer_snapshot_hash: string;
  consumer_input_snapshot_id: string;
  consumer_input_snapshot_hash: string;
  causal_evidence_resolution_set_id: string;
  causal_evidence_resolution_set_hash: string;
}

type DownstreamMacroInput =
  DownstreamWeightedAgentInput<"MACRO", AcceptedMacroTransmission> & {
    agent_id: MacroAgentId;
    source_layer_signal_state: "SIGNAL_SET_READY";
  };
type DownstreamStandardSectorInput =
  DownstreamWeightedAgentInput<"SECTOR", AcceptedSectorSelection> & {
    agent_id: StandardSectorAgentId;
  };
type DownstreamRelationshipInput =
  DownstreamWeightedAgentInput<"SECTOR", AcceptedRelationshipGraph> & {
    agent_id: "relationship_mapper";
  };
type DownstreamSuperinvestorInput =
  DownstreamWeightedAgentInput<
    "SUPERINVESTOR",
    AcceptedSuperinvestorSelection
  > & {
    agent_id: SuperinvestorAgentId;
  };

interface DownstreamSuperinvestorStageSkipInputBase<
  A extends SuperinvestorAgentId,
> {
  graph_run_id: string;
  source_agent_run_id: null;
  cohort_id: string;
  language: "en" | "zh";
  as_of: string;
  source_layer: "SUPERINVESTOR";
  source_entry_status: "NO_EVALUATION_OBJECT";
  source_layer_signal_state: "NO_DIRECTIONAL_SIGNAL";
  agent_id: A;
  output: EvidenceLineageEnvelope<
    NoEvaluationObjectStageSkipRecord<A>
  >;
  usage_share: 0;
  source_layer_snapshot_id: string;
  source_layer_snapshot_hash: string;
  consumer_input_snapshot_id: string;
  consumer_input_snapshot_hash: string;
  causal_evidence_resolution_set_id: string;
  causal_evidence_resolution_set_hash: string;
}

type DownstreamSuperinvestorStageSkipInput = {
  [A in SuperinvestorAgentId]:
    DownstreamSuperinvestorStageSkipInputBase<A>;
}[SuperinvestorAgentId];

type DownstreamAgentInput =
  | DownstreamMacroInput
  | DownstreamStandardSectorInput
  | DownstreamRelationshipInput
  | DownstreamSuperinvestorInput
  | DownstreamSuperinvestorStageSkipInput;

interface DownstreamDecisionInputBase<T> {
  graph_run_id: string;
  source_agent_run_id: string;
  cohort_id: string;
  language: "en" | "zh";
  as_of: string;
  accepted_output_id: string;
  accepted_output_hash: string;
  source_layer: "DECISION";
  output: EvidenceLineageEnvelope<T>;
  darwin_application_mode: "EVOLUTION_ONLY";
  operational_reliability: number;
  operational_reliability_record_id: string;
  operational_reliability_effective_at: string;
  operational_reliability_contract_version: string;
  source_layer_snapshot_id: string;
  source_layer_snapshot_hash: string;
  consumer_input_snapshot_id: string;
  consumer_input_snapshot_hash: string;
  causal_evidence_resolution_set_id: string;
  causal_evidence_resolution_set_hash: string;
}

type DecisionRuntimeStageSkipEnvelope<
  A extends DecisionStageSkipAgentId,
> =
  | {
      stage_skip_origin: "OUTCOME_SCHEDULED";
      output: EvidenceLineageEnvelope<
        NoEvaluationObjectStageSkipRecord<A>
      >;
    }
  | {
      stage_skip_origin: "KNOT_CONTROL_SHADOW";
      output: EvidenceLineageEnvelope<
        KnotControlNoEvaluationObjectStageSkipRecord<A>
      >;
    };

interface DownstreamDecisionStageSkipInputBase<
  A extends DecisionStageSkipAgentId,
> {
  graph_run_id: string;
  source_agent_run_id: null;
  cohort_id: string;
  language: "en" | "zh";
  as_of: string;
  source_layer: "DECISION";
  darwin_application_mode: "EVOLUTION_ONLY";
  source_layer_snapshot_id: string;
  source_layer_snapshot_hash: string;
  consumer_input_snapshot_id: string;
  consumer_input_snapshot_hash: string;
  causal_evidence_resolution_set_id: string;
  causal_evidence_resolution_set_hash: string;
}

type DownstreamDecisionStageSkipInput =
  | {
      [A in "cro" | "autonomous_execution"]:
        DownstreamDecisionStageSkipInputBase<A> & {
          agent_id: A;
          source_layer_signal_state: "CONTROL_SET_READY";
        } & DecisionRuntimeStageSkipEnvelope<A>;
    }["cro" | "autonomous_execution"]
  | (DownstreamDecisionStageSkipInputBase<"alpha_discovery"> & {
      agent_id: "alpha_discovery";
      source_layer_signal_state: "NO_DIRECTIONAL_SIGNAL";
    } & DecisionRuntimeStageSkipEnvelope<"alpha_discovery">);

type DownstreamDecisionInput =
  | (DownstreamDecisionInputBase<AcceptedCroRiskReview> & {
      agent_id: "cro";
      source_layer_signal_state: "CONTROL_SET_READY";
    })
  | (DownstreamDecisionInputBase<AcceptedExecutionAssessment> & {
      agent_id: "autonomous_execution";
      source_layer_signal_state: "CONTROL_SET_READY";
    })
  | (DownstreamDecisionInputBase<AcceptedAlphaDiscovery> & {
      agent_id: "alpha_discovery";
      source_layer_signal_state: DirectionalSourceLayerSignalState;
    })
  | (DownstreamDecisionInputBase<AcceptedCioProposal | AcceptedCioFinal> & {
      agent_id: "cio";
      source_layer_signal_state: DirectionalSourceLayerSignalState;
    })
  | DownstreamDecisionStageSkipInput;
type ModelVisibleSectorAgentSelection =
  | {
      selection_status: "SELECTED";
      preferred_direction: PreferredSectorDirectionSubmission;
      least_preferred_direction: OptionalLeastPreferredDirection;
      persistence_horizon: "DAYS" | "WEEKS" | "MONTHS";
      key_drivers: SectorDriverSubmission[];
      risks: SectorRiskSubmission[];
      claims: Claim[];
      claim_refs: string[];
      preferred_security_status: "PICKS_PRESENT" | "NO_QUALIFIED_SECURITY";
      long_picks: SectorSecurityPickSubmission[];
      least_preferred_security_status:
        | "PICKS_PRESENT"
        | "NO_QUALIFIED_SECURITY"
        | "NOT_APPLICABLE";
      short_or_avoid_picks: SectorSecurityPickSubmission[];
    }
  | {
      selection_status: "NO_QUALIFIED_DIRECTION";
      preferred_direction: { status: "NO_QUALIFIED_DIRECTION" };
      least_preferred_direction: NoQualifiedAvoidDirectionSubmission;
      persistence_horizon: "DAYS" | "WEEKS" | "MONTHS";
      key_drivers: SectorDriverSubmission[];
      risks: SectorRiskSubmission[];
      claims: Claim[];
      claim_refs: string[];
      preferred_security_status: "NO_QUALIFIED_SECURITY";
      long_picks: [];
      least_preferred_security_status: "NOT_APPLICABLE";
      short_or_avoid_picks: [];
    };

interface ModelVisibleAcceptedSectorSelection {
  sector_agent_id: StandardSectorAgentId;
  selection: ModelVisibleSectorAgentSelection;
  directional_confidence: number;
  abstention_confidence: number;
}

type ModelVisibleSuperinvestorSelection =
  | {
      selection_status: "SELECTED";
      holding_period: "WEEKS" | "MONTHS" | "YEARS";
      picks: SuperinvestorSecurityPickSubmission[];
      key_drivers: SectorDriverSubmission[];
      risks: SectorRiskSubmission[];
      claims: Claim[];
      claim_refs: string[];
    }
  | {
      selection_status: "NO_QUALIFIED_CANDIDATES";
      holding_period: "WEEKS" | "MONTHS" | "YEARS";
      picks: [];
      key_drivers: SectorDriverSubmission[];
      risks: SectorRiskSubmission[];
      claims: Claim[];
      claim_refs: string[];
    };

interface ModelVisibleAcceptedSuperinvestorSelection {
  superinvestor_agent_id: SuperinvestorAgentId;
  selection: ModelVisibleSuperinvestorSelection;
  directional_confidence: number;
  abstention_confidence: number;
}

interface DownstreamModelInputBase {
  graph_run_id: string;
  cohort_id: string;
  language: "en" | "zh";
  as_of: string;
  source_layer_signal_state: DirectionalSourceLayerSignalState;
  agent_id: string;
  usage_share: number;
  source_layer_snapshot_id: string;
  source_layer_snapshot_hash: string;
  causal_evidence_resolutions: [
    ModelVisibleCausalEvidenceContributionResolution,
    ...ModelVisibleCausalEvidenceContributionResolution[],
  ];
}

type ModelVisibleSuperinvestorStageSkipInput = {
  [A in SuperinvestorAgentId]: DownstreamModelInputBase & {
    source_layer: "SUPERINVESTOR";
    source_entry_status: "NO_EVALUATION_OBJECT";
    source_layer_signal_state: "NO_DIRECTIONAL_SIGNAL";
    agent_id: A;
    usage_share: 0;
    output: ModelVisibleEvidenceLineageEnvelope<
      ModelVisibleNoEvaluationObjectStageSkipRecord<A>
    >;
  };
}[SuperinvestorAgentId];

type DownstreamModelInput =
  | (DownstreamModelInputBase & {
      source_layer: "MACRO";
      source_entry_status: "ACCEPTED_OUTPUT";
      source_layer_signal_state: "SIGNAL_SET_READY";
      agent_id: MacroAgentId;
      output: ModelVisibleEvidenceLineageEnvelope<ModelVisibleAcceptedMacroTransmission>;
    })
  | (DownstreamModelInputBase & {
      source_layer: "SECTOR";
      source_entry_status: "ACCEPTED_OUTPUT";
      sector_output_kind: "STANDARD_SELECTION";
      agent_id: StandardSectorAgentId;
      output: ModelVisibleEvidenceLineageEnvelope<ModelVisibleAcceptedSectorSelection>;
    })
  | (DownstreamModelInputBase & {
      source_layer: "SECTOR";
      source_entry_status: "ACCEPTED_OUTPUT";
      sector_output_kind: "RELATIONSHIP_GRAPH";
      agent_id: "relationship_mapper";
      output: ModelVisibleEvidenceLineageEnvelope<ModelVisibleAcceptedRelationshipGraph>;
    })
  | (DownstreamModelInputBase & {
      source_layer: "SUPERINVESTOR";
      source_entry_status: "ACCEPTED_OUTPUT";
      agent_id: SuperinvestorAgentId;
      output: ModelVisibleEvidenceLineageEnvelope<ModelVisibleAcceptedSuperinvestorSelection>;
    })
  | ModelVisibleSuperinvestorStageSkipInput;
```

`DownstreamWeightedAgentInput` 以及由 weighted accepted output 与显式 Superinvestor
stage-skip 组成的封闭 union `DownstreamAgentInput` 是 runtime/audit 内部合同，不得原样
序列化进模型 prompt；该 union 没有 Decision branch，不能通过泛型实例化把 Decision
包装成带权输入。stage-skip branch 固定 `usage_share=0`，且不得携带 Darwin weight、
operational/effective reliability、adapter/calibration state 或任何 weight record 外键。
每个 weighted/Decision accepted branch 的 `accepted_output_id/hash` 必须解析到 owner、
kind、graph/source run、origin、cohort/language variant 和 envelope 均匹配的
`AcceptedAgentOutputRecord`；stage-skip branch 的 `source_agent_run_id` 必须为 null，且
不得伪造 accepted-record 字段。
`DownstreamSuperinvestorStageSkipInput`、`DownstreamDecisionStageSkipInput` 和
`ModelVisibleSuperinvestorStageSkipInput` 都按具体 Agent 展开为 mapped union，外层
`agent_id` 与 envelope 内 skip record 的 `agent_id` 必须在类型上相同，不能只靠运行时
字符串校验。Decision runtime 的 outcome-scheduled skip 使用
`NoEvaluationObjectStageSkipRecord`；仅 CIO KNOT 依赖子图的 control-only skip 使用
`KnotControlNoEvaluationObjectStageSkipRecord`。两者可投影成同一 model-visible DTO，但
不得跨 namespace、graph 或 frozen object set 互换。
模型只看到 `DownstreamModelInput`：独立输出、最终 `usage_share` 和共同 snapshot
引用，以及由同一 snapshot 确定性生成的 model-visible causal resolution 集合。
其 `output` 必须通过 `ModelVisibleEvidenceLineageEnvelope` 构造，任何
`evidence_bundle_ids` 字段出现都属于 schema 泄漏并拒绝。
同一次 consumer invocation 的所有输入必须绑定同一个
`consumer_input_snapshot_id/hash` 和 `causal_evidence_resolution_set_id/hash`；resolution
set 中的 source-layer refs 必须与实际输入逐项一致，集合内容按 causal key 排序并覆盖所有
envelope 的全部 key。缺失、多余、hash 不匹配或消费者自行重算均拒绝。`darwin_weight`、
operational/effective reliability、record ID、effective time、
Darwinian contract/snapshot、adapter contract 和 calibration state 全部留在 runtime；这既
隐藏 research knobs，也避免模型反推或改写权重机制。
Macro 下游 payload 必须使用显式白名单 DTO
`ModelVisibleAcceptedMacroTransmission`；`agent_contract_version`、prompt/execution/
component-weight version、`model_confidence` 和 `deterministic_data_quality` 只留内部
accepted/audit。不得把 `AcceptedMacroTransmission` 直接放入 model-visible envelope，或用
通用序列化器在运行时“删几个字段”代替白名单。
Sector 下游 payload 必须使用显式白名单 DTO `ModelVisibleAcceptedSectorSelection`，不能对
内部 accepted 类型只做局部 `Omit`；agent/prompt/execution/registry 版本、pairwise matrix、
comparison/least-eligibility audit ID/hash、原始 submission `confidence` 和
`model_confidence` 均留在 runtime，不能通过通用泛型或嵌套 `selection` 重新泄漏。
`relationship_mapper` 不是标准选择输出，必须使用独立
`ModelVisibleAcceptedRelationshipGraph` 和
`sector_output_kind=RELATIONSHIP_GRAPH`；factual/predictive edges、可见 claims 与校准后的
`directional_confidence` 可传递，behavior/version、accepted attribution 和 edge
validation/scoring audit 不得进入模型。九个标准 Sector 使用
`sector_output_kind=STANDARD_SELECTION`，两类 payload 不得互相反序列化。
Superinvestor 同样必须通过
`ModelVisibleAcceptedSuperinvestorSelection` 序列化，不能把内部
`AcceptedSuperinvestorSelection` 直接作为泛型参数。两层 raw submission attribution
只留 submission audit，解析后的 `accepted_macro_input_attributions` 只留 accepted/runtime
audit；二者均不进入 model-visible 上游内容，避免下游重复消费上游对 Macro 的使用审计。
Sector/Superinvestor 的 model-visible output 只保留校准后的
`directional_confidence` 与独立的 `abstention_confidence`，禁止再暴露语义不明的通用
accepted `confidence`；`model_confidence`、calibration curve/样本和 adapter provenance
只在内部 audit payload。
Decision-to-Decision 交接不使用上述通用 `DownstreamModelInput` union，而由
`get_execution_snapshot()`/`get_cio_decision_snapshot()` 的显式白名单 DTO 承载；其 runtime
侧仍必须使用封闭的 `DownstreamDecisionInput`、`EvidenceLineageEnvelope` 和同一
consumer-input `CausalEvidenceResolutionSet`。CRO 约束或 Alpha discovery output 与上游共享 causal
key 时只保留一份独立证据计数，硬约束本身仍不受 usage share 缩放。
`get_cro_risk_snapshot()` 只能嵌入本 run 的 `ModelVisibleAcceptedCioProposal`，并从其
完整目标组合确定性生成 pre-CRO candidate universe；不得直接从 Alpha 或其他上游另加
候选。
`get_execution_snapshot()` 只能嵌入 `ModelVisibleAcceptedCioProposal` 和
`ModelVisibleAcceptedCroRiskReview`，或在 CRO 无评价对象时嵌入唯一匹配的
`ModelVisibleNoEvaluationObjectStageSkipRecord<"cro">`；
`get_cio_decision_snapshot()` 的 proposal phase 只能嵌入
`ModelVisibleAcceptedAlphaDiscovery` 或唯一匹配的
`ModelVisibleNoEvaluationObjectStageSkipRecord<"alpha_discovery">`；final phase 的
Decision-to-Decision 对象只能嵌入同 run/hash 的
`ModelVisibleAcceptedCioProposal`、`ModelVisibleAcceptedCroRiskReview`/对应 CRO skip，以及
`ModelVisibleAcceptedExecutionAssessment`/对应 Execution skip，同时必须重新挂载与
proposal phase 字节相同的 pre-CIO Macro/Sector/Superinvestor source-layer snapshots，供
final 核对证据并形成最终 attribution。final phase 不得再次把 Alpha DTO、上游候选或变化后的
source-layer snapshot 当成可新增候选源；Alpha 来源只能通过 proposal hash 继承。Superinvestor
stage skip 只通过 `DownstreamModelInput` 的专用 branch 传递。两类 stage skip 都只证明
冻结对象集合为空，不是 Agent accepted output、abstention 或 fallback，也不携带
operational reliability；其
`causal_dedupe_key` 由 `agent_id + frozen_object_set_hash + skip_reason` 确定性生成，并必须
与外层 envelope 唯一 key 一致。该 skip key 对应的
`CausalEvidenceContributionResolution` 固定为单一 contributing Agent、
`contributing_claim_refs=[]/interpretation_state=FACT_ONLY`；其他 accepted-output causal
key 的 contributing claim refs 必须非空。内部 accepted
版本、冻结对象 ID/hash、Macro attribution 和 operational reliability 不得通过 snapshot
序列化给模型。
`DownstreamDecisionInput` 不含 `darwin_weight/effective_reliability/usage_share` 或任何
weight record 外键；Decision 只有 `EVOLUTION_ONLY` evaluation track，operational reliability
仅作运行审计，不能变成连续权限或缩放系数。
`CONTROL_SET_READY` 固定用于 CRO/Execution 非方向性 Decision control payload；
Macro、Sector、Relationship 和 Superinvestor 输入不得使用该状态，Decision 硬约束存在时
也不得伪装成 `NO_DIRECTIONAL_SIGNAL`；Alpha/CIO 只能使用方向层状态，不得使用
`CONTROL_SET_READY`。

运行时只对十个 accepted transmission 的方向性解释计算信息份额：

```text
a_i = confidence_i * darwin_weight_i * operational_reliability_i
usage_share_i = a_i / sum(a_j)
```

其中 `effective_reliability=a_i`。`operational_reliability` 来自第 10.1 节每个
预注册生产运行槽位的 `OperationalOpportunityAudit`；没有可问责机会时为带原因的
`1.0 COLD_START`，
有记录后等于最近 30 个可问责机会中的 accepted opportunities / all accountable
opportunities，并包含当前已经验收的运行。窗口不足 30 时使用已有全部机会且记录
样本数，不得只等待满 30 后才暴露失败率。
所有实际计划调用 Agent 的 production graph slot 都必须先冻结唯一 `run_slot_id` 并最终写
一条 immutable operational audit：命中 outcome schedule 时为 `OUTCOME_SCHEDULED` 并绑定
`scheduled_sample_id`；事件型/固定槽位 Agent 在非评分日仍被调用供当日下游消费时为
`DOWNSTREAM_ONLY/scheduled_sample_id=null`。后者不创建伪 outcome opportunity、label 或
Darwinian 样本，但 accepted/failure 仍进入 operational reliability，避免只在有利评分日
统计稳定性。同一 Agent/graph slot 只能有一个 final operational disposition。
`OPPORTUNITY_SET_UNAVAILABLE` 只允许
`OUTCOME_SCHEDULED` 且该失败按第 10.1 节确实阻止本次 Agent 调用时作为 operational
exogenous reason；`DOWNSTREAM_ONLY` 本来就不要求 outcome opportunity set，不能借此跳过
当日调用或隐藏 failure。
KNOT champion/candidate 及 post-promotion champion shadow 只允许
`OUTCOME_SCHEDULED`；CIO 配对中的 `KNOT_CONTROL_SHADOW` 只允许
`DOWNSTREAM_ONLY/scheduled_sample_id=null`。控制依赖可引用外层 CIO research slot，但
agent_id 只能是 `alpha_discovery/cro/autonomous_execution`，不得把 CIO 的 scheduled
sample ID 冒充为依赖 Agent 自己的 outcome sample。
`operational_opportunity_audit_id` 在 run slot 冻结时预分配，因此 outcome audit 的
`AWAITING_AGENT_RUN` revision 可以先引用该 ID；模型调用结束后必须物化唯一 final
`OperationalOpportunityAudit` 和 hash。任何 terminal outcome revision、label 或 KNOT score
使用该 ID 时都必须解析到这条 final immutable audit；缺失、重复或 hash 无法重算即拒绝。
组件权重候选的确定性重合成不属于 Agent run slot，不创建
`OperationalOpportunityAudit`、outcome eligibility audit 或额外 outcome label；它只复用第
3.1 节冻结的组件信号和唯一主 `AgentOutcomeLabel` 计算 paired loss，也绝不进入任何
operational reliability。
预运行 required data/source coverage/PIT/opportunity-set 外生失败不进入分母；
outcome 未成熟或重叠窗口只属于评价状态，不能覆盖同日实际 downstream run 的 operational
accepted/failure。schema/语义拒绝、越权工具、模型伪造字段或模型请求 fallback 属于 Agent
可问责失败。不得只保留成功运行而删除失败记录。
每个 Agent 的 operational reliability 只消费该 Agent 自己
`OperationalOpportunityAudit.production_reliability_eligible=true/accountable=true` 的
`ACCEPTED` 或 `AGENT_FAILURE`；outcome eligibility audit 只负责评价/成熟状态，不再充当
operational 分母。不得把
另一个 Agent 的失败转嫁进本轨。CIO proposal/final 共用一个 logical operational
opportunity：proposal 或 final 任一由 CIO 自身失败时，该 opportunity 在 CIO 分母中只计一次；
只有 accepted `cio_final` 才能使该 opportunity 为 `ACCEPTED`，proposal 成功本身不提前
写第二条 operational success；
Alpha/CRO/Execution 阻断形成的 `DEPENDENCY_BLOCKED` operational audit 不进入 CIO 分母，
且必须引用依赖 Agent 同一 graph run 的 final
`blocked_dependency_operational_audit_id/hash`；但依赖 Agent 的原始
`AGENT_FAILURE` 仍只进入其自身分母。合法 Decision stage skip、pre-run/UNAVAILABLE 外生排除
和 outcome-maturity exclusion 均不进入 operational reliability。

`usage_share` 只是对十个独立输出的可审计
使用比例归一化，不合并、改写或压缩任何 Agent 的 transmission。

`darwin_weight` 必须为有限正数，并从同一 cohort/language、Agent/prompt behavior/execution
behavior/component 合同
轨道中选择 `effective_at<=as_of` 的最新版本。只有评分器能够证明匹配样本少于
30 个且该 track 从未发布过权重时，才允许确定性创建唯一的 1.0 initialization；
已有权重后窗口重新不足必须继续使用最后合法记录。匹配轨道缺失、版本不明或未来权重
不得静默回退。
operational reliability 也必须来自同一 track、合同版本且
`effective_at<=as_of`，并带可回查记录 ID；缺少 operational audit 历史时只能使用显式
`COLD_START` 记录。每个权重必须带可回查的记录 ID 和生效时间；十个输入必须使用同一
`darwinian_contract_version/darwinian_snapshot_id`，不能逐 Agent 混用不同合同或计算批次。
`macro_input_gate` 还必须为同一 graph/cohort/language 的十个有序 envelope、可靠度元数据和合同版本生成不可变
`source_layer_snapshot_id/hash`；所有直接消费者必须读取同一 Macro snapshot hash。该
hash 必须覆盖 `graph_run_id/cohort_id/language/as_of`；manifest 只证明该层传输内容一致，
不生成 bundle 分数或 stance。最终
`CausalEvidenceResolutionSet` 由每个下游 input assembler 在冻结该消费者获准读取的全部
source-layer snapshot 后生成，因此能够对 Macro、Sector、Relationship、Superinvestor
以及已获准的 Decision-to-Decision 输入之间的共同 causal key 一次去重，而不是只在单层
内部去重。

`sum(a_j)=0` 时正式下游消费拒绝，不能回退为等权。`usage_share` 只描述
direction、strength、channels、key drivers 和 `INTERPRETATION` claims 的相对
可靠度；FACT、EVENT、RISK_FLAG、原始数值和证据 lineage 必须完整可见，不能因
低权重或零份额被删除、截断或隐藏。特别是 CRO 必须看到全部已验证硬风险。

下游模型不能自行改写上游 `confidence/usage_share`，也根本接触不到
`darwin_weight/effective_reliability`。
为保留可观察归因，每个消费 Macro 信息的下游 submission 必须输出：

```ts
interface MacroInputAttributionSubmission {
  agent_id: MacroAgentId;
  target_type:
    | "SUBMISSION_SUMMARY"
    | "SECTOR_THESIS"
    | "SECURITY_PICK"
    | "RISK_ACTION"
    | "PORTFOLIO_DECISION";
  target_local_ref: "$SUBMISSION" | string;
  claim_refs_used: string[];
  effect: "SUPPORTS" | "OPPOSES" | "RISK_ONLY" | "MIXED" | "NOT_MATERIAL";
}

interface AcceptedMacroInputAttribution {
  agent_id: MacroAgentId;
  usage_share: number;
  target_type: MacroInputAttributionSubmission["target_type"];
  target_ref: string;
  target_hash: string;
  claim_refs_used: string[];
  effect: MacroInputAttributionSubmission["effect"];
}
```

运行时要求每个 submission 对十个 Agent 各有且只有一条
`target_type=SUBMISSION_SUMMARY` attribution；它覆盖整份输出，存在相反的目标级
作用时使用 `MIXED`，模型只写 `target_local_ref="$SUBMISSION"`。每个 thesis、证券、
风险动作或组合决策可再有零至多条目标级 attribution，其 `target_local_ref` 必须指向
submission schema 中真实存在的稳定局部 ID；模型不得提交 runtime output ID、hash
或 usage share。

runtime 先完成 schema/语义验收并冻结目标对象，再把局部 ID 解析为持久化
`target_ref`、复制权威 `usage_share` 并计算 `target_hash`。summary hash 固定为
accepted payload 中除 raw `macro_input_attributions`、权威
`accepted_macro_input_attributions`、runtime envelope、
accepted_at 和所有 lineage/hash 字段之外的 canonical submission body hash，从定义上消除自引用；
目标级 hash 只覆盖对应冻结对象。解析不到唯一对象、模型回显 runtime 字段、或 hash
重算不一致时拒绝。`claim_refs_used` 必须属于对应 accepted output；
未采用时使用 `NOT_MATERIAL` 和空 `claim_refs_used`，不得删除 summary 行。
`SUPPORTS`、`OPPOSES`、`RISK_ONLY` 和 `MIXED` 必须有非空 `claim_refs_used`；
`NOT_MATERIAL` 必须为空。该合同只能审计模型的显式使用，不能声称精确控制模型
内部注意力。

消费范围：

- Sector、Superinvestor、`cro`、`alpha_discovery` 和 `cio` 接收十个直接输入，
  按自身职责解释，不得生成新的 Macro 投票或改写上游 transmission。
- `autonomous_execution` 不直接读取十个 Macro 输出，只读取 CIO 已批准决策、
  CRO 约束和获准的 execution-timing 事件投影。
- 同一 `causal_dedupe_key` 在一个下游候选中的 `independent_evidence_count` 固定为 1；
  所有角色解释和各自层内 usage share 仍保留。禁止跨 Macro/Sector/Relationship/
  Superinvestor confidence 取最大、相加或排序；相反解释必须显式标记冲突，不能增加
  独立支持数量。
- Macro 层不生成正式或诊断 stance；系统唯一正式投资 stance 由 CIO final 在
  十个 Macro、十个 Sector、四个 Superinvestor roster slot 齐备、Alpha 来源已冻结进
  proposal，且 CRO/Execution 各有 accepted output 或合法 stage skip 后形成。

### 9.1 其他层的 Darwinian 消费

同一个可靠度元数据合同泛化为封闭的 `DownstreamAgentInput` union。Macro 层使用上面的
专用别名；九个标准 Sector 加 `relationship_mapper` 的十个 accepted 输出在进入
Superinvestor 和获准 Decision 节点前，按
`confidence*darwin_weight*operational_reliability` 在 Sector 层归一化；四个
Superinvestor roster slot 必须各由 accepted output 或 hash 匹配的
`NoEvaluationObjectStageSkipRecord` 占据，只有 accepted output 在进入 Decision 层前按同一
公式归一化。stage skip 不进入分母、不生成权重或 calibration state，并以
`usage_share=0` 原样传递；`source_layer_signal_state` 仍由该层全部 accepted output
共同决定。因为四个角色共享同一冻结 Layer-2 candidate domain，stage skip 必须四个 slot
同时出现并引用同一 domain hash；非空域时四个 slot 都必须是 accepted output。每层都必须使用
一个不可变 `source_layer_snapshot_id/hash`，不得把低权重输出删除或压缩成 consensus。
`technology`、`real_estate_construction` 和 `agriculture` 因此与其他 Sector 一样拥有
真实的下游使用比例，而不只是一个审计分数。

非 Macro 层的 `confidence` 来源必须显式注册，不能从任意字段临时挑选：

```ts
interface SourceLayerReliabilityAdapterBase {
  adapter_contract_version: string;
  accepted_output_schema_version: string;
  calibration_contract_version: string;
  confidence_semantics_contract_version: string;
  cold_start_policy: "EXPLICIT_IDENTITY";
  factual_edges_never_hidden: true;
}

type SourceLayerReliabilityAdapter =
  | (SourceLayerReliabilityAdapterBase & {
      source_layer: "SECTOR";
      agent_id: StandardSectorAgentId;
      confidence_source: "CALIBRATED_SECTOR_OUTPUT_UTILITY";
    })
  | (SourceLayerReliabilityAdapterBase & {
      source_layer: "SECTOR";
      agent_id: "relationship_mapper";
      confidence_source: "MATERIALITY_WEIGHTED_PREDICTIVE_EDGES";
    })
  | (SourceLayerReliabilityAdapterBase & {
      source_layer: "SUPERINVESTOR";
      agent_id: SuperinvestorAgentId;
      confidence_source: "CALIBRATED_OUTPUT_LEVEL";
    });

interface ReliabilityCalibrationState {
  calibration_state_id: string;
  adapter_contract_version: string;
  calibration_target_id: string;
  effective_at: string;
  trained_through: string;
  training_sample_ids_hash: string;
  calibration_parameters_hash: string;
}
```

- 九个标准 Sector 和四个 Superinvestor 的 submission 新增必需的输出级
  `confidence: number`；accepted output 分别保存 `model_confidence`、adapter 校准后的
  `directional_confidence` 以及单独的 `abstention_confidence`。Sector `SELECTED` 或
  Superinvestor 有方向候选时 `abstention_confidence=0`；Sector
  `NO_QUALIFIED_DIRECTION` 或 Superinvestor `NO_QUALIFIED_CANDIDATES` 时
  `directional_confidence=0`，原 confidence 只校准为对“应弃权”的
  `abstention_confidence`，不得伪装成方向或选股置信度。Sector 不再生成 preferred/least
  两侧独立 confidence；`CALIBRATED_SECTOR_OUTPUT_UTILITY` 只把语义稳定的 submission
  顶层 confidence 按 branch 校准：SELECTED 对应整份相对方向与 picks 优于确定性 null，
  abstain 对应冻结 opportunity evaluator 未发现超过 materiality floor 的调用。SELECTED
  branch 不因 least 是否存在而切换 target、取最小值或重新分配权重；两类 calibration state
  必须使用不同 `calibration_target_id` 且不得混训。它也不对所辖全部子行业做平均或为两个
  方向生成两份 usage share。Sector 不生成 preferred/least 两侧的方向 confidence；仅在某侧
  非空 shortlist 上主动提交 `NO_QUALIFIED_SECURITY` 时保存独立的 security-abstention
  forecast probability，且该值只进入该侧 outcome proper loss，不进入 adapter 或 usage share。
- `relationship_mapper` 由 runtime 对 accepted predictive edges 的
  `calibrated_confidence`
  按预注册 materiality 加权得到方向解释 confidence；factual edges 不参与这个数值，
  也永远不因低份额隐藏。没有 predictive edge 时方向份额为 0，但事实图仍完整传递。
- `adapter_contract_version` 只在算法、目标或 confidence 语义变化时发布；这种变化连同
  accepted schema/`confidence_semantics_contract_version` 进入新 Agent track，不能继承
  旧样本或权重。常规重校准只发布新的 `ReliabilityCalibrationState`，不改变 Agent
  track key，也不重置 Darwinian history。state 只能使用 `trained_through<effective_at`
  且在当时已成熟的 PIT outcome，source-layer snapshot 固定所用 state ID，禁止用未来
  label 回写历史 usage share。模型只看到计算后的 `usage_share`，看不到 adapter knob。

因此 §9.1 非 Macro 方向公式中的 `confidence` 始终指
`directional_confidence`，不是未经校准的模型原值或 abstention confidence。少于校准最小
样本时只能使用带记录 ID 的 `EXPLICIT_IDENTITY` state，达到门槛后必须按预注册
calibration contract 更新；缺少 adapter/state/冷启动记录时层级 gate 拒绝。方向份额只在
`directional_confidence>0` 的 accepted 输出之间归一化。若全层都是合法 abstention，
则每个 `usage_share=0`、层状态为 `NO_DIRECTIONAL_SIGNAL`，但完整输出、FACT、风险、
abstention confidence 和 lineage 仍传给下游；这不是拒绝，也不得伪造一组中性份额。
Superinvestor 空域时四个 slot 全部 stage skip，非空域时四个 slot 全部为 accepted output；
两种分支不得混用。非空域上的 accepted output 可以全部合法 abstention，此时整层同样为
`NO_DIRECTIONAL_SIGNAL`，且这些 abstention 携带 abstention confidence 并进入
calibration/Darwinian 样本。
该状态必须同时写入 runtime/audit 和每个 `DownstreamModelInput`；非 Macro 层存在至少一个
`directional_confidence>0` 时为 `SIGNAL_SET_READY`。Macro gate 验收十个 transmission 后
固定为 `SIGNAL_SET_READY`，即使某些角色结论为 `NEUTRAL`；缺角色属于拒绝而非 abstention。

某层 required roster 不完整或合同/behavior 版本不匹配时，该层正式下游消费拒绝；
Superinvestor 的 required roster 完整性按四个固定 slot 逐一验证，每个 slot 只能是该 Agent
的 accepted output 或从共同冻结 candidate domain 及自身 matching eligibility audit 生成的
stage skip；四个 slot 混用两类分支、
Agent/domain hash 不匹配、空域生成 accepted output 或非空域使用 skip 均拒绝。存在
方向输出但方向可靠度总和为零时也拒绝。全层合法 abstention 按上一段放行，不能把缺失
角色转换为中性或静默重新归一化。Sector/Superinvestor 的
FACT、风险和 lineage 同样不因低份额隐藏。四个 Decision Agent 没有下游使用权重：
`cro`、`alpha_discovery`、`autonomous_execution` 和 `cio` 只进入评价/演化轨，不能用
连续权重缩放职责、候选、权限、约束、订单或目标仓位。

## 10. Darwinian 与评分迁移

- KNOT/Darwinian 不读取或修改组件基础权重，只读取 Agent 最终 accepted output 和对应
  role-matched outcome。Darwinian 评价覆盖全部 28 个 Agent，但只有 Macro、Sector 和
  Superinvestor 共 24 个上游信息源把评价结果转换为第 9 节下游使用权重；该基数对每个
  active production variant 独立成立，不再进入因子或 stance 聚合。
- 每个 Agent 拥有独立 `DarwinEvaluationTrack`；`cio_proposal/cio_final` 属于同一 `cio`
  逻辑 Agent，同一
  `agent_id/as_of` 只计一个结果样本；只有 accepted `cio_final` 进入
  CIO 评分，proposal 仅保留过程审计。
- application mode 固定为：10 Macro、10 Sector、4 Superinvestor 是
  `DOWNSTREAM_USAGE_WEIGHT`；CRO、Alpha、Execution、CIO 是 `EVOLUTION_ONLY`。
  对每个 active production variant，前 24 个同时拥有 `DarwinUsageWeightTrack`，后四个的
  weight/weight record 必须为 `N/A`，不能写入伪造的 1.0 行。
- Darwinian roster 的基数按 active production variant 计算，而不是全库全局固定为
  28/24。每个 `(execution_behavior_release_id, cohort_id, language)` variant 只有在 28 个
  evaluation track 全部具有评分合同、role-matched outcome 映射和冷启动/成熟状态，且
  24 个 usage track 具有合法权重状态时才为 READY。若同时激活多个 cohort/language，
  总轨道数按 variant 数量相乘，禁止把不同 variant 的轨道折叠为“一 Agent 一条全局轨”。
  只有
  `weight=1.0` 而没有可成熟评分路径，或给 `EVOLUTION_ONLY` Agent 创建 weight row，均为
  readiness 失败。

```ts
type DarwinApplicationMode = "DOWNSTREAM_USAGE_WEIGHT" | "EVOLUTION_ONLY";

interface DarwinProductionVariantRoster {
  // (cohort_id, language) 的稳定 canonical ID；跨 release revision 不变
  production_variant_roster_id: string;
  production_variant_roster_revision_id: string;
  production_variant_roster_revision_hash: string;
  execution_behavior_release_id: string;
  cohort_id: string;
  language: "en" | "zh";
  evaluation_track_key_hashes: string[];
  usage_track_key_hashes: string[];
  decision_evaluation_track_key_hashes: string[];
  readiness: "READY" | "REJECTED";
}

interface DarwinEvaluationTrack {
  track_key_hash: string;
  production_variant_roster_id: string;
  first_registered_roster_revision_id: string;
  cohort_id: string;
  language: "en" | "zh";
  agent_id: AgentId;
  darwin_application_mode: DarwinApplicationMode;
  agent_contract_version: string;
  prompt_behavior_version: string;
  execution_behavior_version: string;
  component_weight_contract_version: string | null;
  reliability_adapter_contract_version: string | null;
  confidence_semantics_contract_version: string | null;
  outcome_contract_version: string;
  scoring_contract_version: string;
  sample_schedule_contract_version: string;
  rank_scope_contract_version: string;
  rank_scope: OutcomeRankScope;
  primary_label_id: PrimaryLabelId;
  latest_normalized_score_window_hash: string | null;
  maturity_state: "COLD_START" | "MATURE";
}

interface DarwinUsageWeightTrack {
  usage_track_key_hash: string;
  production_variant_roster_id: string;
  evaluation_track_key_hash: string;
  darwin_application_mode: "DOWNSTREAM_USAGE_WEIGHT";
  current_weight_record_id: string;
  current_weight_record_kind:
    | "COLD_START_INITIALIZATION"
    | "MATURE_UPDATE";
  has_mature_update: boolean;
}
```

`DarwinProductionVariantRoster` 由 execution behavior release manifest 生成而不是手写：
`production_variant_roster_id` 只由 `cohort_id/language` 生成并跨 release 保持稳定；
每次 execution behavior release 为该稳定 variant 生成新的
`production_variant_roster_revision_id/hash`，冻结当时 28/24/4 轨道集合。
`evaluation_track_key_hashes` 必须恰好覆盖 28 个 Agent，`usage_track_key_hashes` 必须恰好
覆盖前 24 个 usage track，`decision_evaluation_track_key_hashes` 必须恰好是前一数组中
四个 Decision evaluation track 的子集。各数组内部不得重复，任何 usage track 都不得外键到
Decision evaluation track，也不得引用其他 cohort/language。新 release 中行为/合同版本
未变化的 Agent 必须复用原 track hash；只有其自身轨道主键字段变化时才创建新轨，不能因
全局 release ID 或 roster revision 更新而重置同 variant 的其他 27 个 Agent。

- 轨道主键必须包含 `production_variant_roster_id`、`cohort_id`、`language`、`agent_id`、
  `agent_contract_version`、
  `prompt_behavior_version`、`execution_behavior_version`、
  `component_weight_contract_version | null`、
  `reliability_adapter_contract_version | null`、
  `confidence_semantics_contract_version | null` 和
  `outcome_contract_version`、`scoring_contract_version`、
  `sample_schedule_contract_version`、`rank_scope_contract_version`、
  `primary_label_id`、`rank_scope` 与 `darwin_application_mode`。
  `execution_behavior_version` 是 model provider/ID/revision、语言、解码参数、tool
  capability schema/allowed-tools manifest template、snapshot bundle contract、parser/repair
  policy、结构化输出模式、完整 schema binding set 与 immutable phase instruction set 的
  canonical content hash；每次运行的 nonce、签名、issued/expiry
  time 和 bundle ID 不进入 behavior hash；
  任一可改变模型行为的运行配置变化都创建新轨道，不继承
  旧样本；usage track 也不继承旧权重。`calibration_state_id` 明确不属于轨道主键：同一冻结 adapter
  contract 的滚动重校准不得重置 Agent 表现历史。
- 所有 KNOT/Darwinian 更新只接受主键完全匹配、PIT 合法、已成熟、
  role-matched 且非重叠的有效样本。评分窗口、非重叠抽样、更新 epoch、更新频率和
  归一化公式由 `scoring_contract_version` 固定，不得由 prompt 或单次运行改动。
- 每个 READY production variant 的 24 条 usage weight 轨保留现有有界渐进更新算法。新
  track 不得继承其他
  `execution_behavior_version` 的权重；在从未发布过本轨权重且少于 30 个匹配样本时，
  只生成一次带原因、样本数和 `record_kind=COLD_START_INITIALIZATION` 的
  `darwin_weight=1.0` 初始记录。四条 Decision evaluation track 少于
  30 个样本时只记录 `maturity_state=COLD_START`，不生成 weight。达到 30 个样本后，
  peer 轨道只在对应 rank scope 达到预注册的最少成熟 Agent 数时排名；
  不足时保持 `previous_weight` 不变。已经发布过本轨权重后，如果 rolling window 因
  1260 日 lookback、coverage 或样本过期重新不足 30，不得重置为 1.0；必须写
  `HELD_INSUFFICIENT_WINDOW` checkpoint 并继续引用最后一个合法 weight record。
  Macro 和 `sector_relationship` self usage 轨按下述
  绝对分档更新；Decision self scope 只计算表现分档和 KNOT deficit，不执行权重更新。
  `has_mature_update=false` 时 record kind 必须为 `COLD_START_INITIALIZATION` 且权重恰为
  1.0；第一次正式更新后永久为 true，后续 hold checkpoint 的
  `previous_weight_record_id=resulting_weight_record_id`，不得生成新 weight row。

正式 usage-weight 更新公式固定为：

```text
Q1: new_weight = clip(previous_weight * 1.05, 0.3, 2.5)
Q4: new_weight = clip(previous_weight * 0.95, 0.3, 2.5)
Q2/Q3: new_weight = previous_weight
```

同质 peer rank scope 只保留 `sector_selection` 9 个标准 Sector Agent（最少成熟 7）和
`superinvestor_selection` 4 个 Agent（最少成熟 3）。十个 Macro 的评价对象、事件机会和
固定槽位不同，不做 cross-agent 排名；分别使用
`macro_<agent_id>` 自身 scope。这样不需要用一个未定义的 opportunity normalization 把
中国发布事件、地缘事件和固定五日金融路径强行比较。每个 Agent 仍先由自己的 outcome
contract 使用第 10.3 节冻结的 label-specific null baseline 和 scale 映射到 `[-1,1]`；
简单 clamp 原始指标不算有效归一化。两个 peer scope 只比较同一个
`rank_scope_contract_version` 注册为兼容、共享 normalization/opportunity family、共同
cutoff 且达到最低 outcome coverage 的表现；各角色仍保留自己的
`scoring_contract_version`，不能假装共享一套 labeler。
`sector_selection` 的 `opportunity_normalization_family` 必须进一步固定为同一
`SectorOpportunitySearchCalibrationContract` family：所有成员都以 direction/shortlist/
template cardinality 匹配的 pre-cutoff null maximum 调整机会效用。只共享一个 family 名称
但使用 raw maximum、不同 cardinality key 定义、不同 null generator/cutoff 或未通过最小
null-sample 门槛的 Sector 不得进入同一 peer batch。

排名窗口和 quartile 规则固定为：

```ts
interface DarwinianRankScopeContract {
  rank_scope_contract_version: string;
  rank_scope: "sector_selection" | "superinvestor_selection";
  window_kind: "LATEST_N_ELIGIBLE_SCORES";
  window_size: 30;
  maximum_lookback_trading_days: 1260;
  estimator: "ARITHMETIC_MEAN_NORMALIZED_SCORE";
  minimum_window_coverage: 0.8;
  tie_epsilon: number;
  normalization_family: string;
  opportunity_normalization_family: string;
  compatible_scoring_contract_versions: string[];
}

interface DarwinianSelfScopeContract {
  rank_scope_contract_version: string;
  rank_scope: Exclude<OutcomeRankScope, "sector_selection" | "superinvestor_selection">;
  darwin_application_mode: DarwinApplicationMode;
  weight_updates_enabled: boolean;
  window_kind: "LATEST_N_ELIGIBLE_SCORES";
  window_size: 30;
  maximum_lookback_trading_days: 1260;
  estimator: "ARITHMETIC_MEAN_NORMALIZED_SCORE";
  minimum_window_coverage: 0.8;
  q1_minimum: 0.25;
  q2_minimum: 0;
  q4_maximum: -0.25;
  compatible_scoring_contract_version: string;
}
```

- 每个 update slot 以 slot close 为共同 cutoff；每条 track 按
  `(outcome_due_at, outcome_sequence)` 选取 cutoff 前最新 30 个 `SCORE`，不得按收益
  选择窗口，且最早样本不得早于 cutoff 前 1260 个 A 股交易日。表现值是 30 个
  `normalized_score` 的算术均值；五年内不足 30 个时 evaluation track 不成熟。usage track
  从未发布过权重时使用唯一 1.0 initialization record；已有权重时保持上一权重，不创建
  第二条 1.0 fallback。
- 每个 peer batch 只包含同一 `production_variant_roster_id` 的 production tracks；不同
  cohort/language、shadow candidate 或不同 rank-scope contract 不得混排。batch 必须冻结
  当时 current 的 `production_variant_roster_revision_id`，且成员恰为该 revision 列出的
  同一 rank scope 的 usage-track hashes；新 release 中合法复用的旧 usage-track hash 可以
  继续参与，但 revision 外 track 不得混入。
- coverage 在从最早入选 score 对应的计划机会到 cutoff 的完整 schedule 上计算：
  `SCORE/(SCORE+AGENT_FAILURE)`；`PENDING/EXOGENOUS_EXCLUSION` 不进分母。coverage
  小于 0.8 或未满 30 个 score 的成员不成熟。两个 peer scope 均使用各自统一的固定
  opportunity schedule；任何 event-triggered contract 不得加入 peer scope。
- 按表现降序使用 midrank；绝对差不超过 `tie_epsilon` 的连续成员属于同一 tie block，
  共享该 block 的平均 rank，`agent_id` 只用于序列化而不打破统计并列。`n>=5` 时
  `quartile=min(floor((midrank-1)*4/n)+1,4)`；`n=4` 的无并列 rank 映射为
  Q1/Q2/Q3/Q4，`n=3` 为 Q1/Q2/Q4。并列一律按同一 midrank 公式映射；全部相等时
  不更新任何成员。所有 tie epsilon、输入 IDs、均值、midrank 和 quartile 留审计。

十个 Macro 分别使用 `macro_china`、`macro_us_economy`、`macro_eu_economy`、
`macro_central_bank`、`macro_us_financial_conditions`、
`macro_euro_area_financial_conditions`、`macro_commodities`、
`macro_geopolitical`、`macro_market_breadth` 和 `macro_institutional_flow` 自身 scope。
`relationship_mapper` 的图关系职责与单一行业方向选择/选股不可比，使用
`sector_relationship` 自身轨道 scope。四个 Decision Agent 的责任也不可比，因此使用
`decision_cro`、`decision_alpha`、
`decision_execution` 和 `decision_cio` 四个自身轨道 scope，不做 cross-agent 排名。
这些 15 个 self scope 达到 30 个匹配样本后，按各自 scoring contract 中固定的最近 30 个非重叠
`normalized_score` 均值分档：`>=0.25` 为 Q1，`[0,0.25)` 为 Q2，
`(-0.25,0)` 为 Q3，`<=-0.25` 为 Q4。十个 Macro 与 `sector_relationship` 固定
`darwin_application_mode=DOWNSTREAM_USAGE_WEIGHT/weight_updates_enabled=true`，沿用 Q1/Q4
usage-weight 更新；四个 Decision 固定
`darwin_application_mode=EVOLUTION_ONLY/weight_updates_enabled=false`，只保存 performance band、
样本数、窗口 hash 和 KNOT deficit，不写旧/新 weight 或进入 weight batch。CIO 表现也不参与
CRO/Alpha/Execution 的分档、KNOT deficit 或任何上游更新。

Darwinian evaluator 可以每日刷新成熟 score/window；usage-weight updater 对每个 READY
production variant 分别扫描 `weight_updates_enabled=true` 的 24 条轨，且权重最多在由预注册 A 股交易日历 epoch
锚定的每五个交易日 update slot 更新一次。每个 scope/track 保存：

```ts
interface DarwinUsageWeightUpdateCheckpoint {
  usage_track_key_hash: string;
  production_variant_roster_id: string;
  production_variant_roster_revision_id: string;
  rank_scope: UsageWeightRankScope;
  update_slot_id: string;
  update_disposition:
    | "UPDATED"
    | "HELD_INSUFFICIENT_WINDOW"
    | "HELD_INSUFFICIENT_PEERS"
    | "NO_NEW_OUTCOME";
  scoring_window_hash: string;
  max_consumed_outcome_sequence: number;
  consumed_outcome_set_hash: string;
  max_consumed_matured_at: string;
  previous_weight_record_id: string;
  resulting_weight_record_id: string;
  update_event_id: string;
}

interface DarwinUsageWeightUpdateBatch {
  update_event_id: string;
  batch_revision_id: string;
  supersedes_revision_id: string | null;
  production_variant_roster_id: string;
  production_variant_roster_revision_id: string;
  rank_scope: UsageWeightRankScope;
  update_slot_id: string;
  rank_scope_contract_version: string;
  member_usage_track_key_hashes: string[];
  consumed_outcome_set_hash: string;
  previous_weight_record_ids: string[];
  new_weight_record_ids: string[];
  darwinian_snapshot_id: string;
  status: "PREPARED" | "PUBLISHED" | "ABORTED";
}
```

`outcome_sequence` 是 label store 的单调提交序号，不能用无序字符串 outcome ID 的
`max()` 冒充水位。`update_event_id` 由 scope、update slot、排序后的 usage-track/outcome
sequences、scoring window hash、`production_variant_roster_id` 和合同版本确定性生成，并设唯一约束。
同名 scope/slot 在不同 stable cohort/language roster 中必须生成不同 batch/event，
不能因 `rank_scope` 相同而交叉更新。`production_variant_roster_revision_id` 必须等于发布时
current revision，但 revision/release 变化本身不进入 event identity；若 member track、outcome、
window 和合同均未变化，同一 slot 必须继续 no-op，不能因原子 prompt release 重复乘权重。
peer scope 只有评分窗口相对上次成功更新
至少新增一个成熟合格 outcome 时才可整体重排；self usage scope 必须新增自身 outcome。
同一窗口重跑、跨日但没有新 label、迟到的重复采集以及同一 `update_event_id` 都必须
no-op，不能再次乘 `1.05/0.95`。迟到但 PIT 合法的新 label 只能在下一个尚未发布的
update slot 进入，不追溯改写已经生效的权重。

batch status 通过 append-only revision 从 `PREPARED` 进入 `PUBLISHED/ABORTED`，不得
原地改行。peer scope 的 checkpoint、全部成员 weight rows 和唯一 `PUBLISHED` snapshot 必须在
同一个 SQLite transaction 中原子发布；reader 只读取 `PUBLISHED` batch。任何成员写入、
coverage、版本或唯一约束失败都将整批标记 `ABORTED`，不得让一部分成员看到新权重。
self usage scope 也使用同一 batch 协议，只是成员数为 1。Decision evaluation scope 不创建
该 batch；其 score-window/KNOT scheduler checkpoint 使用独立 append-only evaluation 表。
`PREPARED` batch 不对生产查询可见。

现有仅以 `(cohort,agent,date)` 唯一的 `darwinian_weights` 不能承载新轨道和幂等约束。
迁移时新增 append-only v2 usage-weight/update/checkpoint/batch 表，以完整 usage-track key 和
`update_event_id` 设唯一约束；旧表只读并标记 legacy。不得原地把旧 Agent 的最新行
补字段后冒充新合同轨道，也不得让“latest per agent”查询混合不同 behavior/scoring
合同或不同 snapshot。

- 发布新的 `component_weight_contract_version` 时，为该 Agent 创建新的
  KNOT/Darwinian 评分轨道；旧版本成绩仅保留审计，不评价新版本。
- Autoresearch 候选 prompt 在 shadow 中创建独立 `prompt_behavior_version` 和
  `KnotResearchTrack`，不创建 production `DarwinEvaluationTrack/DarwinUsageWeightTrack`，
  也不继承 champion 样本。晋级时从未来生效点新建空的 production evaluation track；
  application mode 为 `DOWNSTREAM_USAGE_WEIGHT` 时同时创建从 1.0 开始的 usage track。
  KNOT 选择用的 shadow labels 不得复制到 production track。只修改
  翻译、拼写或格式且行为合同不变时仅更新内容 hash；改变分析方法、证据优先级、
  反证流程或信息使用方式时必须更新 behavior version。
- shadow 候选必须在 mutation manifest 每个 `target_variant` 自己预注册的
  `cohort_id/language` 非重叠槽位使用与该 variant champion 相同的冻结输入 snapshot
  独立运行，或者使用绑定同一 target variant、能够完整重建 PIT 输入的固定 replay manifest；
  不能复制 champion 输出或把同一候选输出重复成多个样本。每个 research track
  单独保存运行、验收和 outcome，达到 30 个匹配样本前不能晋级。shadow 输出不进入
  当日正式下游消费；流量配额、槽位 epoch、replay 区间和晋级比较必须在候选创建时
  冻结，避免只选择有利日期。
- Macro Darwinian 的主 label 始终是角色匹配 outcome。CIO 最终结果和第 9 节
  attribution 只作诊断，不能进入 Macro `normalized_score` 或更新 Macro 权重。
- 本 v2 release 同时改变 28 个 Agent 的 prompt behavior/runtime manifest，并对各层引入新的
  accepted/model-view、工具或 outcome 合同，因此每个 initial active production variant
  都为 28 个 Agent 创建零成熟样本的新 evaluation track；其中 24 个上游信息源各创建唯一
  `darwin_weight=1.0` 冷启动记录，四个 Decision 只创建
  `EVOLUTION_ONLY` evaluation track，不继承或新建 weight row。
- `eu_economy`、`us_financial_conditions`、`euro_area_financial_conditions`、
  `technology`、`real_estate_construction` 和 `agriculture` 是全新 ID，额外禁止任何旧 ID
  映射；七个 COMPONENTS Macro 首次启用组件合同，九个标准 Sector 首次启用
  preferred/least 相对选择合同，`relationship_mapper` 使用新 universe/scope，
  四个 Superinvestor 使用新的冻结候选/attribution/model-view 合同。上述任一轨都不得继承
  旧 paired sample、outcome、normalized score 或 weight。
- 新 Sector outcome 只评价自身冻结的 preferred/可选 least-preferred 相对选择、证券选择和
  产业链路径，不复用其他 Sector 或 `commodities` 的宏观标签。旧 Decision weight 仅作
  legacy 审计。
- `dollar`、`yield_curve`、`volatility` 的旧成绩不得继承。
- 一般迁移规则只有角色、输出、评分、数据和 behavior 主键全部精确匹配时才能复用轨道；
  但本 v2 initial release 已明确改变 `geopolitical`、`market_breadth` 和
  `institutional_flow` 的 prompt/runtime/output 或 outcome 合同，因此三者同样从零样本新轨
  开始，不能援引一般规则保留旧成绩。

评分方向：

- 中国、美国、欧盟实体经济按发布事件和随后 A 股传导评分。
- `central_bank` 按 PBOC 政策/流动性事件及国内利率敏感路径评分。
- 两个外部金融条件 Agent 按其对应金融市场路径和 A 股外部冲击评分。
- `commodities`、`geopolitical` 按对应市场冲击路径评分。
- `market_breadth` 仍按随后 5 日 breadth composite 变化和等权 A 股相对
  大盘表现各 50%。
- `agriculture` 使用农业行业/产业链可验证路径，不使用 `commodities` 的
  同一宏观 label。

### 10.1 Agent outcome 唯一合同

Darwinian 评价对象是某次运行已验收的 Agent 输出，不是文本风格、下游
是否采纳，也不是 CIO 最终收益对全部上游的反向分摊。唯一合同源新增：

```ts
type PrimaryLabelId = keyof typeof OUTCOME_LABEL_REGISTRY;

type OutcomeRankScope =
  | "macro_china"
  | "macro_us_economy"
  | "macro_eu_economy"
  | "macro_central_bank"
  | "macro_us_financial_conditions"
  | "macro_euro_area_financial_conditions"
  | "macro_commodities"
  | "macro_geopolitical"
  | "macro_market_breadth"
  | "macro_institutional_flow"
  | "sector_selection"
  | "sector_relationship"
  | "superinvestor_selection"
  | "decision_cro"
  | "decision_alpha"
  | "decision_execution"
  | "decision_cio";

type UsageWeightRankScope = Exclude<
  OutcomeRankScope,
  "decision_cro" | "decision_alpha" | "decision_execution" | "decision_cio"
>;

type OutcomeSchedule =
  | {
      kind: "FIXED_NON_OVERLAP";
      trading_calendar_id: string;
      epoch: string;
      step_trading_days: number;
    }
  | {
      kind: "EVENT_TRIGGERED";
      trading_calendar_id: string;
      event_registry_version: string;
      event_priority_version: string;
    };

interface AgentOutcomeContractBase {
  outcome_contract_version: string;
  scoring_contract_version: string;
  sample_schedule_contract_version: string;
  rank_scope_contract_version: string;
  agent_id: AgentId;
  darwin_application_mode: DarwinApplicationMode;
  evaluation_object_type:
    | "MACRO_TRANSMISSION"
    | "SECTOR_TILT_PICKS"
    | "RELATIONSHIP_EDGES"
    | "SUPERINVESTOR_PICKS"
    | "CRO_FROZEN_RISK_ACTIONS"
    | "ALPHA_FROZEN_NOVEL_PICKS"
    | "EXECUTION_FROZEN_ORDER_INTENT"
    | "CIO_FROZEN_FINAL_PORTFOLIO";
  evaluation_object_schema_version: string;
  primary_label_id: PrimaryLabelId;
  metric_schema_id: string;
  maturity: {
    entry_semantics: "T_PLUS_1_OPEN" | "NEXT_SESSION_EXECUTION";
    horizon_trading_days: 1 | 5 | 20 | 21;
    trading_calendar_id: string;
  };
  sample_schedule: OutcomeSchedule;
  rank_scope: OutcomeRankScope;
  opportunity_set_contract_version: string;
  normalization_contract_version: string;
  required_source_ids: [string, ...string[]];
  fallback_allowed: false;
}

// OUTCOME_LABEL_REGISTRY 是唯一可编辑注册表。它为 28 个 agent_id 各生成一条
// AgentOutcomeContractBase，并以 primary_label_id 为 discriminator 绑定唯一 Zod
// raw-metrics/realized-metrics schema、确定性 labeler、normalization function 和
// application mode。
type OutcomeRegistry = typeof OUTCOME_LABEL_REGISTRY;
type AgentOutcomeContract = {
  [L in PrimaryLabelId]: AgentOutcomeContractBase & {
    primary_label_id: L;
    agent_id: OutcomeRegistry[L]["agent_id"];
    metric_schema_id: OutcomeRegistry[L]["metric_schema_id"];
  };
}[PrimaryLabelId];

interface RealizedOutcomeObservationBase<L extends PrimaryLabelId, M> {
  realized_outcome_observation_id: string;
  realized_outcome_observation_hash: string;
  scheduled_sample_id: string;
  agent_id: AgentId;
  primary_label_id: L;
  outcome_contract_version: string;
  scoring_contract_version: string;
  evaluation_opportunity_set_id: string;
  evaluation_opportunity_set_hash: string;
  as_of: string;
  outcome_due_at: string;
  matured_at: string;
  realized_metrics: M;
  outcome_evidence_ids: [string, ...string[]];
  pit_status: "VERIFIED";
}

type RealizedOutcomeObservation = {
  [L in PrimaryLabelId]: RealizedOutcomeObservationBase<
    L,
    z.infer<OutcomeRegistry[L]["realized_metrics_schema"]>
  > & {
    agent_id: OutcomeRegistry[L]["agent_id"];
  };
}[PrimaryLabelId];

type OutcomeSampleOrigin =
  | "PRODUCTION_ACTIVE"
  | "KNOT_RESEARCH_SHADOW"
  | "KNOT_POST_PROMOTION_CHAMPION_SHADOW";

type AcceptedOutputPayloadRegistry = {
  MACRO_TRANSMISSION: {
    agent_id: MacroAgentId;
    payload: AcceptedMacroTransmission;
  };
  STANDARD_SECTOR_SELECTION: {
    agent_id: StandardSectorAgentId;
    payload: AcceptedSectorSelection;
  };
  RELATIONSHIP_GRAPH: {
    agent_id: "relationship_mapper";
    payload: AcceptedRelationshipGraph;
  };
  SUPERINVESTOR_SELECTION: {
    agent_id: SuperinvestorAgentId;
    payload: AcceptedSuperinvestorSelection;
  };
  CRO_RISK_REVIEW: {
    agent_id: "cro";
    payload: AcceptedCroRiskReview;
  };
  ALPHA_DISCOVERY: {
    agent_id: "alpha_discovery";
    payload: AcceptedAlphaDiscovery;
  };
  EXECUTION_ASSESSMENT: {
    agent_id: "autonomous_execution";
    payload: AcceptedExecutionAssessment;
  };
  CIO_PROPOSAL: {
    agent_id: "cio";
    payload: AcceptedCioProposal;
  };
  CIO_FINAL: {
    agent_id: "cio";
    payload: AcceptedCioFinal;
  };
};

type AcceptedOutputKind = keyof AcceptedOutputPayloadRegistry;

type AcceptedOutputRunBinding =
  | {
      sample_origin: "PRODUCTION_ACTIVE";
      run_slot_kind: "OUTCOME_SCHEDULED";
      scheduled_sample_id: string;
    }
  | {
      sample_origin: "PRODUCTION_ACTIVE";
      run_slot_kind: "DOWNSTREAM_ONLY";
      scheduled_sample_id: null;
    }
  | {
      sample_origin: Exclude<OutcomeSampleOrigin, "PRODUCTION_ACTIVE">;
      run_slot_kind: "OUTCOME_SCHEDULED";
      scheduled_sample_id: string;
    };

type KnotControlAcceptedOutputKind =
  | "CRO_RISK_REVIEW"
  | "ALPHA_DISCOVERY"
  | "EXECUTION_ASSESSMENT";

interface AcceptedAgentOutputRecordBase {
  accepted_output_id: string;
  accepted_output_hash: string;
  graph_run_id: string;
  run_id: string;
  run_slot_id: string;
  operational_opportunity_audit_id: string;
  production_variant_roster_id: string;
  production_variant_roster_revision_id: string;
  execution_behavior_release_id: string;
  cohort_id: string;
  language: "en" | "zh";
  track_key_hash: string;
  agent_contract_version: string;
  prompt_behavior_version: string;
  execution_behavior_version: string;
  as_of: string;
  accepted_at: string;
}

type ScheduledOrProductionAcceptedAgentOutputRecord = {
  [K in AcceptedOutputKind]: AcceptedAgentOutputRecordBase &
    AcceptedOutputRunBinding & {
      accepted_output_kind: K;
      agent_id: AcceptedOutputPayloadRegistry[K]["agent_id"];
      output: EvidenceLineageEnvelope<
        AcceptedOutputPayloadRegistry[K]["payload"]
      >;
    };
}[AcceptedOutputKind];

type KnotControlAcceptedAgentOutputRecord = {
  [K in KnotControlAcceptedOutputKind]: AcceptedAgentOutputRecordBase & {
    sample_origin: "KNOT_CONTROL_SHADOW";
    run_slot_kind: "DOWNSTREAM_ONLY";
    scheduled_sample_id: null;
    accepted_output_kind: K;
    agent_id: AcceptedOutputPayloadRegistry[K]["agent_id"];
    output: EvidenceLineageEnvelope<
      AcceptedOutputPayloadRegistry[K]["payload"]
    >;
  };
}[KnotControlAcceptedOutputKind];

type AcceptedAgentOutputRecord =
  | ScheduledOrProductionAcceptedAgentOutputRecord
  | KnotControlAcceptedAgentOutputRecord;

type OperationalOpportunityScheduleBinding =
  | {
      run_slot_kind: "OUTCOME_SCHEDULED";
      scheduled_sample_id: string;
    }
  | {
      run_slot_kind: "DOWNSTREAM_ONLY";
      scheduled_sample_id: null;
    };

type OperationalOpportunityContext =
  | (OperationalOpportunityScheduleBinding & {
      sample_origin: "PRODUCTION_ACTIVE";
      production_reliability_eligible: true;
    })
  | {
      sample_origin: Exclude<OutcomeSampleOrigin, "PRODUCTION_ACTIVE">;
      production_reliability_eligible: false;
      run_slot_kind: "OUTCOME_SCHEDULED";
      scheduled_sample_id: string;
    }
  | {
      sample_origin: "KNOT_CONTROL_SHADOW";
      agent_id: "alpha_discovery" | "cro" | "autonomous_execution";
      production_reliability_eligible: false;
      run_slot_kind: "DOWNSTREAM_ONLY";
      scheduled_sample_id: null;
    };

type OperationalAgentFailureReasonFields =
  | {
      failure_reason: OutcomeAgentFailureReason;
      fallback_used: false;
    }
  | {
      failure_reason: "MODEL_FALLBACK";
      fallback_used: true;
    };

type OperationalCioFailurePhaseFields =
  | {
      failed_cio_phase: "PROPOSAL";
      accepted_cio_proposal_id: null;
      accepted_cio_proposal_hash: null;
    }
  | {
      failed_cio_phase: "FINAL";
      accepted_cio_proposal_id: string;
      accepted_cio_proposal_hash: string;
    };

type OperationalDependencyBlockedReasonFields =
  | {
      failure_reason: "DEPENDENCY_AGENT_FAILURE";
      blocked_dependency_disposition: "AGENT_FAILURE";
    }
  | {
      failure_reason: "DEPENDENCY_EXOGENOUS_EXCLUSION";
      blocked_dependency_disposition: "EXOGENOUS_EXCLUSION";
    };

type OperationalAcceptedNonCioFields = {
  [K in Exclude<AcceptedOutputKind, "CIO_PROPOSAL" | "CIO_FINAL">]: {
    agent_id: AcceptedOutputPayloadRegistry[K]["agent_id"];
    accepted_output_kind: K;
  };
}[Exclude<AcceptedOutputKind, "CIO_PROPOSAL" | "CIO_FINAL">];

interface OperationalOpportunityAuditBase {
  operational_opportunity_audit_id: string;
  operational_opportunity_audit_hash: string;
  graph_run_id: string;
  run_slot_id: string;
  production_variant_roster_id: string;
  production_variant_roster_revision_id: string;
  execution_behavior_release_id: string;
  cohort_id: string;
  language: "en" | "zh";
  agent_id: AgentId;
  track_key_hash: string;
  agent_contract_version: string;
  prompt_behavior_version: string;
  execution_behavior_version: string;
  as_of: string;
  recorded_at: string;
}

type OperationalOpportunityAudit = OperationalOpportunityAuditBase &
  OperationalOpportunityContext &
  (
    | (OperationalAcceptedNonCioFields & {
        disposition: "ACCEPTED";
        accountable: true;
        run_id: string;
        accepted_output_id: string;
        accepted_output_hash: string;
        stage_skip_id: null;
        stage_skip_hash: null;
        failure_reason: null;
        fallback_used: false;
      })
    | {
        disposition: "ACCEPTED";
        accountable: true;
        agent_id: "cio";
        accepted_output_kind: "CIO_FINAL";
        run_id: string;
        accepted_output_id: string;
        accepted_output_hash: string;
        stage_skip_id: null;
        stage_skip_hash: null;
        failure_reason: null;
        fallback_used: false;
      }
    | (OperationalAgentFailureReasonFields & {
        disposition: "AGENT_FAILURE";
        accountable: true;
        agent_id: Exclude<AgentId, "cio">;
        run_id: string;
        accepted_output_kind: null;
        accepted_output_id: null;
        accepted_output_hash: null;
        stage_skip_id: null;
        stage_skip_hash: null;
      })
    | (OperationalAgentFailureReasonFields &
        OperationalCioFailurePhaseFields & {
          disposition: "AGENT_FAILURE";
          accountable: true;
          agent_id: "cio";
          run_id: string;
          accepted_output_kind: null;
          accepted_output_id: null;
          accepted_output_hash: null;
          stage_skip_id: null;
          stage_skip_hash: null;
        })
    | {
        disposition: "EXOGENOUS_EXCLUSION";
        accountable: false;
        run_id: null;
        accepted_output_kind: null;
        accepted_output_id: null;
        accepted_output_hash: null;
        stage_skip_id: null;
        stage_skip_hash: null;
        failure_reason:
          | "REQUIRED_DATA_UNAVAILABLE"
          | "SOURCE_COVERAGE_UNHEALTHY"
          | "PIT_UNVERIFIED";
        fallback_used: false;
      }
    | {
        disposition: "EXOGENOUS_EXCLUSION";
        accountable: false;
        run_slot_kind: "OUTCOME_SCHEDULED";
        scheduled_sample_id: string;
        run_id: null;
        accepted_output_kind: null;
        accepted_output_id: null;
        accepted_output_hash: null;
        stage_skip_id: null;
        stage_skip_hash: null;
        failure_reason: "OPPORTUNITY_SET_UNAVAILABLE";
        fallback_used: false;
      }
    | {
        disposition: "NO_EVALUATION_OBJECT";
        accountable: false;
        sample_origin: OutcomeSampleOrigin;
        agent_id: NoEvaluationObjectStageSkipAgentId;
        run_id: null;
        accepted_output_kind: null;
        accepted_output_id: null;
        accepted_output_hash: null;
        stage_skip_id: string;
        stage_skip_hash: string;
        failure_reason: null;
        fallback_used: false;
      }
    | {
        disposition: "NO_EVALUATION_OBJECT";
        accountable: false;
        sample_origin: "KNOT_CONTROL_SHADOW";
        agent_id: DecisionStageSkipAgentId;
        run_id: null;
        accepted_output_kind: null;
        accepted_output_id: null;
        accepted_output_hash: null;
        stage_skip_id: string;
        stage_skip_hash: null;
        failure_reason: null;
        fallback_used: false;
      }
    | (OperationalDependencyBlockedReasonFields & {
        disposition: "DEPENDENCY_BLOCKED";
        accountable: false;
        agent_id: "cio";
        run_id: null;
        accepted_output_kind: null;
        accepted_output_id: null;
        accepted_output_hash: null;
        stage_skip_id: null;
        stage_skip_hash: null;
        fallback_used: false;
        blocked_dependency_agent_id: "alpha_discovery";
        blocked_dependency_operational_audit_id: string;
        blocked_dependency_operational_audit_hash: string;
        last_completed_cio_phase: "NONE";
        accepted_cio_proposal_id: null;
        accepted_cio_proposal_hash: null;
      })
    | (OperationalDependencyBlockedReasonFields & {
        disposition: "DEPENDENCY_BLOCKED";
        accountable: false;
        agent_id: "cio";
        run_id: string;
        accepted_output_kind: null;
        accepted_output_id: null;
        accepted_output_hash: null;
        stage_skip_id: null;
        stage_skip_hash: null;
        fallback_used: false;
        blocked_dependency_agent_id: "cro" | "autonomous_execution";
        blocked_dependency_operational_audit_id: string;
        blocked_dependency_operational_audit_hash: string;
        last_completed_cio_phase: "PROPOSAL";
        accepted_cio_proposal_id: string;
        accepted_cio_proposal_hash: string;
      })
  );

interface AgentOutcomeLabelBase<L extends PrimaryLabelId, M> {
  outcome_id: string;
  outcome_hash: string;
  outcome_sequence: number;
  scheduled_sample_id: string;
  eligibility_audit_id: string;
  eligibility_audit_revision_id: string;
  eligibility_audit_revision_hash: string;
  graph_run_id: string;
  run_slot_id: string;
  run_id: string;
  accepted_output_id: string;
  accepted_output_hash: string;
  production_variant_roster_id: string;
  production_variant_roster_revision_id: string;
  execution_behavior_release_id: string;
  cohort_id: string;
  language: "en" | "zh";
  agent_id: AgentId;
  track_key_hash: string;
  agent_contract_version: string;
  prompt_behavior_version: string;
  execution_behavior_version: string;
  component_weight_contract_version: string | null;
  reliability_adapter_contract_version: string | null;
  confidence_semantics_contract_version: string | null;
  outcome_contract_version: string;
  scoring_contract_version: string;
  sample_schedule_contract_version: string;
  rank_scope_contract_version: string;
  rank_scope: OutcomeRankScope;
  normalization_contract_version: string;
  as_of: string;
  outcome_due_at: string;
  matured_at: string;
  evaluation_object_hash: string;
  evaluation_opportunity_set_id: string;
  evaluation_opportunity_set_hash: string;
  realized_outcome_observation_id: string;
  realized_outcome_observation_hash: string;
  primary_label_id: L;
  raw_metrics: M;
  output_utility: number;
  null_utility: number;
  utility_delta: number;
  normalization_scale: number;
  normalized_score: number;
  outcome_evidence_ids: [string, ...string[]];
  pit_status: "VERIFIED";
}

type AgentOutcomeLabelEligibility =
  | {
      sample_origin: "PRODUCTION_ACTIVE";
      darwin_application_mode: "DOWNSTREAM_USAGE_WEIGHT";
      darwin_evaluation_eligible: true;
      usage_weight_eligible: true;
    }
  | {
      sample_origin: "PRODUCTION_ACTIVE";
      darwin_application_mode: "EVOLUTION_ONLY";
      darwin_evaluation_eligible: true;
      usage_weight_eligible: false;
    }
  | {
      sample_origin: Exclude<OutcomeSampleOrigin, "PRODUCTION_ACTIVE">;
      darwin_application_mode: DarwinApplicationMode;
      darwin_evaluation_eligible: false;
      usage_weight_eligible: false;
    };

type AgentOutcomeLabel = {
  [L in PrimaryLabelId]: AgentOutcomeLabelBase<
      L,
      z.infer<OutcomeRegistry[L]["raw_metrics_schema"]>
    > &
    AgentOutcomeLabelEligibility & {
      agent_id: OutcomeRegistry[L]["agent_id"];
      darwin_application_mode: OutcomeRegistry[L]["darwin_application_mode"];
    };
}[PrimaryLabelId];

interface EvaluationOpportunitySetBase {
  opportunity_set_id: string;
  opportunity_set_hash: string;
  opportunity_set_contract_version: string;
  outcome_contract_version: string;
  scoring_contract_version: string;
  sample_schedule_contract_version: string;
  rank_scope_contract_version: string;
  rank_scope: OutcomeRankScope;
  primary_label_id: PrimaryLabelId;
  scheduled_sample_id: string;
  darwin_application_mode: DarwinApplicationMode;
  as_of: string;
  generated_at: string;
  qualification_predicate_version: string;
  pit_status: "VERIFIED";
  member_evidence_ids: [string, ...string[]];
}

type EvaluationOpportunitySet =
  | (EvaluationOpportunitySetBase & {
      member_state: "NON_EMPTY";
      agent_id: AgentId;
      member_refs: [string, ...string[]];
    })
  | (EvaluationOpportunitySetBase & {
      member_state: "EMPTY";
      agent_id: NoEvaluationObjectStageSkipAgentId;
      member_refs: [];
    });

type OutcomeAgentFailureReason =
  | "OUTPUT_REJECTED"
  | "SCHEMA_REJECTED"
  | "SEMANTIC_REJECTED"
  | "UNAUTHORIZED_TOOL";

type OutcomeExogenousExclusionReason =
  | "REQUIRED_DATA_UNAVAILABLE"
  | "SOURCE_COVERAGE_UNHEALTHY"
  | "PIT_UNVERIFIED"
  | "NO_EVALUATION_OBJECT"
  | "OVERLAPPING_WINDOW";

type OutcomePostAcceptanceExclusionReason = Exclude<
  OutcomeExogenousExclusionReason,
  "NO_EVALUATION_OBJECT" | "OVERLAPPING_WINDOW"
>;

type OutcomeExclusionReason =
  | "AWAITING_AGENT_RUN"
  | "NOT_MATURED"
  | "MODEL_FALLBACK"
  | "OPPORTUNITY_SET_UNAVAILABLE"
  | "DEPENDENCY_AGENT_FAILURE"
  | "DEPENDENCY_EXOGENOUS_EXCLUSION"
  | OutcomeAgentFailureReason
  | OutcomeExogenousExclusionReason;

interface EvaluationOpportunitySetGenerationFailure {
  generation_attempt_id: string;
  generation_attempt_hash: string;
  opportunity_set_contract_version: string;
  generator_contract_version: string;
  qualification_predicate_version: string;
  attempted_at: string;
  required_source_ids: [string, ...string[]];
  source_evidence_ids: [string, ...string[]];
  error_codes: [string, ...string[]];
}

interface AgentOutcomeEligibilityAuditBase {
  audit_id: string;
  audit_revision_id: string;
  audit_revision_hash: string;
  supersedes_revision_id: string | null;
  scheduled_sample_id: string;
  graph_run_id: string;
  run_slot_id: string;
  run_id: string | null;
  production_variant_roster_id: string;
  production_variant_roster_revision_id: string;
  execution_behavior_release_id: string;
  cohort_id: string;
  language: "en" | "zh";
  agent_id: AgentId;
  track_key_hash: string;
  agent_contract_version: string;
  prompt_behavior_version: string;
  execution_behavior_version: string;
  component_weight_contract_version: string | null;
  reliability_adapter_contract_version: string | null;
  confidence_semantics_contract_version: string | null;
  outcome_contract_version: string;
  scoring_contract_version: string;
  sample_schedule_contract_version: string;
  rank_scope_contract_version: string;
  rank_scope: OutcomeRankScope;
  primary_label_id: PrimaryLabelId;
  opportunity_set_contract_version: string;
  normalization_contract_version: string;
  as_of: string;
  outcome_due_at: string;
  fallback_used: boolean;
  evidence_ids: [string, ...string[]];
  recorded_at: string;
}

type AgentOutcomeEligibilityOrigin =
  | {
      sample_origin: "PRODUCTION_ACTIVE";
      production_reliability_eligible: true;
      darwin_application_mode: DarwinApplicationMode;
      operational_opportunity_audit_id: string;
    }
  | {
      sample_origin: Exclude<OutcomeSampleOrigin, "PRODUCTION_ACTIVE">;
      production_reliability_eligible: false;
      darwin_application_mode: DarwinApplicationMode;
      operational_opportunity_audit_id: string;
    };

type CioAgentFailureReasonFields =
  | {
      exclusion_reason: OutcomeAgentFailureReason;
      fallback_used: false;
    }
  | {
      exclusion_reason: "MODEL_FALLBACK";
      fallback_used: true;
    };

type CioAgentFailurePhaseFields =
  | {
      failed_cio_phase: "PROPOSAL";
      accepted_cio_proposal_id: null;
      accepted_cio_proposal_hash: null;
    }
  | {
      failed_cio_phase: "FINAL";
      accepted_cio_proposal_id: string;
      accepted_cio_proposal_hash: string;
    };

type CioBlockedDependencyReasonFields =
  | {
      exclusion_reason: "DEPENDENCY_AGENT_FAILURE";
      blocked_dependency_disposition: "AGENT_FAILURE";
    }
  | {
      exclusion_reason: "DEPENDENCY_EXOGENOUS_EXCLUSION";
      blocked_dependency_disposition: "EXOGENOUS_EXCLUSION";
    };

type AgentOutcomeEligibilityAudit = AgentOutcomeEligibilityOrigin &
  (
  | (AgentOutcomeEligibilityAuditBase & {
      opportunity_set_status: "AVAILABLE";
      disposition: "PENDING";
      exclusion_reason: "AWAITING_AGENT_RUN";
      run_id: null;
      accepted_output: false;
      accepted_output_id: null;
      accepted_output_hash: null;
      fallback_used: false;
      evaluation_object_hash: null;
      evaluation_opportunity_set_id: string;
      evaluation_opportunity_set_hash: string;
      evaluation_opportunity_member_state: "NON_EMPTY";
      opportunity_set_generation_failure: null;
    })
  | (AgentOutcomeEligibilityAuditBase & {
      opportunity_set_status: "AVAILABLE";
      disposition: "PENDING";
      exclusion_reason: "NOT_MATURED";
      run_id: string;
      accepted_output: true;
      accepted_output_id: string;
      accepted_output_hash: string;
      fallback_used: false;
      evaluation_object_hash: string;
      evaluation_opportunity_set_id: string;
      evaluation_opportunity_set_hash: string;
      evaluation_opportunity_member_state: "NON_EMPTY";
      opportunity_set_generation_failure: null;
    })
  | (AgentOutcomeEligibilityAuditBase & {
      opportunity_set_status: "AVAILABLE";
      disposition: "SCORE";
      exclusion_reason: null;
      run_id: string;
      accepted_output: true;
      accepted_output_id: string;
      accepted_output_hash: string;
      fallback_used: false;
      evaluation_object_hash: string;
      evaluation_opportunity_set_id: string;
      evaluation_opportunity_set_hash: string;
      evaluation_opportunity_member_state: "NON_EMPTY";
      opportunity_set_generation_failure: null;
    })
  | (AgentOutcomeEligibilityAuditBase & {
      opportunity_set_status: "AVAILABLE";
      disposition: "AGENT_FAILURE";
      exclusion_reason: OutcomeAgentFailureReason;
      agent_id: Exclude<AgentId, "cio">;
      run_id: string;
      accepted_output: false;
      accepted_output_id: null;
      accepted_output_hash: null;
      fallback_used: false;
      evaluation_object_hash: null;
      evaluation_opportunity_set_id: string;
      evaluation_opportunity_set_hash: string;
      evaluation_opportunity_member_state: "NON_EMPTY";
      opportunity_set_generation_failure: null;
    })
  | (AgentOutcomeEligibilityAuditBase & {
      opportunity_set_status: "AVAILABLE";
      disposition: "AGENT_FAILURE";
      exclusion_reason: "MODEL_FALLBACK";
      agent_id: Exclude<AgentId, "cio">;
      run_id: string;
      accepted_output: false;
      accepted_output_id: null;
      accepted_output_hash: null;
      fallback_used: true;
      evaluation_object_hash: null;
      evaluation_opportunity_set_id: string;
      evaluation_opportunity_set_hash: string;
      evaluation_opportunity_member_state: "NON_EMPTY";
      opportunity_set_generation_failure: null;
    })
  | (AgentOutcomeEligibilityAuditBase &
      CioAgentFailureReasonFields &
      CioAgentFailurePhaseFields & {
        opportunity_set_status: "AVAILABLE";
        disposition: "AGENT_FAILURE";
        agent_id: "cio";
        run_id: string;
        accepted_output: false;
        accepted_output_id: null;
        accepted_output_hash: null;
        evaluation_object_hash: null;
        evaluation_opportunity_set_id: string;
        evaluation_opportunity_set_hash: string;
        evaluation_opportunity_member_state: "NON_EMPTY";
        opportunity_set_generation_failure: null;
      })
  | (AgentOutcomeEligibilityAuditBase & {
      opportunity_set_status: "AVAILABLE";
      disposition: "EXOGENOUS_EXCLUSION";
      exclusion_reason: Exclude<
        OutcomeExogenousExclusionReason,
        "NO_EVALUATION_OBJECT"
      >;
      run_id: null;
      accepted_output: false;
      accepted_output_id: null;
      accepted_output_hash: null;
      fallback_used: false;
      evaluation_object_hash: null;
      evaluation_opportunity_set_id: string;
      evaluation_opportunity_set_hash: string;
      evaluation_opportunity_member_state: "NON_EMPTY";
      opportunity_set_generation_failure: null;
    })
  | (AgentOutcomeEligibilityAuditBase &
      CioBlockedDependencyReasonFields & {
      opportunity_set_status: "AVAILABLE";
      disposition: "EXOGENOUS_EXCLUSION";
      agent_id: "cio";
      sample_origin: "PRODUCTION_ACTIVE";
      run_id: null;
      accepted_output: false;
      accepted_output_id: null;
      accepted_output_hash: null;
      fallback_used: false;
      evaluation_object_hash: null;
      evaluation_opportunity_set_id: string;
      evaluation_opportunity_set_hash: string;
      evaluation_opportunity_member_state: "NON_EMPTY";
      blocked_dependency_agent_id: "alpha_discovery";
      blocked_dependency_eligibility_audit_id: string;
      blocked_dependency_eligibility_audit_revision_id: string;
      blocked_dependency_eligibility_audit_revision_hash: string;
      last_completed_cio_phase: "NONE";
      accepted_cio_proposal_id: null;
      accepted_cio_proposal_hash: null;
      opportunity_set_generation_failure: null;
    })
  | (AgentOutcomeEligibilityAuditBase &
      CioBlockedDependencyReasonFields & {
      opportunity_set_status: "AVAILABLE";
      disposition: "EXOGENOUS_EXCLUSION";
      agent_id: "cio";
      sample_origin: "PRODUCTION_ACTIVE";
      run_id: string;
      accepted_output: false;
      accepted_output_id: null;
      accepted_output_hash: null;
      fallback_used: false;
      evaluation_object_hash: null;
      evaluation_opportunity_set_id: string;
      evaluation_opportunity_set_hash: string;
      evaluation_opportunity_member_state: "NON_EMPTY";
      blocked_dependency_agent_id: "cro" | "autonomous_execution";
      blocked_dependency_eligibility_audit_id: string;
      blocked_dependency_eligibility_audit_revision_id: string;
      blocked_dependency_eligibility_audit_revision_hash: string;
      last_completed_cio_phase: "PROPOSAL";
      accepted_cio_proposal_id: string;
      accepted_cio_proposal_hash: string;
      opportunity_set_generation_failure: null;
    })
  | (AgentOutcomeEligibilityAuditBase & {
      opportunity_set_status: "AVAILABLE";
      disposition: "EXOGENOUS_EXCLUSION";
      exclusion_reason: "NO_EVALUATION_OBJECT";
      agent_id: NoEvaluationObjectStageSkipAgentId;
      run_id: null;
      accepted_output: false;
      accepted_output_id: null;
      accepted_output_hash: null;
      fallback_used: false;
      evaluation_object_hash: null;
      evaluation_opportunity_set_id: string;
      evaluation_opportunity_set_hash: string;
      evaluation_opportunity_member_state: "EMPTY";
      opportunity_set_generation_failure: null;
    })
  | (AgentOutcomeEligibilityAuditBase & {
      opportunity_set_status: "AVAILABLE";
      disposition: "EXOGENOUS_EXCLUSION";
      exclusion_reason: OutcomePostAcceptanceExclusionReason;
      run_id: string;
      accepted_output: true;
      accepted_output_id: string;
      accepted_output_hash: string;
      fallback_used: false;
      evaluation_object_hash: string;
      evaluation_opportunity_set_id: string;
      evaluation_opportunity_set_hash: string;
      evaluation_opportunity_member_state: "NON_EMPTY";
      opportunity_set_generation_failure: null;
    })
  | (AgentOutcomeEligibilityAuditBase & {
      opportunity_set_status: "UNAVAILABLE";
      disposition: "EXOGENOUS_EXCLUSION";
      exclusion_reason: "OPPORTUNITY_SET_UNAVAILABLE";
      run_id: null;
      accepted_output: false;
      accepted_output_id: null;
      accepted_output_hash: null;
      fallback_used: false;
      evaluation_object_hash: null;
      evaluation_opportunity_set_id: null;
      evaluation_opportunity_set_hash: null;
      evaluation_opportunity_member_state: null;
      opportunity_set_generation_failure:
        EvaluationOpportunitySetGenerationFailure;
    })
  );
```

所有正式或 KNOT accepted payload 都必须先包裹为唯一
`AcceptedAgentOutputRecord`，不能把裸 payload 直接写入 graph state、accepted store 或
operational audit。`accepted_output_hash` 覆盖 record 中除自身 hash 外的全部字段和完整
`EvidenceLineageEnvelope`；它只保存预分配的
`operational_opportunity_audit_id`，不保存 operational hash，因此生成顺序固定为
accepted record 先、final operational audit 后，不形成循环 hash。
`accepted_output_kind/agent_id/output` 必须按 `AcceptedOutputPayloadRegistry` 精确匹配；
record 的 graph/run/slot/origin/schedule/variant/behavior 必须与对应 operational audit
逐字段一致。普通 Agent 每个 operational opportunity 最多一个 accepted record；只有 CIO
可在同一 logical opportunity 下各有至多一个 `CIO_PROPOSAL` 和一个 `CIO_FINAL`，
proposal 不能被 operational `ACCEPTED` disposition 引用，只有 final 可以。
`KNOT_CONTROL_SHADOW` 只允许 Alpha/CRO/Execution 三种 accepted kind；production reader
必须显式过滤 `sample_origin=PRODUCTION_ACTIVE` 和当前 graph/run，不得使用无 origin 的
“latest accepted output”查询。裸 payload、跨 namespace/slot 引用、record/audit hash
不匹配或 KNOT accepted record 进入 production graph 均拒绝。

AVAILABLE 分支必须按 `disposition` 继续封闭字段关系：只有 `SCORE`、已接受但尚未成熟的
`PENDING/NOT_MATURED`，以及已接受输出后发生的
`EXOGENOUS_EXCLUSION` 可以携带 `evaluation_object_hash`，且这三类分支还必须携带非空
`accepted_output_id/accepted_output_hash`，并精确解析到同一 scheduled sample 的
`AcceptedAgentOutputRecord`；其余分支的这三个 accepted/evaluation 字段必须全为 null。
只有 `SCORE` 可以生成 label；
schema、语义、工具和普通输出拒绝固定为 `AGENT_FAILURE`，模型 fallback 固定
`fallback_used=true`；required data、source coverage、PIT 和重叠窗口固定为
`EXOGENOUS_EXCLUSION`。成功冻结但成员为空的机会集必须保留非空生成证据，并在模型调用前
固定为 `EXOGENOUS_EXCLUSION/NO_EVALUATION_OBJECT`；它不是 generation failure，也不能启动
Agent。对四个 Superinvestor 和 `cro/alpha_discovery/autonomous_execution`，runtime 还必须
从同一 set/audit 确定性生成唯一 `NoEvaluationObjectStageSkipRecord` 供图继续执行；该记录
不是 accepted output 或 Darwinian 样本。除该分支外，所有 AVAILABLE 分支的
`member_refs` 必须非空。`member_state=EMPTY` 只允许
`NoEvaluationObjectStageSkipAgentId`；Macro、Sector、`relationship_mapper` 或 CIO
返回空 set 属于 opportunity-set generation contract failure，必须走 `UNAVAILABLE`，不能
创建 `NO_EVALUATION_OBJECT` audit 或 stage skip。
运行前外生排除固定 `run_id=null/accepted_output=false`；已经接受
输出后在 outcome maturity 才发现 required outcome data、source coverage 或 PIT 不可证时，
保留 `run_id/evaluation_object_hash` 并固定 `accepted_output=true`，但仍不生成 label。
`NO_EVALUATION_OBJECT/OVERLAPPING_WINDOW` 只能是运行前分支。禁止用宽泛 boolean/null
组合表示这些状态。

在该 outcome audit 中，CIO 的 `accepted_output` 专指可评价的
`AcceptedCioFinal`，不把中间态 `AcceptedCioProposal` 算作 accepted evaluation output。
proposal 与 final 共用一个 CIO logical `run_id`、一个 scheduled sample 和一个 operational
opportunity。以下 `DEPENDENCY_*` outcome 分支只属于 `PRODUCTION_ACTIVE`；KNOT
control dependency block 只写第 9/10.6 节定义的 operational/pairing audit，不创建 CIO
outcome eligibility revision。下列 `accepted_cio_proposal_id/hash` 始终引用
`accepted_output_kind=CIO_PROPOSAL` 的 `AcceptedAgentOutputRecord` 及其 record hash，
不是 proposal payload 内部的 `proposal_id/proposal_hash`：

- CIO 自身在 proposal 失败时写唯一 `AGENT_FAILURE`，固定
  `failed_cio_phase=PROPOSAL` 且 proposal ID/hash 为 null；自身在 final 失败时同样只写一条
  CIO `AGENT_FAILURE`，固定 `failed_cio_phase=FINAL` 并保留已接受 proposal 的 ID/hash。
  两个阶段不能分别计为两个 CIO failure。
- Alpha 在 proposal 前没有产生 accepted output 或合法 stage skip 时，CIO 写
  `DEPENDENCY_*` 分支，`run_id=null/last_completed_cio_phase=NONE`；CRO 或 Execution 在
  proposal 后阻断时，CIO 写
  `run_id=<logical CIO run>/last_completed_cio_phase=PROPOSAL` 并保留 proposal ID/hash。
- `DEPENDENCY_AGENT_FAILURE` 必须引用同一 graph run 中依赖 Agent 的
  `AGENT_FAILURE` audit；`DEPENDENCY_EXOGENOUS_EXCLUSION` 只能引用尚未产生 accepted output
  或合法 stage skip 的 pre-run/UNAVAILABLE `EXOGENOUS_EXCLUSION`。已接受依赖输出之后的
  `NOT_MATURED` 或 outcome-maturity exclusion 不会阻断 CIO。对应
  `blocked_dependency_disposition` 必须与 reason 的封闭 discriminant 一致；引用必须固定到
  依赖 Agent 的最终 eligibility audit revision ID/hash，不能只保存稳定 chain ID 后读取
  latest。
- Alpha、CRO 或 Execution 的合法 `NO_EVALUATION_OBJECT` stage skip 是显式可继续输入，
  不得改写成 dependency exclusion。依赖失败只进入依赖 Agent 自己的 operational
  reliability；对应 CIO dependency audit 不进入 CIO operational reliability、Darwin score
  或 label。

运行前状态机的优先级固定且不可由 Agent 自由选择：

1. 先按 opportunity-set contract 读取其最小 required source 并冻结机会集；生成失败走
   `UNAVAILABLE/OPPORTUNITY_SET_UNAVAILABLE`。
2. 若合法 `NoEvaluationObjectStageSkipAgentId` 得到 `member_state=EMPTY`，立即写
   `NO_EVALUATION_OBJECT` audit/stage skip，不再构建模型快照、不检查只为分析非空对象所需的
   role-event/市场/财务分支，也不计 operational failure。
3. 只有 `member_state=NON_EMPTY` 才构建完整 Agent snapshot；此时 required data、coverage
   或 PIT 失败走对应 pre-run `EXOGENOUS_EXCLUSION`。
4. snapshot READY 后才写 `AWAITING_AGENT_RUN` 并允许模型调用；模型/合同失败随后进入
   `AGENT_FAILURE`，被该 Agent outcome contract 指定的 accepted evaluation output
   才能进入 `NOT_MATURED/SCORE`；CIO 中仅 `CIO_FINAL` 符合，proposal 不符合。

同一 scheduled sample 只能命中上述一条路径；不得因后续 snapshot 故障把已证明的合法空集
改写为数据失败，也不得先跳过 snapshot 来把非空机会集伪装成无评价对象。

`RealizedOutcomeObservation` 只保存双方共同的后续市场/事件实现、机会集和 PIT evidence，
不包含任何 Agent 输出、预测误差、utility 或 normalized score。每个 champion/candidate
accepted evaluation output 必须基于自己的 `evaluation_object_hash` 生成独立 outcome
label；两条 label
可以且只可以在同一 KNOT pair 中引用同一个 realized observation ID/hash。label ID、raw metrics、
utility 和 normalized score 不得复用。

`sample_origin`、label 的两个 eligibility flag 和 audit 的
`production_reliability_eligible` 在 schedule/audit/label 创建时由运行时写入并保持不可变：
它当且仅当 `sample_origin=PRODUCTION_ACTIVE` 时为 true；label 的
`darwin_evaluation_eligible` 同样当且仅当 `PRODUCTION_ACTIVE` 时为 true，其中 application
mode 为 `DOWNSTREAM_USAGE_WEIGHT` 时且仅此时
`usage_weight_eligible=true`。`KNOT_RESEARCH_SHADOW` 和
`KNOT_POST_PROMOTION_CHAMPION_SHADOW` 的 outcome audit/label production eligibility flag
都必须为 false，只能进入各自研究 namespace，不能被 production Darwin updater、maturity
counter、rank window 或 operational reliability 查询读取。`KNOT_CONTROL_SHADOW` 只有同样
production-ineligible 的 operational audit，不属于 outcome sample；组件校准也不创建
outcome/operational audit 或额外 label。这里 outcome audit 的 flag 只封闭 sample-origin
真值表；第 9 节
operational 分母唯一读取独立 `OperationalOpportunityAudit`，不能把 outcome audit 再计一次。
研究配对中的 incumbent 即使同时是 production champion，也必须另建
`KNOT_RESEARCH_SHADOW` audit/label，不能引用该日 production label 充当 paired sample。

以上四个评价版本字段和 `darwin_application_mode` 只能由同一
`OUTCOME_LABEL_REGISTRY` 行生成。合同、运行前冻结的
`EvaluationOpportunitySet`、eligibility audit、成熟 label、组件校准记录和 Darwinian
track key 中的 `outcome/scoring/sample_schedule/rank_scope` version、`primary_label_id`、
`rank_scope` 值以及 application mode 必须
逐字段完全相等；
不得从 prose 推导、使用默认值或让 label/audit 缺少其中一项。任一不一致都标记
为合同/readiness 失败并阻止生产 schedule；若已在冻结 slot 中发生，则记录
`AGENT_FAILURE/SEMANTIC_REJECTED`，而不是伪装成 `EXOGENOUS_EXCLUSION` 或另起一个无法
追溯的 latest 轨道。

`normalized_score` 必须由确定性代码计算并位于 `[-1,1]`。只有 outcome contract 指定且
通过 `SCORE` audit 的 accepted evaluation output 可以生成 label；CIO proposal、
`DOWNSTREAM_ONLY` accepted output 和 `KNOT_CONTROL_SHADOW` accepted output 均不可生成。
被拒绝或使用 fallback 的运行不生成方向/效用 label，但每个
预注册评价槽位都必须生成 eligibility audit。其匹配
`OperationalOpportunityAudit=AGENT_FAILURE/accountable=true` 才进入第 9 节 operational
reliability 分母；outcome audit 自身不计第二次。`EXOGENOUS_EXCLUSION/PENDING` 不进入；
任何失败记录都不能因没有 label 而删除。eligibility 从 `PENDING` 到最终 disposition 的变化通过新的 immutable
revision 和 `supersedes_revision_id` 表示，不能原地覆盖。
每个 revision 必须有可重算的 `audit_revision_hash`。outcome label 只能引用同一
scheduled sample 的最终 `SCORE` revision ID/hash，并与该 revision 引用同一个
`accepted_output_id/accepted_output_hash`；`NoEvaluationObjectStageSkipRecord`
只能引用最终 `NO_EVALUATION_OBJECT` revision。稳定 `audit_id` 只标识 revision chain，
不能单独作为 label、skip 或 dependency 的冻结依据。
对全部 28 个 Agent，各自某个 scheduled sample 的 accepted-output record、eligibility audit
和 outcome label 必须保存该 variant manifest 对应的同一个
`execution_behavior_version`；audit/label 还必须逐字段保存并匹配同一个
`production_variant_roster_id/production_variant_roster_revision_id/
execution_behavior_release_id/cohort_id/language`。不同 Agent/语言/variant 不要求 hash
相等。audit/label 的 `accepted_output_id/hash` 必须解析到该 accepted-output record，
record 外层 `agent_id/accepted_output_kind` 必须与 payload 内部 owner 字段及当前 Agent
一致；三者的 graph/run/slot/origin/schedule/track/variant 字段也必须逐字段相等。
单样本三者缺失、track hash 无法解析到这些 variant 字段或任一字段不一致时不得进入 track。
Macro 之外的 accepted schema 也必须由同一运行时 envelope 注入该样本版本，不能依赖模型
回显。`outcome_sequence` 由 label store 在 append 时分配为严格递增的正整数，
不能由模型、labeler 或外部 source 提交。
每个合同的 `required_source_ids` 必须非空，且在进入 READY 前逐一通过 schema、
PIT 覆盖和成熟时间验证。
所有五日结果默认从 `as_of` 后下一个交易日开盘计至第五个交易日收盘；
20/21 日结果使用同样的 T+1 进场语义。结果未成熟、必需源缺失或 PIT
不可证时不生成中性 label。
事件驱动 Agent 的窗口发生重叠时，按预注册 `event_priority`、发布时间和稳定事件 ID
排序选择唯一样本，其余保留 `OVERLAPPING_WINDOW` 排除记录，不得根据事后
结果挑选。

每个计划样本必须在 Agent 运行前尝试生成 `EvaluationOpportunitySet`。成功时冻结非空
ID/hash 并走 `opportunity_set_status=AVAILABLE`；失败时不得启动 Agent，必须写
`UNAVAILABLE/OPPORTUNITY_SET_UNAVAILABLE` 分支，保留非空 generation attempt、
required source、错误和证据，同时 set ID/hash 必须为 null。两种分支互斥，禁止为失败
记录伪造空机会集 ID/hash。只有 `NoEvaluationObjectStageSkipAgentId` 可以成功冻结
`member_state=EMPTY/member_refs=[]`，表示 generator 以完整 PIT evidence 证明本槽位没有
评价对象，并必须在模型调用前结束为 `NO_EVALUATION_OBJECT`；其他 Agent 的空结果是
generator failure。非空成功机会集才是 missed opportunity、abstention 和 coverage 的唯一
分母，不能在 outcome 成熟后从全市场挑“最佳遗漏”。Macro 使用当次固定槽位或
verified event；标准 Sector 使用 PIT 行业成分与
预注册流动性/可交易性/基本面最小筛选；Superinvestor 使用冻结 Layer-2 accepted
候选域；CRO 使用 pre-CRO 全部候选；Alpha 使用冻结 Layer-3 候选中经预注册 novel
资格筛选后的集合；Execution 使用 CIO 批准的 frozen order intents；CIO 使用 pre-CIO
持仓、获准候选和约束集合，其中必须始终包含唯一 canonical pre-CIO portfolio/null-policy
member；即使证券持仓和新增候选都为空，也以显式 cash position 表示，不能返回空 set。
`relationship_mapper` 使用运行前可验证实体对候选域和固定
匹配非边抽样规则。

机会集生成器、资格 predicate、排序/截断、空集合语义、source IDs 和 hash 都属于
scoring contract。若 required opportunity set 无法 PIT 重建，eligibility 为
`EXOGENOUS_EXCLUSION/OPPORTUNITY_SET_UNAVAILABLE` 且对应数据 readiness 不得 READY；
generation failure audit 必须足以重放失败原因，不得删除 missed-opportunity 分量、退化为
仅评分已选证券，或用 outcome 期末全市场排名补集合。

`OUTCOME_LABEL_REGISTRY` 必须以 TypeScript Zod 定义为源，同时生成 Python/JSON
schema、矩阵文档和 labeler dispatch；禁止在 Python 再维护自由字符串表。注册表必须
恰好覆盖 28 个 Agent，并对每个 `primary_label_id` 指定强类型 raw/realized metrics、null
baseline、scale、分母为零规则和 fixture。`Record<string,...>`、未定义常量或运行时
临时选择公式均不允许进入生产合同。

### 10.2 28 Agent 评价矩阵

| Agent | evaluation object | primary label | maturity horizon | rank scope | Darwin mode |
| --- | --- | --- | --- | --- | --- |
| `china` | 最终 `AcceptedMacroTransmission` | `china_macro_transmission_a_share_path_5d` | 中国主要发布事件后 5 交易日 | `macro_china` | `DOWNSTREAM_USAGE_WEIGHT` |
| `us_economy` | 最终 `AcceptedMacroTransmission` | `us_economic_cycle_a_share_path_5d` | 美国主要发布事件后 5 交易日 | `macro_us_economy` | `DOWNSTREAM_USAGE_WEIGHT` |
| `eu_economy` | 最终 `AcceptedMacroTransmission` | `eu_economic_cycle_a_share_path_5d` | 欧盟主要发布事件后 5 交易日 | `macro_eu_economy` | `DOWNSTREAM_USAGE_WEIGHT` |
| `central_bank` | 最终 `AcceptedMacroTransmission` | `pboc_rate_liquidity_a_share_path_5d` | PBOC 政策/流动性事件后 5 交易日 | `macro_central_bank` | `DOWNSTREAM_USAGE_WEIGHT` |
| `us_financial_conditions` | 最终 `AcceptedMacroTransmission` | `us_financial_conditions_a_share_path_5d` | 固定非重叠 5 交易日槽位 | `macro_us_financial_conditions` | `DOWNSTREAM_USAGE_WEIGHT` |
| `euro_area_financial_conditions` | 最终 `AcceptedMacroTransmission` | `euro_area_financial_conditions_a_share_path_5d` | 固定非重叠 5 交易日槽位 | `macro_euro_area_financial_conditions` | `DOWNSTREAM_USAGE_WEIGHT` |
| `commodities` | 最终 `AcceptedMacroTransmission` | `commodity_a_share_transmission_path_5d` | 固定非重叠 5 交易日槽位 | `macro_commodities` | `DOWNSTREAM_USAGE_WEIGHT` |
| `geopolitical` | 最终 `AcceptedMacroTransmission` | `geopolitical_transmission_a_share_path_5d` | 已验证事件触发后 5 交易日 | `macro_geopolitical` | `DOWNSTREAM_USAGE_WEIGHT` |
| `market_breadth` | 最终 `AcceptedMacroTransmission` | `market_breadth_confirmation_5d` | 固定非重叠 5 交易日槽位 | `macro_market_breadth` | `DOWNSTREAM_USAGE_WEIGHT` |
| `institutional_flow` | 最终 `AcceptedMacroTransmission` | `institutional_flow_followthrough_5d` | 固定非重叠 5 交易日槽位 | `macro_institutional_flow` | `DOWNSTREAM_USAGE_WEIGHT` |
| `semiconductor` | accepted preferred、可选 least-preferred 与约束 picks | `semiconductor_direction_pick_alpha_5d` | 5 交易日 | `sector_selection` | `DOWNSTREAM_USAGE_WEIGHT` |
| `technology` | accepted preferred、可选 least-preferred 与约束 picks | `technology_direction_pick_alpha_5d` | 5 交易日 | `sector_selection` | `DOWNSTREAM_USAGE_WEIGHT` |
| `energy` | accepted preferred、可选 least-preferred 与约束 picks | `energy_direction_pick_alpha_5d` | 5 交易日 | `sector_selection` | `DOWNSTREAM_USAGE_WEIGHT` |
| `biotech` | accepted preferred、可选 least-preferred 与约束 picks | `biotech_direction_pick_alpha_5d` | 5 交易日 | `sector_selection` | `DOWNSTREAM_USAGE_WEIGHT` |
| `consumer` | accepted preferred、可选 least-preferred 与约束 picks | `consumer_direction_pick_alpha_5d` | 5 交易日 | `sector_selection` | `DOWNSTREAM_USAGE_WEIGHT` |
| `industrials` | accepted preferred、可选 least-preferred 与约束 picks | `industrials_direction_pick_alpha_5d` | 5 交易日 | `sector_selection` | `DOWNSTREAM_USAGE_WEIGHT` |
| `real_estate_construction` | accepted preferred、可选 least-preferred 与约束 picks | `real_estate_construction_direction_pick_alpha_5d` | 5 交易日 | `sector_selection` | `DOWNSTREAM_USAGE_WEIGHT` |
| `financials` | accepted preferred、可选 least-preferred 与约束 picks | `financials_direction_pick_alpha_5d` | 5 交易日 | `sector_selection` | `DOWNSTREAM_USAGE_WEIGHT` |
| `agriculture` | accepted preferred、可选 least-preferred 与约束 picks | `agriculture_direction_pick_alpha_5d` | 5 交易日 | `sector_selection` | `DOWNSTREAM_USAGE_WEIGHT` |
| `relationship_mapper` | 最终 `AcceptedRelationshipGraph` 的 factual/predictive edges | `relationship_graph_validation_20d` | 20 交易日 | `sector_relationship` | `DOWNSTREAM_USAGE_WEIGHT` |
| `druckenmiller` | final `AcceptedSuperinvestorSelection` | `druckenmiller_pick_utility_21d` | 21 交易日 | `superinvestor_selection` | `DOWNSTREAM_USAGE_WEIGHT` |
| `munger` | final `AcceptedSuperinvestorSelection` | `munger_pick_utility_21d` | 21 交易日 | `superinvestor_selection` | `DOWNSTREAM_USAGE_WEIGHT` |
| `burry` | final `AcceptedSuperinvestorSelection` | `burry_pick_utility_21d` | 21 交易日 | `superinvestor_selection` | `DOWNSTREAM_USAGE_WEIGHT` |
| `ackman` | final `AcceptedSuperinvestorSelection` | `ackman_pick_utility_21d` | 21 交易日 | `superinvestor_selection` | `DOWNSTREAM_USAGE_WEIGHT` |
| `cro` | frozen pre-CRO 候选集与 accepted 风险动作 | `cro_risk_control_calibration_5d` | 5 交易日 | `decision_cro` | `EVOLUTION_ONLY` |
| `alpha_discovery` | frozen novel-pick 可选集与 accepted novel picks | `alpha_discovery_incremental_alpha_5d` | 5 交易日 | `decision_alpha` | `EVOLUTION_ONLY` |
| `autonomous_execution` | frozen 订单意图、feasibility 与成本预估 | `execution_feasibility_cost_t1` | 下一交易日收盘 | `decision_execution` | `EVOLUTION_ONLY` |
| `cio` | accepted `cio_final` 冻结目标组合 | `cio_portfolio_utility_5d` | 5 交易日 | `decision_cio` | `EVOLUTION_ONLY` |

### 10.3 Label 计算合同

注册表的 28 行必须全部且只能归入以下八个强类型 metric family；表中字段均为必需字段，不允许以自由
`Record` 代替：

| metric family | 必需 raw metrics | deterministic null |
| --- | --- | --- |
| Macro transmission | `direction_sign`、`strength`、`confidence`、`role_path_metric`、`pit_volatility_scale`、forecast/null loss | `p=0` |
| Standard Sector | `output_confidence`、冻结方向截面、唯一 preferred/审计决定的可选 least-preferred、逐方向预测 tilt/五日相对路径、冻结 side shortlist、逐证券 action/conviction/相对方向 benchmark 净 alpha、least eligibility、abstention base-rate Brier 与 missed-opportunity regret | 方向/证券预测为 0；abstention 使用冻结 pre-cutoff base rate |
| Relationship | 逐边 trigger、方向、raw `model_confidence`、是否激活、残差共振、共回撤、匹配非边 lift；accepted `calibrated_confidence` 与 state 仅作下游消费审计 | 不声明关系边 |
| Superinvestor | `output_confidence`、逐 pick side/conviction/净超额收益、下行路径、冻结候选漏报机会 | 不选择证券 |
| CRO | frozen candidate/action、风险概率、实际风险状态、precision/recall/specificity/calibration 分量 | 全部 `NO_OBJECTION` |
| Alpha | frozen candidate、selected flag、净超额收益、confidence calibration、漏报机会 | 不新增 novel pick |
| Execution | frozen order、预测/实际成本、fill、feasibility、target delta、realized policy compliance | 基准成本/feasibility 模型 |
| CIO | pre-CIO/target/realized 权重、净收益、回撤、换手成本、realized constraint compliance | 保持 pre-CIO 组合 |

Macro 评分将方向、强度和置信度合成为对归一化 role path 条件均值的点预测。使用
相对零预测 baseline 的平方损失改善，避免简单用 confidence 同时缩小奖励和惩罚：

```text
x_i = direction_sign * strength / 5
p_i = confidence * x_i
y_i = clamp(role_path_metric / PIT_volatility_scale, -1, 1)

forecast_loss_i = (p_i - y_i)^2
null_loss_i     = y_i^2                 # p=0 deterministic null forecast
output_utility_i = -forecast_loss_i
null_utility_i   = -null_loss_i
utility_delta_i  = output_utility_i - null_utility_i

normalized_score_i = normalize_against_frozen_null(
    utility_delta_i,
    primary_label_id,
    normalization_contract_version
)
```

平方损失使 `p_i` 的最优值为条件均值；模型把 confidence 降到零只会回到
`utility_delta=0` 的 baseline，不会取得正的技能分。direction hit、strength error 和
confidence calibration 另外保存为诊断 raw metrics，不替代 primary utility。

所有 label 的 `normalize_against_frozen_null` 使用合同生效日前冻结的、PIT 合法的
reference set。reference set 必须包含 null policy 和预注册的固定 naive benchmark
policies/forecasts 在同一历史机会上的效用，不能只放恒为零的 null 行，也不能使用待评价
Agent 的 live 分布拟合自己的 scale。每个 label 预注册 deterministic null policy，
先按同一公式为 reference policy 计算唯一的 `utility_delta`，再固定
`scale=max(q90(abs(utility_delta)), epsilon)`，最后计算
`clamp(utility_delta/scale,-1,1)`。禁止把已经相对 null 的 delta 再减一次
`null_utility`。reference 截止日、样本 IDs、epsilon、
scale 和 hash 随 normalization contract 固定，live 结果不能回写 scale。只有使用同一
normalization family、零点语义（优于 null 为正）和最低 coverage 的 label 才能进入同一
peer scope；仅把原值裁剪到 `[-1,1]` 不算完成归一化。

十个 Macro label 都必须冻结各自 role path，不能只有新 Agent 有代理定义：

| `primary_label_id` | 五日 `role_path_metric`（各分量先按自身 PIT scale 标准化） |
| --- | --- |
| `china_macro_transmission_a_share_path_5d` | 国内增长/生产、价格、信用数量、外需和财政五个 PIT 暴露子篮子各 20%；各子篮子先按自身 scale 标准化再合成 |
| `us_economic_cycle_a_share_path_5d` | 美国增长/生产、价格、就业、需求/贸易四个 PIT A 股传导子路径各 25%；只使用实体经济暴露，不混入 Fed/美元/曲线路径 |
| `eu_economic_cycle_a_share_path_5d` | EU27 增长/生产、价格、就业、需求/贸易四个 PIT A 股传导子路径各 25%；不混入 ECB/欧元/曲线路径 |
| `pboc_rate_liquidity_a_share_path_5d` | PBOC 政策倾向、流动性/货币市场、中国曲线和信用条件四个 PIT A 股传导子路径各 25% |
| `us_financial_conditions_a_share_path_5d` | Fed/流动性、美国曲线、信用/金融压力、美元/人民币四个 PIT A 股外部传导子路径各 25% |
| `euro_area_financial_conditions_a_share_path_5d` | ECB/流动性、欧元区曲线、银行信用、欧元/金融压力四个 PIT A 股外部传导子路径各 25% |
| `commodity_a_share_transmission_path_5d` | 能源、工业金属、黄金、农产品/食品四个 PIT A 股传导子路径各 25%；每个子路径同时冻结受益与输入成本敏感篮子 |
| `geopolitical_transmission_a_share_path_5d` | `as_of` 已冻结 affected-channel 篮子相对匹配非暴露篮子路径 50% + 等权 A 股相对宽基风险偏好路径 50%；升级/缓和的正负方向只由事件合同预注册映射 |
| `market_breadth_confirmation_5d` | 随后五日 breadth composite 变化 50% + 等权 A 股相对宽基表现 50% |
| `institutional_flow_followthrough_5d` | 随后五日确定性市场/行业/ETF flow continuation composite 50% + `as_of` 净流入最高分位相对最低分位的 PIT 篮子路径 50% |

前七个 COMPONENTS Macro 的 role-path 子路径 ID 必须与第 3 节组件集合一一对应，表中
outcome 合成权重由 `outcome_contract_version` 固定，不随待评估的
`component_weight_contract_version` 或候选权重变化；否则校准器会改变自己的 target。

表中“对 A 股支持”为统一正方向。每个分量的 series、方向变换、截面资格、篮子权重、
匹配规则、基准、复权、再平衡、缺失值、scale floor，以及表中登记的合成权重/顺序，
都必须写入对应 role-path contract；不能让 labeler 根据 Agent 当日方向选择有利篮子。事件型
`geopolitical` 的 affected channels 只能来自运行前冻结且已验证的 event record，不能在
五日路径已知后补选。`institutional_flow` 的 flow continuation 只用运行后自然成熟的同一
注册指标，不读取 CIO 持仓或下游采纳。

每个代理篮子的 series ID、权重、成分股 PIT 规则、基准、复权和波动率尺度必须在
outcome contract 中预注册。未完成数据映射和历史覆盖验证前，相应 Macro 的
Darwinian 轨道可为 `COLD_START` 但 roster 不得为 READY；不得回退到通用
CSI300 收益或 CIO 组合收益。

标准 Sector label 使用以下唯一 raw-metrics schema 和公式，不因 least-preferred 是否存在而
切换 benchmark 或评价目标：

```ts
interface StandardSectorDirectionOutcomeMetric {
  direction_id: string;
  realized_return_5d: number;
  parent_sector_return_5d: number;
  realized_scaled_path: number; // y_d
  predicted_tilt: number;       // p_d
  selected_role: "PREFERRED" | "LEAST_PREFERRED" | "UNSELECTED";
}

interface StandardSectorSecurityOutcomeMetric {
  side: "PREFERRED" | "LEAST_PREFERRED";
  direction_id: string;
  ts_code: string;
  action: "LONG" | "SHORT" | "AVOID" | "UNSELECTED";
  conviction: number;
  net_alpha_5d: number;
  realized_scaled_alpha: number; // y_k
  predicted_position: number;    // p_k
}

interface StandardSectorSecurityAbstentionOutcomeMetric {
  side: "PREFERRED" | "LEAST_PREFERRED";
  direction_id: string;
  security_status:
    | "PICKS_PRESENT"
    | "NO_QUALIFIED_SECURITY_EMPTY_SHORTLIST"
    | "NO_QUALIFIED_SECURITY_NONEMPTY_SHORTLIST";
  shortlist_size: number;
  raw_opportunity_utility: number | null;
  cardinality_adjusted_opportunity_utility: number | null;
  abstention_warranted_label: 0 | 1 | null;
  abstention_forecast_probability: number | null;
  abstention_null_probability: number | null;
  abstention_forecast_loss: number | null;
  abstention_null_loss: number | null;
  missed_opportunity_regret: number | null;
  side_security_utility_delta: number;
  abstention_base_rate_record_id: string | null;
  abstention_base_rate_record_hash: string | null;
  opportunity_search_calibration_id: string | null;
  opportunity_search_calibration_hash: string | null;
}

interface SectorOpportunitySearchCalibrationContract {
  opportunity_search_calibration_id: string;
  opportunity_search_contract_version: string;
  opportunity_search_calibration_hash: string;
  template_family_version: string;
  cardinality_key_fields: readonly [
    "eligible_direction_count",
    "nonempty_side_count",
    "direction_pair_template_count",
    "security_template_count",
    "shortlist_size_bucket_vector_hash",
  ];
  null_generation:
    "PRE_CUTOFF_BLOCK_PERMUTATION_PRESERVING_CROSS_SECTIONAL_DEPENDENCE";
  adjustment:
    "RAW_MAX_MINUS_MATCHED_NULL_Q95_DIVIDED_BY_MATCHED_NULL_SCALE";
  supported_cardinality_keys_hash: string;
  matched_null_distribution_registry_hash: string;
  minimum_null_samples: number;
  maximum_templates_per_family: number;
  cutoff: string;
}

interface StandardSectorOutcomeRawMetrics {
  output_confidence: number;
  confidence_semantics: "DIRECTIONAL_UTILITY" | "ABSTENTION_WARRANTED";
  least_preferred_eligibility_status:
    | "REQUIRED"
    | "NOT_QUALIFIED"
    | "NOT_APPLICABLE";
  direction_metrics: StandardSectorDirectionOutcomeMetric[];
  security_metrics: StandardSectorSecurityOutcomeMetric[];
  security_abstention_metrics: StandardSectorSecurityAbstentionOutcomeMetric[];
  direction_forecast_loss: number;
  direction_null_loss: number;
  security_forecast_loss: number;
  security_null_loss: number;
  direction_utility_delta: number;
  security_utility_delta: number;
  abstention_forecast_loss: number | null;
  abstention_null_loss: number | null;
  abstention_utility_delta: number | null;
  abstention_warranted_label: 0 | 1 | null;
  abstention_null_probability: number | null;
  abstention_base_rate_record_id: string | null;
  abstention_base_rate_record_hash: string | null;
  abstention_missed_opportunity_regret: number | null;
  combined_utility_delta: number;
  unit_confidence_utility_delta: number | null;
  abstention_raw_opportunity_utility: number | null;
  abstention_opportunity_utility: number | null;
  abstention_opportunity_search_calibration_id: string | null;
  abstention_opportunity_search_calibration_hash: string | null;
  confidence_calibration_target: 0 | 1;
}
```

```text
# 冻结输入
c = output_confidence
D = as_of 前冻结的全部 eligible directions
R_d = direction benchmark 从 T+1 open 到 T+5 close 的 PIT 可实现总收益
R_parent_sector = parent Sector benchmark 的同窗口 PIT 可实现总收益

if len(D) >= 2:
    y_d = clamp(
        (R_d - R_parent_sector) / direction_path_scale,
        -1,
        1,
    )

    for d in D:
        p_d = 0
    if preferred exists:
        p_[preferred_direction_id] =
            c * preferred_strength / 5
    if least_preferred_eligibility_status == REQUIRED:
        p_[least_preferred_direction_id] =
            -c * least_preferred_strength / 5
else:
    y_d = clamp(
        (R_d - R_single_direction_null_benchmark) / direction_path_scale,
        -1,
        1,
    )
    p_d = c * preferred_strength / 5 if preferred exists else 0

direction_forecast_loss = mean_equal_weight((p_d - y_d)^2 for d in D)
direction_null_loss     = mean_equal_weight(y_d^2 for d in D)
direction_utility_delta = direction_null_loss - direction_forecast_loss

# opportunity set 必须在 Agent 运行前为每个 eligible direction 冻结并按 scoring contract
# 截断 candidate shortlist；最终只激活 selected side，但不能运行后重建 shortlist。
# 未选证券仍以 action=UNSELECTED/p_k=0 保留在分母。
for each scored side s:
    if frozen candidate shortlist is proven empty:
        side_forecast_loss_s = 0
        side_null_loss_s = 0
        side_missed_opportunity_regret_s = 0
        side_security_utility_delta_s = 0
    elif security_status_s == PICKS_PRESENT:
        y_k = clamp(net_alpha_k_vs_own_direction_benchmark / security_alpha_scale_s, -1, 1)
        p_k = 0
        p_k =  c * conviction_k  for LONG
        p_k = -c * conviction_k  for SHORT or AVOID
        side_forecast_loss_s = mean((p_k - y_k)^2 over frozen candidates in side s)
        side_null_loss_s     = mean(y_k^2 over the same candidates)
        side_missed_opportunity_regret_s = 0
        side_security_utility_delta_s =
            side_null_loss_s - side_forecast_loss_s
    else:
        side_raw_opportunity_utility_s =
            evaluate_best_preregistered_sparse_security_action(side=s)
        side_opportunity_utility_s =
            adjust_max_for_frozen_search_cardinality(
                side_raw_opportunity_utility_s,
                side_search_cardinality_key_s,
                opportunity_search_calibration_contract,
            )
        side_abstention_warranted_label_s =
            1 if side_opportunity_utility_s <= security_abstention_materiality_floor else 0
        side_abstention_null_probability_s =
            frozen_pre_cutoff_security_abstention_base_rate_for_same_cardinality_key
        q_s = submitted_security_abstention_confidence_for_side_s
        side_forecast_loss_s = (q_s - side_abstention_warranted_label_s)^2
        side_null_loss_s =
            (
                side_abstention_null_probability_s
                - side_abstention_warranted_label_s
            )^2
        side_missed_opportunity_regret_s =
            0 if side_abstention_warranted_label_s == 1 else
            1 + clamp(
                (
                    side_opportunity_utility_s
                    - security_abstention_materiality_floor
                ) / security_abstention_regret_scale,
                0,
                1,
            )
        side_security_utility_delta_s =
            side_null_loss_s
            - side_forecast_loss_s
            - side_missed_opportunity_regret_s

if preferred exists and least_preferred_eligibility_status == REQUIRED:
    security_forecast_loss =
        0.5 * preferred_side_forecast_loss + 0.5 * least_side_forecast_loss
    security_null_loss =
        0.5 * preferred_side_null_loss + 0.5 * least_side_null_loss
    security_utility_delta =
        0.5 * preferred_side_security_utility_delta
        + 0.5 * least_side_security_utility_delta
elif preferred exists:
    security_forecast_loss = preferred_side_forecast_loss
    security_null_loss = preferred_side_null_loss
    security_utility_delta = preferred_side_security_utility_delta
else:
    security_forecast_loss = 0
    security_null_loss = 0
    security_utility_delta = 0

# calibration target 与 branch 一一对应。
if preferred exists:
    confidence_semantics = DIRECTIONAL_UTILITY
    abstention_forecast_loss = null
    abstention_null_loss = null
    abstention_utility_delta = null
    abstention_warranted_label = null
    abstention_null_probability = null
    abstention_base_rate_record_id = null
    abstention_base_rate_record_hash = null
    abstention_missed_opportunity_regret = null
    combined_utility_delta =
        0.5 * direction_utility_delta + 0.5 * security_utility_delta
    unit_confidence_utility_delta = recompute_combined_utility_delta(c=1)
    abstention_raw_opportunity_utility = null
    abstention_opportunity_utility = null
    abstention_opportunity_search_calibration_id = null
    abstention_opportunity_search_calibration_hash = null
    confidence_calibration_target =
        1 if unit_confidence_utility_delta > 0 else 0
else:
    confidence_semantics = ABSTENTION_WARRANTED
    unit_confidence_utility_delta = null
    abstention_raw_opportunity_utility =
        evaluate_best_preregistered_sparse_action_over_frozen_opportunity_set()
    abstention_opportunity_utility =
        adjust_max_for_frozen_search_cardinality(
            abstention_raw_opportunity_utility,
            overall_search_cardinality_key,
            opportunity_search_calibration_contract,
        )
    abstention_opportunity_search_calibration_id =
        opportunity_search_calibration_contract.opportunity_search_calibration_id
    abstention_opportunity_search_calibration_hash =
        opportunity_search_calibration_contract.opportunity_search_calibration_hash
    abstention_warranted_label =
        1 if abstention_opportunity_utility <= abstention_materiality_floor else 0
    abstention_null_probability =
        frozen_pre_cutoff_abstention_base_rate
    abstention_base_rate_record_id =
        frozen_pre_cutoff_abstention_base_rate_record.id
    abstention_base_rate_record_hash =
        frozen_pre_cutoff_abstention_base_rate_record.hash
    abstention_forecast_loss =
        (c - abstention_warranted_label)^2
    abstention_null_loss =
        (abstention_null_probability - abstention_warranted_label)^2
    abstention_missed_opportunity_regret =
        0 if abstention_warranted_label == 1 else
        1 + clamp(
            (
                abstention_opportunity_utility
                - abstention_materiality_floor
            ) / abstention_regret_scale,
            0,
            1,
        )
    abstention_utility_delta =
        abstention_null_loss
        - abstention_forecast_loss
        - abstention_missed_opportunity_regret
    combined_utility_delta = abstention_utility_delta
    confidence_calibration_target = abstention_warranted_label

normalized_score = normalize_against_frozen_null(
    combined_utility_delta,
    primary_label_id,
    normalization_contract_version,
)
```

多方向评价始终使用完整冻结截面；每个方向直接评价相对 parent Sector 的主动调用。
preferred-only 时只有 preferred 的 `p_d>0`，其他方向严格为 `p_d=0`，不会因去均值而被
隐式解释为 underweight/short；只有
`LeastPreferredEligibilityAudit=REQUIRED` 时对应 least 的 `p_d<0`。
`LeastPreferredEligibilityAudit=REQUIRED`
却缺少 least 时输出在验收阶段直接拒绝；`NOT_QUALIFIED/NOT_APPLICABLE` 时不会虚构空头腿。
单方向 Sector 只使用其显式注册且成分不重合的 null benchmark。方向 scale、security scale、
shortlist 截断数、流动性/可交易性、收益复权、成本和 T+1 语义都必须在 scoring contract
冻结；机会集无法 PIT 重建或 scale 非正时拒绝。资格过滤后被证明为空的 shortlist 是合法
`NO_QUALIFIED_SECURITY`，该 side 的 utility delta 固定为 0；shortlist 非空而模型提交
`NO_QUALIFIED_SECURITY` 时，不再用全零证券预测取得免费零技能，而是使用该 side
独立提交的 security-abstention 概率 `q_s`，相对同 cardinality 冻结 base rate
计算 Brier skill，并在漏掉 material security action 时减去至少 1 的 regret。base rate 同样
裁剪到 `[0.05,0.95]` 时，即使错误弃选时把 `q_s` 降到 0，其 utility 上界仍为
`0.95^2-0-1=-0.0975<0`，因此不存在通过低置信度空报逃避负分的路径。
不能把数据失败伪装成合法空集，也不能运行时改分母。
`security_metrics` 必须对每个实际评分 side 的 exact frozen shortlist 中每只证券恰有一行；
accepted pick 只改变对应行的 action/conviction，其余固定为 `UNSELECTED/0`。缺行、额外行、
重复 ticker、用 broad candidate domain 或 accepted picks 自身替换 shortlist 分母均拒绝。
`security_abstention_metrics` 必须对每个实际评分 side 恰有一行，并按 picks、空 shortlist、
非空 shortlist 弃选三种状态满足互斥 nullability；非空弃选缺 search calibration、base rate、
proper loss 或 regret 任一字段都拒绝。存在非空 security abstention 时，
`security_utility_delta` 是各 side `null_loss-forecast_loss-regret` 的等权值，不得错误重算为
聚合 `security_null_loss-security_forecast_loss` 而漏掉 regret。

`evaluate_best_preregistered_sparse_action_over_frozen_opportunity_set` 和 security-side
版本只枚举 scoring
contract 在 Agent 运行前冻结的有限模板：每个 eligible direction 各一次 unit-strength
preferred 调用、每个不同 direction 的 ordered preferred/least unit-strength pair，以及各模板
对应冻结 side shortlist 中至多合同上限数量的 unit-conviction LONG/AVOID 调用；模板集合、
组合上限、交易成本、scale 和
`abstention_materiality_floor`、正的 `abstention_regret_scale` 全部版本化并在 outcome 前
冻结。raw maximum 不能直接跨 Sector 或不同 direction/shortlist 数量使用。每次评价必须按
运行前的 direction 数、非空 side 数、pair/security template 数和 shortlist-size bucket vector
形成 cardinality key，再用 `SectorOpportunitySearchCalibrationContract` 中只含 pre-cutoff
路径的匹配 null maximum 分布做 family-wise 调整；null 样本不足、key/hash 不匹配或模板数
超过预注册上限时 outcome 不合格。materiality、base rate、normalization 和 peer-rank
compatibility 都使用调整后的 opportunity utility，不使用会随候选数量机械增大的 raw max。
它们只生成 abstention
label 和 missed-opportunity raw metric，不能在 outcome 后从全市场添加证券或自由搜索最优
组合。`frozen_pre_cutoff_abstention_base_rate` 是同一 Sector label/scoring contract 在
相同 opportunity-search family 和 cardinality key 的生效日前 reference set 中“没有
material opportunity”的 PIT 比率，固定裁剪到
`[0.05,0.95]` 并保存 cutoff、sample IDs 和 hash；它不是 `p=0`、不是永远 abstain，也不能由
当前 Agent 的 live 输出分布拟合。security-side abstention base rate 使用同样的 pre-cutoff、
cardinality-key、裁剪和 record ID/hash 规则，但只在相应 side 的非空 shortlist reference
set 上估计，不能复用整体方向弃权率。abstain branch 以相对该非平凡概率基线的 Brier skill
减去 missed-opportunity regret 后写入 primary `combined_utility_delta`。当存在 material
opportunity 时 regret 至少为 1，而基准概率被裁剪到 0.95，因此无论模型把 confidence 降到
多少，错误弃权的最坏上界也是
`0.95^2-0-1=-0.0975<0`；正确弃权时 regret 为零，校准优于冻结 base rate 才能获得正分。

LONG/SHORT/AVOID 都评价证券相对所属方向 benchmark 的价格判断；`AVOID` 的负预测只表示规避
相对损失，不假设卖空成交、借券或订单。`NO_QUALIFIED_SECURITY` 在空 shortlist 时为零，
在非空 shortlist 时走上述 proper-loss/regret 分支，因此既不强迫模型凑 picks，也不能免费
放弃可识别的证券机会。`NO_QUALIFIED_DIRECTION` 同样保留
完整冻结方向 opportunity set；方向/证券子技能仍以全零预测取得零，但 primary score 使用
上述 abstention proper loss。它不删除样本，也不因事后看到最佳/最差方向而构造新的负仓位。

SELECTED 的输出级 confidence 直接进入方向预测和实际 picks 的证券预测损失；非空 shortlist
上的 security abstention 只使用对应 side 的 `q_s`。SELECTED/整体 abstain 分别以各自
`confidence_semantics/confidence_calibration_target` 训练第 9.1 节分离 adapter，不能只保存
而不评分或把两个 target 混训。九个标准 Sector
共享上述 metric schema、SELECTED branch 的 50/50 权重、abstention proper-utility
branch 和 normalization family。pairwise matrix、ETF criterion
verdict、least eligibility 和冲突复核只参与确定性 selection mechanism/audit，不生成额外
AgentOutcomeLabel、Darwin weight 或下游票；Darwinian 仍只评价最终 accepted Sector output。

`relationship_mapper` 不与标准 Sector 排名。其 accepted output 增加结构化边
`source_entity`、`target_entity`、`edge_type`、`transmission_direction`、
`activation_trigger`、raw `model_confidence`、runtime `calibrated_confidence` 和
`claim_refs`。factual edge 在验收时验证；
20 日 outcome 只评价预测责任，并使用第 6.7 节完整冻结机会集：

```ts
interface RelationshipEdgeOutcomeMetricBase {
  edge_candidate_id: string;
  materiality_weight: RelationshipMaterialityWeight;
  realized_edge_state:
    | "NO_ACTIVATION"
    | "POSITIVE"
    | "NEGATIVE"
    | "MIXED";
  matched_non_edge_lift: number;
  candidate_counterfactual_best_utility: number;
  activation_direction_brier_skill: number;
  path_lift_utility_delta: number;
  missed_edge_regret: number;
  edge_utility_delta: number;
}

type RelationshipEdgeOutcomeMetric =
  | (RelationshipEdgeOutcomeMetricBase & {
      submitted: true;
      submitted_direction: "POSITIVE" | "NEGATIVE" | "MIXED";
      submitted_model_confidence: number;
    })
  | (RelationshipEdgeOutcomeMetricBase & {
      submitted: false;
      submitted_direction: null;
      submitted_model_confidence: 0;
    });

interface RelationshipOutcomeRawMetrics {
  predictive_graph_status:
    | "EDGES_PRESENT"
    | "NO_QUALIFIED_PREDICTIVE_EDGE";
  edge_metrics: RelationshipEdgeOutcomeMetric[];
  weighted_edge_utility_delta: number | null;
  graph_abstention_forecast_probability: number | null;
  graph_abstention_warranted_label: 0 | 1 | null;
  graph_abstention_forecast_loss: number | null;
  graph_abstention_null_loss: number | null;
  graph_abstention_best_raw_opportunity_utility: number | null;
  graph_abstention_cardinality_adjusted_utility: number | null;
  graph_abstention_missed_opportunity_regret: number | null;
  combined_utility_delta: number;
}
```

```text
# 每个 candidate 都评分；未提交 candidate 的 forecast 固定为 NO_ACTIVATION=1。
if candidate submitted:
    forecast_probability[submitted_direction] = model_confidence
    forecast_probability[NO_ACTIVATION] = 1 - model_confidence
else:
    forecast_probability[NO_ACTIVATION] = 1

activation_direction_brier_skill =
    frozen_pre_cutoff_null_brier_loss
    - multiclass_brier_loss(forecast_probability, realized_edge_state)

direction_alignment =
    1  if submitted and submitted_direction == realized_edge_state
    -1 if submitted and realized_edge_state != NO_ACTIVATION
           and submitted_direction != realized_edge_state
    0  otherwise

path_lift_utility_delta =
    direction_alignment
    * submitted_model_confidence
    * clamp(abs(matched_non_edge_lift) / frozen_lift_scale, 0, 1)

missed_edge_regret =
    1.01 + clamp(
        (candidate_counterfactual_best_utility - materiality_floor)
        / frozen_missed_edge_regret_scale,
        0,
        1,
    )
    if not submitted
       and candidate_counterfactual_best_utility > materiality_floor
    else 0

edge_utility_delta =
    0.5 * activation_direction_brier_skill
    + 0.5 * path_lift_utility_delta
    - missed_edge_regret
```

`submitted=true` 时 `submitted_model_confidence` 必须严格复用 accepted edge 当时保存的
`[0,1]` raw confidence；`submitted=false` 时 schema 固定
`submitted_direction=null/submitted_model_confidence=0`，不能在 outcome 时补写概率或方向。
`candidate_counterfactual_best_utility` 使用该 candidate 三个 unit-confidence direction
template 按下文同一公式取最大值；`frozen_missed_edge_regret_scale` 必须为正并在
opportunity-set scoring contract 中预注册。这样每个未提交的 material candidate 都至少
承担 1.01 regret，不能靠同时提交少数正确边掩盖漏报。

`EDGES_PRESENT` 的 `combined_utility_delta` 是完整机会集上按运行前
`materiality_weight` 归一化的 `edge_utility_delta` 加权均值；不能只对 submitted edges
取平均。`edge_metrics` 必须按冻结 opportunity 顺序一一覆盖全部 candidate，
`edge_candidate_id/materiality_weight` 与冻结值逐字段完全相等；缺失、重复、重排、outcome
时改权或权重和非有限正数时 label 拒绝。`NO_QUALIFIED_PREDICTIVE_EDGE` 则对冻结机会集中每个
candidate 的 `POSITIVE/NEGATIVE/MIXED` 三个有限 counterfactual template，使用实现后的
edge state 和 matched-non-edge path 计算 unit-confidence raw opportunity utility；不能在
outcome 后生成新 candidate 或方向。每个 template 固定
`forecast_probability[template_direction]=1`，按上文相同 multiclass Brier skill 计算
activation utility，并令
`template_path_lift_utility=direction_alignment(template_direction,realized_edge_state)
* clamp(abs(matched_non_edge_lift)/frozen_lift_scale,0,1)`；
`counterfactual_template_utility=0.5*template_activation_brier_skill+
0.5*template_path_lift_utility`。其余确定性公式为：

```text
graph_abstention_best_raw_opportunity_utility =
    max(counterfactual_template_utility over frozen candidates and directions)

graph_abstention_cardinality_adjusted_utility =
    graph_abstention_best_raw_opportunity_utility
    - frozen_pre_cutoff_null_max_for_same_candidate_count_and_type_mix

graph_abstention_warranted_label =
    1 if graph_abstention_cardinality_adjusted_utility <= materiality_floor
    0 otherwise

graph_abstention_forecast_loss =
    (predictive_graph_abstention_confidence
     - graph_abstention_warranted_label) ** 2

graph_abstention_null_loss =
    (frozen_pre_cutoff_graph_abstention_base_rate
     - graph_abstention_warranted_label) ** 2

graph_abstention_missed_opportunity_regret =
    0
    if graph_abstention_warranted_label == 1
    else 1.01 + clamp(
        (graph_abstention_cardinality_adjusted_utility - materiality_floor)
        / frozen_graph_abstention_regret_scale,
        0,
        1,
    )

combined_utility_delta =
    graph_abstention_null_loss
    - graph_abstention_forecast_loss
    - graph_abstention_missed_opportunity_regret
```

base rate、candidate-count/type-mix null maximum、materiality floor、regret scale 和
counterfactual-template utility contract 都必须在 prediction opportunity set 冻结前由
pre-cutoff 样本版本化；scale 非正、null cell 样本不足或 type mix 无匹配 null 时 label 拒绝。
由于 Brier skill 上界为 1，而错误空图 regret 至少为 1.01，错误空图必为负分；正确空图可以
相对 null 获得正分，永久空图不能逃避评价。该分支中
`weighted_edge_utility_delta=null`，上述 graph-abstention raw metric 全部非空；
`EDGES_PRESENT` 则相反：`weighted_edge_utility_delta` 非空，全部 graph-abstention metric
必须为 `null`。两分支最终都通过同一冻结 normalization contract 映射到
`[-1,1]`。模型不得在 outcome 后删除未激活边、补加成功边、重选匹配非边或改变
materiality/cardinality 分母。

四个 Superinvestor label 统一使用 21 交易日 conviction-weighted 超额收益与
下行路径惩罚。模型声明的 `holding_period` 仅作诊断，不能改变 Darwinian
主 label 的 21 日成熟时间。`NO_QUALIFIED_CANDIDATES` 使用冻结 Layer-2
非空候选域的事后漏报机会分数，不删除样本或自动记为中性；候选域为空时固定为
`EXOGENOUS_EXCLUSION/NO_EVALUATION_OBJECT` 并生成 stage skip，不创建 label。null policy
是从冻结候选域不选择证券；四个 Agent 共享 metric schema、下行惩罚和 normalization
family。
输出级 confidence 对 21 日组合效用使用同一校准诊断，并由
`SourceLayerReliabilityAdapter` 的版本化映射生成下游有效 confidence；cold start 的
identity mapping 必须显式记录，不能在映射缺失时静默假定 1.0。

Sector、Relationship 和 Superinvestor 的每个加权分量都必须先由 label-specific
raw-metrics schema 定义方向、scale、缺失值和分母为零规则，再按冻结 null/scale
转换；不得把上述文字权重直接实现为未归一化指标的相加。

### 10.4 Decision outcome 合同

四个 Decision primary label 必须先由 `OUTCOME_LABEL_REGISTRY` 注册以下封闭 Zod
raw-metrics family；不能只注册一个 label 名称后在 Python 中临时拼
`Record<string, number>`：

```ts
type DecisionUtilityComponentId =
  | "PRECISION"
  | "RECALL"
  | "SPECIFICITY"
  | "CALIBRATION"
  | "SELECTED_PICK_UTILITY"
  | "INCREMENTAL_OPPORTUNITY_UTILITY"
  | "COST_ERROR"
  | "FEASIBILITY"
  | "TARGET_DELTA"
  | "POLICY_COMPLIANCE"
  | "RELATIVE_RETURN"
  | "DRAWDOWN"
  | "TURNOVER_COST"
  | "CONSTRAINT_COMPLIANCE";

type DecisionMetricUnit =
  | "RATIO"
  | "PROBABILITY_LOSS"
  | "BASIS_POINTS"
  | "PORTFOLIO_WEIGHT"
  | "RETURN";

type DecisionDenominatorZeroRuleId =
  | "NOT_APPLICABLE"
  | "ZERO_UTILITY_IF_NO_PREDICTED_POSITIVE"
  | "ZERO_UTILITY_IF_NO_ACTUAL_POSITIVE"
  | "ONE_IF_NO_ACTUAL_NEGATIVE"
  | "EXOGENOUS_EXCLUSION_IF_EMPTY_OBJECT_SET";

interface DecisionUtilityComponent {
  component_id: DecisionUtilityComponentId;
  component_weight: number;
  unit: DecisionMetricUnit;
  direction: "HIGHER_IS_BETTER" | "LOWER_IS_BETTER";
  unclipped_output_value: number;
  unclipped_null_value: number;
  scale: number;
  output_utility: number;
  null_utility: number;
  utility_delta: number;
  denominator_zero_rule_id: DecisionDenominatorZeroRuleId;
}

interface DecisionOutcomeRawMetricsBase {
  combined_output_utility: number;
  combined_null_utility: number;
  combined_utility_delta: number;
}

interface CroCandidateOutcomeMetric {
  candidate_ref: string;
  ts_code: string;
  predicted_action:
    | "VETO"
    | "CAP_WEIGHT"
    | "REDUCE_WEIGHT"
    | "REQUIRE_REVIEW"
    | "NO_OBJECTION";
  predicted_risk_probability: number;
  predicted_positive: boolean;
  realized_risk_state: 0 | 1;
  realized_risk_evidence_ids: [string, ...string[]];
}

interface CroOutcomeRawMetrics extends DecisionOutcomeRawMetricsBase {
  components: [
    DecisionUtilityComponent & {
      component_id: "PRECISION";
      component_weight: 0.35;
    },
    DecisionUtilityComponent & {
      component_id: "RECALL";
      component_weight: 0.35;
    },
    DecisionUtilityComponent & {
      component_id: "SPECIFICITY";
      component_weight: 0.2;
    },
    DecisionUtilityComponent & {
      component_id: "CALIBRATION";
      component_weight: 0.1;
    },
  ];
  candidate_metrics: [
    CroCandidateOutcomeMetric,
    ...CroCandidateOutcomeMetric[],
  ];
  true_positive_count: number;
  false_positive_count: number;
  true_negative_count: number;
  false_negative_count: number;
  precision: number;
  recall: number;
  specificity: number;
  forecast_brier_loss: number;
  null_brier_loss: number;
  precision_denominator_zero: boolean;
  recall_denominator_zero: boolean;
  specificity_denominator_zero: boolean;
}

interface AlphaCandidateOutcomeMetric {
  candidate_ref: string;
  ts_code: string;
  selected: boolean;
  submitted_conviction: number;
  realized_net_excess_return_5d: number;
  realized_scaled_alpha: number;
  missed_opportunity_utility: number;
}

interface AlphaOutcomeRawMetrics extends DecisionOutcomeRawMetricsBase {
  components: [
    DecisionUtilityComponent & {
      component_id: "SELECTED_PICK_UTILITY";
      component_weight: 0.7;
    },
    DecisionUtilityComponent & {
      component_id: "INCREMENTAL_OPPORTUNITY_UTILITY";
      component_weight: 0.3;
    },
  ];
  discovery_disposition: "CANDIDATES" | "NONE_FOUND";
  candidate_metrics: [
    AlphaCandidateOutcomeMetric,
    ...AlphaCandidateOutcomeMetric[],
  ];
  selected_pick_utility_delta: number;
  incremental_candidate_utility_delta: number;
  output_confidence_forecast_loss: number;
  output_confidence_null_loss: number;
}

interface ExecutionOrderOutcomeMetric {
  order_intent_ref: string;
  ts_code: string;
  requested_delta_weight: number;
  predicted_feasibility: "FEASIBLE" | "PARTIAL" | "BLOCKED";
  predicted_feasibility_confidence: number;
  realized_feasibility: "FEASIBLE" | "PARTIAL" | "BLOCKED";
  predicted_cost_bps: number;
  realized_cost_bps: number;
  pit_cost_scale_bps: number;
  normalized_absolute_cost_error: number;
  realized_delta_weight: number;
  target_delta_attainment: number;
  realized_policy_compliance: 0 | 1;
  outcome_evidence_ids: [string, ...string[]];
}

interface ExecutionOutcomeRawMetrics extends DecisionOutcomeRawMetricsBase {
  components: [
    DecisionUtilityComponent & {
      component_id: "COST_ERROR";
      component_weight: 0.4;
    },
    DecisionUtilityComponent & {
      component_id: "FEASIBILITY";
      component_weight: 0.3;
    },
    DecisionUtilityComponent & {
      component_id: "TARGET_DELTA";
      component_weight: 0.2;
    },
    DecisionUtilityComponent & {
      component_id: "POLICY_COMPLIANCE";
      component_weight: 0.1;
    },
  ];
  execution_mode: "PAPER" | "REAL";
  order_metrics: [
    ExecutionOrderOutcomeMetric,
    ...ExecutionOrderOutcomeMetric[],
  ];
  mean_normalized_cost_error: number;
  feasibility_classification_utility_delta: number;
  target_delta_utility_delta: number;
  policy_compliance_utility_delta: number;
}

interface CioPortfolioWeightMetric {
  ts_code: string;
  pre_cio_weight: number;
  target_weight: number;
  realized_weight: number;
  realized_net_return_5d: number;
}

interface CioOutcomeRawMetrics extends DecisionOutcomeRawMetricsBase {
  components: [
    DecisionUtilityComponent & {
      component_id: "RELATIVE_RETURN";
      component_weight: 0.5;
    },
    DecisionUtilityComponent & {
      component_id: "DRAWDOWN";
      component_weight: 0.25;
    },
    DecisionUtilityComponent & {
      component_id: "TURNOVER_COST";
      component_weight: 0.15;
    },
    DecisionUtilityComponent & {
      component_id: "CONSTRAINT_COMPLIANCE";
      component_weight: 0.1;
    },
  ];
  decision_disposition: "TARGET_PORTFOLIO" | "HOLD_CURRENT" | "ALL_CASH";
  portfolio_metrics: CioPortfolioWeightMetric[];
  pre_cio_cash_weight: number;
  target_cash_weight: number;
  realized_cash_weight: number;
  output_net_return_5d: number;
  null_net_return_5d: number;
  output_max_drawdown_5d: number;
  null_max_drawdown_5d: number;
  output_turnover_cost: number;
  null_turnover_cost: number;
  realized_constraint_compliance: 0 | 1;
}
```

四个 schema 的 `components` 不是自由数组：CRO 必须恰好为
`PRECISION/RECALL/SPECIFICITY/CALIBRATION`，Alpha 为
`SELECTED_PICK_UTILITY/INCREMENTAL_OPPORTUNITY_UTILITY`，Execution 为
`COST_ERROR/FEASIBILITY/TARGET_DELTA/POLICY_COMPLIANCE`，CIO 为
`RELATIVE_RETURN/DRAWDOWN/TURNOVER_COST/CONSTRAINT_COMPLIANCE`，顺序和权重由 registry
冻结；逐项 `component_weight` 必须精确为本节的
35/35/20/10、70/30、40/30/20/10 或 50/25/15/10，且和为 1。所有 probability、权重和
compliance 必须在其声明范围内，所有数值必须有限；
`pit_cost_scale_bps/normalization scale` 必须严格为正。candidate/order/portfolio metrics
必须与运行前冻结对象一一对应，不能在 outcome 时删除未采纳对象或新增证券。

- `cro_risk_control_calibration_5d`：在 CRO 介入前冻结全部上游候选集，对每个
  `VETO/CAP_WEIGHT/REDUCE_WEIGHT/REQUIRE_REVIEW/NO_OBJECTION` 保存预测状态。
  随后五日使用候选证券的反事实价格路径、流动性失效和确定性约束违例
  计算 35% precision、35% recall、20% specificity 和 10% 置信度校准，再映射到
  `[-1,1]`。即使 CIO 没有采纳某个候选，也必须评价该冻结对象，避免
  选择偏差。`VETO/REDUCE_WEIGHT/CAP_WEIGHT/REQUIRE_REVIEW` 的风险概率映射和
  无预测正例/无实际正例的分母为零规则必须在 scoring contract 注册时已经完整，
  未完成不得创建生产合同。null policy 固定为对同一冻结候选全部
  `NO_OBJECTION`；utility delta 是上述加权效用相对 null 的改善。
  `correlated_risks/black_swan_scenarios` 在未结构化触发器前只作诊断，不由
  LLM 判定是否命中。CRO 硬约束不得因 Darwinian score、成熟状态或 KNOT 结果而放松。
- `alpha_discovery_incremental_alpha_5d`：在 CIO 选择前冻结 novel-pick 候选域，
  70% 评价已选 novel picks 的等权五日超额收益，并用输出级 confidence 校准；
  30% 评价相对 Layer-3 候选池的增量收益。`NONE_FOUND` 使用冻结候选域的事后可验证
  漏报率，不自动得到中性分。null policy 是不新增 novel pick；证券收益、基准、
  交易成本、输出级 confidence calibration 和漏报机会的 scale 全部写入 metric schema。
  frozen novel universe 为空时是
  `EXOGENOUS_EXCLUSION/NO_EVALUATION_OBJECT`；只有非空机会集上的
  `NONE_FOUND` 才进入漏报/正确弃权评价。
- `execution_feasibility_cost_t1`：只评价 frozen order intent 的执行责任。有真实成交时
  使用 PIT fill/VWAP；shadow/paper 时使用预注册确定性成交模型。分数由 40% 成本
  预估误差、30% feasible/partial/blocked 分类、20% 目标 delta 达成和 10% 执行
  政策合规组成；不使用后续股价涨跌评价执行 Agent。null policy 是同一订单意图上
  预注册的基准成本模型和 feasibility 分类器。成本误差先除以订单方向、成交量和流动性
  对应的 PIT cost scale；政策合规指随后真实/paper 执行是否遵守批准约束，不是输出通过
  schema 后恒为 1 的字段。frozen order-intent set 为空时不创建 execution evaluation
  object 或 accepted output，固定为 `EXOGENOUS_EXCLUSION/NO_EVALUATION_OBJECT`；
  存在 intent 时必须逐单评分，不能用空输出删除 blocked/partial 样本。
- `cio_portfolio_utility_5d`：只读取 accepted `cio_final` 冻结的完整目标组合，
  按 T+1 可交易价格建仓并扣除预注册成本。分数由 50% 相对宽基的波动率归一化
  收益、25% 回撤路径效用、15% 换手/成本效用和 10% 确定性约束合规组成。
  `HOLD_CURRENT/ALL_CASH` 同样按实际冻结权重评价，不作空样本。proposal 不计分。
  null policy 是冻结的 pre-CIO 当前组合；收益、回撤和换手都先转成相对该 null 的效用，
  约束合规评价五日内真实/paper 组合路径而不是 schema acceptance。

四个 Decision metric schema 必须列出每个 raw metric、单位、方向、裁剪前范围、scale、
分母为零规则、output/null utility、utility delta 和确定性公式。各分量先转换成同一
utility 单位再应用
35/35/20/10、70/30、40/30/20/10 或 50/25/15/10 权重，最后通过第 10.3 节冻结的
normalization contract 映射。不能只在 prose 中保留百分比，也不能把 acceptance 后的
恒定合规值作为区分 Agent 表现的分量。

Decision 的 Darwinian evaluation score/window 只用于该 Agent 自身的可靠度审计、
Autoresearch 优先级和 prompt 版本演化；不生成 usage weight，也不在同一运行中改变控制
权限：不得越过 CRO 硬约束、放宽 execution 可行性门或缩放 CIO 最终目标仓位。

### 10.5 反归因污染规则

- outcome label 只能更新 `agent_id` 与 `AgentOutcomeContract.agent_id` 相同的轨道。
- CIO 组合收益只更新 `cio` evaluation track，不更新 Macro、Sector、Superinvestor 的
  usage weight，也不更新 CRO、Alpha 或 Execution evaluation track。
- CRO 使用 pre-CRO frozen universe，Alpha 使用 pre-CIO novel universe，Execution
  使用 frozen order intent；下游未采纳不得删除上游样本。
- Macro/Sector/Superinvestor 使用自己的反事实市场路径评分，不以 CIO
  是否持有该候选作为 label。
- 第 9 节 attribution、CIO dissent 和最终 PnL 可作诊断，但不能进入上游
  `normalized_score` 公式。
- 一个 outcome 合同变更 label、horizon、冻结对象、归一化或数据源时，
  必须发布新 `scoring_contract_version` 并重建独立 Darwinian 轨道。

### 10.6 Autoresearch 演化闭环

Darwinian weight 只反映可靠度，不自动改 prompt。KNOT 是候选行为变更的唯一 proposer，
但不是权重、合同或 production prompt 的写入者；Darwinian updater 仍是权重唯一 owner，
prompt registry/promotion gate 是 behavior version 唯一 owner。所有研究阈值、排名和晋级
规则留在 runtime contract，不写入 MOSAIC-Combat-Evolved 或任何 Agent prompt。
这里的 weight owner 对每个 active production variant 只覆盖其 24 条
`DOWNSTREAM_USAGE_WEIGHT` 轨；四条 Decision
`EVOLUTION_ONLY` 轨直接用 normalized-score window、operational reliability 和失败诊断参与
KNOT 提名、配对、晋级与回滚，不生成或读取 usage weight。

本计划的 roster、角色、工具、snapshot schema、source map、Sector direction/ETF/comparison registry、
PIT/readiness、capability 或 RKE 隔离变化都属于合同迁移，不是 KNOT mutation。它们必须先发布新的
`agent_contract_version/execution_behavior_version`，由生成器同步重建 bundled/private
prompt 和 runtime manifest；受影响 Agent 的 KNOT scheduler 在 production data/tool
readiness 通过前为 `CONTRACT_MIGRATION_PAUSED`。新版本建立独立 champion baseline 和
Darwinian/KNOT track，不继承旧通用工具或旧数据合同下的 paired samples。

候选选择不得把不同 self/peer scope 的 `normalized_score` 直接全局排序。每个预注册
research slot 先在每个 scope 内确定性提名至多一个已满 30 个成熟样本、无 active
candidate、未处于 rollback cooldown 且数据/评分 READY 的 production track：peer scope
按本 scope 的 midrank percentile 最差者提名，self scope 按本轨最近 30 个均值相对其固定
Q2 下界的 `deficit=max(0, q2_minimum-mean_normalized_score)` 最大者提名。self scope
只有 `deficit>0` 或 `operational_reliability` 低于 scheduler contract 的固定下界时才提名；
否则该 scope 本 slot 明确返回 `NO_RESEARCH_NOMINATION`。同分依次选择较低
`operational_reliability`、较早 `last_mutated_at`、字典序较小 `agent_id`；peer scope
在最差 percentile 并列时使用同一 tie-break，不以稳定序列化顺序伪装统计优劣。
不同 scope 的提名不比较分数；
版本化 scheduler 按 `last_research_served_slot` 最早者轮转，并应用 layer quota，最后以
`production_variant_roster_id/scope_id/agent_id` 稳定打破调度并列。scope nomination、
service debt、active candidate 和 cooldown 的状态键都必须包含
`production_variant_roster_id`；相同 Agent 在另一语言/cohort 的状态不能阻止、放行或替代
本 variant 的 research slot。Darwinian weight 可作诊断，但不是跨 scope
排序代理或自动变更授权。KNOT 只能基于所选 track 的失败诊断提出一个最小 behavior
delta；不得改变角色边界、工具白名单、output schema、outcome label、component weight、
immutable phase instruction、Sector direction/ETF/comparison registry 或 research knobs
可见性。scheduler 必须在两侧调用前只物化一次
目标 Agent 的 root `AgentSnapshotBundle`；candidate 与 champion 使用各自独立
nonce/signature 的 capability，但必须指向字节相同的 root
`snapshot_bundle_id/hash`、tool payload hashes、runtime input hash、
`AgentToolCapability.allowed_tools` 和 frozen candidate scope。两侧实际选择调用哪些 optional
tool 属于被评价行为，但服务端只能返回该共同 bundle 中的 payload，不能实时重采集。
任一侧调用任意 ticker/raw collector、旧
`get_industry_policy_digest`、production RKE 或不同数据 vintage 时 pairing 无效并记为
contract failure，不能作为 candidate 改善。

每个 mutation manifest 必须冻结非空的
`target_variants: Array<{production_variant_roster_id; execution_behavior_release_id;
production_variant_roster_revision_id; cohort_id; language: "en" | "zh"}>`。五个字段必须共同解析到同一 active production
variant；只修改某一私有 prompt
变体时只登记该变体，不把未配对运行的其他 cohort/语言当诊断门。若一个 mutation 明确
同时改变多个 cohort 或中英文行为，则每个 target variant 都必须拥有独立且相同规则的
champion/candidate 配对 schedule、30 个成熟 paired scores 和晋级统计；任一目标变体失败，
整个多变体 promotion 不得部分发布。涉及职责块、工具白名单、schema 或 bundled invariant
的改动不属于 Autoresearch prompt mutation，必须走正常合同发布和全量测试。
KNOT 只可变更 cohort 私有的推理顺序、反证检查或表达策略；它不能把 endpoint/series
catalog、capability 字段、评分公式、Darwinian 状态或 research knobs 写进 prompt。
`RKE_SHADOW` 可拥有独立 research experiment namespace，但在本计划 shadow-only 不存在
通往 production prompt/behavior manifest 的 promotion edge。

每个 target variant 的 champion/candidate 使用同一
`production_variant_roster_id/production_variant_roster_revision_id/
execution_behavior_release_id/cohort_id/language`、同一冻结 root `snapshot_bundle_id/hash`、
同一 runtime input、同一 opportunity set 和同一
`RealizedOutcomeObservation` 独立运行；双方必须生成不同的 evaluation object、label ID、
raw metrics、utility 和 normalized score。mutation manifest 还必须固定 production private prompt commit、variant path、
champion/candidate content hash、canonical structured-output schema binding-set hash 和
provider mode；
bundled/fake prompt 不能与 private production variant 配对。候选拥有新的
`prompt_behavior_version`；若 provider/model revision、language、decoding、tool capability、
snapshot bundle、parser/repair、structured-output mode、schema binding set 和 immutable
phase instruction set 均未变化，则沿用同一
`execution_behavior_version`。只有这些 execution canonical fields 之一变化时才同时创建新的
execution version。shadow track 以 prompt/execution 两个版本精确匹配，不继承 champion
输出、样本或权重。候选创建时冻结 schedule epoch、最大研究窗口和停止规则，按时间顺序取最先 30 个
双方可问责的非重叠机会；`SCORE` 使用 normalized score，任一侧 `AGENT_FAILURE` 在研究
比较中固定使用 `KnotResearchScoreContract.agent_failure_score=-2`，双方共同的
`EXOGENOUS_EXCLUSION/PENDING` 不计且不能补挑有利日期。
同一冻结输入却出现单边 exogenous disposition 时整次 pairing 审计失败。运行失败仍保留
operational audit，不能只比较双方都成功的日期。晋级门使用的 candidate/champion
operational reliability 只从这条 `KnotResearchTrack` 的 shadow audit 对称计算；它不能读取
champion 同期 production audit，也不能写回 production operational reliability。

CIO 是唯一需要在一侧 pair 内执行多阶段依赖子图的目标 Agent。CIO champion/candidate
先共享同一份 pre-CIO root bundle、同一 Alpha accepted/skip 控制输入和同一
opportunity set；若该 Alpha 输入未由预注册 graph/replay 冻结，runtime 只执行一次 pinned
Alpha `KNOT_CONTROL_SHADOW` 并把同一结果复用于两侧，不得分别采样 Alpha。两侧随后分别
生成自己的 proposal，runtime 再按
`proposal -> CRO -> CRO-adjusted intents -> Execution -> CIO final` 独立派生 side-specific
bundle。两侧 CRO/Execution 必须 pin 相同的 production agent/prompt/execution contract、
解码策略、工具 manifest、底层市场数据 payload 和确定性算法版本；它们的 bundle hash
允许且只能因为本侧 proposal、CRO control 和由此派生的 frozen object set 不同而不同。
这些 Alpha/CRO/Execution 依赖调用固定为 `KNOT_CONTROL_SHADOW`：不生成依赖 Agent 的
outcome eligibility audit/label，不进入其 Darwin maturity、KNOT research track、usage
weight 或 operational reliability，也不得为依赖 Agent 生成
`KnotResearchScoreRecord`；每次实际调用仍必须生成
`production_reliability_eligible=false` 的 operational audit，供 CIO pair 的 dependency
阻断与运行诊断使用。
预先冻结并复用的 Alpha accepted/skip 也必须来自当前 CIO pair 的
`KNOT_CONTROL_SHADOW` namespace，分别解析到 control
`AcceptedAgentOutputRecord`/`KnotControlNoEvaluationObjectStageSkipRecord`；不得复用
production、KNOT research outcome 或“latest” Alpha 结果。

若某侧依赖对象为空，使用同一 control operational audit 派生的
`KnotControlNoEvaluationObjectStageSkipRecord` 并继续到 CIO final；不得创建或复用
outcome eligibility stage skip。若 Alpha、CRO 或
Execution 在任一侧发生无 accepted/skip 结果的 Agent failure 或 pre-run exogenous block，
该 CIO pair 写 dependency-blocked audit，不把 `-2` 归给 CIO，也不进入 30 个 CIO
accountable paired scores。该预注册 slot 仍被消费且不得换成同日/同事件的备用样本；候选创建
时冻结的最大研究窗口和停止规则保持不变，避免通过反复等待依赖成功来挑样本。CIO proposal
自身失败或 final 自身失败才是该侧 CIO `AGENT_FAILURE=-2`，且 proposal/final 在该 pair
中合计只形成一个 CIO research score。双方成功 final 后各自生成独立 evaluation object/
label，但共享覆盖两侧冻结证券域的同一 `RealizedOutcomeObservation`。这是前述“同一
root 输入出现单边 exogenous 即 pairing audit failure”规则在多阶段 dependency 下的封闭
处理：pair 仍失败、不可计分且消耗 slot，但 failure 不归因给 CIO，也不能被当成共同
exogenous 后静默跳过。

所有 KNOT 配对都绑定同一个版本化 `KnotResearchScoreContract`，mutation manifest 只保存
该合同的 ID/version/hash，不得选择或覆盖分数、成本、晋级或回滚系数。
该合同由全局 `KnotRuntimeContractManifest` 持有；Sector universe 只引用其 ID/version/hash，
不得拥有可独立漂移的合同副本。`runtime_agent_manifest_v3`、`KnotResearchTrack`、pairing
audit 与 promotion/rollback
revision 必须逐字段保存同一 ID/version/hash；非 Sector 也不得省略该绑定。每侧先确定性
计算唯一的 `research_comparison_score`：

```text
normalized_inference_cost =
    0.5 * clamp(input_tokens / total_stage_input_token_cap, 0, 1)
    + 0.5 * clamp(output_tokens / total_stage_output_token_cap, 0, 1)

sector_cost_adjusted_score =
    normalized_score
    - 0.2 * normalized_inference_cost
    - 0.05 * int(conflict_review_triggered)

raw_research_score =
    -2                                      if AGENT_FAILURE
    normalized_score                        otherwise

research_comparison_score =
    -2                                      if AGENT_FAILURE
    sector_cost_adjusted_score              if successful standard Sector
    raw_research_score                      otherwise
```

成功的标准 Sector 分数范围为 `[-1.25,1]`，其他成功角色为 `[-1,1]`，因此失败分
`-2` 严格低于任何合法成功结果，不能因成本惩罚而让失败优于成功。input/output 分母必须来自
本次配对共同冻结的 `SectorInferenceBudgetContract`；cap 为零、预算合同/hash 不一致、
token audit 缺失或归一化成本超出 `[0,1]` 时配对失败。该公式和常数只存在于 runtime
合同与审计，不进入任何 prompt。`AGENT_FAILURE` 不生成 `AgentOutcomeLabel` 或
`normalized_score`；`raw_research_score=-2` 是 research comparison 的确定性 failure
sentinel，不能写回 production outcome store。

对标准 Sector，champion/candidate 还必须绑定相同
`SectorInferenceBudgetContract` 和 `KnotResearchScoreContract`。每侧实际
direction-research/review/final call 数和 token 在推理结束时写入独立、不可变的
`SectorInferenceCostAudit`。成功 outcome 成熟后，runtime 才把该 cost audit 与该侧唯一
`AgentOutcomeLabel` join 到 `KnotResearchScoreRecord` 并按上述公式计算
`sector_cost_adjusted_score/raw_research_score/research_comparison_score`；失败侧不等待
outcome，直接生成无 label、两个 research score 均为 `-2` 的 score record。非 Sector
成功侧的 score record 固定令 raw/comparison score 都等于 normalized score，且不得绑定
Sector cost audit。score record append-only 且由 pair side 唯一键幂等生成，cost audit
不得在未来 label 成熟时被回写。

这些 penalty 只用于 KNOT research efficiency，不写回 production
`AgentOutcomeLabel/normalized_score/Darwinian weight`。review 由相同的确定性 conflict
resolver 触发，candidate 不能自行请求；预算违例或额外 subcall 仍是 `AGENT_FAILURE`。晋级
审计同时报告 review rate、平均 calls、input/output tokens 和 `sector_cost_adjusted_score`；这样允许
必要复核改善结果，但候选不能靠更高复核率或更多 token 获得免费的演化优势。

晋级必须同时满足：

- 至少 30 个按上述规则确定的 paired research scores，成功 label 必须成熟且 PIT 合法；
- paired `research_comparison_score` 差的均值至少 `+0.05`，且 raw
  `raw_research_score` 差的均值不得为负；两者都使用全部 30 个可问责 pair，failure
  以 `-2` 进入，不能只在双方成功的子集上重算。预注册 block-bootstrap 95% CI 下界
  大于 0，且同一批候选的单侧检验通过 Benjamini-Hochberg `q<=0.05`；
- `candidate_operational_reliability >= champion_operational_reliability - 0.05`，且 schema/语义拒绝、
  未授权工具、fallback、隐私、role boundary 和 hard-risk 测试均无回归；
- 标准 Sector candidate 的 review rate、平均 model calls 或 token cost 任一超过 champion
  的预注册容忍带时不得晋级，除非 paired `research_comparison_score` 差的 CI 下界仍通过且没有预算
  breach；具体容忍带属于版本化 scheduler contract，penalty 系数属于
  `KnotResearchScoreContract`，mutation manifest 只固定两者的 ID/hash，均禁止进入 prompt；
- manifest 中每个 target variant 的 holdout regime 均不超过预注册 5% 恶化门槛；
  未登记且没有 paired schedule 的语言/cohort 不得充当放行或否决统计。

promotion 从未来 research slot 生效：先在私有 prompt 仓提交晋级后的 target variant，
再发布新的 `ExecutionBehaviorReleaseManifest` 和受影响 stable production variant 的
`DarwinProductionVariantRoster` revision；未变 Agent/variant 复用原 content/version/track
hash，只有晋级 Agent 建立新的空 production evaluation track，并在
`DOWNSTREAM_USAGE_WEIGHT` 模式下建立唯一 1.0 usage initialization。多 target promotion
必须在同一新 release 中全部切换或全部不切换，不能部分发布。上一 champion 保留供回滚，
不追溯改写历史，也不把 promotion 前的 research label 计入 production Darwin 成熟度或
usage weight。晋级后前 20 个成熟非重叠样本继续让旧 champion 在相同冻结输入上
shadow；出现任何 hard safety/privacy/contract failure 立即回滚，或 paired mean delta
（统一使用 `research_comparison_score`）
`<=-0.05`、raw `raw_research_score` mean delta 为负，或 operational reliability 落后超过
0.10 时在下一个 slot 回滚。回滚写新
private prompt/behavior release 与 roster revision，不删除失败候选轨道，并启动预注册
cooldown。所有 selection、mutation、
pairing、promotion、rollback 和 multiple-testing manifest 都需 content hash 和唯一 ID，
相同 research slot 重跑必须 no-op。

## 11. Market Breadth 不变部分

`get_market_breadth_snapshot` 继续由确定性代码计算：

- PIT 股票池：当日已上市且未退市、至少 60 个交易日历史、当日非停牌。
- 仅使用截至 `as_of` 已知的复权因子。
- 核心指标：
  - `advance_decline_balance`
  - `above_ma20_pct`
  - `above_ma60_pct`
  - `new_high_low_20d_balance`
  - `turnover_expansion_pct`
  - `return_dispersion`
  - `top_decile_turnover_share`
  - `eligible_count`
  - `observed_count`
  - `coverage_ratio`
- 核心 composite 等权使用涨跌平衡、趋势广度、新高新低和成交扩散。
- 状态使用截至当日 252 日滚动分位数和 20 日变化：composite 高于自身
  60 分位且 20 日变化为正时为 `BROADENING`；低于 40 分位且 20 日变化
  为负时为 `NARROWING`；其余为 `MIXED`。
- `top_decile_turnover_share` 高于自身 80 分位为高集中度，低于 20 分位
  为低集中度，其余为中等集中度。
- 核心覆盖率低于 90% 时拒绝。
- 涨跌停只作 2020 年后的可选诊断。
- 不读取 `eco_cal` 或 World Bank。

## 12. Prompt 重建

### 12.1 唯一合同源

TypeScript `ClaimSchemaV2`/其他 Zod schema、职责矩阵、第 6.1.1 节 28-Agent 工具矩阵、snapshot projection、
事件用途矩阵、工具白名单、`KnotRuntimeContractManifest`/`KnotResearchScoreRecord`、
`CausalEvidenceResolutionSet`、`SectorUniverseManifest`、
`SECTOR_DIRECTION_METRIC_REGISTRY`、benchmark query/`SectorSecurityScoringContract`/
least-qualification/reducer contract、`SectorCatalystCoverageSummary`、
`FrozenRelationshipPredictionOpportunitySet` 与
四个 Decision submission/accepted/model-view discriminated contract及 CRO/Execution
per-item accepted ref/hash、第 10.1 节 `OperationalOpportunityAudit` 与
`AcceptedOutputPayloadRegistry/AcceptedAgentOutputRecord`、opportunity-set
success/failure audit union、
第 10.4 节四个
Decision raw-metrics family，以及
`GEOPOLITICAL_INITIAL_SOURCE_MANIFEST` 的强类型 registration/adapter/route-query coverage-scope
合同是唯一合同源。运行时从这些版本化 manifest 生成 schema、工具、角色块、query/route
hash 和 KNOT immutable block；禁止以 opaque hash、Markdown 表或 collector 默认值补全
sector/geopolitical 行为。删除：

- 手写 JSON 示例。
- 过期工具说明。
- Python bridge 重复字段表。
- 跨角色先验。
- 暴露内部实现的 research knobs。

Zod 生成的 JSON Schema 不复制进 prompt 正文，而由 provider adapter 通过结构化输出
`response_format` 或等价的强类型 tool schema 在模型调用时 out-of-band 提供。每个实际
模型 phase 的 schema ID/hash 必须形成有序、闭合的 schema binding set；其 canonical set
hash、provider structured-output mode 和 parser/repair policy 必须进入
`execution_behavior_version`；provider 不能强制该 schema、返回 schema drift 或退化为自由
文本时节点拒绝，不能靠 prompt 中的合同名称猜字段，也不能恢复手写 JSON 示例。
标准 Sector 额外注册
`DIRECTION_RESEARCH/CONFLICT_REVIEW/FINAL_SELECTION` 三个 phase schema ID/hash；三者共享
同一简洁角色 behavior block 和 snapshot bundle，但 structured-output schema 不可互换。
未发生冲突时 review schema 不调用，任何 phase 返回另一个 phase 的字段均直接拒绝。
CIO 同样必须注册 `CIO_PROPOSAL/CIO_FINAL` 两个不同 phase schema ID/hash；其他逻辑 Agent
恰好使用一个 `DEFAULT` binding。一个私有 prompt 文件仍对应一个逻辑 Agent variant，
多 phase 只增加 manifest binding，不增加逻辑 Agent、prompt 文件或 Darwinian track 数量。
标准 Sector/CIO 的私有文件只保存共享角色与 cohort behavior block；runtime 根据当前 phase
追加由同一合同源生成、不可由 cohort/KNOT 修改的最小 phase instruction。phase instruction
hash 必须与 schema binding 一起进入 behavior manifest，不能把 proposal/final 或
research/review/final 的差异藏在未版本化的拼接字符串中。

### 12.2 bundled prompt

- 默认 cohort 中英文 prompt 按新 28-Agent manifest 重新生成；任何旧 Agent ID、通用
  ticker 工具、`get_industry_policy_digest` 或 production RKE 工具使构建失败。
- 内容保持简洁且顺序固定为：一句角色目标、职责禁区、该角色零参数工具、PIT/证据
  要求、生成的 output contract 引用。endpoint/series catalog、capability manifest、
  原始 source-registry readiness、Darwinian/KNOT 状态不写入 prompt；模型只读取快照中
  已接受的 data-quality/PIT 字段。
- MOSAIC-Combat-Evolved 不出现 `research_knobs`、内部字段名或旋钮值。
- prompt 只描述角色限定事件投影，不允许 Agent 自行查询原始
  `eco_cal`。
- Sector/Superinvestor/Decision prompt 只说明 runtime 已冻结候选域和上游输入，不暴露
  scope hash/ledger ID；模型不得请求扩域。Sector prompt 必须要求从 snapshot 给出的注册方向
  中研究方向，但不得提交总体 pair winner、preferred/least 或 picks：`n>=2` 时对全部 eligible
  无序 pair 的八个固定 criterion 完成结构化 verdict；`n=1` 时对唯一方向与注册 null 使用相同
  八项 criterion 完成 qualification。runtime 按四个 core、两个 coverage-gated 一票和可比
  ETF 半票的冻结加权规则解析 A/B/`NO_CLEAR_WINNER`。`MACRO_EVENT_FIT` 仅在
  `RoleEventCoverageSummary=SOURCE_UNAVAILABLE` 时为 `NO_VOTE`；
  `CATALYSTS` 仅在对应两侧 `SectorCatalystCoverageSummary` 任一不可用时为 `NO_VOTE`。
  一项 coverage 不得改变另一项的 verdict，两个 `NO_VOTE` 都不得写成中性；若 runtime
  请求唯一一次 conflict review，
  review prompt 只允许
  重提冻结冲突集合内部 pair，仍不得提交 final selection。reducer 与
  `LeastPreferredEligibilityAudit` 完成后，独立 final-selection prompt 只接收净化后的
  `ModelVisibleSectorFinalSelectionDirective`、精确 scoring shortlist，以及 stage 开始时已
  冻结且与前两阶段同 hash 的十个 model-visible Macro 输入/authoritative usage share；
  不接收完整 pair matrix、Copeland 分数或内部 audit。这样 final submission 可以生成必需
  Macro attribution，但不能重新研究方向或改变 reducer。模型必须逐字段服从
  `REQUIRED/NOT_QUALIFIED/NOT_APPLICABLE`，同时输出受约束 picks、drivers、risks、
  claims/evidence 和 Macro attribution，不得自行用 confidence 决定是否省略 least。ETF
  只作为卡片中已验证的 optional supplemental confirmation，缺失必须标为
  `INCOMPARABLE` 而不得判负，可比时由 runtime 以固定半票有限影响 resolver；不得在 prompt
  正文手写 direction/ETF catalog、技术指标公式、
  reducer 或 outcome 评分公式。Macro prompt 只列该角色唯一 snapshot。
- bundled `cohort_default` 只作为公开仓 fake/offline fallback；它不是 production prompt
  registry。其 canonical behavior block 必须与私有仓同语言 `cohort_default` 字节一致，完整
  content hash 也写入 manifest。fake/offline 调用使用显式不同的
  `execution_behavior_version`，并禁用正式 accepted/audit/outcome/weight writer；它只在
  隔离的 ephemeral graph state 中验证 schema、阶段和路由，不创建可被查询的
  `AcceptedAgentOutputRecord`、operational/outcome audit、label 或 Darwinian/KNOT 样本。
  因而不得用 `PRODUCTION_ACTIVE` 伪装 fake sample，也无需向正式 sample-origin union 增加
  测试专用分支。

### 12.3 私有 cohort prompt

```ts
type StructuredOutputSchemaPhase =
  | "DEFAULT"
  | "DIRECTION_RESEARCH"
  | "CONFLICT_REVIEW"
  | "FINAL_SELECTION"
  | "CIO_PROPOSAL"
  | "CIO_FINAL";

interface StructuredOutputSchemaBinding {
  phase: StructuredOutputSchemaPhase;
  schema_id: string;
  schema_hash: string;
  immutable_phase_instruction_hash: string;
}

interface ExecutionBehaviorReleaseVariant {
  variant_path: string;
  agent_id: AgentId;
  cohort_id: string;
  language: "en" | "zh";
  prompt_content_hash: string;
  immutable_contract_block_hash: string;
  prompt_behavior_version: string;
  execution_behavior_version: string;
  structured_output_schema_bindings: [
    StructuredOutputSchemaBinding,
    ...StructuredOutputSchemaBinding[],
  ];
  structured_output_schema_set_hash: string;
  runtime_tool_manifest_hash: string;
  knot_champion_baseline_hash: string;
}

interface ExecutionBehaviorProductionVariant {
  production_variant_roster_id: string;
  cohort_id: string;
  language: "en" | "zh";
}

interface ExecutionBehaviorReleaseManifest {
  execution_behavior_release_id: string;
  execution_behavior_release_hash: string;
  private_prompt_commit: string;
  active_production_variants: [
    ExecutionBehaviorProductionVariant,
    ...ExecutionBehaviorProductionVariant[],
  ];
  variants: [
    ExecutionBehaviorReleaseVariant,
    ...ExecutionBehaviorReleaseVariant[],
  ];
}
```

`structured_output_schema_bindings` 必须按 `phase` canonical 排序且 phase 不重复：
九个标准 Sector 恰好包含三个 Sector phase，`cio` 恰好包含两个 CIO phase，其余 18 个
逻辑 Agent 恰好包含一个 `DEFAULT`。`structured_output_schema_set_hash` 必须覆盖完整有序
binding 数组，包括每个 `immutable_phase_instruction_hash`；单个 schema hash、缺 phase、
额外 phase、phase instruction 漂移或按调用时临时选择未登记 schema 均使 release 失败。
`runtime_tool_manifest_hash` 也必须覆盖多 phase capability policy：标准 Sector 固定为仅
`DIRECTION_RESEARCH` 有工具，CIO 固定为 proposal/final 两个 stage 各自的
`get_cio_decision_snapshot()` phase payload；遗漏该策略或只哈希工具名列表不算完整
execution behavior。

- 重建 8 个 cohort × 28 个 Agent × 2 种语言的全部 448 份私有 prompt：
  160 份 Macro、160 份 Sector（其中 48 份为新增 `technology`、
  `real_estate_construction` 和 `agriculture`）、64 份
  Superinvestor 和 64 份 Decision。
- 初始 release 的 `active_production_variants` 必须恰好覆盖 8 个 cohort × 2 种语言的
  16 个唯一 key；`production_variant_roster_id` 必须等于 cohort/language 的 canonical
  stable ID。每个 key 必须恰好解析到 28 个 Agent variant，并生成一个
  stable `production_variant_roster_id` 和该 release 的
  `DarwinProductionVariantRoster` revision。后续 release 只为 behavior/合同主键实际变化的
  Agent 创建新 track，其余 Agent 在新 roster revision 中复用原 track；若停用某个
  cohort/language，必须发布新的
  execution behavior release；不能只删除 Darwin track 或在查询时临时忽略。
- `.zh.md` 必须使用自然中文，`.en.md` 必须使用英文。
- 职责、禁区、工具和 schema 块在所有 cohort 中不可变。
- cohort 必须保留不同的研究视角、反证路径或压力测试重点，不能完全相同。
- cohort 差异不得变成方向性先验、隐藏旋钮或不一致输出合同。
- 每个私有 prompt 的 immutable block hash 必须等于对应 bundled contract block；KNOT
  只能修改 manifest 指定的 cohort behavior block。合同迁移后 448 份 prompt 和 KNOT
  champion manifests 必须在同一 `execution_behavior_release_id` 原子发布，禁止新旧工具块
  混用。每个 variant manifest 绑定自己的 `execution_behavior_version`；因为该 hash 包含
  language、provider/schema/tool runtime 等行为字段，中英文 variant 不得伪装成同一个
  version。release manifest 必须列出全部 448 个
  `variant_path -> prompt_behavior_version -> execution_behavior_version` 映射并整体签名，
  只保证它们属于同一原子合同发布，不要求所有 hash 相等。
- 私有 prompt registry 是 production 唯一 canonical source；runtime 必须加载公开运行清单
  固定的 private commit、variant path、content hash 和 language。文件缺失、hash 不符或私有仓
  不可用时 production fail closed，不得切到 bundled。私有 `cohort_default` 与 bundled
  canonical behavior block 不一致时发布失败；其他七个 cohort 必须保留各自非空 behavior
  block 差异。

统一要求：

- 检查 `as_of`、发布与 vintage 有效性。
- 检查变化、预期差和证据冲突。
- 明确 A 股传导渠道。
- 禁止空壳 claim、模糊空数组、跨角色结论和无证据百分比。
- Sector、Superinvestor、`cro`、`alpha_discovery` 和 `cio` prompt 必须消费十个
  直接 Macro 输入并输出十条 `SUBMISSION_SUMMARY` 及必要的目标级
  `MacroInputAttributionSubmission`，不得描述六因子、Macro 综合分数或 Macro stance。
- `autonomous_execution` prompt 不得包含十个 Macro outputs 或 Darwinian
  usage share，只消费 CIO/CRO 与 execution-timing 合同。
- `alpha_discovery` prompt 只消费 frozen novel universe、其市场/财务/催化与 role-event
  快照、静态风险/资格约束和已冻结上游 inputs，不得引用同轮尚未发生的 CIO
  proposal/CRO/Execution；`cro` prompt 只能审查本轮
  CIO proposal 确定性派生的完整 candidate universe，不得从 Alpha 或上游另加证券。
- `cio` proposal prompt 必须显式消费 Alpha accepted/skip 并把采纳候选纳入 pre-CRO
  完整目标组合；final prompt 重新读取与 proposal 字节相同的 pre-CIO
  Macro/Sector/Superinvestor snapshots，只能在同一 proposal 候选域内解析 CRO/Execution
  controls 和重做最终 attribution，不得重新运行 Alpha、增加 proposal 外候选或用更新后的
  上游快照改写 thesis。
- 模型只看到 runtime 计算后的 `usage_share`，不得看到 raw Darwinian weight、
  operational/effective reliability、record IDs、adapter version 或 promotion thresholds。
- `primary_label_id`、具体 outcome 公式、quartile 边界、Darwinian weight 和
  成熟评分结果都是运行时评分/审计元数据，不注入 bundled 或私有 Agent
  prompt，避免模型围绕评分代理指标进行反向优化。

## 13. 隐私与许可边界

- Tushare、Eurostat、ECB、World Bank 和官方发布的原始响应
  仅进入本地私有缓存。
- 提交物只包含 schema、代码、预注册映射、哈希、脱敏 fixture 和审计。
- 不提交新闻原文、许可内容、token 或本地缓存。
- `major_news/news/npr/monetary_policy` 权限状态固定为禁用，不注册工具、不发起
  请求；新闻接口不形成情绪票，政策接口缺失不解释为“无政策变化”。
- 不调用 OpenCLI、Google/Caixin 搜索或实时雪球关注数生成正式因子。
- `get_rke_research_context` 只存在于 `RKE_SHADOW` capability 和隔离 state；任何 production
  prompt/tool manifest/graph edge、accepted output、候选域或 Darwinian 更新引用均为发布阻断。
- prompt 私有仓只存双语 prompt，不存数据响应。

## 14. 实施顺序

### 阶段 A：合同和迁移

1. 更新 Agent roster、ID、职责矩阵、工具白名单和 Zod schema，并将
   runtime-only `DownstreamWeightedAgentInput`/封闭 `DownstreamAgentInput`、
   `DownstreamDecisionInput`、model-only `DownstreamModelInput`、
   `MacroInputAttributionSubmission/AcceptedMacroInputAttribution`、显式
   `ModelVisibleAcceptedSectorSelection/ModelVisibleAcceptedSuperinvestorSelection`、
   四个 Decision submission、五个 accepted phase output 及对应 model-visible DTO、
   `AcceptedOutputPayloadRegistry/AcceptedAgentOutputRecord`、
   `NoEvaluationObjectStageSkipRecord`、`KnotControlNoEvaluationObjectStageSkipRecord`、
   `ModelVisibleNoEvaluationObjectStageSkipRecord`、
   `DecisionStageSourceRef/DecisionControlSourceRef`、
   `CausalEvidenceResolutionSet`、`KnotResearchScoreRecord` 和 model-visible causal
   resolution 白名单
   纳入同一合同源；accepted Sector/Superinvestor 保存解析后的 attribution，raw local-ref
   submission 只进入 submission audit；
   同步实现第 6.1.1 节预物化 `AgentSnapshotBundle`、签名 capability envelope、原子
   `(capability_id,tool_id)` 使用账本、服务端 `tools.list/tools.call` 强制校验和零参数角色
   快照，禁止仅靠 prompt whitelist 控权或在 tool call 中重新采集。
2. 分离 model submission 与 accepted transmission，增加组件、数据质量、事件
   投影和证据所有权合同；将现有可选字段式
   `CroOutput/AlphaDiscoveryOutput/AutoExecOutput/CioOutput` 迁移为第 3 节封闭
   discriminated schema，proposal/final 使用不同 schema 和 accepted record。
3. 为全部跨层输出增加 `EvidenceLineageEnvelope`；每个消费者调用前冻结其全部获准
   source-layer snapshot，生成唯一 `consumer_input_snapshot_id/hash` 及完整、按 key 排序的
   `CausalEvidenceResolutionSet`；graph state/persistence 只保存
   `AcceptedAgentOutputRecord` ID/hash，runtime transport 从 record 投影 envelope，model
   transport 再投影白名单 DTO；
   禁止消费者跨层比较 confidence 或自行重算去重结果。
4. 删除六因子和 Macro stance 聚合代码，将 `aggregate_l1` 替换为
   `macro_input_gate`，并更新十个命名 graph-state accepted-record 引用、直接下游路由、
   Darwinian 元数据和旧角色迁移。
5. 对 `layer1_consensus` 做完整消费者清单并逐一迁移：state/types、Layer-2 Sector
   factory、Layer-3 Superinvestor factory、Decision user context/runtime、daily-cycle、
   layer graph/subgraph、CLI 输出、backtest/backtest-evolve、Python scorecard/bridge、
   fixtures 和文档。production graph/state 不得再读写该字段；历史回放只通过显式
   `legacy_layer1_consensus` read-only adapter，且不能进入新 outcome 或权重轨道。
6. 新建 `runtime_agent_manifest_v3`、对应 JSON schema、28-Agent domain catalog/
   prompt-check manifest 和 RKE delivery/readiness contract；不得原地改写仍代表
   25-Agent/26-stage 历史语义的 v1/v2 artifacts。同步更新 manifest generator、Python
   schema validation、prompt bridge、registry required-file 清单、wiki/CLI 文档和固定
   benchmark matrix。RKE 继续 shadow-only，迁移不能让 report-derived signal 进入生产。
7. 单独清点并迁移 RKE shadow 的 Agent ID/字段路由，至少覆盖
   `mosaic/rke/agent_research_context.py`、`mosaic/rke/report_intelligence.py`、
   `mosaic/rke/macro_expansion.py` 和 `mosaic/rke/phase_minus1.py` 中的
   `macro.dollar/macro.yield_curve/macro.volatility`、25-Agent roster 与 delivery 映射。
   旧 artifact 原样保留 `legacy_unverified`；新映射只按第 2.1 节 data-field route 分发，
   不 alias 身份、不继承旧 outcome/weight，且仍为 shadow-only。
8. 以 feature-gated 双读验证新旧持久化记录，production cutover 后只写 v3；旧 manifest、
   旧 Agent 输出和旧 Darwinian 表只读并标记 legacy，不得被“latest”查询混入。
9. 先写失败测试，覆盖旧 ID、越权工具、模型伪造 lineage、重复证据、任何 production
   `layer1_consensus` 引用，以及旧 25/26 roster 或 26/27 stage 常量漂移。

### 阶段 B：共享事件基础设施

1. 实现 `eco_cal` 分片采集、私有缓存和权限预检。
2. 实现 retrieval batch、逐字段解析、跨批次 revision、批内 conflict、不可变
   retrieval observation 和 PIT 选择。
3. 实现 owner/consumer 投影、lineage envelope 与跨层用途限制。
4. 将投影注入 Macro 快照，并实现运行时身份绑定的零参数
   `get_role_event_snapshot()`；分别计算 event presence 与 required-route completeness，
   保存 required/healthy/unhealthy route 分区，部分事件加任一 route 故障仍确定性映射为
   `SOURCE_UNAVAILABLE`。
5. 实现第 6.8 节 geopolitical official/discovery adapters、append-only event lifecycle、
   分 route/source/scope-query coverage health、再确定性聚合 event-type coverage、30 日
   availability/latency preflight、来源独立性、
   去重确认和 `get_geopolitical_events_snapshot` 失败关闭；加入 MARAD/UKMTO 航运源，
   提交 `GEOPOLITICAL_INITIAL_SOURCE_MANIFEST` 的强类型 registration、
   `GeopoliticalSourceAdapterContract`、approved-domain 和
   `GeopoliticalCoverageScopeContract`，重算每个 adapter/route/scope-query hash，并证明全部
   applicable actor/event、region/event 和 GLOBAL route 的 closure；每条 applicable route
   还必须绑定非空
   `no_event_evidence_source_ids`，逐一验证其为 required-source 子集且对应 adapter 的
   `no_event_claim_capable=true`，并以健康、完整、未截断的连续查询 fixture 验证
   `COVERAGE_CONFIRMED_NO_EVENT` 不能由 discovery/confirm-only source 生成；冻结武装冲突
   和外交 watchlist 连续查询。四个无权限
   Tushare endpoint 只保存在第
   6.1 节唯一 registry，不能在 geopolitical registry 复制状态，也不能生成 client、
   tool binding 或轮询 job；删除现有 `_NEWS_SOURCES`、fixture 和 crawler default 中的
   `tushare.major_news/tushare.news` production 分支，历史记录只读并标为 legacy。
6. 将 `mosaic/dataflows/tushare_catalog.py`、全部 series map、bridge 和 collector 引用
   收敛到封闭 `TushareEndpointId` registry；未知字符串编译/启动失败，并对每个
   `PRECHECK_REQUIRED` endpoint 生成真实权限、非空 schema 和 PIT 字段证据。注册表必须
   覆盖第 6.1.2–6.1.4 节新增的 `daily_basic`、`suspend_d`、`stk_limit`、`index_classify`、
   `index_member_all`、`index_weight`、`fund_adj`、`stock_st`、
   `stock_company`、`fina_indicator`、`forecast`、`express`、`income`、
   `balancesheet`、`cashflow` 和 `research_report`；任何未激活 endpoint 都不能被
   snapshot 静默忽略或 fallback。

### 阶段 C：中国与 PBOC 数据

1. 冻结第 6.2 节 `CHINA_MACRO_SERIES_MAP` 五个 `china` 组件和五个 PBOC/中国利率
   series family 的 source contract，验证国家统计局、海关总署、财政部和 PBOC 官方目录
   URL 层级、分页、发布/生效时间、历史覆盖、许可和 freshness；缺少确切目录的 adapter
   保持 `PREFLIGHT_REQUIRED`，不得先写生产映射。
2. 复用并测试 `mosaic/dataflows/pboc_ops.py` 的公开市场操作目录，新增 LPR、货币政策
   委员会/执行报告、金融统计/社融的 append-only adapter 与脱敏 fixture；为 MPC 和执行
   报告分别建立带来源、revision 和证据的 expected-release calendar，冻结
   `+15 calendar days grace/+150 calendar days hard cap`，不得复用 Fed/ECB 90 日规则。
3. 对 `cn_gdp/cn_pmi/cn_cpi/cn_ppi/shibor/shibor_quote/yc_cb` 执行统一 Tushare registry
   的权限/schema smoke；任何
   未通过项不得进入 `china_money_market_curve`，替代源必须独立注册而非 fallback。
4. 实现 `get_china_macro_snapshot` 和 `get_central_bank_snapshot` 的 required coverage、
   PIT vintage、频率感知 freshness 与失败关闭；用历史 `as_of` 验证后来正文/修订不泄漏。
5. 参数化验证同一信用发布在 `china_credit_impulse_quantity` 与
   `pboc_credit_conditions_price_access` 的字段级投影、PRIMARY/CONTEXT_ONLY ownership
   和共同 causal key；重复的信用数量方向必须拒绝。
6. 只有两组各五个 required component/family 的 adapter、30 日采集审计（低频源以计划发布/事件机会计）、目录
   schema 与 snapshot smoke 全部通过，China/PBOC 数据阶段才可 `READY`。

### 阶段 D：美国、商品与市场定位数据

1. 冻结第 6.3 节 ALFRED/Fed/NY Fed source map，验证所有 series metadata、release、
   vintage、单位和频率；实现 `eco_cal` 与 official actual/vintage 的 PIT reconciliation；
   将现有仅允许 `us_economy` 的 ALFRED role gate 迁移为精确 series-to-role map，使
   `DFII5/DFII10/DFII30/BAA10Y/NFCI/VIXCLS/DTWEXBGS` 仅投影给
   `us_financial_conditions`，实体 series 仍仅归 `us_economy`。
2. 对 `us_tycr/fx_obasic/fx_daily` 执行权限、具体 instrument、schema、日历和历史覆盖
   preflight，冻结 `USD_CNY/EUR_CNY/EUR_USD` 角色映射；禁止 DXY 或未注册交叉盘。
3. 实现 `get_us_macro_snapshot/get_us_financial_conditions_snapshot` 四组件 required
   coverage、角色日历 freshness 与失败关闭，并验证实体摘要只为 `CONTEXT_ONLY`。
4. 冻结并实现 `COMMODITY_CONTRACT_MAP`、真实合约期限结构条件和
   `get_commodity_conditions_snapshot`；实现 `get_market_positioning_snapshot` 的
   market/industry/ETF universe/share-adjusted-price 四分支、`fund_adj` 和
   share/corporate-action adjustment，以及 optional crowding 数据。
5. 对 Sector direction ETF confirmation 和 market positioning required ETF 分支使用的
   `fund_basic/etf_index/fund_daily/fund_adj/fund_share/fund_nav` 执行权限、schema、
   上市退市、价格复权、份额/NAV 公告时间和历史覆盖 preflight；结果写入
   optional source status，失败不得阻断 Sector required basket technicals，也不得生成伪零流量。
6. 仅将 US/EU 收入暴露 collector 中错误的 `fina_mainbz(type=P)` 路径迁移为 `type=D`；
   Sector 产品结构的 `type=P` 路径保持独立。实现 `disclosure_date` 的
   append-only capture 及上交所/深交所/北交所公告 metadata 核验；无法证明 historical
   release time 的地区收入从 `first_seen_at` 才可用。统一修复财务、基金持仓、股东和
   研究数据的 release-time join：必须使用第 6.1.4 节注册的
   `f_ann_date/ann_date/actual_date/first_seen_at`，禁止 `end_date` 作为可见时间。
7. 为上述所有 required endpoint/source 运行权限、非空 schema、PIT、coverage 与
   freshness smoke；任一 source map 未 READY 时对应 snapshot/labeler 保持拒绝。

### 阶段 E：欧盟和 World Bank

1. 通过官方 catalog/metadata 逐项验证第 6.4 节 Eurostat/ECB 完整 key、dimensions、
   非空响应、series title、单位、频率、status 与 structure hash；固定
   `metadata_verified_on`，结构漂移时失败关闭。
2. 实现 Eurostat、ECB 采集器。
3. 实现官方 vintage、append-only 和 reconciliation；保存 `geo_composition_at_vintage`，
   changing-composition EU aggregate 与固定 `EU27_2020` 分离，未完成成员国重建方法合同前
   不得拼接或进入历史评分。
4. 实现 World Bank `CONTEXT_ONLY` 补充映射。
5. 实现 required coverage、expected-release freshness、grace 和 hard cap。
6. 复用阶段 D 的 `fina_mainbz(type=D)` 公告时间合同，实现 EU27 历史成员映射、
   PIT 代理篮子和 relationship 匹配非边数据合同；权限或历史覆盖不足时失败关闭。

### 阶段 F：Agent、图和评分

1. 新增 `eu_economy`、`us_financial_conditions`、
   `euro_area_financial_conditions` 三个目标 Macro Agent 并删除旧运行节点。
2. 扩展 `central_bank`，新增 `technology`、`real_estate_construction` 和 `agriculture`，
   将汽车从 `industrials` 移入 `consumer`，将光伏/风电/电池从电力设备中拆入
   `energy`，把煤炭与石油石化保持为两个独立 direction，并把第 6.1.2 节已冻结的八个
   农业 L2 literal code 通过真实 `index_classify/index_member_all` metadata、成员有效期和
   coverage preflight 固化为四个非空、无重叠且完整覆盖 parent 的 exact-L2 direction，
   禁止 `agriculture_total` fallback；按第 6.1.2 节重建工业 exact-code 范围。为九个标准 Sector 实现
   含 direction-partition/parent/single-null 三类 benchmark 的 `SectorDirectionContract`、显式
   tagged benchmark universe query plan、精确 scoring shortlist、Sector/Superinvestor
   model-visible 白名单 DTO、恰好一个 preferred 和由
   `LeastPreferredEligibilityAudit` 决定的可选 least-preferred accepted validator。
3. 按第 8 节迁移波动率数据：VIX/美国隐含波动只进入
   `us_financial_conditions`，已注册 CISS 只进入
   `euro_area_financial_conditions`，中国实现波动只进入 `cro` 风险状态；不创建欧元区
   未注册隐含波动分支，也不让 Execution 独立重复判断。
4. 更新 28 Agent / 29 阶段图、fake fixtures 和 scorecard；Decision 子图固定为
   `alpha_discovery -> cio(PROPOSAL) -> cro -> autonomous_execution -> cio(FINAL)`，
   proposal 显式绑定 Alpha accepted/skip，CRO universe 只从 proposal 派生，final 不得绕过
   proposal 重加 Alpha 候选；CIO final 必须复用 proposal phase 字节相同的 pre-CIO
   Macro/Sector/Superinvestor snapshots，并与 proposal/final 共用一个 logical run 和
   operational opportunity。
5. 实现十个直接 Macro accepted-record graph-state 引用、`macro_input_gate`、Darwinian/
   operational reliability 元数据、覆盖 scheduled/downstream-only 的唯一
   `AcceptedAgentOutputRecord/OperationalOpportunityAudit`、model/runtime 双视图、不可变
   source-layer snapshot、graph/cohort/language 一致性、按具体 Agent 关联的
   Superinvestor/Decision stage-skip mapped union、
   无自引用目标 attribution validator 和 execution 隔离。
6. 实现组件和三个 DIRECT Macro 的数据质量合同及确定性质量计算，accepted/downstream/
   outcome 统一使用 effective confidence，模型原始 confidence 单独留审计。
7. 实现带自身 ID/hash、`PRODUCTION_ACTIVE` literal、accepted-record/final-operational
   外键的组件信号，以及固定五日 outcome、校准审计和权重合同的 append-only 存储。
8. 实现仅使用版本化 `cohort_default/zh`
   `COMPONENT_CALIBRATION_REFERENCE_VARIANT` 的组件校准器、purged walk-forward 验证、
   其余 production variant 分离诊断、shadow 和版本晋级。
9. 实现组件权重、prompt behavior 与 Darwinian 评分轨道的隔离和迁移。
10. 按每个 active `(execution_behavior_release_id, cohort_id, language)` production variant
    建立 stable roster ID 和该 release 的 `DarwinProductionVariantRoster` revision，并将全部 28 个逻辑 Agent 注册为
    `DarwinEvaluationTrack`；只为 10 Macro、10 Sector、4 Superinvestor 创建该 variant 的
    24 条 `DarwinUsageWeightTrack`，四个 Decision 固定
    `EVOLUTION_ONLY` 且不得存在 weight row。本 v2 initial release 的 prompt/runtime/output/
    outcome 合同整体变化，因此 24 条 usage track 全部创建唯一 1.0 冷启动记录，28 条
    evaluation track 全部从零成熟样本开始；不得只重置新增 ID 或 Sector。
    上述创建与迁移必须对初始 16 个 production variant roster 逐一执行，
    并实现有界 Q1/Q4 渐进更新、精确定义的 30 样本/coverage/tie rank contract、
    五交易日 update slot、原子 update batch、单调 outcome sequence checkpoint、幂等
    event ID、统一 snapshot 和审计记录。
11. 实现 `OUTCOME_LABEL_REGISTRY` 生成的强类型
    `AgentOutcomeContract/RealizedOutcomeObservation/AgentOutcomeLabel/AgentOutcomeEligibilityAudit`、28 Agent
    矩阵、两个同质 peer rank scope、十个 Macro self scope、`sector_relationship` 和
    四个 Decision self scope
    的冻结 null/scale 归一化合同；按第 10.4 节实现四个封闭 Decision raw-metrics Zod family、
    deterministic labeler 和 TS/Python fixture；CIO audit 必须封闭 proposal/final 自身失败阶段、
    Alpha/CRO/Execution dependency block、accepted proposal lineage 和单一 logical opportunity，
    未登记或 label 无法成熟的 Agent 不得使 roster READY。
12. 实现第 10.3 节全部十个 Macro 的 PIT role-path/代理篮子和 labeler、所有角色的
    `EvaluationOpportunitySet`，以及 CRO、Alpha、Execution、CIO 的 frozen evaluation
    object 和专属 outcome labeler；机会集生成必须在运行前产出 AVAILABLE set 或带
    generation attempt/source/error evidence 的 UNAVAILABLE audit discriminant，失败时不得
    启动 Agent 或伪造 set ID/hash；空集只允许四个 Superinvestor、CRO、Alpha、Execution
    生成 `NO_EVALUATION_OBJECT` stage skip，其他 Agent 的成功机会集必须非空。标准 Sector
    必须按完整冻结 direction 截面和 exact side
    scoring shortlist 实现第 10.3 节唯一 50/50 MSE-skill 公式、preferred-only 非中心化
    active tilt、SELECTED unit-confidence target、使用冻结 base-rate Brier skill 减
    missed-opportunity regret 的 abstention primary utility、非空 shortlist 的
    security-abstention proper loss、cardinality-adjusted opportunity search、分离
    calibration state、零/空集合语义及 TS/Python 共享实现；relationship opportunity
    generator 必须在 Agent 调用前验证非空、唯一 candidate 和严格正的有限 materiality
    weights，outcome 按同顺序逐项复用冻结权重。Alpha eligibility 必须使用
    `stock_st(trade_date)` 的 PIT 状态；2016 年以前缺少替代历史档案时机会集失败关闭。
13. 实现 label-owner 硬约束，确保 CIO PnL、attribution 或下游采纳结果不能
    更新任何上游 Darwinian 轨道。
14. 将同一可靠度输入合同扩展到 Sector→Superinvestor/Decision 和
    Superinvestor→Decision，确保 `technology`、`real_estate_construction`、
    `agriculture` 等非 Macro 权重具有真实下游消费路径。
15. 实现 KNOT 候选选择、冻结 champion/candidate 同输入运行、固定 PIT replay manifest、
    共同 `RealizedOutcomeObservation` 与双方独立 label、research/production sample-origin
    隔离、paired 统计晋级、原子 promotion、持续 shadow 和 rollback；发布全局唯一
    `KnotRuntimeContractManifest`，让每个 active production variant 的 28 条 evaluation
    track 及其派生的 research pair/promotion/rollback audit 绑定同一
    score/scheduler contract，并让 Sector universe 只保存 score contract 外键。所有失败 pair
    中由目标 Agent 自身导致的 `AGENT_FAILURE` 才持久化
    `raw_research_score/research_comparison_score=-2` 并进入完整 30 个可问责 pair
    双门槛；共同 exogenous exclusion 不计分，CIO control dependency-blocked pair 只消耗
    预注册 slot、记录 failed pairing 且不生成 CIO score；
    promotion 后只从未来 production slot 建空 evaluation/usage track，禁止复制 research label
    或成熟度。
    CIO KNOT pair 必须执行第 10.6 节的两侧依赖子图：共享 pre-CIO root/Alpha 输入，
    side-specific proposal 派生 CRO/Execution bundle，依赖调用只写
    `KNOT_CONTROL_SHADOW` operational audit；空控制对象只生成
    `KnotControlNoEvaluationObjectStageSkipRecord` 并通过显式
    `stage_skip_origin=KNOT_CONTROL_SHADOW` runtime branch 传递，不得生成 outcome audit/label；
    dependency-blocked pair 消耗预注册 slot 但不把 `-2` 归给 CIO，
    CIO 自身 proposal/final failure 才生成单一 CIO failure score。
16. 实现 Sector/Superinvestor 输出级 confidence 与 relationship reliability adapter；
    Sector 只校准语义稳定的 submission 顶层 confidence，不再生成两侧方向 confidence 或按
    least 腿数切换 target；两侧 security-abstention probability 只进入各自 proper loss。
    为 Macro、标准 Sector、relationship 和 Superinvestor 分别实现
    显式 model-visible 白名单 DTO/discriminant；只把最终 usage share 与白名单内容暴露给
    模型，内部 model/data-quality confidence、behavior/version、audit 和
    Darwinian/operational knobs 留在 runtime。
17. 实现九个零参数 `get_sector_research_snapshot()` 角色投影、
    `get_relationship_graph_snapshot()` 和四个 `get_superinvestor_candidate_snapshot()`；
    生成唯一强类型 SW2021 `SectorUniverseManifest`、可重放 `SectorMembershipQueryPlan`、
    exact `SectorDirectionContract` partition、包含 `DIRECTION_PARTITION_PIT` 的三类 tagged
    benchmark universe query plan、
    具有本计划全部固定 entry/公式的闭集 `SECTOR_DIRECTION_METRIC_REGISTRY`、
    exact `SectorSecurityScoringContract/FrozenSectorSecurityScoringShortlist`、
    PIT constituent-flow、PIT/暴露阈值/单 direction 独占的 optional ETF map、全局 overlap precedence 和
    `SectorFlowCoverageContract`；实现冻结候选域全量个股 `moneyflow` 聚合、20 日
    median-turnover 分母和 90% required flow gate，并把 `moneyflow_ind_ths` 限制为
    optional diagnostic；实现 direction 成分股技术卡、ETF corporate-action
    adjustment、family 滞后权重价格/份额/估算申赎确认、`n>=2` 时逐 criterion 的全 eligible pair
    comparison audit、core/coverage-gated/ETF 半票 runtime weighted pair resolver、一次幂等 conflict review、
    严格 Condorcet/reducer、least eligibility 和独立 final-selection 调用；
    对只有一个 eligible direction 的路径实现独立 null comparison card、同 criterion
    `SingleDirectionQualificationContract/Audit`、无 review 的资格解析及 final evidence binding；
    对 single-direction null 使用的 `index_weight` 执行权限、schema、历史 constituent、
    `trade_date/first_seen_at` 和排除 direction 后非空覆盖 preflight；
    将 `RoleEventCoverageSummary` 与 `SectorCatalystCoverageSummary` 分开物化和校验，
    为 catalyst summary 固定非空 source registry/hash、required/healthy/unhealthy 完整分区、
    presence/completeness 派生和非空 coverage evidence，使 macro-event 与 catalyst
    criterion 只能由各自 coverage 决定；将 final runtime
    directive、accepted selection 和 outcome denominator 绑定同一
    shortlist ID/hash 与 scoring contract；实现固定 Sector inference budget/cost audit 和
    对全局 `KnotResearchScoreContract` ID/version/hash 的只读绑定，并在全部 KNOT 配对中使用统一
    `research_comparison_score`；删除 production
    `get_industry_policy_digest` 与任意 ticker 查询依赖，并验证 frozen candidate scope hash。
18. 为 `relationship_mapper` 实现运行前完整
    `FrozenRelationshipPredictionOpportunitySet`、candidate binding、空/非空 graph
    discriminant、逐 candidate outcome、匹配非边 lift、missed-edge regret 和 graph-abstention
    proper loss；opportunity set 必须非空、candidate 唯一且 materiality weight 为有限严格正数，
    outcome metric 按冻结顺序和权重一一对应；未提交 candidate 固定为
    `submitted_direction=null/submitted_model_confidence=0`，空机会集按 required-data
    unavailable 拒绝，空图不能逃避评分。
19. 实现 `get_cro_risk_snapshot()`、`get_alpha_candidate_snapshot()`、
    `get_execution_snapshot()` 和 `get_cio_decision_snapshot()` 的专属 required 分支、
    `DECISION_SNAPSHOT_ALGORITHM_REGISTRY`、ledger/constraint hash 和 paper/real execution
    gate；为 CRO action 与 Execution order assessment 物化 accepted per-item ref/hash，
    使 CIO local resolution 可确定性解析到 frozen item；无 broker quote/OMS 时禁止真实执行。
20. 将 `get_rke_research_context` 迁移到独立 `RKE_SHADOW` capability/state/scorecard；
    production graph、prompt、accepted output、candidate universe 和 Darwinian update
    均不存在引用路径。

### 阶段 G：Prompt

1. 先将第 6.1.1 节工具矩阵、零参数 snapshot、RKE 隔离和候选域规则写入唯一合同源与
   生成器，并生成 KNOT immutable block hash。
2. 按第 12.2 节简化结构重建 bundled default prompt，删除旧通用工具和 source/knob
   内部实现；Zod schema 只通过 provider structured-output channel 注入并固定 hash。
3. 重建私有仓全部 448 份双语 prompt，验证 immutable block 与 bundled/runtime manifest
   一致，同时保留真实 cohort behavior 差异；production 只加载 pinned private variant，
   bundled 仅供 distinct behavior version、正式 writer 全部禁用的 fake/offline fallback。
4. 按新 `execution_behavior_release_id` 中每个 variant 对应的
   `execution_behavior_version` 重建 KNOT champion baseline/track；旧 paired samples
   不继承，受影响 Agent 在 data/tool readiness 前保持 `CONTRACT_MIGRATION_PAUSED`。
5. 验证语言、cohort 差异、private/bundled precedence、完整
   prompt/schema-binding-set hash、
   structured-output enforcement、schema/tool drift、capability 越权、RKE 隔离和 knob 泄漏。
6. 私有仓先提交并推送，得到可由公开仓运行清单解析的 commit/hash；prompt commit、
   runtime manifest 和 KNOT baseline hash 必须原子绑定。

### 阶段 H：验证和 PR

1. 更新公开运行清单，固定私有 prompt commit/hash。
2. 执行第 15 节验证。
3. 提交并推送公开仓变更。
4. 创建或更新两个交叉链接 draft PR。
5. 检查两个 PR 的 CI；若修复产生新提交，按“私有先推送并更新 pin → 公开再推送”的顺序
   重跑相关验证，直到 draft PR 检查通过。

## 15. 测试与验收

### 15.1 合同和角色

- 参数化覆盖 10 个 Macro Agent 的 submission/accepted schema、claims、
  transmission、`claim_refs`、语义一致性、职责边界和工具白名单；DIRECT 必须使用
  `signal.claim_refs`，COMPONENTS 必须逐组件提供 refs，accepted 顶层 refs 必须等于有效
  组件 refs 的确定性去重并集。
- 验证 accepted output 必须携带匹配的 `agent_contract_version`、
  `prompt_behavior_version`、`execution_behavior_version` 和组件权重合同版本。
- 验证 `FACT/EVENT` 与快照完全一致，`RISK_FLAG` 有确定性触发条件；
  不可验证解释必须标为 `INTERPRETATION`，且所有 claim 的
  `evidence_ids` 非空。
- `ClaimSchemaV2` 是唯一生产 schema：参数化验证旧
  `claim_type/evidence_refs/snapshot_hash` 模型字段拒绝，旧 fact 只有经确定性分类后才能
  迁移为 FACT/EVENT，inference/uncertainty 映射规则固定，INTERPRETATION 缺
  `research_rule_refs` 时拒绝，`structured_conclusion={}` 时拒绝；历史旧 claim 只能进入
  `legacy_unverified` 审计，迁移器不得为旧 uncertainty 合成 research rule/evidence。
- 验证七个组件 Agent 只能提交 `mode=COMPONENTS`，其余三个只能提交
  `mode=DIRECT`；组件集合缺失、重复或越界时拒绝；模型提交运行时 lineage
  字段时拒绝。DIRECT accepted 的 `component_weight_contract_version` 必须为 null，
  COMPONENTS 必须为实际 composer 使用的非空版本；mode/version 交叉错配时拒绝。
- 覆盖 10 个 Sector Agent，并单独验证 `technology`、`real_estate_construction`、
  `agriculture` 以及汽车只属于 `consumer`。
- 参数化覆盖 CRO、Alpha、Execution、CIO proposal/final 的 submission、accepted 和
  model-visible discriminated schema：冻结对象必须一一覆盖，proposal/final 不能互相
  反序列化，Decision model view 不泄漏版本/hash/Darwinian 字段；CIO final 省略任一
  CRO/Execution control resolution、越过 hard control 或提高不可执行量时拒绝。
  Decision 图顺序必须严格为
  `Alpha -> CIO proposal -> CRO -> Execution -> CIO final`；proposal 缺少或错误绑定
  `alpha_source`、CRO universe 不是从同一 proposal 派生、Execution 引用旧 CRO/proposal、
  final 直接加入 proposal 外 Alpha 候选、读取未来阶段，或 final 与 proposal 的 pre-CIO
  Macro/Sector/Superinvestor snapshot hash 不同均失败。Alpha prompt/snapshot 出现同轮 CRO
  output、CRO 从 proposal 外扩域、final 重新注入 Alpha DTO 也必须拒绝。
  CRO/Alpha/Execution 的冻结对象集合为空时不得调用模型或生成 accepted output，只能从
  同一 opportunity set/audit 生成唯一 `NoEvaluationObjectStageSkipRecord`；非空集合伪造
  skip、
  skip 的 agent/set/audit/hash 不匹配或把 skip 计作 abstention/fallback/Darwin sample 均拒绝。
- CRO action 与 Execution order assessment 必须分别物化稳定 per-item ref/hash；覆盖
  local ID 重复、payload/hash 篡改、顶层 accepted hash 未覆盖 item、CIO 引用不存在或旧
  item、local ref 无法唯一解析和 accepted final 残留 local ref。model view 只能看到 local
  ID，不得泄漏 persistent ref/hash。
- 参数化验证第 6.1.1 节 28-Agent model-callable tool 矩阵完全一致：零参数 snapshot
  不接受 agent/ticker/as-of/scope；伪造签名/key ID、过期、重复 tool call、已终结或跨 node
  capability，跨 graph/run slot/run 重放、篡改候选域/snapshot bundle hash，以及直接调用 collector/raw endpoint 均由
  bridge 服务端拒绝。验证 tool call 只读取预物化 bundle、不会发起 collector I/O，并覆盖
  两个获准工具各一次成功调用与跨 session replay，不能只依赖 prompt 检查。
  `AgentExecutionStageId` 必须恰好 29 项；非 CIO 的 stage/agent 不相等、CIO 使用
  `cio` 或未知 stage、bundle 与 capability stage 不同均拒绝。
  `AgentId/AgentToolId` 必须由封闭 roster/工具 union 生成，空工具集合、未知字符串或
  角色矩阵外组合不能进入 bundle/capability。
- `get_industry_policy_digest` 和任意 ticker 通用研究工具不得出现在 production manifest；
  九个标准 Sector、relationship、四个 Superinvestor 和四个 Decision 快照必须分别覆盖
  required source branches 与 frozen scope。
- 验证 Macro、Sector、Superinvestor、Decision 的 lineage envelope 贯穿 graph
  state 和持久化；同一 causal key 的独立证据数固定为 1，保留全部角色解释并拒绝跨层
  confidence 取最大、相加或排序。
- 验证 Macro Agent 不能读取其他 Macro LLM 输出。
- 验证旧角色仅可作为 `legacy_unverified` 审计数据；migration manifest 把
  `dollar/yield_curve/volatility` 记为 tombstone、三个目标 Agent 记为 new ID，且禁止
  旧 Agent ID/权重/样本 alias 到新 Agent。
- 波动率字段路由必须唯一：`VIXCLS` 只进入 `us_financial_conditions`，CISS 只进入
  `euro_area_financial_conditions`，中国实现波动只进入 `cro` 风险快照；欧元区未注册
  隐含波动分支或 Execution 再次读取原始波动率均失败。
- Tushare 权限注册表必须把 `major_news/news/npr/monetary_policy` 固定为
  `DISABLED_PERMISSION_DENIED` 且 `runtime_client_enabled=false`；参数化验证 tool
  whitelist、bridge、collector、replay 和 fallback 均无调用路径，权限拒绝不能伪装成
  成功空响应。封闭 registry 必须覆盖 catalog、series map、bridge 和 collector 引用的
  并集；未知 endpoint 拒绝，不能依赖“其余默认”。其他已登记 endpoint 未通过真实
  preflight 时只能为 `PRECHECK_REQUIRED`。
- `get_central_bank_snapshot` 的 required series map 不得包含 `npr/monetary_policy`；
  PBOC 官方政策/操作证据缺失、过期或 PIT 不可证时拒绝，`eco_cal` 不能替代正文或让
  输出退化成“政策不变”。
- 参数化覆盖 `pboc_omo_operations/pboc_lpr/pboc_policy_stance/pboc_credit_money/
  china_money_market_curve` 的官方目录、分页、发布/生效/首次采集时间、append-only
  revision、freshness hard cap 和 PIT replay；目录 schema drift、截断或任一 required
  family 不 READY 时两个中国 snapshot 失败关闭。`pboc_policy_stance` 的 MPC 与执行报告
  必须分别验证 `expected_next_release+15` 与 `first_published+150` 的较早边界；任何套用
  ECB/Fed 90 日上限、用另一分支延寿或由 retrieval 推断 expected release 的实现失败。
- 参数化覆盖 `CHINA_MACRO_SERIES_MAP` 的增长、价格、信用、外需、财政五维官方目录、
  Tushare endpoint、发布时间和 vintage；增长维必须包含 PIT 合法的官方生产/需求/就业
  发布，就业 release 只能由 `china` 作为 PRIMARY，进入 `central_bank` 时必须为
  `CONTEXT_ONLY`。信用 release 只能由 `china` 产生数量方向，
  `central_bank` 只能在独立 PBOC/融资价格证据下定向，并共享 causal key。
- 参数化覆盖美国实体四组件和金融条件四组件的 ALFRED/Fed/NY Fed/Tushare/FX 映射、
  具体 series ID、日历、PIT、freshness 和 required failure；VIX/Fed/曲线/美元不得拆票，
  实体摘要不能给金融组件贡献 `b_j`。
- 参数化覆盖商品四组件真实合约与 expiry、无期限结构语义，以及 positioning 的全市场、
  行业、ETF universe、share/adjusted-price required 分支；缺少 PIT `fund_adj`、份额单位
  无法归一化或 corporate-action hash 不闭合时拒绝，龙虎榜/持仓 optional 数据不能补缺。
- 三个 DIRECT Macro 必须各有唯一 `DirectAgentDataQualityContract`；验证 required 失败关闭、
  optional 缺失确定性降质、accepted confidence 等于模型 confidence 与质量乘积，且 usage
  share/forecast loss 不得误用未经降质的模型值。COMPONENTS 的 top-level 模型/质量诊断与
  effective composer 分别留痕，不能再次相乘。
- freshness fixture 必须分别跨中国、美国、TARGET2 和各交易所节假日，验证每个 series
  使用自己的 release/trading calendar；任何把欧盟工作日全局套到美国或中国的实现失败。
- production snapshot 测试必须拒绝只有任意非空 evidence 的本地 JSON；只有逐项满足
  required component/source-map/schema/PIT/freshness 的快照可 READY，fake loader 只能在显式
  fake mode 使用。
- RKE shadow migration inventory 必须覆盖 `agent_research_context/report_intelligence/
  macro_expansion/phase_minus1` 的旧 Macro ID；旧 artifact 保持 legacy，新 runtime/RKE
  manifest 不得 alias 身份或让 report-derived signal 进入生产。production prompt、tool
  capability、graph state、accepted output、候选域、Decision input 和 Darwinian update
  中出现 `get_rke_research_context` 或 RKE-derived evidence 时测试必须失败。
- production state、Layer-2/3/4 factories、daily-cycle、CLI/backtest、scorecard 和 bridge
  中不存在 `layer1_consensus` 读写；只有显式 legacy adapter 可读取历史字段。
- `runtime_agent_manifest_v3`、28-Agent domain catalog、29-stage graph 和 RKE readiness
  artifact 版本一致；v1/v2 25-Agent artifacts 保持不可变、只读且不能被 latest 查询混入。

### 15.2 eco_cal

- 单次 100 行限制和分片完整性。
- 完全重复行去重。
- 同 batch 的 actual/previous/forecast 冲突拒绝，跨 batch 的唯一值变化形成有序
  revision；批内冲突不得伪装成跨批修订。
- `RESOLVED` 必须列出全部原冲突字段和非空官方 resolution evidence；只解决
  部分字段时仍为 `CONFLICT`，发布后 forecast 不得反向解决。
- 国家、货币、事件别名、参考期、单位和时区解析。
- 发布前 actual 泄漏。
- 发布后但 `retrieved_at > as_of` 的泄漏。
- forecast 必须在发布前可见。
- logical event ID 在改期时保持稳定，revision ID、有效区间和 supersedes 链
  正确更新。
- reference period 为空的同名周/月重复事件使用不同 occurrence key；官方改期在唯一
  match 时保持 ID，歧义时新建 occurrence 并审计。原始 date/time 在时区未验证时仍保留。
- 原始 K/B/T/%/空值、规范化单位和 actual/previous/forecast 独立 parse status。
- 重复轮询只追加 retrieval observation；revision 行不可变，`last_seen_at` 和
  `valid_to` 可从 append-only 记录重建。
- `time_status=UNVERIFIED` 时禁止 surprise、risk timing 和 execution timing。
- Macro scope 的 PRIMARY signal owner 唯一性、source evidence 独立性和
  所有消费者复用同一 `evidence_bundle_id/causal_dedupe_key`。
- Sector-specific 事件可在自己的 Sector thesis 中作为 PRIMARY，但不能形成
  重复 Macro 方向来源或在下游叠加共同因果置信度。
- `CONTEXT_ONLY` 不能单独支撑方向。
- Sector 不得重复 Macro 方向。
- CRO/Alpha/Execution 的用途限制。
- `get_role_event_snapshot()` 不接受身份参数，运行时绑定调用者；伪造身份、范围
  或用途失败，拒绝角色的工具表中不存在该工具。
- `AgentEventProjection` 必须携带净化后的 normalized event、reference period、
  release stage、scheduled/released time、phase、actual/previous/forecast/surprise、单位、
  time/conflict/reconciliation 状态和 evidence；opaque ID-only projection、未满足发布前
  forecast/时间/PIT/冲突条件却生成 surprise、或数值与权威 event revision 不一致时拒绝。
- 每次标准 Sector 调用前必须先物化唯一 `RoleEventSnapshot`，并把同一
  snapshot ID/hash、coverage 和 projections 嵌入 `get_sector_research_snapshot()`。模型未调用、调用一次或
  optional event tool 调用失败不得改变 criterion coverage、pair resolver 或最终 directive；
  tool 只能返回已物化 bundle，不能触发重采集。`COVERAGE_CONFIRMED_NO_MATERIAL_EVENT`
  仅在 required routes 全部健康、query complete、coverage evidence 非空且 material event
  revision IDs 为空时成立；`AVAILABLE_MATERIAL_EVENTS` 还要求同样的完整覆盖且 revision
  IDs 与 projection 集合完全一致。构造“观察到 material event 但另一个 required route
  stale/unavailable”的 fixture，必须得到 `event_presence_state=MATERIAL_EVENTS_PRESENT`、
  `coverage_completeness=INCOMPLETE` 和 `coverage_state=SOURCE_UNAVAILABLE`，保留部分
  revision IDs 但 Sector 固定
  `NO_VOTE`，CRO/Alpha/Execution 节点拒绝。required/healthy/unhealthy route 集合缺失、
  重复、非分区或与 evidence 不一致也必须失败。
- 禁止 `market_breadth`、`institutional_flow`、CIO 和
  Superinvestor 直接读取 `eco_cal` 或 role-event 投影。

### 15.3 Geopolitical

- `GEOPOLITICAL_INITIAL_SOURCE_MANIFEST` 必须包含第 6.8 节全部初始 source registration、
  强类型 adapter contract、actor/region/global event coverage route 和 approved-domain 行；逐项验证 exact
  URL/API、cursor、query、publisher/upstream、actor/region/global/event coverage、时区、发布时间、
  许可、poll/truncation 与 no-event capability，并重算 adapter/route hash。actor/jurisdiction、
  region、approved domain 不得为空或使用“相关”占位符；prose-only 默认值、opaque hash、
  registration 外键悬空或 hash 不匹配必须失败。
- 初始 production source closure 必须恰为第 6.8 节列出的 14 个 DIRECT source；OCHA 只能
  额外以 `OPTIONAL_CONTEXT/PREFLIGHT_REQUIRED` 存在。任意额外 ACTIVE required/discovery
  source、初始 Tushare registration 或未发布新 coverage contract 就追加 source ID 均失败。
- 每个 watchlist actor、watchlist region 与 active event type 的 pair 必须恰有一条结构化
  applicability/route 记录，event-family 全局源必须有显式 GLOBAL route；applicable pair
  缺 ACTIVE continuous route，或 route 中 required adapter 未显式覆盖该 actor/region/global
  scope 时对应 coverage 失败关闭。没有 actor 自身官方 adapter 不能单独触发全局
  失败；若已注册的 GDELT、UN/发行司法辖区官方目录等替代 route 完整、健康且通过 preflight，
  该 pair 可以 READY。`NOT_APPLICABLE` 必须固定
  `NO_REGISTERED_MATERIAL_LINK`、空 required/no-event source 数组和
  `route_status=NOT_APPLICABLE`；APPLICABLE 必须使用非空 source tuple 和非
  `NO_REGISTERED_MATERIAL_LINK` reason。任一交叉错配或靠省略 pair 表达均拒绝。
- required official/discovery source family 的 adapter preflight、权限、schema drift、
  查询截断、轮询成功率和 30 日 publication-to-capture p50/p95/p99 审计。
- 每次 poll observation append-only；coverage 由成功/失败、schema hash、分页和截断
  记录重建，失败轮询不能原地覆盖或从 SLO 分母删除。
- GDELT 15 分钟 discovery 与官方 API/RSS/HTML 各自的 poll interval/max capture age；
  provider 未承诺的 SLA 不得伪造为数据属性。Tushare `major_news/news` 必须保持
  permission-denied 禁用，测试发现任何请求即失败。
- official、multisource、unconfirmed、conflict 的状态转换；同源转载、内容镜像和
  同一官方稿不能凑成两源确认。
- `OFFICIAL_CONFIRMED` 必须有 route-matched ACTIVE official evidence，
  `MULTISOURCE_CONFIRMED` 必须有至少两个独立 approved source；
  `primary_source_tier` 必须从 evidence 派生。`time_status=VERIFIED` 却缺
  `published_at`/发布时间证据，或任一 verification/source-tier 字段由模型自报时失败。
- 任一 required route/source/scope query stale/unavailable/schema drift 时对应 event-type
  coverage 拒绝；同一 source 的另一条成功 query 不得补位。制裁/出口、贸易限制、
  航运、武装冲突和外交状态必须逐类型生成 coverage。MARAD/UKMTO/GDELT 航运查询、
  每个 applicable actor/region/global route 所列的 GDELT、UN/发行司法辖区官方目录或已验证 actor
  官方目录缺一时，不得用其他 event family 的健康状态补位；未列为 required 的 actor 官方源
  缺失不得反过来推翻一条已经闭合的替代 route。
- 参数化覆盖一个 GDELT/官方 source 同时服务多个 actor/region query 的场景：每条 query
  必须具有独立 `coverage_query_key`、poll observation 和 health；任一 query 截断/失败时
  `required_query_keys` 分区必须显示该失败，不能由 source-level `last_successful_poll_at`
  把 event-type coverage 标为完整。
- 参数化覆盖 actor、region、GLOBAL 三种 route subject：最低六个 region 与每个 active
  event type 都必须有 applicable/not-applicable 记录，红海/霍尔木兹等航运 REGION route
  缺失时 roster 不得 READY。`no_event_evidence_query_keys` 必须逐 route/source query
  闭合，只有 source ID 健康但对应 region query 缺失时不得声明无事件。
- 只有每个 `active_event_types` 成员都为 `COVERAGE_CONFIRMED_NO_EVENT` 时空事件集合才可为
  `COVERAGE_CONFIRMED_NO_MATERIAL_EVENT`；任一 `COVERAGE_UNAVAILABLE` 必须得到
  `COVERAGE_INCOMPLETE/REJECTED`。`OTHER_REGISTERED` 不在初始 active set，缺少专属
  source/no-event contract 时不能加入或声明无事件。
- 每个 applicable actor/region/global route 必须有非空 `no_event_evidence_source_ids`，且为
  required sources 子集、全部 adapter 的 `no_event_claim_capable=true`；event-type coverage
  的 `no_event_evidence_query_keys` 必须精确等于 route/source query 并集。用仅可
  discovery/confirm、不能声明无事件的源生成
  `COVERAGE_CONFIRMED_NO_EVENT`，或遗漏失败的 capable source，均必须拒绝。
- `source_backend=TUSHARE` 必须有指向唯一 registry ACTIVE endpoint 的
  `tushare_endpoint_id`，DIRECT 必须为 null；两处状态不一致、未激活 event type 或
  registration/active-set 不匹配时拒绝。
- 两源确认参数化拒绝同 publisher organization、同 upstream origin、canonical URL/
  reference 相同和内容镜像；Geopolitical registry 不得复制 Tushare permission 状态。
- ReliefWeb 未取得预批准 appname 或许可/30 日 preflight 未完成时必须保持
  `OPTIONAL_CONTEXT/PREFLIGHT_REQUIRED` 且无生产请求；启用后也不能单独确认事件或
  声明无事件，公开 fixture 不得包含伙伴正文。
- published/effective/first-seen/retrieved time 分离，未验证时区不能支撑 PIT；本地后来
  下载的新闻/GDELT archive 不得回填历史及时性。
- append-only announcement/effective/escalation/de-escalation/resolution revision，
  official/provisional ID alias、headline collision、causal dedupe、事件重叠 priority 和
  future-leakage。
- `UNCONFIRMED/CONFLICT` 只能生成观察型 RISK_FLAG，不能单独支持 direction；
  `eco_cal` 不得替代事件状态，模型不得虚构价格影响百分比。
- raw news/license cache 私有边界和公开脱敏 fixture/poll coverage audit。

### 15.4 欧盟和 World Bank

- 对第 6.4 节六个 Eurostat required series branch/dimensions 和九个 ECB series key
  逐一执行官方非空 metadata/data smoke；特别验证 `prc_hicp_minr/coicop18=TOTAL`、
  `une_rt_m/age=TOTAL`、`sts_trtu_m/indic_bt=VOL_SLS`、
  `ext_st_eu27_2020sitc/partner=EXT_EU27_2020` 的 EXP/IMP 双 flow、2Y/10Y AAA
  曲线、BSI/MIR、EXR/CISS，旧 HICP key 或无数据 `Y15-74` 不得静默 fallback。
  series title/单位/频率/structure hash 漂移即失败。
- `LOCAL_CAPTURE` 必须 `retrieved_at<=as_of`；之后下载的 `OFFICIAL_VINTAGE`
  必须有发布时间目录证据，不能仅凭 observation date 回填历史。
- Eurostat 最新版和有限 vintage 的边界。
- 参数化覆盖 `geo_composition_at_vintage`：changing-composition EU15/EU25/EU27_2007/
  EU28 aggregate 不得拼接到 `EU27_2020`、计算正式增长或进入 label；只有明确匹配固定
  composition 的 row 或经独立成员国重建合同验收的 series 才可用。member sum 没有
  chain-link/季调/reconciliation 合同时必须拒绝。
- ECB `includeHistory`。
- EU27 实体四组件/六 series-branch required matrix、欧元区金融五维 required matrix、固定
  freshness 与覆盖门槛。
- expected release、官方改期、grace、hard cap、日/月/季频锚点；revision 或
  retrieval 不得刷新 `first_released_at` 并延长旧 reference period 的寿命。
- World Bank 必须为 `CONTEXT_ONLY`、`required=false`，不能让阶段
  `READY`。
- 官方值与 `eco_cal` reconciliation 冲突。
- `fina_mainbz(type=D)` 权限、分页、地区别名、无法分类、负/缺失收入和报告期对应
  实际公告时间；`disclosure_date` current row 不得证明 historical PIT，只有当时已捕获
  的 actual/modify date 或交易所官方公告 metadata 可证明 `released_at`。测试必须捕获
  现有 `type=P` 产品口径、计划日期回填和 first-seen 之前泄漏。
- EU27 历史成员关系、暴露篮子成分 valid interval、再平衡、基准、复权、权重上限和
  今日成分回填历史的未来数据泄漏。
- relationship factual edge 的证据验收、结构化 trigger、PIT 匹配非边、固定随机种子、
  残差共振/共回撤 lift；`RelationshipGraphSubmission`、`AcceptedRelationshipGraph`、
  `ModelVisibleAcceptedRelationshipGraph` 三层 schema 必须区分 factual/predictive edge，
  factual edge 不接受模型 confidence，predictive edge 固定 20 日 horizon 且 refs 非空；
  每条 predictive edge 必须绑定运行前冻结且唯一的 `edge_candidate_id`，域外、重复或
  source/target/type 不匹配均拒绝。outcome 必须对完整 opportunity set 逐项生成 metric，
  未提交 candidate 仍在分母；验证 materiality-weighted 50% multiclass Brier skill、50%
  matched-non-edge path lift、方向错配和 missed-edge regret。
  submission 的 `model_confidence` 必须用于该边 Darwinian outcome，accepted 层同时保存
  raw/model 与 PIT calibration state 生成的 `calibrated_confidence`，model-visible 层只能
  暴露 calibrated 值。缺 state、使用未来 state、下游误用 raw 值、或 generic serializer
  泄漏 raw/state 字段均拒绝；
  空 predictive graph 的 directional confidence 为 0 但 factual edges 仍传递，并必须提交
  graph abstention probability；验证 cardinality-adjusted opportunity search、冻结 base-rate
  Brier skill、正确空图奖励和遗漏 material edge 至少 1 的 regret。永久空图、只对 submitted
  edge 取平均、outcome 后补边/删边/重选 matched non-edge 均不得逃避负分。RKE 边不得进入
  生产 label。

### 15.5 Sector、Superinvestor 与 Decision 数据

- 九个标准 Sector required 基座覆盖 PIT 行业成员、行情/复权、`daily_basic`、停复牌、
  涨跌停、财务和行业资金；ETF/基金仅按第 6.1.2 节作 optional supplemental confirmation，缺少不得使
  required readiness 失败，也不得被模型解释为无资金。逐角色验证 overlay，`agriculture`
  同时覆盖粮食和养殖投入链，`energy` 同时覆盖煤油电与光伏/风电/电池，optional 官方源
  缺失不能被模型补写。
- `SECTOR_UNIVERSE_REGISTRY` 必须恰有九行 SW2021 exact-code 合同，名称语义、排除范围、
  overlap precedence、member valid interval、PIT constituent-flow contract 和 ETF map 与第 6.1.2
  节一致；每条 Sector contract 引用的 query-plan/flow-coverage ID、version、hash 必须解析到
  唯一强类型对象并可从内容重算，九条 contract 必须共享 manifest 中唯一的全局 precedence
  和 coverage 公式。必须额外验证 `technology` 从电子 L1 剔除半导体 L2，汽车只进入 `consumer`，
  光伏/风电/电池进入 `energy` 且不再进入 `industrials`，基础化工/钢铁/有色/环保进入
  `industrials`，房地产/建材/建筑装饰只进入
  `real_estate_construction`。code 为空/漂移、字符串模糊匹配、一只证券进入多个标准 Sector、
  个股 flow coverage 未达门槛却计 required coverage 均失败；90% 财务覆盖、snapshot 和 outcome 使用同一 universe/hash，
  缺财务证券不能从分母删除。
- `SectorDirectionContract` 必须在每个 Sector 内无重叠且完整覆盖 exact universe，所有
  direction ID、codes/exclusions、direction return/parent Sector/single-direction null
  benchmark、候选资格和 hash 都可重算；每个 benchmark 必须解析到 kind 匹配的 tagged
  query plan。direction return 必须绑定 `DIRECTION_PARTITION_PIT`、相同 direction ID/
  partition definition hash 和所属 membership plan；parent 必须绑定完整 Sector
  `SW2021_MEMBERSHIP` 且 `bound_direction_id=null`。用完整 parent membership 直接计算
  多方向 direction return、partition codes/hash 漂移、单方向 null 与自身/parent 成分相同、
  多方向误填 single-direction null、
  单方向漏填 null、用 SW Sector membership plan 伪装宽基/peer null、注册指数或 peer
  basket 使用 `known_at>as_of`/今日成分回填历史、snapshot trailing close 与 outcome T+1
  entry 端点混用均失败；`index_weight` 权限/schema/历史覆盖未通过时相应单方向 Sector
  不得 READY。`energy` 必须包含煤炭、石油石化、电力、光伏、风电、电池/储能六个
  独立方向；`agriculture` 必须包含种植/种业、养殖/水产、饲料/动保、林业/加工/服务四个
  exact-L2 分区，并逐字段匹配
  `801016.SI`、`801017.SI+801015.SI`、`801014.SI+801018.SI`、
  `801011.SI+801012.SI+801019.SI` 四组 literal code，且无 `agriculture_total`
  fallback。submission
  必须恰有一个 registered preferred，并严格服从 `LeastPreferredEligibilityAudit`：
  `REQUIRED` 时必须提交唯一 Condorcet loser，`NOT_QUALIFIED/NOT_APPLICABLE` 时必须使用
  匹配 reason 的 `NO_QUALIFIED_AVOID_DIRECTION`。preferred 不成立时才允许
  `NO_QUALIFIED_DIRECTION`。REQUIRED audit 必须以非空 qualifying refs 覆盖 loser 的每条
  败边，其他状态 refs 必须为空。多个 preferred/least、模型用 confidence 省略 required least、
  完整方向排名表、总体
  `sector_score`、自造主题、方向相同、跨方向 picks 均拒绝。long picks 只能属于 preferred，
  SHORT/AVOID picks 只能属于 least-preferred，且必须属于运行前冻结并传入 final directive
  的 exact scoring shortlist；来自 broad candidate domain 但不在 shortlist 的 ticker 也必须
  拒绝。每侧超过五只、整份 submission 重复 ticker、conviction 非正/大于 1 或同侧和大于
  1 均拒绝。方向已选但合法 shortlist 为空时保留方向并使用空 picks 状态，不能错误升级为
  整份 abstain；非空 shortlist 允许 `NO_QUALIFIED_SECURITY`，但 outcome 必须进入
  security-abstention proper-loss/regret 分支，并要求该 side 独立提交 `[0,1]`
  abstention forecast probability。`PICKS_PRESENT`、`NOT_APPLICABLE`、合法空 shortlist
  以及整份 `NO_QUALIFIED_DIRECTION` 的对应字段必须为 `null`；非空 shortlist 弃选却缺值、
  两侧错位、复用顶层 confidence 或把该值暴露到 model-visible DTO 均拒绝。数据失败不得
  伪装为空 shortlist。runtime
  directive、accepted output 和 outcome 必须引用同一 shortlist ID/hash 与 scoring contract，
  只比较 ticker 数组、运行后重建或 hash 不闭合均拒绝。`AVOID` 不得进入 execution order。
- Sector output schema 参数化验证非空结构化 drivers、risks、claims、结论级 claim refs、
  claim evidence、long picks、SHORT/AVOID picks 和 Macro attribution。每个 driver/risk/pick
  引用不存在或空证据 claim、pick 缺 thesis、十个 Macro `SUBMISSION_SUMMARY` 缺失/重复、
  preferred/least direction-local ref 或 pick-local ref 无法解析时拒绝；模型回显 usage share、
  target hash 或 Darwin weight 同样拒绝。
- `SectorDirectionComparisonCard` fixture 对每个 eligible direction 使用同一 PIT universe/hash，
  验证 5/20/60 日篮子相对收益、MA20/MA60 上方比例、新高新低、成交扩张、实现波动、回撤、
  自身历史/同 Sector 截面分位和 TS/Python 数值一致；`SECTOR_DIRECTION_METRIC_REGISTRY`
  必须逐行生成本计划固定的 26 个 metric ID、闭合 formula/version/hash、单位、lookback、
  benchmark、权重、minimum observations/coverage 和 percentile method；TS/Python 必须从
  同一 registry 生成 dispatch，禁止自由 formula string/parameter map。逐公式 fixture 覆盖
  TTM 同比/现金流率/earnings yield/book-to-price、相对总收益、MA breadth、新高新低、
  成交扩张、实现波动、回撤和全部 ETF family 指标。成分股与 ETF 的 20 日成交扩张都必须
  使用“当前日 + 前 20 日”共 21 个有效行情日；只有 20 日时必须
  `INSUFFICIENT_HISTORY`。未知 metric/unit、错误 lookback、核心 coverage
  低于 90%、required metric 缺失/重复/额外、AVAILABLE 缺 value/evidence、unavailable
  非空 value、252 日历史分位使用未来观测、单方向截面分位不是
  `NOT_APPLICABLE_SINGLE_DIRECTION`、今日成分、后见复权、停牌伪收益、未来 ETF/NAV/share
  行或模型自行计算技术指标均失败。
- direction ETF map 覆盖零/一/多 ETF、entry ID/version/content hash、valid interval、上市/
  退市、少于 60 日、重复映射和 mapping evidence；同一 ETF 的重叠跨 direction 映射必须
  失败。`TRACKED_INDEX_EXACT` 必须没有 holdings 字段，并有可 PIT 重放的 tracked index
  code/contract/hash 和与 direction partition 精确一致的 match hash；名称相似、当前说明页
  或 hash 不匹配必须失败。`HOLDINGS_EXPOSURE_VERIFIED` 必须
  使用 `as_of` 已公开/生效披露、至少 90% holdings coverage、80% direction exposure、
  最长 120 日账龄和 30 日 mapping refresh。
  多 ETF family 必须使用 `as_of` 前 20 日 median amount 滞后权重；验证
  `fund_daily+fund_adj` 的 PIT 复权及 5/20/60 日价格趋势、成交扩张、1/5/20 日份额变化、
  NAV/close basis、premium/discount 和
  `ESTIMATED_CREATION_REDEMPTION` 标记，以及拆并份、份额单位变化、基金合并/代码迁移的
  corporate-action adjustment。缺失/未来/后见 `fund_adj` 时 price confirmation 必须
  unavailable，不能使用未复权 close；无法归一化时 share-flow 指标必须 unavailable；不得把份额
  变化估算称为确认净流入，也不得由模型挑选表现最佳 ETF。
- ETF confirmation 缺失只产生 `NO_REGISTERED_ETF/INSUFFICIENT_HISTORY/SOURCE_UNAVAILABLE`，
  不改变 Sector readiness、不产生负票，也不冒充资金流出；任一 pair 的一侧 ETF
  不可比时对应 ETF criterion 必须 `INCOMPARABLE` 且 resolver 计零票。两侧均可比时每项 ETF 只计
  `0.5`，验证其可在 base tie/边缘时有限确认或反证，但 winner 少于两个 base support 时不能
  单独建边。共同成分股技术基座缺失则 direction `REJECTED`，ETF 不得补位。
- `SectorDirectionResearchSubmission` 必须按 eligible direction 数使用严格 discriminant：
  `n>=2` 只能为 `PAIRWISE`，并恰有 `n*(n-1)/2` 个无序 pair，覆盖缺 pair、
  重复/反向重复、未知 direction、无证据 verdict、
  模型提交总体 winner/decisive list、空/悬空 comparison claims 和 criterion 越权。每个 pair
  必须恰好包含四个 core、两个 coverage-gated 与两个 ETF criterion result；core 必须
  `COMPARABLE`。`MACRO_EVENT_FIT` 的三态只来自 `RoleEventCoverageSummary`；
  `CATALYSTS` 的三态只来自两侧 `SectorCatalystCoverageSummary`。分别覆盖 material、
  健康无 material 和 source unavailable 的 `COMPARABLE/NEUTRAL/NO_VOTE` 语义；财经日历
  无事件不得抹掉官方政策/产业/公司催化，catalyst source 不可用也不得改变 macro-event
  coverage。两类 coverage 被混用、任一 evidence/claim nullability 不一致或模型覆盖 runtime
  expected state 时拒绝。catalyst required source 为空、registry/hash 不匹配、
  healthy/unhealthy 未完整分区、query 截断却标 COMPLETE、部分 catalyst 加 source failure
  却标 AVAILABLE、无 material refs 却标 PRESENT 或 coverage evidence 为空时也必须拒绝。
  ETF 不可比时不得省略且必须双字段 `INCOMPARABLE`、两侧 ETF 可比时
  不得伪装不可比。验证 runtime 的 base criterion 各 1 票、可比 ETF 各 0.5 票：
  winner 必须至少两个 base support 且 weighted margin 至少 1，否则
  `NO_CLEAR_WINNER`；覆盖 unavailable 与 ETF unavailable 均为零票，数组顺序和 cohort
  不得改变解析结果。runtime decisive criteria 必须恰为支持胜方且实际计票的 results，
  least qualification 必须仍含非 ETF qualifying evidence。core criterion 引用 ETF evidence、
  ETF criterion 引用未注册 ETF block、coverage unavailable 伪造中性/负票、ETF 单独建边
  均拒绝。comparison contract 的 minimum base support/weighted margin、
  edge/winner/loser/Copeland/conflict-set/
  review-scope/unresolved literal 与 content hash 任一漂移必须失败。验证唯一严格
  Condorcet winner/loser、无边、并列、三节点循环、强连通/no-clear-winner/Copeland 极值
  冲突集合、确定性 review ID、相同 bundle、只替换冲突内 pair、重复 review 幂等、第二轮
  拒绝，以及一次复核后仍不唯一的对应 abstain。comparison/review schema 必须拒绝
  `final_selection`；runtime audit/directive 生成后才允许独立
  `SectorFinalSelectionSubmission`。参数化拒绝 directive 中 selection status、preferred/
  least ID、reason 与两侧 allowed-security arrays 的非法组合。final preferred/least 与 directive/reducer 或 least
  eligibility 不一致、final claim 未引用 directive 的 required evidence、ETF 参与最终 edge
  却未纳入 decisive evidence、或 directive 只含 ETF evidence 而没有非 ETF qualifying
  evidence 时拒绝；final 调用重新提交 pair、
  数组顺序、direction ID、Copeland
  分数和模型总分不能破同分。final-selection 必须复用 stage 开始时同一组 model-visible
  Macro input/source-layer snapshot hash 以生成 attribution；丢失任一 Macro、usage share
  漂移、重新物化输入或把内部 pair/audit 暴露给 final prompt 均失败。
  `n=1` 只能为 `SINGLE_DIRECTION_QUALIFICATION`，验证空 pair matrix、恰好一个
  `SingleDirectionQualificationSubmission`、非重合宽基/peer null card、相同八 criterion
  coverage/nullability 和同一 base/ETF 半票 resolver；只有方向达到 base support 至少 2 且
  weighted margin 至少 1 时 audit 才为 `QUALIFIED`，否则 final directive 必须为
  `NO_QUALIFIED_DIRECTION`。该分支禁止 conflict review，single audit ID/hash 与
  PAIRWISE audit 字段必须互斥，并固定 `conflict_type=NONE`、空 conflict set/null review
  binding、canonical empty initial/final matrix hash 和匹配 qualification 状态的
  `SINGLE_DIRECTION_QUALIFIED/SINGLE_DIRECTION_NOT_QUALIFIED`；final required evidence
  只能来自 qualification audit，
  且合格/不合格两种状态都要求非空 non-ETF evidence，不能用 `NO_VOTE` 或 ETF-only 填充；
  无论 qualification 是否通过，least 都强制
  `NOT_APPLICABLE/SINGLE_ELIGIBLE_DIRECTION`；不合格时不得退化为
  `NOT_QUALIFIED/PREFERRED_NOT_QUALIFIED`，final evidence 也不得引用不存在的 pair
  matrix。`n=0` 必须 stage reject，不能
  accepted abstain。完整 initial/review
  matrix、eligibility 和 reducer trace 只进 audit，
  production `SectorInferenceCostAudit` 必须固定 null KNOT pair/side；KNOT
  research/post-promotion audit 必须固定非空 pair/side。两类 origin 交叉、production
  accepted selection 引用 KNOT cost audit 或 `KnotResearchScoreRecord` 引用 production cost
  audit 均失败。
  final claims 必须与 decisive evidence lineage 相交且不得冲突，正式下游不能展开成多张票。
- `index_member_all` fixture 必须分别覆盖 `is_new=Y/N`、`in_date/out_date`、换行业、退市和
  同行重复行，并从 `SectorMembershipQueryPlan` 内容重算 hash；只采默认最新成员、用今日成员
  回填历史、只存 opaque hash 或漏掉已剔除成员时失败。
- Sector flow fixture 覆盖完整/缺失个股资金行、重复证券、非 universe 行、零 turnover、
  `net_mf_amount` 单位归一化和 PIT 日期；买卖分项相减重建净额必须拒绝。按冻结候选域
  前 20 日 median turnover
  计算 `T_obs/T`，低于 90% 时 required 行业资金分支拒绝，达到门槛时按
  `sum(signed_net_flow_i)/T_obs` 合成 flow intensity，并验证缺失成员保留在分母及
  TypeScript/Python 数值一致。`moneyflow_ind_ths` 行进入正式 Sector 值、readiness 或
  缺失补齐时测试必须失败。
  ETF 缺失只移除 optional supplemental vote，不能改变 Sector readiness 或生成“无资金”结论。
- 财务六表/指标/主营、预告快报、基金持仓、股东和研究报告参数化验证公告时间：
  `f_ann_date/ann_date/actual_date/first_seen_at<=as_of`；用 `end_date`、今日公告日期、
  后见复权因子或今日行业成员回填历史必须失败。
- `research_report` 只允许进入 `RKE_SHADOW` 私有 collector；任何 production Sector/
  Superinvestor snapshot、公开 artifact、候选入域、accepted evidence 或 Darwinian 更新引用
  均失败。其权限或 release-time preflight 不影响 production required 基座。
- Superinvestor 只能查询 frozen Layer-2 accepted candidates；空域必须在调用模型前形成
  `NoEvaluationObjectStageSkipRecord`，跨域 ticker、直接事件/RKE/政策工具和四哲学间不同
  底层 snapshot 均失败。参数化验证四个
  `SuperinvestorAgentSubmission` 的 `SELECTED/NO_QUALIFIED_CANDIDATES` 分支、1–10 只唯一 ticker、
  conviction 正值且总和不超过 1、非空 drivers/risks/claims、十条 Macro summary
  attribution、accepted local-ref 解析及独立
  `ModelVisibleAcceptedSuperinvestorSelection`；`NO_QUALIFIED_CANDIDATES` 只接受非空冻结
  候选域，空域调用模型、生成 submission/accepted output 或进入 label 均失败；
  raw/accepted attribution、model confidence、behavior/provenance 字段进入 model view 均失败。
- CRO fixture 覆盖持仓/现金/硬约束、中国实现波动、PIT covariance、流动性和停牌/涨跌停；
  缺一 required 分支即拒绝，硬约束不受权重缩放；逐项验证 20/60 日波动、60 日 covariance、
  40 共同观测、20% diagonal shrink、停牌零收益 flag、pair unavailable 和稳定排序；
  CRO proposal ID/hash 不匹配或 candidate universe 不是从 proposal 完整目标组合派生时失败。
- Alpha fixture 验证 frozen novel universe 先于 outcome，CIO 未采纳仍保留评价；模型添加
  域外证券或后来催化失败；验证 60 日上市、18/20 行情、逐日 `stock_st`/停牌、20 分位
  流动性、200 上限和 `ts_code` tie-break，并验证 `type/type_name` 对 ST/退市整理的覆盖；
  未覆盖退市整理且没有交易所 adapter 时必须失败。当前名称或今日 `stock_basic` 状态回填
  历史必须失败；2016 年以前没有预注册风险警示档案时必须生成
  `OPPORTUNITY_SET_UNAVAILABLE`，不能默认非 ST。
- Execution fixture 区分 paper 与 real：日线数据只允许确定性 paper fill/cost；没有已验证
  broker quote/OMS 时 real 模式拒绝，LLM fill 或后续收益进入 execution label 均失败；覆盖
  T+1 VWAP、涨跌停/停牌 blocked、10% volume cap、partial fill、impact 公式、effective-dated
  fee schedule、零成交量和 TS/Python 字节一致性。frozen order intents 必须由同一 proposal
  确定性应用 CRO action 后生成；VETO/未解除 REQUIRE_REVIEW 重新出现、CAP/REDUCE 未裁剪、
  proposal/CRO source hash 错配或 raw proposal intent 绕过控制时失败。
- CIO proposal/final 分别冻结持仓、现金、约束、前次目标和 accepted upstream hash；两阶段
  必须复用同一 pre-CIO source-layer snapshot，final 只能在 proposal 域内解析控制和重做
  attribution。热更新输入、直接新闻/原始市场工具或缺 ledger version 均失败；CRO covariance
  与 Execution cost/fee hash 不一致时拒绝。

### 15.6 市场广度

- 无幸存者偏差股票池。
- 停复牌、新股、退市、复权和缺失值。
- 90% 覆盖门槛。
- 252 日滚动 60/40 breadth 阈值、20 日方向条件和 80/20 集中度阈值。
- 未来数据泄漏。

### 15.7 组件、直接消费与 Darwinian

- 组件确定性合成、相反组件的 confidence penalty、零组件可靠度拒绝和
  `persistence_horizon` 并列选择；所有 Macro 的
  `evaluation_horizon_trading_days` 固定为 5，组件不形成独立下游输入。
- 不存在六因子、`G/R/W/S`、Macro stance 或 `±0.3` 阈值的运行路径和 schema。
- `aggregate_l1` 被不生成语义输出的 `macro_input_gate` 取代；该门只校验完整性、
  PIT 权重和使用比例，不写入 consensus、score 或 stance。
- 十个 accepted outputs 使用相同 `graph_run_id/cohort_id/language/as_of` 直接传递，各自保留并
  校验独立的 `source_agent_run_id`；缺少任一角色时拒绝正式下游 Macro 输入。
- `effective_reliability=confidence*darwin_weight*operational_reliability`，十个
  `usage_share` 精确和为 1；`sum(a_i)=0` 时拒绝，不能回退等权。每个 production run slot
  的 accepted payload 都必须先生成 namespace-safe `AcceptedAgentOutputRecord`，再生成唯一
  final `OperationalOpportunityAudit`；只有命中 outcome schedule 的槽位另外生成 eligibility
  audit。裸 payload、“latest accepted”跨 namespace 查询、record/audit 的
  graph/run/slot/origin/variant/kind/hash 不一致均失败。graph state 只能保存十个 Macro
  record ID/hash；weighted/Decision accepted runtime input 也必须保存并解析对应 record，
  stage-skip input 携带 accepted record 字段或模型看到这些内部外键均失败。
  `DOWNSTREAM_ONLY` accepted/failure
  不得伪造 outcome 样本，但必须进入
  最近 30 个 accountable operational opportunities；外生排除不进入，少于 30 个机会时不得
  隐藏已有失败。
- Darwinian 权重必须同 cohort、合同和 behavior 版本匹配，`effective_at<=as_of`
  且记录 ID 可回查；十条输入必须共享同一 Darwinian 合同和 snapshot。
  未来、缺失、非有限、非正或混合批次权重拒绝。只有新 track 从未发布权重且已证明
  少于 30 个匹配样本时才允许唯一的 1.0 initialization；已有合法权重的 track 不足
  30 时必须保留该权重，不能再次 fallback 到 1.0。
- evaluation/usage track key 对 `execution_behavior_version` 敏感；model revision、语言、
  解码参数、tool capability、snapshot bundle contract 或 parser/repair policy 任一变化时不得
  继承旧样本；usage track 也不得继承 previous weight。
- track key、outcome contract、`EvaluationOpportunitySet`、eligibility audit、outcome label
  和组件校准记录的 `outcome/scoring/sample_schedule/rank_scope` 四个 version 必须完全
  相等，`primary_label_id`、`rank_scope` 值和 `darwin_application_mode` 也必须一致；缺字段、默认值或任一不匹配都不得成熟、join 或
  更新权重。
- track key 包含稳定的 reliability adapter/`confidence_semantics` contract，但不包含滚动
  `calibration_state_id`；同一 adapter contract 的新 calibration state 不重置样本/权重，
  算法、目标或 confidence 语义变化必须新建轨道。state 必须带匹配
  `calibration_target_id`，Sector directional/abstention 样本混训或 state 训练数据晚于
  `as_of` 时拒绝。
  `SourceLayerReliabilityAdapter` 的 discriminant 必须固定为：标准 Sector 只能
  `CALIBRATED_SECTOR_OUTPUT_UTILITY`，`relationship_mapper` 只能
  `MATERIALITY_WEIGHTED_PREDICTIVE_EDGES`，Superinvestor 只能
  `CALIBRATED_OUTPUT_LEVEL`；source layer、Agent 或 confidence source 交叉错配必须失败。
- usage checkpoint/batch 的 `rank_scope` 只能是 `UsageWeightRankScope`；四个
  `decision_*` scope 进入 usage batch、生成 weight record 或借用同名 self scope 时类型和
  readiness 都必须失败。
- 每个 active production variant 的 Darwinian roster 中，全部 28 个逻辑 Agent 各有且只有
  一条当前 production evaluation track，并恰有 24 条 `DOWNSTREAM_USAGE_WEIGHT` 轨和
  4 条 Decision `EVOLUTION_ONLY` 轨；多 variant 时总数按 roster 数相乘，不得跨
  cohort/language/release 合并。初始 16 个 active variant 因此必须得到 16 个 roster、
  448 条 evaluation track、384 条 usage track 和 64 条 Decision evaluation track；
  不得误验收为全库只有 28/24/4 条。
  后续 execution behavior release 只改变一个 Agent variant 时，stable roster ID 不变、
  roster revision 更新且仅该 Agent 的 track hash 变化；其余 27 条 evaluation track 和
  对应 usage track 必须复用。把全局 release/roster revision 写入 track key而导致整组
  冷启动，或跨 cohort/language 复用 track，均失败。
  shadow prompt 候选/paired champion 只能存在于 `KnotResearchTrack`，不能创建或冒充
  production evaluation/weight track。CIO 只用 accepted `cio_final` 计样本，proposal 不能
  重复计分。
- variant roster readiness 要求每个 Agent 同时存在评分合同、application mode 和
  role-matched outcome 映射；该 variant 的 24 个上游源必须有 usage-weight 冷启动/成熟状态，
  四个 Decision 必须没有
  weight row。只有 1.0 权重而没有后续成熟路径，或给 Decision 写 1.0，均拒绝。
- 验证渐进更新公式：Q1 乘 1.05、Q4 乘 0.95、Q2/Q3 不变，并裁剪到
  `[0.3,2.5]`；每个 variant 的 24 个全新 usage track 少于 30 个样本时各恰有一条
  1.0 initialization；
  曾经成熟/发布过权重后窗口重新不足 30 时保持最后权重而非重置 1.0。两个 peer scope
  分别少于 7/3 个成熟 Agent 时也保持上一权重。四个 Decision 少于 30 个样本只为 evaluation
  `COLD_START`，达到门槛后仍不得进入 weight updater/batch/snapshot。
- peer rank 使用共同 cutoff、最新 30 个 SCORE、算术均值和完整机会 schedule 的
  80% coverage 与 1260 交易日 max lookback；参数化覆盖 Superinvestor 的 2/3/4 成员和
  Sector 的 6/7/8/9 成员、epsilon tie、全部并列、midrank quartile、
  event-triggered contract 禁止加入 peer scope 和不同窗口长度，确保无隐式 tie-break。
- 十个 Macro、`sector_relationship` 和四个 Decision self scope 不做 cross-agent 排名；验证最近
  30 个非重叠样本均值的 `0.25/0/-0.25` 分档边界，并验证 relationship/CIO score
  变化不会改变其他 scope 的 quartile 或权重；Decision performance band/deficit 只供 KNOT，
  不创建 weight update。事件型 Macro 与固定槽位 Macro 之间不存在 rank batch 或
  opportunity normalization join。
- 同一 update slot 重跑、下一日但无新 label、相同 scoring-window hash、重复采集和
  相同 update-event ID 均为 no-op；新增成熟 label 只能触发一次更新，迟到 label
  不追溯重写已发布权重。相同 rank scope/update slot 在两个 production variant roster
  必须生成不同 checkpoint/batch/event ID，缺少或错配 roster 外键时拒绝；同一 stable
  roster 仅发生 release/revision 更新且 member tracks/outcomes 未变时则必须复用 event
  identity 并 no-op，不能重复应用 multiplier。
- v2 usage-weight/update/checkpoint/batch 表以完整 usage-track key 和 `update_event_id` 唯一；
  checkpoint 的 `usage_track_key_hash` 及 batch 的
  `member_usage_track_key_hashes` 必须只解析到同一 roster revision、同一 rank scope 的
  `DOWNSTREAM_USAGE_WEIGHT` 轨，不能混入 evaluation-track hash 或 Decision track；
  outcome watermark 使用单调 sequence 而不是字符串 ID max；注入任一 peer 成员写入
  失败时整批不可见，reader 只能读取原子 `PUBLISHED` snapshot。legacy
  `(cohort,agent,date)` 行不可被新查询混入，latest 查询必须返回单一合同/snapshot。
- 验证 evaluation track 主键包含 production-variant roster、cohort、language、Agent/角色合同、
  prompt/execution behavior、组件权重、
  reliability adapter/confidence 语义合同、outcome/scoring/sample-schedule/rank-scope
  合同版本、primary label、rank scope 值和 Darwin mode；任一不匹配时不得继承样本或
  previous weight。usage track 必须外键到 mode 匹配的 evaluation track。
- 本 v2 initial release 的每个 active production variant 必须为全部 24 个上游信息源各创建
  一条可审计的 1.0 冷启动记录，并让全部 28 条 evaluation track 从零成熟样本开始；
  不得只重置新增 ID 或 Sector。旧 `dollar/yield_curve/volatility` 权重、旧多行业总倾向、
  旧 sector universe、旧 prompt/runtime/output/outcome 下的样本、权重和 KNOT paired
  result 均不得继承。
- `technology`、`real_estate_construction` 和 `agriculture` 只使用各自 role-matched
  outcome，与其他 Sector/`commodities` 的标签、样本和权重轨道隔离。
- 低或零 usage share 不得删除事实、事件、claims、lineage 或 CRO 硬风险。
- model view 不包含 raw Darwinian/operational/effective reliability、record IDs、
  effective time、model confidence/calibration provenance、adapter version 或 promotion
  thresholds；Macro 必须通过 `ModelVisibleAcceptedMacroTransmission` 白名单序列化，
  model view 不得出现 agent/prompt/execution/component version、`model_confidence` 或
  `deterministic_data_quality`。Sector 必须通过显式白名单 DTO 序列化，model view 不包含完整 pairwise
  matrix、comparison/least-eligibility audit、合同/registry 版本、顶层或嵌套 submission
  confidence、model confidence；`relationship_mapper` 必须走独立
  `RELATIONSHIP_GRAPH` discriminant 和白名单 DTO，不能被错误解析为标准 Sector
  selection，且不得泄漏 edge/audit/attribution 版本字段；Superinvestor 必须通过独立显式白名单 DTO 序列化。
  所有 model-visible output envelope 必须是
  `ModelVisibleEvidenceLineageEnvelope`，其 schema 中不得存在 `evidence_bundle_ids`；
  仅在序列化后删除该字段的实现也必须由类型/泄漏测试捕获。Sector/Relationship/Superinvestor
  accepted output 必须保存解析后的
  `AcceptedMacroInputAttribution`，raw local refs 只在 submission audit，model view 两者都
  不包含。给任一内部 accepted 类型只做局部 `Omit`、把内部类型传给通用 model-input 泛型，
  或漏接 authoritative attribution 的实现必须由泄漏/合同测试捕获，runtime audit view 必须
  完整。
- 每个消费节点恰好提交十条 `SUBMISSION_SUMMARY` attribution，并覆盖多空目标相反时
  的 `MIXED`；模型只能给 local ref/claim/effect，不能回显 hash、runtime ID 或份额。
  runtime 冻结 payload 后解析 `target_ref/hash` 与权威 usage share，summary canonical
  hash 排除 attribution/envelope/lineage 字段且不自引用；非 `NOT_MATERIAL` 必须引用
  对应 claim，`NOT_MATERIAL` 必须为空且不得省略 Agent summary 行。
- 相同 causal key 不重复增加独立证据数，相反解释显式冲突。
- `CausalEvidenceContributionResolution` 对每个 key 固定
  `independent_evidence_count=1/cross_layer_confidence_reducer=NONE`；构造 Macro、
  Sector、Relationship、Superinvestor 以及 CRO/Alpha Decision confidence 数值大小相反的
  fixture，验证不会跨层取最大、相加或排序，同时所有解释、claims、层内 usage share、
  Decision 硬约束和冲突状态仍完整传递。
  同一 consumer invocation 的全部输入必须绑定同一 consumer-input/resolution-set hash，
  ordered source-layer refs 与实际输入逐项一致，并覆盖全部 envelope key；漏层、漏 key、
  多余 key、重复 resolution、只在各层内部去重或消费者重算 hash 均失败。
- `autonomous_execution` 不直接读取 Macro outputs；CIO final 是唯一正式 stance。
- 组件合成、Darwinian 元数据和 usage share 的 TypeScript/Python fixture 数值
  一致。
- Macro、Sector 和 Superinvestor source-layer snapshot/hash 在所有获准消费者间完全
  一致；存在方向信号时十个 Sector 和四个 Superinvestor 的 directional usage share
  各自在层内和为 1，低权重输出不被删除，三个新增 Sector 权重实际进入下游输入。
  Superinvestor 的四个 roster slot 必须逐一接受 accepted output 或同 Agent/hash 的 stage
  skip；共享冻结 domain 为空时四个 slot 必须全部 skip，非空时必须全部 accepted，混用
  分支直接拒绝。skip 固定 usage share 为 0，不携带权重、operational reliability 或
  calibration state。四个 slot 全部为 skip，或非空域上的四个 accepted output 全部合法
  abstention 时，才允许整层 `NO_DIRECTIONAL_SIGNAL`；存在方向 accepted output 时所有输入
  必须共享 `SIGNAL_SET_READY`。`source_entry_status=ACCEPTED_OUTPUT` 与
  `NO_EVALUATION_OBJECT` 的 payload 不得互相反序列化。
- 九个标准 Sector/四个 Superinvestor 必须分别保存 model confidence 与 adapter 校准后的
  `directional_confidence/abstention_confidence`，并覆盖显式 identity cold start、稳定
  adapter contract、滚动 calibration state 和缺失记录拒绝；Sector
  `NO_QUALIFIED_DIRECTION` 与 Superinvestor `NO_QUALIFIED_CANDIDATES`
  必须 directional confidence/usage share 为 0。全层合法 abstention 应放行完整事实与
  风险并标记 `NO_DIRECTIONAL_SIGNAL`，而非拒绝或归一化 abstention confidence；
  该状态必须进入 runtime 与 model transport schema，存在方向时改为
  `SIGNAL_SET_READY`；model view 不得再使用语义不明的通用 accepted confidence；
  Sector adapter 必须只校准语义稳定的 submission 顶层 confidence，SELECTED 与 abstain
  使用分离 target/state；SELECTED 内 least eligibility 或腿数变化不能切换 target、取两侧
  最小值、求和或生成两个 usage share；
  relationship directional confidence 只能由版本化 edge adapter 确定性生成，事实边不
  隐藏；缺少 adapter 或 confidence 时 source layer 拒绝。
- `CONTROL_SET_READY` 只允许 Decision-to-Decision 的 CRO/Execution control payload；
  Macro/Sector/Relationship/Superinvestor 使用该状态、存在硬约束却标
  `NO_DIRECTIONAL_SIGNAL`、Alpha/CIO 使用 `CONTROL_SET_READY`，或通用 model-input union
  接受 Decision 内部 DTO 均失败。
  类型测试必须证明封闭 `DownstreamAgentInput` 不存在 `"DECISION"` branch，不能通过泛型
  参数实例化出带权 Decision；`DownstreamDecisionInput` 出现 darwin weight、usage share、
  effective reliability 或 weight record 外键也必须失败。Superinvestor stage-skip branch
  除固定 `usage_share=0` 外不得携带任何可靠度/权重/calibration/accepted-record 字段；
  Decision stage-skip branch 不得携带 operational reliability 或 accepted-record 字段。两类
  skip 都必须在 envelope、outer `agent_id`
  和 model-visible skip DTO 三处使用同一 Agent；只有 stage-skip causal resolution 可使用
  空 contributing claim refs，且必须为单 Agent/`FACT_ONLY`，普通 accepted-output
  resolution 为空时失败。
  类型测试还必须证明 Decision runtime outcome-scheduled skip 只接受
  `NoEvaluationObjectStageSkipRecord`、CIO KNOT control-only 依赖只接受
  `KnotControlNoEvaluationObjectStageSkipRecord`，两者跨 namespace 互换失败。
  所有 runtime/model input 的 `language` 必须与 graph 当前 production variant、accepted
  record 和 weight track 一致；同 cohort 内混用中英文输出或权重必须拒绝。
- 全部 24 个 v2 上游 usage track 低于 30 个匹配样本时从各自唯一 1.0 initialization
  开始；后续不足窗口不得覆盖已发布权重。六个新增 ID 还必须验证不存在旧 ID alias；
  Decision 永远不生成 weight。
- 中国、美国和欧盟实体经济及四个金融/商品 Agent 的组件集合、基础权重与和为
  1 的合同。
- 确定性数据质量在 `[0,1]`，required 失败关闭、optional 按输入权重降质；模型
  或 prompt 不能覆盖，模型置信度与数据质量分别留痕。DIRECT accepted
  `confidence` 必须等于 `model_confidence*deterministic_data_quality`，写入组件校准信号时
  对应字段名为 `effective_confidence`；COMPONENTS 按第 3 节含 dispersion 的 composer
  计算且不得把 top-level 诊断值再次相乘，TS/Python fixture 数值一致。
- 组件校准只接受 PIT、合同匹配、成熟、非重叠且无 fallback/冲突的样本。
- 普通 daily run 未命中固定 slot、事件未被 registry 选择或机会集冻结失败时，不得生成
  `ComponentCalibrationSignal`；验证不能事后补造 `scheduled_sample_id/outcome_due_at`，
  但当日 accepted transmission 仍可写非训练诊断。只有运行前已有合法 schedule/opportunity
  set 且组件输出 accepted 的运行才生成 signal。
- 每条组件校准信号必须有可重算的自身 ID/hash，固定
  `sample_origin=PRODUCTION_ACTIVE`，并解析到同一 graph/run/slot/variant 下唯一的 Macro
  `AcceptedAgentOutputRecord` 和引用它的 final `ACCEPTED`
  `OperationalOpportunityAudit`；KNOT shadow、裸 payload、悬空/跨 namespace 外键或
  accepted/operational hash 不匹配均拒绝。
- 组件信号只能 join 唯一 `AgentOutcomeLabel`，不得生成第二套
  `ComponentOutcomeLabel`；重复/缺失/版本错配 label 都拒绝。
- 七个组件 Agent 的校准 target 必须与各自 Darwinian `primary_label_id` 的 role path
  完全一致；role-path 子路径必须与该 Agent 组件集合一一对应，outcome 合成权重固定在
  outcome contract，不能被当前/候选 component weight 改写。通用宽基/等权 A 股标签替代、
  候选权重同时改变预测和 target 时测试失败。
- 只有 stable `cohort_default/zh` reference variant 当前有效 revision/release 的运行
  进入正式样本计数，同一 `agent_id/as_of` 只计一次；其余 15 个
  production variant 只作分离诊断，不产生伪重复样本，且每条 signal 的
  stable roster/revision/release/cohort/language/sample-role 必须一致。仅其他 Agent
  变化导致的全局 release/revision 更新不得切断该 Component Agent track 的历史样本。
- outcome 固定使用 T+1 开盘至第五个交易日收盘，所有组件共享同一 due time；
  accepted `persistence_horizon` 复制到校准信号的 `live_persistence_horizon` 仅作诊断，
  不能与候选权重一起改变五日 label horizon。
- 少于 60 个样本不拟合、60–99 个样本仅 shadow、至少 100 个样本才可申请
  正式晋级。
- 校准权重满足总和、上下限、单次最大变化和跨 cohort 一致性约束。
- 校准目标必须用 production composer 生成离散 direction/strength/confidence 后的
  `p=confidence*direction_sign*strength/5`；构造 `F` 改善但部署 `p` 恶化的 fixture，
  候选必须拒绝。solver version 和相同输入字节一致性也必须验证。
- 五日 purge/embargo、至少五个 fold、每 fold 至少 12 个样本、方向阈值、
  NORMAL/STRESS 定义、75% fold 调整方向和 50% 边界命中门槛。
- 样本外无改善、方向命中率下降、任一 regime 超限或 shadow 样本不足时拒绝
  晋级并保持旧权重。
- 新组件权重版本只向未来生效、不改写历史，并创建从 1.0 开始的独立
  Macro usage-weight 轨及独立 evaluation 评分轨。
- 行为性 prompt 变更创建独立 `prompt_behavior_version` 和 Darwinian 轨道；仅 prompt
  行为变化而 execution canonical fields 不变时沿用 `execution_behavior_version`，语言改变
  或 provider/model revision、解码、tool/snapshot/parser/structured-output/schema-binding/
  immutable-phase-instruction 任一变化时才同时
  创建新的 execution version。只有同一语言内、不改变 canonical behavior block 语义的
  拼写/格式修正才只更新 content hash。
- shadow behavior 使用相同冻结输入独立运行或固定 PIT replay；复制 champion 输出、
  选择有利日期、跨 behavior 复用输出或少于 30 个非重叠样本晋级时失败。
- KNOT pair 必须共享同一 `RealizedOutcomeObservation`，但 champion/candidate 必须各自产生
  不同 `evaluation_object_hash`、label ID、raw metrics、utility 和 normalized score；复用
  production label、双方共用一条 label 或复制 label 字段时失败。所有
  `KNOT_RESEARCH_SHADOW`、`KNOT_POST_PROMOTION_CHAMPION_SHADOW` 的 outcome/
  operational audit 与 label 的 production eligibility flag 必须为 false，并从
  production Darwin maturity、rank、usage updater 和 operational reliability 查询中排除；
  KNOT 自身只能在 research namespace 对称读取其 shadow operational audits。
- `KNOT_CONTROL_SHADOW` 只允许生成 production-ineligible operational audit，不能生成
  outcome eligibility audit/label 或 `KnotResearchScoreRecord`；其 failure 只用于 CIO pair
  dependency-blocked 诊断，不能污染依赖 Agent 的 production 或 research 轨。空控制对象
  必须由同一 operational audit 派生唯一 `KnotControlNoEvaluationObjectStageSkipRecord`；
  control operational row 必须先固定 skip ID、`stage_skip_hash=null`，随后 control skip
  hash 覆盖 final operational ID/hash。出现双向 hash、引用普通 outcome stage skip、
  缺/错 operational hash、CIO pair 复用 production/research/latest Alpha/CRO/Execution
  accepted record，或把 control skip 用于 production graph 均失败。
- 组件权重候选只能复用冻结的 `ComponentCalibrationSignal` 和唯一 production
  `AgentOutcomeLabel` 做确定性 paired recomposition；不得创建 component-calibration
  sample origin、额外 outcome eligibility audit/label、operational audit 或 maturity sample。
- promotion 必须在未来生效点创建零样本 production evaluation track；有 usage mode 时另建
  1.0 weight track。promotion 前 research labels、paired champion labels、持续 shadow labels
  和样本计数均不得复制或 join 到 production；首个 production 成熟样本只能来自 promotion
  生效后的 `PRODUCTION_ACTIVE` slot。
- Autoresearch 覆盖确定性 track selection、单一最小 mutation、前 30 个可问责 paired
  research scores、统一 `raw_research_score/research_comparison_score`、Agent failure=-2、
  共同 exogenous 排除、
  CI/BH gate、atomic promotion、20 样本持续 shadow、hard safety 即时回滚、性能/
  operational rollback、cooldown 和相同 research slot 幂等；标准 Sector 还必须验证双方
  inference budget 相同、review 只能由 resolver 触发、review reserve 不可转移、额外
  subcall/token 超限为 failure、`0.5/0.5` token-cap 归一化、`0.2/0.05` 成本公式、
  `[-1.25,1]` 合法成功范围、cost-adjusted comparison score 与 `raw_research_score` 双门槛，
  以及 review rate/call/token 审计。非 Sector 成功样本必须精确使用 normalized score；
  failure 没有 outcome label/normalized score，但两个 research score 都必须为 -2，并在完整
  30-pair 分母进入晋级/回滚，不能只比较双成功子集。`SectorInferenceCostAudit` 必须覆盖
  0/1/2/3/>3 次调用、最后尝试阶段、pre-model/subcall/越权/预算失败与成功分支，且不得在
  outcome 成熟后被回写。`KnotResearchScoreRecord` 必须覆盖 Sector/non-Sector 的成功与失败
  discriminant、audit/label nullability、成功后 join、失败即时 `-2`、pair-side 幂等和
  append-only，并逐侧保存 stable roster/revision/release/cohort/language、prompt/execution version、
  scheduled sample 和共同 snapshot hash；任一跨 variant/版本错配均拒绝。
  KNOT `SectorInferenceCostAudit` 也必须绑定同一 pair side、roster、Agent 和 snapshot。
  failure=-2 必须严格低于两类成功分数下界。mutation manifest 只能 pin
  score/scheduler contract ID/hash，不能覆盖系数；所有由 active production variant
  evaluation track 派生的 KNOT track、pair/promotion/rollback audit 必须保存匹配全局
  `KnotRuntimeContractManifest` binding；Sector universe
  只能引用 score contract ID/version/hash，不能内嵌可漂移副本。KNOT 不得写权重或合同。
- Autoresearch selection 先在每个 scope 内提名，再按 scope 服务债务轮转；构造两个
  normalized-score 分布不可比的 scope，验证不会跨 scope 排序。mutation manifest 的每个
  `production_variant_roster_id/production_variant_roster_revision_id/
  execution_behavior_release_id/cohort_id/language` target
  variant 必须各自具备 30 个配对样本和 holdout gate；未配对
  的其他 cohort/语言既不能放行也不能否决，多变体不得部分晋级。非
  `cohort_default` target 必须在自身 variant schedule/replay 上运行，禁止借用
  `cohort_default` 样本；仅 prompt behavior 改变的 candidate 必须保持 execution version
  不变，execution canonical field 改变的 fixture 才要求新 execution version。scheduler
  nomination/service-debt/cooldown key 缺少 `production_variant_roster_id`，或一个
  cohort/language 的 active candidate 阻断/放行另一 variant 时测试失败。
- Autoresearch 测试固定 self deficit 公式、无 deficit 时的
  `NO_RESEARCH_NOMINATION`、较低 operational reliability/较早 mutation/字典序 tie-break，
  并验证晋级边界精确为
  `candidate_operational_reliability >= champion_operational_reliability - 0.05`。
- 合同迁移 fixture 验证 roster/tool/snapshot/source/PIT/capability/RKE 任一变化都会生成新
  `execution_behavior_version`、独立 KNOT/Darwinian track 和
  `CONTRACT_MIGRATION_PAUSED`，旧 paired samples/weight/champion manifest 不得继承。
- KNOT champion/candidate 目标 Agent 的独立签名 capability 必须指向同一预物化
  root `snapshot_bundle_id/hash`、tool payload hashes、runtime input 和 frozen scope；tool call 中
  发生 collector I/O、候选通过 raw/ticker/旧政策/RKE 工具扩域、使用不同 vintage，或修改
  immutable prompt block 时 pairing 失败。`RKE_SHADOW` experiment 不得 promotion 到 production。
- CIO KNOT fixture 必须证明两侧共享 pre-CIO root/Alpha accepted-or-skip，但各自 proposal
  只派生本侧 CRO/Execution bundle；依赖 contract/version/底层市场 payload 必须相同，
  side-specific hash 差异只能来自 proposal/control/frozen object。没有预先冻结 Alpha
  input 时只能运行一次并复用于两侧；Alpha/CRO/Execution 依赖调用只写
  `KNOT_CONTROL_SHADOW` operational audit，不得污染其 production Darwin maturity/usage/
  operational reliability、独立 KNOT research track，或生成依赖 Agent 的
  `KnotResearchScoreRecord`。合法 stage skip 继续 final；任一侧 dependency block
  必须标记 failed pairing 并消耗预注册 slot，不得按共同 exogenous 静默跳过、替换样本或给
  CIO 记 `-2`；
  CIO proposal/final 自身失败才形成该侧唯一 `AGENT_FAILURE=-2`，两阶段不得生成两条
  research score。
- Macro 权重以 role-matched outcome 更新；CIO 最终结果和下游 attribution
  只作诊断，不能进入任何上游 `normalized_score`。

### 15.8 Outcome 合同与反归因污染

- `AgentOutcomeContract` 矩阵必须恰好覆盖 28 个 Agent，无缺失、重复或未知
  `agent_id`；每行的 evaluation object、label、horizon、rank scope 和 Darwin application
  mode 必须与
  第 10.2 节完全一致。
- eligibility audit/outcome label 必须保存并匹配
  `graph_run_id/run_slot_id/production_variant_roster_id/production_variant_roster_revision_id/
  execution_behavior_release_id/cohort_id/language/track_key_hash`；label 的
  `outcome_sequence` 必须是 label store 分配的严格递增正整数。跨语言/roster 错接、
  sequence 重复/倒退或由模型/source 提交均失败。
- `NOT_MATURED`、`SCORE` 和 post-acceptance exclusion audit 必须保存非空
  `accepted_output_id/hash` 并解析到同一 scheduled sample 的
  `AcceptedAgentOutputRecord`；其他 eligibility 分支必须保存 null。label 必须与最终
  `SCORE` revision 引用同一 accepted record。ID/hash 悬空、record hash 不可重算、
  payload owner 与 Agent 不一致、跨 graph/run/slot/origin/variant join 或读取
  “latest accepted”均失败。
- audit revision hash 必须可从 immutable revision 重算；label 必须引用最终 `SCORE`
  revision，stage skip 必须引用最终 `NO_EVALUATION_OBJECT` revision，CIO dependency
  outcome audit 必须引用依赖 Agent 的最终阻断 eligibility revision。只保存稳定 audit
  ID、引用 PENDING/已 supersede
  revision、revision hash 不匹配或读取 latest 漂移均失败。
- `OUTCOME_LABEL_REGISTRY` 必须生成以 `primary_label_id` 区分的 Zod/Python/JSON
  `RealizedOutcomeObservation` 与 `AgentOutcomeLabel` schema；自由字符串 horizon/schedule、
  `Record<string,...>` realized/raw metrics、未定义常量、
  缺少 null/scale 或分母为零规则时合同构建失败。
- `RealizedOutcomeObservation` 只能保存共同实现事实、机会集和 PIT evidence，不得包含
  Agent 输出、预测误差或 utility。KNOT champion/candidate 可以引用同一 observation，
  但必须拥有不同 label；`sample_origin` 和 eligibility flag 必须满足封闭真值表：
  `PRODUCTION_ACTIVE` 才能且必须进入 Darwin evaluation，只有其中
  `DOWNSTREAM_USAGE_WEIGHT` 才能进入 usage updater，所有 outcome-shadow 两个 flag 都为
  false；`KNOT_CONTROL_SHADOW` 不能进入 outcome schema，
  audit 的 `production_reliability_eligible` 也必须当且仅当 production active。模型字段覆盖、
  任一非法 boolean 组合或 shadow 样本进入 production maturity/rank/weight/reliability 查询均失败。
- 每个 production evaluation track 必须关联一个可成熟的 outcome contract；
  `fallback_allowed` 必须为 false，required source 为空、labeler 未注册或评分
  数据不可用时 roster 不得 READY。
- 按每个 `DarwinProductionVariantRoster` 验证 24/4 application-mode 分区：
  Macro/Sector/Superinvestor 必须有 usage-weight 外键，
  CRO/Alpha/Execution/CIO 必须 `EVOLUTION_ONLY` 且不存在 current/legacy-mixed weight row；
  Decision score 仍进入 KNOT selection/promotion/rollback，但不进入 usage-share 或 weight batch。
- `normalized_score` 必须为确定性 `[-1,1]` 值，必须保存 frozen
  evaluation object hash、outcome evidence 和 PIT 状态；LLM 不能生成或修改 label。
- 每个 scheduled sample 必须在 Agent 前冻结并 hash `EvaluationOpportunitySet`；标准
  Sector/Superinvestor/Alpha/CRO/Execution/CIO 的 missed opportunity 分母按第 10.1 节
  生成，测试拒绝 outcome 后全市场最佳项、CIO 采纳集合或仅已选证券替代冻结集合。
- opportunity-set 成功/失败必须服从 `AgentOutcomeEligibilityAudit` discriminated union：
  AVAILABLE 分支要求非空 set ID/hash 且 generation failure 为 null；UNAVAILABLE 分支固定
  `EXOGENOUS_EXCLUSION/OPPORTUNITY_SET_UNAVAILABLE`、set ID/hash 与 evaluation object
  为 null，并保存可重放的非空 generation attempt/source/error evidence。空字符串/伪造
  空 set、两分支字段混用或失败后仍启动 Agent 均拒绝。成功冻结的空 member set 必须保留
  非空 set/evidence 并固定为运行前
  `EXOGENOUS_EXCLUSION/NO_EVALUATION_OBJECT`；它不能伪装为 UNAVAILABLE，也不能启动 Agent。
  四个 Superinvestor 与三个可跳过 Decision Agent 必须各在自身空对象分支生成唯一、hash
  可重算的 stage-skip record；Macro、Sector、CIO 不得借此伪造 accepted output 或绕过
  required stage。类型测试必须证明 `member_state=EMPTY` 只能绑定
  `NoEvaluationObjectStageSkipAgentId`，其他 Agent 的空 generator result 只能进入
  `UNAVAILABLE/OPPORTUNITY_SET_UNAVAILABLE`。状态优先级测试必须证明 opportunity-set
  generation failure 先于空集判断、合法空集先于完整模型 snapshot readiness、非空集才检查
  required snapshot，且一个 scheduled sample 不得同时出现 skip、data exclusion 或
  `AWAITING_AGENT_RUN`。
  CIO 在无证券持仓、无新增候选的全现金 fixture 中仍必须用 canonical cash
  portfolio/null-policy member 生成非空 set，并可评价 `HOLD_CURRENT/ALL_CASH`；返回空 set
  或伪造 CIO stage skip 必须失败。
  AVAILABLE 内继续参数化拒绝
  `SCORE+accepted_output=false/null evaluation object`、
  `AGENT_FAILURE+accepted_output=true`、普通 failure 使用 `fallback_used=true`、
  `MODEL_FALLBACK+fallback_used=false`、外生 reason 进入 `AGENT_FAILURE`，以及
  agent reason 进入 `EXOGENOUS_EXCLUSION`。外生排除必须区分运行前和 outcome-maturity
  分支：前者无 run/evaluation object，后者保留已接受输出及其 hash；
  `NO_EVALUATION_OBJECT/OVERLAPPING_WINDOW` 出现在 post-acceptance 分支必须失败。
  CIO 还必须覆盖封闭的两阶段分支：proposal 自身 failure 固定 phase=PROPOSAL 且无 proposal
  ref，final 自身 failure 固定 phase=FINAL 且保留 proposal ref；两者各只生成一条 CIO
  `AGENT_FAILURE`。Alpha 在 proposal 前阻断只能形成
  `last_completed_cio_phase=NONE/run_id=null`，CRO/Execution 在 proposal 后阻断只能形成
  `last_completed_cio_phase=PROPOSAL` 并绑定 proposal。`DEPENDENCY_AGENT_FAILURE` 与
  `DEPENDENCY_EXOGENOUS_EXCLUSION` 必须分别引用 disposition 匹配、同 graph run 的依赖
  audit，且 `blocked_dependency_disposition` 交叉错配时类型/语义校验失败；合法 stage
  skip、已接受但 `NOT_MATURED` 或 post-acceptance exclusion 不得被误判为 dependency block。
- outcome contract、track、opportunity set、audit、realized observation、label 和组件信号的
  `primary_label_id` 必须逐字段一致；缺失、自由字符串或跨 Agent label join 均拒绝。
- 每个 production run slot 都有唯一 `OperationalOpportunityAudit`，覆盖 scheduled 与
  downstream-only、accepted、schema/semantic/tool/fallback failure、pre-run exogenous、
  stage skip 和 CIO dependency-blocked；只有 `production_reliability_eligible=true` 且
  `accountable=true` 的 accepted/failure 进入 operational reliability。重复 slot、漏记
  downstream-only failure、用 outcome audit 代替 operational audit 或同一 slot 双计均失败。
  Production origin 可合法绑定 scheduled/downstream-only；KNOT research/post-promotion
  origin 只能绑定 scheduled，`KNOT_CONTROL_SHADOW` 只能绑定
  `alpha_discovery/cro/autonomous_execution` 和
  `DOWNSTREAM_ONLY/scheduled_sample_id=null`。任一 Agent/origin/schedule 交叉错配或把 CIO
  sample ID 写到控制依赖 audit 均失败。
  CIO `DEPENDENCY_BLOCKED` operational audit 必须引用依赖 Agent 同一 graph run 的 final
  operational audit ID/hash，且 disposition 与 dependency reason 匹配；引用 outcome
  revision、旧/不同 run 的 operational row 或无法重算 hash 均失败。
  每个 `ACCEPTED` operational audit 必须解析到唯一、hash 可重算的
  `AcceptedAgentOutputRecord`；kind、Agent owner、payload owner 字段、graph/run/slot、
  sample origin/schedule 和 variant/behavior 全部一致。只有 CIO proposal/final 可共享同一
  operational opportunity，且 operational accepted 只能引用 `CIO_FINAL`；proposal 被当作
  success、non-CIO kind/Agent 在类型层交叉错配、KNOT/control record 被 production reader
  选中或 accepted record 保存 operational hash 形成循环依赖均失败。
  KNOT run-based origin 缺 operational audit ID 或无法解析 final audit 时失败；组件权重
  候选不是 Agent run-based origin，若创建任何 operational/outcome audit 或额外 label
  同样失败。
- 每个计划评价样本另有 eligibility audit；覆盖 accepted、schema/semantic/tool 拒绝、
  model fallback、required-data unavailable、未成熟和 `OVERLAPPING_WINDOW`。只有
  outcome contract 指定且进入最终 `SCORE` 的 accepted evaluation output 才能形成 VERIFIED
  label；CIO proposal、downstream-only/control accepted output 和排除记录不能伪装成
  label。CIO proposal/final
  必须共享一个 logical operational opportunity：自身任一
  阶段失败只计一次，dependency audit 不进入 CIO 分母，但被引用依赖 Agent 的原始 failure
  仍进入该依赖自身分母。
- Macro 点预测平方损失技能分以 `p=0` 为 null；验证 confidence=0 得到零技能而非正分，
  正确校准预测优于 null，错误高置信度预测受罚。每个 label 的 reference set、截止日、
  q90 scale、epsilon 和 hash 冻结，live label 不能更新 normalization scale。
- `output_utility=-forecast_loss`、`null_utility=-null_loss`、
  `utility_delta=output_utility-null_utility` 只做一次 baseline subtraction；构造
  `null_utility!=0` fixture，验证归一化不会二次减 null。
- 十个 Macro label 的 role path、代理篮子、权重、PIT 成分股、基准、复权和波动率尺度
  必须完全预注册；缺任一 required 输入时不得回退 CSI300、通用
  benchmark 或 CIO PnL。
- Macro 事件样本、固定 5 日槽位、Sector 5 日、relationship 20 日、
  Superinvestor 21 日、Execution T+1 和其他 Decision 5 日的成熟时间、
  purge 和非重叠选样通过未来数据泄漏测试。
- 标准 Sector 按完整冻结 direction 截面计算的 50% direction MSE-skill 与按冻结 side
  shortlist 计算的 50% security MSE-skill，必须使用 TS/Python 共享 fixture 验证。覆盖
  preferred-only 时所有未选方向严格 `p=0`、required least 时只有审计 least 为负、
  least 不合格、单方向非重合 null、未选方向/证券 `p=0`、LONG/SHORT/AVOID、exact
  shortlist 外 pick 拒绝、空但合法 shortlist、无法重建 shortlist、confidence=0/1、
  SELECTED unit-confidence target、非空 shortlist 的 `NO_QUALIFIED_SECURITY` proper
  loss/regret、abstention sparse-template opportunity evaluator、
  materiality floor/regret scale、冻结且非平凡的 abstention base rate、Brier skill 减
  missed-opportunity regret、direction/shortlist/template 数量匹配的 cardinality-adjusted
  null maximum、raw max 与 adjusted utility 分离、null 样本不足/错误 key/hash 拒绝、
  两类 calibration state 隔离、零 scale 和分母为零；least 状态
  不得切换 benchmark 或 normalization family。
  整体 abstain 保留机会集，方向/证券子技能为零，但 primary score 必须按 abstention proper
  loss 对正确弃权奖励、错误弃权惩罚；always-abstain、confidence 降到零、使用 live
  abstention 分布拟合 null、删除样本、从冻结模板外添加证券或按 outcome 后全市场最佳/最差项
  构造仓位均不得逃避负分。relationship 的 50% trigger 激活校准/
  50% 后续匹配非边 lift 和 Superinvestor 固定 21 日下行惩罚使用 TS/Python 共享 fixture
  验证；relationship fixture 还必须覆盖全部冻结 candidate、候选域外/重复绑定拒绝、
  未提交 candidate 的 `direction=null/confidence=0`、非空机会集上的正确/错误空图、
  graph-abstention base-rate Brier skill、missed-edge regret 和空机会集 required-data
  unavailable；零、负、`NaN`、无穷 materiality weight，非正/非有限权重和，以及 outcome
  edge metric 缺失、重复、重排或改写冻结权重必须拒绝。自报 holding period 不能改变主
  label horizon。
- CRO 测试覆盖风险 precision/recall/specificity/校准、`NO_OBJECTION`、无风险
  窗口、下游未采纳的反事实候选和硬约束不受权重影响；candidate raw metrics 必须与
  frozen universe 一一对应，空 universe 只能形成
  `EXOGENOUS_EXCLUSION/NO_EVALUATION_OBJECT`。
- Alpha 测试覆盖已选 novel picks、相对 Layer-3 的增量 alpha、`NONE_FOUND`
  漏报和 CIO 未采纳仍评分；空 novel universe 只能形成
  `EXOGENOUS_EXCLUSION/NO_EVALUATION_OBJECT`。
- Execution 测试覆盖真实 fill 与 paper 确定性成交模型、成本误差、可行性
  分类、delta 达成和政策合规；后续股价收益不得进入 Execution score，空 order-intent set
  必须跳过模型且只能形成 `EXOGENOUS_EXCLUSION/NO_EVALUATION_OBJECT`，非空 set
  不得用空 accepted output 删除样本；submission/accepted schema 出现 `NO_DELTA` 分支时失败。
- CIO 测试覆盖 T+1 进场、五日净费用组合收益、回撤、换手、约束、
  `HOLD_CURRENT/ALL_CASH` 和 proposal 不计分。四个 Decision raw-metrics schema 必须
  拒绝自由 component ID、缺失固定分量、错误 component weight/权重和、非有限数、非正
  scale、错误单位/方向、未注册分母为零规则，以及 output/null/utility delta 重算不一致。
- label owner 校验必须拒绝 CIO PnL 更新上游轨道、attribution 更新 Macro
  权重、下游未采纳删除上游样本，以及任意 cross-agent label write。
- 两个 peer scope 的成员集、最少成熟数 7/3、小 scope 第一名 Q1/
  最后一名 Q4，以及十个 Macro、`sector_relationship`/四个 Decision self scope 的成员隔离和
  绝对分档，必须参数化覆盖。不同 null/normalization family 或 coverage 不足的 label
  不得进入同一 peer 排名；Macro outcome 不参与任何 cross-agent peer 排名。
- outcome label、horizon、frozen object、归一化或数据源变更时必须发布新
  scoring contract，旧样本不得继承；usage track 的 previous weight 也不得继承。

### 15.9 Prompt

Prompt 测试必须捕获：

- OpenCLI、Google/Caixin、雪球正式因子依赖。
- Tushare `major_news`、`news`、`npr`、`monetary_policy` 工具、调用路径或 fallback
  依赖。
- 散户情绪和机构背离旧字段。
- `china` Macro prompt 把地产设为必选维度；`real_estate_construction` 的角色职责不属于该禁令。
- `energy` prompt 遗漏光伏、风电或电池/储能，或把新能源汽车整车归入 `energy`；
  `industrials` prompt 重复纳入光伏/风电/电池子域。
- 任一标准 Sector prompt 要求逐子行业分别输出、输出总体 `sector_score`、允许模型自造
  direction ID；direction-research/review prompt 提前要求或允许 preferred/least/picks，或 final-selection
  prompt 未明确要求“恰好服从 directive 的 registered preferred、least 必须服从 runtime
  eligibility status 且不得用 confidence 自行省略”。
- Sector research prompt 未在 `n>=2` 时要求全部 eligible pair 各覆盖八个 criterion verdict，
  或未在 `n=1` 时要求唯一 direction 对注册 null 的同八 criterion qualification；允许模型
  提交 overall pair winner/decisive list、允许省略不可比 ETF criterion、允许第二轮 conflict
  review，或 review prompt 携带 final selection；模型自行计算 ETF/篮子技术指标、手写 ETF
  清单/reducer/outcome 公式、把 `NO_REGISTERED_ETF` 当成资金流出、把 macro-event 或
  catalyst source unavailable 写成中性/负面而非各自的 `NO_VOTE`、用财经日历无事件覆盖
  行业 catalyst 状态、用 catalyst source 故障覆盖 macro-event 状态、让 ETF 获得整票/单独建边，或让 optional ETF
  confirmation 替代 required 成分股技术基座。
- 标准 Sector 的 `CONFLICT_REVIEW/FINAL_SELECTION` 获得任何 tool capability、复用
  `DIRECTION_RESEARCH` handle、重新采集 snapshot 或使用不同 root bundle；只有第一
  subcall 可调用本角色工具，后两者必须只消费同 bundle 的 runtime 投影。
- DXY/iVX 误标。
- 手写 schema。
- `.zh.md` 英文正文。
- 不同 cohort 完全相同。
- bundled prompt 过长。
- `research_knobs` 或内部旋钮泄漏。
- bundled/private prompt 不符合第 12.2 节固定简化结构，或包含 endpoint/series catalog、
  capability 字段、原始 source-registry readiness、KNOT scheduler/pairing/promotion 状态。
- production 未固定 private commit/variant/content hash、私有文件缺失时回退 bundled、
  bundled 与 private `cohort_default` canonical behavior block 不一致，或 fake/offline 与
  production 复用同一 `execution_behavior_version`。fake/offline smoke 若启用任何正式
  accepted/audit/outcome/weight writer、写入 `PRODUCTION_ACTIVE` 或留下可被 production/KNOT
  reader 查询的样本，同样失败。
- Zod 生成 JSON Schema 未通过 provider structured-output channel 强制、schema binding-set
  hash/provider mode 未进入 behavior version、自由文本 repair 冒充结构化成功，或 prompt
  重新嵌入手写字段表。
- Sector 三个 phase schema ID/hash 或 CIO 两个 phase schema ID/hash 未同时进入有序
  behavior binding set、phase 间复用错误 schema、其他 Agent 不恰有一个 `DEFAULT`、
  immutable phase instruction 缺失/漂移、set hash 无法重算、无冲突仍调用 review，
  或任一 phase 返回其他 phase 字段。
- raw Darwinian/operational/effective reliability、record ID、adapter version、rank/
  promotion/rollback 阈值泄漏；只允许最终 `usage_share` 出现在获准消费者输入。
- Agent 越权访问原始 `eco_cal`。
- production prompt 中的 `get_rke_research_context`、`get_industry_policy_digest`、任意 ticker
  查询参数或不属于第 6.1.1 节该 Agent 的 snapshot 工具。
- 旧六因子、`G/R/W/S`、`±0.3` Macro 阈值或 Macro stance 指令泄漏。
- 消费 Macro 的下游 prompt 缺少十条 `SUBMISSION_SUMMARY` attribution、目标级
  attribution 合同，或 execution prompt 直接包含 Macro outputs/usage share。
- prompt 泄漏 `primary_label_id`、outcome 公式、quartile 边界、Agent 当前权重
  或成熟评分结果。
- 私有 prompt 总数必须恰为 448，并按 160/160/64/64 分层；所有 28 个 Agent、
  8 个 cohort 和中英文组合均存在且只有一份。
- 初始 `active_production_variants` 必须恰有 16 个唯一 cohort/language key，每个 key
  精确解析 28 个 prompt variant 和一个 Darwin production roster；缺失、重复、只激活
  `cohort_default` 或不发布新 release 就临时停用 variant 均失败。
- 448 份 immutable block hash、完整 content hash、structured-output schema binding-set
  hash、runtime
  tool manifest 和 KNOT champion baseline 必须逐 variant 绑定其精确
  `execution_behavior_version`，同时全部列入同一原子 `execution_behavior_release_id`。
  中英文被错误绑定为同一 behavior hash、variant/version 映射缺失/重复、KNOT 改动
  职责/禁区/工具/schema block、新旧工具混用或把 bundled/fake 与 private production
  variant 配对时 drift gate 失败。

### 15.10 命令

TypeScript：

```bash
cd mosaic-ts
pnpm typecheck
pnpm lint
pnpm test
pnpm prompt:check
pnpm prompt:drift
pnpm dev daily-cycle --cohort cohort_default --fake-llm
```

Python：

```bash
uvx ruff@0.15.15 check mosaic tests
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp \
  uv run python -m pytest tests/ -q \
  --basetemp .mosaic/tmp/pytest-mosaic-rke
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp \
  uv run python scripts/check_prompt_leaks.py
git diff --check
```

额外 smoke：

- 29 阶段 fake smoke；每个标准 Sector 在无冲突路径执行 comparison+final 两个 subcall，
  在冲突路径执行 comparison+review+final 三个 subcall，但 stage/accepted-output/
  operational-opportunity 计数仍各为一。
- 一次具备 Tushare 权限的真实结构化单日 smoke。
- 对 Eurostat、ECB 和 World Bank 执行 response schema
  drift 检查。
- 对 geopolitical required adapters 执行无正文落盘的 live health/schema/pagination smoke，
  并验证既有连续 30 日 preflight 报告满足 availability/latency SLO；单次成功不能代替
  30 日 readiness。
- 使用不调用 LLM 的冻结历史/合成 fixture 回放至少 30 个非重叠 outcome，覆盖
  5/20/21 日和 T+1 成熟、peer/self 更新与幂等；单日 smoke 不作为 Darwinian
  成熟路径的证明。
- 不启动 100 日测试。

## 16. 提交和 PR

- 公开仓和私有 prompt 仓继续使用
  `codex/macro-agent-role-contracts`。
- 两仓在实施开始时都必须以各自最新 `main` 为基线并记录 base SHA；若同名分支已经存在，
  先把最新 `main` 纳入该分支再追加本计划提交，不能以过期基线继续开发。
- 私有 prompt 仓先提交。
- 公开仓运行清单固定私有 commit/hash 后再提交。
- 公开 PR 包含代码、schema、数据工具、bundled prompt、测试和文档。
- 私有 PR 只包含双语 prompt。
- 两个 PR 保持交叉链接并继续为 draft，直到全部验收完成。
- 推送前检查历史中不存在 Tushare 原文、本地缓存或许可数据。

## 17. 完成定义

只有同时满足以下条件才算完成：

1. 目标 28 Agent / 29 阶段图运行成功。
2. 10 个 Macro Agent 和 10 个 Sector Agent 的 model submission、accepted
   output、职责边界和工具合同通过；四个无权限 Tushare endpoint 保持禁用且不存在
   runtime 调用路径；所有其他已引用 Tushare endpoint 均在封闭 registry 中且具有明确
   preflight/active 状态。28-Agent 工具矩阵由预物化 snapshot bundle、签名 capability 和
   原子使用账本在 bridge 服务端强制执行，模型不能伪造角色、日期、候选域、bundle 或调用
   原始/任意 ticker 工具，tool call 不发生实时重采集。
3. `eco_cal` 能被获准 Agent 共享；同一 evidence bundle 在 Macro scope
   只有一个 PRIMARY signal owner，Sector-specific PRIMARY 不形成第二张
   Macro 票，`get_role_event_snapshot()` 由运行时绑定身份，且 lineage envelope
   与绑定同一 consumer-input snapshot/hash 的 `CausalEvidenceResolutionSet` 让下游跨
   Macro、Sector、Relationship 和 Superinvestor 按共同 causal key 去重；
   跨层 confidence 不比较、不求和，冲突解释和全部 claims 仍完整传递。event presence 与
   required-route completeness 分开记录，部分事件不能掩盖 route 故障或放行 Decision。
4. `geopolitical` required official/discovery family 覆盖健康，30 日可得性/延迟
   preflight、append-only 生命周期、确认级别、PIT 时效和“无事件”覆盖语义均可审计；
   初始 exact source/actor/region/approved-domain manifest、强类型 adapter 和逐
   actor/region/global event coverage route 已提交并通过 hash/route-closure 校验；source
   stale、未确认或后来回填不能
   产生正式方向或评分样本。每条 applicable route 的 no-event source 子集非空且全部
   `no_event_claim_capable=true`；仅 discovery/confirm-capable source 不能生成“无事件”。
   缺少 actor 自身官方站点不会在替代 route 完整时造成永久失败。
5. 中国宏观五组件与 PBOC/中国利率五个 required family 具有已验证的官方目录、权限、
   PIT、freshness 和 append-only adapter，信用字段所有权不重复，两个中国 snapshot
   在缺失或过期时失败关闭；MPC/执行报告分别使用可审计的
   `expected_next_release+15/first_published+150` freshness，不套用 Fed/ECB 90 日规则。
6. 美国实体四组件、美国金融条件四组件、商品四组件和市场定位四分支均来自明确、
   权限已验证的 source map；USD/CNY、名义/实际曲线、基金/ETF universe、
   `fund_adj`/share corporate-action adjustment 和合约 expiry 可 PIT 审计，required
   缺失不 fallback。
7. 欧盟实体与欧元区金融 required 数据均来自已验证映射，PIT、expected-release
   freshness、grace 和 hard-cap 边界可审计；第 6.4 节每个 Eurostat dimension 与 ECB
   exact key 具有非空 metadata/data、structure hash 和禁止静默替代的 drift gate；
   changing-composition EU vintage 与固定 `EU27_2020` 不得拼接。
8. World Bank 只提供 `CONTEXT_ONLY` 背景。
9. 十个 accepted Macro outputs、Darwinian/operational reliability 元数据、不可变
   source-layer snapshot、usage share、lineage 和 summary/目标级 attribution 直接贯通；
   全部 accepted payload 只通过 namespace-safe `AcceptedAgentOutputRecord` 持久化和进入
   graph，graph state 只保存 record ID/hash，production/KNOT/control 的
   graph/source-run/slot/origin/cohort/language/kind 不可混读；
   Sector 与 Superinvestor 层同样传递独立输出和可靠度，运行时不存在六因子或
   Macro stance。Sector 下游只通过显式白名单 DTO 暴露最终 selection、
   `directional_confidence/abstention_confidence`，内部 model confidence、合同版本和全部
   comparison/eligibility audit 不泄漏。带 usage weight 的封闭输入 union 不接受 Decision；
   Superinvestor 空候选域使用无权重的 stage-skip branch，只有非空候选域上的主动弃权进入
   accepted output、calibration 和 Darwinian 样本；Decision-to-Decision 只使用无 weight
   字段、Agent/payload 绑定的显式合同和白名单 DTO。
10. 组件权重固定合同、离线校准、shadow 晋级和 Darwinian 版本隔离均可审计，
   且 KNOT/Darwinian 不直接修改组件权重。全部 28 个逻辑 Agent 都有有效 evaluation
   track、可成熟 outcome 合同和唯一 label owner；每个 active production variant 恰有
   24 个上游源拥有 usage-weight track，四个 Decision 固定 `EVOLUTION_ONLY` 且不存在
   weight row。本 v2 initial release 的全部 24 个上游 usage track 从各自唯一 1.0
   冷启动记录开始，全部 28 个 evaluation track 从零成熟样本开始，并按同一渐进/演化合同
   推进；六个新增 ID 不得继承任何旧 ID 轨道。十个 Macro label 的 PIT A 股
   role-path/传导代理映射验证通过，CRO/Alpha/Execution/CIO 按专属 outcome 评分，
   四类 Decision submission/accepted/model-view 和 raw-metrics Zod family 完整，
   CIO PnL 不能反向更新上游权重；CIO proposal/final 只形成一个 logical operational/
   evaluation opportunity，依赖阻断不污染 CIO reliability，CIO KNOT 依赖调用不污染
   Alpha/CRO/Execution production 轨；更新对重复运行幂等，没有新成熟 label 时权重
   不得变化。KNOT 双方只共享实现观察、不共享 label；所有 KNOT shadow outcome 样本及
   组件校准 signal/recomposition 工件与 production Darwin maturity、rank、usage weight 和
   operational reliability 严格隔离，
   promotion 后从未来 slot 的空 production track 冷启动。
11. bundled prompt 按固定最小结构生成且无 source/capability/KNOT/knob 泄漏；production
    只加载 pinned private prompt，bundled/fake 使用独立 behavior version，Zod schema 通过
    out-of-band structured output 强制；fake/offline 关闭全部正式持久化与评分 writer，
    MOSAIC-Combat-Evolved 只看到角色行为合同。
12. 私有仓 448 份中英文 prompt 完整、语言正确、cohort 有真实差异，immutable block、
    runtime manifest 和 KNOT champion baseline 逐 variant 绑定精确 execution behavior
    version，并由同一 execution behavior release 原子发布；合同迁移不继承旧 paired samples。
13. 29 阶段 fake smoke 和单日结构化 smoke 通过。
14. prompt leak、隐私边界、lint、typecheck、相关测试和
    `git diff --check` 全部通过。
15. 九个标准 Sector、relationship、四个 Superinvestor 和 CRO/Alpha/Execution/CIO
    专属快照具备可审计的 frozen scope、PIT 公告时间和 required failure semantics；SW2021
    exact universe、可重放成员查询、无重叠且全覆盖的 direction registry、全局 overlap
    precedence、基于个股 `moneyflow.net_mf_amount` 的 `SectorFlowCoverageContract` 与
    Decision deterministic algorithm registry 已冻结；`moneyflow_ind_ths` 仅为 optional
    diagnostic，不存在 THS→SW 分摊合同；Alpha 非 ST 资格使用逐日 `stock_st`，2016 年以前
    无替代 PIT 档案时失败关闭；
    direction/parent/single-null benchmark 由 kind 匹配的 tagged query plan 重放，direction
    return 必须由绑定 direction ID/hash 的 `DIRECTION_PARTITION_PIT` 生成，且 single null
    不与自身/parent 成分重合；每个标准
    Sector 恰好输出一个注册 preferred，least 是否必需完全由可重放
    `LeastPreferredEligibilityAudit` 决定，整体无 preferred 时合格 abstain，且不生成多行业
    总分。固定 26-entry/公式闭集 metric registry、全方向 PIT 成分股技术卡、90% required
    coverage、运行前 exact scoring shortlist、每侧 pick/budget 约束、可得时的
    direction ETF 价格/份额/估算申赎确认、80% holdings exposure、ETF 单 direction 独占和
    exact tracked-index contract/hash、corporate-action adjustment 均通过；逐 criterion 全
    pair audit、core/coverage-gated/ETF 半票 weighted resolver、一次幂等 conflict review、
    严格 Condorcet reducer、least audit、绑定 exact shortlist ID/hash 的独立 final
    selection directive/call 和 final evidence lineage 可重放。Sector SELECTED outcome 使用
    非中心化 active tilt 的 50/50 唯一公式，abstain 使用冻结 base-rate Brier skill 减
    missed-opportunity regret 的 primary utility，非空 security abstention 也使用 proper
    loss/regret，所有 opportunity max 均做 cardinality-adjusted null 校正；
    两者共享完整冻结方向截面和 exact side shortlist，least 状态不切换 benchmark/target，
    TS/Python 结果一致；Sector ETF 仅为 optional supplemental half-vote，缺失不影响 required
    readiness。Sector inference budget/cost audit、统一 `KnotResearchScoreContract` 与 KNOT
    `research_comparison_score` 配对门通过。
    relationship 冻结机会集非空且所有 materiality weight 为严格正的有限值，outcome
    一一复用冻结 candidate 顺序与权重。
    Macro/Sector/Relationship/Superinvestor accepted attribution 和各自显式 model-visible DTO
    边界通过泄漏测试。
    Decision 五阶段严格按
    `Alpha -> CIO proposal -> CRO -> Execution -> CIO final` 运行，proposal 显式绑定
    Alpha accepted/skip，CRO/Execution/final 都引用同一 proposal lineage，任何阶段倒序、
    旧 run/hash 或绕过 proposal/CRO 的候选均失败；final 必须复用 proposal 的 pre-CIO
    source-layer snapshot，CIO 自身 proposal/final failure、依赖阻断与合法 stage skip 的
    audit/operational/KNOT 归因互不混淆；`KNOT_CONTROL_SHADOW` 依赖调用只写非生产
    operational audit，不创建 outcome audit/label。
    无 broker
    quote/OMS 时真实执行不可用，
    `get_rke_research_context` 只存在于隔离 shadow。

## 18. 已确认的公开接口

- Tushare `eco_cal`：
  https://tushare.pro/document/2?doc_id=233
- Tushare 申万行业分类 `index_classify`：
  https://tushare.pro/document/2?doc_id=181
- Tushare 申万行业成分（分级）`index_member_all`：
  https://tushare.pro/document/2?doc_id=335
- Tushare 同花顺行业资金 `moneyflow_ind_ths`：
  https://tushare.pro/document/2?doc_id=343
- Tushare 个股资金流向 `moneyflow`：
  https://tushare.pro/document/2?doc_id=170
- Tushare 历史 ST 股票列表 `stock_st`：
  https://tushare.pro/document/2?doc_id=397
- Tushare 接口权限目录（含 ETF/基金复权因子 `fund_adj`）：
  https://tushare.pro/document/1?doc_id=108
- PBOC 公开市场业务公告目录（现有 `pboc_ops.py` adapter）：
  https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125431/index.html
- PBOC 利率政策/LPR 目录：
  https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125440/index.html
- PBOC 货币政策委员会例会目录：
  https://www.pbc.gov.cn/zhengcehuobisi/125207/3870933/3870936/index.html
- PBOC 货币政策执行报告目录：
  https://www.pbc.gov.cn/zhengcehuobisi/125207/125227/125957/index.html
- PBOC 金融统计/社会融资规模发布目录：
  https://www.pbc.gov.cn/diaochatongjisi/116219/116225/index.html
- 国家统计局“国家数据”（GDP、CPI/PPI、工业、零售等）：
  https://data.stats.gov.cn/easyquery.htm
- 海关总署月度进出口公报：
  https://english.customs.gov.cn/statics/report/monthly.html
- 财政部全国财政收支情况：
  https://www.mof.gov.cn/zhengwuxinxi/redianzhuanti/quanguocaizhengshouzhiqingkuang/
- ALFRED vintage 数据库：
  https://alfred.stlouisfed.org/
- Federal Reserve FOMC calendar/statements：
  https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
- New York Fed Markets API：
  https://markets.newyorkfed.org/static/docs/markets-api.html
- GDELT 2.0 Event codebook（15 分钟数据表）：
  https://data.gdeltproject.org/documentation/GDELT-Event_Codebook-V2.0.pdf
- 中国外交部重要新闻：
  https://www.mfa.gov.cn/web/zyxw/
- 中国商务部产业安全与进出口管制局：
  https://aqygzj.mofcom.gov.cn/
- UN Security Council Consolidated List（XML/HTML/PDF）：
  https://main.un.org/securitycouncil/en/content/un-sc-consolidated-list
- OFAC Sanctions List Service / official list resources：
  https://ofac.treasury.gov/other-ofac-sanctions-lists
- BIS Federal Register Notices：
  https://www.bis.gov/regulations/federal-register-notices
- USTR Section 301 official actions：
  https://ustr.gov/issue-areas/enforcement/section-301-investigations/search
- European Commission sanctions resources / EU official lists：
  https://finance.ec.europa.eu/eu-and-world/sanctions-restrictive-measures/overview-sanctions-and-related-resources_en
- MARAD Maritime Security Communications with Industry advisories：
  https://www.maritime.dot.gov/msci-advisories
- UKMTO maritime advisories：
  https://www.ukmto.org/
- OCHA ReliefWeb API V2（仅 optional、需预批准 appname 和许可 preflight）：
  https://apidoc.reliefweb.int/index.html
- Tushare `fina_mainbz` 权限与历史覆盖目录：
  https://tushare.pro/document/1?doc_id=108
- Tushare `disclosure_date`：
  https://tushare.pro/document/2?doc_id=162
- Tushare `us_tycr`：
  https://tushare.pro/document/2?doc_id=219
- Tushare `fx_obasic/fx_daily`：
  https://tushare.pro/document/2?doc_id=178
  https://tushare.pro/document/2?doc_id=179
- Eurostat Web Services：
  https://ec.europa.eu/eurostat/data/web-services
- Eurostat 本计划冻结的实体 dataset API：
  https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/namq_10_gdp
  https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/prc_hicp_minr
  https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/une_rt_m
  https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/sts_inpr_m
  https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/sts_trtu_m
  https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/ext_st_eu27_2020sitc
- Eurostat Euro indicators 与 vintage 说明：
  https://ec.europa.eu/eurostat/web/euro-indicators/information-data
- ECB Data Portal API：
  https://data.ecb.europa.eu/help/api/data
- ECB 本计划冻结的金融 series（series page/API metadata 双重校验）：
  https://data.ecb.europa.eu/data/datasets/FM/FM.B.U2.EUR.4F.KR.DFR.LEV
  https://data.ecb.europa.eu/data/datasets/FM/FM.B.U2.EUR.4F.KR.MRR_FR.LEV
  https://data.ecb.europa.eu/data/datasets/EST/EST.B.EU000A2X2A25.WT
  https://data.ecb.europa.eu/data/datasets/YC/YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y
  https://data.ecb.europa.eu/data/datasets/YC/YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y
  https://data.ecb.europa.eu/data/datasets/BSI/BSI.M.U2.Y.U.A20T.A.I.U2.2240.Z01.A
  https://data.ecb.europa.eu/data/datasets/MIR/MIR.M.U2.B.A2A.A.R.A.2240.EUR.N
  https://data.ecb.europa.eu/data/datasets/EXR/EXR.D.USD.EUR.SP00.A
  https://data.ecb.europa.eu/data/datasets/CISS/CISS.D.U2.Z0Z.4F.EC.SS_CIN.IDX
- Sector official overlay 入口（均须 adapter preflight 后启用）：
  https://www.miit.gov.cn/
  https://www.nea.gov.cn/
  https://www.nmpa.gov.cn/
  https://www.cde.org.cn/
  https://www.nhsa.gov.cn/
  http://www.moa.gov.cn/
  https://www.cma.gov.cn/
- World Bank Global Economic Monitor：
  https://datacatalog.worldbank.org/search/dataset/0037798/global-economic-monitor
- World Bank Indicators API：
  https://datahelpdesk.worldbank.org/knowledgebase/articles/889392
