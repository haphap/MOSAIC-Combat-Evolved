# 项目交接文档

> [!WARNING]
> 这是截至 2026-06-16、分支 `rke-recipe-required-data` 的历史交接快照，不是当前分支、
> runtime 或操作状态。当前入口以 [`README.md`](../../README.md) 和
> [`rke_report_intelligence_operations.md`](../runbooks/rke_report_intelligence_operations.md)
> 为准；当前 Agent/prompt 私有边界见
> [`macro-agent-role-contracts-v2-plan.md`](../plans/macro-agent-role-contracts-v2-plan.md)，生产
> prompt/KNOT 资产必须按固定私有 commit/hash fail closed 加载。

更新时间：2026-06-16  
项目目录：`/home/hap/Project/MOSAIC-RKE`  
当前分支：`rke-recipe-required-data`，跟踪 `origin/rke-recipe-required-data`  
当前工作区状态：最近检查为干净；最新本地/远端提交为 `0faf293 Route RKE temp workspace to home tmp`

## 1. 项目基本信息

- 项目名称：MOSAIC-RKE / MOSAIC Report Knowledge Extraction line
- 项目目标：把 A 股多智能体研究框架 MOSAIC 中的研报知识抽取、PIT outcome 评价、人工 gold-set、paper-trading、监控和 prompt/agent 演化闭环做成可审计、shadow-only 的研发线。
- 这个项目最终要解决什么问题：让研报观点不再只靠 LLM 自评，而是被拆成 source-grounded claim、方法、指标和 recipe，再由行业 ETF、个股 qlib 价格、人工 review、schema/audit 和 paper-trading 共同验证，形成可演化但受控的研究资产。
- 当前开发阶段：RKE 主体功能已实现，处于 shadow-only 验证和人工 review gate 阶段；生产 promotion 仍被 gold-set、analytical-footprint 和 lockbox gate 阻断。
- 技术栈：Python、TypeScript、LangGraph、LangChain、JSON-RPC、file-backed JSON/JSONL registry、qlib、Tushare、AKShare、FRED、MinerU、OpenAI-compatible vLLM、Vitest、pytest、ruff、Biome。
- 运行环境：Linux 本地开发环境；Python `>=3.10`；Node `>=22`；Python 依赖用 `uv`；TypeScript 依赖用 `pnpm`；RKE 临时目录使用 `~/tmp/mosaic-rke`。
- 主要依赖：`pandas`、`numpy`、`requests`、`tushare`、`akshare`、`stockstats`、`yfinance`、`pyqlib`、`mineru[core]`、`vllm`、`pytest`、`ruff@0.15.15`、`@langchain/*`、`@langchain/langgraph`、`commander`、`ink`、`vitest`、`biome`。
- 项目所在目录：`/home/hap/Project/MOSAIC-RKE`
- 当前分支或版本状态：`rke-recipe-required-data`；最近推送到远端；工作区最近检查无未提交 tracked 改动。
- 是否有线上部署：没有确认到线上部署；这是本地开发/验证 checkout。
- 是否涉及数据库：没有传统业务数据库；RKE 使用 `registry/` 文件注册表。工具层可选 SQLite cache；MOSAIC-Fish 外部服务可能使用 Neo4j，但不属于本 repo 内置数据库。
- 是否涉及第三方 API：涉及。包括 Tushare、FRED、AKShare、Alpha Vantage、Brave Search、OpenAI-compatible LLM/vLLM endpoint、可选 GitHub/private prompt repo、MOSAIC-Fish 服务。
- 是否涉及敏感配置或密钥：涉及。`.env` 和用户本地环境可能包含 API key、token、LLM key、Tushare token、FRED key、私有 prompt repo 配置等。任何交接、日志、commit、PR 描述中都必须写成 `[REDACTED]`。

## 2. 当前项目进度

### 模块 A：RKE Report Intelligence 主流程
- 状态：已完成主体功能，仍受人工 review gate 阻断。
- 相关文件：
  - `mosaic/rke/report_intelligence.py`
  - `mosaic/rke/cli.py`
  - `registry/report_intelligence/*`
  - `schemas/report_intelligence_*.schema.json`
  - `tests/test_rke_report_intelligence.py`
- 核心逻辑：Tushare/source rows -> PDF/MinerU Markdown -> vLLM extraction -> forecast claims、analytical footprints、metric candidates、method patterns、tool gaps、outcome labels、profiles、recipe、monitor、evolution artifacts。
- 当前问题：私有源和 Markdown/PDF cache 不能提交；当前 promotion 还卡在 gold-set、footprint、lockbox 人工 gate。
- 下一步：先完成当前 gold-set 和 footprint review batch，dry-run/apply 后再跑 schema/status/promotion dry-run。

### 模块 B：个股研报 PIT outcome label
- 状态：已完成并有公开 artifact 证明。
- 相关文件：
  - `mosaic/rke/report_intelligence.py`
  - `registry/report_intelligence/outcome_labeling_readiness.json`
  - `registry/report_intelligence/report_outcome_labels.jsonl`（私有/本地可能存在，不应提交）
  - `tests/test_rke_report_intelligence.py`
  - `docs/plans/rke_stock_report_outcome_and_evolution_plan.md`
  - `docs/plans/rke_stock_report_outcome_and_evolution_status.md`
- 核心逻辑：使用 qlib `cn_data` 的股票复权收盘价，按 T+1 入场、5/20/60/120 交易日窗口生成 `stock_price_proxy` 标签，记录股票收益、benchmark 收益、relative alpha、after-cost alpha 和 directional hit。
- 当前问题：全市场 qlib 数据完整性和 survivorship/delisting 仍需持续审计；停牌、涨跌停、退市和流动性 gap 不能伪造 label。
- 下一步：继续保持 readiness gap，不要为了覆盖率强行生成标签。

### 模块 C：行业 ETF proxy outcome label
- 状态：已完成并和个股 label 分层共存。
- 相关文件：
  - `registry/report_intelligence/industry_etf_proxy_map.jsonl`
  - `registry/report_intelligence/industry_etf_proxy_pit_availability.json`
  - `registry/report_intelligence/outcome_labeling_readiness.json`
  - `tests/test_rke_schema_artifacts.py`
- 核心逻辑：行业观点映射到 PIT 可用 ETF，使用 T+1 entry 和多窗口 ETF return 评价。工业金属映射为 `SH560860`。
- 当前问题：仍有未映射行业和 PIT 不可用 mapping，作为 action watchlist 暴露。
- 下一步：只在有 PIT 可用 ETF 和明确行业口径时扩展映射。

### 模块 D：prompt/agent 演化闭环
- 状态：部分完成，仍不可 promotion。
- 相关文件：
  - `registry/report_intelligence/evolution_readiness_gate.json`
  - `registry/report_intelligence/prompt_mutation_candidates.jsonl`
  - `registry/report_intelligence/recipe_paper_trading_runs.jsonl`
  - `registry/report_intelligence/recipe_paper_trading_summary.json`
  - `registry/report_intelligence/confidence_impact_monitor.json`
  - `mosaic/rke/report_intelligence.py`
  - `mosaic/rke/schema_validation.py`
