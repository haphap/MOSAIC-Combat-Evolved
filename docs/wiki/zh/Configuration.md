# 配置

运行时配置是单个对象(`mosaic-ts/src/bridge/types.ts` 的 `MosaicConfig`;`mosaic/default_config.py` 的 `DEFAULT_CONFIG`)。它被 sidecar 按进程读取,由前端推送/持久化。

## 关键字段

| 字段 | 含义 |
| --- | --- |
| `llm_provider` | `anthropic`(默认)/ `openai` / `deepseek` / `lemonade` / …(见 `src/llm/factory.ts`) |
| `deep_think_llm`、`quick_think_llm` | 两档 LLM 的模型 id |
| `backend_url`、`anthropic_base_url`、`anthropic_effort` | 可选 provider 覆盖 |
| `output_language` | `Chinese`(默认)/ `English` / `Bilingual` |
| `active_cohort` | 活动 cohort 键(默认 `euphoria_2021`) |
| `cohorts` | 7 个 cohort × {start, end}(见[自我改进](Self-Improvement.md)) |
| `autoresearch` | cooldown / lockout / keep 阈值 / 月度上限 / 评估窗口 + opt-in `git` push |
| `mirofish` | `engine` / `scorer` / `inject_context`(均 opt-in;默认 montecarlo / terminal / off) |
| `data_vendors`、`tool_vendors` | 逐类别数据源选择 |
| `agent_data_cache` | routed agent tool 数据的 SQLite 精确调用缓存;条目会保留到 TTL 刷新、max-entry 淘汰、cleanup 或 clear(`enabled` 默认 true;`db_path` 可选;`read_ttl_seconds` 默认 86400;`max_entries` 默认 50000;`skip_empty_results` 默认 true) |

## 持久化模型

- **`config.default`** —— 原始 `DEFAULT_CONFIG`。
- **`config.get`** —— 运行中 sidecar 进程的活动配置。
- **`config.set`** —— **仅本进程**替换活动配置(一个 `ContextVar`;随进程消亡)。
- **`config.save`** —— 写入 `~/.mosaic/config.json` **并**应用。跨重启:每个 sidecar 启动时跑 `initialize_config()`,把持久化文件 merge 到 `DEFAULT_CONFIG` 之上。

行为保守:**不存在**配置文件 ⇒ 纯默认(行为不变);**非法** JSON ⇒ fail-soft 回默认。`MOSAIC_CONFIG` 覆盖文件路径(用于测试隔离)。

每个 CLI 命令 spawn 自己的 sidecar,所以只有 **`config.save`** 的改动能到达下一个命令 —— 这也是 [TUI 设置页](TUI.md) 用 `config.save` 的原因。

## 环境覆盖

除[快速上手](Getting-Started.md)的键外:`MOSAIC_PYTHON`(解释器)、`MOSAIC_DATA_DIR` / `MOSAIC_RESULTS_DIR` / `MOSAIC_CACHE_DIR`(产物根)、`MOSAIC_AGENT_DATA_CACHE_ENABLED` / `MOSAIC_AGENT_DATA_CACHE_DB` / `MOSAIC_AGENT_DATA_CACHE_READ_TTL_SECONDS` / `MOSAIC_AGENT_DATA_CACHE_MAX_ENTRIES` / `MOSAIC_AGENT_DATA_CACHE_SKIP_EMPTY_RESULTS`(routed tool 缓存保留/新鲜度控制)、`MOSAIC_BENCHMARK_TICKER`(评分基准)、`QLIB_CN_DATA_PATH` / `QLIB_CN_ETF_PATH`(qlib 数据集)、`MOSAIC_QLIB_REPO` / `MOSAIC_QLIB_ETF_COLLECTOR`(采集器发现)、`MOSAIC_MIROFISH_URL`(OASIS 引擎)。
