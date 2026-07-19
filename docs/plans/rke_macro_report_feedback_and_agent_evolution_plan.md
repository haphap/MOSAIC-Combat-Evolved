# Part 1：RKE 个股、行业、宏观研报市场反馈、评级与 Agent 演化闭环计划

> **范围说明（2026-07）：** 本文只保留 RKE report-feedback 的历史设计语境。
> 当前运行角色、prompt 消费和演化/晋级边由
> `docs/plans/macro-agent-role-contracts-v2-plan.md` 覆盖；RKE 在 v2 中保持
> shadow-only，不向生产 prompt 或交易决策提供晋级边。

## 背景

Report Intelligence 已经把个股、行业、宏观三类研报接入抽取链路，并形成了同一条基本
原则：LLM 只抽取观点、方向、目标、机制和方法，系统用 PIT 市场数据生成非 LLM 市场反馈。

已有基础：

- 行业研报已经接入 `industry_etf_proxy`，使用行业 ETF 的 PIT 价格窗口生成 outcome label。
- 个股研报已经接入 `stock_price_proxy`，使用 qlib 股票价格、benchmark、T+1 entry 和成本模型
  生成 outcome label/readiness。
- 宏观策略研报已有 `macro_asset_proxy`，并在本计划中补齐 direct macro series、curve、
  claim legs、regime snapshot 和 macro agent prior。

当前能力可以证明三类研报观点已经“开始可评价”，但还没有达到“个股、行业、宏观观点全面可评级、
可演化、可供下游 agents 使用”的交付标准。主要限制是：

1. 当前宏观市场反馈仍需要补齐和稳定直接利率、收益率曲线、汇率、波动率、
   非黄金商品期货/现货序列接入 outcome labeler。
2. 多资产宏观观点常常包含“利率、美元、人民币、黄金、权益、债券”多个 leg，但当前
   `target` 更接近单目标映射，容易丢掉完整宏观策略观点中的一部分。
3. `claim_regime_trace` 已经作为 PIT 背景信息存在，但还需要稳定的
   agent-readable regime snapshot 和 agent prior 输出。
4. 个股、行业、宏观 outcome 不能混算：必须按 `label_type`、target family、benchmark family、
   cost model、agent layer、metric family 和 regime bucket 分层，避免把异质资产和成本模型
   当作同质样本。
5. 下游 agents 需要的是可审计、可降级、无 source prose 泄漏的研究先验，而不是原始 claim
   文本、source span 或 LLM 自评。

本计划把 `docs/plans/rke_stock_report_outcome_and_evolution_plan.md` 已定义的个股/行业
outcome 闭环，与本文件后续宏观补齐工作合并到同一个交付口径。P0-P11.6 按三域展开
claim 契约、PIT 数据、outcome labeler、抽取、context、评级、prior、演化、schema/audit/test
和实施拆解；P12-P14 给出统一交付状态和下一步优先级。

## 目标

最终目标是让个股、行业、宏观研报观点都形成完整闭环：

```text
个股 / 行业 / 宏观研报 PDF/Markdown
  -> source-grounded stock / industry / macro claim
  -> domain-specific target resolution and PIT context
  -> non-LLM market outcome labels
  -> claim rating and viewpoint performance profile
  -> redacted agent research priors
  -> offline evolution candidates
  -> gated shadow adoption
```

交付后应满足：

- 个股、行业、宏观观点可评级：每条可评价 stock / industry / macro claim 或 claim leg
  都能产生 pending、blocked 或 completed 的 PIT 市场反馈状态。
- 个股、行业、宏观观点可演化：错误、正确、低置信、mapping gap、数据缺口、tool gap 和
  prior misuse 都能进入 evolution candidate 输入，而不是只停留在人工审阅记录。
- 个股、行业、宏观观点可供 agents 使用：下游 macro、sector、superinvestor、decision
  agents 可以读取红线内的 redacted summary/prior，不读取私有原文、source span 或 claim text。
- 个股、行业、宏观观点可审计：PIT、provenance、statistical robustness、privacy、schema、
  retrieval ranking 和 evolution gate 都能验证。

## 原则

1. LLM 只负责抽取观点、结构、机制、目标和方法；不判断研报观点是否正确。
2. claim correctness 只能来自非 LLM 的 PIT outcome label 或人工 gold-set。
3. `claim_regime_trace` 是背景信息，只用于回测后分层评价，不用于抽取阶段验证 claim。
4. 宏观 claim 的 `claim_horizon` 来自原文上下文；固定的 90/180/360 天只是 evaluation
   windows，不能伪装成原文预测期限。
5. 直接 PIT 序列优先于 proxy。个股用股票价格，行业用治理后的 ETF proxy，收益率、汇率、
   波动率、商品价格有 PIT 序列时不能悄悄用 ETF proxy 反推。
6. 多资产宏观观点必须保留 parent claim 和 child claim legs；个股/行业观点必须保留
   target resolution 证据，不能为了单目标 label 丢失
   原文策略逻辑。
7. 缺目标、缺方向、缺 quote convention、缺 PIT 序列、缺交易日或 exit 未到期时，只记录
   readiness gap 或 pending window，不补造 label。
8. RKE 继续 shadow-only；任何研报研究先验都不能直接改变生产交易决策。
9. report-intelligence 派生 artifact 默认本地私有处理，不提交到 public repo；即使是
   redacted aggregate，也必须有明确任务要求才允许进入 repo。任何可发布的 agent
   prior 也只能是 redacted derived summary，不能包含 `claim_text`、`source_span_ids`、原文摘录、
   报告摘要或私有 licensed 数据。

## 当前状态

当前已有能力：

- `forecast_claims.jsonl` 能承载个股、行业、宏观 claim、`analyst_claim`、`claim_regime_trace`、
  `metric_proxy_mapping` 和 pre-review。
- 个股 `stock_price_proxy` 已接入统一 outcome/readiness/profile 路径，包含 T+1 entry、
  benchmark 对齐、20 bps 成本、停牌/退市/价格缺失 readiness gap。
- 行业 `industry_etf_proxy` 已接入统一 outcome/readiness/profile 路径，包含治理后的 ETF
  mapping、PIT availability、T+1 entry、10 bps 成本和 mapping/PIT gap。
- `macro_asset_proxy` 已进入 outcome label schema 和 readiness。
- `macro_asset_proxy` 使用 T+1 entry 和 90/180/360 evaluation windows。
- `outcome_label_source=pit_macro_asset_etf_price_window`。
- `decision_basis=directional_macro_asset_proxy_return`。
- PIT/provenance/statistical robustness/evolution readiness gate 已能覆盖首轮宏观 proxy label。
- 本分支已新增 `macro_series_directional` 与 `macro_curve_directional` label type，
  收益率、汇率、波动率、商品价格、期限利差等 direct PIT 序列优先于 ETF proxy。
- 本分支已新增 scorecard `macro_series` 只读适配器：
  `ReportIntelligenceConfig.scorecard_db_path` 指向已有 `scorecard.db` 时，refresh 会按
  claim 所需 series/curve leg 读取 PIT observations 并生成 `sha256:` data vintage hash；
  DB 或序列缺失时只进入 readiness gap，不补造 label。
- 本分支已新增 `mosaic-rke macro-series-backfill`：
  先用已有 `mosaic.dataflows.macro_data` adapter 拉取宏观序列并写入 scorecard
  `macro_series`，再运行 `mosaic-rke report-intelligence --refresh-derived-only
  --scorecard-db-path data/scorecard.db`。RKE refresh 仍只读 scorecard DB，不负责原始数据采集。
- 本分支已新增本地 redacted `macro_regime_snapshots.jsonl` 与
  `macro_agent_research_priors.jsonl` 能力：只包含 agent/date/regime/profile aggregate 和
  shadow-only policy，不包含 `claim_text`、`source_span_ids`、报告标题或原文。该类
  report-intelligence 派生文件仍按本地私有处理，默认不提交。
- 本分支已新增 parent macro claim + child `macro_claim_legs` 契约：`forecast_claims.jsonl`
  仍是私有源头，不新增平行 raw claim 文件；宏观 outcome/readiness/profile 在内存中按 leg
  展开，并通过 `parent_forecast_claim_id`、`macro_claim_leg_id`、`macro_claim_leg_index`
  保持可追溯。
- 本分支已让 `macro_asset_proxy`、`macro_series_directional`、`macro_curve_directional`
  labels 写入 leg trace 字段；asset proxy 额外写入 `target_agent_candidates`、
  `quote_convention=price_return` 和 `proxy_or_direct=proxy`；curve label 额外写入
  `entry_spread_bps`、`exit_spread_bps` 和 `curve_direction`。
- 本分支已扩展 `macro_regime_snapshots.jsonl` 的 agent-readable 字段：
  `regime_family`、`regime_features`、`feature_units`、`source_series_ids`、
  `missing_feature_reasons`，且继续保持 `background_only=true`、
  `claim_validation_allowed=false`。
- 本分支已扩展 `macro_agent_research_priors.jsonl` 的 downstream 字段：
  `macro_claim_leg_ids_redacted`、`metric_family`、`target_series_family`、
  `expected_direction`、`latest_completed_exit_date`、`freshness_bucket`、
  `known_failure_mode_tags`、`tool_gap_ids`；并新增 `mosaic-rke export-macro-agent-priors`
  用于按 `agent_id`/`as_of_date` 输出 redacted shadow prior。
- 本分支已在 evolution readiness gate 中新增 RI-MACRO-01 至 RI-MACRO-07 分支：
  无宏观输入时作为 not-applicable 通过；存在宏观 claim/label/prior/snapshot 时检查 leg
  contract、PIT label coverage、regime snapshot background-only、market-feedback rating
  evidence、prior privacy、prior shadow-only policy 和 readiness gap audit。

## 当前实现边界

截至 2026-07-03，RKE 已经形成“个股、行业、宏观研报观点可评级、可进入 shadow
evolution gate”的三域市场反馈底座；宏观还额外形成了 redacted macro agent prior MVP。
但三域整体还没有完整实现为：

```text
个股 / 行业 / 宏观研报 claim / all-agent claim
  -> 通用 mechanism candidate
  -> 通用 rule pack / parameter prior
  -> 受控 validation
  -> module-level Prompt IR / Agent Runtime patch
  -> all-agent autoresearch / Darwinian weight / RKE profile replay
  -> monitoring / rollback feedback
```

当前已实现或已有 MVP 证据：

```text
1. `macro.central_bank` 有 central-bank MVP 骨架：
   claim / hypothesis -> rule pack -> parameter prior -> validation checker
   -> mutation / patch validator -> Prompt IR artifact -> runtime checker
   -> paper-trading / monitoring / rollback readiness reports。
2. Report Intelligence 已经能生成个股、行业、宏观 claim、PIT outcome labels、
   viewpoint/source profiles 和 evolution readiness gate。
3. 宏观路径已经能生成 macro claim legs、macro regime snapshots 和 macro agent research priors。
4. `weighted_research_contexts.jsonl` 已经计算 source/viewpoint/combined research prior weight。
```

当前缺口：

```text
1. `macro.central_bank` MVP 不能代表所有 macro agents、sector agents、investment agents
   或全量研报 claim 已经自动编译为 rule pack。
2. 个股、行业、宏观 agent prior 仍主要是 redacted research context，不是 validated rule pack、
   parameter prior 或 production runtime patch。
3. Patch artifact 和 validator 已存在，但从 validation result 到 Prompt IR / Agent Runtime 的
   apply/activation 状态机尚未通用化。
4. Agent-facing RKE context 仍需落地 retrieval ranking，不能只按输入顺序截断。
5. Autoresearch 和 Darwinian weight 还需要读取 RKE prior usage quality、agent claim outcome、
   RKE profile update、rollback feedback，并覆盖 macro、sector、superinvestor、decision
   全部 agent prompt，才能形成 replay 中可进化的闭环。
```

因此，本计划后续阶段要把“个股、行业、宏观研报可评价/可导出 prior”推进到“所有 MOSAIC agents 能在
replay 中可审计地使用 RKE prior，并让使用效果反哺各层 prompt、rule、parameter、profile
和 retrieval ranking”。研报反馈是 RKE 输入源，prompt evolution 的对象覆盖 macro、sector、
superinvestor 和 decision agents。所有阶段继续保持 shadow-first；任何生产影响仍需单独
promotion gate。

### 三域交付边界

| 域 | 当前评价通道 | 下游 agent 消费目标 | 仍需补齐 |
| --- | --- | --- | --- |
| 个股 | `stock_price_proxy`，PIT 股票价格、benchmark、成本和 readiness gap | superinvestor、decision、sector relationship mapper 读取 redacted stock prior | agent-facing retrieval ranking、stock prior 到 recipe/rule candidate、agent claim outcome 回流 |
| 行业 | `industry_etf_proxy`，治理后的行业 ETF mapping、PIT availability 和 readiness gap | sector agents、decision agents 读取 redacted sector/industry prior | 行业映射 coverage 继续扩展、sector agent target ranking、ETF proxy 局限性标注 |
| 宏观 | `macro_asset_proxy`、`macro_series_directional`、`macro_curve_directional`、macro claim legs 和 regime snapshot | macro agents、decision agents 读取 redacted macro prior | 证据样本仍薄、retrieval ranking、candidate compiler、cross-asset consistency 和 orphan assignment |

### Prompt private repo 边界

所有涉及 agent prompt 内容、prompt mutation、prompt hash 冻结、prompt drift 复核和
prompt evolution 的工作，都以 private prompt repo 为 source of truth。MOSAIC-RKE public
repo 只保留：

- agent id、runtime schema、tool contract、prompt loader 和最小 fallback prompt。
- private prompt repo 路径/版本/hash 的引用与检查结果，但不提交完整优化 prompt 内容。
- prompt leak/drift 检查脚本、runtime wiring、测试 fixture 和 migration audit。

后续优化 Munger、Burry 以及其他 agents 时，完整中文/英文 prompt、role rubric、RKE 使用细则、
tool discipline 和 mutation candidate 必须落在 private prompt repo；public repo 只同步必要的
agent roster、fallback prompt、schema 和测试。benchmark/replay 记录应保存 effective prompt
source、private prompt revision/hash、fallback 是否被使用，以及 prompt unavailable 的降级原因。

Canonical private prompt repo：

- repo identity：`https://github.com/haphap/MOSAIC-Prompts`。
- 优化后的 prompt 可以在该 private repo 中直接覆盖当前 agent prompt 文件；不需要在 public
  repo 复制完整 prompt，也不需要为每次优化新增平行 prompt 文件。
- “直接覆盖”仍必须通过 private repo 的 git history 审计：记录 branch/commit、prompt file
  path、prompt sha256、review/benchmark 结果和 rollback target。

运行契约：

- Prompt resolution 优先使用 `MOSAIC_PROMPTS_REPO` 或 `MOSAIC_PRIVATE_PROMPT_REPO` 指向
  `https://github.com/haphap/MOSAIC-Prompts` 的本地 clone；`MOSAIC_PROMPTS_ROOT` 仅作为
  直接 `prompts/mosaic` 路径入口，并且必须能恢复 git provenance。bundled prompt 只作为
  smoke/fallback。
- 正式 LLM benchmark、replay、autoresearch 和 Darwinian weight 评估不得静默使用 bundled
  fallback prompt。private prompt 缺失时，该 agent/date/model 组合必须记录 blocker 或
  `private_prompt_unavailable`，不能算作有效 paired comparison。
- 每次 benchmark/replay 必须记录 private prompt repo revision、prompt file hash、resolved
  prompt source、fallback_used=false/true 和 prompt loader config。
- public repo 不提交 private prompt 内容，只提交 loader/runtime 能识别 prompt source 的代码、
  最小 fallback prompt 和检查结果。

## 复用优先级

本计划不是新建第二套研报 RKE 系统。实施时必须优先复用现有结构，只有现有契约无法表达时才新增
artifact 或 builder；个股、行业、宏观都必须进入统一 forecast/outcome/readiness/profile/gate
语义。

必须复用的现有能力：

