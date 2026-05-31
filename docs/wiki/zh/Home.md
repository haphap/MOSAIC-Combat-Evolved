# MOSAIC 项目 Wiki

> 🌐 **语言 / Language:** [English](../Home.md) · **中文**

**MOSAIC** 是一个受 ATLAS 启发的 A 股自我改进型多智能体量化交易框架。它采用混合架构:重逻辑(numpy/pandas/git/SQLite/行情数据)留在 **Python sidecar**,编排、LLM、CLI 与 TUI 交给 **TypeScript 前端**,两端通过**行分隔 JSON-RPC over stdio** 通信。

> 本 wiki 由代码生成并与之逐一核对。凡涉及具体事实处均标注源文件路径,便于核验。

## 目录

- [架构 (Architecture)](Architecture.md) — 混合 sidecar/前端 拆分、JSON-RPC 桥、仓库布局。
- [快速上手 (Getting Started)](Getting-Started.md) — 安装(uv + pnpm)、可选 extras、`.env`、首跑。
- [CLI 参考 (CLI Reference)](CLI-Reference.md) — 每个 `pnpm dev <command>` 及其子命令。
- [桥 RPC (Bridge RPC)](Bridge-RPC.md) — 按命名空间列出的完整 `@method` 接口。
- [智能体 (Agents)](Agents.md) — 4 层 25 智能体决策图。
- [数据层 (Data Layer)](Data-Layer.md) — qlib 本地读取、ingest、vendored 采集器、ETF 路由、研报工具。
- [自我改进 (Self-Improvement)](Self-Improvement.md) — Autoresearch / PRISM / JANUS / MiroFish。
- [评分与纸上交易 (Scorecard & Paper Trading)](Scorecard-and-Paper-Trading.md) — 评分、胜率、Darwinian 权重、纸交易引擎。
- [TUI](TUI.md) — 可读可编辑的 Ink 仪表盘及其标签页。
- [配置 (Configuration)](Configuration.md) — `MosaicConfig`、持久化、环境变量覆盖。
- [贡献指南 (Contributing)](Contributing.md) — 分支命名、验证矩阵、PR 约定。

## 一览

| 方面 | 概要 |
| --- | --- |
| 决策图 | 4 层 25 智能体(10 宏观 → 7 行业 → 4 投资哲学 → 4 决策),由 LangGraph.js 编排成单次 daily cycle |
| 自我改进 | Autoresearch 在 git 分支上改写提示词,按 ΔSharpe 决定 keep/revert |
| 多周期 | PRISM 跨 7 个市场 regime cohort 训练;JANUS 跨 cohort 元加权 |
| 反身性模拟 | MiroFish 前向模拟情景(默认 Monte-Carlo,可选 swarm 引擎) |
| 回测/纸交易 | qlib 两段式向量化回测 + 自建纸上交易引擎(T+1、佣金) |
| 行业/个股研报 | 行业 agent 用 Tushare 行业研报、个股级 agent 用个股研报分析 |
| 语言 | Python `≥3.10` sidecar · Node `≥22` + TypeScript 前端 |
| 协议 | Apache-2.0(vendored qlib 采集器依赖仍为 MIT — 见[数据层](Data-Layer.md)) |

## 权威来源

权威设计/阶段文档是仓库根目录的 [`mosaic-tsplan.md`](../../../mosaic-tsplan.md)。README([根](../../../README.md)、[`mosaic-ts`](../../../mosaic-ts/README.md))覆盖快速用法。本 wiki 在二者基础上展开,并保持每条断言可溯源至代码。