- 核心逻辑：用 gold-set、PIT outcome、paper-trading、monitor、schema/audit failure、tool gaps 生成 shadow-only prompt mutation candidates。演化不直接改 production prompt。
- 当前问题：`schema-status` 仍失败；人工 gold-set/footprint 质量 gate 未过；lockbox 未打开。
- 下一步：先过人工 gate，再评估 mutation candidates。

### 模块 E：人工 review gate
- 状态：开发完成，实际人工 review 未完成。
- 相关文件：
  - `mosaic/rke/manual_review_batches.py`
  - `mosaic/rke/manual_review_import.py`
  - `mosaic/rke/review_progress.py`
  - `mosaic/rke/review_gates.py`
  - `registry/review_batches/manual_review_progress_report.json`
  - `registry/review_batches/manual_review_runbook.md`
  - `registry/review_batches/gold_set_reviewed.jsonl`（本地私有工作文件，不提交）
  - `registry/report_intelligence/analytical_footprint_review_batch.jsonl`（本地私有工作文件，不提交）
- 核心逻辑：prepare -> reviewer fills sparse import -> dry-run -> apply -> rerun progress。review aids/evidence 不是 import 文件。
- 当前问题：gold-set 当前 scratch 26 行全部待填；gold target 总待审 47 行；footprint 当前 batch 50 行待填，总待审 1017 行；source-license 已 applied；lockbox 等前置 gate。
- 下一步：人工审核当前 gold 26 行和 footprint 50 行，dry-run/apply，再循环到剩余 batch。

### 模块 F：Python/TS bridge 和 agent 前端
- 状态：已有可用框架，不是当前 RKE blocker。
- 相关文件：
  - `mosaic/bridge/server.py`
  - `mosaic/bridge/registry.py`
  - `mosaic/bridge/handlers/*.py`
  - `mosaic-ts/src/bridge/*`
  - `mosaic-ts/src/cli/index.ts`
  - `mosaic-ts/src/graph/*.ts`
  - `mosaic-ts/src/agents/**`
- 核心逻辑：TS CLI/TUI 通过 stdio JSON-RPC 调 Python sidecar；Python handler 用 `@method("namespace.action")` 注册。
- 当前问题：RKE CLI 不走 TS bridge；不要把 RKE 手工 gate 和 TS daily-cycle 混在一起。
- 下一步：RKE 目标优先处理 `mosaic-rke` CLI。

### 模块 G：MinerU/vLLM 研报转换和抽取
- 状态：本地环境已有配置记录；不要重复安装。
- 相关文件：
  - `docs/runbooks/rke_report_intelligence_operations.md`
  - `mosaic/rke/report_intelligence.py`
  - `.env`（本地，含敏感配置，不提交）
  - `.mosaic/rke/report_intelligence/*`（本地 cache，不提交）
- 核心逻辑：PDF -> MinerU Markdown -> OpenAI-compatible local vLLM/LLM extraction。
- 当前问题：vLLM/Docker 服务可能未启动；需要时再启动。不要把 PDF/Markdown/cache 提交。
- 下一步：需要 LLM 抽取时先检查 Docker 容器和 endpoint。

### 已验证可用
- `operator-readiness --root . --no-write` 最近通过 18/18。
- `schema-status --root . --failures-only --no-write` 最近按预期失败 23 项，失败集中在人工 review/patch v1.5 gate。
- `review-progress --root . --summary --no-write` 最近显示 4 个 gate，source-license ready，gold/footprint/lockbox blocked。
- 最近针对 temp 迁移的 focused pytest 39 个通过；ruff、prompt leak guard、`git diff --check` 也通过。

### 只是写了代码但还没完全验证/推广
- prompt mutation candidates 是 shadow-only，不能当 production prompt。
- gold-set 和 footprint review aid 有建议字段，但不能自动填人工字段。
- 个股和行业 outcome label 是 shadow-only，不能直接进入生产交易决策。

### 写到一半或需要人工继续
- gold-set 当前 26 行人工 review。
- footprint 当前 50 行人工 review，后续还有多批。
- lockbox 必须等 gold-set 和 footprint gate 完成后再打开。

### 已废弃或不要重复尝试
- 不要使用 LLM 判断研报对错；LLM 只抽取观点/机制/方向/方法。
- 不要用报告当日收盘生成 T+0 label；必须 T+1。
- 不要把 `.OF`、货币基金、LOF/ETF/指数混进 `cn_data` 股票口径。
- 不要把私有 Tushare 全文、PDF、Markdown、review import 提交到 git。
- 不要重复安装 MinerU；先按 runbook 检查现有环境。
- 不要把 pytest basetemp 放 `/tmp/pytest-*`；使用 `~/tmp/mosaic-rke`。
- 不要为了绕过手工 gate 直接改 public summary 或 schema 让它通过。

## 3. 文件结构说明

- `pyproject.toml`
  - 作用：Python 包配置、依赖 extras、`mosaic-rke` CLI entry point、pytest/ruff 配置。
  - 当前状态：可用；`mosaic-rke = "mosaic.rke.cli:main"`。
  - 里面最重要的函数/类：无函数；重要配置是 `[project.scripts]` 和 optional dependencies。
  - 新 AI 修改时要注意什么：不要随意把 heavy deps 放入默认 dependencies；MinerU/vLLM 保持在 `report-intelligence` extra。

- `.env`
  - 作用：本地私有运行配置。
  - 当前状态：存在；含敏感值，不能输出真实值，不能提交。
  - 里面最重要的配置：`MOSAIC_RKE_VLLM_BASE_URL`、`MOSAIC_RKE_VLLM_MODEL`、`MOSAIC_VLLM_API_KEY`、`MOSAIC_RKE_TMPDIR`、`TMPDIR`。
  - 新 AI 修改时要注意什么：只写本地，所有 key/token/password 输出都写 `[REDACTED]`。

- `.env.example`
  - 作用：公开环境变量模板。
  - 当前状态：可用。
  - 里面最重要的配置：LLM keys、Tushare/FRED keys、MiroFish URL、qlib path、prompt repo、china-policy-db、agent data cache。
  - 新 AI 修改时要注意什么：示例不得包含真实 secret。

- `CLAUDE.md`
  - 作用：仓库架构和开发规则总览。
  - 当前状态：可用。
  - 里面最重要的内容：三大子系统、RKE file registry、CI/verification 命令、private boundary。
  - 新 AI 修改时要注意什么：大改前先读。

- `AGENTS.md`
  - 作用：本地 agent 工作规则。
  - 当前状态：被 `.gitignore` 忽略；最近已加入 Think Before Coding / Simplicity / Surgical Changes / Goal-Driven Execution。
  - 新 AI 修改时要注意什么：这是本地协作指令，不会出现在 git diff。

- `mosaic/rke/cli.py`
  - 作用：`mosaic-rke` CLI 入口和子命令路由。
  - 当前状态：RKE 操作主入口。
  - 里面最重要的函数/类：`main()` 及各 subcommand wiring。
  - 新 AI 修改时要注意什么：新增 artifact 时要把 build/write/status 命令接进 CLI，并保持 dry-run 语义。