| 现有能力 | 复用方式 | 不重复造车约束 |
| --- | --- | --- |
| `forecast_claims.jsonl` | 继续作为 parent forecast claim 的私有源头 | 不新增平行的 raw stock/industry/macro claim 文件 |
| `claim_regime_trace` | 继续作为 claim as-of 背景 trace | 不把 regime trace 改成 claim validation |
| `build_stock_price_proxy_readiness()` / `build_stock_price_proxy_outcome_labels()` | 继续负责个股 PIT 股票价格 proxy | 不新建个股 outcome 文件；只扩展统一 label/profile 字段 |
| `build_industry_etf_proxy_readiness()` / `build_industry_etf_proxy_outcome_labels()` | 继续负责行业 ETF proxy readiness/outcome | 不把行业映射写回 prompt；mapping gap 进入 readiness/evolution |
| `build_macro_asset_proxy_readiness()` | 继续负责 ETF/资产代理 readiness | 只扩展字段和 mapping，不重写 ETF proxy labeler |
| `build_macro_asset_proxy_outcome_labels()` | 继续生成 `macro_asset_proxy` labels | 不为权益/债券/黄金 ETF 再建一套 macro price labeler |
| `build_outcome_labeling_readiness_report()` | 汇总 standard、industry、stock、macro readiness | 新增宏观 direct series readiness 时接入该总表 |
| `report_outcome_labels.jsonl` | 继续作为统一 outcome evidence 私有文件 | 不新增独立的 stock/industry/macro outcome 文件；redacted aggregate 也默认本地私有，除非任务明确要求提交 |
| `build_viewpoint_performance_profiles()` | 继续做 viewpoint 层 performance profile | 增加 macro layer/agent 分层，不新造 profile 聚合器 |
| `build_report_intelligence_evolution_readiness_gate()` | 继续作为演化 gate | 增加 RI-MACRO 子检查，不建第二个 gate |
| `schema_validation.py` | 继续做 schema 之外的 hard invariant | 扩展 validator，不只依赖 JSON Schema |
| `macro-agent-data-source-plan.md` | 作为 macro series/evidence 数据源蓝图 | 序列接入沿用其中的 agent/source taxonomy |
| `mosaic/dataflows/macro_data.py` 和 `mosaic/scorecard/store.py` 的 `macro_series` | 作为已有宏观序列采集/存储能力 | RKE 不重复存 raw series；只保存 mapping、hash、label 和 readiness |
| `research_prior_not_current_data` 运行时语义 | 作为下游 agent 消费边界 | prior 只能是研究背景，不能变成 current signal |

新增内容的判断标准：

1. 如果只是新增 label type，优先扩展 `report_outcome_labels.jsonl` 和现有 profile/gate。
2. 如果只是新增数据源，优先接到现有 qlib、ETF proxy、`macro_series`/dataflow/catalog 语义。
3. 如果只是给 agent 消费，优先复用 `research_prior_not_current_data` 和 weighted research context
   的 shadow-only 口径。
4. 如果 artifact 可能包含 source prose、claim text、source span 或 licensed raw data，默认 private。
5. 新 builder 必须回答：为什么现有 stock proxy、industry ETF proxy、`macro_asset_proxy`、
   readiness、profile 或 scorecard macro series 不能承载。

当前主要缺口：

| 缺口 | 当前风险 | 本计划解决方式 |
| --- | --- | --- |
| 个股 target resolution 仍需更严格审计 | metadata `ts_code`、LLM target 和正文公司主体不一致时可能误打 stock label | 建立 stock target resolution priority、`stock_target_conflict` 和 no-forced company-name mapping |
| 个股可交易性 gap 未进入 agent prior | 停牌、涨跌停锁死、退市和 benchmark 对齐问题可能被误读成观点错误 | stock context snapshot 和 rating 记录 tradeability failure tags，只输出 blocked/pending，不伪造 hit/miss |
| 行业 ETF mapping coverage 仍有缺口 | unknown sector 或 proxy 偏离会让行业观点被错误 ETF 评价 | governed mapping registry + PIT availability；无高质量 proxy 时保留 `sector_etf_mapping_missing` |
| 行业 proxy limitation 未进入下游 | sector agents 可能把 ETF proxy outcome 当成真实行业组合表现 | industry context/prior 记录 mapping confidence、proxy liquidity 和 limitation tags |
| 直接利率/收益率未 label | 利率下行 claim 只能 pending 或错误映射到债券 ETF | 新增 `macro_series_directional` label，bps change 直接评价 |
| 汇率 quote convention 不完整 | USD/CNY 上行和人民币贬值容易方向错配 | 每个 FX label 强制记录 quote convention 和 orientation |
| 商品非黄金 direct series 未接入 | 铜、油、黑色等 claim 只能 ETF proxy 或 pending | 新增 futures/spot mapping 和 commodity series family |
| 波动率可用但未纳入宏观 outcome | volatility agent 无法从研报观点获得评价 | 新增 volatility index/realized-vol label family |
| 多资产 claim 被压成单 target | 宏观策略观点的资产配置逻辑被截断 | 新增 parent claim + claim legs |
| stock/industry prior 还没有按 agent 角色排序 | 投资/行业 agents 可能只看到输入顺序靠前但低价值的研报经验 | 在统一 agent research context 中对 stock、industry、macro prior 使用同一 retrieval ranking policy |
| agent 消费接口不明确 | 下游 agents 不能安全使用 RKE 研报经验 | 新增/扩展 redacted agent priors，覆盖 macro、sector、superinvestor、decision |
| agent context 仍按输入顺序截断 | 已计算的 `combined_research_prior_weight`、source/viewpoint profile 和 reliability 没有真正进入下游优先级；高质量 prior 可能被低价值旧顺序挤出，autoresearch/Darwin 也无法观察 RKE 排序贡献 | 新增 agent prior retrieval ranking policy：先做安全过滤，再按 agent 匹配、profile match、combined weight、n_effective/reliability、freshness 稳定排序；低权重/反例只降权不删除 |
| regime trace 背景不够结构化 | 后续无法按 agent/regime 做归因 | 新增 PIT macro regime snapshot |

## P0：三域 claim 数据契约

三域共用 `forecast_claims.jsonl` 作为私有源头，不新增平行 raw claim 文件。每条 claim 必须能
落到以下三类之一：

| domain | 典型 report_type | target contract | primary outcome channel |
| --- | --- | --- | --- |
| `stock` | 个股研报 | `target_type=stock`、标准 `ts_code`、source-grounded company subject | `stock_price_proxy` |
| `industry` | 行业研报 | `target_type=sector` / `industry`、canonical sector、ETF proxy mapping | `industry_etf_proxy` |
| `macro` | 宏观/策略/固收/汇率/大类资产 | `macro_asset` / `macro_series` / `macro_curve` / `macro_regime` | `macro_asset_proxy`、`macro_series_directional`、`macro_curve_directional` |

共用字段要求：

```text
forecast_claim_id
report_id
domain
target_type
target_id
target_label
metric_family
direction
claim_horizon
evaluation_windows
target_resolution_source
source_grounding_status
target_agent_candidates
current_data_required=true
production_signal_allowed=false
```

### P0.S 个股 claim 契约

个股 claim 可评价条件：

- `target.target_type == "stock"`。
- `target.target_id` 是标准 `ts_code`，例如 `000001.SZ`、`600000.SH`、`920xxx.BJ`。
- `direction` 是 `positive` / `negative` 或可安全映射到看多/看空。
- `signal_datetime` 有效，且 qlib stock calendar 可找到 T+1 entry。
- claim 必须是公司主体相关，不允许把“公司”“龙头公司”等泛称直接当成 stock target。

目标解析优先级：

1. LLM `target.target_id` 与 Tushare 元数据 `ts_code` 一致时使用该 `ts_code`。
2. 元数据 `ts_code` 存在且原文支持该公司投资观点时，使用元数据 `ts_code`。
3. 元数据缺失但 LLM 抽出格式有效且 source-grounded 的 `ts_code` 时，使用 LLM target。
4. LLM target 与元数据 `ts_code` 冲突时，记录 `stock_target_conflict`，不生成 label。
5. 公司名到 `ts_code` 的自动映射不强推；无法 source-grounded 时记录
   `stock_target_mapping_missing`。

个股 metric families：

| metric_family | 用途 | 默认 agent candidates |
| --- | --- | --- |
| `stock_forward_return` | 看多/看空方向反馈 | `superinvestor.*`, `decision.cio`, sector owner |
| `stock_relative_alpha` | 相对 benchmark 的超额收益 | `superinvestor.*`, `decision.alpha_discovery` |
| `target_price_path` | 目标价命中辅助 evidence | `superinvestor.ackman`, `superinvestor.burry` |
| `earnings_growth_path` | 盈利/收入预测机制，不直接替代价格 label | sector owner, `decision.cio` |

### P0.I 行业 claim 契约

行业 claim 可评价条件：

- `target.target_type` 是 `sector`、`industry` 或可治理映射到 canonical sector。
- `metric_proxy_mapping` 包含或可映射到 `industry_etf_forward_return`。
- 行业名称必须经过 alias normalization；不能把未知行业硬映射到相邻 ETF。
- 每个行业 mapping 必须记录 proxy symbol、mapping confidence、coverage policy 和 PIT
  availability。

行业 metric families：

| metric_family | 用途 | 默认 agent candidates |
| --- | --- | --- |
| `industry_etf_forward_return` | 行业 ETF proxy 市场反馈 | sector owner, `decision.cio` |
| `industry_relative_alpha` | 相对宽基 benchmark 的行业超额 | sector owner, `decision.alpha_discovery` |
| `industry_cycle_regime` | 需求/库存/价格/政策 cycle 背景 | sector owner |
| `industry_policy_catalyst` | 政策或监管催化，不直接替代市场 label | sector owner, `macro.china` when applicable |

没有高质量 ETF proxy 的行业必须记录 `sector_etf_mapping_missing` 或
`industry_proxy_low_confidence`，不能为了覆盖率强行映射。

### P0.M1 宏观 parent claim 与 claim legs

保留现有 forecast claim 作为 parent claim，但宏观研报中只要出现多个可评价资产或宏观变量，
必须拆出 claim legs。

新增逻辑概念 `macro_claim_leg`：

```text
parent_forecast_claim_id
macro_claim_leg_id
leg_index
target_type
target_id
target_label
metric_family
metric_proxy
direction
quote_convention
orientation_rule
claim_horizon
evaluation_windows
source_grounding_status
target_agent_candidates
```

例子：

```text
parent claim:
  美联储转向更高更久，压制美股和黄金，推升美债收益率与美元。

claim legs:
  US_EQUITY_SP500, equity_index_forward_return, negative
  US_10Y_YIELD, bond_yield_level, positive, unit=bps
  DXY or USDCNY, fx_rate, positive for USD strength
  GOLD, commodity_price or gold_etf_forward_return, negative
```

parent claim 用于保留完整宏观逻辑，claim leg 用于市场反馈和评级。

### P0.M2 宏观 target type

首轮支持以下 target type：

| target_type | 用途 | outcome channel |
| --- | --- | --- |
| `macro_asset` | 权益、债券、黄金、港股、美股等资产方向 | `macro_asset_proxy` |
| `macro_series` | 利率、收益率、汇率、波动率、商品价格等直接序列 | `macro_series_directional` |
| `macro_curve` | 利差、期限利差、曲线陡峭/平坦化 | `macro_curve_directional` |
| `macro_policy_event` | 央行/财政/监管事件方向和强度 | 首轮只做 evidence/readiness，不直接打 completed label |
| `macro_regime` | 增长、通胀、流动性、美元、风险偏好 regime 判断 | 首轮只做 background trace，不直接判对错 |

不允许把 `macro_regime` 自身直接当作可交易 outcome，除非明确映射到可观察序列或资产路径。

### P0.M3 宏观 metric family

标准化 `metric_family`，避免每个 extractor 自由造词：

| metric_family | 例子 | 默认 agent |
| --- | --- | --- |
| `policy_rate_level` | Fed funds、MLF、OMO rate | `macro.central_bank` |
| `money_market_rate` | SHIBOR、DR007 proxy、SOFR | `macro.central_bank` |
| `bond_yield_level` | CN10Y、US10Y | `macro.yield_curve` |
| `yield_curve_slope` | 2s10s、3m10y、中美国债利差 | `macro.yield_curve` |
| `fx_rate` | USD/CNY、USD/CNH、DXY | `macro.dollar`, `macro.emerging_markets` |
| `equity_index_forward_return` | A 股、港股、美股、成长/价值 | `macro.china`, `macro.emerging_markets` |
| `bond_etf_forward_return` | 国债 ETF、信用债 ETF | `macro.central_bank`, `macro.yield_curve` |
| `commodity_price` | 黄金、铜、油、黑色 | `macro.commodities` |
| `volatility_index` | VIX、iVX、realized vol | `macro.volatility` |
| `risk_off_asset_path` | 黄金、美元、债券、权益回撤组合 | `macro.geopolitical`, `macro.volatility` |
| `growth_inflation_release` | PMI、CPI、PPI、GDP | `macro.china`, `macro.commodities` |

### P0.X Agent trace policy

新增或规范 `target_agent_candidates`，但不要把它当作 correctness label。

规则：

- claim leg 可以映射到多个 agents。
- agent 映射用于后续 profile、prior、evolution candidate 分发。
- agent 映射来源必须记录：`metric_family_rule`、`target_type_rule`、`source_text_hint` 或
  `manual_review_override`。
- 如果 agent 映射不确定，记录 `agent_mapping_low_confidence` readiness gap，不阻断 claim
  extraction，但阻断 agent prior 发布。

## P1：PIT 数据目录

PIT 数据目录分三层：个股价格目录、行业 ETF proxy 目录、宏观序列目录。RKE 只保存 mapping、
metadata、availability、hash 和 readiness，不复制 raw licensed observations。

### P1.S 个股 PIT 价格目录

个股 price labeler 使用 qlib `cn_data`：

```text
qlib_stock_dir
calendar_source
latest_calendar_date
stock_symbol
price_field=adjclose
volume_field
entry_tradeability_policy
delisting_policy
benchmark_symbol=SH510300
benchmark_source=cn_etf
cost_model_id=single_stock_round_trip_20bps_v1
```

必须记录 readiness gap：

- `stock_series_missing`
- `stock_calendar_missing`
- `stock_benchmark_missing`
- `stock_entry_suspended`
- `entry_limit_locked`
- `stock_long_suspension_window`
- `stock_delisted_before_exit`
- `stock_target_conflict`

### P1.I 行业 ETF proxy 目录

行业目录由 mapping registry 和 PIT availability 两部分组成：

```text
industry_name
canonical_sector
sector_aliases
proxy_symbol
proxy_name
benchmark_symbol
mapping_confidence
mapping_policy
calendar_source
latest_calendar_date
pit_available
pit_gap_reason
cost_model_id=industry_etf_round_trip_10bps_v1
```

约束：

- 优先一行业一主 ETF，避免后验挑选。
- mapping 可以由 registry 覆盖 code fallback，但必须保留 provenance。
- mapping gap 进入 readiness/evolution，不写回 prompt。
- proxy limitation 必须进入 agent prior 的 `known_failure_mode_tags` 或 `tool_gap_ids`。

### P1.M1 扩展 macro market series catalog

RKE 侧只需要一个轻量 catalog/readiness 视图来说明哪些宏观序列可用于 claim outcome。
原始时间序列采集和存储优先复用 `macro-agent-data-source-plan.md`、`mosaic/dataflows/macro_data.py`
和 scorecard store 中已有的 `macro_series` 语义。不要在 `registry/report_intelligence/` 下复制
raw macro observations。

可新增或扩展 builder：

- `build_macro_market_series_catalog()`
- `write_macro_market_series_catalog()`

目标是记录“哪些 PIT 序列可用于评价宏观 claim”，不是存储大量原始行情。

字段：

```text
series_id
series_family
source
source_endpoint
instrument
quote_convention
unit
calendar
frequency
latest_observation_date
earliest_observation_date
point_in_time_policy
license_boundary
target_agent_candidates
implementation_status
readiness_status
gap_reason
```

