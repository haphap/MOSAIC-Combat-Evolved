# MOSAIC 项目实施计划

> A 股版 ATLAS：自我改进多智能体交易框架。
> 基于 ETFAgents 混合架构（Python sidecar + TypeScript 前端）。
>
> **工作主文档**。每完成一项 sub-step 后更新对应章节的 **状态** + **完成时戳** +
> **追加备注**。计划超过子步骤范围的发现/决策一律先在 **§14 待决议题** 章节记录。
> 在用户能验证的 checkpoint 处暂停，不私自滚动到下一阶段。

---

## 0. 项目背景与目标

**MOSAIC** = 把 [ATLAS](https://github.com/general-intelligence-capital/atlas)
4 层多智能体自我改进交易框架**完整复刻**并**适配 A 股市场**。沿用
[ETFAgents](file:///home/hap/Projects/ETFAgents) 的混合架构经验（Python sidecar
+ TypeScript 前端），最大化降低开发成本。

**ATLAS 公开仓只有展示性 ~3,400 LOC**（src/janus.py 571 + src/mirofish/ ~2,800
+ 架构文档 + 通用 prompt 模板）；**核心 IP（25+ 训练好的 prompt、agents/、
autoresearch loop、market_data.py、scorecard.py、API 集成）全部不在仓里**。所
以这是 **基于架构文档 + ETFAgents 经验从零实现** 一套自己的 A 股版 ATLAS。

## 1. 用户已确认的关键决策

- **Q1=a**：完整复刻 ATLAS 全部能力（25+ agents + autoresearch + PRISM + JANUS + MiroFish + 执行 + TUI）
- **Q2**：数据源 = **Tushare + akshare + FRED + opencli/brave**（A 股 + 全球宏观 + 新闻）
- **Q3=b**：autoresearch 推到 Phase 4（agents + 每日循环 + scorecard 跑通后）
- **Q4=a**：保留 ATLAS 原 4 位 US superinvestor（Druckenmiller / Aschenbrenner / Baker / Ackman），把哲学过滤器应用到 A 股
- **Q5=a**：执行层 = **paper trading**（复用 ETFAgents）；回测 **改用 qlib 向量化引擎**
  （原计划的 backtrader 在 Phase 8 已弃，死依赖 + `run_candidate_pool` 存根已于收尾清理）
- **Q6=c**：autoresearch 用 **Git + SQLite 混合**（git 存 prompt 内容，SQLite 存元数据/Sharpe/branch 状态）
- **代号**：MOSAIC（中英语义中性，多 agent → 拼图比喻贴切）
- **Cohort 配置**：7 个（含新增 2006-2007 牛市 + 2008 危机 A 股本地段）
- **双语**：中英文可切换，**默认 Chinese**
- **LLM provider**：默认 **Anthropic Claude Sonnet**（与 ATLAS 原版对齐），
  备选 **DeepSeek**（成本约 1/10）+ 本地 **Lemonade Qwen**（开发零成本）
- **启动 cohort**：`euphoria_2021`（先单 cohort 跑通 Phase 2-4，再扩展 PRISM）
- **PRISM 并发**：cohort 之间顺序训练，cohort 内 layer 间顺序、layer 内最多
  **5 个 agent 并发**（避免 Anthropic 限速）
- **prompt 修改约束**：同一 agent 24h 最多 1 次 mutation；3 天内不能撤销 keep 的修改
- **Branch 命名**：`cohort/{cohort_name}/auto/{agent}/{YYYY-MM-DD}`

## 2. 总体架构

```
TypeScript (mosaic-ts/)               JSON-RPC stdio        Python sidecar (mosaic/)
─────────────────────────             ───────────────       ──────────────────────────
CLI (commander) + TUI (Ink)           newline-delimited     bridge/ (复制 etfagents/bridge/)
LangGraph.js orchestration:                                  dataflows/ (Tushare + akshare + FRED + opencli + brave)
  Layer 1: 10 macro agents           ⇄                       agents/utils/scorecard (新)
  Layer 2: 7  sector agents          ⇄ JSON-RPC              agents/utils/autoresearch (新)
  Layer 3: 4  superinvestor          ⇄ stdio                 agents/utils/git_ops (新)
  Layer 4: CRO/Alpha/Exec/CIO                                prism/ (新)
LLM clients (Anthropic-first)                                janus.py (port ATLAS 公开 571 LOC)
Scorecard / Darwinian 视图                                   mirofish/ (port ATLAS 公开 ~2,800 LOC)
Cohort 切换 UI（PRISM）                                       paper_trading/ + backtest/ (复用 ETFAgents)
                                                              persistence: SQLite + git repo
```

**关键架构原则**（沿用 ETFAgents）：
- Bridge 用**行分隔 JSON-RPC over stdio**（与 ETFAgents 一致）
- 工具调用边界用字符串/JSON（**无跨语言 DataFrame 传输**）
- 解释器发现：`MOSAIC_PYTHON` env > `<repo>/.venv/bin/python` > fail loud
- 所有 numpy / pandas / git / SQLite / Tushare 重逻辑保留在 Python 端
- TS 端只承担 LLM 编排、CLI、TUI、scorecard 可视化

**与 ETFAgents 的关键差异**：
- 25+ agents vs 6 analyst（节点数量 ↑3x）
- **自我改进**（autoresearch + Darwinian + git）—— ETFAgents 完全没有
- **多 cohort 训练**（PRISM）—— ETFAgents 是单 graph
- **反身性模拟**（MiroFish）—— ETFAgents 没有
- **Cohort 元加权**（JANUS）—— 新增

---

## 3. 阶段总览

| Phase | 范围 | 估算 turns | 状态 |
|---|---|---|---|
| 0 | Python sidecar + bridge（Tushare/FRED + 8 macro tools） | 5–6 | ✅ 完成（Day 1–5 / 2026-05-28、Day 5 收尾 2026-05-29） |
| 1 | TS skeleton + bridge-client（直接复用 ETFAgents Phase 1） | 3–4 | ✅ 完成（PR #1 merged 2026-05-29） |
| 2 | Daily cycle MVP：25 agents + 4 层 LangGraph.js（单 cohort） | 11–12 | ✅ 完成（PR #2 merged 2026-05-29） |
| 3 | Scorecard + Darwinian 权重 | 4 | ✅ 完成（PR #3 merged 2026-05-29，3A–3F 全做完） |
| 3.5 | qlib 历史数据底座 + 两段式向量化回测 | 5–6 | ✅ 完成（PR #4 merged 2026-05-29，3.5A–3.5F 全做完） |
| 4 | Autoresearch（git + SQLite，prompt mutation + keep/revert） | 5–6 | ✅ 完成 |
| 5 | PRISM 7 cohort 训练编排 | 5–6 | ✅ 完成（训练编排落地：§1 并发模型 cohort 顺序/layer 顺序/layer 内≤5 并发；§11.6 5A–5E） |
| 6 | JANUS 元层（port ATLAS 571 LOC） | 3 | ✅ 完成（元加权落地：7 cohort rolling 准确度 → feasibility-aware softmax → regime 信号 → 跨 cohort blend；§11.7 6A–6D） |
| 7 | MiroFish 反身性模拟（port ATLAS ~2,800 LOC + Tushare 适配） | 4–5 | ✅ 完成（numpy 情景引擎：相关蒙特卡洛 base/bull/bear/tail + 事件注入 + 打分；前向训练环 + mirofish_runs 隔离账本；§11.8 7A–7E）。**扩展 7M.1–7M.5（交互 swarm/记忆/persona）：7M.1 swarm 引擎 + path-aware scorer 已并入主干；7M.2/7M.3 经增益验证 deferred，详见 §11.8.1** |
| 8 | 执行层（**paper trading** 复用 ETFAgents；回测复用 Phase 3.5 qlib 引擎，**不引 backtrader**） | 4 | ✅ 完成（刀1 `PaperTradingEngine` 移植 + `paper.*` RPC：auth/account/buy/sell/T+1/佣金/持仓/成交；刀2 `backtest.signals` 精简移植 + 接通 `suggest_order_from_signal`（agent 决策→下单）+ paper TS CLI（register/login/account/buy/sell/positions/trades/suggest）。signals 的 LLM 文本解析路径待决策层接入时再移植） |
| 9 | Ink TUI + CLI + 文档 + CI 部署 | 6–8 | ✅ 完成（9A：GitHub Actions CI 两 lane + README 刷新 + CI badge；9B：只读 Ink TUI dashboard〔`pnpm dev dashboard`〕——3 tab〔skill/paper/cohorts〕聚合既有只读 RPC + 键盘导航〔1/2/3/r/q〕，引入 ink+react，ink-testing-library 组件测试。13 CLI 命令 + 1 TUI 屏覆盖全部操作） |
| **总计** | | **50–58 turns / 6.5–9.5 个月业余工时** | |

### 项目收尾总览（2026-05-31）

**Phase 0–10 全部交付**（每阶段一句话）:
- **0** Python sidecar + JSON-RPC bridge(Tushare/FRED + macro tools)。
- **1** TS skeleton + 类型化 bridge client。
- **2** 25 agent × 4 层 LangGraph.js 日循环 → CIO 出组合建议。
- **3** Scorecard(forward_return/alpha)+ Darwinian 权重。
  - **ETF 评分**:CIO 宽基 ETF 建议(5xxxxx.SH / 1xxxxx.SZ)的前向收益经 `scorer._fetch_close` 路由到 `pro.fund_daily`(个股=`daily`、指数=`index_daily`、ETF=`fund_daily`),从而 winrate/skill 同样覆盖 ETF 建议(此前 ETF 行 forward_return 恒为 NULL)。
- **3.5** qlib 历史数据底座 + 两段式向量化回测。
  - **自包含采集器(vendored)**:tushare 股票/ETF 采集器 + qlib `dump_bin.py` + `data_collector/{base,utils}.py`(MIT,microsoft/qlib)vendor 进 `mosaic/dataflows/collectors/`(`NOTICE.md`/`LICENSE.qlib` 记归属;ruff extend-exclude)。`find_qlib_collector` 优先用 vendored 副本(`MOSAIC_QLIB_REPO`/`MOSAIC_QLIB_ETF_COLLECTOR` env 仍覆盖)。运行期只需 `pyqlib` 的 `qlib.utils`;采集器子进程依赖归入 `ingest` extra(fire/loguru/joblib/yahooquery/beautifulsoup4)。
  - **增量更新**:`data.{incremental,validate}` bridge handler + `pnpm dev data incremental --kind stock|etf [--end YYYY-MM-DD]` / `data validate` CLI,封装 `qlib_ingest.ingest_incremental`(append cn_data/cn_etf)。
- **4** Autoresearch(git feature 分支 + SQLite,prompt mutation keep/revert)。
- **5** PRISM 7-cohort 训练编排(layer 顺序 / layer 内并发)。
- **6** JANUS 元层(rolling 准确度 → feasibility-aware softmax → regime → 跨 cohort blend)。
- **7** MiroFish 反身性情景引擎(相关蒙卡 + 事件注入 + path scorer + 隔离 mirofish_runs)。
- **7M.1** 真 agent-to-agent `LocalSwarmEngine`(opt-in)+ 7M.1b 调参 + path-aware scorer。
- **8** Paper trading 执行层(auth/T+1/佣金/持仓,signal→order)。
- **9A** GitHub Actions CI(Python + TS 两 lane)+ 文档刷新。
- **9B** 只读 Ink TUI dashboard。
- **10** TUI 加 today(当日 CIO 建议)+ winrate(逐标的方向命中率)两屏 + ETF 数据(读 cn_etf + 驱动 ETF collector)。
- **TUI 设置页(key 7)**:curated 可编辑配置(LLM provider/模型/输出语言/active cohort/autoresearch 5 数值 + git push·remote/mirofish engine·scorer·inject_context),↑↓选 / enter 编辑 / space 切 bool·枚举 / s 保存。配置经 `config.save` 持久化到 `~/.mosaic/config.json`(`MOSAIC_CONFIG` 可覆盖路径),每个 sidecar 启动 `initialize_config` 时 merge over `DEFAULT_CONFIG`(文件不存在=纯默认,行为不变;非法 JSON fail-soft 回默认)。

**关键决策**:完整复刻 ATLAS 4 层 25+ agents;执行=paper trading,回测=qlib 向量化(**不引 backtrader**);
autoresearch=git+SQLite;默认中文 + Anthropic(可切本地 Qwen 零成本);MiroFish 用三接口
(SwarmEngine/AgentMemory/SeedGraph)隔离机制与后端。

**经增益验证 deferred(诚实,非未做)**:
- **7M.2/7M.3** memory + LLM persona —— 雏形证明当前调参/合成目标下增量≈零(三度量一致),
  接口 + 三套 A/B harness 留存,满足三重启条件之一即可恢复。

**已识别、范围清晰的可补项(deferred 候选,非阻塞)**:
1. **`mirofish.get_agent_context` 注入通路** —— 把 MiroFish 情景预测/tail-risk/最高信念回灌进
   日循环 agent prompt(对齐 ATLAS 唯一让模拟影响交易的真实接法;见 §11.8.1 对照)。**最高价值。**
2. **results 导出器** —— 把回测产出聚合成 ATLAS 同构的 summary.json / portfolio_trajectory.csv /
   equity_curve.png(数据已全有,缺绘图+序列化)。
3. **ETF ingest CLI** —— `qlib_ingest kind=etf` 已可用但未暴露 CLI/RPC(目前 operator 直调)。

**与 ATLAS 的诚实对比一句话**:情景引擎/相关性/打分 ≈ 或优于 ATLAS 公开版,swarm 机制**更真**
(numpy 多 actor 耦合 vs 一次 LLM prompt 扮演);唯一实质落后是"预测回灌 agent prompt"通路(可补)。
"thousands of agents / OASIS+Zep" 在 ATLAS 公开代码里同样不存在。

---

## 4. ETFAgents 复用清单（成本控制关键）

> ETFAgents 已完成 Phase 0/1 + Phase 2 sub-step 2.5b，下表的代码全部已经过测
> 试和真实 LLM/Tushare 端到端验证过，可以直接复制到 MOSAIC。

### 4.1 直接整体复制（仅改 etfagents → mosaic 包名）：约 7,000 LOC

| 来源 | 行数 | 用途 |
|---|---|---|
| `etfagents/bridge/` 全部 → `mosaic/bridge/` | ~600 | Python sidecar 模板（JSON-RPC 协议、handler 注册、stdio 循环、错误码） |
| `etfagents/cache_manager.py` → `mosaic/cache_manager.py` | ~250 | API/signals/snapshots/checkpoints 缓存管理 |
| `etfagents/paper_trading/` → `mosaic/paper_trading/` | ~1,500 | bcrypt 用户 + SQLite 仓位 + 佣金规则 |
| `etfagents/backtest/{backtrader_engine.py, signals.py, cache.py}` → `mosaic/backtest/` | ~3,800 | 候选池回测 + signal 抽取 |
| `etfagents/dataflows/` 除 fred/macro_data 外 → `mosaic/dataflows/` | ~3,500 | tushare/akshare/yfinance/opencli/brave/stockstats 等数据层 |
| `ts/src/bridge/` → `mosaic-ts/src/bridge/` | ~700 | TS 端 BridgeClient + Python 解释器发现 + 错误映射 + 类型化 RPC |
| `ts/src/llm/factory.ts` → `mosaic-ts/src/llm/factory.ts` | ~120 | 多 provider LLM 工厂（OpenAI 兼容 + Anthropic + Google） |
| `tests/test_bridge_protocol.py` → `tests/test_bridge_protocol.py` | ~280 | bridge 集成测试（subprocess 黑盒驱动） |

**复制成本：~7,000 LOC，预计 1–2 turns 改名 + 测试。**

### 4.2 大段复用 + 小适配：约 5,400 LOC

| 来源 | 适配点 |
|---|---|
| `ts/src/agents/helpers/{content,process_narration,tool_report_chain}.ts` ~590 | 直接用，无适配 |
| `ts/src/agents/helpers/{report_leads,role_terms}.ts` ~330 | role-term map 加 ATLAS 角色（CRO/CIO/Druckenmiller/Aschenbrenner/Baker/Ackman 等） |
| `ts/src/agents/helpers/validate_refine.ts` ~400 | spec 增加 ATLAS-style sections（每个 agent 自己的 required_top_sections） |
| `ts/src/agents/helpers/market_levels.ts` ~210 | label 集扩展为 A 股语境（北向资金/跌停/ST/股权登记/解禁/集合竞价 等） |
| `ts/src/agents/helpers/trader_format.ts` ~390 | 部分复用；`stripConstituentTradeInstructions` 在 ATLAS 不适用，替换为 ATLAS 风险纪律 helper |
| `ts/src/agents/helpers/render.ts` ~70 | 改造为 4 层渲染（Layer 1/2/3/4 各一段） |
| `etfagents/dataflows/interface.py`（route_to_vendor）~280 | 加 FRED 路由 |
| `etfagents/agents/utils/{agent_states,memory,analysis_memory,structured,report_leads,validate_refine}.py` ~3,000 | 适配 cohort 字段（state 加 cohort、memory 加 cohort 隔离） |

**适配成本：~5,400 LOC，~3–4 turns。**

### 4.3 模式复用（结构借鉴，重写实现）

| 来源 | 用途 |
|---|---|
| `etfagents/graph/etf_graph.py`（LangGraph 装配） | MOSAIC 4-layer LangGraph.js 装配 |
| `etfagents/agents/utils/structured.py`（structured output + free-text fallback） | 每个 MOSAIC agent 的 schema 输出 |
| `etfagents/agents/utils/analysis_memory.py` | scorecard + Darwinian 数据存储模式 |

---

## 5. 25 个 Agent 详细设计

> 每个 agent 必须有：(a) 中英双语 prompt（外部 .md 文件 + TS 加载）；
> (b) `AnalystReportSpec`；(c) tool 列表 + `unexecuted_tool_recovery` 配置；
> (d) Zod structured output schema。

### 5.1 Layer 1 — Macro（10 个）

| ID | 中文名 | 主要工具 (RPC tools.call) | Structured 输出 schema | Prompt 关键约束 |
|---|---|---|---|---|
| `central_bank` | 央行 | `get_pboc_ops`、`get_fred_series(FEDFUNDS,DFF)`、`get_yield_curve_cn` | `{stance, key_rate_change_bps, qe_qt_balance_change, next_window}` | 必须双央行联动判断；引用具体 BPS / 余额变动 |
| `geopolitical` | 地缘 | `get_global_news(geopolitical)`、`get_us_china_relations` | `{escalation_level: 1-5, hot_zones, trade_impact}` | 必须给具体事件 + 时间窗口 |
| `china` | 中国本土 | `get_pboc_ops`、`get_industry_policy`、`get_property_data` | `{policy_direction, sector_focus, risk_drivers}` | 关注产业政策窗口 + 房地产 + 消费 |
| `dollar` | 美元 | `get_fred_series(DTWEXBGS)`、`get_usdcny`、`get_north_capital_flow` | `{dxy_trend, cny_pressure, north_flow_correlation}` | 必须三角分析 DXY/CNY/北向 |
| `yield_curve` | 收益率曲线 | `get_yield_curve_cn`、`get_fred_series(DGS10,DGS2)`、`get_us_china_spread` | `{curve_shape, recession_signal, cn_us_spread_bps}` | 必须给中美利差具体值 |
| `commodities` | 商品 | `get_commodity_prices`、`get_fred_series(DCOILWTICO,GOLDPMGBD228NLBM)` | `{oil_regime, metals_regime, ag_regime, china_demand_signal}` | 区分能源/金属/农产品 |
| `volatility` | 波动率 | `get_ivx`、`get_fred_series(VIXCLS)`、`get_etf_indicator(510050.SH)` | `{vix_regime, ivx_regime, regime_filter}` | 必须计算 VIX/iVX 比值 |
| `emerging_markets` | 新兴市场 | `get_etf_price_data(EEM)`、`get_etf_price_data(2800.HK)` | `{em_relative, hk_a_share_ratio, capital_flow}` | 关注港 A 比价 |
| `news_sentiment` | 新闻情绪 | `get_xueqiu_heat`、`get_news`、`get_caixin_sentiment` | `{retail_sentiment_score: -1 to 1, hot_topics, contrarian_flag}` | 量化雪球热度 |
| `institutional_flow` | 机构资金 | `get_north_capital_flow`、`get_lhb_ranking`、`get_fund_flow` | `{north_net_flow_cny, top_buyers, sectors_in_out}` | 必须给具体净流入/流出金额 |

**Layer 1 输出聚合 → `RegimeSignal { stance: BULLISH/BEARISH/NEUTRAL,
confidence: 0-1, key_drivers, layer_1_consensus_score }`**（10 个 agent 共识打分）

### 5.2 Layer 2 — Sector（7 个，申万一级映射）

| ID | 申万一级映射 | 主要工具 | Output schema |
|---|---|---|---|
| `semiconductor` | 电子（半导体子板） | `get_etf_holdings(159995.SZ 半导体)`、`get_industry_research`、`get_north_capital_flow(by_sector)` | `{longs: [tickers w/ thesis], shorts, sector_score}` |
| `energy` | 石油石化 + 煤炭 + 公用事业 | `get_etf_holdings(516660.SH 石化)`、`get_commodity_prices` | 同上 |
| `biotech` | 医药生物 | `get_etf_holdings(512010.SH)`、`get_industry_research` | 同上 |
| `consumer` | 食饮 + 家电 + 美护 | `get_etf_holdings(159928.SZ 消费)` | 同上 |
| `industrials` | 机械 + 军工 + 交运 | `get_etf_holdings(512660.SH 军工)` | 同上 |
| `financials` | 银行 + 非银 | `get_etf_holdings(512800.SH 银行)` | 同上 |
| `relationship_mapper` | 跨行业（产业链/股东网络） | `get_top_holdings_overlap`、`get_related_party_transactions` | `{supply_chains, ownership_clusters, contagion_risks}` |

### 5.3 Layer 3 — Superinvestor（4 位 US 哲学家保留）

| ID | 哲学 | A 股应用 prompt 关键 |
|---|---|---|
| `druckenmiller` | 宏观/动量 | "What's the most asymmetric trade in A-share right now? Identify sector rotation + policy catalyst pairs. Concentrate on regime-driven 3-5 names." |
| `aschenbrenner` | AI/算力周期 | "Who benefits from China's AI capex cycle vs US export controls? Map domestic compute (华为链/寒武纪/海光) + AI 应用 (科大讯飞/360)." |
| `baker` | 深度科技/生物 IP | "Which A-share names have real IP moats? Focus on 创新药 / 罕见病 / 国产替代 with patent strength + clinical pipeline." |
| `ackman` | Quality Compounder | "Find pricing power + FCF + catalyst trio. White liquor + appliances + branded consumer dominate. Quality > price for 5+ year hold." |

### 5.4 Layer 4 — Decision（4 个）

| ID | 角色 | 输入 | 输出 |
|---|---|---|---|
| `cro` | 对抗风控 | Layer 1+2+3 全部输出 | `{rejected_picks: [{ticker, reason}], correlated_risks, black_swan_scenarios}` |
| `alpha_discovery` | 找遗漏 | Layer 1+2+3 全部输出 | `{novel_picks: [{ticker, why_missed_by_others}]}` |
| `autonomous_execution` | 信号→仓位 | Layer 3 picks + Layer 4 cro/alpha + Darwinian weights | `{trades: [{ticker, action, size_pct, conviction}]}` |
| `cio` | 最终决策 | 全部上层输出 + Darwinian weights + JANUS regime | `{portfolio_actions: [{ticker, action, target_weight, holding_period, dissent_notes}]}` |

---

## 6. RPC 方法清单

### 6.1 复用 ETFAgents（21 个）
直接保留：
- `tools.list` / `tools.call`
- `config.{default, get, set}`
- `cache.{stats, cleanup, clear, details}`
- `paper.{register, login, logout, current_user, get_account, reset_account, buy, sell, get_positions, get_trades, suggest_order_from_signal}`
- ~~`backtest.run_candidate_pool`~~（backtrader 候选池路径,Phase 8 已弃并清理;回测走
  `backtest.{create_run,append_actions,complete_run,run_historical}` 的 qlib 两段式)

### 6.2 新增（约 27 个）

> ⚠️ **此清单是 Phase 0 的早期草案,方法名已与实现漂移**(如实际是
> `scorecard.{append,score_pending,list_skill}`+`darwinian.{compute,get_weights}`、
> `mirofish.{generate_scenarios,score_recommendation,record_run,get_history,save_context,get_context}`、
> `janus.{run_daily,regime,...}`)。**权威的现行 RPC 契约见各 §11.x 子节 + `mosaic-ts/src/bridge/types.ts`
> 头部(13 namespaces / 62 methods)。** 下表仅留作历史草案。

```
# Scorecard
scorecard.record_recommendation(agent, ticker, action, conviction, date, cohort)
scorecard.score_pending(date)              # 给所有 5/21 天到期的推荐评分
scorecard.get_weights(cohort?)             # 当前 Darwinian 权重
scorecard.get_history(agent, cohort, days?)
scorecard.get_sharpe(agent, cohort, window=30)

# Autoresearch
autoresearch.trigger(cohort?, force_agent?)
autoresearch.evaluate_pending()
autoresearch.get_log(cohort?, days?)
autoresearch.list_active_branches()
autoresearch.revert_modification(modification_id)

# PRISM
prism.list_cohorts()
prism.train_cohort(cohort_name, start_date?, end_date?, dry_run?)
prism.cohort_status(cohort_name)
prism.compare_cohorts(metric=sharpe, since_date)

# JANUS
janus.blend_today(date, cohort_outputs)
janus.regime_signal(window_days=30)
janus.update_weights()
janus.get_history(days?)

# MiroFish
mirofish.generate(date, scenario_count=5, days_ahead=30)
mirofish.simulate(scenario_id)
mirofish.score(scenario_id, actual_outcomes)
mirofish.get_context(date)
mirofish.train_on_scenarios(agent, scenarios)

# Prompts (autoresearch 写入对象)
prompts.read(agent, cohort, lang)
prompts.write(agent, cohort, lang, content, branch?)
```

---

## 7. SQLite Schemas

```sql
-- ============== scorecard ==============
CREATE TABLE recommendations (
  id INTEGER PRIMARY KEY,
  cohort TEXT NOT NULL,
  agent TEXT NOT NULL,
  ticker TEXT NOT NULL,
  date DATE NOT NULL,
  action TEXT NOT NULL,                      -- BUY/SELL/HOLD/...
  conviction REAL,
  target_weight_pct REAL,
  rationale_snapshot TEXT,
  forward_return_5d REAL,                    -- NULL until scored
  forward_return_21d REAL,
  alpha_5d REAL,                             -- 相对基准
  scored_at DATETIME,
  UNIQUE(cohort, agent, ticker, date)
);
CREATE INDEX idx_rec_pending ON recommendations(scored_at) WHERE scored_at IS NULL;

CREATE TABLE darwinian_weights (
  id INTEGER PRIMARY KEY,
  cohort TEXT NOT NULL,
  agent TEXT NOT NULL,
  date DATE NOT NULL,
  weight REAL CHECK (weight >= 0.3 AND weight <= 2.5),
  rolling_sharpe_30 REAL,
  rolling_sharpe_90 REAL,
  quartile INTEGER,
  UNIQUE(cohort, agent, date)
);

-- ============== autoresearch ==============
CREATE TABLE prompt_versions (
  id INTEGER PRIMARY KEY,
  cohort TEXT NOT NULL,
  agent TEXT NOT NULL,
  branch_name TEXT NOT NULL,                 -- e.g. cohort/euphoria_2021/auto/cro/2024-01-15
  base_commit_hash TEXT NOT NULL,
  modification_commit_hash TEXT NOT NULL,
  modification_summary TEXT,                 -- LLM 生成的修改说明
  created_at DATETIME NOT NULL,
  status TEXT NOT NULL,                      -- pending/keep/revert
  decided_at DATETIME,
  pre_sharpe REAL,
  post_sharpe REAL,
  delta_sharpe REAL
);
CREATE INDEX idx_pv_pending ON prompt_versions(status, created_at) WHERE status = 'pending';

CREATE TABLE autoresearch_log (
  id INTEGER PRIMARY KEY,
  prompt_version_id INTEGER REFERENCES prompt_versions(id),
  event TEXT NOT NULL,                       -- triggered/mutated/evaluated/kept/reverted
  detail TEXT,
  created_at DATETIME NOT NULL
);

-- ============== cohort ==============
CREATE TABLE cohort_runs (
  id INTEGER PRIMARY KEY,
  cohort TEXT NOT NULL,
  date DATE NOT NULL,
  cycle_started_at DATETIME,
  cycle_completed_at DATETIME,
  llm_calls INTEGER,
  llm_cost_usd REAL,
  cio_action TEXT,
  cio_target_weight REAL,
  notes TEXT,
  UNIQUE(cohort, date)
);

-- ============== janus ==============
CREATE TABLE janus_history (
  id INTEGER PRIMARY KEY,
  date DATE NOT NULL UNIQUE,
  cohort_weights JSON,                       -- { "bull_2007": 0.3, "crisis_2008": 0.5, ... }
  regime TEXT,                               -- NOVEL/HISTORICAL/MIXED
  blended_actions JSON
);
```

**存储位置**：`<repo>/data/mosaic.db`（受 `MOSAIC_DATA_DIR` env 控制；默认在
项目根 data/ 下）。autoresearch 数据每天 backup 到 `data/backups/` 防止误删。

---

## 8. Git Autoresearch 分支策略

```
main                                            ← cohort_default 初始 prompt（手写）
├── cohort/bull_2007/main                       ← cohort 演化 trunk
│   ├── cohort/bull_2007/auto/cro/2024-01-15   ← 单次 modification feature branch
│   ├── cohort/bull_2007/auto/cio/2024-01-22
│   └── ...
├── cohort/crisis_2008/main
├── cohort/bull_2016/main
├── cohort/crisis_covid/main
├── cohort/recovery_2020/main
├── cohort/euphoria_2021/main                   ← 启动 cohort
└── cohort/rate_tightening/main
```

### 协议

1. autoresearch trigger → 在 `cohort/<name>/main` 上创建 feature branch
2. 修改单个 agent prompt 文件 → commit
3. SQLite 记录 `prompt_versions(status=pending)`
4. 5 个交易日后 evaluate：
   - **keep** → fast-forward merge feature → `cohort/<name>/main`，删 feature branch
   - **revert** → 删 feature branch（不影响主线）
5. 周期性 rebase main 到所有 cohort 主线（仅在用户手动触发"upgrade base prompts"时）

### 约束（用户已同意）

- 同一 agent **24 小时内最多 1 次新 mutation**
- **3 天内不能撤销 keep 的 mutation**（即不能立刻 revert 一个刚 merge 的 commit）
- Keep 阈值：**Δ Sharpe > 0.1**（不只是 > 0），避免微小波动触发 keep
- 月度修改次数上限：每 cohort × 25 agent 总和不超过 100 次/月

---

## 9. 7 个 Cohort 时段配置

```
1. bull_2007        2006-01-04 → 2007-10-16    牛市顶 6124 ⭐ A 股本土
2. crisis_2008      2007-10-17 → 2008-10-28    暴跌 70%，1664 见底 ⭐ A 股本土
3. bull_2016        2016-01-29 → 2017-12-29    慢牛 + 白酒
4. crisis_covid     2018-10-19 → 2020-03-23    贸易战 + 疫情合并
5. recovery_2020    2020-03-24 → 2020-12-31    疫后宽松反弹
6. euphoria_2021    2020-07-01 → 2021-02-18    茅指数高峰（启动 cohort）
7. rate_tightening  2022-04-01 → 2023-12-31    中特估 + 量化退潮 + Fed 加息
```

**启动顺序**：先 **euphoria_2021**（数据深度好 + 风格鲜明）打通 Phase 2-4
全套，验证后 Phase 5 展开剩余 6 cohort。

---

## 10. 双语 Prompt 结构

### 10.1 文件布局

```
prompts/mosaic/
├── README.md                                      # 各 cohort 训练状态/进度
├── cohort_default/                                # 初始 prompt（未训练）
│   ├── macro/
│   │   ├── central_bank.zh.md
│   │   ├── central_bank.en.md
│   │   └── ... (10 × 2)
│   ├── sector/ (7 × 2)
│   ├── superinvestor/ (4 × 2)
│   └── decision/ (4 × 2)
├── cohort_bull_2007/
├── cohort_crisis_2008/
├── cohort_bull_2016/
├── cohort_crisis_covid/
├── cohort_recovery_2020/
├── cohort_euphoria_2021/
└── cohort_rate_tightening/
```

### 10.2 TS 端 builder

每个 agent 一个 `.ts` 文件，构造函数接收 `language: "Chinese" | "English" | "Bilingual"`：

```ts
export function buildCentralBankSystemMessage(ctx: PromptContext): string {
  const ROLE_ZH = await loadPrompt("central_bank", ctx.cohort, "zh");
  const ROLE_EN = await loadPrompt("central_bank", ctx.cohort, "en");

  if (ctx.outputLanguage === "Bilingual") {
    return `${ROLE_ZH}\n\n---\n\n${ROLE_EN}\n\n${SHARED_RULES}`;
  }
  return ctx.outputLanguage === "Chinese" ? ROLE_ZH : ROLE_EN;
}
```

### 10.3 切换方式

- **CLI**：`--lang zh` / `--lang en` / `--lang bilingual`
- **TUI**：`Ctrl+L` 动态切换
- **默认**：`Chinese`

外部 markdown 文件是 autoresearch mutation 的对象（Python 端
`read_prompt_file(agent, cohort, lang)` 读取，TS 通过 RPC `prompts.read`
拉取）。

---

## 11. Phase 0 详细任务（Day 1-5）

### Day 1：Bridge 骨架 ✅ 2026-05-28
- [x] 0.1.1 创建 `mosaic/` Python 包骨架
- [x] 0.1.2 复制 `etfagents/__init__.py` + `default_config.py` → `mosaic/`，改名
      （并将默认 LLM 切到 `anthropic` + `output_language=Chinese`，新增 cohorts 表 +
      autoresearch 约束块）
- [x] 0.1.3 复制 `etfagents/bridge/` 全部 → `mosaic/bridge/`（5 文件 + handlers/ 子包，
      `etfagents` → `mosaic` 改名）
- [x] 0.1.4 改 `mosaic/bridge/handlers/__init__.py` 的 import 路径；所有跨包 import
      改为 lazy + 在 `ImportError` 时返回友好的 `CONFIG_ERROR / PAPER_ERROR /
      BACKTEST_ERROR` + 阶段提示，让后续 Phase 增量 land 时不破坏 bridge
- [x] 0.1.5 跑 `python -m mosaic.bridge` 验证：
      * 21 个方法注册成功（`tools.{list,call}` + `config.{default,get,set}` +
        `cache.{stats,cleanup,clear,details}` + `paper.*`(11) + `backtest.run_candidate_pool`）
      * `tools.list` → `[]`（Day 4 才有 tool 模块）
      * `config.default` → 完整配置（含 7 cohorts + autoresearch 约束）
      * 未知方法 → `METHOD_NOT_FOUND`
      * 无效 JSON → `PARSE_ERROR`
      * `cache.stats` → `CONFIG_ERROR` 带 "Phase 0 Day 2" 阶段提示

**Day 1 产出**：
- `MOSAIC-Agents/.gitignore` `.env.example` `pyproject.toml` `README.md`
- `MOSAIC-Agents/mosaic/__init__.py` `default_config.py`
- `MOSAIC-Agents/mosaic/bridge/{__init__,__main__,server,protocol,registry}.py`
- `MOSAIC-Agents/mosaic/bridge/handlers/{__init__,tools,config,cache,paper,backtest}.py`
- `.venv/` 已建（Python 3.11.15 via uv），`langchain-core==1.4.0` + `python-dotenv==1.2.2` 已安装

**Day 1 → Day 2 待办**：移植 `etfagents/dataflows/`（除 `fred/macro_data` 外）+
`cache_manager.py` + 新写 `mosaic/dataflows/fred.py`。届时 `config.get/set` /
`cache.*` 全部从 `CONFIG_ERROR` 转为正常工作。

### Day 2：FRED + dataflows ✅ 2026-05-28
- [x] 0.2.1 复制 `etfagents/dataflows/` 全部（除 fred/macro_data 外）
      （20 文件，全部相对 import 无需修改；唯一调整：`config.py` 把
      `import etfagents.default_config` → `import mosaic.default_config`，
      `ContextVar` 名 `etfagents_*` → `mosaic_*`）
- [x] 0.2.2 复制 `etfagents/cache_manager.py`
      （唯一调整：`cache.clear("checkpoints")` 把 `from etfagents.graph.checkpointer
      import clear_all_checkpoints` 改为 try/except 包裹的 lazy import；
      `mosaic.graph` 在 Phase 2 落地前用 rmtree 兜底）
- [x] 0.2.3 新写 `mosaic/dataflows/fred.py`（343 LOC）：
      * `load_dotenv` 读 `FRED_API_KEY`（缺失抛 `DataVendorUnavailable`，让 fallback 链生效）
      * `_fetch_series_dataframe(...)` 返回 `pandas.DataFrame`（私有，测试 + macro_tools 用）
      * `get_fred_series(...)` 返回 CSV 字符串（vendor 契约，被 `route_to_vendor` 调用）
      * 限速：`_SlidingWindowLimiter` 实现 120 req/min 滑动窗口（线程安全）
      * 磁盘缓存：`{data_cache_dir}/fred/{series_id}_{start}_{end}.json`，24h TTL
      * `clear_cache()` helper（用于测试 + 后续 `cache.clear("api")` 集成）
- [x] 0.2.4 改 `mosaic/dataflows/interface.py` 加 FRED 路由：
      * 新增 `from .fred import get_fred_series as get_fred_series_impl`
      * `TOOLS_CATEGORIES["macro_data"]` 类目占位（Day 3 填充其他 7 个 macro tool）
      * `VENDOR_LIST` 加 `"fred"`
      * `VENDOR_METHODS["get_fred_series"] = {"fred": get_fred_series_impl}`
      * `_RANGE_DATE_METHODS["get_fred_series"] = (1, 2)` 让 backtest_context 正确 clamp end_date
- [x] 0.2.5 写 `tests/test_fred.py`（277 LOC）：
      * 19 个测试，**15 passed + 4 skipped**（live integration 在 `FRED_API_KEY` 缺失时跳过）
      * 覆盖：input validation、CSV 输出、DataFrame 输出、FRED 错误负载、HTTP 失败、
        cache 命中/失效/清理、限速器在容量内/超容量行为
      * 用 `monkeypatch + unittest.mock` 完全 hermetic（无网络）
      * 装了 `pandas==3.0.3` + `pytest==9.0.3` 作为 Day 2 测试依赖
- [x] 0.2.6 端到端 bridge 验证：
      * `config.get` / `config.set`：从 Day 1 的 `CONFIG_ERROR` → 正常工作（设 `output_language=English`、
        `active_cohort=crisis_2008` 后从响应里读回）
      * `cache.stats`：返回 `{api: 0, signals: 0, snapshots: 0, checkpoints: 0, total_mb: 0}`，
        `subdirs=["fred"]`（fred.py 早期烟雾测试创建）
      * `cache.cleanup` / `cache.details`：响应正常
      * `tools.list` 仍为 `[]`（Day 4 才加 macro_tools）

**Day 2 → Day 3 待办**：写 `mosaic/dataflows/macro_data.py`（~400 LOC）
覆盖 PBOC/北向/龙虎榜/中国国债曲线/中美利差/雪球/产业政策 7 个 A 股本地数据源。
届时安装 `[data]` extras（pandas + tushare + akshare + yfinance + stockstats + pytz）
让 `mosaic.dataflows.interface` 端到端 import 通过。

### Day 3：Macro data 接口 ✅ 2026-05-28
- [x] 0.3.1 写 `mosaic/dataflows/macro_data.py`（527 LOC）：
  - `get_pboc_ops(curr_date, look_back_days=7)` 央行公开市场操作（Tushare `cb_op`）
  - `get_north_capital_flow(start_date, end_date)` 沪/深股通净买入（Tushare `moneyflow_hsgt`）
  - `get_lhb_ranking(curr_date)` 龙虎榜（Tushare `top_list`）
  - `get_yield_curve_cn(curr_date, look_back_days=30)` 中国国债曲线（Tushare `yc_cb`，curve_type=0）
  - `get_us_china_spread(curr_date, look_back_days=30)` 中美 10Y 利差（合成：FRED `DGS10` + Tushare `yc_cb` 10y，按日期 inner join，spread_bps = (us-cn)*100）
  - `get_xueqiu_heat(ticker=None, top_n=30)` 雪球热度（AkShare `stock_hot_search_xq`，可按 ticker filter）
  - `get_industry_policy(curr_date, look_back_days=7, keywords=...)` 政策公告（Tushare `news` + 政策关键词过滤；plan 里写的 `anns_d` 是公司公告，不是政策新闻，故走更高召回的 `news` + filter）

  共享 helper：`_validate_iso_date`, `_to_tushare_date`, `_date_range_from_lookback`,
  `_query_tushare`（lazy import 复用 `tushare._query_pro` 的 retry/backoff），
  `_df_to_markdown_csv`（统一 CSV 输出，含空帧友好提示）。
  所有 public 函数返 str（vendor 契约）；缺 token / bad input / endpoint 失败 → `DataVendorUnavailable`。

- [x] 0.3.2 写 `tests/test_macro_data.py`（401 LOC）：
  - 30 个测试，**28 passed + 2 skipped**（live integration 在 `TUSHARE_TOKEN` 缺失时跳过）
  - 覆盖：shared helpers / 7 个函数 × {正常输出, 空帧, 输入校验, 失败回退}
  - `_extract_cn_10y_yield` 同时支持 `curve_term` 和 `ts_code="10.0000.CB"` 两种 schema
  - us_china_spread 测试合成路径（验证日期 inner join + bps 计算）+ 缺 FRED leg 失败路径
  - Xueqiu 测试通过 monkeypatch `sys.modules['akshare']` stub，无需真装
  - **当日全套 49 tests = 43 passed + 6 skipped**（FRED 4 + Tushare 2）

- [x] 0.3.3（计划内顺带做）改 `mosaic/dataflows/interface.py` 加 macro_data 路由：
  - `TOOLS_CATEGORIES["macro_data"].tools` 扩展为 8 个 (`get_fred_series` + 7 macro)
  - `VENDOR_LIST` 加 `"akshare"`
  - 7 个 macro 函数加进 `VENDOR_METHODS`（`get_us_china_spread` 同时挂 `tushare` + `fred` 共享 callable，因为它本身就是合成）
  - 日期路由：`get_north_capital_flow` → `_RANGE_DATE_METHODS`；
    `get_pboc_ops / get_lhb_ranking / get_yield_curve_cn / get_us_china_spread / get_industry_policy` →
    `_CURRENT_DATE_METHODS`；`get_xueqiu_heat` → `_UNBOUNDED_BACKTEST_METHODS`（实时数据，回测期阻塞）
  - `mosaic.dataflows.interface` 现共有 **26 个 VENDOR_METHODS** 跨 9 个 category

**Day 3 → Day 4 待办**：写 `mosaic/agents/utils/macro_tools.py`（10 个 `@tool`-decorated 函数包装 macro_data + fred），把 `_TOOL_MODULES` 加到 `bridge/handlers/tools.py`。届时 `tools.list` 应返 ≥10 条，`tools.call(get_pboc_ops, ...)` 在线（需要 `TUSHARE_TOKEN`）能拉真实数据。

**§14 新增议题**（来自 Day 3）：
- Tushare 端点名 `cb_op` / `yc_cb` 与 plan §11 文字对齐，但**未实弹验证**。Day 5
  端到端测试时若发现实际名为 `cb_open_op` / 类似变体，仅需改 `macro_data.py`
  调用点（VENDOR_METHODS / 测试 mock 自动生效，因为 mock 替换的是
  `_query_pro`，与 endpoint 名解耦）。
- `get_industry_policy` 走 `news` + 关键词过滤；plan §11 文字写 `anns_d`，但
  `anns_d` 在 Tushare 实为公司公告（issuer-level filings）。这是设计偏离 plan
  的地方，已在函数 docstring 里记录。Day 5 验证后若发现存在更精确的 "政策新闻"
  endpoint（如 `cctv_news` 联播专题），可以在不破坏接口的前提下迁移过去。

### Day 4：Macro tools 包装 ✅ 2026-05-28
- [x] 0.4.1 写 `mosaic/agents/utils/macro_tools.py`（321 LOC）：
  - 8 个 `@tool`-decorated 函数（`get_fred_series` + 7 macro_data 函数）
  - 每个 tool 用 `typing.Annotated` 给参数加描述，docstring 完整 Args/Returns
  - 全部委托给 `mosaic.dataflows.interface.route_to_vendor`，自动获得：
    backtest 上下文裁剪 + vendor 路由 + 配置驱动的 fallback 链
  - 沿用 `etfagents/agents/utils/*_tools.py` 模式（`from langchain_core.tools import tool`）
  - **注**：plan §11 写"10 个"，但 macro_data.py 只有 7 个 + fred 1 个 = 8 个。
    plan 数字偏离了实际函数表，已纠正记录在此。

  并补建 `mosaic/agents/__init__.py` 和 `mosaic/agents/utils/__init__.py` 子包。

- [x] 0.4.2 把 `"mosaic.agents.utils.macro_tools"` 加进
  `mosaic/bridge/handlers/tools.py:_TOOL_MODULES`。bridge `tools.list` 现在返回 **8 个工具**，
  每个含完整 Pydantic v2 `args_schema`（含 `Annotated` 描述）。

- [x] 0.4.3 写 `tests/test_macro_tools.py`（298 LOC，44 个测试 全绿）：
  - **Registration**：每个工具都是 `BaseTool` 实例，`__all__` 完整，
    bridge `_iter_module_tools` 能发现全部 8 个，`_TOOL_MODULES` 含路径
  - **Schemas**：每个工具的 args_schema 属性集合 / required 集合 / 描述都正确
  - **Dispatch**：`.invoke({...})` 正确把 args 转成 positional 调 `route_to_vendor`
    （含默认值场景，9 条 dispatch 用例覆盖全部 8 个工具）
  - **Bridge handler**：`tools_list({})` 返 8 项；`tools_call(...)` 经
    `route_to_vendor` 派发；未知 tool → `METHOD_NOT_FOUND`；非 dict args →
    `INVALID_PARAMS`；底层 `DataVendorUnavailable` → `DATA_VENDOR_UNAVAILABLE`；
    缺 required arg → `TOOL_EXECUTION_ERROR/INVALID_PARAMS` 含 Pydantic 错误细节

- [x] 0.4.4（端到端 smoke）实跑 `python -m mosaic.bridge` 6 个真实 JSON-RPC 请求：
  ```
  tools.call get_fred_series  → DATA_VENDOR_UNAVAILABLE (FRED_API_KEY 未配)
  tools.call get_pboc_ops     → TOOL_EXECUTION_ERROR (TUSHARE_TOKEN 未配)
  tools.call get_xueqiu_heat  → 暴露真实问题 (见下)
  tools.call missing arg      → ValidationError 透出 Pydantic 详细信息
  tools.call unknown tool     → METHOD_NOT_FOUND
  tools.call backtest mode    → 阻塞 get_xueqiu_heat（_UNBOUNDED_BACKTEST_METHODS）
  ```
  另用 mock 注入 `sys.modules['akshare']` 跑通了 get_xueqiu_heat 的完整链路：
  bridge → `@tool` wrapper → `route_to_vendor` → `macro_data.get_xueqiu_heat` →
  akshare → DataFrame → CSV → JSON-RPC `result.text`，返回真 CSV 内容。

**当日全套测试：87 passed + 6 skipped**（macro_data 30 + macro_tools 44 + fred 19 - 6 live）。

**Day 4 → Day 5 待办**：
- 复制 `etfagents/tests/test_bridge_protocol.py` 模板适配 mosaic 包名
- 端到端 smoke：spawn `python -m mosaic.bridge`，实际配 `TUSHARE_TOKEN` /
  `FRED_API_KEY`，跑 `tools.call(get_north_capital_flow, ...)` 拿真数据
- 把已收敛的 §14 议题（Tushare endpoint 名 / akshare endpoint 名）做 live 验证

**§14 新增议题**（Day 4 实弹暴露 + 已修复）：
- AkShare 端点名 `stock_hot_search_xq` 在 1.18.x **不存在**。Day 4 端到端测试触发
  `AttributeError: module 'akshare' has no attribute 'stock_hot_search_xq'`。
  探查 akshare 真实接口后切换到 `stock_hot_follow_xq(symbol="最热门")`，schema
  为 `["股票代码", "股票简称", "关注", "最新价"]`（股票代码格式 `SH600519`，与
  Tushare 的 `600519.SH` 不同，过滤逻辑做了 substring 匹配适配）。
- 这次实弹暴露说明：Day 5 必须做 **每个 vendor endpoint 的真调用** 验证，不能只信 mock。
  Tushare 的 `cb_op` / `yc_cb` / `news` 仍未真实验证；Day 5 跑通时若发现实际名异，
  调整 `mosaic/dataflows/macro_data.py` 调用点即可（mock 测试不变）。

### Day 5：Bridge 集成测试 ✅ 2026-05-29
- [x] 0.5.1 复制 `etfagents/tests/test_bridge_protocol.py` 模板，
      适配 mosaic 包名 → `tests/test_bridge_protocol.py`（458 LOC）。
      - **Layer 1（14 个协议契约测试）**：每测试 spawn 一个 `python -m mosaic.bridge`
        子进程做 hermetic 隔离；tempdir 包 cache/results。覆盖 tools.list / tools.call
        (unknown / invalid / backtest-blocked) / config.{default,get,set} / cache.stats /
        cache.cleanup / paper.{current_user,buy,suggest_order_from_signal} / backtest
        validation / unknown method / parse-error 不杀服务。
      - **Layer 2（5 个 macro tool 子进程测试 + 1 个 live smoke）**：
        每个 macro tool 都有完整 args_schema；`get_fred_series` 缺 required 抛
        Pydantic ValidationError；缺 `TUSHARE_TOKEN` 时 `get_pboc_ops` 返干净错误码且
        bridge 仍能服务后续请求；`get_xueqiu_heat` 在 backtest mode 被 `_UNBOUNDED_BACKTEST_METHODS`
        阻塞；`get_north_capital_flow` 错误日期格式抛 YYYY-MM-DD 提示。
      - **§14 议题处理**：paper.* 在 Phase 8 才 port，handler 立 stub → `-32020 PAPER_ERROR`
        含 "Phase 8" 字样。Day 5 测试明确锁这个契约（用 `assertEqual(err["code"], -32020)`）。

- [x] 0.5.2 端到端 smoke：
      `test_get_north_capital_flow_live` 用 `@unittest.skipUnless(os.getenv("TUSHARE_TOKEN") ...)`
      gating，spawn 真实 bridge 子进程，发送 `tools.call(get_north_capital_flow, start_date=2024-06-03, end_date=2024-06-07)`，
      断言 result.text 含 `"沪深股通"` + `"moneyflow_hsgt"` 头 + 数据行 / 空窗口提示。
      **当前用户环境未配 `TUSHARE_TOKEN`，该 case 在 Phase 0 收尾时被 skip**；测试结构就位，
      用户后续 `export TUSHARE_TOKEN=...` 再跑就能验证真实数据来回。

- [x] 0.5.3 Phase 0 完成确认：
      - **测试统计**：113 tests = **106 passed + 7 skipped**（4 FRED live + 2 Tushare live + 1 bridge live smoke）
      - bridge 21 RPC 方法注册成功，8 个 macro tool 出现在 `tools.list`
      - `mosaic.dataflows.interface` 共 26 VENDOR_METHODS / 9 categories
      - 文档：plan §3 Phase 0 状态切到 ✅
      - **Phase 0 LLM 成本：$0**（不涉及 LLM 调用，全部测试 + 校验跑在本地）

**Phase 0 综合产出统计**：

| 类别 | LOC | 数量 |
|---|---|---|
| 移植自 ETFAgents（dataflows + cache_manager + bridge 模板） | ~7,300 | 22 文件 |
| 新写 mosaic 代码（FRED + macro_data + macro_tools + bridge 适配） | ~1,890 | 12 文件 |
| 新写测试 | ~1,440 | 5 文件 |
| 文档 + 配置 | ~500 | 5 文件 |
| **合计** | **~11,100** | **44 文件** |

**Phase 0 → Phase 1 待办**：TS skeleton + bridge-client。直接复用 ETFAgents Phase 1 的
`ts/src/bridge/` (~700 LOC) + `ts/src/llm/factory.ts` (~120 LOC)，建 `mosaic-ts/` 工作区。
Phase 0 §14 议题中 Tushare endpoint 名 `cb_op` / `yc_cb` / `news` 的 live 验证留待用户配
`TUSHARE_TOKEN` 后跑 `pytest tests/test_macro_data.py::TestLiveTushare` 完成。

---

## 11.2 Phase 2 详细任务（Sub-step 2A–2F）

> 估算 11–12 turns，~8,600 LOC TS。
> 分支：`phase-2-daily-cycle-mvp`（已建，内含 Phase 1 review follow-ups 收口
> commit `e74b766` + Lemonade port fixup `e0c3142`）。
> 目标：跑通单 cohort（`cohort_default`）的 daily cycle MVP，4 层 25 agents
> 在 LangGraph.js 上完整调度一次，输出可读报告。

### 关键设计决策（写在前面以免后续走偏）

1. **State 形状**：MOSAIC 不沿用 ETFAgents 的 flat-30-key state（25 agents flat
   会爆到 40+ field 太吵）。改用 **per-layer output maps keyed by agent ID**，
   reducer 用 dict-merge（`{...prev, ...next}`）。这样：
   - 多个 L1 agents 可以并发往 `layer1_outputs` 写入而不冲突
   - 状态 key 数从 40+ 降到 ~12
   - 每层有一个 aggregated consensus（`layer1_consensus: RegimeSignal | null`
     等）由 layer-end aggregator 节点写入
   ```ts
   // mosaic-ts/src/agents/state.ts 概念
   {
     active_cohort: string;           // "cohort_default" / "cohort_euphoria_2021"
     as_of_date: string;              // YYYY-MM-DD; "" 表示 live
     mode: "live" | "backtest";
     // memory（沿用 ETFAgents pattern）
     continuity_context: Record<string, string>;
     lesson_context: Record<string, string>;
     method_context: Record<string, string>;
     // layer outputs（dict-merge reducer）
     layer1_outputs: Record<string, MacroAgentOutput>;
     layer1_consensus: RegimeSignal | null;
     layer2_outputs: Record<string, SectorAgentOutput>;
     layer2_consensus: SectorConsensus | null;
     layer3_outputs: Record<string, SuperinvestorOutput>;
     layer4_outputs: { cro, alpha_discovery, autonomous_execution, cio };
     // observability
     llm_calls: LlmCallRecord[];      // append reducer
     trace_id: string;
   }
   ```

2. **Output 类型**：state.ts 只用 TS interface（编译期）；运行期 Zod schema 跟
   每个 agent 定义在 `agents/<layer>/<agent>.ts` 旁边。`z.infer` 桥接两端。

3. **Cohort path resolver**：fallback 链 `cohort_xxx/<layer>/<agent>.<lang>.md`
   缺失则回 `cohort_default/<layer>/<agent>.<lang>.md`。让 PRISM (Phase 5) 训练
   后的 cohort prompt 与未训练的 cohort 共享 baseline。

4. **2A 范围控制**：只创建 1 对 prompt 占位（`central_bank.{zh,en}.md`）作为
   loader 测试 fixture；剩余 24 对（48 个 .md）随 2C/2D 各 agent wire-up 时创建。
   避免 2A 一上来就有 50 个空模板文件污染 diff。

5. **Phase 2 不做 cohort 切换 UI**：plan §1 启动 cohort 是 `euphoria_2021`，但
   Phase 2 全程跑 `cohort_default` 基线 prompt（plan §10.1）。Cohort 切换机制
   留 Phase 5 PRISM 落地。

### Sub-step 2A：Foundation（拆 2A.1 + 2A.2 两个 commit）

**2A.1 — State + 路径 + scaffold**
- [ ] 创建 `prompts/mosaic/cohort_default/{macro,sector,superinvestor,decision}/`
      目录骨架（含 `.gitkeep`）
- [ ] 创建 fixture：`prompts/mosaic/cohort_default/macro/central_bank.{zh,en}.md`
- [ ] 写 `mosaic-ts/src/agents/types.ts` —— layer-1/2/3/4 output 接口（per Plan §5）
- [ ] 写 `mosaic-ts/src/agents/state.ts` —— LangGraph.js Annotation root + 12 fields
      with reducers
- [ ] 写 `mosaic-ts/src/agents/prompts/cohorts.ts` —— path resolver +
      `findPromptsRoot()` (under repoRoot/prompts/mosaic/)
- [ ] 写 `mosaic-ts/src/agents/prompts/loader.ts` —— `loadPrompt({agent, layer,
      cohort, language})` 读 .md，cache，fallback 链
- [ ] tests：`test/state.test.ts`（reducer 行为、defaults）+
      `test/prompt_loader.test.ts`（fallback 链、缺失文件错误）

**2A.2 — 移植 4 个 ETFAgents helpers**（直接复用类，~800 LOC）
- [ ] `ts/src/agents/helpers/content.ts` (60) → `mosaic-ts/src/agents/helpers/content.ts`
- [ ] `ts/src/agents/helpers/process_narration.ts` (201) → 对应路径
- [ ] `ts/src/agents/helpers/tool_report_chain.ts` (328) → 对应路径
- [ ] `ts/src/agents/helpers/structured_output.ts` (214) → 对应路径
- [ ] 测试：`test/process_narration.test.ts` 等沿用 ETFAgents 测试模板

**2A.2 设计决策**（移植中遇到的取舍，记录在前以免后续走偏）：

1. **`prompts/shared.ts`、`schemas/rating.ts` 不整体 port**：tool_report_chain 只
   依赖 `getNoProcessNarrationInstruction`，structured_output 只依赖 `isChinese`。
   抽出 2 个小工具到 `helpers/`：
   - `helpers/i18n.ts`：包 `isChinese()`（从 schemas/rating.ts 取出）
   - `helpers/prompt_snippets.ts`：包 `getNoProcessNarrationInstruction()`
   避免把 ETFAgents 的 ETF 专用 prompt（buildInstrumentContext 等）拉进来。

2. **structured_output.ts: structured-only sentences 改为参数注入**：ETFAgents
   把 3 个 trader 专用 sentence（`STRUCTURED_FIELD_POPULATION_INSTRUCTION` 等）
   硬编码进 `STRUCTURED_ONLY_SENTENCES`，提到 `target_weight_pct` / `add_triggers`
   这些 ETF 字段。MOSAIC 25 agents 各有不同 schema 字段，必须改成 caller 注入。
   API 变化：
   ```ts
   // ETFAgents (硬编码)
   stripStructuredOnlyText(text)  // 内部 STRUCTURED_ONLY_SENTENCES
   // MOSAIC (参数化)
   stripStructuredOnlyText(text, sentencesToStrip: ReadonlyArray<string>)
   ```
   `bindStructured` / `buildProseOnlyFallbackPrompt` / `invokeStructuredOrFreetext`
   都加一个可选 `structuredOnlySentences` 参数，默认空数组。每个 agent 自己定义
   并传入 schema-only sentences。

3. **保留 ETFAgents 的 regex 字面量**：`process_narration.ts` 的中英文 process-
   narration 正则是经过 ETFAgents 真实样本调过的，verbatim 复制（不改一字）。
   后续 MOSAIC 25 agent 跑下来如果发现新 false-positive 模式，回到这里加分支。

### Sub-step 2B：Vertical slice（central_bank 端到端）

证明 1 个 agent 走完 prompt → tool → schema → node → state.write 完整链路。
其他 24 agents 按这个模板批量做。

- [ ] 写完 `central_bank` 真 prompt（zh + en，不再 placeholder）
- [ ] `mosaic-ts/src/agents/layer1/central_bank.ts` —— Zod output schema +
      build node function（接 BridgeClient + LLM + 3 个工具：`get_pboc_ops` /
      `get_fred_series(FEDFUNDS)` / `get_yield_curve_cn`）
- [ ] node 内：load_prompt → bind_tools → tool_loop（复用 Phase 1 的 runToolLoop
      逻辑，可能要 extract 出 helper）→ structured_output 解析 → 写入
      `layer1_outputs.central_bank`
- [ ] vitest 用 mock LLM + mock BridgeApi 验证完整流转

**2B 设计决策**（在写 central_bank 之前定，避免后续 24 agents 反工）：

1. **Two-phase agent execution**：每个 agent 节点先跑工具循环拿到自由分析文本
   （phase 1：tool-bound LLM + iterative tool calls），再跑结构化抽取
   （phase 2：用 phase-1 的分析当 user input 喂给 `invokeStructuredOrFreetext`）。
   不在同一次 LLM call 里同时 bind tools + structured output —— 多数 provider
   不支持这种组合，强行做会让 schema 解析失败率飙升。

2. **2B 不做 factory 抽象**：先把 `central_bank` 写成具体函数（不复用 generic
   `buildAgentNode<T>`）。等 2C 拿一个跑通的实现做参照，再抽 factory，避免
   factory 设计错了 2C 重写 9 次。

3. **`runAgentToolLoop` 小 helper**：放 `helpers/agent_loop.ts`，~100 LOC。
   `runToolReportChain` 假定 LangGraph-level loop；2B 还没装图，需要一个
   inline 循环 helper。2E 装图时这个 helper 可能让位给 LangGraph subgraph，
   不阻塞。

4. **目录布局**：`src/agents/macro/central_bank.ts` 对齐 prompt 目录
   `prompts/mosaic/cohort_default/macro/`，agent ID = 文件名。共享 schema 进
   `src/agents/macro/_schemas.ts`（前缀 `_` 避免被误认为 agent 文件）。

5. **结构化抽取的 system prompt**：phase-2（structured extractor）单独写一段
   "你只负责把下面的分析文字抽成 JSON 字段"，不复用 phase-1 system message。
   原因：phase-1 system 包含工具使用规则、写作风格约束等，对 schema 抽取无关
   且容易让 model 多写解释性 prose 干扰 JSON。

6. **Layer-1 输出契约**：`MacroAgentOutputBase` 的 `confidence` + `key_drivers`
   是聚合器（aggregateLayer1）必读字段。Schema 必须把这两项标 `.describe()` 让
   LLM 看到约束。否则 RegimeSignal 的 `layer_1_consensus_score` 计算会带噪。

### Sub-step 2C：Layer 1 剩余 9 macro agents + aggregator

按 2B pattern 批量做：
- [ ] 9 × {prompt zh+en, schema, node, test} = 27 deliverables
- [ ] `aggregateLayer1` 节点：把 10 个 `MacroAgentOutput` 合成 `RegimeSignal`
- [ ] LangGraph 局部装配：10 macro nodes 并发 → aggregator → 写
      `layer1_consensus`

**2C 拆 3 个子提交**（一气干完容易失控）：

* **2C.1** — factory 抽象 + china（第 2 个 agent，证明 factory 可复用）
* **2C.2** — 剩余 8 个 macro agents 批量加（geopolitical / dollar /
  yield_curve / commodities / volatility / emerging_markets /
  news_sentiment / institutional_flow）
* **2C.3** — `aggregateLayer1` → `RegimeSignal` + LangGraph L1 fan-out
  装配（10 macro 并发 → aggregator）

**2C 设计决策**（在抽 factory 前定，避免后续 8 个 agent 反工）：

1. **`buildLayerOneAgentNode<TOutput>(spec, deps)` factory**：把 central_bank
   两阶段执行抽出来。`spec` 携带 agent-specific 配置（agentId / schema /
   fieldNames / requiredTools / render / fallback / 可选 extractor system），
   `deps` 携带 `{llmHandle, api, config, onLog?}`。Factory 内部走完
   `loadPrompt → pickBridgeTools → runAgentToolLoop → invokeStructuredOrFreetext
   → state update`。每个 macro agent 文件 ~50-80 LOC（vs 2B 的 213 LOC）。

2. **agent 文件结构**：每个 macro agent 一个 `.ts`，导出 `<agent>Spec` +
   `build<Agent>Node = (deps) => buildLayerOneAgentNode(spec, deps)`。这样：
   - 测试可以 import `<agent>Spec` 在 unit 层独立验证 spec 合法性
   - 2D 的 sector / superinvestor / decision agent 可以参考这个 pattern
     建自己的 layer-specific factory（Layer-2 工具不同，Layer-3 哲学过滤器
     系统提示不同，Layer-4 输入是上层输出而不是 BridgeApi 工具）

3. **prompts 真值密度策略**：剩余 9 个 macro agent 的 prompt 都按
   `central_bank` 同款风格写（**双工具最低要求 + 量化约束 + 输出 schema 描述
   + 写作约束**），但 prompt 长度控制在 30-60 行/语言。Phase 4 autoresearch
   会迭代这些 prompt，初版"可工作 + 输出契约清晰"即可，不追求完美措辞。

4. **`get_property_data` 不存在的临时处理**：plan §5.1 china agent 列了
   `get_property_data`，但 Phase 0 macro_data 没实现。china agent 暂用
   `get_north_capital_flow` 替代（北向资金侧面反映外资对地产/消费的态度），
   并在 plan §14 加一条 follow-up：Phase 4 autoresearch 之前补
   `get_property_data` 工具到 mosaic/dataflows/macro_data.py。

5. **Aggregator 算法（2C.3）**：`aggregateLayer1` 简单加权：
   - stance 投票：每个 agent 的 stance 字段（央行/中国/美元/曲线 → 偏多/偏空
     映射，volatility/news_sentiment 反向）按 confidence 加权得到 BULLISH /
     BEARISH / NEUTRAL
   - `layer_1_consensus_score` = mean(confidence) × stance_alignment_ratio
   - `key_drivers` 取每个 agent confidence>0.5 的最强 1 条 driver concat
   不在 2C.3 引入 LLM 二次判断（保持 deterministic，便于回测复现）。

**2C.3 设计决策**（aggregator + graph 装配前定）：

   **Stance 映射表**（每个 agent 字段 → vote {-1, 0, +1}）：
   | Agent | 字段 | +1 (BULLISH) | -1 (BEARISH) | 0 (NEUTRAL) |
   |---|---|---|---|---|
   | central_bank | stance | ACCOMMODATIVE | TIGHTENING | NEUTRAL |
   | china | policy_direction | PRO_GROWTH | RESTRAINING | BALANCED |
   | geopolitical | escalation_level | 1 / 2 | 4 / 5 | 3 |
   | dollar | dxy_trend | WEAKENING | STRENGTHENING | STABLE |
   | yield_curve | recession_signal | GREEN | RED | YELLOW |
   | commodities | china_demand_signal | ACCELERATING | DECELERATING | STEADY |
   | volatility | regime_filter | RISK_ON | RISK_OFF | NEUTRAL |
   | emerging_markets | em_relative | OUTPERFORMING | UNDERPERFORMING | INLINE |
   | news_sentiment | retail_sentiment_score + contrarian_flag | score > 0.3 且 contrarian=false | score < -0.3 OR contrarian=true 且 score>0 | 其他 |
   | institutional_flow | sum(sectors_in_out.net_amount_cny) | > +1B CNY | < -1B CNY | 中间 |

   **加权阈值**：weighted_sum / total_weight > +0.3 → BULLISH，< -0.3 → BEARISH，
   ±0.3 之间 → NEUTRAL。这个阈值偏保守，避免 10 个 agent 出现"轻度偏多"
   （比如 6 个 weak +1，4 个 weak -1）就直接喊 BULLISH。

   **`layer_1_consensus_score`**：mean_confidence × alignment_ratio。其中
   `alignment_ratio` = (与 final stance 同方向 vote 的 agent 数) / 10。
   这个数 ≤ mean_confidence，反映"agents 之间共识强度"。下游 Layer 2/3 拿
   它做 sector / superinvestor 启用门槛。

   **LangGraph fan-out 拓扑**：
   ```
   START ─┬→ central_bank ──┬→ aggregate_l1 → END
          ├→ china ─────────┤
          ├→ geopolitical ──┤
          ├→ dollar ────────┤
          ├→ yield_curve ───┤
          ├→ commodities ───┤
          ├→ volatility ────┤
          ├→ em ────────────┤
          ├→ news_sentiment ┤
          └→ institutional ─┘
   ```
   10 个 macro 节点从 START 并行扇出（LangGraph 看到多 edge from same source
   会自动并发），所有节点跑完后 fan-in 到 aggregator。`layer1_outputs` 的
   dict-merge reducer 自动收 10 个 agent 的写入。

   **2C.3 范围控制**：subgraph 终点是 END（不是 Layer 2 入口）。2D 落 sector
   agent 时把 END 换成 `layer2_subgraph_entry` 即可；Phase 2C.3 完结时
   `aggregate_l1 → END` 是合法终态，可以直接 invoke 跑出 `layer1_consensus`。

### Sub-step 2D：Layer 2/3/4（15 agents + cohort fanout 工具）

**2D 拆 3 个子提交**：
* **2D.1** — Layer 2 / 7 sector agents（含 relationship_mapper） + Layer-2 factory + L2 subgraph
* **2D.2** — Layer 3 / 4 superinvestor agents（哲学过滤器，prompts 重头戏）+ L3 subgraph
* **2D.3** — Layer 4 / 4 decision agents（cro/alpha/autonomous/cio）+ L4 subgraph

按 Plan §5.2/5.3/5.4 配置：

- [ ] Layer 2: 7 sector agents（同模板，工具用 sector-specific holdings/research）
- [ ] Layer 3: 4 superinvestor agents（哲学过滤器；prompts 重头戏）
- [ ] Layer 4: cro / alpha_discovery / autonomous_execution / cio
      （Plan §5.4，cio 是 final aggregator）
- [ ] cohort fanout helper：从 `layer1_consensus` 派生不同 cohort 的 view
      （Phase 5 PRISM 用）

**2D.1 设计决策**（Layer 2 sector agents）：

1. **Layer-2 factory 独立**（不复用 Layer-1 factory）。两点关键差异：
   - Layer 2 节点 **读上游 state**：`state.layer1_consensus` (`RegimeSignal`) +
     `state.layer1_outputs.{china, institutional_flow, ...}` 的 sector_focus
     等字段。把这些塞进 phase-1 system message context（"当前宏观 regime: ...
     sector_focus 列表：..."），让 sector agent 在选 longs/shorts 时知道
     宏观背景。
   - 写入位置不同（`layer2_outputs` vs `layer1_outputs`）；factory 的 state
     update 路径必须独立。

2. **6 个标准 sector agents 共享 schema 形态**（半导体/能源/医药/消费/工业/
   金融），都是 `{longs: SectorPick[], shorts: SectorPick[], sector_score,
   key_drivers, confidence}`。每个 agent 用 z.literal(<id>) 区分。
   `relationship_mapper` 输出形态完全不同（supply_chains / ownership_clusters
   / contagion_risks），但走同一 factory（factory 是 schema-agnostic）。

3. **types.ts 补 `confidence` 到 sector base**：原始定义没有；Phase 3 scorecard
   + Phase 5 PRISM 都需要 sector-level 置信度，现在补上避免日后改契约。

4. **工具缺口处理**（Plan §5.2 列出的 ETF 工具 Phase 0/1 都没有）：
   `get_etf_holdings(*)` / `get_industry_research` / `get_top_holdings_overlap`
   等都缺。2D.1 sector agents 退而求其次用：
   - `get_industry_policy`（按 sector 关键词 filter）
   - `get_xueqiu_heat`（板块龙头股的散户关注度 → 散户对 sector 的认知）
   - `get_lhb_ranking`（当日 LHB 上榜个股按 sector 聚合）
   - `get_north_capital_flow`（北向资金的 sector preference proxy；真实的
     by-sector flow 在 Phase 4+ 接 `moneyflow_hsgt_top10` 后再替换）

   每个 sector agent 的 prompt 明确说"由于 ETF 工具不可用，picks 必须基于
   板块龙头 + 政策 + 资金流向 三角推断，不要编造未在工具返回中出现的 ticker"。
   `confidence ≤ 0.5` cap on 所有 sector agents until Phase 4 ETF tools land。

5. **`relationship_mapper` 单独处理**：
   - Plan §5.2 的 `get_top_holdings_overlap` / `get_related_party_transactions`
     都不存在（ETF 持仓 + 股东网络数据均缺）。
   - 2D.1 的 relationship_mapper 仅做 **跨 sector 资金流向相关性** 推断，
     基于 `state.layer2_outputs.*.sector_score` + 北向资金的 sector breakdown。
     输出 contagion_risks 仍有意义，supply_chains / ownership_clusters
     直接列已知大产业链（半导体设备链 / 新能源车链 / 白酒消费链）的硬编码
     映射作为占位。Phase 4 接真实工具后改。

6. **L2 subgraph 入口契约**：buildLayer2Graph 假定 `layer1_consensus` 已写入
   （即从 L1 subgraph 聚合器输出过来）。空状态下退化到 NEUTRAL regime。

**2D.2 设计决策**（Layer 3 superinvestor philosophy filters）：

1. **Layer-3 factory 独立**（不复用 Layer-1 / Layer-2 factory）。读上游：
   `state.layer1_consensus` (regime) + **`state.layer2_outputs.*`**（7 个
   sector agent 的 longs/shorts，作为 superinvestor 选股 universe 的输入）。
   写到 `state.layer3_outputs`。Layer-3 不依赖 LangGraph state 之外的"全局
   weights / cohort weights" —— 那些 (Plan §5.3 提的 Darwinian weights)
   留 Phase 3 +。

2. **4 个 superinvestor 都 share 同一 schema 形态**（`{picks: [{ticker,
   thesis, conviction, holding_period}], philosophy_note, key_drivers,
   confidence}`），各自用 `z.literal(<id>)` 区分。比 L2 还简单 — 没有
   `relationship_mapper` 这种异类。

3. **types.ts 补 `confidence` 到 SuperinvestorOutput**：与 L1 / L2 保持
   一致，让 Phase 3 scorecard / Phase 5 PRISM 都能读 superinvestor 置信度。

4. **工具配置**（每个 superinvestor 1-2 个 supplementary tools，主输入是
   上游 layers）：
   - `druckenmiller`（宏观动量）：`get_yield_curve_cn` + `get_industry_policy`
     —— 找 regime catalyst pair
   - `aschenbrenner`（AI 算力）：`get_industry_policy` + `get_xueqiu_heat`
     —— AI 政策 + 算力链 retail attention
   - `baker`（IP/生物）：`get_industry_policy` —— 药审 / 专利政策窗口
   - `ackman`（quality compounder）：`get_xueqiu_heat` + `get_lhb_ranking`
     —— 龙头股关注度 + 大资金动向（quality 公司流动性深）
   每个 superinvestor 的 prompt 强调"主输入是 layer2_outputs 里的 sector
   picks，工具只用于补充验证"。

5. **prompt 是 plan §3 标记的"重头戏"**：写得比 sector agent 更详细，体现
   每个 philosopher 独有的判断框架（asymmetric trade / AI capex / IP moat /
   pricing power）。每个 prompt 30-50 行，明确：
   - 你的哲学是什么、为什么这个哲学适用 A 股
   - 选股 universe = layer2_outputs.*.longs（**先在那里找 candidate**）
   - 评分维度（不同 superinvestor 不同）
   - holding_period 分桶（短/中/长）映射

6. **Cohort awareness**：Phase 5 PRISM 会按 cohort 训练 superinvestor
   prompts（plan §10）。2D.2 写 baseline 版本，后续 cohort_xxx 覆盖。

7. **L3 subgraph**：buildLayer3Graph(deps) 拓扑 START → 4 nodes（并发） →
   END。无 aggregator —— Layer-4 cio 才做最终聚合。

**2D.3 设计决策**（Layer 4 decision agents）：

1. **Layer-4 factory 与 L1/L2/L3 显著不同**：**不调 BridgeApi 工具**，纯
   synthesis。每个 L4 节点：load prompt → buildUserContext（读特定上游 layers）
   → 单次 LLM invoke（无 tool loop） → 结构化抽取 → 写 state.layer4_outputs。
   这让 L4 节点更便宜（每节点 1-2 次 LLM call vs L1-3 的 3-4 次）。

2. **L4 是小 DAG，不是并行 fan-out**：plan §5.4 输入依赖关系如下，
   buildLayer4Graph 必须显式建出来：
   ```
   START ─┬→ cro ────────────┐
          └→ alpha_discovery ─┴→ autonomous_execution → cio → END
   ```
   - cro + alpha_discovery 并行（都读 L1+L2+L3）
   - autonomous_execution 等 cro+alpha 完成后跑（读其结果 + L3 picks）
   - cio 最后跑（读所有上层 + L4 cro/alpha/auto_exec）
   LangGraph 的多 incoming-edge 自动 superstep barrier 处理这个依赖。

3. **types.ts 给 L4 outputs 都加 confidence**：CRO / AlphaDiscovery /
   AutoExec / CIO 都加 agent-level `confidence: number`，与 L1-3 对齐。
   `AutoExecOutput.trades[].conviction` 是 per-trade，与 agent confidence
   并存。

4. **CIO 双写状态**：`state.layer4_outputs.cio` + `state.portfolio_actions`。
   后者是顶层便利字段（Phase 3 scorecard / TUI 直接读），由 cio 单一写入，
   replace reducer 一致。

5. **Darwinian weights / JANUS regime 的占位策略**：
   - autonomous_execution prompt 提到"Darwinian weights" 的概念，但 2D.3
     用 stub（uniform weights = 1/N）；Phase 3 scorecard 落地后真实 weights
     从 `state.continuity_context` 流入。
   - cio prompt 提到"JANUS regime" 概念，但 2D.3 阶段 JANUS 不存在
     （Phase 6 落地）。cio 直接看 `state.layer1_consensus` 当 regime 信号。
   - 两个 stub 都在 prompt 里**明确说出来**："本 cycle 没有 Darwinian /
     JANUS 上下文，按 uniform / 单 cohort 处理"。Phase 3/6 接入时改 prompt。

6. **Schema 严格度递增**：
   - cro: 简单（rejected_picks 列表 + 风险描述）
   - alpha_discovery: 简单（novel_picks 列表 + 为什么别人没看到）
   - autonomous_execution: 中等（trades 含 size_pct + conviction）
   - **cio**: 严格（portfolio_actions 含 ticker / action / target_weight /
     holding_period / dissent_notes）。target_weight 必须 sum to 1.0
     ±0.05 容差（schema 用 superRefine 校验）。dissent_notes 在 cio 与
     auto_exec 不一致时必须非空。

### Sub-step 2E：4 层 LangGraph.js graph 装配

**2E 设计决策**（落地 daily_cycle.ts 之前）：

1. **顺序复合，subgraph 用 delta wrapper 调用**：L1/L2/L3/L4 都是已经
   compile 的 StateGraph，且共享同一个 `DailyCycleState` 注解。**实测发现**
   把 compiled subgraph 直接传给 `addNode("layer1", l1)` 时，subgraph 返回
   的是完整 output state（含累积的 `llm_calls`），parent 的 appendReducer
   会把它再追加到自己已有的 `llm_calls` 上 —— 4 层串完后 llm_calls 数从
   25 膨胀到 120+，加 replay 后到 243。所以我们用 `invokeSubgraph` wrapper
   显式计算 append-reducer 字段（llm_calls / messages）的 delta，
   replace / dict-merge channel 直接转发（这两类 reducer 对相同内容的
   重复更新是幂等的）。

2. **拓扑**：
   ```
   START → layer1 → layer2 → layer3 → layer4 → [veto_check]
                                                  ↓ replay
                                                  layer4_replay → END
                                                  ↓ end
                                                  END
   ```
   每个 layer 节点是 compiled subgraph。`veto_check` 是 conditional edge
   函数，读 `state.layer4_outputs.cro` 决定走 replay 还是 end。

3. **CRO veto loop 用拓扑保证 max 1 replay**：不引入 `daily_cycle_retries`
   状态字段。`layer4_replay → END` 是无条件边，所以图最多走一次 replay 路
   径。如果 replay 后 cro 仍然不满意，下一次 daily cycle 再处理（或 phase
   3 把 retries 接入）。这避免在 state 上加新 channel 影响所有现有
   fixtures。

4. **layer4_replay subgraph**：`START → alpha_discovery → auto_exec → cio
   → END`（不重跑 cro，复用 state 里现有 cro 输出）。alpha_discovery 在
   replay 时读到的 `layer4_outputs.cro` 是第一轮的 rejected_picks，可以
   据此找替代候选。auto_exec 同样看到 cro 的反对，不会再选被拒的 ticker。

5. **veto 触发条件**：cro.rejected_picks 数 > L3 picks 总数 × 0.5。空集
   或低拒绝率直接 END。`getCandidatePoolSize(state)` 计算 L3 superinvestor
   各 agent picks 的并集大小。这是简单启发式，phase 3 scorecard 后可换
   为基于历史命中率的自适应阈值。

6. **CLI 入口推迟到 2F**：2E 只产出 `buildDailyCycleGraph(deps)` 工厂，
   返回 compiled graph，不写 CLI command；CLI/smoke 是 2F 的事，方便
   2E 单独跑 vitest 单测。

7. **llm_calls / messages append-reducer 安全性**：通过 `invokeSubgraph`
   wrapper 主动 slice 出 delta（`result.llm_calls.slice(state.llm_calls.length)`），
   parent 的 appendReducer 只接收新增条目。我们在测试里 assert：跑完
   一次 daily cycle 后 llm_calls.length = sum(per-layer agent count) =
   25（无 veto 路径）或 28（含 replay 的 alpha+auto+cio 各 +1）。

- [ ] `mosaic-ts/src/graph/daily_cycle.ts` —— `buildDailyCycleGraph()`
- [ ] State propagation：L1 → L2（按 RegimeSignal 决定 sector 启用集）→
      L3 → L4
- [ ] Conditional edge：CRO 否决 → 回 L4 重做 alpha_discovery（max 1 轮，
      避免死循环）
- [ ] 大约 ~500 LOC，参考 ETFAgents `graph/etf_graph.py` 架构

### Sub-step 2F：Daily cycle MVP CLI smoke

**2F 设计决策**：

1. **CLI flag 集合**（参考 cli/commands/tool-loop.ts 模式）：
   - `--cohort <name>`（默认 cohort_default）
   - `--date <YYYY-MM-DD>`（默认今日，A 股 trading 日历不在 Phase 2 范围）
   - `--fake-llm`：用 mock LLM 跑端到端，sidecar / tool / graph 都是真的，
     仅 LLM 调用是 canned。零 API cost。**主验证渠道**。
   - `--llm-provider <lemonade|anthropic>`：默认从 .env 读
     LEMONADE_BASE_URL 推断。Phase 2F 实测用 lemonade。
   - `--out <path>`：JSON dump 最终 state（含 4 layer outputs +
     portfolio_actions）。默认 stdout。

2. **打印格式**：4 块（L1 regime / L2 sector picks / L3 superinvestor picks
   / L4 + portfolio_actions），每块 ≤ 20 行。彩色分层（chalk），对终端
   可读。`--out` 模式输出原始 JSON 不做 ANSI 染色。

3. **错误处理优先级**：bridge 启动失败 / sidecar tool 调用失败 → log + 继续
   （当前 layer 用 fallback output 占位）。LLM 调用失败 → bubble up 让 CLI
   exit 1。这避免一个 tool 故障让整个 25-agent cycle 挂。

4. **smoke 测试矩阵**：
   - **`pnpm dev daily-cycle --fake-llm`**: 必跑通；sidecar + 8 个 macro
     tool 都真调用（FRED / Tushare token 从 .env），LLM 用 mock。这验证
     bridge 链 + dataflows + LangGraph 全栈。
   - **`pnpm dev daily-cycle`** (lemonade)：跑过即可，不强制断言成本。
     验证 lemonade 本地工具调用 + 中文输出。
   - 不做 anthropic 跑，留给用户本地 + 生产期。

5. **不写 unit 测试**：CLI 命令本身是 thin wrapper，逻辑都已 covered 在
   2A-2E 的 228 个测试里。2F 的"测试" = `--fake-llm` smoke 跑出非空
   portfolio_actions 即合格。

6. **Phase 2 出口标准**（plan §11.2 末已定）：
   - 25 agents 全部写完 ✓
   - LangGraph.js 4 层装配跑通 1 次完整 daily cycle ✓ via 2E e2e test
   - `pnpm dev daily-cycle --fake-llm` 跑通 → smoke 输出 portfolio_actions
   - PR `phase-2-daily-cycle-mvp → main`

- [ ] `mosaic-ts/src/cli/commands/daily-cycle.ts` —— 新 CLI 命令
      `pnpm dev daily-cycle [--cohort cohort_default] [--date YYYY-MM-DD] [--dry-run]`
- [ ] 真 sidecar + lemonade 跑通一次完整 cycle（25 agents 串完）
- [ ] 输出：4 层报告 + final portfolio_actions 表
- [ ] 验证 LLM 成本（plan §13 估算 $0.125/cycle，实测 / 校准）

### 2A → 2F 验证矩阵（每个 sub-step 完成后）

```
pnpm typecheck     必绿
pnpm lint          必绿
pnpm test          必绿（增量加测试）
pnpm dev daily-cycle --cohort cohort_default --dry-run   2F 后必跑通
```

### Phase 2 出口标准

- 25 agents 全部写完（prompt zh+en、schema、node、单测）
- LangGraph.js 4 层装配跑通 1 次完整 daily cycle
- 输出形态稳定（`layer4_outputs.cio.portfolio_actions[]` 是 Phase 3 scorecard 的
  输入契约）
- PR `phase-2-daily-cycle-mvp → main`，类似 PR #1 流程

---

## 11.3 Phase 3 详细任务（Sub-step 3A–3F）

**目标**：把每个 daily cycle 的 25 agent 输出落进 SQLite，按 forward return
打分，算每 agent 的 rolling Sharpe + Darwinian 权重；在 autonomous_execution
里把 Phase-2 留的 stub 替换成真权重。Phase 3 出口后 Phase 4 autoresearch
就有真信号可用（Δ Sharpe ≥ 0.1 keep 阈值）。

### Phase 3 整体设计决策

1. **存储位置**：`<repoRoot>/data/scorecard.db`，gitignored，单文件多 cohort
   共享。同一个 db 在 Phase 4 autoresearch 也会用（plan §7 prompt_versions
   表共库）。建库由 Python sidecar handler 自动初始化（migrations 简单粗暴：
   `CREATE TABLE IF NOT EXISTS …`）。

2. **打分时机**：`scorecard.append` 在每次 `pnpm dev daily-cycle` 跑完后
   自动调用（写入 pending recommendations）。`scorecard.score_pending` 是
   单独命令（建议每天交易后 17:00 跑）；不在 daily cycle 主流程里同步阻塞。
   这避免 daily cycle 速度被 Tushare 行情查询拖慢。

3. **Forward return horizon**：5d primary（与 Plan §13 Phase 4 keep 阈值
   一致 —— 5 个交易日 Δ Sharpe）；21d secondary（tail watch）。**不算 1d**：
   A 股日内噪声大；T+1 制度下 1d 也无法实际兑现。

4. **Forward return 时间对齐**：`next_trading_day(date + N_trading_days)`，
   不用日历日。A 股双休 + 节假日多，日历对齐会把节假日也算进 horizon。
   `mosaic/dataflows/calendar.py` 提供交易日历（akshare 或 Tushare
   trade_cal 接口）。

5. **Benchmark**：默认 `000300.SH`（沪深300）算 alpha；可通过 env
   `MOSAIC_BENCHMARK_TICKER` 覆盖。alpha 公式：
   `alpha_5d = stock_return_5d - benchmark_return_5d`。
   不做 beta 调整（CAPM）—— Phase 5 PRISM 时再考虑。

6. **Darwinian weight 公式**：
   ```
   weight = clip(0.5 + rolling_sharpe_30d, 0.3, 2.5)
   ```
   - Sharpe 不显著 (|Sharpe| < 0.5) → weight ≈ 1.0
   - 强者 (Sharpe ≥ 2.0) → weight 2.5（25× 强弱差异是上限，避免极端集中）
   - 弱者 (Sharpe ≤ -0.2) → weight 0.3
   - 30d rolling 是最短窗口；90d/180d 在 Phase 4 autoresearch 才会用。
   - quartile 字段是 informational only（前端展示分位），multiplier 是连续值。

7. **空数据 fallback**：cohort 启动 < 30 个交易日时，rolling Sharpe 计算
   不足 → 所有 agent weight = 1.0（uniform）。这与 Phase 2 stub 行为
   完全等价，让前 30 天 daily cycle 的 portfolio 不被 Phase 3 改变 ——
   仅记录数据，不影响决策。3F 把 weight 注入 autonomous_execution 时
   prompt 也明确告诉 agent："如果 weights 都是 1.0 你就当是 uniform
   stub，不要据此 over-interpret"。

8. **Weight 注入点（3F）**：只 autonomous_execution agent 的 user context
   读 weights（其他 agent 通过 output 自带 confidence 表达置信度，无需
   weight）。具体做法：`renderDarwinianWeights(state, api)` 通过 BridgeApi
   查 `darwinian.get_weights(cohort, date)`，把每个 L3 superinvestor 的
   weight 拼到 user message 里。auto_exec prompt 已经写好对 weight 的
   理解（plan §11.2 2D.3 #5）。

9. **JANUS regime stub 不在本 phase 处理**：plan §11.2 2D.3 #5 留下两个
   stub —— Darwinian + JANUS。Phase 3 仅替换 Darwinian；JANUS 是 Phase 6
   多 cohort blend 的事。3F 不动 cio.ts。

10. **Bridge handler 命名**：`scorecard.*` + `darwinian.*` 两个命名空间。
    与 Phase 0 已有的 `tools.*` / `config.*` / `cache.*` / `paper.*` /
    `backtest.*` 一致，单 RPC method 用 `<ns>.<verb>`。

### Sub-step 3A：SQLite schema + 持久化层 ✅ **已完成** (2026-05-29)

- [x] `mosaic/scorecard/__init__.py` —— package 标记 ✅
- [x] `mosaic/scorecard/store.py` —— SQLiteStore 类 ✅
    - `init_schema()` —— CREATE TABLE IF NOT EXISTS recommendations
      + darwinian_weights（plan §7 schema）✅
    - `append_from_state(state: dict)` —— 接收一个 daily-cycle 终态 dict
      （完整 state JSON），从中抽取每个 agent 的输出 + portfolio_actions，
      写入 recommendations 表（每行 = 一个 agent + 一个 ticker 的建议）。
      pending（forward_return_5d / scored_at 都是 NULL）。✅
    - `list_pending(cohort, before_date)` —— 返回需要打分的行 ✅
    - `update_scoring(row_id, forward_return_5d, forward_return_21d, alpha_5d, scored_at)` ✅
    - `list_scored(cohort, agent?, since_date?)` —— 返回已打分行（alpha_5d IS NOT NULL）✅
    - `upsert_darwinian_weights(rows)` —— 批量 upsert Darwinian 权重 ✅
    - `get_darwinian_weights(cohort, date?)` —— 查询权重（date=None 时返回每个 agent 最新值）✅
    - `expand_state_to_recommendations(state)` —— 纯函数，state → rows 展开 ✅
- [x] `tests/test_scorecard_store.py` —— 21 tests, all passing ✅
    - expand_state_to_recommendations: L2 longs → rows, L2 shorts excluded,
      relationship_mapper excluded, L3 picks → rows, L3 philosophy fallback,
      L4 cio actions → rows, L1 not persisted, row count, missing date raises,
      truncation ✅
    - ScorecardStore: schema creation, append idempotency (UNIQUE constraint),
      upsert preserves scoring columns, list_pending filters, cohort isolation,
      empty state, list_scored excludes pending ✅
    - Darwinian weights: upsert/get, CHECK constraint (weight 0.3-2.5),
      latest per agent when date omitted ✅

**3A 实现备注**：
- UNIQUE(cohort, agent, ticker, date) 约束确保幂等 ingest
- ON CONFLICT DO UPDATE 保留 scoring 列（forward_return_5d/21d/alpha_5d/scored_at）不被覆盖
- L2 relationship_mapper 被正确跳过（output shape 不同，无 longs/shorts）
- L2 shorts 不入表（A 股做空不可行）
- L1 macro agents 不持久化（无 ticker，regime 信号是 inputs 不是 predictions）
- 默认 DB 路径：`<repoRoot>/data/scorecard.db`（可通过 MOSAIC_DATA_DIR env 覆盖）

**3A 设计决策**：
- 一个 `state` ingest 会展开成 (10 + 7 + 4 + 4 = 25 agent rows × 1+
  ticker per agent) 行 recommendations。**只展开有 ticker 的输出**：
  L1 macro agents 没 ticker，跳过（regime 信号不入 recommendations 表）。
- L2 sector：每个 long pick 一行；shorts 暂不入表（A 股做空不可行）。
- L3 superinvestor：每个 picks[]  一行。
- L4 cio: 每个 portfolio_actions[] 一行，agent 字段填 "cio"。
- `target_weight_pct` 字段：L4 cio 写真值；L2/L3 写 `conviction × 100`
  作为 conviction 占比的近似（Phase 3 scorecard 关心的是「方向 +
  置信度」，target_weight 仅 L4 真实有意义）。
- `rationale_snapshot`：thesis（L2/L3）/ dissent_notes（L4 cio）/
  philosophy_note（L3）— 取 ≤ 200 字符的关键文字快照。

### Sub-step 3B：Forward-return scorer

- [ ] `mosaic/scorecard/scorer.py` —— Scorer 类
    - `score_pending(cohort, today: date)` —— pull list_pending(cohort, today
      - 5 trading days)，调 Tushare 取每个 ticker 的收盘价 + 基准 5d/21d
      forward return + alpha；UPDATE recommendations 表。
    - 内部用 `dataflows/calendar.py` 算 next_trading_day(date, n)
- [ ] `mosaic/dataflows/calendar.py` —— get_trading_calendar() 缓存版
- [ ] `tests/test_scorecard_scorer.py` —— mocked Tushare + benchmark；测
  正常打分 + 缺数据回退（ticker 停牌）+ 跨节假日对齐

**3B 设计决策**：
- 停牌的 ticker forward_return 写 NULL，scored_at 仍然填日期（避免无限
  pending）。Phase 4 autoresearch 计算 Sharpe 时 NULL 直接 drop。
- Benchmark 数据来自同一个 Tushare daily 接口，不单独 vendor。
- 缓存复用 mosaic/cache_manager 的 SQLite price_daily 缓存，避免每天
  重新拉一遍。

### Sub-step 3C：Darwinian weights compute

- [ ] `mosaic/scorecard/weights.py` —— compute_weights(cohort, today)
    - 对每个 (cohort, agent) 取 rolling 30d / 90d 的 alpha_5d 序列
    - Sharpe = mean / std × sqrt(252)
    - weight = clip(0.5 + sharpe_30d, 0.3, 2.5)
    - quartile = 1-4 by sharpe_30d 在 cohort 内的排名
    - INSERT INTO darwinian_weights (UNIQUE on (cohort, agent, date))
    - 空数据 fallback: < 30 trading days of scored data → weight = 1.0
- [ ] `tests/test_scorecard_weights.py`

**3C 设计决策**：
- Rolling Sharpe 用 alpha_5d（已剔除 benchmark），不用 raw return —— 否
  则牛市里所有 agent 都「显得很厉害」。
- annualization √252 标准做法。**注意 5d horizon 的 Sharpe 是「5d 周期
  的年化」**，不是「日 Sharpe 年化」；不与日频 Sharpe 直接可比。
- quartile 是 informational only。weight 数学上是连续的；quartile 只是
  方便前端 UI 把 agent 染色（top quartile 绿 / bottom 红）。

### Sub-step 3D：Bridge handlers + TS wrappers

- [ ] `mosaic/bridge/handlers/scorecard.py` —— register_handlers:
    - `scorecard.append` (state: dict) → bool
    - `scorecard.score_pending` (cohort: str, today: str) → {scored: int}
    - `scorecard.list_skill` (cohort: str, since: str) →
       [{agent, mean_alpha_5d, sharpe_30d, n_obs}]
- [ ] `mosaic/bridge/handlers/darwinian.py` —— register_handlers:
    - `darwinian.compute` (cohort, today) → {written: int}
    - `darwinian.get_weights` (cohort, date) →
       {agent: {weight, sharpe_30d, quartile}}
- [ ] `mosaic-ts/src/bridge/api.ts` —— 加 scorecardAppend / scoreCardScore /
      scorecardListSkill / darwinianCompute / darwinianGetWeights typed
      wrappers
- [ ] `mosaic-ts/src/bridge/types.ts` —— SkillRow / DarwinianWeights interfaces
- [ ] `tests/test_bridge_protocol.py` 加 5 个 RPC 路由测试
- [ ] `mosaic-ts/test/bridge_scorecard.test.ts` —— TS 端 wrapper 单测

**3D 设计决策**：
- `scorecard.append` 直接接 state dict，不要 cohort/date 参数 —— state 自带。
- `list_skill` 返回的 mean_alpha_5d / sharpe_30d 直接给 CLI / TUI 展示，
  不暴露 raw recommendations 行（前端不需要那么细）。
- 所有 RPC method idempotent —— append 同一 (cohort, agent, ticker, date)
  靠 UNIQUE 约束 +  ON CONFLICT DO UPDATE 实现，多次调用安全。

### Sub-step 3E：CLI visualization

- [ ] `mosaic-ts/src/cli/commands/scorecard.ts` —— `pnpm dev scorecard`
    - `--cohort cohort_default` (default)
    - `--since 30d` —— 看最近 30 天
    - 输出 per-agent 表格：agent / mean_alpha_5d / sharpe_30d / quartile
      / n_obs，按 sharpe_30d 排序，染色 top/bottom quartile
- [ ] `mosaic-ts/src/cli/commands/darwinian.ts` —— `pnpm dev darwinian`
    - 输出 per-agent weight 表
    - `--date YYYY-MM-DD` 可指定看历史某日（默认最新）
- [ ] CLI 用 picocolors 染色，与 daily-cycle CLI 风格一致

**3E 设计决策**：
- 不做 TUI（plan §9 Phase 9 才做）；现在是 plain stdout 表格。
- 不做 export to CSV / JSON 格式；--out 留 Phase 4 autoresearch 评估时
  再加（届时 Δ Sharpe 计算需要它）。

### Sub-step 3F：Wire Darwinian weights into autonomous_execution

- [ ] `mosaic-ts/src/agents/decision/_user_context.ts` ——
      `renderDarwinianWeights(state, api): Promise<string>` 替代
      `renderDarwinianWeightsStub()`。注意：变成 async，因为要查 bridge。
- [ ] `mosaic-ts/src/agents/decision/autonomous_execution.ts` —— 更新
      `buildUserContext` 改为 async；factory 也要支持 async user context
      builder（_factory.ts）
- [ ] `mosaic-ts/src/agents/decision/_factory.ts` —— buildUserContext 类型
      改成 `(state) => string | Promise<string>`
- [ ] 测试更新：autonomous_execution 端到端测加 `darwinian.get_weights` mock

**3F 设计决策**：
- 不动 cio.ts —— JANUS 留 Phase 6。
- 空数据 fallback（前 30 天 cohort）：bridge 返回 weight = 1.0 给所有
  agent，prompt 自动收敛到与 stub 等价的行为；CLI 输出 Darwinian table
  全 1.0 也是合法状态。
- 这一步会让 daily-cycle CLI 的 autonomous_execution agent 多 1 次
  bridge round-trip（`darwinian.get_weights`）。可接受 —— 整 daily cycle
  本来就 N 个 bridge call，多 1 个不是瓶颈。

### Phase 3 出口标准

- 一次 daily cycle 跑完后 SQLite recommendations 表自动多 25-50 行
- `pnpm dev scorecard --cohort cohort_default` 输出非空表（前提：scorecard
  跑过几天 + score_pending 跑完）
- `pnpm dev darwinian` 输出非空 weight 表
- autonomous_execution prompt 在 user context 中收到非 stub 文本（即
  `renderDarwinianWeights` 真实返回，不是 stub 占位）
- PR `phase-3-scorecard → main`，类似 PR #2 流程

---

## 11.4 Phase 3.5 详细任务（Sub-step 3.5A–3.5F）

**目标**：接入 qlib 作为历史数据底座 + 向量化回测引擎。Phase 4 autoresearch
评估时间从"等 1 周看 1 个 5d Sharpe 数据点"压到"秒级历史回放"——单天可跑
数百次 mutation。同时为 Phase 5 PRISM 多 cohort 训练、Phase 8 backtest
执行打底。

**用户决策（2026-05-29）**：
- 整合方式 **(a)(ii) 重整合**——直接 import qlib，用 qlib 的 backtest.executor
  + Strategy 接口（不自己写回测引擎）。MOSAIC 的 LangGraph daily-cycle 适配成
  qlib `BaseStrategy.generate_trade_decision()`。
- 数据范围：**全部 A 股 1990-至今**（沪 + 深 + 创业 + 科创板 + 已退市）。
- 时机：**立刻做 Phase 3.5**，不先做 forward-time Phase 4 MVP。
- 数据源优先级：**Tushare primary**（你已有 token，可靠 > 免费）。akshare
  作为 fallback 用于 Tushare 缺失的退市股。
- 增量更新：**手动**（operator 跑 `pnpm dev qlib-update`）。daily-cycle 不
  自动 refresh data，保持确定性。
- 失败 ingest：**skip ticker**（gap > 1% 的 ticker 整支跳过，写入
  `data/qlib_skipped.txt`），survivorship-bias 在边际牺牲，数据质量优先。

### Phase 3.5 整体设计决策

1. **数据存储**：`~/.qlib/qlib_data/cn_data/` 为 qlib 标准路径，`QLIB_CN_DATA_PATH`
   env 可覆盖（`mosaic/dataflows/qlib_local.py` 已有此逻辑）。gitignored。
   预估容量 1.5-2 GB（5500+ tickers × 35 年 × OHLCV + factor）。

2. **依赖管理**：`pyproject.toml` 加 `pyqlib >= 0.9.6`（最新稳定版）+
   `cython`（pyqlib 原生扩展依赖）。`pyqlib` 是 200+ MB 包；放在
   optional dependency group `[backtest]` 里，普通 daily-cycle 跑不需要。

3. **Ingest 流程**：
   - 主源：Tushare `pro.daily(ts_code=*, start_date=19900101, end_date=YYYYMMDD)`
     —— 分批拉，每个 ticker 一次 call。Tushare 速率：免费档 200 次/分钟，
     2000 积分档 500 次/分钟。**全 ingest 估算**：5500 tickers × 35 年 × 250
     bars / batch_size 200 ≈ 30-60 分钟单次完整下载。
   - akshare fallback：Tushare 返回空或 5xx 错误时尝试 akshare
     `stock_zh_a_hist`（特别是退市股）。
   - dump：自己实现 CSV → qlib binary 转换（参考 qlib `scripts/dump_bin.py`），
     不依赖 qlib 的 collector 脚本（它对 CN 数据支持有 gap）。

4. **Survivorship-bias-free universe**：通过 Tushare `stock_basic(list_status='L,D,P')`
   拉所有上市 / 退市 / 暂停的 ticker，写入 `instruments/all.txt`。
   benchmark constituents（CSI300/500 等）取每个交易日的 point-in-time 名单
   ——用 Tushare `index_weight(index_code, trade_date)` 接口，按月采样然后
   插值。

5. **Skip 策略**（决策 III）：**任何 gap > 1%** 的 ticker（实际 vs 期望
   bar 数）整支不入 universe，记录到 `data/qlib_skipped.txt` 供后续
   review。这意味着部分早期退市股会缺失，但保证 backtest 数据干净。

6. **Backtest 语义（strict point-in-time）**：
   - Daily cycle 跑 `as_of_date = current_trading_day`，bridge 工具自动
     clamp end_date（Phase 0 backtest mode 已实现）。
   - 成交时点：**next_open** —— A 股 T+1 制度，今天的 portfolio_actions 在
     明天开盘成交。
   - Slippage：**8 bps**（qlib CN default）。
   - Commission：**3 bps buy + 13 bps sell**（A 股零售实际，含印花税单边）。
   - Initial cash：**¥1,000,000** 默认，CLI flag 可改。
   - Benchmark：**000300.SH 沪深300**（与 Phase 3 scorer 一致）。

7. **Strategy adapter**（3.5C 关键）：MOSAIC 的 LangGraph daily-cycle 输出是
   `state.portfolio_actions[]`，每元素 `{ticker, action, target_weight}`。
   qlib 的 `BaseStrategy.generate_trade_decision(trade_step)` 期望返回
   `TradeDecision`。adapter 流程：
   - 进入 step → 取当前 trading_day → 构造 initial DailyCycleState（active_cohort
     + as_of_date = trading_day + mode = backtest）。
   - 调 `buildDailyCycleGraph(deps).invoke(state)` —— 但这是 TS！
   - **跨语言挑战**：Python qlib 跑回测，但 daily-cycle 在 TS。两个方案：
     - 方案 A：qlib runner 通过 BridgeClient 调 TS 的 `daily_cycle.run` RPC
       (TS → 反向 RPC server)。复杂。
     - 方案 B：daily-cycle 跑在 TS 端，TS 把 portfolio_actions 流式 push 到
       Python，Python 端 qlib 收消费。架构清晰。
     - **方案 C（采纳）**：把 daily-cycle 提前批量跑完（per backtest day），
       结果存 SQLite，然后 qlib runner 单纯读 SQLite + 执行成交。**两阶段
       回测**：阶段 1 = TS 跑 N 个 daily-cycle 写表，阶段 2 = Python qlib
       从表读 portfolio_actions 跑回测。
   - 方案 C 优势：解耦语言、可重跑、Phase 4 mutation 时只需重跑阶段 1 的
     变化部分（agent 级 cache），qlib 阶段 2 永远是确定性回放。

8. **Two-stage backtest 缓存表**（新增 SQLite schema）：
   ```sql
   CREATE TABLE backtest_runs (
     id INTEGER PRIMARY KEY,
     cohort TEXT NOT NULL,
     start_date TEXT NOT NULL,
     end_date TEXT NOT NULL,
     prompt_commit_hash TEXT NOT NULL,           -- 关联 git commit (Phase 4)
     created_at TEXT NOT NULL,
     UNIQUE(cohort, start_date, end_date, prompt_commit_hash)
   );
   CREATE TABLE backtest_actions (
     id INTEGER PRIMARY KEY,
     run_id INTEGER REFERENCES backtest_runs(id),
     trade_date TEXT NOT NULL,
     ticker TEXT NOT NULL,
     action TEXT NOT NULL,
     target_weight REAL NOT NULL,
     holding_period TEXT,
     dissent_notes TEXT,
     UNIQUE(run_id, trade_date, ticker)
   );
   ```
   表落在 `data/scorecard.db` 同一个文件（已有 recommendations + darwinian_weights）。

9. **Phase 4 重写指引**：3.5 落地后，Phase 4 evaluation 流程变成：
   - mutate prompt → git commit → trigger `backtest.run_historical(cohort,
     start, end)` → 用新 prompt 跑 N=60 天 daily-cycle（阶段 1） → qlib
     回测（阶段 2） → 得到 post Sharpe → 与 base prompt 的同期 backtest
     比较 → ΔSharpe ≥ 0.1 keep / 否则 revert。
   - 评估时间从 5 个真实交易日 → ~10 分钟（60 天 daily-cycle 跑 60 次 LLM × 25
     agents 用 lemonade 本地推理）。Phase 4 PR 时再细化。

10. **不在 Phase 3.5 范围**：
    - 不接 qlib 自己的 model 训练（我们有 25-agent prediction layer）
    - 不接 qlib 的 factor library
    - 不做 PRISM 多 cohort（Phase 5）
    - 不做 paper trading 实盘（Phase 8 后段）
    - 不做 RD-Agent 的 Researcher/Developer 拆分（Phase 4 决定，Phase 3.5
      只搭基础设施）

### Sub-step 3.5A：pyqlib 依赖 + 现有 qlib_local.py sanity

- [ ] `pyproject.toml` 加 optional dep group `[backtest]`
      包含 pyqlib + cython
- [ ] `mosaic/dataflows/qlib_local.py` —— 现有 454 LOC 港口源，验证 read
      路径仍工作（端到端用一个手工造的 10-ticker × 1-月 mini dataset 测）
- [ ] `tests/test_qlib_local.py` —— 端到端 read 测试（不依赖真 qlib_data）
- [ ] `.gitignore` 加 `~/.qlib/`（防止用户误提交 1.5GB 数据）
- [ ] 设计决策：pyqlib import 失败时 graceful degradation
      （DataVendorUnavailable）—— qlib_local.py 已有此模式

### Sub-step 3.5B：Bulk ingest pipeline

- [ ] `mosaic/dataflows/qlib_ingest.py` —— 主入口
    - `ingest_full(start='1990-01-01', end='today')` —— 全量
    - `ingest_incremental(today)` —— 单日增量
    - `_fetch_ticker_bars(ts_code, start, end)` —— Tushare 优先 / akshare fallback
    - `_dump_to_qlib_bin(df, ts_code, output_dir)` —— CSV → 二进制
    - `_build_universe_lists()` —— `instruments/all.txt` + `csi300.txt` 等
    - 速率限制 + 重试 + 进度条（tqdm）
- [ ] `mosaic/dataflows/qlib_dump.py` —— qlib binary 格式 writer（参考
      qlib `scripts/dump_bin.py` 实现）
- [ ] `tests/test_qlib_ingest.py` —— mock Tushare/akshare，测 dump 路径
- [ ] CLI: `python -m mosaic.dataflows.qlib_ingest --full` /
      `--incremental 2024-12-15`

### Sub-step 3.5C：Strategy adapter（two-stage 阶段 1）

- [ ] `mosaic-ts/src/cli/commands/backtest-fill.ts` —— TS 命令
      `pnpm dev backtest-fill --cohort X --start --end`
    - 对 [start, end] 每个交易日调一次 `buildDailyCycleGraph().invoke()`
    - 把 `portfolio_actions` 写入 `backtest_actions` 表（通过新 RPC）
- [ ] `mosaic/scorecard/store.py` —— 加 backtest_runs / backtest_actions
      schema + upsert API
- [ ] 新 RPC: `backtest.append_actions(run_id, date, actions[])`
- [ ] 增量缓存：同 (cohort, dates, prompt_commit) 已有 → 跳过

### Sub-step 3.5D：Backtest runner（two-stage 阶段 2）

- [ ] `mosaic/backtest/__init__.py`
- [ ] `mosaic/backtest/qlib_runner.py` —— 主入口
    - `run_backtest(run_id) → metrics` ——读取 backtest_actions，构造 qlib
      Strategy（仅读表，不调 LLM），跑 qlib executor，返回指标
    - 指标：total_return / annualized_return / sharpe / max_drawdown /
      ic / alpha / beta / turnover
- [ ] `mosaic/backtest/qlib_strategy.py` —— qlib BaseStrategy 子类，从
      backtest_actions 表读 trade decisions
- [ ] `tests/test_qlib_runner.py` —— mocked qlib data，测端到端

### Sub-step 3.5E：Bridge handler + TS wrapper

- [ ] `mosaic/bridge/handlers/backtest.py` —— 替换 Phase 0 PAPER_ERROR stub
    - `backtest.run_historical(cohort, start, end, prompt_commit_hash?)
       → metrics dict + run_id`
    - `backtest.list_runs(cohort, since?) → [{run_id, ...}]`
    - `backtest.get_metrics(run_id) → metrics`
- [ ] `mosaic-ts/src/bridge/types.ts` —— BridgeApi.backtestRunHistorical
      / .backtestListRuns / .backtestGetMetrics + interfaces
- [ ] `tests/test_bridge_backtest.py` —— in-process handler tests

### Sub-step 3.5F：CLI

- [ ] `mosaic-ts/src/cli/commands/backtest.ts` —— `pnpm dev backtest
      --cohort cohort_default --start 2023-01-01 --end 2023-12-31`
    - Step 1: 调 `backtest-fill` 跑 daily-cycles 写表（如 commit 已 cached
      则跳过）
    - Step 2: 调 `backtest.run_historical` 跑 qlib executor
    - 输出：metrics 表 + ASCII equity curve（picocolors）
    - `--out path` JSON dump 完整 equity curve

### Phase 3.5 出口标准

- pyqlib 装好，`python -c "import qlib"` 不抛
- 运行 `python -m mosaic.dataflows.qlib_ingest --full` 后 `~/.qlib/qlib_data/cn_data/`
  约 1.5 GB，包含全 A 股 1990-至今（minus skipped tickers）
- `pnpm dev backtest --cohort cohort_default --start 2024-01-01
  --end 2024-03-31` 跑通端到端，输出 metrics 表
- skipped tickers 列表 `data/qlib_skipped.txt` 存在（透明记录）
- PR `phase-3.5-qlib-integration → main`

---

## 11.5 Phase 4 详细任务（Sub-step 4A–4F）

> 估算 5–6 turns。分支：`phase-4-autoresearch`（待开工时建）。
> **目标**：闭合 ATLAS 的自我改进回路 —— 让系统自动 (1) 选一个 agent、
> (2) 用 LLM 改写它的 prompt、(3) git 提交到 feature branch、(4) 用 Phase 3.5
> 两段式回测算改前/改后 Δ Sharpe、(5) 按 Δ Sharpe ≥ 0.1 决定 keep（merge）
> 或 revert（删 branch），全程受 §1/§8 约束（24h 冷却 / 3 天 keep 锁定 /
> 月度 100 次上限）约束。Phase 4 出口后系统能在单 cohort 上每天自我迭代
> prompt 且有数据支撑的优胜劣汰。

### 已确认决策（2026-05-29 checkpoint）

用户已就 §14 #10–13 拍板，本节据此定稿：

- **#10 目标 cohort = `crisis_2008`**（§9：2007-10-17 → 2008-10-28，A 股本土
  暴跌 70% / 1664 见底）。**理由**：高波动 regime 下 agent 质量差异显著，
  ΔSharpe 信号比平淡区间更有意义 —— 是 autoresearch 优胜劣汰的更强压力测试。
  - **eval 窗口**：cohort 时段内**最后 60 个交易日**（≈ 2008-08 → 2008-10-28），
    自然覆盖雷曼崩溃（2008-09）+ A 股见底，stress 最强。
  - **prompt fallback 不需 seeding 步骤**：crisis_2008 目前无 cohort 专属
    prompt，全部 fallback 到 `cohort_default`（loader 已支持）。这意味着
    **base 回测**所有 25 agent 都读 cohort_default；**mutation feature branch**
    只新增 1 个 `cohort_crisis_2008/<layer>/<agent>.{zh,en}.md`，故 base/post
    两次回测**只在被改 agent 上有差异**，ΔSharpe 干净可比。keep 的 mutation
    以 cohort_crisis_2008 文件累积，逐步让 crisis_2008 prompt 从 default 演化
    分叉 —— 正是期望行为。
  - **数据前提**：依赖 Phase 3.5 `qlib_ingest --full`（1990-至今）已覆盖
    2007-2008；注意当年 A 股 universe 较薄（上市数少 + survivorship），eval
    用 `000300.SH` 基准 + 当时实际成分，stress 窗口个股缺失靠 skip 策略兜底。
- **#11 git 模型简化 = OK**：MVP 用单 trunk on `main` + 短寿 feature branch，
  per-cohort 演化 trunk 推迟 Phase 5。
- **#12 评估方法 = confirmed**：backtest-based ΔSharpe（秒级回放 + prompt_commit
  缓存），不等 5 个真实交易日。
- **#13 macro tools pre-flight = follow advice**：先跑通 autoresearch 机制本身，
  Layer-1 macro 工具缺口（property / usdcny / commodity / ivx）Phase 4 后补；
  4.0 P1 不在 Phase 4 范围内执行。

### Phase 4 起跑前的事实基线（写在最前，避免重复造轮子）

Phase 0–3.5 已落地、Phase 4 直接复用的关键设施（**已验证可用**）：

| 设施 | 位置 | Phase 4 用途 |
|---|---|---|
| `backtest_runs.prompt_commit_hash` 列 + UNIQUE(cohort,start,end,prompt_commit_hash) | `mosaic/scorecard/store.py` | **核心**：每个 prompt 版本的回测结果天然按 commit hash 隔离缓存。改前/改后就是两个 commit hash 的两条 run。 |
| 两段式回测：`backtest-fill`(TS stage-1) → `backtest.run_historical`(qlib stage-2) | `mosaic-ts/.../backtest-fill.ts` + `mosaic/bridge/handlers/backtest.py` | 评估引擎直接调，秒级回放得到 Sharpe（plan §3.5 设计决策 #9） |
| `backtest.{create_run,append_actions,complete_run,run_historical,list_runs,get_run}` RPC | `mosaic/bridge/handlers/backtest.py` | 评估编排复用，**无需新写回测 RPC** |
| TS prompt loader：`loadPrompt({agent,cohort,language,promptsRoot?,noCache})` + `clearPromptCache()` + cohort→cohort_default fallback | `mosaic-ts/src/agents/prompts/{loader,cohorts}.ts` | mutator 读现有 prompt；**已有 `promptsRoot?` 形参**，4C worktree 评估可直接用 |
| `AGENTS_BY_LAYER` / `LAYER_BY_AGENT` / `ALL_AGENTS` | `mosaic-ts/src/agents/prompts/cohorts.ts` | mutator 选 agent + 定位 layer 目录 |
| `scorecard.list_skill` / `darwinian.get_weights` RPC | `mosaic/bridge/handlers/{scorecard,darwinian}.py` | mutator 把 agent 近期表现喂给 LLM 作为「改什么」的依据 |
| `config.autoresearch` 约束块（cooldown/lockout/keep_threshold/monthly_cap/horizon） | `mosaic/default_config.py` | 约束执行器直接读，**无需新增配置** |
| 25 × 2 prompt `.md` 已在 `prompts/mosaic/cohort_default/{macro,sector,superinvestor,decision}/` | repo 内 | git mutation 的对象 |

**还没有、Phase 4 要新建的**：`prompt_versions` + `autoresearch_log` 两张表
（plan §7）、git_ops 模块、mutation 生成器（TS）、评估器、keep/revert 决策器、
`autoresearch.*` + `prompts.*` RPC、`pnpm dev autoresearch` CLI。

### Phase 4 整体设计决策（开工前定，避免后续走偏）

1. **职责切分沿用全局架构原则**（plan §2）：
   - **TS 端**：mutation LLM 编排（读 prompt + skill → 生成改写）、评估编排
     （驱动 backtest-fill 两段式）、CLI、orchestrator 主循环。
   - **Python 端**：git 操作（branch/commit/merge/worktree）、SQLite
     （prompt_versions / autoresearch_log）、约束判定、Δ Sharpe 计算（读两条
     backtest run 的 metrics）。
   - 即「TS 出主意 + 编排，Python 落盘 + 算账」。`git` / `sqlite3` 重逻辑全
     在 Python，与 ETFAgents 一致。

2. **评估方法 = 回测优先（backtest-primary），不等 5 个真实交易日**（plan §3.5
   设计决策 #9 已定调，正式取代 §8 原协议的「5 交易日后 evaluate」）：
   ```
   mutate → git commit (feature branch) → 对 base_commit 与 mod_commit 各跑一遍
   两段式回测（同 cohort、同 eval 窗口）→ ΔSharpe = post_sharpe − pre_sharpe
   → ΔSharpe ≥ keep_threshold(0.1) ? keep(merge) : revert(删 branch)
   ```
   - **eval 窗口**：默认取 cohort 时段内**最后 N=60 个交易日**（可
     `--eval-days` 覆盖）。Phase 4 目标 cohort = `crisis_2008`（已确认决策 #10），
     故默认窗口 ≈ 2008-08 → 2008-10-28（雷曼崩溃 + A 股 1664 见底）。固定窗口
     保证改前改后**同期可比**。
   - `pre_sharpe` 来自 base prompt 在该窗口的回测；若已 cache（同
     cohort+window+base_commit）直接读，不重算。
   - 评估耗时 ≈ 跑 N 天 daily-cycle（stage-1，用 **lemonade 本地 LLM** 零
     API 成本）+ 秒级 qlib 回放（stage-2）。plan §3.5 估 ~10 分钟/次。
   - **forward-time 路径不在 Phase 4 MVP 范围**：生产实盘上线后可用
     `scorecard.score_pending` 的真实 5d/21d alpha 做二次确认，但那是
     Phase 8 执行层 + 实盘运行的事；Phase 4 只做 backtest-based 评估闭环。

3. **git 模型 MVP 简化：单 trunk on `main`，per-cohort 演化 trunk 推迟到
   Phase 5**。plan §8 画的是 7 条 `cohort/<name>/main` 长寿 trunk + feature
   branch 的两层结构，那是 PRISM 多 cohort 才需要的。Phase 4 单 cohort MVP：
   - mutation 直接从 `main` 切短寿 feature branch
     `cohort/<cohort>/auto/<agent>/<YYYY-MM-DD>`（命名沿用 plan §1）。
   - 每条 feature branch **只含 1 个 commit**，只动
     `prompts/mosaic/<cohort>/<layer>/<agent>.{zh,en}.md`。
   - keep = 把该 commit cherry-pick / fast-forward 回 `main`；revert = 删
     branch。
   - Phase 5 PRISM 落地时再把 `main` 升级成「main 存代码 + cohort/<name>/main
     存各 cohort 演化」的两层模型（plan §8）。**这条简化记入 §14 待决，请用户
     确认**。

4. **mutation 粒度：一次只改一个 agent 的一对 prompt（zh + en 同步改）**。
   - 中英文必须语义一致（autoresearch 不能让两个语言版本漂移）。做法：mutator
     一次 LLM 调用，structured output 同时产出 `{zh_prompt, en_prompt,
     modification_summary, rationale}`，两个语言版本由同一次推理保证一致。
   - 受 §1 约束：同一 (cohort, agent) **24h 内最多 1 次新 mutation**。

5. **prompt 改写的「护栏」**（防止 LLM 把 prompt 改坏）：
   - **保结构**：mutator 的 meta-prompt 强制保留每个 agent 的「输出 schema
     描述段」「工具最低使用要求段」（这些是 structured_output 解析成功的前提，
     改坏会让整个 agent 输出失败）。4B 用一个 `assertPromptInvariants(text)`
     做轻量校验（检查关键 section 标题 / schema 字段名仍在）。
   - **限幅**：改写后长度变化 ≤ ±40%，避免 LLM 把 30 行 prompt 膨胀成 200 行。
   - **必须有实质改动**：改写后与原文 normalized 后不得完全相同（否则
     trigger 视为 no-op，不创建 version）。

6. **约束执行集中在 Python 端**（single source of truth，避免 TS / Python 双
   实现漂移）：cooldown / monthly_cap 在 `autoresearch.trigger` 创建 version
   前查 prompt_versions 表判定；keep-lockout 在 `autoresearch.evaluate` 决策
   时判定。TS orchestrator 只是调用方，约束逻辑不在 TS。

7. **幂等 & 可重入**：
   - `autoresearch.trigger` 对同一 (cohort, agent, date) 已有 pending version
     → 返回既有 version，不重复创建（幂等）。
   - 评估失败 / 中断后可重跑：`evaluate_pending` 扫所有 `status='pending'` 的
     version，逐个评估；已有完整 backtest run（按 commit hash）直接读不重跑。

8. **store 单例 + 连接复用（顺带修 §14 R-T4）**：Phase 4 autoresearch 高频调
   SQLite（trigger / log / version 状态机）。把 bridge handler 的
   `_store()` 改成 **module-level 单例（按 db_path 缓存）**，避免每个 RPC new
   一个 connection。`scorecard.py` / `darwinian.py` / `backtest.py` 的 `_store()`
   统一收敛到 `mosaic/scorecard/__init__.py` 的 `get_store(db_path=None)`。

9. **`update_scoring` rowcount 防御（顺带修 §14 R-T5）**：Phase 4 可能加
   purge old recommendations 路径；先把 `update_scoring` 在 `cur.rowcount==0`
   时 `log.warning` 补上，避免静默 no-op。

10. **CIO conviction 可比性（顺带定 §14 R-A2）**：autoresearch 比较 per-agent
    Sharpe 时，CIO 的 "conviction" 实为 target_weight（仓位权重，非真置信度）。
    **决策：Phase 4 评估 CIO mutation 时，用组合层 Sharpe（整个 portfolio 的
    回测 Sharpe）而非 per-pick conviction**，因此 CIO 的 conviction 不可比问题
    在 Phase 4 不影响 —— 评估永远基于「整组 portfolio_actions 跑出来的回测
    Sharpe」，不是 agent 自报 conviction。per-agent skill（scorecard.list_skill）
    只用于 mutator「选改哪个 agent + 改什么方向」的输入，不直接进 keep/revert
    判据。这条同时澄清了 §14 R-A2。

11. **不在 Phase 4 范围**（避免 scope creep）：
    - 多 cohort 并发训练（Phase 5 PRISM）
    - per-cohort 演化 trunk 两层 git 模型（Phase 5，见决策 #3）
    - JANUS 元层 / MiroFish（Phase 6/7）
    - RD-Agent 风格的 Researcher/Developer 拆分（plan §3.5 已记，Phase 4 只做
      单 LLM mutator，不拆角色）
    - prompt 多样性 / 探索-利用策略（先做「贪心：表现差的 agent 优先改」，
      bandit / 温度调度推迟）

### Sub-step 4A：SQLite schema + git_ops 基础 + 约束判定

> 纯 Python，无 LLM。把 plan §7 的 prompt_versions / autoresearch_log 落库，
> 写 git 操作封装，实现 3 个约束判定。这是后续所有 sub-step 的地基。

- [ ] `mosaic/scorecard/store.py` —— 加 plan §7 两张表到 `_SCHEMA_SQL`
      （`CREATE TABLE IF NOT EXISTS`，与现有表共库 `data/scorecard.db`）：
    - `prompt_versions(id, cohort, agent, branch_name, base_commit_hash,
      modification_commit_hash, modification_summary, created_at, status,
      decided_at, pre_sharpe, post_sharpe, delta_sharpe)`
      + `idx_pv_pending ON (status, created_at) WHERE status='pending'`
    - `autoresearch_log(id, prompt_version_id FK, event, detail, created_at)`
    - 新增 store 方法：`create_prompt_version(...)→id`（pending 起始）、
      `get_prompt_version(id)`、`list_prompt_versions(cohort?, status?, agent?)`、
      `set_version_eval(id, pre, post, delta)`、`decide_version(id, status,
      decided_at)`、`count_mutations_this_month(cohort)`、
      `last_mutation_at(cohort, agent)`、`append_log(version_id, event, detail)`、
      `get_log(cohort?, days?)`、`list_active_branches(cohort?)`（status='pending'
      或 'keep'-未清理的 branch）。
- [ ] `mosaic/autoresearch/__init__.py` + `mosaic/autoresearch/git_ops.py` ——
      薄封装 `git` CLI（subprocess，scoped 到 repo root，fail-loud）：
    - `current_commit()` / `current_branch()`
    - `create_branch(name, from_ref='main')`
    - `write_and_commit(paths_and_contents: dict[str,str], message, branch)`
      —— 在指定 branch 上写文件 + `git add` + `git commit`，返回 commit hash
    - `merge_to_main(branch, ff_only=True)` / `delete_branch(name)`
    - `show_file(ref, path) → str`（`git show <ref>:<path>`，给 prompts.read 用）
    - `add_worktree(ref) → path` / `remove_worktree(path)`（4C 评估用，隔离
      checkout 不动主工作树）
    - `push(ref, remote='origin')`（**Option B,可选自托管 git 服务器镜像**）——
      keep 路径 merge 成功后,若 `autoresearch.git.push=True`（默认 OFF）则
      `git push <remote> main`,把保留的 prompt 变更镜像到自托管服务器(Gitea/
      GitLab/裸库)。push 失败只 warn 不回滚 keep;凭证由 operator 预配置(SSH/
      credential helper),不入库。默认仍 100% 本地。
    - **安全**：所有写操作前 assert 当前无未提交改动（`git status --porcelain`
      为空），否则抛清晰错误（避免污染用户工作树）。
- [ ] `mosaic/autoresearch/constraints.py` —— 3 个纯函数（读 config.autoresearch
      + store）：
    - `check_cooldown(store, cohort, agent, now) → ok|reason`（24h）
    - `check_monthly_cap(store, cohort, now) → ok|reason`（≤100/月）
    - `check_keep_lockout(store, version, now) → ok|reason`（keep 后 3 天内不能
      revert）
- [ ] 收敛 store 单例：`mosaic/scorecard/__init__.py` 加 `get_store(db_path=None)`
      模块级缓存（修 §14 R-T4）；`update_scoring` 加 rowcount 警告（修 §14 R-T5）。
- [ ] tests：`tests/test_autoresearch_store.py`（version 状态机 + log + 计数）
      、`tests/test_git_ops.py`（在 `tmp_path` 里 `git init` 造迷你 repo 测
      branch/commit/merge/worktree/show_file）、`tests/test_autoresearch_constraints.py`。

**4A 设计决策**：
- git_ops 用 subprocess 调系统 `git`，不引 GitPython（少一个依赖；ETFAgents
  也没用 GitPython）。所有命令 `check=True` + 捕获 stderr 进异常 message。
- prompt_versions 与 backtest_runs 通过 `modification_commit_hash` ↔
  `prompt_commit_hash` 关联（**不加 FK**，因为 backtest run 可能晚于 version
  创建，且 base_commit 的 run 可能复用）。关联在查询层 join。
- worktree 放 `data/worktrees/<branch-slug>/`（gitignored），评估完即删。

### Sub-step 4B：Mutation 生成器（TS）+ `prompts.*` RPC（Python） ✅ 完成（2026-05-29，分支 phase-4b-mutator）

> TS 读现有 prompt + agent 近期 skill → LLM 生成改写。Python 提供 prompt 读写
> 的 git-aware RPC。

- [x] `mosaic/bridge/handlers/prompts.py` —— 新 handler（plan §6.2）：
    - `prompts.read(agent, cohort, lang, ref?)` —— ref 缺省读工作树磁盘文件
      （cohort → cohort_default fallback，与 TS loader 一致）；给 ref（commit/
      branch）时走 `git_ops.show_file`。返回 `{content, path}`。
    - `prompts.write(agent, cohort, contents:{zh?,en?}, branch?, message?)` ——
      **签名微调**：用 `contents`（lang→text 映射）一次写整对，保证一条 feature
      branch 只含 1 个 commit（plan git 决策）。branch 缺省直写工作树（危险，
      仅测试用，返回 `{paths}`）；给 branch 时走 `git_ops.write_and_commit`，
      返回 `{commit_hash, branch, paths}`。
    - 注册进 `handlers/__init__.py`（把注释里的 "prompts" 落实）。
- [x] `mosaic-ts/src/autoresearch/mutator.ts` —— mutation 生成器：
    - 输入：`{cohort, agent, deps:{llm, api}, since?, promptsRoot?}`
    - 流程：① `loadPrompt({agent,cohort,'zh'/'en', noCache:true})` 拿现 prompt；
      ② `api.scorecardListSkill(cohort)` + `api.darwinianGetWeights(cohort)` 拿
      该 agent 近期 mean_alpha / sharpe / weight；③ 组装「prompt 工程师」
      English meta-prompt；④ structured output 产出 `{zh_prompt, en_prompt,
      modification_summary, rationale}`（zod `MutationSchema`）；⑤
      `assertPromptInvariants` 校验护栏（决策 #5：保 section / 保 schema 字段名 /
      ±40% 限幅 / no-op 拒绝）。
    - 不直接写盘 / 不碰 git —— 返回改写结果给 orchestrator（4E）由它调
      `prompts.write` 落到 branch。
- [x] `mosaic-ts/src/bridge/types.ts` —— 加 `promptsRead` / `promptsWrite`
      typed wrappers + `PromptLang` / `PromptReadResult` / `PromptWriteResult`
      接口（`BridgeApi` 在 types.ts，无 api.ts）。
- [x] tests：`mosaic-ts/test/mutator.test.ts`（9 tests：护栏生效、length 限幅、
      no-op 检测、zh/en 同步、cold start 退化）；`tests/test_bridge_prompts.py`
      （11 tests：read 工作树 / fallback / read ref / write to branch + 工作树
      的 RPC 路由 + git roundtrip）。全绿。

**4B 设计决策**：
- meta-prompt 用 **English**（reasoning quality；与 §default_config 注释「内部
  agent debate 用英文」一致），但产出的 `zh_prompt` 仍是中文 prompt 内容。
- mutator 只「提议」不「落盘」：保证可在 orchestrator 层做 dry-run（生成但不
  commit）。
- skill 数据缺失（前 30 天 cold start，scorecard 还没数据）时，mutator 退化为
  「基于 prompt 自身可读性 / 约束清晰度」的泛化改进，meta-prompt 里明确告知
  「无近期表现数据，做保守的清晰化改写」。

### Sub-step 4C：评估引擎（backtest-based Δ Sharpe）

> 最复杂的一步。把「一个 pending version」变成「pre/post Sharpe + ΔSharpe」。
> 复用 Phase 3.5 两段式回测，git worktree 隔离改前/改后 prompt。

- [ ] `mosaic-ts/src/cli/commands/backtest-fill.ts` —— 加 `--prompts-root <path>`
      flag（透传给 `buildDailyCycleGraph` → `loadPrompt({promptsRoot})`）。
      让 stage-1 能从 worktree 的 `prompts/mosaic` 读改后 prompt，而不是只读主
      工作树。**这是 4C 唯一需要改的现有 TS 文件**（loader 已支持 promptsRoot 形参）。
    - 串改：`buildDailyCycleGraph(deps)` → graph 构造时把 `promptsRoot` 传到
      各 agent node 的 `loadPrompt` 调用。需检查 daily_cycle/factory 是否已透传
      `config.promptsRoot`；若没有，4C 补一条 deps 字段（向后兼容，缺省
      `findPromptsRoot()`）。
- [ ] `mosaic/autoresearch/evaluator.py` —— 评估编排（Python 侧只做 git
      worktree + Δ 计算；驱动 stage-1 fill 的 TS 命令由 orchestrator 在 4E 调）：
    - `ensure_baseline_run(cohort, window, base_commit) → run_id`：若
      `backtest_runs(cohort, window, base_commit)` 已 complete 直接返回；否则
      返回「需要 fill」信号（实际 fill 由 TS orchestrator 触发，见 #决策）。
    - `compute_delta(version_id) → {pre_sharpe, post_sharpe, delta_sharpe}`：读
      base_commit run + mod_commit run 的 `run_historical` metrics（Sharpe），
      算差，写回 `prompt_versions`（`set_version_eval`）+ `append_log('evaluated')`。
- [ ] `autoresearch.prepare_worktree(branch) → {path}` /
      `autoresearch.cleanup_worktree(path)` RPC（4D 的 handler 文件里一起注册）
      —— 让 TS orchestrator 能：① 让 Python 在 worktree checkout mod_commit；
      ② TS 用 `--prompts-root <worktree>/prompts/mosaic` 跑 backtest-fill；③
      跑完清理 worktree。
- [ ] tests：`tests/test_autoresearch_evaluator.py`（造两条 mock backtest run，
      验 ΔSharpe 计算 + 写回 + 日志）；worktree 生命周期测（复用 4A git_ops 测
      基建）。

**4C 设计决策**（跨语言评估流程，写清楚避免 4E 反工）：
- **评估的真实编排在 TS（4E orchestrator）**，因为 stage-1 fill 是 TS 命令
  （要跑 LangGraph daily-cycle + LLM）。Python evaluator 只负责 (a) 提供
  worktree、(b) 在两条 run 都 fill+run_historical 完之后算 ΔSharpe。
- **完整评估时序**（4E 把它串起来）：
  ```
  1. (Python) prepare_worktree(feature_branch) → wt_path   # checkout mod_commit
  2. (TS) backtest-fill --cohort C --start..--end --prompt-commit-hash <mod>
          --prompts-root wt_path/prompts/mosaic               # stage-1 改后
  3. (TS) backtest.run_historical(run_id=mod_run)            # stage-2 改后 → post_sharpe
  4. base run 若无缓存：用主工作树（main）跑同窗口 fill + run_historical → pre_sharpe
  5. (Python) compute_delta(version_id)                       # 读两条 run metrics 算差
  6. (Python) cleanup_worktree(wt_path)
  ```
- base run 复用：同 (cohort, window, base_commit) 的 run 一旦算过，后续所有改
  自同一 base 的 mutation 共享这条 pre_sharpe，**不重复跑**（这是 prompt_commit_hash
  缓存设计的最大收益）。
- worktree 而非 `git checkout`：避免在评估期间切换主工作树分支（用户可能正在
  主工作树上看代码 / 跑 daily-cycle）。worktree 是只读用途，评估完即删。

### Sub-step 4D：keep/revert 决策 + `autoresearch.*` RPC + git merge

- [ ] `mosaic/autoresearch/decider.py` —— `decide(store, git, version) → action`：
    - 读 `delta_sharpe`；`< keep_threshold(0.1)` → revert；`≥` → 先过
      `check_keep_lockout` → keep。
    - keep：`git_ops.merge_to_main(branch)` → `decide_version(keep)` +
      `append_log('kept')`。
    - revert：`git_ops.delete_branch(branch)` → `decide_version(revert)` +
      `append_log('reverted')`。
- [ ] `mosaic/bridge/handlers/autoresearch.py` —— plan §6.2 RPC：
    - `autoresearch.trigger(cohort, force_agent?)` —— 选 agent（缺省：
      scorecard 里 sharpe 最低且过 cooldown 的）+ 过 cooldown/monthly_cap →
      创建 pending version 的「壳」（branch 名 + base_commit；实际 mutation 内容
      由 TS mutator 产出后经 prompts.write 提交，再回填 mod_commit）。返回
      `{version_id, agent, branch_name, base_commit}`。
    - `autoresearch.record_mutation(version_id, mod_commit, summary)` —— TS 提交
      改写后回填 mod_commit + summary，version 转 pending-evaluable。
    - `autoresearch.evaluate_pending(cohort?)` —— 对 pending 且已有 mod_commit 的
      version 调 evaluator + decider（注：需要 TS 先把 backtest run fill 好；
      RPC 在 run 齐备时算 Δ + 决策，缺 run 时返回 "needs_fill" 让 orchestrator 补）。
    - `autoresearch.get_log(cohort?, days?)` / `autoresearch.list_active_branches()`
      / `autoresearch.revert_modification(version_id)`（手动 revert，过 lockout）。
    - `autoresearch.prepare_worktree` / `cleanup_worktree`（4C 用）。
    - 注册进 `handlers/__init__.py`。
- [ ] `mosaic-ts/src/bridge/{api,types}.ts` —— autoresearch.* typed wrappers + 接口。
- [ ] tests：`tests/test_autoresearch_decider.py`（keep / revert / lockout 拦截 /
      cap 拦截 + git 副作用 mock）；`tests/test_bridge_autoresearch.py`（RPC 路由
      + 幂等 trigger + 状态机）；`mosaic-ts/test/bridge_autoresearch.test.ts`。

**4D 设计决策**：
- trigger 与 mutation 分两步 RPC（trigger 建壳 → TS mutator 生成 →
  record_mutation 回填）。原因：mutation 内容由 TS LLM 产出，Python trigger 时
  还没有内容；先占坑（拿 base_commit + branch 名 + 过约束）能让幂等 & cooldown
  判定基于「坑」而非「内容」，避免并发重复改同一 agent。
- `evaluate_pending` 设计成「能算就算、缺 run 就报 needs_fill」，把「跑 stage-1
  fill」的副作用留给 TS orchestrator —— 保持 Python handler 无 LLM 依赖、可单测。

### Sub-step 4E：Orchestrator（TS）+ `pnpm dev autoresearch` CLI

- [ ] `mosaic-ts/src/autoresearch/orchestrator.ts` —— 把 4B/4C/4D 串成一轮：
    ```
    runAutoresearchCycle({cohort, evalDays, maxMutations, dryRun, deps}):
      for n in 1..maxMutations:
        t = api.autoresearchTrigger(cohort)            # 选 agent + 占坑（过约束）
        if t == null: break                            # 无可改 agent（全在 cooldown / cap 满）
        m = mutator.mutate({cohort, agent:t.agent, deps})
        if dryRun: print(m); continue                  # 只生成不提交
        w = api.promptsWrite(agent, cohort, 'zh', m.zh, branch:t.branch)  # + en
        api.autoresearchRecordMutation(t.version_id, w.commit_hash, m.summary)
        # 评估
        wt = api.autoresearchPrepareWorktree(t.branch)
        runMod = backtestFill(cohort, window, mod_commit, promptsRoot:wt.path)
        api.backtestRunHistorical(runMod)              # post sharpe
        ensureBaselineFilled(cohort, window, base_commit)   # pre sharpe（缓存复用）
        api.autoresearchEvaluatePending(cohort)        # Python 算 Δ + 决策 keep/revert
        api.autoresearchCleanupWorktree(wt.path)
    ```
- [ ] `mosaic-ts/src/cli/commands/autoresearch.ts` —— 子命令组：
    - `pnpm dev autoresearch trigger --cohort C [--agent X] [--max N] [--dry-run]`
      —— 跑生成 + 提交 + 评估 + 决策（一条龙）。`--dry-run` 只生成改写打印不
      落 git。
    - `pnpm dev autoresearch evaluate --cohort C` —— 单独评估已 pending 的
      version（断点续跑用）。
    - `pnpm dev autoresearch log --cohort C [--days N]` —— 打印 autoresearch_log。
    - `pnpm dev autoresearch branches` —— 列 active feature branch + pending
      version（agent / branch / base / 状态）。
    - `pnpm dev autoresearch revert <version_id>` —— 手动 revert（过 lockout）。
    - 风格沿用 `scorecard.ts` / `darwinian.ts`（picocolors 表格）。
- [ ] tests：`mosaic-ts/test/autoresearch_orchestrator.test.ts`（mock LLM + mock
      BridgeApi，验一轮 trigger→mutate→commit→eval→decide 的调用序列 + dryRun
      不写 git）。

**4E 设计决策**：
- orchestrator 默认 **`--fake-llm` 可跑通**（CI / 零成本 smoke）：mutator 用
  canned 改写、backtest-fill 用 mock LLM。真实改写用 lemonade 本地（开发期）/
  anthropic（生产期）。
- `--max N`（默认 1）：单 cohort 单日默认只改 1 个 agent（plan §14 #3 触发频率
  「单 cohort 每天 1 次」），避免一次 trigger 风暴。

### Sub-step 4F：端到端 dry-run + 文档 + PR

- [ ] 端到端 smoke（`--fake-llm` + 极小 eval 窗口，如 `--eval-days 5`）：
    ```
    pnpm dev autoresearch trigger --cohort crisis_2008 --agent volatility --eval-days 5 --fake-llm
    ```
    观察：① 建出 `cohort/crisis_2008/auto/volatility/<date>` branch +
    1 commit（新增 `prompts/mosaic/cohort_crisis_2008/macro/volatility.{zh,en}.md`）；
    ② prompt_versions 多 1 行（pending→keep/revert）；③
    autoresearch_log 有 triggered/mutated/evaluated/kept|reverted 事件链；④
    keep 时 prompt 改动 merge 回 main，revert 时 branch 被删、main 不变。
- [ ] 验证约束：连跑 2 次同 agent → 第 2 次被 cooldown 拦（返回换别的 agent
      或 no-op）；造一个 keep 后立刻 revert → 被 3 天 lockout 拦。
- [ ] 文档：更新 plan §3 表（Phase 4 → ✅）、§14 相关条目收敛、§11.5 各 sub-step
      状态 + 完成时戳；`mosaic-ts/README.md` / `README.md` 加 autoresearch CLI 用法。
- [ ] 验证矩阵（沿用 §15）：`pnpm typecheck` / `pnpm lint` / `pnpm test` /
      `python -m unittest discover -s tests -q` 全绿。
- [ ] PR `phase-4-autoresearch → main`（类似 PR #2/#3/#4 流程）。

**4F 设计决策**：
- 端到端 smoke 对象 = `crisis_2008`（已确认决策 #10）。该 cohort 无专属 prompt，
  全 fallback 到 cohort_default，base 回测读 default；mutation 只新增被改 agent
  的 cohort_crisis_2008 文件，故 base/post 仅在该 agent 上有差异（ΔSharpe 干净）。
- `--fake-llm` 模式下 mutator 产出一个**确定性的小改动**（如在 prompt 末尾追加
  一行 marker 段），保证 smoke 可重复断言，不依赖真实 LLM 输出。

### Phase 4 出口标准

- `autoresearch.{trigger,record_mutation,evaluate_pending,get_log,
  list_active_branches,revert_modification}` + `prompts.{read,write}` RPC 全部
  注册并被 TS typed wrapper 覆盖
- `prompt_versions` + `autoresearch_log` 两表落库，version 状态机
  pending→keep/revert 跑通
- `pnpm dev autoresearch trigger --cohort crisis_2008 --fake-llm` 端到端跑通：
  建 branch + commit、算 ΔSharpe、按阈值 keep（merge 回 main）或 revert（删 branch）
- 约束生效：24h cooldown / 3 天 keep-lockout / 月度 100 上限 都有测试覆盖且
  端到端可触发
- §14 R-T4（store 单例）/ R-T5（update_scoring 警告）/ R-A2（CIO 用组合 Sharpe
  评估）顺带收敛
- PR `phase-4-autoresearch → main`

### Phase 4 启动前的 pre-flight（4.0）

- **(P1) Layer-1 macro tools 缺口（plan §14 #8）— 已决定 Phase 4 后补（决策 #13）**：
  autoresearch 优化的是 agent prompt，工具集缺口（property / usdcny / commodity
  / ivx 用 proxy 替代）会限制 mutation 优化空间，但**用户已确认先跑通机制本身**，
  P1 不在 Phase 4 范围执行；记入 Phase 4 后续 / Phase 5 启动前补
  `get_property_data` / `get_usdcny` / `get_commodity_prices` / `get_ivx`。
- **(P2) 评估 LLM 成本 — 默认 lemonade 本地零成本**：60 天 eval 窗口 × 25 agents
  × 每次 mutation 评估 ≈ 1500 次 daily-cycle agent 调用。用 lemonade 本地跑零
  成本。若改用 anthropic 评估需先估预算（plan §13.3：约 $0.125/cycle × 60 ≈
  $7.5/次 mutation 评估，偏贵）。

---

## 11.6 Phase 5 详细任务（Sub-step 5A–5E）— PRISM 7-cohort 训练编排

> 估算 5–6 turns。分支：`phase-4c-5-autoresearch-prism`（与 4C–4F 同 PR）。
> **目标**：把 Phase 4 的「单 cohort 单 agent autoresearch 一轮」放大成
> 「7 个 regime cohort 各自演化一套 prompt」的训练编排。Phase 5 出口后，
> `pnpm dev prism train --all --fake-llm` 能按 §1 并发模型把 7 个 cohort
> 依次训练一遍，每个 cohort 的 25 个 agent prompt 被逐层 autoresearch 迭代，
> 结果落进 cohort 演化分支 + cohort_runs 账本，可 `prism compare` 横评。

### 已确认决策（§1，Phase 5 据此定稿）

- **并发模型（§1 PRISM 并发）**：**cohort 之间顺序**训练（避免 7×25 同时打爆
  Anthropic 限速）；**cohort 内 layer 间顺序**（macro→sector→superinvestor→
  decision，因为下层依赖上层的输出语义）；**layer 内最多 5 个 agent 并发**
  （`max_agents_concurrent=5`，可配）。
- **7 cohort（§9）**：bull_2007 / crisis_2008 / bull_2016 / crisis_covid /
  recovery_2020 / euphoria_2021 / rate_tightening。顺序 = COHORT_CONFIGS 声明序。
- **git 演化模型（§8 两层）**：Phase 4 的单 trunk(main)+短寿 feature branch 升级成
  `cohort/<name>/main` 长寿演化 trunk + 短寿 `cohort/<name>/auto/<agent>/<date>`
  feature branch。每个 cohort 的 keep mutation 累积进它自己的 `cohort/<name>/main`。
  （Phase 4 决策 #3 把这条简化推迟到 Phase 5；此处落地。）
- **prompt fallback**：cohort 启动时无专属 prompt，全 fallback 到 cohort_default；
  训练逐步在 `prompts/mosaic/cohort_<name>/` 累积分叉文件（与 4F 同机制）。
- **复用 Phase 4 全栈**：每个 (cohort, agent) 的训练就是调一次
  `runAutoresearchCycle({cohort, forceAgent, maxMutations:1, ...})`。Phase 5
  **不重写** trigger/mutate/evaluate/decide，只做**编排层**（fan-out + 并发 +
  顺序 + 账本）。

### Phase 5 起跑前的事实基线（PR #9 已落地部分）

| 设施 | 位置 | 状态 |
|---|---|---|
| 7 cohort 定义 `COHORT_CONFIGS` + `list_cohorts/get_cohort/get_cohort_prompt_dir` | `mosaic/prism/cohorts.py` | ✅ PR #9 |
| `cohort_runs` 表 + `create_cohort_run/complete_cohort_run/get_cohort_runs/get_cohort_status_summary` | `mosaic/scorecard/store.py` | ✅ PR #9（`complete_cohort_run` 当时未被调用） |
| `ensure_cohort_branch` / `compare_cohorts` | `mosaic/prism/trainer.py` | ✅ PR #9 |
| `prism.{list_cohorts,train_cohort,cohort_status,compare_cohorts}` RPC + TS wrapper | `mosaic/bridge/handlers/prism.py` + `types.ts` | ✅ PR #9 |
| `pnpm dev prism {list,train,status,compare}` CLI | `mosaic-ts/src/cli/commands/prism.ts` | ✅ PR #9（train 仅建 branch+run 壳，未跑训练） |
| 7 个 per-cohort prompt 目录 `.gitkeep` | `prompts/mosaic/cohort_*/` | ✅ PR #9 |
| `runAutoresearchCycle`（单 agent 一轮 trigger→mutate→eval→decide） | `mosaic-ts/src/autoresearch/orchestrator.ts` | ✅ Phase 4 |

**PR #9 的核心缺口**：`prism.train_cohort` 只是「建 branch + 建 cohort_run 壳」的
infra-stub，**没有真正的训练循环**（按 §1 并发模型逐层 fan-out agent 调
autoresearch）。`max_agents_concurrent` 形参定义了但没用；`complete_cohort_run`
方法存在但没人调。Phase 5 要补的就是这个**真训练编排器**。

### Sub-step 5A：TS 训练编排器（核心缺失件）

- [x] `mosaic-ts/src/prism/trainer.ts` —— PRISM 训练编排：
    - `runCohortTraining({cohort, layers?, maxAgentsConcurrent=5, maxMutationsPerAgent=1,
      dryRun, fakeLlm, deps, onLog}) → {cohort, layers:[{layer, agents:[MutationResult]}]}`：
      - 按 `["macro","sector","superinvestor","decision"]` **顺序**遍历 layer；
      - 每个 layer 内，对该 layer 的 agent 列表（`AGENTS_BY_LAYER[layer]`）做
        **并发上限 = maxAgentsConcurrent** 的 fan-out（一个轻量 `pool()` 信号量，
        不引依赖）；
      - 每个 agent 调 `runAutoresearchCycle({cohort, forceAgent:agent,
        maxMutations:maxMutationsPerAgent, dryRun, fakeLlm, deps})`，收集其
        `mutations[0]` 结果；
      - 返回逐层结果，供 CLI 汇总打印。
    - `runPrismTraining({cohorts?, ...}) → [{cohort, ...}]`：对 cohorts（缺省 7 个
      声明序）**顺序**调 `runCohortTraining`，cohort 之间不并发。
- [x] tests：`mosaic-ts/test/prism_trainer.test.ts`（mock LLM + mock BridgeApi）：
      验 ① layer 顺序 macro→…→decision；② layer 内并发不超过 cap（用计数器探针）；
      ③ 每个 agent 以 `forceAgent` 调 orchestrator；④ dryRun/fakeLlm 透传；
      ⑤ `runPrismTraining` cohort 顺序。

### Sub-step 5B：`prism.complete_cohort_run` RPC + 账本闭合

- [x] `mosaic/bridge/handlers/prism.py` —— 加 `prism.complete_cohort_run(run_id,
      llm_calls?, llm_cost_usd?, cio_action?, cio_target_weight?)` RPC（store 方法
      已存在，PR #9 未暴露）。注册进 handler。
- [x] `mosaic-ts/src/bridge/types.ts` —— `prismCompleteCohortRun` typed wrapper。
- [x] tests：`tests/test_bridge_prism.py` 加 complete_cohort_run 路由 + 账本回填
      （cycle_completed_at / llm_calls 写入）测试。

### Sub-step 5C：`prism train` CLI 接真训练循环

- [x] `mosaic-ts/src/cli/commands/prism.ts` `train` 子命令重写为一条龙：
    - flags：`--cohort <name>` | `--all`、`--max-concurrent <n>`（默认 5）、
      `--max-mutations <n>`（默认 1）、`--dry-run`、`--fake-llm`、
      `--llm-provider/--model/--base-url`。
    - 流程：① `prism.train_cohort`（建 cohort 演化 branch + cohort_run 壳，拿
      run_id）；② 调 `runCohortTraining`（或 `--all` 时 `runPrismTraining`）跑真
      训练；③ 跑完 `prism.complete_cohort_run(run_id, llm_calls=…)` 闭合账本；
      ④ picocolors 表格打印 per-layer / per-agent kept|reverted|needs_fill 结果。
    - `--dry-run` / `--fake-llm` 全程透传到 orchestrator（零成本 smoke）。
- [x] CLI 已在 `cli/index.ts` 注册（PR #9 done）。

### Sub-step 5D：端到端 fake-llm smoke + 约束验证

- [x] `pnpm dev prism train --cohort crisis_2008 --fake-llm --max-concurrent 5`
      端到端跑通：观察 ① `cohort/crisis_2008/main` 演化 trunk 建出；②
      25 agent 逐层被触发（受 cooldown：同 agent 当日第 2 次被拦，符合预期）；
      ③ cohort_runs 多 1 行且 cycle_completed_at 被回填；④ 结果表打印。
- [x] `pnpm dev prism train --all --fake-llm --dry-run` 7 cohort 顺序跑、无副作用。
- [x] `pnpm dev prism compare` 横评 7 cohort 的 n_runs / n_mutations / kept / reverted。

### Sub-step 5E：文档 + 验证矩阵 + 状态收口

- [x] 文档：`mosaic-ts/README.md` 的 prism 段补 `--all/--max-concurrent/--fake-llm`；
      plan §3 表 Phase 5 状态从「✅ 完成（仅 infra）」更新为「✅ 完成（训练编排
      落地）」；§11.6 各 sub-step 勾选 + 完成时戳。
- [x] 验证矩阵（§15）：`pnpm typecheck` / `pnpm lint` / `pnpm test` / `ruff` /
      dependency-light `pytest` 全绿。

### Phase 5 出口标准

- TS 训练编排器 `runCohortTraining` / `runPrismTraining` 落地，严格遵守 §1 并发
  模型（cohort 顺序 / layer 顺序 / layer 内 ≤5 并发），有测试覆盖并发上限。
- `prism.complete_cohort_run` RPC 注册 + TS wrapper，cohort_run 账本能闭合。
- `pnpm dev prism train --cohort C --fake-llm` 端到端跑通真训练循环（非 stub），
  `--all` 顺序训练 7 cohort，`--dry-run` 无副作用。
- `prism compare` 能横评 7 cohort。
- §3 表 Phase 5 标注「训练编排落地」（区别于 PR #9 的 infra-only stub）。

### Review 收口（f3af696 → 后续 commit，2026-05-30）

- **账本归编排器**：`cohort_runs` 的开（`prism.train_cohort` 壳）+ 关
  （`prism.complete_cohort_run`，放 `finally`）移进 `runCohortTraining`，使
  `runPrismTraining` / 外部 caller / CLI 走同一路径，账本不再只在 CLI、不漏关。
- **per-agent 隔离**：每个 agent 的 cycle 用 try/catch 包裹，单 agent 抛错只产
  `status='error'` 条目，不再 reject `pool()` worker / 中止整 cohort。
- **全量 mutation**：layer 结果保留每个 agent 的全部 mutations（修
  `maxMutations>1` 漏报）。
- **llm_calls 不误标**：不再把 agent 计数写进 `cohort_runs.llm_calls`（那列含义
  是 LLM 调用次数，留给 bridge 成本层）。
- **deps-light 双注册崩溃修复**：`test_prism.py` / `test_bridge_autoresearch.py`
  的 except 分支先查 `sys.modules`（包 __init__ 在 tools 失败前已注册过
  prism/autoresearch），命中则复用，不再 re-exec 致 `@method` 重复注册。
- **O(N²) evaluate_pending ✅ 已修复（2026-05-30）**：`autoresearch.evaluate_pending`
  加可选 `version_id` 参数；orchestrator 评估时只传刚 trigger 的 version，使一个
  N-agent layer 做 N 次单 version 评估而非 N 次全 cohort 扫描。缺省（无 version_id）
  仍扫全部 pending（`prism evaluate` / 断点续跑契约不变）。
- **遗留（同 4C–4F 限制）**：fake-llm 下终态仍是 `needs_fill`（keep/revert/merge
  需 qlib stage-2）。

### 不在 Phase 5 范围（避免 scope creep）

- 真实（非 fake-llm）大规模训练跑通 = 运行期任务，依赖 qlib `.[backtest]` +
  lemonade/anthropic 预算，不在本 PR 代码范围。
- cohort 之间的 prompt 迁移学习 / 跨 cohort 知识共享（Phase 6 JANUS 元层）。
- 训练进度断点续跑的持久化队列（先用 cooldown 幂等兜底，足够 MVP）。

---

## 11.7 Phase 6 详细任务（Sub-step 6A–6D）— JANUS 元加权层

> 估算 3 turns。分支：`phase-6-janus`。**目标**：port ATLAS `janus.py`（571 LOC）
> 的元加权思想到 MOSAIC —— 在 7 个 PRISM regime cohort **之上**再加一层，按各
> cohort 近期预测准确度（rolling hit_rate + Sharpe）动态加权、融合它们的当日
> 推荐，并把 cohort 权重差作为 regime 信号。Phase 6 出口后：
> `pnpm dev janus run` 能产出「跨 cohort 融合推荐 + regime 标签 + 各 cohort
> 30 天准确度」，并落库 + 留历史供 TUI（Phase 9）画权重漂移曲线。

### 从 ATLAS 移植的核心思想（保留）

ATLAS `Janus` 类（2 个时间窗 cohort：18month / 10year）：
- `calculate_cohort_metrics`：rolling 窗内 hit_rate（方向对不对）+ 加权收益的
  年化 Sharpe。
- `_softmax_with_constraints`：raw_score = 0.5·hit_rate + 0.5·norm_sharpe →
  softmax → 加 floor/ceiling 约束（MIN/MAX_WEIGHT）+ 重归一。
- `regime_signal`：短窗 vs 长窗权重差 > 阈值 → NOVEL/HISTORICAL/MIXED。
- `blend_recommendations`：按 cohort 权重对同 ticker 的多 cohort 推荐做
  conviction 加权融合，方向冲突时 `contested` 并打折。
- `run_daily`：load → update_weights → blend → regime → 落 daily + history。

### MOSAIC 适配（关键差异，写清楚避免照抄踩坑）

1. **数据源 JSON-file → SQLite**：ATLAS 读 `recommendations_<cohort>.json` +
   `scored_outcomes.json`。MOSAIC 全在 `data/scorecard.db`：
   - 各 cohort 的「推荐」= 该 cohort 的 **CIO 行**（`recommendations` 表
     `agent='cio'`，即 Layer-4 最终组合动作）。
   - 准确度 = `list_scored(cohort, agent='cio', since_date)` 的已评分行
     （`forward_return_5d` + `action`）。hit = (LONG/BUY 且 ret>0) 或
     (SHORT/SELL/REDUCE 且 ret<0)。
2. **2 cohort → 7 regime cohort**：cohort 集 = PRISM 的 7 个（`COHORT_CONFIGS`）。
3. **softmax 约束必须 feasibility-aware**：ATLAS 的 MIN_WEIGHT=0.2 对 2 cohort
   可行，但 7 cohort × 0.2 = 1.4 > 1 不可行。改为 `floor = min(MIN_WEIGHT,
   0.5/N)`、`ceiling = max(MAX_WEIGHT, 1.5/N)`，保证任意 N 都可归一；逻辑同
   ATLAS（floor→renorm→ceiling→renorm）。
4. **conviction 来源**：CIO conviction 已按 §14 R-A2 写 NULL，故 blend 用
   `target_weight_pct`（仓位权重 0–100）作 cohort 内 per-pick 强度。
5. **regime 信号**：ATLAS 是「短窗 vs 长窗」二元差。MOSAIC 7 cohort 无单一轴，
   改为「**当前最高权 cohort 的 regime 标签**」（crisis / bull / recovery /
   rate_tightening / euphoria…）+ 权重集中度（max_weight − uniform，> 阈值 =
   `CONCENTRATED`，否则 `DIFFUSE`）。即输出 `{dominant_cohort, regime_label,
   concentration}`。
6. **落盘**：新增 `janus_runs` 表（date, weights_json, regime_label,
   dominant_cohort, concentration, n_blended, n_contested, created_at）+
   `get_janus_history(days)`。daily 全量输出走 RPC 返回，不必落 blended 明细
   （与 ATLAS history-summary 一致）。

### Sub-step 6A：`mosaic/janus/` 核心元加权（纯 Python，无 LLM）

- [x] `mosaic/janus/__init__.py` + `mosaic/janus/meta.py`：
    - `cohort_accuracy(store, cohort, now_iso, window_days=30) → {hit_rate, sharpe, n}`
      （读 `list_scored(cohort,'cio',since)`，算 hit_rate + 加权收益年化 Sharpe）。
    - `compute_cohort_weights(store, cohorts, now_iso, window_days) → {cohort: weight}`
      （raw=0.5·hit+0.5·norm_sharpe → `softmax_with_constraints`）。
    - `softmax_with_constraints(scores, n) → weights`（feasibility-aware floor/ceiling）。
    - `regime_signal(weights, cohort_configs) → {dominant_cohort, regime_label, concentration}`。
    - `blend_recommendations(store, weights, date) → {blended:[...], contested:[...]}`
      （跨 cohort 同 ticker 按权重 × target_weight_pct 融合 + 冲突打折，port
      ATLAS `_blend_ticker_recommendations`）。
    - `run_daily(store, cohorts, date, window_days) → output dict` + 落 `janus_runs`。
- [x] `mosaic/scorecard/store.py`：加 `janus_runs` 表 + `record_janus_run` /
      `get_janus_history`。
- [x] tests：`tests/test_janus.py`（accuracy hit/sharpe、softmax 约束在 N=2/7
      都可行且 sum=1、regime dominant/concentration、blend 冲突打折 + contested）。

### Sub-step 6B：`janus.*` RPC handlers

- [x] `mosaic/bridge/handlers/janus.py`：
    - `janus.run_daily(date?, window_days?)` → 全量 output（weights/regime/blended/
      contested/accuracy）+ 落库。
    - `janus.get_weights(date?, window_days?)` → 只算权重 + accuracy（不 blend）。
    - `janus.regime(date?, window_days?)` → 只 regime 信号。
    - `janus.get_history(days?)` → `janus_runs` 历史（TUI 用）。
    - 注册进 `handlers/__init__.py`。
- [x] tests：`tests/test_bridge_janus.py`（RPC 路由 + 落库 + 空数据兜底）。

### Sub-step 6C：TS wrappers + `pnpm dev janus` CLI

- [x] `mosaic-ts/src/bridge/types.ts`：`JanusRunResult` / `JanusWeights` /
      `JanusRegime` / `JanusHistoryEntry` 接口 + `janusRunDaily` / `janusGetWeights`
      / `janusRegime` / `janusGetHistory` wrappers。
- [x] `mosaic-ts/src/cli/commands/janus.ts`：`run` / `weights` / `regime` /
      `history` 子命令（picocolors 表格，复用 `_format.pad`），注册进 `cli/index.ts`。
- [x] tests：CLI 走真 bridge（dependency-light 下 janus 不需要 langchain，能跑）。

### Sub-step 6D：文档 + 验证 + PR

- [x] plan §3 表 Phase 6 → ✅；§11.7 勾选 + 时戳；`mosaic-ts/README.md` 加 janus CLI。
- [x] 验证矩阵：`pnpm typecheck/lint/test` + `ruff` + dependency-light `pytest` 全绿。
- [x] PR `phase-6-janus → main`。

### Phase 6 出口标准

- `mosaic/janus/meta.py` 元加权落地：cohort 准确度 → feasibility-aware softmax
  权重 → regime 信号 → 跨 cohort blend，全有测试覆盖（含 N=7 约束可行性）。
- `janus.{run_daily,get_weights,regime,get_history}` RPC 注册 + TS wrapper + CLI。
- `janus_runs` 表落库 + 历史查询。
- `pnpm dev janus run` 端到端跑通（空数据→equal weights 兜底；有数据→加权融合）。

### 不在 Phase 6 范围

- 用 JANUS regime 信号反向驱动 paper-trading 仓位（Phase 8 执行层）。
- TUI 权重漂移曲线可视化（Phase 9）。
- 真实多 cohort 训练数据下的调参（运行期，依赖 Phase 5 实跑）。

---

## 11.8 Phase 7 详细任务（Sub-step 7A–7E）— MiroFish 反身性 / 前向模拟

> 估算 4–5 turns。分支：`phase-7-mirofish`。**目标**：port ATLAS `mirofish/`
> (~2,800 LOC) 的**前向训练**思想到 MOSAIC —— 用合成「未来情景」（蒙特卡洛
> 相关价格路径 + 事件注入）让 agent 在「可能发生什么」上做决策，再用合成结果
> 打分、形成与真实 P&L **隔离**的反身性反馈环。Phase 7 出口后：
> `pnpm dev mirofish train --fake-llm` 能 (1) 生成 base/bull/bear/tail 情景，
> (2) 把情景喂给 agent 拿推荐，(3) 对合成价格路径打分，(4) 落 mirofish_runs
> 账本 —— 一条不碰实盘的「想象力」训练通道。

### ATLAS MiroFish 拆解（5 模块）与 MOSAIC 取舍

| ATLAS 模块 | 作用 | MOSAIC 处理 |
|---|---|---|
| `mirofish_futures_generator.py` | **纯 numpy** 相关价格路径蒙特卡洛（Cholesky）+ 情景类型 + 事件注入 | **核心移植**（无 LLM，最值钱）→ `mosaic/mirofish/scenarios.py` |
| `mirofish_trainer.py` | 把情景喂 agent → 拿 rec → 对路径打分 → 更新权重 | 拆成 Python 打分（`score_recommendation`）+ TS LLM agent-rec（`mirofish/trainer.ts`） |
| `mirofish_seed_generator.py` | 市场情报 briefing（价格/macro/agent 辩论）作 swarm 种子 | **简化**：MOSAIC 用现有 scorecard/regime 数据，不重写 FMP/FRED briefing；情景起点价取 A 股 ETF |
| `mirofish_context.py` | 把预测注入 prompt | 推迟（Phase 7 只做训练环，prompt 注入等真实跑） |
| `mirofish_bridge.py` | ATLAS 自己的桥 | 不需要（MOSAIC 用统一 JSON-RPC bridge） |

### MOSAIC 适配（关键差异，写清楚）

1. **职责切分**（沿用 autoresearch/prism 架构）：Python sidecar 拥有 numpy 情景
   生成 + 打分 + 持久化；TS 拥有 LLM agent-rec 步骤 + 编排。**不跨语言传 numpy**
   （情景以 JSON dict 过桥）。
2. **资产 US → A 股 regime ETF/指数**：ATLAS 用 SPY/QQQ/TLT/GLD/XLE/VXX/HYG。
   MOSAIC 用：`000300.SH`(沪深300)、`510050.SH`(上证50ETF)、`159915.SZ`(创业板ETF)、
   `511010.SH`(国债ETF≈TLT)、`518880.SH`(黄金ETF)、`512880.SH`(证券ETF≈高 beta)、
   `513050.SH`(中概互联≈成长)。`ASSET_PARAMS`(vol/drift) + `CORRELATIONS` 按 A 股
   特征重设（创业板/证券高 vol、国债/黄金避险负相关、沪深300 为锚）。
3. **情景类型保留**：base(0.5)/bull(0.2)/bear(0.2)/tail_up(0.05)/tail_down(0.05)，
   drift 调整 + 事件注入（A 股事件：业绩季 / 解禁 / 政策窗口 / 春节 / FOMC 外溢）。
4. **打分**：port `score_recommendation` —— rec(BUY/SELL/HOLD + tickers + conviction)
   对情景 cumulative_return 打分（方向对×收益，conviction 加权奖惩），0–1。
5. **反馈隔离**：MiroFish 是**合成训练**，结果落独立 `mirofish_runs` 账本（不写
   `recommendations` / 不进真实 scorecard alpha）。是否反哺 Darwinian 权重 = 推迟
   决策（先把训练环跑通，记 §14 待决）。
6. **确定性**：scenario 引擎接受 `seed` 参数（`np.random.default_rng(seed)`），让
   `--fake-llm` smoke + 测试可重复断言。

### Sub-step 7A：`mosaic/mirofish/scenarios.py` 情景引擎（纯 Python numpy）

- [x] `ASSET_PARAMS`(A 股 7 资产 vol/drift) + `CORRELATIONS`（A 股相关结构）。
- [x] `generate_correlated_returns(tickers, num_days, adjustments, seed)`：Cholesky
      相关正态（奇异时 SVD 兜底，port 原逻辑）。
- [x] `generate_scenario(scenario_type, start_prices, num_days, seed)` → dict：
      drift 调整（base/bull/bear/tail_up/tail_down 乘子）+ `generate_price_path` +
      `_generate_events`（A 股事件注入）+ `final_state`（regime 判定）。
- [x] `generate_all_scenarios(start_prices, num_days, seed)` → 5 情景。
- [x] `score_recommendation(rec, scenario)` → float[0,1]（port ATLAS 打分 + conviction
      奖惩）。
- [x] tests：`tests/test_mirofish.py`（固定 seed 可重复、价格路径长度/收益符号、
      相关矩阵正定兜底、bull>bear SPY 收益、打分方向 + conviction 奖惩）。

### Sub-step 7B：`mirofish_runs` 持久化 + RPC handlers

- [x] `mosaic/scorecard/store.py`：`mirofish_runs` 表（date, scenario_type,
      n_scenarios, agent, avg_score, detail_json, created_at）+ `record_mirofish_run`
      / `get_mirofish_history`。
- [x] `mosaic/bridge/handlers/mirofish.py`：
    - `mirofish.generate_scenarios(num_days?, scenarios?, seed?)` → 情景 dict 列表。
    - `mirofish.score_recommendation(recommendation, scenario)` → {score}。
    - `mirofish.record_run(date, scenario_type, agent, avg_score, detail?)` → {id}。
    - `mirofish.get_history(days?)` → 账本。
    - 注册进 `handlers/__init__.py`。
- [x] tests：`tests/test_bridge_mirofish.py`（RPC 路由 + deps-light guarded import）。

### Sub-step 7C：TS 前向训练器 + CLI

- [x] `mosaic-ts/src/mirofish/trainer.ts` —— `runMirofishTraining({cohort, numDays,
      scenarios, agents, fakeLlm, deps})`：① `mirofish.generate_scenarios` 拿情景；
      ② 对每个 (scenario, agent) 用 LLM（`forceAgent` 风格 / `--fake-llm` canned
      rec）拿推荐；③ `mirofish.score_recommendation` 打分；④ `mirofish.record_run`
      落账。无真实 LLM 时用确定性 canned rec。
- [x] `mosaic-ts/src/bridge/types.ts` —— `MirofishScenario` / `MirofishRunResult` 等
      接口 + `mirofishGenerateScenarios` / `mirofishScoreRecommendation` /
      `mirofishRecordRun` / `mirofishGetHistory` wrappers。
- [x] `mosaic-ts/src/cli/commands/mirofish.ts` —— `generate` / `train` / `history`
      子命令（picocolors 表格，复用 `_format.pad`），注册进 `cli/index.ts`。
- [x] tests：`mosaic-ts/test/mirofish_trainer.test.ts`（mock api + canned LLM：
      scenario→rec→score→record 调用序列、fakeLlm 透传）。

### Sub-step 7D：端到端 fake-llm smoke

- [x] `pnpm dev mirofish train --fake-llm --seed 42` 端到端跑通：生成 5 情景 →
      每 agent 拿 canned rec → 打分 → mirofish_runs 落账 → 表格汇总。
- [x] `pnpm dev mirofish generate --seed 42 --print` 确定性情景输出可重复。

### Sub-step 7E：文档 + 验证 + PR

- [x] plan §3 表 Phase 7 → ✅；§11.8 勾选 + 时戳；`mosaic-ts/README.md` 加 mirofish CLI；
      `pyproject` `.[data]` 显式加 `numpy`。
- [x] 验证矩阵：`pnpm typecheck/lint/test` + `ruff` + dependency-light `pytest` 全绿。
- [x] PR `phase-7-mirofish → main`。

### Phase 7 出口标准

- `mosaic/mirofish/scenarios.py` 纯 numpy 情景引擎落地：相关蒙特卡洛 + 5 情景 +
  事件注入 + 打分，固定 seed 可重复，全有测试覆盖。
- `mirofish.{generate_scenarios,score_recommendation,record_run,get_history}` RPC +
  TS wrapper + CLI + `mirofish_runs` 账本。
- `pnpm dev mirofish train --fake-llm --seed 42` 端到端跑通（合成训练，不碰实盘）。

### 反身性叠加层（reflexivity overlay，2026-05-30 增补）

> 用户指出 MiroFish 的「正主」是 [666ghj/MiroFish](https://github.com/666ghj/MiroFish)
> —— 一个 **swarm 反身性引擎**：seed → GraphRAG → 上千个有人格/记忆的 agent
> 互相交互 + 社会演化（基于 OASIS/CAMEL-AI），由**集体涌现**塑造轨迹。ATLAS 的
> ~2,800 LOC 移植版（本 PR 起点）只有 numpy 蒙特卡洛 + 单 agent 打分，**没有任何
> 反身性反馈**，「反身性模拟」名不副实。

为闭合这个保真度差距（但不引入 OASIS/GraphRAG/记忆这套重依赖），加了一个**轻量、
确定性、纯 numpy 的反身性叠加层**（`generate_scenario(reflexivity=True)`，默认关，
关时与原行为字节一致）：一群行为型 actor（momentum / contrarian / herding / value
四原型）每天根据**近期价格行为**产生净需求，需求**反馈进次日收益**（price →
behaviour → price 闭环）。这抓住了 canonical MiroFish 的*定义性*机制——actor 对
集体行为做反应、反过来改变轨迹——而非 i.i.d. 随机游走。验证：bull 趋势被放大
（0.17→0.33），tail 离散度变宽（stdev 0.088→0.132），全程有限稳定、固定 seed 可
重复。RPC / TS trainer / CLI 加 `--reflexive` / `reflexivity` 透传。

**仍与 canonical MiroFish 的差距（诚实记录）**：本叠加层是**行为原型的解析近似**，
不是真正的 LLM swarm —— 没有 per-agent 人格、长期记忆（Zep）、GraphRAG 知识图、
agent 间显式消息传递、社会网络拓扑、God's-eye 变量注入。要做到那种保真度需要接
OASIS/CAMEL-AI，是独立的大工程（远超 plan §3 给 Phase 7 的 4–5 turns 预算）。本
overlay 是「在 numpy 约束内最大化反身性保真度」的务实选择；真 swarm 留作 Phase 7+
的可选增强。

### 不在 Phase 7 范围

- MiroFish 反哺 Darwinian 真实权重（隔离原则；是否接入记 §14 待决）。
- **真 LLM swarm**（canonical 666ghj/MiroFish 的 GraphRAG + Zep 记忆 + 上千 persona
  agent + OASIS 社会模拟）—— 重依赖、超 Phase 7 预算；本 PR 用解析反身性叠加层近似，
  真 swarm 留作 Phase 7+ 可选增强。
- prompt 注入 MiroFish 预测（`mirofish_context` 等价物）—— 等真实跑再做。

---

## 11.8.1 MiroFish 全保真路线图（Roadmap：从解析叠加层 → 真 swarm）

> **动机**（用户 2026-05-30）：agent-to-agent 交互、记忆、涌现/反身性动态是模拟的
> 灵魂。§11.8 的 reflexivity overlay 只是**解析近似**（行为原型 → 需求 → 价格反馈），
> 抓住了「反身性的*结果*」但没有「反身性的*机制*」——没有真正的 agent 互相观察、
> 记忆、演化。本节设计如何分阶段补齐，逼近 canonical MiroFish（666ghj/MiroFish）。

### canonical MiroFish 后端解剖（backend/app/services/，已核对源码树）

| 模块 | 职责 | 三支柱归属 |
|---|---|---|
| `graph_builder.py` + `ontology_generator.py` | seed → 实体/关系抽取 → **GraphRAG 知识图** | 涌现的*素材* |
| `oasis_profile_generator.py` + `simulation_{runner,manager,ipc}.py` | **OASIS（CAMEL-AI）社会模拟**：persona agent 在模拟平台发帖/回复/转发，行为对彼此可见、按轮演化 | **agent-to-agent 交互 + 涌现** |
| `zep_entity_reader.py` + `zep_graph_memory_updater.py` + `zep_tools.py` | **Zep 时序知识图记忆**：每个 agent 的长期/演化记忆 | **记忆** |
| `report_agent.py` | 模拟后用富工具集与终态环境深度交互 → 预测报告 | 产出 |
| `simulation_config_generator.py` + `text_processor.py` | 自然语言预测需求 → 模拟配置；seed 预处理 | 编排 |

**结论**：canonical = **OASIS 社会模拟 + Zep 时序记忆 + GraphRAG seed + ReportAgent**。
三支柱（交互/记忆/涌现）正是其承重墙。

### 设计原则（沿用 MOSAIC 既有架构，避免推倒重来）

1. **Python sidecar 拥有 swarm 引擎**（numpy/LLM/记忆重逻辑），TS 只编排 + 展示 ——
   与 autoresearch/prism/janus/mirofish 一致。
2. **可插拔后端（buy-vs-build 用接口隔离）**：定义 `SwarmEngine` / `AgentMemory` /
   `SeedGraph` 三个抽象接口；先用**自建轻量实现**（零外部依赖、可在 sidecar 内跑、
   确定性可测），把 OASIS / Zep / GraphRAG 作为**可选适配器**后接，不绑架构。
3. **代表性 agent 压缩**：canonical 跑上千 agent；A 股训练用途不需要——用
   **N 个代表性 actor 类**（如 20–50 个：游资/北向/量化/散户/媒体/政策…各带人口
   权重），在「保真度 vs LLM 成本」间取平衡。每类可代表上万真实参与者。
4. **分层 LLM**：交互轮用便宜/本地模型（lemonade Qwen / haiku 级），只有 ReportAgent
   综合用 deep model。配合代表性压缩，把成本压到可接受。
5. **隔离不变**：swarm 训练结果仍落 `mirofish_runs`（§11.8），不碰实盘（隔离原则）。
6. **确定性可测**：每层都支持 `seed` + `--fake-llm`，CI 零成本 smoke。

### 分阶段子轨（每阶段独立可交付、可单独 PR）

- **7M.0 — 解析反身性叠加层（✅ 已交付，§11.8）**：行为原型需求反馈。作为
  **Tier-0**（无 LLM、最快、CI 默认），与高层并存供对照/兜底。

- **7M.1 — 交互引擎（agent-to-agent，自建轻量）✅ 已交付（2026-05-30，分支
  phase-7m1-swarm-interaction）**：`mosaic/mirofish/swarm.py` 定义 `SwarmEngine`
  接口（OASIS 适配器位）+ 自建 `LocalSwarmEngine`：
  - 一个**共享黑板**（shared environment）：每轮 actor 看到上一轮的聚合状态
    （last_return / 运行情绪 sentiment / 净仓位），产出需求，写回黑板。
  - actor 为**代表性类**（momentum/contrarian/herding/value/noise，各带人口
    share），决策依赖「自身参数 + 可见的他人聚合行为（黑板）」——真正的
    agent-to-agent（A 的动作进黑板、B 下一轮据此反应），而非 7M.0 的纯单资产
    价格反馈。
  - 价格由聚合净需求驱动（价格冲击 + clamp 保稳），形成 price↔board↔price 闭环。
  - 出口：N 类 × R 轮轨迹 + 涌现指标（herding_index / disagreement / sentiment），
    固定 seed 可重复，**纯 Python、无外部依赖、无 LLM**。输出 dict 与 montecarlo
    同形（`score_recommendation` / trainer 不变）+ `emergence` 块。
  - **开关（用户要求的 on/off）**：`config.mirofish.engine`（默认 `montecarlo`
    = swarm **关**）；`mirofish.generate_scenarios` 加 `engine` 参数覆盖；CLI
    `--engine montecarlo|swarm` + `--swarm` 简写（generate / train 都支持）。
    默认行为字节不变；swarm 纯 opt-in。

- **7M.2 — agent 记忆（`AgentMemory` 接口 + 自建 + Zep 适配器位）**：
  - `LocalAgentMemory`：每 actor 一个滚动「信念/仓位/近期被打脸」状态 +
    轻量检索（最近 K 条相关黑板事件）。让 actor 跨轮**有连续性**（记住自己昨天
    喊多被套、今天转空），这是「社会演化」的最小载体。
  - 预留 `ZepAgentMemory` 适配器（实现同接口，调 Zep cloud 时序 KG）——
    需 `ZEP_API_KEY`，免费额度够 smoke；不接也能跑（默认 Local）。
  - 出口：记忆开/关对比测试（有记忆 → 出现持仓惯性/反转行为），Zep 适配器
    behind 一个 `MOSAIC_MIROFISH_MEMORY=local|zep` 开关。

- **7M.3 — LLM persona actor（涌现升级）**：把 7M.1 的规则 actor 升级成
  **LLM 决策**（每个代表性类一个 persona prompt + 7M.2 记忆注入），用分层廉价模型。
  `--fake-llm` 退化到 7M.1 规则。出口：真 LLM persona 跑通一轮 + 成本实测；
  涌现指标（如叙事级联）比规则版更丰富。

- **7M.4 — GraphRAG-lite seed（`SeedGraph` 接口 + 自建）**：
  - seed = MOSAIC 现有数据（scorecard regime + 宏观 + 新闻 + macro tools）→
    轻量实体/关系抽取（先关键词/共现，不强求 LLM 抽取）→ 一张 actor 可查询的
    `LocalSeedGraph`（NetworkX 级，无外部 KG）。actor 决策时检索相关实体。
  - 预留接真 GraphRAG / Zep graph 的适配器位。出口：seed graph 喂进 7M.3 persona，
    决策引用具体实体（个股/政策/事件）。

- **7M.5 — ReportAgent（综合产出）**：模拟终态 → deep-model 综合「共识预测 +
  尾部风险 + 反身性极值 + 最高信念交易」，落 `mirofish_runs.detail`。等价
  canonical `report_agent.py`。出口：`mirofish swarm-report` 出结构化预测。

### 7M.1 A/B 验证（gate before 7M.2，2026-05-30）

> 用户要求：扩 7M.2+ 前先做 A/B。两个引擎都是**合成**的（无真实 ground truth），
> 所以不问「谁预测得准」，而问可证伪的结构问题：**swarm 是否产生了 i.i.d.
> 蒙特卡洛在数学上不可能产生的反身性结构？** 工具：`mosaic/mirofish/ab_compare.py`
> （`compare_engines`，纯 numpy，确定性；探针 000300.SH 日收益，100 seeds × 5 情景
> = 500 路径/引擎）。指标：lag-1 收益自相关（反身性指纹；MC i.i.d.→≈0）、波动
> 聚集（平方收益 lag-1 自相关）、超额峰度、累积收益离散度。

**实测数（默认调参 `_PRICE_IMPACT=0.04`）：**

| 指标 | montecarlo | swarm | 解读 |
|---|---|---|---|
| ret_autocorr_lag1 | −0.012 | **+0.013** | 方向对（swarm>MC），但**微弱** |
| vol_clustering | −0.019 | −0.065 | 都≈0，无聚集 |
| excess_kurtosis | −0.227 | −0.342 | 都薄尾 |
| cum_return_std | 0.190 | 0.024 | swarm **压缩**了离散度 |

**默认调参下结论：swarm ≈「带额外步骤的蒙特卡洛」** —— contrarian+value 阻尼盖过了
momentum+herding，反身信号几乎不可辨，离散度反而被压。

**但机制是有能力的（敏感性探针）：** 调高价格冲击系数，反身结构立刻显现 ——
impact=0.10→autocorr +0.07；impact=0.20→**autocorr +0.20、vol_clustering +0.06**
（MC 永远到不了）；momentum-heavy+impact=0.20→+0.93/+0.93（近确定性趋势）。即
默认 0.04 是为**稳定性**故意压保守的，恰好把「证明 swarm 价值的那个信号」也压没了。
测试 `test_mirofish_ab.py` 锁住：MC autocorr≈0；swarm>MC；且 autocorr 随 feedback
单调上升到非 MC 区间（可证伪 + 回归护栏）。

**Go/No-Go 裁决（7M.2 记忆）：CONDITIONAL —— 先调参，后扩展。**
- **不应**在当前默认调参上直接做 7M.2：此时 swarm 与 MC 结构差异微弱，记忆层加在
  一个行为上接近 i.i.d. 的引擎上，多半是「精致但无增益」。
- **✅ 7M.1b 已完成（2026-05-30）**：扫描 impact 0.08–0.20，选定**默认
  `_PRICE_IMPACT=0.16`** 为稳健非-MC 工作点 —— swarm lag-1 autocorr **+0.158**
  (MC −0.012，gap **+0.17**)、vol_clustering **转正 (+0.01)**（ARCH 信号，MC 到不了），
  同时有界（max 日内 ≈1.6%、cum_std≈0.05、无 0.4/0.88 退化）。`test_mirofish_ab.py`
  断言收紧：MC autocorr<0.05、swarm autocorr>0.10、gap>0.10、swarm vol_clustering>MC。
  默认-off（montecarlo）行为不受影响。
- **✅ path-aware 评分器已交付（2026-05-30，7M.2 前置）**：`score_recommendation`
  加 `path_aware`（默认 `False` = terminal，与旧行为**字节级一致**）；开启时对**方向
  调整后的净值曲线**用 `_path_metric` 评分（terminal 收益 − `_DRAWDOWN_PENALTY=0.5` ×
  最大回撤），swarm 产生的路径形状（lag-1 自相关、更深回撤/往返）**终于进入训练信号**。
  镜像 engine 开关：`config.mirofish.scorer`（默认 `terminal`）→ RPC `scorer` 参数 →
  TS wrapper + trainer 选项 + CLI `--scorer/--path-aware`。证据：同一 +10% 终值，平滑
  爬升 vs 先 −25% 往返，terminal 同分 0.825，path-aware 给往返 **0.372**；CLI 端到端
  同 seed/agent，default avg 0.959 vs `--swarm --path-aware` **0.727**。测试
  `test_mirofish_path_aware.py`（terminal 不变、回撤区分、swarm 上 path-aware≠terminal）
  + bridge scorer-routing（default-off / opt-in / bad-scorer 拒绝 / config 默认）。
- **⛔→🟡 7M.2 解锁条件已满足**：可被利用性前置（path-aware 目标）现已就位；剩下的是
  实测「记忆是否带来可测增益」——即一次真正的 A/B-lift（swarm+memory 训练 vs swarm
  训练）。在看到该增益之前仍不投入完整 7M.2/7M.3。

**建议顺序**：7M.1b 调参 ✅ → path-aware 评分器 ✅ → A/B-lift 验证 ✅（见下）。

### 7M.2 A/B-lift 验证（最终 gate，2026-05-30）

> 问题：swarm 的反身结构（lag-1 autocorr ≈ +0.16）+ path-aware 评分，是否变成
> 一个**可被利用、且排序不同**的训练信号？——这是 memory（7M.2）能加任何东西的前提。
> 工具：`mosaic/mirofish/ab_lift.py`（纯 numpy，确定性）。4 个确定性规则策略
> （trend_follower / mean_reverter / always_buy / always_hold，**只看路径前 25%** 决策，
> 无 look-ahead），跨 engine×scorer 4 个 regime 打分；外加一个干净的前瞻探针。

**实测数（n=150 seeds × 5 情景）：**

| 指标 | 结果 | 解读 |
|---|---|---|
| **前瞻信号**（早窗收益 vs 后窗收益相关，按情景**逐型**算再等权平均） | MC **+0.02** / swarm **+0.10**（n=150 点差 ≈0.075；各样本量 swarm 恒 > MC） | ✅ swarm 有**可被利用的前瞻信号**，MC（i.i.d.）≈0 |
| **区分度**（最优-最差策略均分差） | MC+term **0.59** / swarm+term **0.15** | ⚠️ swarm **压缩**了训练梯度 |
| **排序变化**（vs MC+terminal 的 Spearman ρ） | 仅 swarm+path_aware **ρ=0.8**（其余 1.0） | ✅ 只有 swarm+path_aware 重排了 agent 排序 |

**裁决：CONDITIONAL-GO，但要先解决「梯度压缩」——不是直接全量 7M.2。**
- ✅ **正面**：逐型前瞻相关 swarm 恒为正、MC 恒≈0 —— 这正是 memory 能学的东西
  （「早期趋势 → 后续延续」在 swarm 里真实存在、在 MC 里不存在）。且 swarm+path_aware
  是唯一改变 agent 排序的 regime（ρ=0.8）。**所以反身信号确实存在且可被利用、可改变训练
  排序** —— 7M.2 的存在性前提成立。
- ⚠️ **负面（必须正视）**：swarm 把好坏策略的**区分度从 0.59 压到 0.15**。当前
  `_PRICE_IMPACT=0.16` 在产生 autocorr 的同时也压低了终值离散度，使得「信号存在」却
  「梯度很平」——直接训练，agent 间分差太小，学习信号弱。**前瞻相关的幅度也只有中等
  (~0.1) 且随样本波动**，不是强信号。
- **结论**：full 7M.2 memory **值得做，但 ROI 中等且有前置**。投入顺序应是：
  1. **先做一个最小 memory 雏形 + 在这个 ab_lift harness 上量增益**（trend_follower 类
     策略带「跨轮记忆」是否把前瞻相关转成可测的分差提升），而不是先建完整 7M.2 基建；
  2. 若雏形能把区分度/前瞻利用拉起来，再做完整 `AgentMemory`（7M.2）与 LLM personas
     （7M.3）；
  3. 顺带评估把 `_PRICE_IMPACT` / `_DRAWDOWN_PENALTY` 作为可调旋钮，找「autocorr 高 +
     区分度不塌」的联合工作点（当前二者此消彼长）。
- **诚实结论**：信号是真的，但不强；7M.2 不是「显然高回报」，建议**雏形先行、增益驱动**，
  而非一次性投入完整 memory+persona 栈。

### 7M.2 memory 雏形验证（雏形先行的结果，2026-05-30）

> 按上面的「雏形先行」，做了最小 memory 原型并在同一 `ab_lift` harness 上量增益。
> 工具：`mosaic/mirofish/memory.py`（纯 numpy，确定性）。`AgentMemory` 抽象接口
> （`remember`/`recall`，即最终 §11.8.1 接口的第一版草图）+ `LocalAgentMemory`：按
> context（scenario_type）在线维护「早窗趋势 ↔ 后窗收益」的 **Pearson 相关**（用相关而非
> 协方差/收益，正好归一化掉 swarm 的压缩离散度，且直接对应 A/B-lift 那个区分引擎的量）。
> memory 策略：只在「样本够热 + |学到的相关| > 阈值」处下注（方向取相关符号），否则**弃权**；
> 对照 stateless（永远顺势满仓下注）。

**实测数（n=150 seeds × 5 情景，阈值 0.05）：**

| 指标 | montecarlo | swarm | 解读 |
|---|---|---|---|
| memory 在线学到的相关（均值） | **0.023** | **0.098** | ✅ memory **在线复现了 A/B-lift 的引擎区分**（自经验学到 swarm≫MC） |
| memory 活跃度（下注比例） | **0.47** | **0.95** | ✅ memory **有选择性**：swarm 几乎全下、MC 弃权过半；stateless 恒 1.0 |
| memory captured（去漂移后均值收益） | −0.0016 | +0.0029 | ⚠️ |
| stateless captured | +0.0014 | +0.0035 | ⚠️ swarm 下 memory **不如** stateless |

**裁决：NO-GO（暂缓完整 7M.2/7M.3）—— 雏形先行恰好挡住了一次低回报投入。**
- ✅ **机制全部成立**：memory 接口可用、在线学习正确、确实**自经验学到了 swarm 有信号 /
  MC 没有**（相关 0.098 vs 0.023），且据此**有选择性地行动**（活跃度 0.95 vs 0.47）。
  作为「memory 接口 + 在线学习」的工程草图，这一步是真的、可复用的。
- ❌ **但选择性换不来可测增益**：三个独立度量一致 —— 均值 captured（swarm 0.0029 vs
  stateless 0.0035，memory 略**差**，因为弃权 warmup 期反而少赚）、风险调整 info ratio
  （memory −0.035 / +0.076 vs stateless +0.020 / +0.089）、以及**真实 `score_recommendation`
  下的 conviction sizing**（memory 反而更低，MC 0.24 vs 0.77 / swarm 0.536 vs 0.540）。
  三个度量均由 `measure_memory_lift` 直接产出（可复现）。
- **根因（已诊断，非调参问题）**：(1) 早窗趋势主要捕捉的是**情景漂移**（bull/bear），这一块
  stateless 启发式在两个引擎里都已吃到，而它与 memory 真正隔离出的那点反身信号**大体正交**；
  (2) swarm 的反身信号**绝对值太小**（相关 ~0.10），相对漂移是二阶量；(3) 在这些合成 scorer 下，
  **「在无信号区过度下注」几乎不被惩罚**（MC 下注均值≈0 而非亏），所以 stateless 已接近最优，
  选择性省下的只是 warmup 收益。memory 的价值要显现，需要一个**强惩罚错误高信念**的目标，
  而当前 scorer 不是。
- **结论**：在当前引擎调参 + 合成评分目标下，**完整 `AgentMemory`（7M.2）与 LLM personas
  （7M.3）不值得现在投入** —— 雏形已经证明「即便机制全对，增量也接近零」。**重启 7M.2 的
  前置条件**应是先满足以下之一，再重测本 harness：
  1. 提高 swarm 反身信号强度（`_PRICE_IMPACT` 上探，但需解决「区分度塌缩」，见上）；
  2. 引入**强惩罚错误高信念 / 路径风险**的训练目标（让选择性真正值钱）；
  3. 接入真实/历史数据校验，确认反身信号在真市场也存在且可被记忆利用。
- **诚实总账**：7M（MiroFish 交互栈）到此是一条**设计正确、但经增益验证证伪了「现在就全量
  投入」假设**的线。已交付且有价值的是：可插拔 `SwarmEngine`/`AgentMemory` 接口、`LocalSwarmEngine`、
  path-aware scorer、两套可复用的 A/B harness。建议把 7M.2/7M.3 标为 **deferred（增益驱动重启）**，
  把精力转回主干（实盘/回测/autoresearch 等已落地、对 alpha 有直接贡献的环节）。

#### 细粒度复查：fade 信号是否存在（2026-05-30 追加）

> NO-GO 的全部重量压在「swarm 下 edge 一律为正 ⇒ memory 退化成 stateless 顺势的子集」。
> 能最低成本翻盘的是重启条件 #1（context 异质性 / fade 信号）。直接在更细粒度上实测
> （scenario_type × 早窗趋势幅度 × 波动率桶，300 seeds）：

| 引擎 | 细分 context 数 | edge<−0.03（fade）的数量 | 相关范围 |
|---|---|---|---|
| swarm | 8 | **0** | +0.185 ~ +0.430（全正） |
| montecarlo | 20 | 9 | −0.169 ~ +0.293（i.i.d. 采样噪声，样本外不复现） |

**结论：swarm 下没有任何 fade context，design ceiling 巩固，NO-GO 不变。** 细分反而把
swarm 信号*集中*了（相关从粗粒度 ~0.10 升到 +0.43）——但因一律为正，只是**加强了顺势 edge**，
并未制造 memory 需要的异质性。重启条件 #1 经实测仍不满足。

#### 7M 已交付资产 → 未来扩展映射（deferred，可重启）

把整条 7M 定位为「**机制已建成、增益验证暂未通过、可随条件成熟重启**」的资产。复用清单：

| 已交付资产 | 文件 | 复用 / 未来扩展点 |
|---|---|---|
| `SwarmEngine` 抽象 + `LocalSwarmEngine` | `mosaic/mirofish/swarm.py` | 接口稳定；7M.3 接 OASIS/CAMEL-AI 适配器实现同接口；`_PRICE_IMPACT` 可调旋钮（重启条件 #1） |
| `AgentMemory` 抽象 + `LocalAgentMemory` | `mosaic/mirofish/memory.py` | `remember`/`recall` 接口即 7M.2 接口首版；Zep/GraphRAG 适配器实现同接口；当前为「context→在线相关」雏形 |
| path-aware scorer | `mosaic/mirofish/scenarios.py` | 已并入主干（opt-in）；`_DRAWDOWN_PENALTY` 可调；重启条件 #2（强惩罚错误高信念）可在此扩展 |
| A/B 结构 harness | `mosaic/mirofish/ab_compare.py` | 量「swarm 是否非 MC」的回归护栏 + 引擎重调参后复测工具 |
| A/B-lift harness | `mosaic/mirofish/ab_lift.py` | 量「信号是否可被利用 / 排序是否改变」；任何引擎/目标变更后的增益闸门 |
| memory-lift harness | `mosaic/mirofish/memory.py::measure_memory_lift` | 量「memory 是否跑赢 stateless」（capture/info-ratio/真 scorer 三度量）；重启 7M.2 的验收工具 |

**三个重启触发条件**（满足任一 → 在对应 harness 上重测，通过才投入完整 7M.2/7M.3）：
1. **更强反身性**：上探 `_PRICE_IMPACT` 且解决「区分度塌缩」（`ab_lift` 验收）；
2. **强惩罚错误高信念的训练目标**：在 path-aware scorer 上加路径风险/错误高信念惩罚（`measure_memory_lift` 验收）；
3. **真实/历史数据校验**：确认反身信号在真市场存在且可被记忆利用（接 Phase 3.5 qlib 数据底座）。

> 当前判断：**条件 #1 经细粒度复查仍不满足；#2/#3 未做。** 在任一条件满足前，7M.2/7M.3 保持 deferred。

### ATLAS MiroFish 实现对照（基于实际源码，2026-05-31）

> 用户要求研究 ATLAS 的 MiroFish 实现、与我们的差异和 gap。读了 `chrisworsey55/atlas-gic`
> 的 `src/mirofish/` 全部 5 个文件（bridge / context / futures_generator / seed_generator /
> trainer），结论基于**代码**而非 README 的营销描述。

**关键事实:ATLAS 公开版的 "swarm" 不是真 swarm。**
- README 宣称「thousands of AI agents interact」，但 `mirofish_bridge.py` 的默认
  `LightweightSimulator` **就是一次 Claude API 调用**——让单个 LLM 在一个 ~8192-token
  prompt 里 role-play 扮演所有角色（对冲基金/央行/散户/分析师），"模拟" 10 轮，返回 JSON。
  注释原文:`LIGHTWEIGHT MODE (default): Uses Claude to simulate multi-agent interactions
  - No external dependencies`。
- 所谓 FULL MIROFISH MODE 需 `ZEP_API_KEY` + 外部 `666ghj/MiroFish` 引擎，而**那个引擎不在
  ATLAS 仓里**(README 明列 simulation outputs / 真引擎 NOT included)。即 "thousands of
  agents / OASIS+Zep+GraphRAG" 在公开代码里**并不存在**。
- `mirofish_futures_generator.py` = **Cholesky 相关蒙特卡洛 + 情景漂移 + 硬编码事件注入**
  ——这正是我们 Phase 7 移植的源,逐函数对应。

**逐项对照:**

| 维度 | ATLAS 公开源 | MOSAIC | 谁更接近"真" |
|---|---|---|---|
| 情景路径 / 跨资产相关 | Cholesky MC + SVD 兜底 | 同 + `_nearest_pd` 修正 | MOSAIC 略优(更稳) |
| 事件注入 | 硬编码 CPI/FOMC/NVDA + tail 模板 | 一致 | 平 |
| "swarm" 多 agent | **1 次 LLM 扮演所有角色**(prompt) | `LocalSwarmEngine` 纯 numpy N 类 actor 共享黑板,真 agent-to-agent(lag-1 autocorr +0.16) | **MOSAIC 更真** |
| 反身性 | LLM prompt 里写 5 条规则,靠 LLM 自觉 | per-asset 反馈核 + 黑板反馈环,代码里真算 | MOSAIC 更可验证 |
| 预测打分 | 5 天后字符串匹配 rise/fall 方向 | `forward_return_5d` + alpha 数值化 | MOSAIC 更严谨 |
| **预测→agent prompt 注入** | **`get_agent_context()` 把模拟预测/tail-risk/最高信念交易格式化塞进 25 agent prompt** | **未接**(mirofish 输出仅离线打分) | **ATLAS 有,我们没有 ← 唯一实质 gap** |
| LLM 叙事情景层 | swarm 输出带叙事(具体 CPI 读数/reflexive loop 描述) | 纯 numpy 数值,无叙事 | ATLAS 有 |

**诚实结论:**
1. 情景引擎 / 相关性 / 打分:MOSAIC ≈ 或优于 ATLAS 公开版。
2. swarm 机制:**MOSAIC 更真**(numpy 多 actor 耦合 vs 一次 LLM prompt)。
3. "thousands of agents / 真 OASIS+Zep 引擎":**ATLAS 公开版也没有**(营销 + 缺失外部引擎),
   我们标 7M.3 deferred 与之同水平。
4. **唯一实质 gap = `get_agent_context` 那条「把 MiroFish 预测回灌进日循环 agent prompt」的通路**
   ——这是 ATLAS 让 MiroFish 真正影响交易决策的唯一接法,我们的 mirofish 输出目前只用于离线
   打分,不回灌当日 agent。**这是对齐 ATLAS 真实做法、范围清晰、不需要"thousands agents"
   神话的最高价值可补项**,记为 deferred 候选(下方 wrap-up 列出)。

### get_agent_context 注入通路 + 真引擎 666ghj/MiroFish 深度研究(2026-05-31）

> 读了 ATLAS `mirofish_context.py` + `mirofish_trainer.py` 全文,以及真引擎
> `666ghj/MiroFish` 仓库,把"预测回灌"和"真引擎"两件讲清。

**注入通路的真相 —— 其实有两条,且都没真闭环:**
- **路径 A `mirofish_context.py::get_mirofish_context()`**:读 `mirofish_predictions.json`
  最近一条 → 格式化成 markdown 段(Consensus Predictions / Tail Risks / Highest Conviction
  Trade / Reflexive Extremes + 免责"These are simulations, not certainties")。docstring 说
  用法是 `build_analysis_prompt() 里 prompt_parts.append(...)` —— 但 **`build_analysis_prompt`
  本身闭源(eod_cycle 不在公开仓)**,即注入器公开、调用点不公开。
- **路径 B `mirofish_trainer.py::ForwardTrainer`**:情景→`present_scenario_to_agent`(自己
  拼极简 prompt,haiku)→`evaluate_recommendation`(+20%→1.0 那套,就是我们移植的)→更新
  `agent_weights.json`。**它不调用 A**。所以"Druckenmiller 崩盘 1.0/暴涨 0.22"来自 B 不是 A。
- 两条都是软影响:A 只是给 agent 多一段参考文本;B 调的是独立 `agent_weights.json`,README
  没说接回真实下单。**对照我们:路径 B 我们有且更完整(trainer.ts + mirofish_runs + path scorer);
  路径 A(注入)我们没有,但我们的 `build_analysis_prompt` 等价物是开源的 → 补这条对我们端到端可见、可做。**

**真引擎 `666ghj/MiroFish` 的真相 —— 是全栈服务,不是库:**
- Vue 前端(:3000)+ Python 后端 API(:5001)+ Docker compose,**服务式**。内核 = `OASIS`
  (CAMEL-AI,真·上千 agent 社会模拟)——这才是 "thousands of agents" 的出处。
- 硬依赖:`LLM_API_KEY`(每轮烧 LLM,README 警告 <40 轮起步)+ **`ZEP_API_KEY`**(Zep Cloud
  时序记忆图,联网+配额)+ GraphRAG。Python 3.11–3.12 / Node 18+ / uv。AGPL-3.0。
- **不能 import,只能服务化接**:部署外部服务 + 跨进程/HTTP 调用 + 承担 LLM/Zep 成本与网络依赖。
  ATLAS 公开版也只留 `ZEP_API_KEY` 的 "FULL MODE" 占位、未真接。这正是 §11.8.1 一开始就把
  OASIS/Zep 定为「可选适配器、默认自建零依赖」的原因。

**三步落地路线(分步走):**
- **Step 1（本次)**:情景上下文落库可读 —— `mirofish_context` 表 + `mirofish.save_context`/
  `get_context` RPC,从生成的 scenario set **纯派生** regime/csi300/tail/最高信念摘要。
  不碰 prompt、不碰引擎,是 A 的前提。
- **Step 2**:`get_agent_context()` 格式化器 + 注入日循环 prompt(opt-in/默认关/带免责),
  对齐 ATLAS 路径 A,但注入点开源可见。
- **Step 3（大件,需用户拍板成本)**:`SwarmEngine` 接口下加 `OasisMiroFishEngine` adapter,
  HTTP 调用**已部署的** `666ghj/MiroFish` 服务(:5001),把其预测报告映射成 montecarlo-shaped
  scenario dict。需:Docker 部署 + LLM/Zep key + 接受成本。**默认仍关**。
  - **✅ adapter 已交付并按实测真引擎重写(2026-05-31)**:把真引擎 clone 到
    `~/Project/MiroFish` 实测后发现——**它根本没有 `/scenarios` 这种同步端点**
    (实测 `POST /scenarios` → 404;`GET /health` → ok)。真实 API 是 Flask 多步异步、
    `/api/*` 前缀、产出**自由文本舆情/事件预测报告**(markdown,非价格路径):
    `POST /api/graph/ontology/generate`(multipart 上传种子+需求)→ project_id;
    `POST /api/graph/build`(轮询 `/api/graph/task/<id>`)；`POST /api/simulation/create`
    → simulation_id；`POST /api/simulation/prepare`(轮询 `/prepare/status`)；
    `POST /api/report/generate`(轮询 `/generate/status`)→ report_id；
    `GET /api/report/<id>` → `{markdown_content, outline}`。
    `mosaic/mirofish/oasis.py::OasisMiroFishEngine`(SwarmEngine 第三实现,纯 stdlib
    urllib,deps-light)现**走这条真实多步链**(轮询 + 超时 + 上限),再把报告的方向性
    语义(利好/利空词频 → sentiment ∈[-1,1])**有损映射**成 montecarlo-shaped scenario
    dict(报告无 OHLCV,只能由 regime/drift 合成最小 price path,如实标注近似)。盖
    `engine='oasis'`;`engine='oasis'`(config/RPC)路由到它;缺 URL/超时/轮询上限/任一步
    非2xx 或 `{success:false}` → `MiroFishUnavailable`(handler 映射清晰 RpcError,**不静默
    降级**)。
  - **⛔ 真跑前置(仍需用户)**:本环境实测了「服务能起 + API 形态 + 多步调用序列 + 轮询 +
    报告→scenario 映射」(fake-HTTP),但**未做真实端到端模拟**——那一步需 `LLM_API_KEY` +
    `ZEP_API_KEY`(联网+花钱+配额),不擅自用。真跑需:① Docker 部署 `666ghj/MiroFish`
    (实测依赖 camel-oasis/camel-ai/zep-cloud 可装、后端能起);② 配 LLM/Zep key;
    ③ `MOSAIC_MIROFISH_URL=http://<host>:5001` + 接受按轮成本。**语义鸿沟须知**:MiroFish
    预测的是叙事/舆情,不是 A 股价格,故 oasis 情景是「报告方向 → 价格 drift」的近似,适合
    定性 regime 参考,不宜当精确价格路径。

