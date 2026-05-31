<div align="center">

<!-- LOGO PLACEHOLDER · 在此放置项目 Logo / Banner (docs/assets/mosaic-banner.png) -->

# 🧩 MOSAIC

**A 股自我改进型多智能体量化交易框架**
_An A-share self-improving multi-agent trading framework — inspired by ATLAS._

[![CI](https://github.com/haphap/MOSAIC-Agents/actions/workflows/ci.yml/badge.svg)](https://github.com/haphap/MOSAIC-Agents/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-%E2%89%A53.10-3776AB?logo=python&logoColor=white)
![Node](https://img.shields.io/badge/Node-%E2%89%A522-339933?logo=node.js&logoColor=white)
![Status](https://img.shields.io/badge/phases-0--10%20complete-success)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

> 25 个智能体 · 4 层决策图 · 提示词自进化 · 多周期训练 · 反身性模拟 —— 全部跑在一个混合 **Python sidecar + TypeScript 前端** 架构上。

</div>

---

## 📑 目录 (Table of Contents)

- [关于项目 (About)](#-关于项目-about)
- [技术栈与环境要求 (Tech Stack & Prerequisites)](#️-技术栈与环境要求-tech-stack--prerequisites)
- [快速上手 (Getting Started)](#-快速上手-getting-started)
  - [安装 (Installation)](#安装-installation)
  - [使用 (Usage)](#使用-usage)
- [核心架构与目录结构 (Architecture & Project Structure)](#-核心架构与目录结构-architecture--project-structure)
- [贡献指南 (Contributing)](#-贡献指南-contributing)
- [开源协议与致谢 (License & Acknowledgments)](#-开源协议与致谢-license--acknowledgments)

---

## 🎯 关于项目 (About)

**MOSAIC** 将 [ATLAS](https://github.com/general-intelligence-capital/atlas) 的「四层多智能体 + 自我改进」交易范式**完整复刻并适配到 A 股市场**。它采用混合架构：**重逻辑（numpy / pandas / git / SQLite / 行情数据）留在 Python sidecar，编排 / LLM / CLI / TUI 交给 TypeScript 前端**，两端通过**行分隔 JSON-RPC over stdio** 通信。

**解决的痛点 (Pain Points):**

- 单一 LLM「分析师」缺乏对抗、缺乏记忆、无法随市场演化 —— MOSAIC 用分层 agent 群体 + 风控对抗 + 提示词自进化来应对。
- 策略研究难以复现、难以量化「改了到底有没有变好」—— MOSAIC 用 **git 版本化提示词 + SQLite 元数据 + ΔSharpe 秒级回测**闭环。
- A 股本地化数据缺位 —— 内置 Tushare / akshare / FRED / 雪球 等 14+ 宏观与行情工具。

**核心特性 (Key Features):**

- 🧠 **4 层 25 智能体**：Layer-1 宏观(10) → Layer-2 行业(7) → Layer-3 投资哲学(4) → Layer-4 决策(CRO / Alpha / Execution / CIO)，由 **LangGraph.js** 编排成单次 daily cycle。
- 🔁 **Autoresearch 自进化**：自动选 agent → LLM 改写提示词 → git feature 分支 → 两段式回测算 **ΔSharpe** → 按阈值 `keep`（合并）/ `revert`（删分支），受 24h 冷却 / 3 天锁定 / 月度上限约束。
- 🌈 **PRISM 多周期训练**：7 个市场 regime cohort（2007 牛市 / 2008 危机 / …）顺序训练，层内最多 5 agent 并发。
- ⚖️ **JANUS 元加权 + 🐟 MiroFish 反身性模拟**：跨 cohort softmax 元权重；基于行为主体群的反身性合成行情（可选 swarm 引擎 + path-aware 评分）。
- 📊 **qlib 两段式向量化回测 + 纸上交易**：Scorecard / Darwinian 权重、qlib 历史回放、自建 paper-trading 引擎（T+1 / 佣金 / 持仓），以及只读 **Ink TUI** 仪表盘。

---

## 🛠️ 技术栈与环境要求 (Tech Stack & Prerequisites)

| 层 (Layer)            | 技术 (Stack)                                                                                                          |
| --------------------- | ------------------------------------------------------------------------------------------------------------------- |
| **Python sidecar**    | Python `≥3.10` · langchain-core · pandas / numpy · Tushare / akshare / yfinance / FRED · pyqlib · SQLite · git |
| **TypeScript 前端**   | Node `≥22` · LangGraph.js `^1.3` · `@langchain/{core,anthropic,openai}` · commander · zod · Ink `^7` + React `19`     |
| **工具链 (Tooling)**  | uv (Python) · pnpm `11` · ruff · biome · pytest · vitest · GitHub Actions CI                                          |

**运行前置条件 (Prerequisites):**

- 🐍 **Python ≥ 3.10**（推荐用 [`uv`](https://github.com/astral-sh/uv) 管理虚拟环境）
- 🟢 **Node.js ≥ 22** 与 **pnpm 11**
- 🔑 **API 凭证**（按需，写入 `.env`，参考 `.env.example`）：
  - `TUSHARE_TOKEN` —— A 股行情 / 财务（必需）
  - `FRED_API_KEY` —— 全球宏观（可选）
  - `ANTHROPIC_API_KEY` / `DEEPSEEK_API_KEY` —— 生产期 LLM；开发期可用本地 **Lemonade Qwen** 或 `--fake-llm` 零成本跑通

> 💡 依赖按 **optional extras** 分组：`data`（行情）/ `trading`（纸交易）/ `llm`（LLM provider）/ `backtest`（pyqlib，~200MB）/ `test`。按需安装，避免拉取不必要的重型依赖。

---

## 🚀 快速上手 (Getting Started)

### 安装 (Installation)

```bash
# 1. 克隆仓库
git clone https://github.com/haphap/MOSAIC-Agents.git
cd MOSAIC-Agents

# 2. Python sidecar：创建 .venv 并安装依赖
#    （TS 前端会自动发现 <repo>/.venv/bin/python，或用 MOSAIC_PYTHON 覆盖）
uv venv
uv pip install -e '.[data,trading,llm]'     # 需要历史回测再加 ,backtest

# 3. TypeScript 前端
cd mosaic-ts
pnpm install --frozen-lockfile

# 4. 配置环境变量
cd ..
cp .env.example .env       # 填入 TUSHARE_TOKEN / FRED_API_KEY / LLM keys
```

### 使用 (Usage)

所有命令在 `mosaic-ts/` 下通过 `pnpm dev <command>` 运行（开发期），或 `pnpm build && mosaic <command>`（构建后）。

```bash
cd mosaic-ts

# ▶️ 跑通一次完整 daily cycle（25 agents），零成本 mock LLM
pnpm dev daily-cycle --cohort cohort_default --fake-llm

# 📈 查看 agent 技能分 / Darwinian 权重
pnpm dev scorecard --cohort cohort_default --since 2024-01-01
pnpm dev darwinian --cohort cohort_default

# 🔁 触发一次提示词自进化（生成 → 提交 → ΔSharpe 评估 → keep/revert）
pnpm dev autoresearch trigger --cohort crisis_2008 --fake-llm --eval-days 5
pnpm dev autoresearch log --cohort crisis_2008

# 🌈 PRISM 多周期 · ⚖️ JANUS 元权重 · 🐟 MiroFish 反身性模拟
pnpm dev prism list
pnpm dev janus weights
pnpm dev mirofish generate --swarm --seed 7            # swarm 情景集；train 时 --path-aware 用回撤惩罚打分

# 🧾 纸上交易 · 📊 只读 TUI 仪表盘
pnpm dev paper account
pnpm dev dashboard
```

> ⚙️ 默认输出为**中文报告**；CLI 选项保持英文（`--lang zh|en|bilingual` 可切换）。`--fake-llm` 是推荐的零成本验证通道。

#### 📅 日常使用（每天看什么）

系统是**半自动**的：用 cron 在收盘后按顺序跑这条流水线，结果落 SQLite，再用 TUI 看。

```bash
# crontab 示例（交易日收盘后）：日循环 → 评分 → Darwinian → JANUS
cd mosaic-ts
pnpm dev daily-cycle --cohort cohort_default                # 25 agent → CIO 出当日组合建议（落库 recommendations 表）
pnpm dev scorecard score-pending --cohort cohort_default    # 回填 forward_return（需 T+5 后才有命中数据）
pnpm dev darwinian --cohort cohort_default
pnpm dev janus run
pnpm dev dashboard                                          # 每天看一屏
```

`dashboard` 的 **[1] today** = 今天 CIO 建议买/卖什么（ticker / 方向 / 目标权重 / 逻辑）；**[2] winrate** = 逐标的方向命中率（`sign(action)·未来5日收益>0` 的占比，带样本数 n）。

> 🎯 **关于"胜率"的诚实说明**：winrate 是**本系统 CIO 历史建议**的方向命中率（已评分行上的统计），需要积累若干天的 daily-cycle + 评分回填后才有意义（n 太小不可信）；它**不是**对某只股票的普适"交易胜率预测"。系统给的是"我过去这样建议，事后对了多少"，而非"这只股票未来必涨"。

#### 📦 ETF 行情数据（宽基 ETF 建议可用）

CIO 建议含宽基 ETF（510300/510050/…）。ETF 行情走独立的 qlib 数据集 `~/.qlib/qlib_data/cn_etf`（与个股 `cn_data` 同日历、独立 features 树）：

- **读**：`qlib_local` 按 instrument 前缀路由（ETF=`sh5x/sz1x` → `cn_etf`，个股=`sh6/sz0/sz3` → `cn_data`）；`QLIB_CN_ETF_PATH` 可覆盖路径。
- **刷新**：`qlib_ingest` 的 `kind="etf"` 驱动 ETF collector（`~/.qlib/scripts/data_collector/tushare_etf/collector.py`，或 `MOSAIC_QLIB_ETF_COLLECTOR` 指定），默认 dump 到 `cn_etf`。

---

## 🏗️ 核心架构与目录结构 (Architecture & Project Structure)

```text
TypeScript 前端 (mosaic-ts/)        JSON-RPC / stdio        Python sidecar (mosaic/)
────────────────────────────       ───────────────         ──────────────────────────
CLI (commander) + TUI (Ink)                                 bridge/   (JSON-RPC 服务 + handlers)
LangGraph.js 4 层编排:                                       dataflows/ (Tushare/akshare/FRED/...)
  L1 macro(10) · L2 sector(7)   ⇄  行分隔 JSON  ⇄            scorecard/ · autoresearch/ · prism/
  L3 superinvestor(4) · L4(4)                                janus/ · mirofish/ · backtest/ · paper_trading/
LLM clients · Scorecard 可视化                               persistence: SQLite + git repo
```

```text
MOSAIC-Agents/
├── mosaic/                     # 🐍 Python sidecar
│   ├── bridge/                 #   JSON-RPC over stdio + handlers/ (tools/config/cache/paper/
│   │                           #   backtest/scorecard/darwinian/prompts/autoresearch/prism/janus/mirofish)
│   ├── dataflows/              #   Tushare / akshare / yfinance / FRED / 宏观工具
│   ├── scorecard/              #   SQLite 存储 · forward-return 打分 · Darwinian 权重
│   ├── autoresearch/           #   git_ops · 约束 · 评估器 · keep/revert 决策
│   ├── prism/                  #   7-cohort 训练编排
│   ├── janus/                  #   跨 cohort 元加权
│   ├── mirofish/               #   反身性合成行情 (swarm 引擎 · path-aware 评分)
│   ├── backtest/               #   qlib 两段式向量化回测
│   ├── paper_trading/          #   纸上交易引擎
│   ├── cache_manager.py
│   └── default_config.py
├── mosaic-ts/                  # 🟦 TypeScript 前端
│   └── src/
│       ├── bridge/             #   BridgeClient + 类型化 RPC 封装
│       ├── llm/                #   多 provider LLM 工厂
│       ├── agents/             #   macro/sector/superinvestor/decision + helpers + prompts
│       ├── graph/              #   daily_cycle LangGraph.js 装配
│       ├── autoresearch/ · prism/ · mirofish/
│       ├── cli/commands/       #   CLI 子命令
│       └── tui/                #   Ink 仪表盘
├── prompts/mosaic/             # 📝 双语提示词仓库 (cohort_default + 7 cohorts)
├── tests/                      # ✅ Python 测试 (pytest / unittest)
├── pyproject.toml · mosaic-tsplan.md · .github/workflows/ci.yml
```

> 📐 **架构原则**：工具调用边界一律用字符串 / JSON（无跨语言 DataFrame 传输）；解释器发现顺序 `MOSAIC_PYTHON` → `<repo>/.venv/bin/python` → fail-loud。详见 [`mosaic-tsplan.md`](mosaic-tsplan.md)（§2 架构、§3 阶段总览、§11 详细任务）。

---

## 🤝 贡献指南 (Contributing)

欢迎 Issue 与 PR！请遵循以下约定：

1. **Issue**：报告 bug 请附复现步骤、期望/实际行为与环境（Python / Node 版本）；功能建议请说明动机与使用场景。
2. **分支命名 (Branch)**：`phase-x-<feature>` / `fix-<scope>` / `chore-<scope>`；autoresearch 自动分支为 `cohort/{name}/auto/{agent}/{YYYY-MM-DD}`。
3. **提交前自检 (Verification Matrix)** —— 全绿方可提 PR：
   ```bash
   # TypeScript
   cd mosaic-ts && pnpm typecheck && pnpm lint && pnpm test
   # Python
   ruff check mosaic tests && python -m pytest -q
   ```
4. **PR**：每个 PR 聚焦单一关注点；描述需包含「改了什么 / 怎么测的 / 已知限制」；尽量保持默认行为向后兼容、新能力以**可选开关 (opt-in)** 引入。

---

## 📜 开源协议与致谢 (License & Acknowledgments)

### License

本项目基于 **[Apache License 2.0](LICENSE)** 开源 —— 可自由使用、修改、分发，须保留版权与许可声明并附带变更说明。
Released under the **[Apache License 2.0](LICENSE)**.

### 致谢 (Acknowledgments)

- 🧬 **[ATLAS](https://github.com/general-intelligence-capital/atlas)** —— 四层多智能体自我改进交易范式的设计源头（JANUS / MiroFish 的公开实现）。
- 🧰 **ETFAgents** —— 混合架构（Python sidecar + TS 前端 + JSON-RPC bridge）的工程经验来源。
- 📊 **[Qlib](https://github.com/microsoft/qlib)** —— 历史数据底座与向量化回测引擎。
- 🔗 **[LangChain](https://github.com/langchain-ai/langchain) / [LangGraph](https://github.com/langchain-ai/langgraph)** —— Agent 编排框架。
- 🇨🇳 **[Tushare](https://tushare.pro/) · [akshare](https://akshare.akfamily.xyz/) · [FRED](https://fred.stlouisfed.org/)** —— A 股与全球宏观数据。

---

<div align="center">
<sub>Built with 🧩 by the MOSAIC contributors · Python sidecar × TypeScript front-end</sub>
</div>