如果底层数据来自 Tushare、AKShare、FRED、qlib 或本地私有缓存，catalog 可以公开记录
series metadata，但不能提交 raw licensed observations。

实现约束：

- 如果已有 dataflow 能返回该序列，RKE 只调用或读取其标准输出，不重写采集器。
- 如果已有 scorecard `macro_series` 表有同一 `series_id`，RKE labeler 只读 as-of safe
  observations 和 `data_vintage_hash`。
- 如果某序列当前只存在于 agent tool 而没有持久化历史，先记录
  `source_not_pit_safe` 或 `series_history_missing`，不能为了完成 label 即时抓当前数据。

### P1.M2 宏观首轮必须接入的序列

优先级按“能解决当前限制”和“能覆盖 macro agents”排序：

| 优先级 | series family | 示例 | 解决的问题 |
| --- | --- | --- | --- |
| 1 | CN/US yield level | CN10Y、US10Y、US2Y | 直接评价利率/收益率 claim |
| 1 | FX | USD/CNY、USD/CNH、DXY proxy | 直接评价美元/人民币 claim |
| 1 | volatility | VIX、iVX、A 股 realized vol | 评价 volatility claim |
| 1 | commodity | gold、copper、crude oil、black futures proxy | 评价商品 claim |
| 2 | curve slope | US 2s10s、CN 1y10y、中美利差 | 评价曲线 steepen/flatten claim |
| 2 | China macro release | PMI、CPI、PPI、社融、信贷 | 作为 regime/evidence，不直接替代市场 feedback |
| 2 | central bank operations | OMO、MLF、RRR、policy rate | 作为 regime/evidence 和 event follow-through |
| 3 | geopolitical event proxy | oil/gold/USDCNH/risk-off basket | 作为 geopolitical agent secondary label |
| 3 | institutional flow | fund flow、northbound proxy | 暂作为后续 agent evidence |
| 3 | news sentiment | persisted news sentiment | 暂作为后续 agent evidence |

### P1.X Data source policy

首轮允许多来源，但必须每条序列记录来源和 PIT 规则：

- qlib/ETF price：用于 tradable proxy path。
- Tushare：宏观、外汇、期货、资金和债券数据，遵守 license boundary。
- AKShare：补充波动率、债券收益率、商品等公开序列；必须在 runbook 记录 endpoint。
- FRED：美国利率、美元、VIX 等公开序列；记录 vintage 或 observation as-of 规则。

任何来源如果只有当前值、没有历史 as-of 或更新时间，只能进入 evidence，不可进入 primary
outcome label。

## P2：三域 outcome labeler

所有 label 写入统一 `report_outcome_labels.jsonl`，所有 readiness 写入统一
`outcome_labeling_readiness.json`。禁止新增独立的 stock、industry 或 macro outcome 文件。

### P2.S `stock_price_proxy`

个股 outcome labeler 使用 qlib 股票价格：

- T+1 entry，禁止报告日 T+0 close。
- 固定窗口首轮使用 `5/20/60/120` trading days。
- 默认 benchmark 使用 `SH510300` ETF；stock 和 benchmark 来自不同 qlib 目录时必须按日期对齐。
- 个股 round-trip cost 使用 20 bps。
- 入场停牌、涨停锁死不可买入、退市前无法完成退出窗口时不生成 completed label，只记录 gap。

输出字段：

```text
label_type=stock_price_proxy
outcome_label_source=pit_stock_price_window
llm_outcome_labeling_allowed=false
target_stock_symbol
benchmark_symbol
entry_datetime
exit_datetime
entry_lag_trading_days=1
horizon_days
stock_return
benchmark_return
relative_alpha
after_cost_alpha
directional_after_cost_return
directional_hit
relative_directional_hit
target_resolution_source
cost_model_id
data_vintage_hash
```

目标价命中 `target_price_hit` 可以作为辅助字段，但不能替代 market window evidence。

### P2.I `industry_etf_proxy`

行业 outcome labeler 使用治理后的行业 ETF proxy：

- T+1 entry，禁止 T+0 close。
- 窗口使用 `20/60/120` trading days，保留长期 evidence。
- 行业 ETF round-trip cost 使用 10 bps。
- benchmark 默认使用 `SH510300` 或 mapping registry 指定宽基。
- mapping missing、proxy series missing、calendar missing、PIT availability missing 都进入
  readiness gap。

输出字段：

```text
label_type=industry_etf_proxy
outcome_label_source=pit_industry_etf_price_window
llm_outcome_labeling_allowed=false
canonical_sector
proxy_symbol
benchmark_symbol
mapping_confidence
entry_datetime
exit_datetime
entry_lag_trading_days=1
horizon_days
proxy_return
benchmark_return
relative_alpha
after_cost_alpha
directional_after_cost_return
directional_hit
cost_model_id
data_vintage_hash
```

行业 ETF proxy 是 governed proxy evidence，不等于行业真实组合收益；agent prior 必须保留
`proxy_or_direct=proxy` 和 mapping confidence。

### P2.M1 保留并扩展 `macro_asset_proxy`

现有 `macro_asset_proxy` 继续用于资产代理：

- A 股宽基、沪深300、创业板、港股、美股、债券 ETF、黄金 ETF。
- T+1 entry。
- 90/180/360 trading-day windows。
- `outcome_label_source=pit_macro_asset_etf_price_window`。
- `performance_value_basis=directional_after_cost_return`。

状态：已实现并接入统一 label/readiness/profile。当前已补充的 macro trace 字段包括：

- `target_agent_candidates`
- `macro_claim_leg_id`
- `series_family`
- `quote_convention=price_return`
- `mapping_confidence`
- `proxy_or_direct=proxy`

### P2.M2 已实现 `macro_series_directional`

状态：已实现 direct-series builder，并接入统一 readiness/outcome/profile 流程：

- `build_macro_series_directional_readiness()`
- `build_macro_series_directional_outcome_labels()`

适用对象：

- 利率水平。
- 收益率。
- 汇率。
- 波动率。
- 商品 spot/futures/continuous contract。
- 其他有 PIT 序列的宏观变量。

输出 label：

```text
label_type=macro_series_directional
outcome_label_source=pit_macro_series_window
llm_outcome_labeling_allowed=false
parent_forecast_claim_id
macro_claim_leg_id
target_series_id
series_family
source
quote_convention
unit
direction
orientation_rule
entry_datetime
exit_datetime
entry_lag_trading_days=1
horizon_days
entry_value
exit_value
raw_change
pct_change (optional/nullable; where applicable only; bps_change is primary for yield/rate series)
bps_change
directional_change
directional_hit
performance_value
performance_value_basis
data_vintage_hash
target_resolution_source
```

`pct_change` 是 optional/nullable 字段；yield/rate 系列以 `bps_change` 和
`performance_value_basis=directional_bps_change` 为主，不要求生成百分比变化。

这些 label 写入现有 `report_outcome_labels.jsonl`，并由现有
`build_viewpoint_performance_profiles()`、schema validation 和 evolution gate 消费。不要新增
`macro_outcome_labels.jsonl`。

`performance_value_basis` 按 series family 固定：

| series_family | performance_value_basis |
| --- | --- |
| yield/rate | `directional_bps_change` |
| fx | `directional_fx_change` |
| volatility | `directional_volatility_change` |
| commodity | `directional_price_return` |
| macro release | 首轮不生成 completed label |

### P2.M3 已实现 `macro_curve_directional`

状态：已实现 default mapping、readiness 和 outcome labeler；曲线观点不能只看单一利率。

当前代码路径：

- `MACRO_CURVE_DIRECTIONAL_MAPPING`：定义 curve target 到 long/short leg series 的映射。
- `build_default_macro_curve_directional_map_rows()`：把 mapping 变成 governed mapping rows。
- `_macro_curve_observations()`：按共同 observation date 对齐 long/short leg，计算
  `spread_value = long_leg_value - short_leg_value`。
- `build_macro_curve_directional_readiness()` / `build_macro_curve_directional_outcome_labels()`：
  生成 readiness 和 `macro_curve_directional` labels。

已实现 target：

- `US_2S10S`
- `US_3M10Y`
- `CN_US_10Y_SPREAD`

`CN_1Y10Y` 是 proposed target，需先接入 CN1Y PIT series 后再加入 mapping；当前不要在
验收状态中把它当作已实现。

字段同 `macro_series_directional`，但增加：

```text
long_leg_series_id
short_leg_series_id
entry_spread_bps
exit_spread_bps
spread_change_bps
curve_direction
```

构造规则：

- 所有已实现 curve 都是 `long_leg - short_leg`。
- `US_2S10S = US10Y - US2Y`。
- `US_3M10Y = US10Y - US3M`。
- `CN_US_10Y_SPREAD = CN10Y - US10Y`。
- 频率使用 source macro_series 的共同 observation date；entry/exit 使用 aligned observations，
  不做 rolling average。
- entry 使用 signal date 后的第一个可用共同 observation，并应用
  `MACRO_CURVE_DIRECTIONAL_ENTRY_LAG_OBSERVATIONS=1`。
- mapping row 的 raw leg unit 目前是 `percent`；labeler 在输出时把 percent-unit spread
  转成 bps，写入 `entry_spread_bps`、`exit_spread_bps` 和 `spread_change_bps`。

方向约定：

- `steepen`：long-short spread 上行是 hit。
- `flatten`：long-short spread 下行是 hit。
- `invert_deepen`：倒挂加深需要显式 quote convention。

### P2.X Pending 与 blocked

不满足条件时不生成 completed label，而是进入 readiness：

- `series_mapping_missing`
- `quote_convention_missing`
- `direction_missing_or_unsupported`
- `entry_value_missing`
- `exit_value_missing`
- `exit_after_latest_observation`
- `calendar_missing`
- `source_not_pit_safe`
- `direct_series_required_proxy_not_allowed`
- `agent_mapping_low_confidence`
- `agent_assignment_missing`
- `multi_asset_leg_parse_missing`

## P3：三域 claim 抽取增强

三域抽取都必须按全文上下文执行，不按单句截取。抽取输出必须区分：

- forecast claim：未来方向、目标、期限、机制。
- factual/current observation：当前事实，只能作为 mechanism/background。
- risk disclosure：风险提示，不自动变成反向 forecast。
- method/tool request：进入 recipe/tool-gap，不直接进入 outcome label。

### P3.S 个股抽取

个股研报抽取必须识别：

- covered company、`ts_code`、报告评级、目标价和评级期限。
- source-grounded 的公司基本面机制：收入、利润、订单、产能、产品价格、成本、资本开支、
  现金流、估值、分红/回购、资产负债表。
- benchmark 或相对收益语义；没有 benchmark 时仍可用默认 benchmark，但要记录来源。
- 风险条件：业绩不及预期、价格下行、政策变化、订单延迟、竞争加剧等。

禁止：

- 仅因报告类型是个股研报就把所有行业性句子变成 stock forecast。
- `metadata.ts_code` 与原文公司不一致时静默使用 metadata。
- 把“建议关注公司”当成明确看多，除非上下文有方向和理由。

### P3.I 行业抽取

行业研报抽取必须识别：

- canonical sector、行业链位置、上游/中游/下游、关键 ETF proxy mapping。
- 行业景气方向：需求、供给、库存、价格、产能利用率、订单、政策、补贴、资本开支。
- 行业收益方向：行业 ETF/指数相对表现、龙头公司 basket、产业链子板块。
- proxy limitation：行业过宽、ETF 成分偏离、行业无高质量 ETF proxy。

禁止：

- 把行业观点直接映射成单一股票 outcome，除非 report 明确给出 company target。
- 把 unknown sector 强行映射到相邻 ETF；必须进入 `sector_etf_mapping_missing`。
- 把政策事实本身当成行业收益方向，除非原文给出可评价方向。

### P3.M1 宏观 full-report extraction

宏观研报必须继续按全文上下文抽取，不按单句截取。

抽取时必须识别：

- 宏观 regime：增长、通胀、政策、美元、流动性、风险偏好。
- 传导机制：利率、汇率、信用、估值、盈利、风险溢价、商品供需。
- 资产或序列 target：权益、债券、收益率、汇率、商品、波动率。
- 方向：上行、下行、走强、走弱、利差扩大/收窄、曲线陡峭/平坦。
- 期限：原文 claim horizon 或 report-level/section-level horizon。
- 失败条件：哪些宏观假设变化会使 claim 失效。

### P3.M2 宏观多资产 claim legs

抽取 prompt 和 parser 要求：

- 每个 parent macro claim 最多拆出 6 个首要 legs，避免一篇报告生成几十个重复标签。
- 每个 leg 必须有明确 target、metric_family、direction。
- parent claim 保留完整机制链。
- leg claim 可以复用 parent 的机制链，但不能凭空增加原文未支持的 asset。
- leg 没有明确方向时进入 `leg_direction_missing`，不能纳入 outcome。

### P3.X Horizon extraction

继续沿用当前 horizon 优先级：

1. claim text explicit horizon。
2. section heading or nearby section context。
3. report title, abstract, or core-view temporal context。
4. rating definition or report-level investment-horizon definition。
5. report type default, low confidence。

新增约束：

- 宏观 comment/report 中“数据点评后市场当日反应”不能自动变成未来预测。
- “短期”“中期”“年内”“未来一段时间”必须映射成 confidence-bearing bucket。
- 如果原文只有当前事实，没有未来方向，不生成 forecast leg。

## P4：PIT context snapshot

三域都需要 PIT context，但用途不同：它只能用于 outcome 后分层评价、agent prior 背景和
evolution candidate 归因，不能用于抽取阶段判断 claim 对错。

### P4.S 个股 context snapshot

状态：builder/schema/write path 已落地；clean private validation corpus 当前生成 74 条
`stock_context_snapshots.jsonl` rows。agent context 在 snapshot 存在时输出
`context_snapshot_status=available`，缺失时仍保留降级 contract。

实施规模：M。它不是条件 11 的前置 blocker；若私有 snapshot artifact 缺失，agent prior 仍可从
`stock_price_proxy` outcome/readiness/profile 和 generic RKE research context 降级读取，但必须输出
`stock_context_snapshot_missing` 或等价 no-prior reason，不能伪造 market-cap/liquidity 背景。
当前 `build_rke_agent_research_context_from_rows()` 已支持 stock snapshot 可选输入，并在缺失时输出
`context_snapshot_status=missing` 和 `stock_context_snapshot_missing` ranking reason。

已新增 builder：

- `build_stock_context_snapshots(...)`
- `write_stock_context_snapshots(root=...)`

schema 依赖：

- 新增 `schemas/report_intelligence_stock_context_snapshot.schema.json`。
- schema 必须声明 `background_only=true`、`claim_validation_allowed=false`，并禁止 raw price、
  claim text、source span。

数据源：

- `stock_price_proxy` outcome/readiness rows。
- stock qlib/PIT metadata：market cap bucket、liquidity bucket、tradeability gap、退市/停牌标记。
- report metadata 中的 ts_code/sector 只用于 join key 和分层，不公开报告 title/abstract。

个股 context snapshot 是 redacted 派生背景，不包含价格原始序列或研报原文：

```text
snapshot_id
as_of_date
stock_symbol
sector
market_cap_bucket
liquidity_bucket
stock_outcome_age_bucket
benchmark_family
missing_feature_reasons
background_only=true
claim_validation_allowed=false
```

用途：

- superinvestor/decision agents 了解历史 stock prior 的适用背景。
- profile 按 sector、liquidity、market cap bucket 分层。
- 识别 survivorship、停牌、退市、流动性不足造成的 failure mode。

### P4.I 行业 context snapshot

状态：builder/schema/write path 已落地；clean private validation corpus 当前生成 58 条
`industry_context_snapshots.jsonl` rows。agent context 在 snapshot 存在时输出
`context_snapshot_status=available`，缺失时仍保留 proxy 降级 contract。

实施规模：M。它不是条件 11 的前置 blocker；若私有 snapshot artifact 缺失，sector/decision agents 仍可从
industry ETF proxy outcome/readiness/profile 降级读取，但必须保留 `industry_context_snapshot_missing`
和 proxy limitation，不得把 broad ETF proxy 当作直接行业组合收益。
当前 `build_rke_agent_research_context_from_rows()` 已支持 industry snapshot 可选输入，并在缺失时输出
`context_snapshot_status=missing` 和 `industry_context_snapshot_missing` ranking reason。