#### 记忆分层澄清 + Zep 本地化(2026-05-31，防误解）

> 用户问:「Zep 是 MiroFish 的记忆系统,我们还需要自己的记忆实现吗?」「Zep 社区版能本地接吗?」
> 基于 clone 实测 + Zep 官方公告核对:

- **两层"记忆"不同,别混**:
  - **Zep** = MiroFish **模拟世界内**那批 agent 的长期/演化记忆(实测:`graph_builder.py` /
    `zep_entity_reader.py` / `zep_graph_memory_updater.py` / `zep_tools.py` 用 `zep_cloud` SDK)。
    它在真引擎服务内(:5001),**我们经 HTTP 黑盒调用,对其完全透明,既不复刻也不需要**。
  - **我们的 `AgentMemory`/`LocalAgentMemory`(7M.2)** = **我们交易 agent** 的跨轮记忆,
    经 A/B-lift 增益验证已 **NO-GO/deferred**(雏形证明当前合成目标下增量≈零)。
  - **结论:我们不需要新增任何记忆实现。** 接 oasis 时 simulated-agent 记忆由 Zep 全包(重复造轮子);
    我们自己的交易-agent 记忆已 deferred。`AgentMemory` 接口槽留作将来可选后端(同 SwarmEngine→Oasis 套路)。