- `mosaic/rke/report_intelligence.py`
  - 作用：Report Intelligence 主业务逻辑。
  - 当前状态：当前最关键、最大、风险最高文件。
  - 里面最重要的函数/类：report source fetch/normalize、MinerU conversion、LLM extraction、stock/industry/macro outcome label builders、profiles、recipes、paper-trading、monitor、evolution artifacts、refresh orchestration。
  - 新 AI 修改时要注意什么：严格保护 PIT、private output boundary、shadow-only、`--refresh-derived-only` 不覆盖公开 artifact 的约束。

- `mosaic/rke/schema_validation.py`
  - 作用：JSON/JSONL schema 和语义 contract 校验。
  - 当前状态：CI 和 gate 的关键防线。
  - 里面最重要的函数/类：各 `_validate_*` semantic validator 和 schema-status 聚合。
  - 新 AI 修改时要注意什么：不要只改 schema 不改语义测试；新增字段要有正反测试。

- `mosaic/rke/manual_review_batches.py`
  - 作用：gold/source-license/footprint/lockbox 手工 review batch、assist、evidence、runbook 生成。
  - 当前状态：当前人工 gate 的主要入口。
  - 里面最重要的函数/类：`build_gold_review_evidence()`、`write_gold_review_starter()`、`build_manual_review_batch_status()`、footprint review helpers。
  - 新 AI 修改时要注意什么：review aid 不是 import；不要自动填人工决策字段。

- `mosaic/rke/manual_review_import.py`
  - 作用：gold-set reviewed import 的校验和 dry-run/apply。
  - 当前状态：可用。
  - 里面最重要的函数/类：`apply_gold_set_review_import()`、manual field guards。
  - 新 AI 修改时要注意什么：不要手工绕过 target hash 和 forbidden-field 校验。

- `mosaic/rke/review_progress.py`
  - 作用：汇总当前 manual review gate 进度和下一步命令。
  - 当前状态：可用；当前显示 gold/footprint/lockbox 阻塞。
  - 新 AI 修改时要注意什么：输出必须 public-safe，不含研报正文。

- `mosaic/rke/operator_readiness.py`
  - 作用：检查 operator handoff、manual templates、blank import rejection、promotion gate consistency。
  - 当前状态：最近 `--no-write` 18/18 通过。
  - 新 AI 修改时要注意什么：dry-run root 使用 `~/tmp/mosaic-rke`，不要复制私有大文件。

- `mosaic/rke/temp_paths.py`
  - 作用：RKE 临时目录和命令前缀。
  - 当前状态：默认 `~/tmp/mosaic-rke`。
  - 新 AI 修改时要注意什么：不要回退到 `/tmp` 或 tracked repo 目录。

- `mosaic/rke/registry_manifest.py`
  - 作用：声明 public/private registry boundary。
  - 当前状态：测试会保护 private ignore 规则。
  - 新 AI 修改时要注意什么：任何含 source prose、claim text、reviewer text、license-gated data 的新 artifact 默认 private。

- `mosaic/bridge/server.py`
  - 作用：Python JSON-RPC bridge server。
  - 当前状态：用于 TS 前端，不用于 RKE CLI。
  - 里面最重要的函数/类：bridge server loop。
  - 新 AI 修改时要注意什么：不要跨 bridge 传 DataFrame。

- `mosaic/bridge/handlers/*.py`
  - 作用：Python bridge handlers。
  - 当前状态：多模块已接入。
  - 里面最重要的函数/类：`@method("namespace.action")` decorated handlers。
  - 新 AI 修改时要注意什么：新增 TS 调用前先稳定 Python contract。

- `mosaic/dataflows/*.py`
  - 作用：Tushare、FRED、AKShare、PBOC、gov.cn/china-policy-db、qlib、本地数据工具。
  - 当前状态：多个工具已接入；Tushare 优先，FRED 用于 Tushare 没有或不适合的变量。
  - 新 AI 修改时要注意什么：网络/API 失败要有 fallback；日志脱敏。

- `mosaic-ts/package.json`
  - 作用：TypeScript CLI/TUI 依赖和脚本。
  - 当前状态：Node `>=22`，pnpm。
  - 里面最重要的脚本：`dev`、`build`、`typecheck`、`lint`、`test`。
  - 新 AI 修改时要注意什么：使用 Biome，不要引入 eslint/prettier 风格。

- `mosaic-ts/src/cli/index.ts`
  - 作用：TS CLI 入口。
  - 当前状态：可用。
  - 新 AI 修改时要注意什么：TS CLI 会加载 `.env`；不要把 RKE CLI 硬塞进 TS bridge。

- `mosaic-ts/src/graph/*.ts`
  - 作用：4 层 agent graph 和 daily-cycle。
  - 当前状态：已有 agent layer 实现。
  - 新 AI 修改时要注意什么：用户之前要求 agents 串行逐一运行；不要轻易恢复多层全并行。

- `mosaic-ts/src/agents/prompts/loader.ts`
  - 作用：prompt source 加载，支持 bundled prompts 和 private repo/root override。
  - 当前状态：PR 已合并过相关逻辑。
  - 新 AI 修改时要注意什么：默认 bundled prompts；配置 private repo 后优先 private repo。

- `registry/`
  - 作用：RKE file-backed artifact registry。
  - 当前状态：public artifacts 已提交；private artifacts 本地存在但 gitignored。
  - 新 AI 修改时要注意什么：提交前必须 `git diff -- registry`，只提交任务需要的公开 artifact。

- `registry/report_intelligence/extraction_report.json`
  - 作用：公开安全抽取总览。
  - 当前状态：记录 341 forecast claims、336 outcome labels 等聚合证据。
  - 新 AI 修改时要注意什么：不能加入 claim text/source span 原文。

- `registry/review_batches/manual_review_progress_report.json`
  - 作用：人工 review gate 进度。
  - 当前状态：gold、footprint、lockbox 未完成；source-license 已完成。
  - 新 AI 修改时要注意什么：这是公开摘要，不等于可以跳过私有 import。

- `registry/handoffs/rke_operator_handoff.json` / `.md`
  - 作用：operator 执行顺序和交接命令。
  - 当前状态：semantic validation 通过。
  - 新 AI 修改时要注意什么：命令必须带 `MOSAIC_RKE_TMPDIR` 和 `TMPDIR` 前缀。

- `registry/promotion/*.json`
  - 作用：promotion dry-run 和 production gate 状态。
  - 当前状态：仍为 paper-trading / blocked。
  - 新 AI 修改时要注意什么：不要直接改成 production。

- `schemas/`
  - 作用：registry artifact 的 JSON schema 和 semantic contract 入口。
  - 当前状态：大量 RKE contract 已覆盖。
  - 新 AI 修改时要注意什么：新增 artifact 必须同步 schema、semantic validation、测试。

- `tests/test_rke_report_intelligence.py`
  - 作用：Report Intelligence 核心测试。
  - 当前状态：覆盖 stock/industry outcome、PIT、readiness、derived refresh 等。
  - 新 AI 修改时要注意什么：RKE 测试用 `--basetemp ~/tmp/mosaic-rke/...`。

