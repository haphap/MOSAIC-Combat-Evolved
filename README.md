# MOSAIC-Agents

[![CI](https://github.com/haphap/MOSAIC-Agents/actions/workflows/ci.yml/badge.svg)](https://github.com/haphap/MOSAIC-Agents/actions/workflows/ci.yml)

> A 股版 ATLAS：自我改进多智能体交易框架。
> 混合架构（Python sidecar + TypeScript 前端），复用 [ETFAgents](https://github.com/haphap/ETFAgents) 的 bridge / dataflows / paper_trading / backtest 经验。

**当前状态**：Phase 0–9 完成（25 agents 日循环、scorecard + Darwinian、qlib 回测、autoresearch、PRISM、JANUS、MiroFish、paper trading、CI、只读 Ink TUI dashboard）。MiroFish 记忆/persona（7M.2/7M.3）经增益验证 **deferred**。

完整实施计划与各 Phase 进度见 [`mosaic-tsplan.md`](./mosaic-tsplan.md)（工作主文档，§3 阶段总览）。

## 仓库布局

```
mosaic/                  # Python sidecar（JSON-RPC stdio）
├── bridge/              # 协议 + handler 注册（tools/config/cache/paper/backtest/
│                        #   scorecard/darwinian/autoresearch/prism/janus/mirofish/...）
├── dataflows/           # Tushare/akshare/FRED/qlib 数据接口 + vendor 路由
├── agents/              # 25 agent 的工具与 schema
├── scorecard/           # 评分 + Darwinian 权重 + SQLite store
├── backtest/            # qlib 向量化回测引擎（Phase 3.5）
├── paper_trading/       # 模拟券商账户：auth/仓位/T+1/佣金（Phase 8）
├── mirofish/            # 反身性情景引擎 + swarm + path-aware scorer（Phase 7 / 7M）
├── janus/ · autoresearch/ · ...
└── default_config.py    # 运行时默认配置

mosaic-ts/               # TypeScript 前端（LLM 编排 + CLI）
├── src/agents/          # 4 层 LangGraph.js 编排
├── src/cli/commands/    # daily-cycle / scorecard / backtest / autoresearch /
│                        #   prism / janus / mirofish / paper / ...
└── src/bridge/          # JSON-RPC client + 类型化 API

prompts/mosaic/          # Cohort 双语 prompt 仓库
data/                    # SQLite + 缓存（受 MOSAIC_DATA_DIR 控制；.gitignore）
tests/                   # Python 测试
.github/workflows/ci.yml # CI：Python(pytest) + TS(typecheck/lint/test) 两 lane
```

## 快速开始

```bash
# Python sidecar（bridge）
uv venv
source .venv/bin/activate
uv pip install -e ".[data]"          # 数据层（pandas/numpy/tushare/...）
# 可选 extras：.[trading]（paper trading，bcrypt）/ .[backtest]（qlib）/ .[llm]

# 探测 bridge：
echo '{"jsonrpc":"2.0","id":1,"method":"tools.list","params":{}}' | python -m mosaic.bridge

# TS 前端
cd mosaic-ts
pnpm install
pnpm dev daily-cycle --help          # 日循环
pnpm dev paper account               # 模拟账户（Phase 8）
```

## 日常使用（每天看什么）

系统是**半自动**的：用 cron 在收盘后按顺序跑这条流水线，结果落 SQLite，再用 TUI 看。

```bash
# crontab 示例（交易日收盘后）：日循环 → 评分 → Darwinian → JANUS
cd mosaic-ts
pnpm dev daily-cycle --cohort cohort_default      # 25 agent → CIO 出当日组合建议（落库 recommendations 表）
pnpm dev scorecard score-pending --cohort cohort_default   # 回填 forward_return（需 T+5 后才有命中数据）
pnpm dev darwinian --cohort cohort_default
pnpm dev janus run

# 每天看一屏：
pnpm dev dashboard
```

`dashboard` 的 **[1] today** = 今天 CIO 建议买/卖什么（ticker / 方向 / 目标权重 / 逻辑）；
**[2] winrate** = 逐标的方向命中率（`sign(action)·未来5日收益>0` 的占比，带样本数 n）。

> **关于"胜率"的诚实说明**：winrate 是**本系统 CIO 历史建议**的方向命中率（已评分行上的统计），
> 需要积累若干天的 daily-cycle + 评分回填后才有意义（n 太小不可信）；它**不是**对某只股票的
> 普适"交易胜率预测"。系统给的是"我过去这样建议，事后对了多少"，而非"这只股票未来必涨"。

## 依赖分层（extras）

| extra | 内容 | 何时需要 |
|---|---|---|
| `data` | pandas/numpy/tushare/akshare/yfinance/... | 数据接口、大多数功能 |
| `trading` | bcrypt | paper trading（Phase 8） |
| `backtest` | pyqlib/scipy/tqdm（重，~200MB） | qlib 历史回测（Phase 3.5） |
| `llm` | langchain-anthropic/openai/google + langgraph | TS 端 agent 编排 |
| `test` | pytest | 跑测试 |

CI 的 Python lane 安装 `.[data,trading,test]`（不含重型 qlib），qlib-only 测试在缺 qlib 时自动 skip。

## 关键决策

- **Q1=a**：完整复刻 ATLAS 4 层 25+ agents
- **Q5=a**：执行层 = paper trading（已落地）；回测用 qlib 向量化引擎（**不引 backtrader**）
- **Q6=c**：autoresearch = Git + SQLite 混合
- **默认语言**：Chinese；**默认 LLM**：Anthropic Claude Sonnet（可切本地 Qwen 零成本）
- **MiroFish 交互栈（7M.1–7M.5）**：swarm 引擎 + path-aware scorer 已并入主干；记忆/persona（7M.2/7M.3）经增益验证 **deferred**，详见 `mosaic-tsplan.md` §11.8.1

## 关联仓库

- [ATLAS 公开版](https://github.com/general-intelligence-capital/atlas) — 架构文档 + janus.py + mirofish/ 移植源
- [ETFAgents](https://github.com/haphap/ETFAgents) — bridge / dataflows / paper_trading / backtest 复用源

## License

待添加（Phase 9 末确定）。