- **Zep 本地化(社区版)可行性**:
  - MiroFish 用 `zep_cloud` SDK **v3.13(新一代 graph memory API)**。`Zep()` 虽支持 `base_url`,
    但 **Zep 官方 2025-04-02 已停止维护 Community Edition**(自托管旧 memory 服务),且 CE 与 v3.13
    的 graph API **不兼容** → **配 base_url 直连本地 CE 不行**(死路)。
  - 真正本地化路径 = **Graphiti**(Zep 开源主力,Apache-2.0,驱动其云的时序知识图,可自托管+本地 LLM)
    —— 但 Graphiti 是**库**不是 `zep_cloud` 的 drop-in 服务端,需**改 MiroFish fork** 的那 4 个
    service 文件 + 起 Neo4j/Graphiti 栈。**这属于真引擎部署侧改造,MOSAIC 的 oasis adapter 零改动**
    (它只认 HTTP `/api/*`,后端用 Zep Cloud 还是本地 Graphiti 对它无差别)。
  - **对 MOSAIC 的影响:无。** 本地化只降低你部署真引擎的门槛/成本,不阻塞、不改我们代码。

### buy-vs-build 决策

| 能力 | 自建（先做） | 接外部（后选） | 理由 |
|---|---|---|---|
| 社会模拟 | `LocalSwarmEngine`（黑板+撮合） | OASIS / CAMEL-AI | 自建零依赖、确定性、够 A 股代表性 actor 规模；OASIS 是上千通用社媒 agent，重且偏舆情 |
| 记忆 | `LocalAgentMemory`（滚动状态+检索） | Zep cloud 时序 KG | 自建可离线/可测；Zep 强但要 key + 网络 + 配额 |
| seed 图 | `LocalSeedGraph`（NetworkX 共现） | 真 GraphRAG | 自建够 actor 检索；真 GraphRAG 是独立大工程 |
| persona 决策 | 规则（7M.1）→ 分层 LLM（7M.3） | — | 规则先跑通机制，LLM 加保真度 |

