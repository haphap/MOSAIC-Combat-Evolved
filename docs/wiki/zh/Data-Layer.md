# 数据层

`mosaic/dataflows/` 向 agent 提供行情 + 宏观数据,以及 qlib 历史数据底座与 ingest 工具链。

## 生产数据源与工具边界

- **Tushare** 是 A 股/ETF 行情、PIT 成分、财务报表、基金份额、资金流、期货、外汇和
  全球财经日历 `eco_cal` 的注册主来源，但每个 endpoint 必须先通过权限与 schema
  preflight。`major_news`、`news`、`npr`、`monetary_policy` 已明确无权限，不存在生产
  client 或 fallback。
- **中国/PBOC** 实体与政策观测来自已注册的国家统计局、海关总署、财政部和 PBOC
  官方目录及通过验证的 Tushare series。**美国**实体历史 vintage 使用预注册的
  ALFRED/官方 series，Fed/纽约联储数据进入美国金融条件。**欧盟/欧元区**实体与金融
  数据使用冻结的 Eurostat/ECB key。World Bank 只作 `CONTEXT_ONLY`。
- 原始响应只保存在私有缓存。运行时 collector 在 Agent 启动前物化并签名
  `AgentSnapshotBundle`；模型只能调用零参数的职责快照。bridge 校验 Agent、stage、日期和
  scope，消费一次性 capability，且 `tools.call` 期间不重新采集。
- 行业、关系、Superinvestor 和 Decision 节点同样只读取冻结的角色快照。通用 ticker
  搜索、OpenCLI/财新搜索、雪球关注度、研究报告工具和 `get_rke_research_context` 均不在
  production tool manifest；RKE 始终为 shadow-only。
- endpoint 状态、source mapping 和精确 Agent/tool 分配提交在 `registry/data_sources/`
  与 `registry/prompt_checks/`。required coverage 缺失时失败关闭，不得静默切换数据源。

### 欧盟官方 API adapter

`official_macro_adapters.py` 为冻结的 Eurostat、ECB 与 World Bank series 提供封闭、
host 白名单和响应大小受限的 URL builder/parser。可运行
`uv run python scripts/probe_official_macro_sources.py` 刷新仅含 metadata 的 transport
preflight；公开 artifact 只记录 URL、content hash、行数和 readiness，不保存 provider
观测值。实时 API 可用只证明 transport/schema 可用，并不证明 PIT 安全；在观测值能够连接到
append-only release/vintage ledger，且满足 `released_at/vintage_at <= as_of` 前，欧盟/欧元区
production snapshot 必须继续失败关闭。

### 地缘数据源 preflight

`geopolitical_source_adapters.py` 只探测封闭 source manifest 中的 15 个精确 root，执行
HTTPS/domain 白名单、响应大小限制、redirect 校验和宽泛响应结构校验。可运行
`uv run python scripts/probe_geopolitical_sources.py` 刷新仅含 metadata 的 artifact。
root 可访问不等于事件证据，也不能激活 coverage route；production 仍要求各 source 的
pagination、发布时间解析、完整 route polling，以及连续 30 天 availability/latency 证据。
任何 required source 缺失时，`get_geopolitical_events_snapshot` 必须失败关闭。
私有审计保留 route/query 粒度明细；模型只接收包含事件及各事件族精确覆盖计数/hash 的
有界角色投影。

## qlib 本地读取 (`qlib_local.py`)

**不导入 qlib** 直接读 qlib 的二进制 feature 文件。把复权值还原到市场尺度(`原始 = 复权 / factor`)。提供与 Tushare 数据源同签名的 `get_stock`、`get_indicator` 等。

### 个股 vs ETF 路由

- **个股** → `cn_data` 数据集(`~/.qlib/qlib_data/cn_data`),`QLIB_CN_DATA_PATH` 覆盖。
- **ETF** → `cn_etf` 数据集(`~/.qlib/qlib_data/cn_etf`),`QLIB_CN_ETF_PATH` 覆盖。
- 判定为 ETF 当且仅当 `sh5xxxxx` / `sz1xxxxx`(与个股前缀 sh6/sz0/sz3 不相交)。同一路由在 scorecard 评分器(`_is_a_share_etf`)镜像,使 ETF 推荐经 `pro.fund_daily` 取得前向收益评分。

## Ingest (`qlib_ingest.py`)

vendored 采集器之上的薄编排。公共 API:

- `ingest_full(start, end, kind=...)` —— pipeline:download → normalize → dump_to_bin。
- `ingest_incremental(end, kind=...)` —— 追加最新交易日(`update_data_to_bin`)。
- `sync_calendar(end, ...)` —— 仅刷新 `calendars/day.txt`。
- `validate_after_ingest(...)` —— 逐标的 gap 报告 + skip 清单(`data/qlib_skipped.txt`)。

`kind="stock"` 驱动 cn_data,`kind="etf"` 驱动 cn_etf。经 `data.*` RPC 与 `pnpm dev data incremental|validate` CLI 暴露给前端。

### 临时数据留在项目外

采集器的工作目录默认在 `~/.cache/mosaic_tushare_{raw,norm}` —— **绝不**进项目树。由于采集器现在 vendored 到仓库**内**,`ingest_incremental` / `sync_calendar` 显式传 `--source_dir`/`--normalize_dir`(且 `.gitignore` 忽略 `collectors/` 下任何遗留的 `source/`/`normalize/`/`tmp/`),使原始/归一化 CSV 与 `__inc_tmp__` 永不污染仓库。

## Vendored 采集器 (`mosaic/dataflows/collectors/`)

为使 ingest 自包含(运行期无需外部 qlib 检出):

- `data_collector/tushare/collector.py` + `data_collector/tushare_etf/collector.py` —— 个股 + ETF 采集器。
- `dump_bin.py`、`data_collector/base.py`、`data_collector/utils.py` —— 逐字复制自 **microsoft/qlib**(MIT),采集器依赖它们。
- 运行期仍从 `pyqlib`(`backtest` extra)导入 `qlib.utils`。子进程依赖是 `ingest` extra(fire/loguru/joblib/yahooquery/beautifulsoup4)。

### 发现

`find_qlib_collector(kind)` 优先用 vendored 副本;一个*有效*的 `MOSAIC_QLIB_REPO`(stock)/ `MOSAIC_QLIB_ETF_COLLECTOR`(etf)环境覆盖胜出,若环境覆盖设了却无效则优雅回退到 vendored 副本。

### 许可

MOSAIC 为 Apache-2.0;三个 vendored qlib 文件在 Microsoft 版权下仍为 **MIT**。见 `mosaic/dataflows/collectors/NOTICE.md` + `LICENSE.qlib`。MIT 与 Apache-2.0 兼容。