已新增 builder：

- `build_industry_context_snapshots(...)`
- `write_industry_context_snapshots(root=...)`

schema 依赖：

- 新增 `schemas/report_intelligence_industry_context_snapshot.schema.json`。
- schema 必须声明 `background_only=true`、`claim_validation_allowed=false`，并禁止 ETF raw price、
  constituent raw detail、claim text、source span。

数据源：

- `industry_etf_proxy_map` governed registry。
- industry ETF proxy outcome/readiness rows。
- canonical sector mapping、proxy liquidity bucket、mapping confidence、known proxy limitation。

行业 context snapshot 同样只保留 redacted 派生信息：

```text
snapshot_id
as_of_date
canonical_sector
industry_cycle_bucket
proxy_symbol
mapping_confidence
proxy_liquidity_bucket
benchmark_family
known_proxy_limitations
missing_feature_reasons
background_only=true
claim_validation_allowed=false
```

用途：

- sector agents 了解行业 prior 的 proxy 质量和 cycle 背景。
- profile 按 sector/cycle/proxy confidence 分层。
- evolution 根据 mapping gap 和 proxy limitation 产生 mapping rule candidate。

### P4.M0 Regime calendar 与 snapshot 边界

本计划有两个不同的 PIT regime artifact，不能混用：

1. `macro_regime_calendar.jsonl`：上游治理型 PIT regime 日历。它按日期区间记录
   `regime_id`、`regime_type`、`start_date`、`end_date`、`source`、`pit_available`、
   `policy` 和 `version`，用于在抽取/角色识别阶段按 `as_of_datetime` 补充
   `claim_regime_trace` 的背景 regime。它不是 per-agent snapshot，也不能作为 claim
   correctness evidence。
2. `macro_regime_snapshots.jsonl`：下游 per-agent/as-of derived snapshot。它把
   `claim_regime_trace`、macro series 状态和 agent profile 语义整理成 agent-readable
   背景，用于 profile 分层、prior 解释和 evolution candidate 归因。

关系：

- calendar 是 `claim_regime_trace` 的 PIT 背景输入；snapshot 是后验聚合视图。
- snapshot 可以引用 calendar 生成的 `regime_detail_ids`、`regime_types` 或相关
  `source_series_ids`，但不能复制 source prose 或把 calendar source 当作原文证据。
- calendar 缺失时，snapshot 只能记录 `missing_feature_reasons` 或 deferred gap，不能补造
  regime type。
- `schemas/report_intelligence_macro_regime_calendar.schema.json` 只约束 calendar governance
  rows；`schemas/report_intelligence_macro_regime_snapshot.schema.json` 约束 per-agent snapshot
  rows。

### P4.M1 宏观 snapshot 目标

`claim_regime_trace` 目前记录 claim as-of date 的 regime 背景。下一步要把它做成更稳定、
可审计、可供 profile 和 agents 读取的 PIT snapshot。

新增 builder：

- `build_macro_regime_snapshots()`
- `write_macro_regime_snapshots()`

### P4.M2 宏观 snapshot 字段

```text
snapshot_id
as_of_date
agent_id
regime_family
regime_bucket
regime_features
feature_units
source_series_ids
data_vintage_hash
missing_feature_reasons
background_only=true
claim_validation_allowed=false
```

### P4.M3 宏观 agent 覆盖

首轮必须覆盖：

| agent | snapshot 内容 |
| --- | --- |
| `macro.central_bank` | policy rate、OMO/MLF、money market rate、liquidity bucket |
| `macro.china` | PMI/CPI/PPI/credit/property/policy support bucket |
| `macro.commodities` | gold/oil/copper/industrial basket trend |
| `macro.dollar` | USD/CNY、DXY proxy、中美利差 |
| `macro.emerging_markets` | HK/EM proxy、USDCNH、risk appetite |
| `macro.geopolitical` | risk-off asset basket、oil/gold shock proxy |
| `macro.volatility` | realized vol、VIX/iVX、drawdown state |
| `macro.yield_curve` | CN/US yields、curve slope、term spread |

`macro.news_sentiment` 和 `macro.institutional_flow` 首轮可以只记录
`snapshot_status=deferred`, 因为它们需要持久化语料和资金流历史后才能 PIT-safe 使用。

### P4.X 使用边界

regime snapshot 只能用于：

- outcome 后分层评价。
- agent prior 解释背景。
- evolution candidate 归因。

不能用于：

- 抽取阶段判断 claim 对错。
- 人工 review 阶段替代原文证据。
- 直接覆盖 claim direction。

## P5：三域观点评级

### P5.1 Rating 对象

评级优先扩展现有 viewpoint/source/method performance profile，不新建平行评分系统。需要额外对象时，
只增加 profile 的 domain-specific derived 字段或私有中间表。

三域 rating 对象：

1. `stock_claim_rating`：单个 stock claim 在每个 window 的 after-cost return/alpha feedback。
2. `industry_claim_rating`：单个 industry claim 在 ETF proxy window 的 proxy return/alpha feedback。
3. `macro_claim_leg_rating`：单个 macro leg 在每个 window 的市场反馈。
4. `macro_parent_claim_rating`：parent macro claim 下多个 legs 的聚合结果。
5. `viewpoint_cluster_rating`：相似观点在不同报告、不同 target、不同 regime 下的历史表现。

### P5.1S 个股 rating

个股 rating 必须至少记录：

```text
stock_return
benchmark_return
relative_alpha
after_cost_alpha
directional_after_cost_return
directional_hit
relative_directional_hit
target_price_hit
stock_tradeability_gap
benchmark_family
cost_model_id
```

rating bucket：

- 看多：after-cost alpha > 0 或 directional return > 0 才能成为 supportive evidence。
- 看空：方向反转后计算 directional metrics。
- 目标价命中只能增强 evidence，不能覆盖窗口收益。
- 停牌/退市/涨跌停不可交易的 claim 进入 blocked/pending，不伪造成 hit/miss。

实现路径：

- 首轮不新增公开 `stock_claim_ratings.jsonl`。`stock_claim_rating` 是 row-level logical rating，
  由现有 `stock_price_proxy` outcome rows、readiness gaps 和 cost/benchmark fields 计算后进入
  `build_viewpoint_performance_profiles()` 的 domain-specific profile 分层。
- 如果需要显式中间层，新增内部 helper `build_domain_claim_ratings(..., domain="stock")`，
  只生成内存对象或私有中间表；它不得包含 claim text、source span 或 raw price series。
- `target_price_hit` 只作为 auxiliary evidence 输出到 profile/reason code，不能单独把 claim
  提升为 `supportive_evidence`。

个股 profile 聚合必须分层：

```text
stock_sector
market_cap_bucket
liquidity_bucket
benchmark_family
cost_model_id
holding_window_bucket
fundamental_metric_family
source_viewpoint_cluster
```

个股 known failure mode tags：

- `stock_target_conflict`
- `company_subject_ambiguous`
- `metadata_subject_mismatch`
- `entry_tradeability_blocked`
- `delisting_or_long_suspension`
- `benchmark_alignment_gap`
- `target_price_only_without_return_support`
- `fundamental_claim_without_price_followthrough`

给 investment agents 的 rating 输出不能只说“历史命中率”。必须同时给：

- `n_effective` 和 reliability bucket。
- return/alpha 的方向和区间 bucket。
- tradeability/data-quality blocker share。
- 是否需要 current fundamentals、price、valuation、balance-sheet 或 catalyst data 再确认。

### P5.1I 行业 rating

行业 rating 必须至少记录：

```text
proxy_return
benchmark_return
relative_alpha
after_cost_alpha
directional_after_cost_return
directional_hit
mapping_confidence
proxy_liquidity_bucket
proxy_or_direct=proxy
cost_model_id
```

rating bucket：

- proxy mapping confidence 低时只能输出 provisional 或 blocked_mapping。
- 行业 ETF 成分偏离严重时，known failure mode 必须进入 prior。
- 行业 claim 与宏观 policy/regime 混合时，行业 label 只评价行业收益方向，宏观机制进入
  regime/context 分层。

实现路径：

- 首轮不新增公开 `industry_claim_ratings.jsonl`。`industry_claim_rating` 是 row-level logical
  rating，由现有 `industry_etf_proxy` outcome rows、readiness gaps、mapping confidence 和
  proxy limitation 计算后进入 `build_viewpoint_performance_profiles()` 的 domain-specific profile
  分层。
- 如果需要显式中间层，复用内部 helper `build_domain_claim_ratings(..., domain="industry")`，
  只生成内存对象或私有中间表；它不得包含 claim text、source span、ETF raw price series 或成分明细。
- ETF proxy 的 supportive/contradictory 只能描述 proxy evidence，不能自动外推为全行业真实收益。

行业 profile 聚合必须分层：

```text
canonical_sector
sector_agent_id
industry_cycle_bucket
proxy_symbol
mapping_confidence_bucket
proxy_liquidity_bucket
benchmark_family
cost_model_id
holding_window_bucket
```

行业 known failure mode tags：

- `sector_etf_mapping_missing`
- `industry_proxy_low_confidence`
- `proxy_constituent_mismatch`
- `proxy_liquidity_insufficient`
- `sector_alias_ambiguous`
- `policy_catalyst_without_return_followthrough`
- `cycle_claim_without_price_confirmation`
- `subsector_view_lost_in_broad_etf_proxy`

给 sector agents 的 rating 输出必须保留 proxy 局限性：ETF proxy supportive 不等于全行业基本面
改善；ETF proxy contradictory 也不等于所有子行业观点错误。

### P5.2 Rating 状态

每个 rating 必须有状态，不允许只有分数：

| status | 含义 |
| --- | --- |
| `completed` | PIT exit 已到期且数据完整 |
| `pending_window` | exit 还在未来 |
| `blocked_mapping` | target/series/agent 映射缺失 |
| `blocked_assignment` | target_type、target_id 和 metric_family 已清洗，但没有明确 owning agent；必须关联 `agent_assignment_missing` 或 `owner_agent_missing` readiness gap |
| `blocked_data` | PIT 数据缺失或非 PIT-safe |
| `blocked_quality` | claim 质量不满足可评价条件；必须关联 readiness gap，例如 `direction_missing_or_unsupported`、`claim_horizon_missing`、`multi_asset_leg_parse_missing` 或 `source_grounding_insufficient` |
| `insufficient_sample` | 能评价但样本太少，不给稳定结论 |

### P5.3 Rating 指标

三域通用：

```text
domain
label_type
target_family
target_id_redacted
directional_hit
performance_value
performance_value_basis
window_horizon_days
mapping_confidence
data_quality_bucket
benchmark_family
cost_model_id
```

macro leg-level：

```text
directional_hit
performance_value
performance_value_basis
window_horizon_days
series_family
mapping_confidence
data_quality_bucket
```

parent-level：

```text
leg_count
completed_leg_count
weighted_hit_rate
weighted_performance_value
cross_asset_consistency
failed_leg_reasons
rating_status
```

viewpoint-level：

```text
n_nominal
n_effective
shrunk_hit_rate
shrunk_performance_value
regime_conditioned_performance
agent_conditioned_performance
known_failure_modes
statistical_reliability_bucket
```

`cross_asset_consistency` 必须有明确计算口径：

- 只在 parent claim 至少有两个 completed or pending-mappable legs 时计算；否则为
  `not_applicable`。
- 先把每个 leg 归一到经济方向，例如 `yield_up/down`、`bond_price_up/down`、
  `fx_quote_up/down`、`equity_price_up/down`、`commodity_price_up/down`。
- hard-incompatible 关系必须显式编码，例如同一债券久期上“债券价格上行”与“收益率上行”
  同时作为同一方向观点，除非 parent claim 明确区分信用利差、期限利差或交易结构。
- 结果 bucket 为 `consistent`、`mixed`、`contradictory`、`blocked_mapping` 或
  `not_applicable`。存在 hard-incompatible pair 且冲突 legs 占 parent completed leg weight
  不低于 50% 时为 `contradictory`；冲突不足 50% 或只触发 soft relation 时为 `mixed`。
- `directional_hit` 仍由 leg-level market outcome 决定；`cross_asset_consistency` 只评价
  parent 多资产逻辑是否自洽，不能替代 leg outcome。

### P5.4 评级口径

建议首轮不输出“买入/卖出式”评级，而输出审计型 rating：

| rating_bucket | 条件 |
| --- | --- |
| `supportive_evidence` | 方向命中且 performance_value 为正，样本未被 robustness gate 阻断 |
| `mixed_evidence` | 不同 windows 或 legs 明显分歧 |
| `contradictory_evidence` | 主要 windows/legs 与 claim 方向相反 |
| `pending_or_unrated` | 未到期、缺数据或样本不足 |

原因：宏观研报观点通常是多资产、多机制、多期限，不适合过早压缩成单一绝对分数。

## P6：Agent 可消费研究先验

### P6.1 三域 redacted agent prior

优先复用 `weighted_research_contexts.jsonl` 和 `mosaic/rke/agent_research_context.py` 的
allowlisted context；domain-specific export 只作为 compatibility view。新增/扩展 artifact 时，
必须默认本地私有：

- `registry/report_intelligence/macro_agent_research_priors.jsonl`
- 后续如需 stock/industry 专用 view，命名为 compatibility export，不新增 raw claim 文件。

如果该文件包含 claim 原文、source span、报告标题摘要或 licensed raw values，则必须列入
private local registry。首轮建议只输出 redacted derived summary，使其可公开验证 schema。

实现时先检查现有 `weighted_research_contexts.jsonl` 和运行时
`research_prior_not_current_data` 消费路径是否足够。如果能承载 agent prior，则
`macro_agent_research_priors.jsonl` 只作为 redacted export 或 compatibility view；不要让下游
agents 同时读取两套含义重复的 research prior。

三域通用字段：

```text
prior_id
domain
agent_id
as_of_date
viewpoint_cluster_id
claim_ids_redacted
target_type
target_id_redacted
metric_family
expected_direction
regime_bucket
rating_bucket
shrunk_hit_rate
shrunk_performance_value
statistical_reliability_bucket
n_effective
latest_completed_exit_date
freshness_bucket
known_failure_mode_tags
tool_gap_ids
recipe_ids
current_data_required=true
actionability_guard=no_trade_without_current_data_confirmation
use_policy=shadow_research_prior_only
source_policy=no_source_prose
```

stock-specific prior fields：

```text
stock_symbol_redacted
sector
benchmark_family
stock_outcome_age_bucket
tradeability_failure_tags
fundamental_metric_family
valuation_bucket
balance_sheet_risk_bucket
catalyst_type_tags
current_data_required_fields
```

industry-specific prior fields：

```text
canonical_sector
proxy_symbol
mapping_confidence
proxy_liquidity_bucket
industry_cycle_bucket
proxy_limitation_tags
subsector_tags
cycle_driver_tags
policy_driver_tags
current_data_required_fields
```

macro-specific prior fields：

```text
macro_claim_leg_ids_redacted
target_series_family
regime_types
quote_convention
cross_asset_consistency
```

### P6.2 Agent 使用方式

下游 agents 只能把 prior 当作研究背景：

- macro agents 可以引用“历史上类似宏观观点在某 regime 下表现较好/较差”。
- sector agents 可以引用行业观点历史 proxy 表现、mapping limitation 和 cycle 背景。
- superinvestor agents 可以引用个股观点历史 outcome、known failure mode 和 recipe/tool gap。
- decision agents 可以引用跨层 prior quality、冲突 prior 和 no-prior reason。
- 可以调整 reasoning 中的信息权重。
- 不能直接变成交易信号。
- 不能绕过 agent 自己的数据工具。
- 不能读取原始 claim text 或研报 source span。

三域 prior 分发矩阵：