**核心理念**：用三个接口（`SwarmEngine`/`AgentMemory`/`SeedGraph`）把「机制」与
「后端选型」解耦。先交付全自建、零依赖、确定性、可测的最小真 swarm（7M.1–7M.2 就已
是*真正的* agent-to-agent + 记忆 + 涌现，不再是解析近似）；OASIS/Zep/GraphRAG 作为
同接口的可选适配器，谁有 key/预算谁接，架构不变。

### 成本模型（为什么可负担）

- 代表性压缩（N=20–50 类而非上千）× 分层 LLM（交互轮用 lemonade 本地 / haiku）×
  轮数上限（R≤20，canonical README 也建议 <40 轮起步）。
- 7M.1–7M.2 **零 LLM 成本**（规则 + 本地记忆）；7M.3 起才花钱，且只代表性类。
- 估算：30 actor × 15 轮 × haiku ≈ 450 次廉价调用/模拟 ≈ 远低于一次 PRISM cohort 训练。
- CI/默认 `--fake-llm` 全程零成本。

### 与现有 Phase 7 的关系 + 排期

- 7M.0 已在 §11.8 交付（PR #12）。7M.1–7M.5 建议**独立 Phase 7M 系列 PR**，不阻塞
  Phase 8/9。优先级：**7M.1（交互）+ 7M.2（记忆）** 最高 —— 这两步就把「解析近似」
  升级成「真 agent-to-agent + 记忆 + 涌现」，是用户关切的核心；7M.3–7M.5 是保真度
  与产出的递进增强。