- `tests/test_rke_schema_artifacts.py`
  - 作用：当前 public registry artifact contract 测试。
  - 当前状态：非常关键。
  - 新 AI 修改时要注意什么：如果刷新 public artifact，通常要跑相关 contract 测试。

- `tests/conftest.py`
  - 作用：测试 fixture、临时目录、私有 registry overlay。
  - 当前状态：默认 temp root 指向 `~/tmp/mosaic-rke`。
  - 新 AI 修改时要注意什么：不要让 pytest 写 `/home/hap` 根目录或系统 `/tmp`。

- `.github/workflows/ci.yml`
  - 作用：CI 配置。
  - 当前状态：未在本次交接中重新读取；根据 `CLAUDE.md`，CI 分 Python/TS/prompt leak/RKE tests。
  - 新 AI 修改时要注意什么：如果 CI 失败，先用 `gh run`/logs 查具体 job。

## 4. 核心逻辑说明

MOSAIC 有三条主线：

1. TypeScript agent graph：用户运行 `pnpm dev daily-cycle ...` 后，TS CLI 组织 4 层 agent 流程，并通过 bridge 调 Python 数据/工具。
2. Python bridge：TS 通过 stdio JSON-RPC 调 `mosaic.bridge`，Python handlers 返回 JSON。这里不传 DataFrame。
3. RKE CLI：用户直接运行 `uv run mosaic-rke ...`。RKE 不走 TS bridge，而是读写 `registry/` 里的文件 artifact。

RKE Report Intelligence 的核心流程是：

1. 获取或合并研报 source rows。
2. 下载 PDF，使用 MinerU 转 Markdown。
3. 通过本地 OpenAI-compatible vLLM/LLM 从原文抽取 forecast claims、机制、方法、指标、footprints。
4. 系统使用非 LLM 数据生成 outcome label：行业用 ETF proxy，个股用 qlib `cn_data` 股票价格，宏观资产用对应 proxy。
5. 用 outcome label 生成 source/viewpoint/method performance profile。
6. 从 footprints 和 outcome 生成 analysis recipe，并做 shadow paper-trading。
7. 监控 confidence impact、alpha decay、calibration drift。
8. 生成 shadow-only prompt mutation candidates。
9. 所有结果经过 schema-status、PIT/provenance/statistical/runtime audit、manual review、promotion dry-run 和 lockbox 才能往前走。

容易出 bug 的地方：

- PIT 时间：不能用报告当天收盘，entry 必须在 signal date 之后。
- qlib 股票/ETF calendar：股票在 `cn_data`，ETF 在 `cn_etf`，跨目录 benchmark 必须按 date 对齐。
- 普通股票代码口径：SZ 00/30、SH 60/68、BJ 92；不要混入基金、LOF、ETF、指数。
- 停牌/涨跌停/退市：不能当成可交易价格硬生成 label。
- 私有边界：source prose、abstract、claim_text、source_span_ids、reviewer notes、Tushare 全文不能进入 public artifact。
- 手工 review import：必须 preserve `claim_id`、`target_row_hash`、`review_context_ref` 等字段，dry-run 通过后再 apply。
- LLM 抽取质量：之前出现过 claim 太碎、风险提示/免责声明/评级被抽为 claim、变量 mapping 错、direction 错、semiconductor_storage_cycle 过度泛化等问题。

为什么这样设计：

- LLM 擅长抽取和压缩文本，但不应该判断观点是否正确。
- 市场反馈必须 PIT，避免未来数据泄露。
- 研报全文和 Tushare 数据有私有/授权边界，公开 repo 只能保存聚合、安全、可再校验的 artifact。
- promotion 需要人工 gate 和 lockbox，避免 prompt 演化把噪声或过拟合带进生产。

临时方案或技术债：

- gold-set 和 footprint review 仍需要大量人工审核。
- review evidence 对 `target_correct`、`horizon_correct`、`variable_mapping_correct` 的建议还偏保守，后续可增强，但不能自动填人工字段。
- 个股 survivorship/delisting 审计仍以 readiness gap 形式存在。
- prompt mutation candidates 已生成，但未通过 promotion gate。

## 5. 环境变量与配置

本地存在 `.env`，但不能输出真实值。当前只确认到以下键名：

- `MOSAIC_VLLM_API_KEY`
  - 用途：本地/兼容 LLM endpoint 的 API key。
  - 是否必填：需要 LLM 抽取时必填；跳过 LLM 时可不需要。
  - 示例值：`[REDACTED]`
  - 缺失会导致什么问题：需要 LLM 的 report-intelligence 步骤失败或无法认证。

- `MOSAIC_RKE_VLLM_BASE_URL`
  - 用途：RKE vLLM/OpenAI-compatible base URL。
  - 是否必填：需要 LLM 抽取时必填。
  - 示例值：`http://127.0.0.1:8020/v1` 或 `https://provider.example/v1`
  - 缺失会导致什么问题：LLM extraction 无法连接。

- `MOSAIC_RKE_VLLM_MODEL`
  - 用途：RKE extraction 使用的模型名。
  - 是否必填：需要 LLM 抽取时必填或使用默认。
  - 示例值：`model-name`
  - 缺失会导致什么问题：可能走默认模型或报模型缺失。

- `MOSAIC_RKE_TMPDIR`
  - 用途：RKE CLI、operator dry-run、pytest 的临时根目录。
  - 是否必填：强烈建议设置。
  - 示例值：`/home/hap/tmp/mosaic-rke`
  - 缺失会导致什么问题：默认仍应指向 `~/tmp/mosaic-rke`，但显式设置可避免写系统 `/tmp`。

- `TMPDIR`
  - 用途：Python/pytest/uv 子进程临时目录。
  - 是否必填：强烈建议设置。
  - 示例值：`/home/hap/tmp/mosaic-rke`
  - 缺失会导致什么问题：部分工具可能回退到 `/tmp`。

`.env.example` 还声明了这些常用配置：

- `ANTHROPIC_API_KEY` / `DEEPSEEK_API_KEY` / `OPENAI_API_KEY` / `GOOGLE_API_KEY` / `OPENROUTER_API_KEY` / `XAI_API_KEY`
  - 用途：不同 LLM provider 的 API key。
  - 是否必填：只在使用对应 provider 时必填。
  - 示例值：`[REDACTED]`
  - 缺失会导致什么问题：对应 provider 不可用。

- `TUSHARE_TOKEN`
  - 用途：Tushare 数据接口。
  - 是否必填：需要 Tushare 数据时必填。
  - 示例值：`[REDACTED]`
  - 缺失会导致什么问题：研报、股票/ETF/宏观数据获取失败。

- `FRED_API_KEY`
  - 用途：FRED 数据接口。
  - 是否必填：需要 FRED 数据时必填。
  - 示例值：`[REDACTED]`
  - 缺失会导致什么问题：FRED-only 指标不可用，例如部分美元指数类数据。

- `BRAVE_SEARCH_API_KEY` / `ALPHA_VANTAGE_API_KEY`
  - 用途：外部搜索和 Alpha Vantage 数据。
  - 是否必填：对应工具使用时必填。
  - 示例值：`[REDACTED]`
  - 缺失会导致什么问题：对应工具失败或 fallback。

