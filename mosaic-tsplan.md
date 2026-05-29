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
- **Q5=a**：执行层 = **仅 paper trading + backtrader**（复用 ETFAgents）
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
| 1 | TS skeleton + bridge-client（直接复用 ETFAgents Phase 1） | 3–4 | ⏭ |
| 2 | Daily cycle MVP：25 agents + 4 层 LangGraph.js（单 cohort） | 11–12 | ⏭ |
| 3 | Scorecard + Darwinian 权重 | 4 | ⏭ |
| 4 | Autoresearch（git + SQLite，prompt mutation + keep/revert） | 5–6 | ⏭ |
| 5 | PRISM 7 cohort 训练编排 | 5–6 | ⏭ |
| 6 | JANUS 元层（port ATLAS 571 LOC） | 3 | ⏭ |
| 7 | MiroFish 反身性模拟（port ATLAS ~2,800 LOC + Tushare 适配） | 4–5 | ⏭ |
| 8 | 执行层（paper + backtrader，复用 ETFAgents） | 4 | ⏭ |
| 9 | Ink TUI + CLI + 文档 + CI 部署 | 6–8 | ⏭ |
| **总计** | | **50–58 turns / 6.5–9.5 个月业余工时** | |

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
- `backtest.run_candidate_pool`

### 6.2 新增（约 27 个）

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

- [ ] Layer 2: 7 sector agents（同模板，工具用 sector-specific holdings/research）
- [ ] Layer 3: 4 superinvestor agents（哲学过滤器；prompts 重头戏）
- [ ] Layer 4: cro / alpha_discovery / autonomous_execution / cio
      （Plan §5.4，cio 是 final aggregator）
- [ ] cohort fanout helper：从 `layer1_consensus` 派生不同 cohort 的 view
      （Phase 5 PRISM 用）

### Sub-step 2E：4 层 LangGraph.js graph 装配

- [ ] `mosaic-ts/src/graph/daily_cycle.ts` —— `buildDailyCycleGraph()`
- [ ] State propagation：L1 → L2（按 RegimeSignal 决定 sector 启用集）→
      L3 → L4
- [ ] Conditional edge：CRO 否决 → 回 L4 重做 alpha_discovery（max 1 轮，
      避免死循环）
- [ ] 大约 ~500 LOC，参考 ETFAgents `graph/etf_graph.py` 架构

### Sub-step 2F：Daily cycle MVP CLI smoke

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
   Phase 2 落 agent 之前清掉）：
   - **R1**：`mosaic-ts/src/cli/commands/tool-call.ts` 的 `JSON.parse(argsJson)`
     无 try/catch，畸形 JSON 直接抛 SyntaxError 把 stack 打到 terminal。包成
     友好 CLI 错误。
   - **R2**：`mosaic-ts/src/bridge/types.ts` 的 `BridgeApi` docstring 说 "21 RPC
     methods" 但只 typed 包了 12 个；缺 `paper.{register,login,logout,
     reset_account,buy,sell,suggest_order_from_signal}` + `cache.details`。
     要么 Phase 8 补全，要么改文案为 "selected wrappers"。
   - **R3**：`mosaic-ts/src/llm/factory.ts` 的 Lemonade base URL
     `http://localhost:8000/api/v0` 是从内存写的、未实弹验证。加注释引导用户
     看 `lemonade-server-dev` 启动日志，或暴露 `MOSAIC_LLM_BASE_URL` env override。
   - **代码细项 (1)**：`mosaic-ts/src/bridge/tools.ts` 的 `prop.default as never`
     太宽。放宽 `JsonSchemaProperty.default` 的 type 注解或用 `as
     Parameters<typeof field.default>[0]` 收敛 cast。
   - **代码细项 (3)**：3 个 error class（RpcError、BridgeStartupError、
     BridgeTransportError）不传 `{ cause: err }`，丢失原始 stack chain。补上
     ES2022 cause 链。
   - **代码细项 (5)**：`MosaicConfig = Record<string, unknown>` 太松。Phase 2
     落 agent state / cohort / autoresearch 字段时拉成 Zod-validated schema
     或 discriminated union。

   不阻塞 PR #1 merge。Phase 1 PR #1 提交时已修了真 correctness bug
   （tool-loop forced-final 用 unbound LLM），其余记此追踪。

8. **Layer-1 macro tools 缺口**（plan §5.1 列出的工具 vs Phase 0 macro_data 实际
   实现的工具差距，影响 2C 的 agent prompt）：

   | Plan §5.1 期望 | Phase 0 实际有 | 2C.2 替代 / 处理 |
   |---|---|---|
   | `get_property_data` (china) | ❌ | 用 `get_north_capital_flow` 替代 |
   | `get_us_china_relations` (geopolitical) | ❌ | 用 `get_xueqiu_heat` + `get_industry_policy`（地缘相关关键词）|
   | `get_usdcny` (dollar) | ❌ | 用 `get_fred_series(DTWEXBGS)` + `get_north_capital_flow` |
   | `get_commodity_prices` (commodities) | ❌ | 用 `get_fred_series(DCOILWTICO)` + `get_fred_series(GOLDPMGBD228NLBM)` |
   | `get_ivx` (volatility) | ❌ | 仅用 `get_fred_series(VIXCLS)` + `get_yield_curve_cn` 推断 |
   | `get_etf_indicator(510050.SH)` (volatility) | ❌（ETF 工具 Phase 1+） | 同上 |
   | `get_etf_price_data(EEM)` (emerging_markets) | ❌ | 用 `get_north_capital_flow` + `get_us_china_spread` |
   | `get_etf_price_data(2800.HK)` (emerging_markets) | ❌ | 同上 |
   | `get_news` (news_sentiment) | ✅ dataflows 有，未 macro_tools 包装 | Phase 0 Day 4 已包 `get_industry_policy`（含 news），用它 |
   | `get_caixin_sentiment` (news_sentiment) | ❌ | 用 `get_xueqiu_heat` |
   | `get_fund_flow` (institutional_flow) | ❌ | 用 `get_lhb_ranking` |

   **TODO Phase 4 autoresearch 启动前**补齐 `get_property_data` /
   `get_usdcny` / `get_commodity_prices` / `get_ivx` / `get_etf_*` /
   `get_caixin_sentiment` / `get_fund_flow` 至少其中 4 个核心的（property /
   usdcny / commodity / ivx）。每补一个，对应 agent prompt 的"工具列表"和
   置信度门槛同步收紧（plan §11.2 2C 设计决策 #3 提到 Phase 4 会
   autoresearch 迭代 prompt）。

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