- 估算：7M.1 ≈ 4–5 turns、7M.2 ≈ 3、7M.3 ≈ 3、7M.4 ≈ 3、7M.5 ≈ 2（总 ~15–16，
  与一个完整 Phase 相当；故独立成 Phase 7M 而非塞进 Phase 7）。

### Phase 7M 出口标准（全系列做完）

- `SwarmEngine`/`AgentMemory`/`SeedGraph` 三接口 + 全自建实现落地，N 代表性 actor
  在共享环境里**互相观察、带记忆、按轮演化**，价格由聚合行为内生（真反身性闭环）。
- OASIS/Zep/GraphRAG 各有一个 behind-接口的可选适配器位（接不接都能跑）。
- 分层 LLM + 代表性压缩使单次模拟成本可控；`--fake-llm`/`seed` 全程可重复。
- ReportAgent 出结构化预测，落 `mirofish_runs`（仍与实盘隔离）。
- §3 表加 Phase 7M 行；§11.8.1 各 7M.x 勾选。

---

## 12. 风险登记

| 风险 | 影响 | 缓解 |
|---|---|---|
| Tushare API 配额 / 限速 | 训练阶段大批量调用可能触发限速 | 加缓存层（已在 ETFAgents 复用 cache_manager） + 升级订阅档 |
| LLM 成本失控 | autoresearch + PRISM 全跑可能失控 | 默认开发期用本地 Lemonade Qwen；生产前估算每个 phase 的预算并设上限 |
| Prompt mutation 越改越差 | autoresearch 错误生成的修改可能让 agent 越改越差 | 5 天 keep 阈值用 Δ Sharpe > 0.1；每月修改次数上限；保留 git history 可回溯 |
| A 股 cohort 时段映射错误 | A 股的"crisis"和 US 不同 | Phase 5 启动前先论证每个 cohort 的 A 股代表时段（如 2008 全球危机 / 2018 资管新规 / 2020 Q1 疫情） |
| US Superinvestor 跨市场失效 | US 投资人哲学应用到 A 股可能不准 | Phase 2 末做 superinvestor 端到端验证；如果质量明显差，回头补 4 位 CN 投资人组成 8 哲学（fallback 到 Q4=c） |
| MiroFish 反身性闭环过强 | 模拟未来产生的训练数据可能让 agent 过拟合极端情景 | 与真实 forward returns 校验（Phase 7 子步 7.5） |
| LangGraph.js v1 在 25 节点图上的稳定性 | 节点数量翻倍，内存/检查点行为未知 | Phase 2 子步 2.6 做 stress test：mock LLM × 25 节点 × 10 次 daily cycle |
| Anthropic API 限速 | 25 节点并行可能触发限速 | 节点级 retry + 限流；layer 内并行控制（如 layer 1 一次 5 个并行） |
| Cohort 间 prompt 版本管理混乱 | 5 cohorts × 25 agents × 多次修改 = 125+ branch | 严格 branch 命名 `cohort/{name}/auto/{agent}/{date}` + SQLite 索引 |
| MiroFish 数据源切换 | seed_generator 5 个数据采集函数全替换为 Tushare/akshare | Phase 7 子步 7.2 单独处理，与 ATLAS 公开版完全隔离测试 |

