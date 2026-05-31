# 架构

MOSAIC 是一个**混合双进程系统**。重逻辑/有状态部分留在 Python;编排、LLM 调用与用户界面在 TypeScript。两端通过**行分隔 JSON-RPC over stdio** 通信。

```
TypeScript 前端 (mosaic-ts/)           JSON-RPC / stdio        Python sidecar (mosaic/)
──────────────────────────────        ───────────────        ────────────────────────────
CLI (commander) + TUI (Ink)                                   bridge/    JSON-RPC 服务 + handlers/
LangGraph.js 4 层编排                ⇄  行分隔 JSON         ⇄  dataflows/ Tushare/akshare/FRED/qlib
  L1 宏观(10) · L2 行业(7)                                    scorecard/ · autoresearch/ · prism/
  L3 投资哲学(4) · L4 决策(4)                                janus/ · mirofish/ · backtest/ · paper_trading/
LLM 客户端 · Scorecard 视图                                   持久化:SQLite + 一个 git 仓库
```

## 为何拆分

- **工具调用边界一律字符串/JSON** —— 无跨语言 DataFrame 传输。TS 侧请求数据或动作,Python 返回 JSON。
- 重型 Python 库(pandas、numpy、pyqlib、tushare)无需 Node 绑定。
- LLM/agent 编排(LangGraph.js)与用户侧 CLI/TUI 同处一套 TypeScript 代码。

## 桥 (bridge)

- **服务端**:`mosaic/bridge/server.py` 从 stdin 读 JSON-RPC 请求,按方法名分发,向 stdout 写响应。导入 `mosaic.bridge.handlers` 会通过 `@method("namespace.verb")` 装饰器(`mosaic/bridge/registry.py`)注册每个 handler。
- **客户端**:`mosaic-ts/src/bridge/client.ts`(`BridgeClient`)spawn Python 进程、组帧请求、按 id 关联响应、把 `{error}` 信封映射为 `RpcError`。`mosaic-ts/src/bridge/types.ts`(`BridgeApi`)把每个 RPC 封装为类型化方法。
- **解释器发现**(`mosaic-ts/src/bridge/python.ts`):`MOSAIC_PYTHON` 环境变量 → `<repo>/.venv/bin/python` → fail-loud。
- 完整方法表见[桥 RPC](Bridge-RPC.md)。

## 仓库布局

```
MOSAIC-Agents/
├── mosaic/                     # 🐍 Python sidecar
│   ├── bridge/                 #   JSON-RPC 服务 + handlers/(每命名空间一个模块)
│   ├── dataflows/              #   Tushare / akshare / yfinance / FRED + qlib 本地读取 + ingest
│   │   └── collectors/         #   vendored qlib + tushare/ETF 采集器(见数据层)
│   ├── scorecard/              #   SQLite 存储 · forward-return 评分 · Darwinian 权重
│   ├── autoresearch/           #   git_ops · 约束 · 评估器 · keep/revert 决策器
│   ├── prism/                  #   7-cohort 训练编排
│   ├── janus/                  #   跨 cohort 元加权
│   ├── mirofish/               #   反身性情景模拟(swarm 引擎 · path-aware 评分)
│   ├── backtest/               #   qlib 两段式向量化回测
│   └── paper_trading/          #   自建纸上交易引擎(T+1、佣金、持仓)
├── mosaic-ts/                  # 🟦 TypeScript 前端
│   └── src/
│       ├── bridge/             #   BridgeClient + 类型化 RPC 封装 (BridgeApi)
│       ├── llm/                #   多 provider LLM 工厂
│       ├── agents/             #   macro/sector/superinvestor/decision + helpers + prompts
│       ├── graph/              #   daily_cycle LangGraph.js 装配
│       ├── autoresearch/ · prism/ · mirofish/
│       ├── cli/commands/       #   CLI 子命令
│       └── tui/                #   Ink 仪表盘
├── prompts/mosaic/             # 📝 双语提示词仓库(cohort_default + 7 cohorts)
├── tests/                      # ✅ Python 测试 (pytest / unittest)
├── pyproject.toml · mosaic-tsplan.md · .github/workflows/ci.yml
```

## 确定性 & 防前视 (anti-lookahead)

- 评分器把「今天」回退到最后一个已完成交易日,只给前向窗口已成熟的行评分(`mosaic/scorecard/scorer.py`)。
- MiroFish 上下文注入与上下文读取接受 `as_of_date` 边界,使回测永不看见未来情景数据。

## 持久化

- **SQLite** —— scorecard 推荐 + 评分、autoresearch 元数据、回测 run 缓存、纸交易 DB(`~/.mosaic/paper_trading.db`)。
- **git 仓库** —— Autoresearch 在 feature 分支上版本化提示词变更;keep = 合并到 main,revert = 删分支(见[自我改进](Self-Improvement.md))。
- **配置文件** —— `~/.mosaic/config.json`(可选;见[配置](Configuration.md))。