| prior domain | primary agents | secondary agents | 不可做的事 |
| --- | --- | --- | --- |
| stock | `superinvestor.*`, `decision.cio`, `decision.alpha_discovery` | sector owner, `sector.relationship_mapper` | 不能替代当前财务、估值、价格和风险检查 |
| industry | sector owner, `decision.cio`, `decision.alpha_discovery` | `macro.china`, `sector.relationship_mapper` | 不能把 ETF proxy 当作真实行业组合或子行业结论 |
| macro | `macro.*`, `decision.cio` | sector agents, superinvestors when macro prior affects sector/stock thesis | 不能替代当前宏观数据、市场价格和 agent 工具确认 |

每个 delivered prior 必须带：

```text
domain
agent_id
priority_bucket
ranking_reason_codes
rating_bucket
reliability_bucket
n_effective
known_failure_mode_tags
current_data_required_fields
actionability_guard
```

### P6.2S 个股 prior 给投资 agents 的使用契约

superinvestor 和 decision agents 使用 stock prior 时，必须按角色过滤：

| agent | stock prior 用法 | 必须再确认的 current data |
| --- | --- | --- |
| `superinvestor.munger` | 找到历史上“质量/护城河/现金流”类观点的成功或失败模式 | ROIC/ROE、毛利率、FCF、负债、估值、业务可预测性 |
| `superinvestor.burry` | 找到历史上“低估/逆向/资产负债表/catalyst”类观点的失败和反转路径 | EV/EBIT、FCF yield、净现金/债务、回购/资产处置、下行风险 |
| `superinvestor.ackman` | 找到优质资产、定价权、治理/资本配置 catalyst 的历史表现 | FCF、定价权、管理层行动、资本配置、估值 |
| `superinvestor.druckenmiller` | 找到景气/趋势/政策/价格动量类 stock prior 的时效和失效模式 | 价格趋势、盈利修正、政策/流动性、风险收益比 |
| `decision.cio` | 汇总 stock prior 与当前 portfolio/risk/position context 的冲突 | 当前价格、风险预算、流动性、已有持仓、行业拥挤度 |
| `decision.alpha_discovery` | 发现被 superinvestors 忽略但 RKE 历史 pattern 支持的候选 | 当前基本面、价格、催化、风险和 prior conflict |

stock prior 必须输出 `current_data_required_fields`，例如：

```text
current_price
valuation_metrics
fundamental_growth
balance_sheet
liquidity
catalyst_status
risk_flags
```

如果这些 current data 没有被 agent 工具确认，prior 只能出现在 reasoning 背景，不得支撑最终
position sizing、buy/sell/short 结论。

### P6.2I 行业 prior 给 sector agents 的使用契约

sector agents 使用 industry prior 时，必须按 sector ownership 过滤，并保留 proxy limitation：

| agent | industry prior 用法 | 必须再确认的 current data |
| --- | --- | --- |
| `sector.semiconductor` | 产业链景气、库存/价格/资本开支、AI/算力/电子相关子行业 prior | 当期订单、库存、价格、capex、出口/政策限制 |
| `sector.consumer` | 消费、纺服、教育、包装造纸等需求和价格 prior | 零售/渠道、价格、库存、政策、品牌/渠道变化 |
| `sector.energy` | 油气、煤炭、电力、公用事业 prior | 商品价格、供需、库存、政策、电价/成本 |
| `sector.industrials` | 机械、汽车、材料、有色、稀土、新材料等周期 prior | 订单、产能、价格、政策、库存、出口 |
| `sector.financials` | 银行、券商、保险、非银 prior | 利率、信用、市场成交、资产质量、监管 |
| `sector.biotech` | 医药、器械、创新药 prior | 审批、临床、销售、医保、竞争格局 |
| `sector.relationship_mapper` | 识别行业 prior 对上下游公司和跨行业传导的影响 | 当前供应链、客户/供应商暴露、价格传导 |

industry prior 必须输出：

```text
canonical_sector
subsector_tags
proxy_symbol
mapping_confidence
proxy_limitation_tags
current_data_required_fields
```

sector agent 不得把低 confidence ETF proxy 结果当成行业确定性结论；必须在 reasoning 中说明
proxy 与真实行业/子行业之间的偏差。

### P6.3 Agent prior 排序与截断策略

当前 `weighted_research_contexts.jsonl` 已经计算 `source_weight_multiplier`、
`viewpoint_weight_multiplier` 和 `combined_research_prior_weight`，但 agent-facing context
仍按 forecast 输入顺序过滤后截断。后续必须增加独立的 retrieval ranking policy，避免 RKE
加权结果只停留在 artifact 字段里。

排序只在以下前置过滤之后执行：

- `agent_id` / layer / sector / ticker / macro target 匹配。
- `as_of_date` 和 PIT 可见性过滤。
- private/source prose 字段剔除。
- `research_only=true`、`current_data_required=true`、`production_signal_allowed=false`。

建议稳定排序键：

```text
agent_target_specificity_bucket
performance_context_match_rank
combined_research_prior_weight desc
statistical_reliability_bucket_rank
n_effective desc
freshness_bucket_rank
latest_completed_exit_date desc
original_input_index asc
```

其中：

- `performance_context_match_rank` 优先级为
  `source_and_viewpoint_profile_match` > `viewpoint_profile_match` / `source_profile_match` >
  `insufficient_data`。
- `combined_research_prior_weight` 只能影响展示和 prompt context 优先级，不能直接变成交易信号。
- 低权重或 contradictory prior 必须保留可审计 footprint：可以进入靠后位置或单独的
  `downweighted_prior_sample`，但不能因为权重低而从 RKE 体系消失。
- 排序输出可以新增 redacted/local-safe 字段，例如 `retrieval_rank`、`priority_bucket`、
  `ranking_policy_id` 和 `ranking_reason_codes`；不得包含 claim text、source span、报告标题摘要或
  licensed raw values。

该排序策略是 autoresearch 和 Darwinian weight 使用 RKE 信息的前置条件：prompt mutation
评估时要能区分“agent 是否正确使用了高 priority prior”和“agent 是否忽略/误用了 downweighted
failure-mode prior”。

### P6.4 CLI/API

通用三域 agent context CLI：

```bash
mosaic-rke export-rke-agent-context \
  --root . \
  --as-of-date <YYYY-MM-DD> \
  --agent-id decision.cio \
  --max-items 12
```

macro compatibility CLI：

```bash
mosaic-rke export-macro-agent-priors \
  --root . \
  --as-of-date <YYYY-MM-DD> \
  --agent-id macro.central_bank \
  --no-source-prose
```

TS bridge 已接入同一 redacted builder：

```text
rke.agentResearchContext
rke.macroAgentPriors  # compatibility view
```

bridge 只返回 redacted prior/context，不返回私有 forecast claims。

## P7：三域演化闭环

### P7.1 Evolution 输入

三域演化输入：

- stock claim ratings。
- industry claim ratings。
- macro claim leg ratings。
- viewpoint cluster ratings。
- mapping/readiness gaps。
- PIT regime-conditioned performance。
- human gold-set review。
- extraction quality failure。
- agent prior consumption audit。
- tool/data gap coverage。

stock-specific evolution signals：

- target resolution conflicts by broker/source/report type。
- stock tradeability blockers by market cap/liquidity/sector。
- fundamental metric claims that repeatedly fail price follow-through。
- target-price-only claims with weak forward return evidence。
- superinvestor agents ignoring high-priority supportive/contradictory stock prior。
- current-data confirmation missing after stock prior was surfaced.

industry-specific evolution signals：

- recurring `sector_etf_mapping_missing` aliases。
- low-confidence ETF mappings that create noisy or contradictory labels。
- subsector claims lost in broad ETF proxy。
- industry cycle claims whose proxy return does not follow through.
- sector agents ignoring proxy limitation or using industry prior as current data。
- current sector data/tool gaps needed to validate prior.

### P7.2 Evolution 输出

演化输出不是直接改 prompt，而是候选项：

- stock target resolution rule candidate。
- stock tradeability/data-quality rule candidate。
- stock fundamental metric extraction candidate。
- stock prior-to-superinvestor routing candidate。
- stock current-data requirement candidate。
- industry ETF mapping rule candidate。
- industry proxy limitation rule candidate。
- industry alias/canonical sector rule candidate。
- industry cycle feature candidate。
- industry prior-to-sector-agent routing candidate。
- macro extraction prompt mutation candidate。
- macro target/series mapping rule candidate。
- quote convention rule candidate。
- horizon extraction rule candidate。
- agent tool requirement candidate。
- macro regime feature addition candidate。
- research prior weighting candidate。
- prior retrieval ranking candidate。
- all-agent prompt mutation candidate：macro、sector、superinvestor、decision 全部 prompt
  内容候选必须写入 private prompt repo；public repo 只记录候选 id、hash、评测结果和 runtime
  引用。候选来源可以是 RKE prior usage、agent claim outcome、tool-gap handling 或
  failure-mode handling。

候选项要进入现有 evolution readiness/report-intelligence action 体系；除非现有 gate schema
无法表达 domain 子检查，否则不新增第二个 evolution gate 文件。

candidate refusal reasons：

```text
insufficient_effective_n
missing_pit_outcome
mapping_confidence_too_low
proxy_limitation_too_high
target_resolution_conflict
tradeability_gap_dominates
current_data_requirement_unmet
source_dependent_cluster
claim_quality_blocked
private_text_required_to_validate
```

stock/industry 候选进入 private prompt repo 前，必须先通过 deterministic comparison：

- old vs new extraction/routing/ranking rule 在固定 fixture 和真实 redacted sample 上的差异。
- outcome/readiness/gap 分布是否改善。
- prompt mutation 是否减少 false positives，而不是只增加召回。
- no-source-prose/privacy audit 是否通过。

### P7.3 Gate

已实现的 `evolution_readiness_gate` 宏观分支：

```text
RI-MACRO-01 macro_claim_leg_contract
RI-MACRO-02 macro_series_pit_label_coverage
RI-MACRO-03 macro_regime_snapshot_background_only
RI-MACRO-04 macro_rating_profile_reliability
RI-MACRO-05 macro_agent_prior_privacy
RI-MACRO-06 macro_agent_prior_shadow_only
RI-MACRO-07 macro_evolution_candidate_audit
```

已实现的 stock/industry gate 分支；当前 stock/industry outcome、mapping、
PIT/provenance/privacy evidence 继续进入通用 RI-EVOL 检查和现有 readiness/profile/audit，
并已具备独立 RI-STOCK / RI-INDUSTRY check IDs：

```text
RI-STOCK-01 stock_target_resolution_contract
RI-STOCK-02 stock_pit_label_coverage
RI-STOCK-03 stock_tradeability_gap_audit
RI-STOCK-04 stock_prior_privacy_and_shadow_only
RI-INDUSTRY-01 industry_etf_mapping_contract
RI-INDUSTRY-02 industry_proxy_pit_label_coverage
RI-INDUSTRY-03 industry_proxy_limitation_audit
RI-INDUSTRY-04 industry_prior_privacy_and_shadow_only
```

任何一项 blocker 存在时，不能把 prior 或 prompt mutation 提升到生产。

## P8：Schema、manifest 和隐私边界

需要新增或更新：

- `schemas/report_intelligence_report_outcome_label.schema.json`
- `schemas/report_intelligence_outcome_labeling_readiness.schema.json`
- `schemas/report_intelligence_forecast_claim.schema.json`
- `schemas/report_intelligence_industry_etf_proxy_map.schema.json`
- `schemas/report_intelligence_industry_etf_proxy_pit_availability.schema.json`
- `schemas/report_intelligence_macro_market_series_catalog.schema.json`
- `schemas/report_intelligence_macro_regime_snapshot.schema.json`
- `schemas/report_intelligence_macro_regime_calendar.schema.json`
- `schemas/report_intelligence_macro_agent_research_prior.schema.json`
- `mosaic/rke/registry_manifest.py`
- `mosaic/rke/report_intelligence.py` 的 private path 常量。

隐私规则：

- `forecast_claims.jsonl` 继续 private。
- `report_outcome_labels.jsonl` 继续 private，因为可能包含 target/source provenance 和 claim ids。
- `industry_etf_proxy_map.jsonl` 可以是 governed mapping metadata，但不得包含 report prose；
  mapping review notes 如含人工解释或私有路径则保持 private。
- `industry_etf_proxy_pit_availability.json` 只可包含 public-safe availability aggregate，不提交
  raw prices。
- `macro_regime_snapshots.jsonl` 和 `macro_agent_research_priors.jsonl` 即使只包含 coarse bucket
  或 redacted prior，也默认按本地私有 report-intelligence 派生 artifact 处理，不提交 repo。
- 如果后续确有公开 aggregate 需求，必须新建明确任务和 schema/audit，证明不含 source prose、
  claim text、source span、报告标题摘要、private path 或 licensed raw values。

schema 约束：

- `llm_outcome_labeling_allowed=false`。
- `entry_lag_trading_days >= 1`。
- stock label 必须有 `target_stock_symbol`、benchmark、cost model 和 target resolution source。
- industry label 必须有 canonical sector、proxy symbol、mapping confidence 和 cost model。
- FX 必须有 `quote_convention`。
- yield/rate 必须有 `unit=bps` 或可转换单位。
- completed label 必须有 entry/exit value。
- pending label 不能伪造 performance value。
- public redacted prior 禁止 `claim_text`、`source_span_ids`、`abstract`、`source_excerpt`。

## P9：Audit 扩展

### P9.1 PIT audit

新增检查：

- 禁止 T+0 entry。
- exit date 不能超过 series 最新 observation。
- stock label 必须按 stock calendar 决定 entry/exit；benchmark 即使来自不同 qlib dir，也按日期对齐。
- stock label 发现停牌、涨停锁死、退市或 entry/exit 缺价时必须 blocked。
- industry ETF proxy label 必须来自 governed mapping 和 PIT availability。
- industry ETF proxy 缺 mapping 或 proxy series 时必须 readiness gap，不能 fallback 到任意相邻 ETF。
- macro series label 必须使用 as-of safe series。
- yield claim 必须直接用 yield/rate series，不能静默反转 bond ETF。
- FX claim 必须记录 quote convention。
- commodity continuous contract 必须记录 roll policy。
- regime snapshot 必须 `background_only=true`。

### P9.2 Provenance audit

新增检查：

- stock target 必须可追溯到 metadata `ts_code` 或 source-grounded LLM target；冲突时 blocked。
- industry target 必须可追溯到 canonical sector/mapping row；unknown sector 不可强行映射。
- 每个 claim leg 必须能追溯 parent forecast claim。
- parent claim 必须有 source-grounded extraction。
- leg target/direction 必须来自原文或结构化 rewrite，不允许无来源补全。
- agent prior 只能引用 redacted ids 和 derived stats。

### P9.3 Statistical robustness audit

新增检查：

- stock、industry、macro 的 label_type、benchmark_family、cost_model_id 必须分层统计。
- stock 5/20/60/120 与 industry/macro windows 不能在同一 effective-N bucket 中混算。
- 多 window 不能让单 claim leg 权重超过 1。
- parent claim 多 legs 聚合必须记录 leg count 和 coverage。
- 不同 `series_family`、`label_type`、`cost_model_id`、`quote_convention` 分层统计。
- 样本不足时只能输出 `insufficient_sample`，不能输出稳定结论。

### P9.4 Privacy audit

新增检查：

- public prior 中禁止 claim 原文和 source span。
- public schema artifact 禁止 licensed raw observations。
- private outputs 必须被 gitignored。
- `git rev-list origin/main..HEAD` 不能包含个股、行业、宏观研报 PDF、Markdown、source prose
  或 private JSONL。

## P10：测试计划

### P10.1 Unit fixture

构造小型 PIT fixture：

- stock fixture：上涨股、下跌股、停牌/缺价样本、benchmark。
- industry ETF fixture：上涨行业、下跌行业、mapping missing、proxy series missing。
- yield series：一条上行、一条下行。
- FX series：USD/CNY 上行和下行。
- volatility series：VIX/iVX 上行和下行。
- commodity series：黄金、铜或原油价格。
- curve series：2s10s steepen 和 flatten。
- ETF proxy series：保留现有 macro asset proxy fixture。
- regime snapshot fixture：每个 agent 至少一个 snapshot bucket。