---

## 13. 数据/LLM 预算估算

### 13.1 Tushare 订阅
- **免费档**：基础日线 + 部分财务，限速 200 次/分钟。MVP 阶段可用
- **2,000 积分档**（约 ¥200/年）：覆盖大部分需求 + 北向资金 + 龙虎榜
- **5,000 积分档**（约 ¥500/年）：覆盖期权 / 期货 / 全部高级数据
- **建议**：Phase 0–4 用免费档；Phase 5 PRISM 训练前升级到 2,000 档

### 13.2 FRED
- 完全免费，限速 120 次/分钟，几乎不用担心

### 13.3 LLM API 估算（Anthropic Claude Sonnet）
- 单 daily cycle：25 agents × 平均 8K tokens（含工具结果）≈ 200K tokens
- Sonnet 输入 $3/MTok，输出 $15/MTok，平均 **$0.005/cycle agent ≈ $0.125/daily cycle**
- **Phase 2 MVP** 单天：$0.125
- **Phase 4 autoresearch**：每天额外 1–3 次 prompt mutation = +$0.05/天
- **Phase 5 PRISM**：7 cohorts × 200 trading days × $0.18/day ≈ **$252**
- **Phase 7 MiroFish 训练**：~5,000 模拟 + 训练调用 ≈ **$50**
- **Phase 8 18 个月回测**：378 天 × $0.18 ≈ **$70**
- **总 Phase 1–9 预算**：约 **$370–570 美元** 的 Anthropic 调用，分阶段花费
- **降本方案**：开发期用本地 Lemonade Qwen 跑全流程，仅生产 PRISM 训练用 Anthropic
- **DeepSeek**：约 1/10 价格，质量略差但中文上下文好。Phase 5 训练首选