- `MOSAIC_MIROFISH_URL`
  - 用途：MOSAIC-Fish/OASIS 后端地址。
  - 是否必填：使用 real MiroFish engine 时必填。
  - 示例值：`http://localhost:5001`
  - 缺失会导致什么问题：MiroFish real engine 连接失败。

- `MOSAIC_MIROFISH_LLM_BASE_URL` / `MOSAIC_MIROFISH_LLM_API_KEY` / `MOSAIC_MIROFISH_LLM_MODEL`
  - 用途：MOSAIC-Fish LLM provider。
  - 是否必填：使用 MOSAIC-Fish LLM 时必填。
  - 示例值：`[REDACTED]`
  - 缺失会导致什么问题：MOSAIC-Fish LLM 调用失败。

- `MOSAIC_MIROFISH_EMBEDDING_BASE_URL` / `MOSAIC_MIROFISH_EMBEDDING_API_KEY` / `MOSAIC_MIROFISH_EMBEDDING_MODEL`
  - 用途：MOSAIC-Fish embedding provider。
  - 是否必填：使用 embedding/检索时必填。
  - 示例值：`[REDACTED]`
  - 缺失会导致什么问题：embedding 检索失败。

- `QLIB_CN_DATA_PATH` / `QLIB_CN_ETF_PATH`
  - 用途：qlib 股票和 ETF 数据路径。
  - 是否必填：可选；默认使用 `~/.qlib/qlib_data/cn_data` 和 `~/.qlib/qlib_data/cn_etf`。
  - 示例值：`/home/user/.qlib/qlib_data/cn_data`
  - 缺失会导致什么问题：如果默认路径不存在，stock/ETF outcome readiness 失败。

- `MOSAIC_PROMPTS_REPO` / `MOSAIC_PROMPTS_ROOT` / `MOSAIC_PROMPTS_REPO_ID`
  - 用途：配置 private prompt repo/root。
  - 是否必填：可选；默认使用本 repo bundled prompts。
  - 示例值：`/path/to/local/MOSAIC-Prompts`
  - 缺失会导致什么问题：回退到 bundled prompts。

- `MOSAIC_CHINA_POLICY_DB_DIR` / `MOSAIC_CHINA_POLICY_DB_REPO_URL` / `MOSAIC_CHINA_POLICY_DB_AUTO_SYNC` / `MOSAIC_CHINA_POLICY_DB_GIT_STALE_HOURS` / `MOSAIC_CHINA_POLICY_DB_PUSH_UPDATES`
  - 用途：中国政策数据库本地优先和增量同步。
  - 是否必填：可选；未配置时可自动 clone/cache，旧 PBOC/gov.cn crawler 是 fallback。
  - 示例值：`/path/to/china-policy-db`
  - 缺失会导致什么问题：政策工具可能需要网络 clone 或走 fallback。

- `MOSAIC_AGENT_DATA_CACHE_*`
  - 用途：agent data exact-call SQLite cache。
  - 是否必填：可选。
  - 示例值：`MOSAIC_AGENT_DATA_CACHE_ENABLED=1`
  - 缺失会导致什么问题：使用默认 cache 或禁用相关优化。

配置文件检查：

- `.env`：存在，本地私有，含敏感值。
- `.env.example`：存在，公开模板。
- `pyproject.toml`：Python 包和 CLI 配置。
- `mosaic-ts/package.json`：TS CLI 配置。
- `CLAUDE.md` / `AGENTS.md`：开发和 agent 指令。
- 数据库连接配置：repo 内没有生产 DB 连接；MOSAIC-Fish 可能外接 Neo4j。
- API 配置：环境变量驱动。
- 代理配置：未确认专门代理配置。
- 部署配置：未确认线上部署配置。

## 6. 启动、运行、测试方式

### Python/RKE 安装

```bash
uv venv
uv pip install -e '.[data,trading,test]'
```

状态：未在本次交接中重新执行；这是 repo 标准命令。

需要完整 PDF/MinerU/vLLM 时：

```bash
uv pip install -e '.[data,trading,test,report-intelligence]'
```

状态：未在本次交接中重新执行；不要先重装 MinerU，先看 runbook 和现有环境。

### RKE 常用命令

```bash
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke \
TMPDIR=/home/hap/tmp/mosaic-rke \
UV_CACHE_DIR=/home/hap/tmp/mosaic-rke/uv-cache \
uv run mosaic-rke review-progress --root . --summary --no-write
```

状态：已验证；当前 exit code 为 2，表示 manual review gate 未完成，不是命令错误。

```bash
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke \
TMPDIR=/home/hap/tmp/mosaic-rke \
UV_CACHE_DIR=/home/hap/tmp/mosaic-rke/uv-cache \
uv run mosaic-rke operator-readiness --root . --no-write
```

状态：已验证；当前 18/18 通过。

```bash
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke \
TMPDIR=/home/hap/tmp/mosaic-rke \
UV_CACHE_DIR=/home/hap/tmp/mosaic-rke/uv-cache \
uv run mosaic-rke schema-status --root . --failures-only --no-write
```

状态：已验证；当前 exit code 为 2，23 个预期失败，集中在人工 review 和 patch v1.5 coverage gate。

### RKE 手工 review dry-run

Gold-set 当前 batch：

```bash
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke \
TMPDIR=/home/hap/tmp/mosaic-rke \
uv run mosaic-rke apply-gold-review --root . \
  --input registry/review_batches/gold_set_reviewed.jsonl --dry-run
```

状态：当前不应直接跑通过；需要先填 26 行人工字段。

Footprint 当前 batch：

```bash
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke \
TMPDIR=/home/hap/tmp/mosaic-rke \
uv run mosaic-rke apply-footprint-review --root . \
  --input registry/report_intelligence/analytical_footprint_review_batch.jsonl --dry-run
```

状态：当前不应直接跑通过；需要先填 50 行人工字段。

### Python 测试

```bash
uvx ruff@0.15.15 check mosaic tests
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke \
TMPDIR=/home/hap/tmp/mosaic-rke \
uv run python -m pytest tests/test_rke_report_intelligence.py -q \
  --basetemp /home/hap/tmp/mosaic-rke/pytest-rke-ri
MOSAIC_RKE_TMPDIR=/home/hap/tmp/mosaic-rke \
TMPDIR=/home/hap/tmp/mosaic-rke \
uv run python scripts/check_prompt_leaks.py
git diff --check
```

状态：ruff、prompt leak guard、`git diff --check` 和 focused tests 最近验证通过；全量测试未在本次交接中重新跑。

### TypeScript 安装和运行

```bash
cd mosaic-ts
pnpm install --frozen-lockfile
pnpm typecheck
pnpm lint
pnpm test
```

状态：未在本次交接中重新执行；这是 repo 标准检查。`--fake-llm` 现在必须先按
`docs/wiki/zh/CLI-Reference.md` 生成 fresh、hash-bound 的 synthetic PIT bundle，
并在同一 shell 导出生成器输出；它不会调用真实 LLM，也不会回退到 live 或 stale 数据。

### Python bridge

```bash
uv run python -m mosaic.bridge
```

状态：未在本次交接中重新执行。TS CLI 通常会自动 spawn bridge。

