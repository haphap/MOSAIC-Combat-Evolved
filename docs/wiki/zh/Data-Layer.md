# 数据层

`mosaic/dataflows/` 向 agent 提供行情 + 宏观数据,以及 qlib 历史数据底座与 ingest 工具链。

## 数据源

- **Tushare**(`tushare.py`)—— 主要 A 股个股 + ETF 数据(`pro.daily`、`pro.fund_daily`、`pro.index_daily`、财务),以及**研究报告**(`pro.research_report`):`get_broker_reports`(行业研报,行业级)和 `get_stock_reports`(个股研报,个股级)。LangChain `@tool` 封装 `get_broker_research` / `get_stock_research` 在 `mosaic/agents/utils/research_report_tools.py`,挂载到行业 + 投资哲学 agent(见[智能体](Agents.md))。
- **akshare**、**yfinance**、**FRED**(`macro_data.py`、`fred.py`)、雪球热度 等 —— 宏观/全球/情绪工具。含 `get_property_data`(akshare `macro_china_real_estate` —— 月度国房景气指数,按 `curr_date` 点对点裁剪),由 `china` agent 使用。macro 层共 **17 个工具**。
- 工具选择由配置驱动(`MosaicConfig` 的 `data_vendors` / `tool_vendors`)。

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