### 13.4 存储
- SQLite：scorecard / autoresearch_log / prompt_versions ≈ 几百 MB
- Git repo：7 cohorts × 25 agents × 多次修改 ≈ 几十 MB
- MiroFish 场景缓存：~100 MB
- Tushare 缓存：~1 GB（18 个月行情 + 财务）

---

## 14. 待决议题（Phase 进展中收敛）

1. **A 股 cohort 时段精细化**：每个 cohort 起止日期已初步定（§9），但
   `crisis_covid` 合并 2018 Q4 + 2020 Q1 是否合理？或拆成两段？Phase 5 启
   动前必须确认。

2. **PRISM 启动顺序**：建议先跑 1 cohort（`euphoria_2021`）打通
   Phase 2-4 全套，再展开 PRISM。Phase 4 完成后回头确认。

3. **autoresearch 触发频率**：Phase 4 单 cohort 默认每天 1 次；
   Phase 5 多 cohort 时改为每个 cohort 每天 1 次（避免 7 cohort × 多
   mutation 风暴）。

4. **prompt 多样性约束**：同一 agent 24 小时内最多 1 次修改，3 天内不能撤销
   keep 的修改（已同意）；月度修改次数上限设多少？建议每 cohort × 25 agent
   总和不超过 100 次/月。