### MinerU/vLLM

检查本地 Docker vLLM：

```bash
docker ps
docker start rke-vllm-qwen36-27b-160k-20260610
docker logs rke-vllm-qwen36-27b-160k-20260610
```

状态：未在本次交接中重新执行。需要 LLM 抽取时再启动，用户之前要求可以先暂停 vLLM，使用 Docker 命令操作。

### 数据库启动方式

repo 内没有必须启动的数据库。MOSAIC-Fish real engine 可能需要它自己的 Flask/Neo4j 服务，目录在 `~/Project/MOSAIC-Fish`，但不属于本 repo 的启动步骤。

### 构建命令

```bash
cd mosaic-ts
pnpm build
```

状态：未在本次交接中重新执行。

### 部署命令

未确认线上部署；当前不应做生产部署。

### 常见启动失败原因

- `uv` 写 `/home/hap/.cache/uv` 被沙箱拦截：设置 `UV_CACHE_DIR=/home/hap/tmp/mosaic-rke/uv-cache`。
- 系统 `/tmp` 空间不足：设置 `MOSAIC_RKE_TMPDIR` 和 `TMPDIR` 到 `/home/hap/tmp/mosaic-rke`。
- 缺少 Tushare/FRED/LLM key：检查 `.env`，但不要输出真实值。
- vLLM 连接拒绝：检查 Docker 容器是否启动、端口是否为 8020、base URL 是否 `/v1`。
- qlib 数据缺失：检查 `~/.qlib/qlib_data/cn_data` 和 `~/.qlib/qlib_data/cn_etf`。
- npm global install EACCES：不要用全局安装绕权限；优先项目内 pnpm/uv，必要时用用户级 prefix。
- CI schema-status 失败：先判断是否是预期 manual gate，不能直接改 schema 放行。

## 7. 已知问题与坑

### 问题：`schema-status` 当前失败 23 项
- 表现：`mosaic-rke schema-status --failures-only --no-write` exit code 2。
- 可能原因：gold-set 质量指标、analytical-footprint review、patch v1.5 Phase B/D 还没过人工 gate。
- 已尝试方案：生成 review progress、operator handoff、manual review aids。
- 有效方案：完成真实人工 review import，dry-run/apply 后重新跑 schema。
- 无效方案：直接改 public summary 或 schema 让它通过。
- 相关文件：`registry/gold_sets/tushare_research_reports.review_summary.json`、`registry/report_intelligence/analytical_footprint_review_summary.json`、`registry/report_intelligence/patch_v1_5_coverage_report.json`
- 新 AI 下一步该怎么查：先跑 `review-progress --summary --no-write`，再看当前 batch。

### 问题：gold-set 当前 26 行待人工审核
- 表现：`registry/review_batches/gold_set_reviewed.jsonl` 26 行缺 `manual_claim_text` 和 bool fields。
- 可能原因：当前 batch 是 sparse import 模板，必须人工填。
- 已尝试方案：生成 evidence/assist/workbook，前 5 条曾输出建议但未获最终确认写入。
- 有效方案：逐条人工确认，填入 import，dry-run，通过后 apply。
- 无效方案：让 LLM 自动填并直接 apply。
- 相关文件：`registry/review_batches/gold_set_reviewed.jsonl`、`registry/review_batches/gold_set_review_evidence.jsonl`
- 新 AI 下一步该怎么查：读取 private evidence，按 5 条一组给用户审，不要擅自写入。

### 问题：footprint 当前 50 行 batch 待人工审核，总待审 1017 行
- 表现：`analytical_footprint_review_batch.jsonl` 缺 7 类 required fields。
- 可能原因：footprint 需要人工确认 metric mapping、步骤、unknown 使用、无私有文本泄漏。
- 已尝试方案：生成 assist/evidence。
- 有效方案：填当前 50 行，dry-run/apply，然后 rerun review-progress 准备下一批。
- 无效方案：直接使用 promotion input 代替 transient batch input。
- 相关文件：`registry/report_intelligence/analytical_footprint_review_batch.jsonl`、`registry/report_intelligence/analytical_footprint_reviewed.jsonl`
- 新 AI 下一步该怎么查：看 `manual_review_progress_report.json` 的 footprint action。

### 问题：lockbox 不能现在打开
- 表现：`lockbox_reviewed.json` 仍缺 required fields，且 blocked by gold_set/footprint_review。
- 可能原因：lockbox 设计上必须等待上游 manual gates。
- 已尝试方案：operator-readiness 验证 blank lockbox 被拒绝，上游 guard 生效。
- 有效方案：等 gold-set 和 footprint 完成后再 prepare/apply lockbox。
- 无效方案：提前填 lockbox 或直接改 promotion gate。
- 相关文件：`registry/review_batches/lockbox_reviewed.json`、`mosaic/rke/lockbox_review_import.py`
- 新 AI 下一步该怎么查：`review-progress --review-kind lockbox`。

### 问题：review aid 不是 import 文件
- 表现：`gold_set_review_evidence.jsonl`、`*_assist.jsonl` 里有建议，但 apply 会拒绝。
- 可能原因：这些文件含 evidence-only fields，例如 `evidence_kind`。
- 已尝试方案：测试已覆盖 evidence import 被拒绝。
- 有效方案：把人工确认后的值写入对应 reviewed import。
- 无效方案：直接 apply evidence/assist。
- 相关文件：`mosaic/rke/manual_review_batches.py`、`tests/test_rke_manual_review_batches.py`
- 新 AI 下一步该怎么查：查看 `reviewed_import_path` 和 `manual_input_path`。

### 问题：私有/授权数据不能进入 git 历史
- 表现：早期 PR 曾出现大文件/私有 Tushare artifact 进入 history，后来已重写修复。
- 可能原因：误 add `registry/sources/tushare_research_reports*` 或 `registry/report_intelligence/*.jsonl`。
- 已尝试方案：`.gitignore`、manifest private boundary、prompt leak guard、history checks。
- 有效方案：提交前 `git status --short --ignored=matching` 和 `git check-ignore`。
- 无效方案：先提交再删除；history 仍可恢复。
- 相关文件：`.gitignore`、`mosaic/rke/registry_manifest.py`、`mosaic/rke/report_intelligence.py`
- 新 AI 下一步该怎么查：`git diff --cached --name-only`，确认没有 private paths。

### 问题：`/tmp` 空间曾被测试/缓存填满
- 表现：用户要求清理 `/tmp` 并更换目录。
- 可能原因：pytest basetemp、uv/cache、operator dry-run registry copy 进入系统 `/tmp`。
- 已尝试方案：清理 `/tmp`；默认 temp root 改到 `~/tmp/mosaic-rke`。
- 有效方案：所有 RKE/pytest 命令加 `MOSAIC_RKE_TMPDIR`、`TMPDIR`、必要时 `UV_CACHE_DIR`。
- 无效方案：反复清理 pytest basetemp 而不改默认路径。
- 相关文件：`mosaic/rke/temp_paths.py`、`tests/conftest.py`、`pyproject.toml`
- 新 AI 下一步该怎么查：`du -sh /tmp /home/hap/tmp/mosaic-rke`。