### P10.2 必测用例

本节是 coverage intent，不是稳定测试函数名 API。执行时按 P10.3 跑测试文件；如果单测
函数被重命名，以当前 repo 中覆盖相同行为的测试为准。

1. 个股：qlib stock price window 能生成 `stock_price_proxy` label。
2. 个股：metadata/LLM/正文公司主体冲突会阻断 label。
3. 个股：entry suspension、涨跌停锁死、退市、长停牌等可交易性 gap 会阻断或 pending。
4. 个股：benchmark 按日期对齐，不能用错窗口或缺失 benchmark。
5. 个股：future exit window 进入 pending，不伪造成 completed。
6. 行业：ETF proxy window 能生成 `industry_etf_proxy` label。
7. 行业：missing proxy series、missing benchmark、mapping effective-from gap 进入 readiness。
8. 行业：sector alias normalization 命中 governed mapping。
9. 行业：PIT audit 拒绝 T0 ETF entry。
10. 宏观：parent macro claim 能展开 direct-series / curve claim legs，并保留 parent trace。
11. 宏观：yield/rate claim 使用 direct PIT series 和 bps 口径，不反向套用 bond ETF。
12. 宏观：FX、volatility、commodity direct-series family 的 quote convention / unit 口径正确。
13. 宏观：curve claim 使用 long-short aligned observations，输出 bps spread change。
14. 宏观：asset-allocation claim 仍保留 `macro_asset_proxy` 路径，不被 direct-series 误抢。
15. 宏观：pending exit window、missing series、unsupported direction、missing quote convention
    都进入 readiness gap。
16. Regime/context：macro regime snapshot 是 background-only，不能作为 correctness label。
17. Prior：redacted macro agent prior 不含 source prose、claim text、source span 或报告标题。
18. Gate：mapping gap、unlabelable gap、calibration drift、objective threshold 和 audit-history
    blocker 能进入 evolution readiness gate。
19. Privacy：committed report-intelligence outputs 不含私有文本字段，私有 JSONL/PDF/Markdown/cache
    仍在 gitignore/private boundary 内。
20. Bridge roster：canonical Layer-3 superinvestors 可解析，移除的旧 agents 被拒绝；该覆盖
    属于 Part 2 preflight，但作为 Part 1 handoff sanity check 保留。

### P10.3 验证命令

```bash
uvx ruff@0.15.15 check mosaic tests
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp \
  uv run python -m pytest tests/test_rke_report_intelligence.py -q \
  --basetemp .mosaic/tmp/pytest-rke-ri
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp \
  uv run python -m pytest tests/test_rke_schema_artifacts.py -q \
  --basetemp .mosaic/tmp/pytest-rke-schema
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp \
  uv run python -m pytest tests/test_bridge_prompts.py -q \
  --basetemp .mosaic/tmp/pytest-bridge-prompts
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp \
  uv run python scripts/check_prompt_leaks.py
git diff --check
```

条件 11 ranking contract 落地后追加：

```bash
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp \
  uv run python -m pytest tests/test_rke_agent_research_context.py -q \
  --basetemp .mosaic/tmp/pytest-rke-agent-context
```

私有边界验证：

```bash
git check-ignore registry/report_intelligence/forecast_claims.jsonl
git check-ignore registry/report_intelligence/report_outcome_labels.jsonl
git rev-list --objects origin/main..HEAD | rg 'tushare_research_reports|report_intelligence/markdown|report_intelligence/pdfs|forecast_claims|report_outcome_labels' || true
```

## P11：实施拆解

### P11.1 阶段 A：契约和 schema

实施：

- 统一 stock/industry/macro claim domain contract。
- stock target resolution fields 和 readiness gaps。
- industry ETF proxy mapping/availability schema。
- 增加 macro claim leg 数据结构。
- 增加 macro market series catalog schema。
- 增加 macro regime snapshot schema。
- 增加 macro agent research prior schema。
- 扩展 outcome label schema。

验收：

- schema-status 通过。
- fixture 能构造 stock claim、industry claim、macro parent claim + claim legs。
- stock/industry/macro outcome labels 都进入统一 schema。
- redacted prior schema 禁止 source prose 字段；生成文件默认本地私有，不提交 public repo。

### P11.2 阶段 B：PIT outcome labeler

实施：

- stock qlib price readiness / outcome labeler。
- industry ETF proxy mapping / PIT availability / outcome labeler。
- `macro_series_directional` readiness。
- `macro_series_directional` outcome labeler。
- `macro_curve_directional` outcome labeler。
- quote convention/orientation rule。

验收：

- stock 看多/看空、benchmark 对齐、停牌/缺价/退市 gap 都有 fixture。
- industry mapping hit/missing、proxy series missing、T+1 audit 都有 fixture。
- yield、FX、volatility、commodity fixture 都能 completed。
- exit 未到期进入 pending。
- 缺 quote convention 阻断 FX label。
- yield claim 不允许 ETF 反向代理。

### P11.3 阶段 C：PIT context snapshot

实施：

- stock context snapshot：sector、liquidity、market-cap、outcome age bucket、tradeability gaps。
  状态：已实现 builder/schema/write path；clean private validation corpus 当前生成 74 条 rows。新增
  `build_stock_context_snapshots(...)`、`write_stock_context_snapshots(root=...)` 和
  `schemas/report_intelligence_stock_context_snapshot.schema.json`。若私有 snapshot artifact 缺失，agent prior 必须
  降级到 stock outcome/readiness/profile，并输出 snapshot-missing/no-prior reason。
- industry context snapshot：canonical sector、cycle bucket、mapping confidence、proxy limitation。
  状态：已实现 builder/schema/write path；clean private validation corpus 当前生成 58 条 rows。新增
  `build_industry_context_snapshots(...)`、`write_industry_context_snapshots(root=...)` 和
  `schemas/report_intelligence_industry_context_snapshot.schema.json`。若私有 snapshot artifact 缺失，sector prior 必须
  降级到 industry ETF proxy outcome/readiness/profile，并保留 proxy limitation。
- 每个已启用 macro agent 的 PIT snapshot builder。状态：已实现 macro path。
- snapshot data vintage hash。
- missing feature reason。
- background-only audit。

验收：

- stock/industry context snapshot 不含 price raw values、claim text 或 source span。
- stock/industry context 只用于 profile/prior/evolution，不用于 correctness。
- central_bank、china、commodities、dollar、emerging_markets、geopolitical、
  volatility、yield_curve 都有 snapshot 或明确 deferred gap。
- `claim_validation_allowed=false`。
- PIT audit 能发现 snapshot 被误用为 correctness label。

### P11.4 阶段 D：评级和 profile

实施：

- 首轮不新增公开 `stock_claim_ratings.jsonl` 或 `industry_claim_ratings.jsonl`；rating row 是
  logical/internal concept，已通过 `build_domain_claim_ratings(...)` 扩展现有
  `outcome_layer_support`，因此 source/viewpoint/method performance profiles 都能读取同一套
  redacted internal rating summary。
- 若需要 row-level helper，新增 `build_domain_claim_ratings(..., domain=...)` 作为内存/private
  中间层，输入 outcome label rows，输出不含 claim text/source span/raw price 的 redacted rating rows。
- stock claim rating：已覆盖 after-cost alpha、directional after-cost return、relative directional
  hit 和 target-price auxiliary evidence。
- stock rating 分层：已按 `label_type`、benchmark family、cost model、holding window 输出；
  sector、market-cap、liquidity 由 P4.S snapshot/profile 继续补强。
- stock known failure mode tags：已覆盖 tradeability blocker、target-price-only auxiliary 和
  fundamental-without-relative-followthrough；target conflict/subject mismatch 仍来自 target
  resolution/readiness gap。
- industry claim rating：已覆盖 after-cost/proxy directional evidence、mapping confidence 和 proxy
  limitation tags。
- industry rating 分层：已按 `label_type`、proxy symbol、mapping confidence、proxy liquidity、
  benchmark family、cost model 输出；cycle bucket 由 P4.I snapshot 继续补强。
- industry known failure mode tags：已覆盖 mapping missing、proxy liquidity unverified、operator-seeded
  mapping 和 broad ETF proxy limitation；ambiguous alias/subsector-loss 仍需后续 mapping review 扩展。
- leg rating。
- parent rating。
- viewpoint cluster rating 扩展。
- regime-conditioned performance。
- agent-conditioned performance。

验收：

- stock/industry/macro profile 按 `label_type`、benchmark family 和 cost model 分层。
- stock profile 能输出 tradeability/data-quality blocker share 和 current-data-required fields。
- industry profile 能输出 mapping confidence bucket 和 proxy limitation tags。
- stock/industry proxy limitation 进入 failure mode，不被吞掉。
- mixed legs 不被折叠成单一 hit。
- insufficient sample 输出 provisional。
- profile 按 `series_family` 和 `agent_id` 分层。

### P11.5 阶段 E：agent prior 输出

实施：

- 通用 `build_rke_agent_research_context_from_rows()` retrieval ranking。
- stock prior 面向 superinvestor、decision 和 sector relationship mapper。
- stock prior 按 Munger/Burry/Ackman/Druckenmiller style 生成 role-specific reason codes。
- stock prior 输出 `current_data_required_fields`，覆盖 price、valuation、fundamentals、
  balance sheet、liquidity、catalyst、risk flags。
- industry prior 面向 sector agents 和 decision agents。
- industry prior 按 sector ownership、subsector tags、cycle driver、policy driver 和 proxy limitation
  生成 role-specific reason codes。
- industry prior 输出 `current_data_required_fields`，覆盖订单/库存/价格/政策/供应链/成交等
  sector-specific current data。
- `build_macro_agent_research_priors()`。
- agent prior retrieval ranking policy。
- `export-macro-agent-priors` CLI。
- redacted public/private boundary。
- `rke.agentResearchContext` / `rke.macroAgentPriors` TS bridge wrapper。

stock prior for superinvestors 子任务：

- 状态：已实现 Part 1 builder contract；实施规模 M。
  `build_rke_agent_research_context_from_rows()` 已按 Munger/Burry/Ackman/Druckenmiller
  style 输出 role-filtered stock prior reason codes，并对 removed superinvestor agent
  输出 explicit no-prior reason。runtime prompt wiring、benchmark 和 private prompt mutation
  lifecycle 仍属于 Part 2。
- 实现位置优先放在
  `mosaic/rke/agent_research_context.py::build_rke_agent_research_context_from_rows()`；必要时只在
  该模块内新增小型 ranking/filter helper，避免在 report-intelligence builder 之外复制一套 prior
  语义。
- 输入使用 redacted stock outcome/readiness/profile、known failure mode tags、tool gap 和
  current-data-required fields；不得读取 claim text、source span 或 private prompt content。
- role filter 必须覆盖 P6.2S 的四类 style：
  Munger 质量/护城河/现金流，Burry 低估/逆向/资产负债表/catalyst，Ackman 优质资产/治理/资本配置，
  Druckenmiller 景气/趋势/政策/价格动量。
- 输出必须包含 `ranking_reason_codes`、`current_data_required_fields`、
  `known_failure_mode_tags`、`actionability_guard`、`no_prior_reason` 和 `use_policy`。
- 测试覆盖：四个 canonical superinvestors 得到不同 reason codes；removed agent
  `aschenbrenner` 得到 `unsupported_superinvestor_agent` no-prior reason；缺 current data 时
  prior 保持 research-only；输出不含 claim text/source span。

验收：

- 每个 agent prior 都有 `use_policy=shadow_research_prior_only`。
- 不包含 claim text/source span。
- downstream macro、sector、superinvestor、decision agent 能按 agent_id/as_of_date 读取 summary。
- superinvestor agents 收到的是 stock prior 的 role-filtered context，不是行业/macro prior 的
  无差别拼接。
- sector agents 收到的是 industry prior 的 sector-filtered context，并保留 proxy limitation。
- decision agents 能看到跨层 prior conflict、no-prior reason 和 current-data-required guard。
- downstream context 不再只按输入顺序截断；排序能解释
  `combined_research_prior_weight`、profile match、reliability、freshness 和 agent target match。
- 低权重/contradictory prior 被降权但仍可审计，不被静默删除。
- 缺样本或 blocker 时 prior 降级为 `insufficient_sample` 或不输出。
- 缺 current-data confirmation 时，prior 不得进入 actionable recommendation 字段。

### P11.6 阶段 F：演化 gate

实施：

- stock target/data/tradeability gap -> evolution candidate。
- stock fundamental metric extraction/routing gap -> evolution candidate。
- stock prior-to-superinvestor misuse -> prompt/ranking candidate。
- industry ETF mapping/proxy limitation gap -> evolution candidate。
- industry alias/canonical-sector/cycle feature gap -> evolution candidate。
- industry prior-to-sector-agent misuse -> prompt/ranking candidate。
- 宏观 mapping gap -> evolution candidate。
- 三域低质量 extraction -> prompt candidate。
- 三域 data/tool gap -> tool/data acquisition candidate。
- 三域 agent prior consumption -> shadow audit。
- candidate refusal reasons：insufficient N、missing PIT、mapping confidence too low、
  tradeability gap dominates、proxy limitation too high、source-dependent cluster、
  private text required。

验收：

- evolution gate 有 RI-MACRO-01 到 RI-MACRO-07。
- stock/industry outcome、mapping、privacy 和 shadow-only checks 进入同一 gate evidence。
- stock/industry candidates 先通过 deterministic fixture + redacted real-sample comparison，
  再进入 private prompt repo mutation lifecycle。
- prompt/ranking candidate 必须证明 false-positive 下降或 no-prior/refusal 质量提升，不能只看召回。
- 任一 blocker 存在时，不能 promotion。
- 通过后仍是 shadow-only。

### P11.7+ 后续 all-agent evolution handoff

个股、行业、宏观反馈闭环之后的 all-agent runtime consumption / preflight、private prompt repo
preflight、固定 episode LLM benchmark、agent claim/footprint、autoresearch、Darwinian weight、
replay 和 rollback 规划已拆分到 Part 2：

```text
docs/plans/rke_all_agent_evolution_plan.md
```

本计划保留三域 report feedback、rating、prior 和 gate 的交付口径；P0-P11.6 现在明确包含
stock、industry、macro 三域执行项。`docs/plans/rke_stock_report_outcome_and_evolution_plan.md`
仍作为个股/行业 outcome 的历史实现依据。后续执行约束：

- Part 1 负责 redacted ranked context/export contract；Part 2 负责 all-agent runtime
  consumption、preflight、benchmark 和 replay wiring。Part 2 必须复用 P6.3 的排序键和
  shadow-only 边界，且排序输入必须覆盖 stock、industry、macro prior。
- macro prior 到 macro rule/parameter candidate 的编译仍属于本计划 P7/P11.6 的延伸；
  stock/industry prior 到 recipe/rule candidate 的 refusal/validation 路径也属于三域反馈闭环；
  sector/superinvestor/decision 的 prompt mutation 进入 private prompt repo mutation lifecycle。
- Layer-3 canonical roster、private prompt repo preflight、formal LLM benchmark 和 replay gate
  以 Part 2 `rke_all_agent_evolution_plan.md` 为准。

## P12：交付条件

达到以下条件，才算完成 Part 1（三域 report feedback、rating、redacted prior 和 evolution gate）：

1. 个股、行业、宏观三类 report claims 都进入统一 forecast/outcome/readiness/profile 路径；
   每类至少有真实样本、fixture 和 readiness gap 覆盖。
2. 个股 `stock_price_proxy`、行业 `industry_etf_proxy`、宏观 `macro_asset_proxy`、
   `macro_series_directional`、`macro_curve_directional` 都至少各有 fixture 和真实样本路径。
3. 个股 qlib stock price labeler、行业 ETF proxy labeler、宏观利率/收益率、FX、volatility、
   commodity direct-series labeler 可运行，并且都使用 PIT-safe entry/exit。
4. profile/rating 聚合按 `label_type`、target family、benchmark family、cost model、
   agent layer、metric family 和 regime bucket 分层；禁止把 stock、industry、macro outcome
   当作同质样本混算。