5. **TS UI 中文化程度**：CLI 输出中文报告（默认），CLI help/选项保持英文
   （开发者友好）。**TUI 标签可双语并列**（中文为主，括号标英文）。

6. **是否需要 MiroFish A 股事件库**？ATLAS 公开 MiroFish 用 US 事件
   （Fed 决议 / 财报季 / 地缘冲突）。A 股需要本地化（业绩季 / 解禁 / 政策窗
   口 / 财报集中披露 / 春节假期）。Phase 7 启动前定。

7. **Phase 1 review follow-ups**（PR #1 review 留下的 6 个非阻塞项，集中在
   Phase 2 落 agent 之前清掉）：**✅ 全部收敛（2026-05-30）**。
   - **R1 ✅**：`tool-call.ts` 的 `JSON.parse(argsJson)` 已包 try/catch + 非对象
     校验，畸形 JSON 返回友好 CLI 错误（不再打 stack）。
   - **R2 ✅**：`types.ts` docstring 已改正 —— bridge 现注册 ~50 个 RPC（11 个
     namespace），`BridgeApi` 已 typed 包除 Phase 8 paper *写* 接口 + `cache.details`
     外的全部；docstring 据实描述覆盖范围。
   - **R3 ✅**：`factory.ts` Lemonade base URL 已修正为 `8020/api/v0`（实弹 NPU
     端口），并暴露 `LEMONADE_BASE_URL` env override + 注释引导看
     `lemonade-server-dev` 启动日志。
   - **代码细项 (1) ✅**：`tools.ts` 改用 `as Parameters<typeof field.default>[0]`
     收敛 cast（不再 `as never`）。
   - **代码细项 (3) ✅**：RpcError / BridgeStartupError / BridgeTransportError
     均已传 ES2022 `{ cause }` 链。
   - **代码细项 (5) ✅**：`MosaicConfig` 已从 `Record<string, unknown>` 拉成 typed
     interface（含 llm / cohort / autoresearch 字段 + 开放索引签名兜底未稳定字段）。

   不阻塞 PR #1 merge。Phase 1 PR #1 提交时已修了真 correctness bug
   （tool-loop forced-final 用 unbound LLM），R1/R3/细项 1/3/5 在 Phase 2–4 落
   agent 时陆续修掉，R2 docstring 在 2026-05-30 收口。

8. **Layer-1 macro tools 缺口**（plan §5.1 列出的工具 vs Phase 0 macro_data 实际
   实现的工具差距，影响 2C 的 agent prompt）：

   | Plan §5.1 期望 | Phase 0 实际有 | 2C.2 替代 / 处理 |
   |---|---|---|
   | `get_property_data` (china) | ❌ | 用 `get_north_capital_flow` 替代（仍未补）|
   | `get_us_china_relations` (geopolitical) | ✅ 已补（清华中美关系指数 CSV）| wired into geopolitical |
   | `get_usdcny` (dollar) | ✅ 已补（fx_daily USDCNH.FXCM）| wired into dollar REQUIRED_TOOLS |
   | `get_commodity_prices` (commodities) | ✅ 已补（fut_daily 主连篮子）| wired into commodities |
   | `get_ivx` (volatility) | ✅ 已补（yfinance CSI300 realized-vol proxy）| wired into volatility |
   | `get_etf_indicator(510050.SH)` (volatility) | ✅ 已补（fund_daily）| wired into volatility |
   | `get_etf_price_data(EEM)` (emerging_markets) | ✅ 已补（fund_daily ETF OHLCV）| wired into emerging_markets |
   | `get_etf_price_data(2800.HK)` (emerging_markets) | ✅ 同上 | 同上（用 510300.SH 等 A 股 ETF 代理）|
   | `get_news` (news_sentiment) | ✅ opencli（已包装）| wired into news_sentiment REQUIRED_TOOLS |
   | `get_caixin_sentiment` (news_sentiment) | ✅ 已补（opencli 财新 query）| wired into news_sentiment |
   | `get_fund_flow` (institutional_flow) | ✅ 已补（fund_share）| wired into institutional_flow |

   **✅ 已完成（phase-4-macro-tools，2026-05-29）**：补齐 6 个核心缺口工具
   `get_usdcny` / `get_commodity_prices` / `get_ivx` / `get_etf_indicator` /
   `get_fund_flow` / `get_etf_price_data`（数据源用户指定：tushare fx_daily /
   fut_daily / yfinance / fund_daily / fund_share / fund_daily），并把
   `get_news`(opencli) 接入 news_sentiment。**Phase 6 补全（phase-6-macro-tools，
   2026-05-30）**：`get_caixin_sentiment`（opencli 财新 query → news_sentiment）+
   `get_us_china_relations`（清华中美关系指数 CSV，`MOSAIC_SINO_US_CSV` 可覆盖 →
   geopolitical）。**16 个 macro 工具全部注册 + 路由 + 测试覆盖。仅剩
   `get_property_data` (china)** —— 无单一现成数据源（房地产综合指标），暂保留
   `get_north_capital_flow` 替代，后续按需补。

9. **跨 PR 累积的 review 待办（Phase 4 启动前清理 / 或 Phase 5 集中 hotfix）**：

   合并 PR #2 / #3 / #4 review 留下的非阻塞项。每条标注来源 PR + 严重度。

   **代码质量 (TS)**:
   - **R-T1 (从 PR #2 #2、#5)**：`let graph: any` 出现在 4 个 layer 子图
     builder（layer1/2/3/4）。LangGraph fluent type chain 在 `.addNode()`
     / `.addEdge()` 上每步窄化类型，循环里累 edge 时类型推断断裂，所以加
     了 `any` + biome-ignore。**真正解法**：写一个 typed fluent helper
     `chainEdges(graph, [...edges])` 屏蔽中间类型；或升级 LangGraph 后
     重新审视。**不阻塞功能**。

   - **R-T2 (从 PR #2 #4 + PR #3 #6)**：CLI `pad()` 不处理 CJK 宽度。
     中文字符在终端占 2 列，agent 名 / dissent_notes / rationale 含中文
     时表格列错位。引入 `string-width` package 或写一个简易 CJK 宽度
     探测函数。**纯展示问题**。

   - **R-T3 (从 PR #2 #5)**：`invokeSubgraph` wrapper 直接 `result.llm_calls.slice(prevLen)`，
     若 subgraph 异常返回 undefined 会 NPE。reducer guarantee 当前不允许
     这个状态，但加一个 `(result.llm_calls ?? []).slice(...)` 防御没成
     本。

   - **R-T4 (从 PR #3 #7)**：bridge handler 的 `_store()` factory 每个 RPC
     调用都 new 一个 ScorecardStore（因此 new 一个 SQLite connection）。
     当前 throughput 低，无影响；Phase 4 autoresearch 会高频调用，建议
     引入 module-level singleton。

   - **R-T5 (从 PR #3 #8)**：`update_scoring(row_id, ...)` 当 row_id 不
     存在时静默 no-op。当前没 row 删除路径所以无影响；Phase 4 autoresearch
     可能加 purge old recommendations 路径，到时候补 `if cur.rowcount == 0:
     log.warning(...)`。

   - **R-T6 (从 PR #4 #6)**：error cause chaining 不一致。Python 大部分
     用 `raise X from exc` ✓；TS 没用 `new Error(msg, { cause: err })`。
     bridge errors.ts 在 phase-2 prep 已加，但 daily-cycle / backtest
     CLI 的 error wrapper 没加。系统性补一遍。

   **代码质量 (Python)**:
   - **R-P1 (从 PR #4 #7)**：`mosaic/dataflows/qlib_ingest.py` 的
     `validate_after_ingest` 直接 `struct.unpack` 读 qlib binary。功能
     正确，但耦合 qlib 内部格式。如果 qlib 升级改格式，这里悄悄坏。
     可改用 `qlib.data.cache.H` 或 qlib 的 DataApi。当前接受。

   **架构 / 设计观察（不一定是 fix）**:
   - **R-A1 (从 PR #2 #6)**：daily_cycle 没有 `replay_triggered` state
     channel 记录 CRO veto 是否触发过 replay。Phase 3 scorecard 想区分
     "first-pass cycle" vs "replayed cycle" 时会需要。等 Phase 4
     autoresearch 真正需要时再加。

   - **R-A2 (从 PR #3 #4 + 跨多 PR)**：CIO 的 conviction proxy = target_weight
     在 backtest_actions 表里。这意味着 Phase 4 比较 per-agent Sharpe 时，
     CIO 的"conviction"不是真 conviction（是仓位权重）。要不要：
     (a) 把 CIO 的 conviction 列写 NULL（明确"不可比"）；
     (b) 关联回 L3 superinvestor 的真 conviction。
     Phase 4 启动前定。

   - **R-A3 (从 PR #4 #10)**：backtest-fill 失败时只在 stderr 报错、
     run NOT marked completed。没有 SQLite-持久化的 failed_days 记录，
     操作员重跑要看终端 log。如果 Phase 4 autoresearch 自动化重跑则
     需要查询接口。Phase 4 启动前再决定。

   - **R-A4 (从 PR #4 #6)**：`ingest_full` timeout 默认 120 秒（每个 ticker
     查询）。全 A 股 ~5500 ticker × 35 年理论上单次 ingest 30-90 分钟，
     单 ticker 120s 应该足够；但如果 Tushare 突然慢，120s 可能截断。
     文档需要标"per-ticker 不是全 ingest"。

   **当前状态**：所有 R-T* / R-P* / R-A* 不阻塞 Phase 4 启动；每条都
   配 fix path 描述。**进 Phase 5 PRISM 前最好集中清掉 R-T2/T4/T5 + R-A2**
   （Phase 5 多 cohort 高吞吐会放大这些问题）。

   **✅ 收口状态（2026-05-30，Phase 5 前清理）**：
   - **R-T2 ✅ 修复**：新增 `mosaic-ts/src/cli/_format.ts`（CJK + ANSI 双感知
     `displayWidth()` / `pad()`），替换 6 个 CLI（scorecard / darwinian /
     backtest / daily-cycle / autoresearch / prism）各自的 `pad()`；+7 个
     `format.test.ts` 单测。中文表格不再错列。
   - **R-T3 ✅ 修复**：`daily_cycle.ts` `invokeSubgraph` 改用
     `(result.messages ?? []).slice` / `(result.llm_calls ?? []).slice`，防御
     subgraph 异常返回缺通道时的 NPE。
   - **R-T4 ✅ 已修（PR #6）**：`mosaic/scorecard/__init__.py` `get_store()`
     module-level 单例；bridge handler 统一走它。
   - **R-T5 ✅ 已修（PR #6）**：`update_scoring` 在 `cur.rowcount == 0` 时
     `log.warning`。
   - **R-T6 ✅ 已满足**：`bridge/errors.ts` 三个 error class 均传 ES2022
     `{ cause }`；daily-cycle / backtest CLI 的 catch 块是终端处理器（打印 +
     `process.exitCode`），不 re-wrap、不丢链，无需改动。
   - **R-A2 ✅ 定稿**：`expand_state_to_recommendations` 的 CIO 行 `conviction`
     改写 `NULL`（不再用 target_weight 代理），明确「不可比」；`target_weight_pct`
     仍是真实仓位权重。autoresearch 评估 CIO 用组合 Sharpe（§11.5 决策 #10），
     `scorecard.list_skill` 聚合 `alpha_5d` 不读 conviction，故安全。
   - **仍延后（非阻塞）**：**R-T1**（4 个 layer builder 的 `let graph: any` —
     纯类型推断，待 LangGraph 升级或写 typed `chainEdges` helper）；**R-P1**
     （`qlib_ingest` 直接 `struct.unpack` 读 qlib binary，耦合内部格式，待 qlib
     升级再换 DataApi）；**R-A1**（`replay_triggered` state channel，等真正需要
     时加）；**R-A3**（backtest-fill 失败 `failed_days` 持久化查询接口，等
     autoresearch 自动重跑时加）；**R-A4**（`ingest_full` per-ticker 120s
     timeout 文档标注 — 纯文档，已在此说明：120s 是单 ticker 不是全 ingest）。

10. **Phase 4 目标 cohort — ✅ 已定（2026-05-29）= `crisis_2008`**。用户选高波动
    regime（§9：2007-10-17 → 2008-10-28，A 股暴跌 70% / 1664 见底）作 autoresearch
    压力测试；eval 窗口默认 cohort 最后 60 交易日。crisis_2008 无专属 prompt，
    全 fallback 到 cohort_default，mutation 累积出 cohort_crisis_2008 文件（详见
    §11.5「已确认决策」+ 4F 设计决策）。

11. **Phase 4 git 模型简化 — ✅ 已确认（2026-05-29）= OK**。MVP 用单 trunk on
    `main` + 短寿 feature branch；per-cohort 演化 trunk 推迟 Phase 5 PRISM。

12. **Phase 4 评估方法 — ✅ 已确认（2026-05-29）= backtest-based ΔSharpe**。
    秒级回放（复用 Phase 3.5 两段式 + prompt_commit_hash 缓存），不等 5 个真实
    交易日；forward-time 真实 alpha 确认推迟 Phase 8 实盘。

13. **Phase 4 macro tools pre-flight — ✅ 已决（2026-05-29）= 先跑通机制、工具
    后补**。Layer-1 macro 工具缺口（property / usdcny / commodity / ivx）不在
    Phase 4 范围；Phase 4 后 / Phase 5 启动前补（plan §14 #8 + §11.5 4.0 P1）。

---

## 15. 工作流约定（沿用 ETFAgents）

每个子任务完成后：
1. `pnpm typecheck` clean
2. `pnpm lint`（biome）clean
3. `pnpm test` 全绿
4. `python -m unittest discover -s tests -q` 全绿
5. 更新本文档对应章节状态 + 完成时戳
6. 在用户能验证的 checkpoint 处暂停

**何时端到端**：每完成一个 Phase 末做一次 `mosaic-cycle` 真实跑（用最便宜
的 LLM 配置），观察输出是否相对上次有可见改进；记录 LLM 凭证依赖（Anthropic
API key、TUSHARE_TOKEN、本地 Lemonade 端点）的最低运行要求。

---

## 16. 当前里程碑（写于 2026-05-28）

**已完成**：仅本计划文档。

**下一步**：用户已确认本计划 → 进入 Phase 0 Day 1（Python sidecar 搭建）。

### 16.1 仓库布局（采用方案 A：MOSAIC-Agents 独立仓）

MOSAIC 项目代码全部落地到独立 GitHub 仓库
**`git@github.com:haphap/MOSAIC-Agents.git`**，本地路径
`/home/hap/Projects/MOSAIC-Agents/`。`atlas-gic/` 与 `ETFAgents/`
保留为只读参考。

**只读参考目录**（不在 MOSAIC 仓内，仅提供素材）：

```
/home/hap/Projects/atlas-gic/                # ATLAS 公开版（参考）
├── README.md / CLAUDE.md / LICENSE           # ATLAS 公开材料
├── architecture/ prompts/ results/           # ATLAS 公开架构 + prompt 模板 + 回测
├── src/                                      # ATLAS 公开 src/janus.py + src/mirofish/（Phase 6/7 移植源）
└── mosaic-tsplan.md                          # ⭐ 本文档（保留为只读副本，工作主文档已迁至 MOSAIC-Agents/）

/home/hap/Projects/ETFAgents/                # ETFAgents 已完成项目（复用源）
├── etfagents/                                # bridge/cache/dataflows/paper_trading/backtest 复制源
├── ts/                                       # mosaic-ts 前端复制源
└── tests/                                    # 测试模板复制源
```

**MOSAIC-Agents/ 当前布局**：

```
/home/hap/Projects/MOSAIC-Agents/             # 项目根（GitHub: haphap/MOSAIC-Agents）
└── .git/                                     # 已 clone，远程 = origin
```

**MOSAIC-Agents/ 目标布局**（Phase 0–9 累计创建）：

```
/home/hap/Projects/MOSAIC-Agents/
├── mosaic-tsplan.md           # ⭐ 工作主文档（每个 sub-step 完成后更新）
├── README.md                  # MOSAIC 项目 README（Phase 9 完成）
├── LICENSE                    # MOSAIC 自有 LICENSE
├── pyproject.toml             # Python 包定义（Phase 0 Day 1 创建）
├── .env.example               # 环境变量模板（Phase 0 Day 2）
├── .gitignore                 # 标准 Python + Node 忽略
├── mosaic/                    # Phase 0+ Python sidecar
│   ├── __init__.py
│   ├── default_config.py
│   ├── bridge/                # JSON-RPC stdio sidecar
│   ├── dataflows/             # Phase 0 Day 2-3
│   ├── cache_manager.py       # Phase 0 Day 2
│   ├── agents/utils/          # Phase 0 Day 4 + Phase 2+
│   ├── paper_trading/         # Phase 8 移植
│   ├── backtest/              # Phase 8 移植
│   ├── prism/                 # Phase 5
│   ├── janus.py               # Phase 6 移植 ATLAS
│   └── mirofish/              # Phase 7 移植 ATLAS
├── mosaic-ts/                 # Phase 1+ TypeScript 前端
│   ├── package.json
│   ├── tsconfig.json
│   ├── src/
│   │   ├── bridge/            # Phase 1 复制 ETFAgents
│   │   ├── llm/               # Phase 1
│   │   ├── agents/            # Phase 2+ (4 layer × 25 agents)
│   │   ├── cli/               # Phase 9
│   │   └── tui/               # Phase 9
│   └── test/
├── prompts/mosaic/            # Phase 2+ Cohort prompt 仓库（autoresearch git 修改对象）
│   ├── cohort_default/
│   └── cohort_<name>/         # 7 个 cohort × 25 agent × 双语
├── data/                      # Phase 3+ SQLite + 缓存（受 MOSAIC_DATA_DIR 控制；默认 .gitignore）
│   ├── mosaic.db
│   ├── cache/
│   └── backups/
├── docs/                      # Phase 9 用户文档
├── scripts/                   # 辅助脚本（数据回填 / 训练编排 / cohort 切换）
└── tests/                     # Python 测试（TS 测试在 mosaic-ts/test/）
```

### 16.2 工作主文档约定

- `MOSAIC-Agents/mosaic-tsplan.md` = **工作主文档**（每个 sub-step 完成后更新此处）
- `atlas-gic/mosaic-tsplan.md` = **只读初始副本**（保留作为方案制定时的快照，不再更新）
- 状态符号：⏭ 待开始 / 🟡 进行中 / ✅ 已完成（YYYY-MM-DD）/ ❌ 阻塞（原因）

---

## 17. 总估算

| 维度 | 估算 |
|---|---|
| Phase turns 总数 | 50–58 turns |
| TS 新增代码 | ~10,000 LOC（其中 ~3,000 直接复用 ETFAgents） |
| Python 新增代码 | ~15,000 LOC（其中 ~5,000 直接复用 ETFAgents + ATLAS 公开） |
| 测试代码 | ~6,000 LOC |
| 全程 LLM 成本 | $370–570 美元（Anthropic）或更低（DeepSeek/本地 Lemonade） |
| Tushare 订阅 | 0–500 元/年 |
| 业余推进时间 | 6.5–9.5 个月 |

---