### 问题：MinerU/vLLM 不要重复安装
- 表现：用户多次指出“之前已经安装过 MinerU，为什么又装一遍”。
- 可能原因：新 agent 未读 runbook 和本地记录。
- 已尝试方案：把 MinerU/vLLM 用法写入 runbook 和 AGENTS。
- 有效方案：先检查 `.venv/bin/mineru`、Docker 容器、runbook。
- 无效方案：直接 `uv pip install mineru` 或新建 vLLM 服务。
- 相关文件：`docs/runbooks/rke_report_intelligence_operations.md`、`AGENTS.md`
- 新 AI 下一步该怎么查：先读 runbook 的 MinerU/vLLM 章节。

### 问题：LLM 抽取 claim 质量不稳定
- 表现：风险提示/免责声明/评级被抽取、claim 过碎、缺少上下文机制、direction 错、变量过度映射。
- 可能原因：prompt/规则对“机制、regime、行业周期、公司禀赋”的约束不够。
- 已尝试方案：过滤风险提示/免责声明/评级；gold candidate 清理；人工 review 指导。
- 有效方案：先完成现有人工 review，再用 gold error taxonomy 反推 prompt mutation。
- 无效方案：直接让 LLM 自评正确性。
- 相关文件：`mosaic/rke/gold_candidate_claims.py`、`mosaic/rke/claim_text_filters.py`、`registry/report_intelligence/prompt_mutation_candidates.jsonl`
- 新 AI 下一步该怎么查：看 gold-set review failures 和 prompt mutation candidate。

### 问题：qlib 数据完整性和 code universe
- 表现：曾发现大量股票只有短历史；后来要求清理基金/LOF/ETF/指数类数据。
- 可能原因：数据 ingest 混入口径或增量更新不全。
- 已尝试方案：限制普通股票代码为 SZ 00/30、SH 60/68、BJ 92。
- 有效方案：新增数据前先验证 qlib series lifecycle 和 ordinary-stock code policy。
- 无效方案：直接把所有代码当股票。
- 相关文件：`mosaic/rke/report_intelligence.py`、`mosaic/dataflows/qlib_ingest.py`、`tests/test_tushare_collector_symbols.py`
- 新 AI 下一步该怎么查：`outcome_labeling_readiness.json` 和 qlib feature dirs。

### 问题：Git/npm 权限和审批
- 表现：`npm install -g @openai/codex` 曾因 `/usr/lib/node_modules` EACCES 失败；git/uv/cache 有时需要 sandbox approval。
- 可能原因：系统目录无权限、沙箱限制读写 home cache。
- 已尝试方案：使用项目本地工具、`UV_CACHE_DIR` 到 `~/tmp/mosaic-rke/uv-cache`。
- 有效方案：避免 global install；必要时请求最小审批。
- 无效方案：sudo/global install。
- 相关文件：无固定文件。
- 新 AI 下一步该怎么查：看命令错误路径，优先改到用户/项目目录。

## 8. 最近修改记录

### 修改 1：Route RKE temp workspace to home tmp
- 修改原因：系统 `/tmp` 被测试/缓存占满，用户要求清理 `/tmp` 并更换目录。
- 修改文件：`mosaic/rke/temp_paths.py`、`tests/conftest.py`、`pyproject.toml`、RKE runbooks/status/handoff/promotion artifacts。
- 改了什么：RKE 默认 temp root 改为 `~/tmp/mosaic-rke`；生成命令带 `MOSAIC_RKE_TMPDIR` 和 `TMPDIR`；pytest 默认不再写 repo 或系统 `/tmp`。
- 为什么这么改：避免系统 tmpfs 被大型 registry copy 填满。
- 是否验证：已验证 focused pytest 39 个、ruff、prompt leak guard、operator-readiness 18/18。
- 可能影响：本地 `~/tmp/mosaic-rke` 会变大；不要反复清理正在用的 cache。

### 修改 2：Scope master plan claim schema gate
- 修改原因：master plan/schema gate 需要更准确地约束 claim schema。
- 修改文件：`mosaic/rke/schema_validation.py`、相关 tests/artifacts。
- 改了什么：收紧 master plan claim 相关 validation。
- 为什么这么改：避免 schema gate 误判或遗漏 claim contract。
- 是否验证：最近提交链已推送；具体测试需看 commit diff/CI。
- 可能影响：schema-status 更严格。

### 修改 3：Clean gold candidate rating suffixes
- 修改原因：研报评级/风险提示/免责声明等被抽成 claim。
- 修改文件：`mosaic/rke/gold_candidate_claims.py`、相关 tests/artifacts。
- 改了什么：清理 rating suffix，继续排除免责声明、风险提示和 rating-only 文本。
- 为什么这么改：提高 gold-set review 样本质量。
- 是否验证：相关测试已在提交链中通过。
- 可能影响：candidate 数量可能下降，但质量提升。

### 修改 4：Surface operator handoff batch overview
- 修改原因：operator 需要知道每个 manual gate 当前 batch 和剩余工作量。
- 修改文件：`mosaic/rke/operator_handoff.py`、`registry/handoffs/*`。
- 改了什么：handoff artifact 公开显示 gold/footprint batch overview。
- 为什么这么改：让后续 AI/人工接手时知道当前进度。
- 是否验证：operator handoff semantic validation 通过。
- 可能影响：handoff artifact 需要随 review progress 刷新。

### 修改 5：Surface review batch overview in promotion status
- 修改原因：promotion status 也需要显示 manual batch 阻塞上下文。
- 修改文件：`mosaic/rke/promotion_gate.py` 或相关 promotion/status artifact。
- 改了什么：promotion status 带上 batch overview。
- 为什么这么改：避免只看到 blocked，不知道下一步填哪个文件。
- 是否验证：promotion dry-run/gate contract 通过。
- 可能影响：public artifact 内容变多，但仍应 public-safe。

### 修改 6：Validate manual review batch overview
- 修改原因：manual review progress artifact 需要防漂移。
- 修改文件：`mosaic/rke/schema_validation.py`、`tests/test_rke_schema_artifacts.py`。
- 改了什么：schema/semantic validation 重新计算 batch overview 和 pending plan。
- 为什么这么改：防止 public status 与实际 scratch/import 状态不一致。
- 是否验证：schema artifact tests 覆盖。
- 可能影响：手工改 public JSON 会被拒绝。

### 修改 7：Persist manual review batch overview
- 修改原因：runbook、progress、handoff 需要统一展示 batch 状态。
- 修改文件：`mosaic/rke/review_progress.py`、`registry/review_batches/manual_review_progress_report.json`。
- 改了什么：持久化 current batch status、field workload 和 action order。
- 为什么这么改：交接时能直接看到缺哪些字段。
- 是否验证：review-progress 和 schema contract 通过。
- 可能影响：artifact 刷新时 diff 可能较大。