5. macro、sector、superinvestor、decision agents 都能读取 redacted RKE research context；
   没有适用 prior 的 agent 必须有 explicit no-prior / no-applicable-prior reason。对
   superinvestor agents，generic ranked context 不算完成；必须有 stock prior 的
   role-filtered content。
6. outcome label 对 pending、blocked、completed 三种状态区分清楚。
7. claim rating 能输出 `supportive_evidence`、`mixed_evidence`、
   `contradictory_evidence`、`pending_or_unrated`，并保留 `n_effective`、reliability bucket
   和 pending share。parent-level macro `cross_asset_consistency` 是独立验收项，不能埋在
   profile 分层状态里。
8. PIT/provenance/statistical/privacy/schema gates 全部通过；若 gate 阻塞，P12 状态必须记录
   直接 blocker、根因分类和下一步，不能只写“blocked”。
9. report-intelligence 派生 artifacts 默认本地私有处理，不提交 repo；如有明确任务要求提交
   redacted aggregate，必须先通过 source prose、claim text、source span、PDF/Markdown/cache、
   private path 和 licensed raw data 泄漏检查。
10. 运行 RKE agent context/export 路径能为 stock、industry、macro prior 生成下游可消费的
    shadow research prior；macro-specific `export-macro-agent-priors` 仍作为 compatibility view。
11. Agent-facing RKE context 使用稳定 retrieval ranking policy，不再只按 forecast 输入顺序
    截断；排序字段必须是 redacted/local-safe，且所有非中性 prior 仍要求 current data
    confirmation。生成的详细 context artifact 默认本地私有。Part 1 只交付 redacted
    ranked context/export contract；all-agent runtime preflight、private prompt resolution
    和 benchmark wiring 属于 Part 2。
12. 个股、行业、宏观 prior 都能进入 evolution candidate 输入；至少两个 macro agents 的 prior
    能进入 rule/parameter candidate compiler，stock/industry prior 至少能进入 recipe/rule
    candidate 或 refusal reason 路径，并对缺 PIT、缺 validation target、样本不足或
    source-dependent cluster 给出 refusal reason。若条件 8 gate 仍阻塞，或当前 corpus 只产生
    refusal rows，条件 12 保持未完成。

以下内容不是 Part 1 exit criteria，属于 Part 2 program-level handoff：

- patch application / runtime activation proof。
- fixed-episode LLM benchmark、人工复核、全 agent replay。
- autoresearch / Darwinian weight / RKE retrieval evolution。
- private prompt repo 全 agent 覆盖、prompt hash freeze、prompt mutation lifecycle。
- agent claim 与 report claim 的统一 RKE claim/profile/footprint/evolution 闭环。
- Layer-3 private prompt 深度升级和 roster preflight 的持续校验。

### P12 当前验收状态（2026-07-03）

状态口径：本节里的“已满足/已落地”只指带私有 PDF/Markdown/outcome 输入的
clean validation corpus。默认 checked-in registry 是公开仓库的 input-load 诊断面；
它缺少私有输入时暴露的无 PIT outcome、Markdown 覆盖不足或 refusal-only compiler
输出，必须记录在 blocker 根因表里，但不能替代 clean corpus gate 证据。反过来，如果任一
待发布或待验收 corpus 只产生 refusal rows，或 PIT outcome labels 为零，则该 corpus 下的
条件 8/12 不能关闭。

当前分支已经满足三域 PIT outcome/readiness/profile 的基础底座，并满足宏观反馈闭环的
首轮运行条件；agent-facing retrieval ranking、candidate compiler 和 macro
`cross_asset_consistency` 的 gate 证据已落地。默认 checked-in registry 因不包含私有
PDF/Markdown/outcome 输入，`evolution-readiness --root . --no-write` 仍只适合暴露
input-load blocker；Part 1 gate 证据以本地私有 clean validation corpus 为准：
`.mosaic/rke/report_intelligence/merged_private_replay_clean_macro_20260703`。
该 corpus 的 `evolution_readiness_gate.json` 记录 RI-EVOL-01..09 和 RI-MACRO-01..07
全部 passed，`blocker_count=0`。Part 2 的 patch activation、LLM benchmark、
Layer-3 private prompt 升级和 replay 不属于 Part 1 exit criteria。产物仍保持
shadow-only，不改变生产交易。条件 12 只能在条件 8 的 clean validation gate 已通过时关闭；
默认 checked-in registry 的无 PIT/refusal-only 输出只作为 blocker 诊断，不能用来充当
compiler 有效性证据。条件 8 下的 blocker 根因表是 P12 blocker reason tracker；后续若
RI-EVOL/RI-MACRO gate 重新阻塞，必须先更新该表的直接 blocker、根因分类和下一步，而不是
把失败归因给 ranking 或 compiler：

- 条件 1：基础底座已满足。`forecast_claims.jsonl`、`report_outcome_labels.jsonl` 和
  `outcome_labeling_readiness.json` 已能同时承载 stock、industry、macro 三类 claim/outcome/gap。
  clean validation corpus 记录 442 条 forecast claims、534 条 outcome labels、
  stock proxy labels 273、industry ETF proxy labels 109、macro asset/series/curve
  labels 分别为 92/59/1。
- 条件 2：已满足类型覆盖。`stock_price_proxy`、`industry_etf_proxy`、`macro_asset_proxy`、
  `macro_series_directional`、`macro_curve_directional` 都有测试覆盖；clean validation corpus
  包含 `macro_asset_proxy=92`、`macro_series_directional=59`、`macro_curve_directional=1`。
- 条件 3：已满足首轮可运行要求。个股 qlib stock price、行业 ETF proxy、宏观利率/收益率、
  FX、commodity direct-series label 已有真实路径；VIX 波动率序列已通过
  `macro-series-backfill --series-id VIX` 写入本地 `scorecard.db` 并在
  `macro_market_series_catalog.jsonl` 标记为 ready。当前 corpus 仍缺少可完成的真实
  volatility claim leg，因此 `macro.volatility` 只有数据/fixture ready 和 deferred gap。
- 条件 4：已满足 Part 1 contract。stock/industry outcome 已按 `label_type`、benchmark/cost model
  做基础分层；macro prior 已保留 agent/regime/metric family 分层。parent-level
  `cross_asset_consistency` 的独立 bucket contract 归入条件 7 验收，不埋在 profile
  分层状态里。`outcome_labeling_readiness.json`
  已新增 `assignment_gap_counts`、`assignment_inferred_rule_counts` 和
  `rating_readiness_bucket_counts`；默认 corpus 记录 `blocked_assignment=0`、
  `assignment_gap_counts={}`，并通过 `industry_default_agents` 规则把 8687 条缺显式 owner 的
  claim 路由到 sector/decision owning-agent 候选。当前 public builder 已继续补齐
  `bond`、`commodity`、`market_index`、`style_index`、`equity_index`、`broad_market` 和
  `asset_class` 的 macro target-family owning-agent mapping，复用现有 macro metric/target
  规则；用当前 builder 重算 clean validation corpus 的 assignment gaps 时，
  `agent_assignment_missing` 已从旧 artifact 的 33 降到 1，剩余项是泛
  `entity/forward_return_proxy` 战略展望，保留人工 owner mapping 而不强推到
  stock/industry/macro agent。
  stock/industry context snapshot builder/schema/write path 已落地，clean validation corpus 当前输出
  74 条 stock snapshot rows 和 58 条 industry snapshot rows。当前 public builder 已能从
  redacted metric families 输出 stock `fundamental_metric_family_counts`，并从
  PIT-safe metadata 字段推导 stock `market_cap_bucket`；但 clean corpus 目前未提供市值字段，
  因此 stock 仍是 74/74 unknown，并由 data acquisition proposal 和 shadow-only
  `data_acquisition_prioritization_rule` candidate 汇总为
  `stock_context_market_cap_metadata_missing`，不做交易所或代码前缀猜测。industry builder
  已能从 claim component roles 和 standardized metric families 推导
  `industry_cycle_bucket`；用当前 builder 重算 clean corpus 时，industry unknown cycle
  buckets 从旧 artifact 的 58/58 降到 9/58。
- 条件 5：已满足 Part 1 builder contract。宏观已有 8 个 macro agents 的 redacted research priors：
  `macro.central_bank`、`macro.china`、`macro.commodities`、`macro.dollar`、
  `macro.emerging_markets`、`macro.geopolitical`、`macro.volatility`、
  `macro.yield_curve`。stock/industry prior 可以进入
  generic RKE research context；当私有 snapshot artifact 存在时，stock/industry context item 已能输出
  `context_snapshot_status=available` 和 safe bucket/proxy 字段，缺失时仍带
  `stock_context_snapshot_missing` / `industry_context_snapshot_missing` 降级原因。Munger、
  Burry、Ackman、Druckenmiller 的 stock prior 已输出不同 `role_filter_*` reason codes；
  removed superinvestor agent 得到 explicit `unsupported_superinvestor_agent` no-prior reason。
  条件 11 的 ranking infrastructure 和条件 5 的 role-filtered content 现在都在 builder 层
  有测试覆盖；如果 P11.5 的 superinvestor stock prior role-filtered content 回退为 generic
  context，则 superinvestor 侧条件 5 不能关闭，即使条件 11 的排序基础设施仍通过。全 agent
  runtime preflight、private prompt resolution 和 benchmark wiring 仍属于 Part 2。
- 条件 6：已满足。outcome/readiness 区分 completed、pending window 和 readiness gap；
  RI-MACRO-02 记录 `macro_ready_counts`、`macro_pending_counts` 和 readiness gap counts。
- 条件 7：已满足 Part 1 bucket contract。独立 `cross_asset_consistency` 验收已落地：parent claim 根据
  economic-direction normalization、hard-incompatible pair 和冲突阈值输出
  `consistent`、`mixed`、`contradictory`、`blocked_mapping` 或 `not_applicable`。
  clean validation corpus 分布为 consistent 65、mixed 26、blocked_mapping 48、
  not_applicable 1718。`macro_agent_research_priors.jsonl` 的 rating buckets 已标准化为
  `supportive_evidence`、`mixed_evidence`、`contradictory_evidence`、
  `pending_or_unrated`；clean validation corpus 当前分布为 supportive 5、contradictory 5、
  pending 1847。这个状态只表示 bucket contract 已落地，不表示宏观 rating 已有充分统计
  证据：非 pending 样本仍很少，并且分散在 8 个 macro agents 和多个 metric families 中。
  因此下游只能把 rating 当作 provisional
  shadow prior；任何 agent-facing summary 必须保留 `n_effective`、reliability bucket、
  pending share 和 current-data confirmation guard。stock/industry 的 row-level logical rating
  已按 P11.4 作为 internal/profile 扩展落地：`build_domain_claim_ratings(...)` 从 stock/industry
  outcome rows 生成 redacted in-memory ratings，并把 bucket counts、tradeability blockers、
  target-price auxiliary evidence、fundamental metric family counts、mapping confidence 和
  proxy limitation tags 写入 `outcome_layer_support`。这仍不表示三域 claim rating 已可生产
  使用；market-cap/liquidity/cycle 等 profile strata 的实际 corpus coverage 和有效样本量还需继续补强。
- 条件 8：clean validation corpus 已满足。该 corpus 的 schema/PIT/provenance/statistical
  audit evidence 在 `RI-EVOL-04` 中为 0 current failures、3 trailing passed refreshes；
  `operator-readiness --root . --no-write` 为 18/18 passed。clean validation corpus
  的 derived refresh 记录 531 selected reports、529 Markdown-ready reports、385 LLM-processed
  reports、210 unique outcome claims、41 passed recipe validations、500 reviewed gold claims、
  51 reviewed gold documents、0 Markdown QA queue，并且 `evolution_readiness_gate.json`
  为 `gate_status=passed`、`blocker_count=0`。独立 RI-STOCK-01..04 和
  RI-INDUSTRY-01..04 已接入 `evolution_readiness_gate.json`，覆盖 target/mapping
  contract、PIT label coverage、tradeability/proxy limitation audit，以及 prior
  privacy/shadow-only policy；stock/industry 仍同时通过通用 RI-EVOL、
  schema/PIT/provenance/privacy/readiness/profile 路径覆盖。

  默认 checked-in registry 的 blocker 根因表仍保留为 input-load/runbook 诊断，不作为
  clean validation gate 失败证据：

  | check | 直接 blocker | 当前证据 | 根因分类 | 下一步 |
  | --- | --- | --- | --- | --- |
  | RI-EVOL-01 | `unique_outcome_claim_count_below_threshold`、`stock_proxy_claim_count_below_threshold`、`industry_proxy_claim_count_below_threshold` | unique outcome 0/100，stock proxy 0/30，industry proxy 0/30 | PIT outcome 样本为零；数据/coverage 问题，不是 compiler/ranking 问题 | 生成 stock/industry/macro 非 LLM PIT outcome labels |
  | RI-EVOL-02 | `paper_trading_validated_recipe_count_below_threshold` | validated recipes 0/20，validation pass 0 | 无可绑定 outcome 的 paper-trading 证据；依赖 RI-EVOL-01 | 把 recipe runs 绑定到 direct PIT outcome 和 after-cost metrics |
  | RI-EVOL-07 | markdown/P9 覆盖短缺 | markdown ready 0/300，quality pass 0/300，LLM processed 0/100，stock reports 0/80，120d-ready stock reports 0/30，strata missing 9 | 上游私有 PDF/MinerU/Markdown/LLM coverage 问题 | 运行 stratified private extraction，补 quality-gated markdown coverage |
  | RI-EVOL-08 | `prior_compiler_refusal_only` | 默认 public corpus 只有 refusal compiler 输出；actionable prior candidate 为 0 | PIT outcome/样本不足导致 compiler 只能诊断 blocker；不是 prompt lifecycle 或 ranking 问题 | 用 clean validation corpus 或补 PIT outcome 后重建 prior-to-candidate compiler，直到至少有可验证 actionable candidates |
  | RI-MACRO-02 | `macro_pit_label_coverage_missing` | macro asset/series/curve eligible、labelable、outcome rows 均为 0 | 宏观 PIT label coverage 为零；数据/target mapping/corpus 问题 | 补 macro claim legs 的 direct/proxy PIT outcome labels |
  | RI-MACRO-04 | `macro_rating_profile_market_feedback_missing` | 无 macro market-feedback labels 可聚合 | 统计证据缺失；依赖 RI-MACRO-02 | 在 macro PIT labels 非零后重建 macro rating/profile |
- 条件 9：已满足当前边界。report-intelligence 派生报告已按本地私有处理，不作为默认提交内容；
  私有 detail JSONL、review aids、PDF/Markdown/MinerU cache 仍在 gitignore/private registry
  边界内。
- 条件 10：已满足当前 export contract。`export-rke-agent-context` 复用通用
  `build_rke_agent_research_context()`，可为 stock、industry、macro prior 输出 redacted
  ranked shadow research context，保留 `production_signal_allowed=false`、current-data
  guard、ranking policy 和 no-prior reason。`export-macro-agent-priors --agent-id
  macro.dollar --as-of-date 2026-06-18 --no-source-prose` 仍作为 macro compatibility
  view，可输出 539 条 shadow prior，`private_text_included=false`。

条件 11/12 与 Part 2 边界：

以下两项在 clean validation corpus 下关闭的是 Part 1 的 ranked context 和
candidate/refusal contract；不包含 Part 2 的 runtime preflight、private prompt resolution、
benchmark/replay 或 promotion proof。

- 条件 11：当前 corpus 的 gate 证据已落地。`build_rke_agent_research_context_from_rows()` 已按
  `agent_target_specificity_bucket`、`performance_context_match`、
  `combined_research_prior_weight`、reliability、freshness 和 input index 排序后截断，
  并输出 `retrieval_rank`、`priority_bucket`、`ranking_policy_id`、
  `ranking_reason_codes`、`matched_item_count`、`truncated_item_count` 和 stock/industry
  context snapshot missing reasons。`RI-EVOL-09`
  已进入 `evolution_readiness_gate.json`，当前刷新记录 sector/decision ranked context
  evidence、macro/superinvestor no-prior reason evidence，且 private text、current-data
  guard、shadow policy、ranking policy 和 rank/bucket/count metadata violation 均为 0。这关闭
  Part 1 的 ranking infrastructure 证据；superinvestor stock prior role-filtered content 已在条件 5 的 builder
  contract 中覆盖。
  Part 2 的全 agent runtime preflight、private prompt resolution 和 benchmark wiring 仍不计入
  Part 1 exit criteria。
