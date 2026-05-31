# 快速上手

## 前置条件

- **Python ≥ 3.10**(`pyproject.toml` `requires-python`),用 [`uv`](https://github.com/astral-sh/uv) 管理。
- **Node.js ≥ 22**(`mosaic-ts/package.json` `engines`)+ **pnpm 11**。
- 按需的 **API 凭证**,写入 `.env`(参考 `.env.example`)。

## 安装

```bash
git clone https://github.com/haphap/MOSAIC-Agents.git
cd MOSAIC-Agents

# 1. Python sidecar:建 .venv 并安装(TS 侧自动发现 <repo>/.venv/bin/python)
uv venv
uv pip install -e '.[data,trading,llm]'      # 需 qlib 回测加 ,backtest;需数据更新加 ,ingest

# 2. TypeScript 前端
cd mosaic-ts
pnpm install --frozen-lockfile

# 3. 配置环境变量
cd ..
cp .env.example .env
```

## 可选 extras(`pyproject.toml`)

依赖按需分组,使只跑日循环的 CLI 用户不必拉取重型数据/回测库:

| Extra | 用途 | 主要依赖 |
| --- | --- | --- |
| `data` | 行情/宏观数据 | pandas, numpy, tushare, akshare, yfinance, stockstats |
| `trading` | 纸上交易 | bcrypt |
| `llm` | LLM provider | langchain-anthropic/openai/google, langgraph |
| `backtest` | qlib 回测引擎 | pyqlib, scipy, tqdm |
| `ingest` | 采集器子进程依赖 | fire, loguru, joblib, yahooquery, beautifulsoup4 |
| `test` | 测试 | pytest, pytest-asyncio |
| `all` | 以上全部 | — |

> `pyqlib` 仅提供 cp38–cp312 wheel;在更新的 Python 上 `backtest`/ingest 路径在测试中被跳过(测试套件对依赖 qlib 的用例做了 guard)。

## 环境变量(`.env.example`)

LLM keys:`ANTHROPIC_API_KEY`、`DEEPSEEK_API_KEY`、`OPENAI_API_KEY`、`GOOGLE_API_KEY`、`OPENROUTER_API_KEY`、`XAI_API_KEY`、`LEMONADE_BASE_URL`/`LEMONADE_API_KEY`(本地开发)。
数据:`TUSHARE_TOKEN`(A 股,实盘数据必需)、`FRED_API_KEY`、`BRAVE_SEARCH_API_KEY`、`ALPHA_VANTAGE_API_KEY`。
运行期覆盖:`MOSAIC_DATA_DIR`、`MOSAIC_RESULTS_DIR`、`MOSAIC_CACHE_DIR`、`MOSAIC_PYTHON`、`MOSAIC_BENCHMARK_TICKER`。

开发期可用 mock LLM(`--fake-llm`)零成本跑通整条流水线。

## 首次运行

```bash
cd mosaic-ts

# 冒烟测试 bridge(spawn Python sidecar,列出 tools + config)
pnpm dev bridge-ping

# 用零成本 mock LLM 跑通一次完整 daily cycle(25 agents)
pnpm dev daily-cycle --cohort cohort_default --fake-llm

# 看只读仪表盘
pnpm dev dashboard
```

完整命令面见 [CLI 参考](CLI-Reference.md),日常使用流程见[那里的 cron 流水线](CLI-Reference.md#日常运维)。

## 验证环境

```bash
# TypeScript
cd mosaic-ts && pnpm typecheck && pnpm lint && pnpm test
# Python
cd .. && ruff check mosaic tests && python -m pytest -q
```