### 修改 8：Focus manual review quality gaps
- 修改原因：gold-set 质量 gate 不只是 pending rows，还需要知道哪些字段拖累指标。
- 修改文件：`mosaic/rke/review_progress.py`、`mosaic/rke/manual_review_batches.py`、相关 artifacts。
- 改了什么：把 failing metrics 映射到 review fields，例如 `variable_mapping_correct`、`unsupported_field_false_grounded`、`direction_correct`。
- 为什么这么改：人工 review 优先修最影响 gate 的字段。
- 是否验证：review-progress 输出和 tests 覆盖。
- 可能影响：review aid 更有指导性，但仍不能自动填。

### 修改 9：Group/order/summarize review fields
- 修改原因：人工 review 字段太多，需要按 workflow 和剩余工作排序。
- 修改文件：`mosaic/rke/review_progress.py`、`registry/review_batches/manual_review_runbook.md` 等。
- 改了什么：新增 `current_batch_review_field_workload_summary`、action order、workflow groups。
- 为什么这么改：让人先填最关键字段，减少重复问。
- 是否验证：operator-readiness 和 schema contract 最近通过。
- 可能影响：runbook/status diff 较大。

### 修改 10：宏观、政策、AKShare、PBOC 等前序工具接入
- 修改原因：Tushare 有的尽量用 Tushare；Tushare 没有或不适合时使用 FRED/AKShare/china-policy-db/fallback crawler。
- 修改文件：`mosaic/dataflows/*`、`mosaic/agents/utils/macro_tools.py`、tests。
- 改了什么：PBOC/gov policy local-first china-policy-db、AKShare EPU/realized vol 等工具。
- 为什么这么改：提高宏观和政策数据覆盖。
- 是否验证：前序 PR 已 review/merge。
- 可能影响：网络/API 依赖和本地 repo cache 需要维护。

### 修改 11：MOSAIC-Prompts/private prompt source
- 修改原因：所有 agent 工作要可选择基于 private prompt repo。
- 修改文件：`mosaic-ts/src/agents/prompts/loader.ts`、`mosaic-ts/src/cli/prompt-source.ts`、相关 tests。
- 改了什么：默认 bundled prompts，可配置 private repo/root，flag 优先级和 `.env` 解析修复。
- 为什么这么改：保护 private prompt，同时支持生产 prompt 演化。
- 是否验证：PR review 通过，TS checks 曾全绿。
- 可能影响：所有 TS CLI 会加载 `.env`。

### 修改 12：个股研报 outcome 和演化计划
- 修改原因：原来只评价行业研究，个股研报也应使用 qlib `cn_data` 评价。
- 修改文件：`docs/plans/rke_stock_report_outcome_and_evolution_plan.md`、`docs/plans/rke_stock_report_outcome_and_evolution_status.md`、`mosaic/rke/report_intelligence.py`、tests/schema artifacts。
- 改了什么：stock proxy outcome、paper-trading、confidence monitor、evolution readiness、PIT/survivorship/liquidity readiness gaps。
- 为什么这么改：让行业和个股研报都能进入同一套非 LLM 评价闭环。
- 是否验证：public status 显示主体已实现；manual gates 未完成。
- 可能影响：更多 private artifacts 和 review 工作量。

## 9. 下一步开发计划

### 下一步最优先做什么？
- 目标：完成当前 gold-set 26 行人工 review batch，并让 `apply-gold-review --dry-run` 接受。
- 原因：gold-set 是当前 schema/evolution/promotion 的核心 blocker；当前还有 47 个 gold target rows pending，其中当前 scratch 覆盖 26 行。
- 涉及文件：
  - `registry/review_batches/gold_set_reviewed.jsonl`
  - `registry/review_batches/gold_set_review_evidence.jsonl`
  - `registry/review_batches/gold_set_review_evidence.md`
  - `registry/review_batches/manual_review_progress_report.json`
  - `mosaic/rke/manual_review_import.py`
- 具体步骤：
  1. 按 5 条一组读取 private evidence，输出建议给用户审核。
  2. 用户确认后，写入 `gold_set_reviewed.jsonl`，保留 `claim_id`、`target_row_hash`、`review_context_ref`、`target_review_path`。
  3. 跑 `apply-gold-review --dry-run`。
  4. dry-run 通过后再 apply。
  5. rerun `review-progress --review-kind gold_set`，准备剩余 21 行。
- 验收标准：
  - 当前 26 行 dry-run accepted。
  - apply 后 current batch pending 降为 0。
  - rerun progress 显示下一批 21 行或 gold gate 完成。
  - 不提交 private review import。

### 第二优先级：
- 目标：完成 analytical-footprint 当前 50 行 batch。
- 原因：footprint review 总待审 1017 行，metric_mapping_accuracy 是 patch/evolution blocker。
- 具体步骤：
  1. 使用 `analytical_footprint_review_evidence.jsonl` 和 workbook 辅助审核当前 50 行。
  2. 填 `analytical_footprint_review_batch.jsonl`。
  3. 跑 `apply-footprint-review --dry-run`。
  4. 通过后 apply，将 batch merge 到 `analytical_footprint_reviewed.jsonl`。
  5. rerun review-progress，准备下一批。
- 验收标准：
  - 当前 batch dry-run accepted。
  - target review template/reviewed import hash 对齐。
  - metric_mapping_accuracy 朝 0.80 gate 改善。

### 第三优先级：
- 目标：在 gold/footprint gate 完成后运行 lockbox 和 promotion dry-run。
- 原因：lockbox 是 final holdout，不应提前打开。
- 具体步骤：
  1. 确认 gold-set 和 footprint ready。
  2. 运行 `prepare-lockbox-review`。
  3. 人工填写 `lockbox_reviewed.json`。
  4. `apply-lockbox-review --dry-run`，通过后 apply。
  5. `promotion-dry-run`、`promotion-status`、`schema-status`。
- 验收标准：
  - promotion dry-run accepted。
  - `schema-status --failures-only --no-write` 无 manual gate failures。
  - production gate 仍按 shadow/promotion policy，不直接上生产。

### 哪些任务不要现在做？
- 不要把 RKE outcome label 接入生产交易决策。
- 不要打开 lockbox。
- 不要重装 MinerU/vLLM。
- 不要跑会写 `/tmp` 的全量测试。
- 不要提交私有 Tushare、PDF、Markdown、review import、`.mosaic/`。
- 不要直接修改 public gate summary 伪造通过。
- 不要恢复多层 agents 并行，除非用户明确要求且有测试。

### 哪些功能容易过度开发？
- 公司名到 ts_code 的 fuzzy mapping：目前只记录 gap，除非有强验证数据，不要强推。
- gold-set 自动审核：可以生成辅助建议，但不能自动填人工字段。
- prompt evolution：mutation candidates 已有，先过人工 gate，再做 promotion。
- 通用 abstraction：RKE 已经有大量 build/write/schema/test 模式，新增前先复用。
- 宽泛变量 ontology：先修当前 claim quality，不要一次性发明大量变量。

### 哪些地方要先验证再写代码？
- qlib 股票/ETF 数据完整性、calendar 对齐和 ordinary-stock code policy。
- vLLM/MinerU 是否已经可用。
- `.env` 是否已有需要的 key，但不要输出真实值。
- private file 是否被 git ignore。
- 当前 public artifact 是否需要刷新，刷新后 schema contract 是否覆盖。
- 用户是否确认人工 review 建议；未确认前不要写入 review import。