- 条件 12：clean validation corpus 的 compiler/candidate/refusal contract 证据已落地。
  `prompt_mutation_candidates.jsonl` 已接入
  redacted prior-to-candidate compiler 路径：macro prior 可生成
  `macro_prior_rule_parameter_candidate` 或 refusal；stock/industry prior 可生成
  `*_prior_recipe_rule_candidate` 或带 `missing_pit_outcome`、
  `missing_validation_target`、`insufficient_effective_n`、
  `source_dependent_cluster` 的 refusal。`RI-EVOL-08` 已进入
  `evolution_readiness_gate.json`。clean validation corpus 当前记录 22 条 prompt mutation
  candidates，其中 `macro_prior_rule_parameter_candidate=5`、
  `macro_prior_rule_parameter_refusal=3`、`stock_prior_recipe_rule_candidate=1`、
  `industry_prior_recipe_rule_candidate=1`，并包含 1 条
  `data_acquisition_prioritization_rule` 用于 market-cap PIT metadata 缺口；prior compiler
  actionable candidate count 为 7，private text / shadow policy violation 均为 0。
  如果当前 corpus 只产生 refusal rows，条件 12 保持未完成；“可运行的 compiler path”不能替代
  “带 PIT outcome 和足够样本的可验证 candidate”。这些 candidate 仍是 shadow-only；接入
  P7/P11.6 的 patch activation、benchmark 和 runtime proof 属于 Part 2。

Part 2 handoff notes，不计入 Part 1 完成判定：

- patch validation 已有；`rke_benchmark.patch_activation_readiness` 已补 no-write
  shadow activation/runtime proof gate，要求 patch artifact、validation、shadow apply、
  runtime activation/proof 和 rollback refs，且 production activation 继续禁止。真实
  patch apply/activation proof 仍需由正式 run 产生。
- Python `get_rke_research_context` tool path 已记录 consumed context hash、Part 1
  ranking policy、retrieval rank/priority bucket 分布和 truncation audit；agent
  footprint summary 和 shadow replay gate 已强制每个 consumed context hash 都带这些
  runtime ranking/truncation proof；全 agent private prompt provenance、benchmark wiring 和
  replay proof 仍属于 Part 2。
- `prompts.preflight` 已提供 formal benchmark/replay 前的 private prompt provenance
  预检机制，不返回 prompt body；dirty private prompt repo 会被
  `private_prompt_repo_dirty` 阻断，避免把 working-tree prompt hash 与 HEAD revision
  混作可复现 release pin，并返回 no-body source summary/dirty count 作为 blocker
  evidence。真实 private prompt repo 的全 agent ready rows、
  leak/drift/release checks 和 benchmark 仍属于 Part 2。
- `rke_benchmark.all_agent_prompt_provenance_readiness` 已能把全 25 agents × 2
  languages 的 private prompt pins 与 audit-version、release/leak-drift evidence 聚合成
  formal benchmark/replay 前置 gate；release evidence 必须匹配 preflight 的 private
  `prompt_repo_id`、`prompt_repo_revision` 和 prompt file path；在 shadow/delivery 聚合中
  使用时还必须绑定同一个 `benchmark_run_id`，并保留 prompt source summary/dirty blocker；
  真实 private prompt audit/release 仍需在 private prompt repo 中完成。
- `rke_benchmark.fixed_episode_manifest` 已提供 E2 fixed-episode manifest/preflight：
  8 个 regime episodes、17 个 as-of dates、全 25 agents、4 类 model config slot、
  input/scoring contract 和 manual-review-required 状态。真实 LLM paired outputs、
  deterministic score tables、investment outcomes 和 manual review 决策仍未运行。
- `rke_benchmark.fixed_episode_benchmark_evidence` 已提供 no-body benchmark evidence
  gate，要求 paired output manifest、三类 required model config 的逐模型 paired output
  counts、fixed episode/as-of-date/model-config manifest refs、schema validation report、
  deterministic score table、investment outcome table、benchmark quality gate summary
  和 approved manual review timestamp，并要求 evidence refs、quality summary 和
  manual review 绑定同一个 `benchmark_run_id`；quality summary 会阻断 severe safety
  violation、fallback prompt run、current-data confirmation violation 和未通过的
  schema-failure gate。实际 LLM 输出和人工复核仍需由正式 benchmark run 产生。
- LLM reasoning benchmark 和人工复核 gate 尚未运行；正式 benchmark 还必须使用 private
  prompt repo 解析出的 frozen prompt hash，不能用 public fallback 充当有效 paired output。
- `rke_benchmark.darwinian_autoresearch_consumption_readiness` 已补 no-write
  consumption gate，要求 replay run、input manifest、RKE prior usage metrics、
  downstream outcome metrics、Darwinian/autoresearch update 和 rollback readiness refs；
  真实 autoresearch / Darwinian replay 仍需实际读取 RKE prior usage quality、agent claim
  outcome、retrieval ranking quality 和 rollback feedback 并写出这些 refs。
- `rke_benchmark.capture_agent_claim_footprints` 已提供 redacted private-local
  agent claim/footprint capture contract，`rke_benchmark.agent_footprint_summary`
  已能从 private rows 输出 redacted aggregate profile summary，并统计 linked report claim
  refs；runtime `rke_context_hash` 必须是可复核的 64-hex SHA-256 digest；真实
  benchmark/replay agent rows 仍未完成。
- `rke_benchmark.agent_profile_evolution_readiness` 已能检查四层 agent footprint
  coverage、RKE context hash、report claim link、privacy/no-source-prose audit、
  runtime ranking metadata、profile update ref 和 evolution input ref，并要求 profile
  evidence 绑定同一个 `benchmark_run_id`；其中每个 consumed RKE context hash 都必须对应
  redacted report claim ref、canonical Part 1 `ranking_policy_id`、正整数
  `retrieval_rank`、canonical `priority_bucket`（`high`/`medium`/`low`）和 truncation
  audit 非负整数，并有 current-data confirmation，避免未绑定研报 claim、ranking proof
  或 current-data guard 的 agent footprint 进入 profile/evolution。真实
  profile/evolution 写入仍需由实际 benchmark/replay run 产生。
- `rke_benchmark.darwinian_autoresearch_input_manifest` 已把 RKE prior usage、
  current-data confirmation、stale/contradictory prior handling、downstream outcome、
  turnover/cost 和 prompt provenance 拆成独立输入，并要求 downstream outcome 与
  prompt provenance 绑定同一个 `benchmark_run_id`，要求 current-data confirmation 覆盖每个
  consumed RKE context hash，同时明确 `rke_prior_treated_as_current_data=false`；
  `darwinian_autoresearch_consumption_readiness`
  进一步要求 replay/run refs、同一 `benchmark_run_id` 的 consumption evidence 和
  consumed flags，避免把 input-ready 误读成已消费。真实 autoresearch/Darwinian replay
  消费和权重更新仍未完成。
- `rke_benchmark.candidate_consumption_manifest` 已能读取 Part 1
  `prompt_mutation_candidates.jsonl` 并保留 candidate/refusal blocker reason，
  同时阻断 production/private-text/manual-review/promotion-state 违规，并把
  tooling/data-acquisition、review、coverage、mapping-registry 和 policy-gate queue
  candidate 标记为 no-prompt-branch 消费；没有可解析 affected agent 的 prompt-like candidate
  也只记录 blocker，不创建空 private prompt branch。no-prompt-only 队列不会声明需要 private prompt
  mutation，prompt release、rollback 和 patch activation gate 对其返回 `not_applicable`。
  真实 private prompt mutation、benchmark、replay 和 rollback 消费仍未完成。
- `rke_benchmark.prompt_mutation_lifecycle_manifest` 已能把 safe candidate/refusal
  摘要转成 private prompt branch 生命周期预检；refusal-only row 和 tooling/data-acquisition
  queue candidate 只记录 blocker，不创建 prompt branch，也不能作为条件 12 的完成证据。
- `rke_benchmark.prompt_mutation_release_readiness` 已能检查 prompt version id 正整数、
  private prompt repo commit/hash、lifecycle private branch、base prompt repo revision、
  overwrite target paths、audit-version ref、`prompts.verify_release` 和 leak/drift
  evidence；在 shadow/delivery 聚合中使用时，release evidence 必须绑定同一个
  `benchmark_run_id`；candidate `blocked_by` 未清空时仍阻断 release；真实 private prompt
  写入与 release 仍需在 private prompt repo 中执行。
- `rke_benchmark.patch_activation_readiness` 已能检查 shadow-only patch activation 的
  artifact/validation/apply/runtime proof/rollback refs，并把 candidate `blocked_by`
  保持为硬 blocker；patch activation evidence 必须绑定同一个 `benchmark_run_id`，在
  `delivery_readiness` 中复查时也沿用该绑定；真实 runtime activation proof 仍需由实际 replay/benchmark
  产生。
- `rke_benchmark.prompt_mutation_rollback_readiness` 已能检查 private prompt branch
  candidate 离开 shadow 前所需的 rollback trigger、与 lifecycle prompt pins 匹配的
  previous prompt hashes、rollback procedure、monitor output 和 post-rollback verification
  evidence；rollback evidence 必须绑定同一个 `benchmark_run_id`，在 shadow/delivery
  聚合中复查时也沿用该绑定；candidate `blocked_by` 未清空时仍阻断 rollback gate；真实 rollback
  monitor 输出仍需由实际 replay/paper-trading run 产生。
- `rke_benchmark.shadow_replay_readiness` 已能把 all-agent prompt provenance、
  benchmark evidence、Darwinian input、prompt mutation release/leak-drift readiness、
  runtime RKE context/current-data confirmation 和 rollback readiness 汇总为 shadow replay
  gate；current-data confirmation 必须覆盖每个 consumed RKE context hash。真实
  replay/paper-trading run 仍未执行，不能据此 promotion。
- `rke_benchmark.paper_trading_readiness` 已能检查 shadow replay ready 后进入 paper-trading
  所需的同一 `benchmark_run_id` operator-approved reviewed plan、risk limit 和
  stop-loss/rollback ref；
  这只允许 paper-trading entry，不允许 production promotion。
- `rke_benchmark.promotion_decision_readiness` 已能检查 paper-trading result、monitor
  summary、approved second review 和 lockbox decision refs，并要求 promotion evidence 绑定同一个
  `benchmark_run_id`；它只标记 ready for operator promotion decision，不执行也不允许
  production promotion。
- `rke_benchmark.delivery_readiness` 已能把 Part 2 E7 的 prompt provenance、runtime
  context、benchmark、profile/evolution、Darwinian/autoresearch input 和 consumption、
  prompt release、patch activation、rollback、shadow replay、paper-trading 和 promotion
  decision gates 汇总成逐项 blocker 审计，并把 prompt source blocker 作为 no-body
  condition evidence summary 透传；
  真实 benchmark/replay/promotion 仍需实际运行。
- `rke_benchmark.record_delivery_evidence` 已能把真实 run 产生的 no-body evidence refs
  写入 private-local `.mosaic/rke/all_agent_evolution/delivery_evidence.jsonl`，后续
  `delivery_readiness` 可按 `benchmark_run_id` 复查；同一 run 的多次记录按 evidence key
  增量合并，便于 benchmark、replay、paper-trading 和 promotion 分阶段追加；该私有 evidence
  store 会记录 `cohort`，支持非默认 cohort 按 run id 复查；写入返回值会把 proof-object key
  count 和 run context key count 分开统计；该私有 evidence store 不提交。
- `rke_benchmark.delivery_evidence_audit` 已能按 `benchmark_run_id` 审计该私有 store
  已记录和仍缺失的 proof-object keys，并返回 aggregate delivery readiness status，避免把
  key-complete evidence 误读为 E7 ready；同时透传 condition-level readiness summaries；
  `cohort`、`prompt_source_status` 等 run context keys 与 proof-object keys 分开统计；
  不返回 evidence body。
- 所有 agent 的 private prompt repo 版本 replay/evaluation 记录尚未覆盖。
- agent claim 和 report claim 尚未统一进入 RKE claim/profile/footprint/evolution 闭环。
- Layer-3 roster preflight：当前分支已完成 public runtime、fallback prompt、RKE style-fit、
  docs 和 tests 的同步迁移，canonical 四人组为 `druckenmiller`、`munger`、`burry`、`ackman`。
  本地 `tests/test_bridge_prompts.py::test_superinvestor_roster_uses_canonical_four` 读取四个
  canonical agents，并拒绝 `aschenbrenner` 和 `baker`；完整 Munger/Burry prompt 升级仍需进入
  private prompt repo，并在 benchmark 前冻结 private prompt hash。

因此当前状态是：个股、行业、宏观研报观点已经能进入 PIT outcome/readiness/profile 底座；
三域统一的 agent-facing ranked context/export、prior-to-candidate/refusal compiler 和独立
RI-STOCK/RI-INDUSTRY/RI-MACRO evolution gate 已有 public contract。所有 agent private
prompt repo 版本的 RKE 驱动演化、正式 benchmark/replay 和 promotion 证据仍未完成。
所有产物仍为研究和演化用途，不能影响生产交易，除非后续有单独的 promotion gate 任务明确批准。

## P13：首轮不做的事

为控制风险，首轮明确不做：

- 不让个股、行业、宏观研报观点直接影响生产交易。
- 不让 LLM 判断 claim 正确性。
- 不实时联网补历史新闻作为 PIT evidence。
- 不把收益率 claim 静默映射成债券 ETF 反向结果。
- 不把 regime snapshot 当作 claim validation。
- 不把多资产 parent claim 强行压成单一 score。
- 不公开任何含 source prose 或 licensed raw data 的 artifact。

## P14：建议优先级

历史实施顺序是 P0/P1/P2 -> P3/P4 -> P5/P6 -> P7/P9；这些基础阶段已经按 P12 状态完成，
不要把本节当作重新执行清单。

当前下一步聚焦仍未完成的三域 agent-facing 闭环：

1. 保持 clean private validation corpus 的三域 PIT outcome / markdown coverage 样本，
   不把默认 checked-in registry 的 missing private inputs 当作 Part 1 gate 失败。
2. 同步补剩余三域评级缺口：target-family owning-agent mapping 和 industry cycle buckets 的
   public builder contract 已补到可测试路径；stock fundamental metric counts 已能从
   redacted claim metric families 输出，stock market-cap bucket 仍依赖 PIT metadata coverage，
   当前由 `stock_context_market_cap_metadata_missing` data proposal 跟踪，并进入
   shadow-only data acquisition prompt-mutation candidate；该 candidate 的 aggregate
   evidence 已纳入 semantic contract 校验；
   `blocked_assignment` 已从 readiness/candidate 证据推进到可复核 aggregate，后续只需随新 target
   family 扩展映射，并通过 clean private corpus 重跑验证 coverage 是否实际下降。macro
   `cross_asset_consistency` 已有独立条件 7 证据；后续只随 claim-leg coverage 扩样，并继续保留
   hard-incompatible 与 50% 冲突阈值审计。
3. 最后把 compiler 输出接到 P7/P11.6 的 evolution gate，仍保持 shadow-only；all-agent
   benchmark、replay、Darwinian weight 和 private prompt mutation 按
   `docs/plans/rke_all_agent_evolution_plan.md` 执行。

理由：

- 个股、行业、宏观 outcome 底座已经存在；继续扩展前应先保证 agents 读取的是排序后、
  可解释、可截断且不泄漏的 context。
- 证据样本仍薄，compiler 必须先输出 refusal/provisional 状态，不能把少量 completed rating
  当作稳定投资规则。
- all-agent prompt evolution 是独立工程，不应重新塞回本三域 report-feedback 计划。
