# 评分与纸上交易

## 评分 (`mosaic/scorecard/`)

一个 SQLite 支撑的 CIO 推荐及其实际表现的台账。

### 评分算法 (`scorer.py`)

对每条待评分推荐行:
1. 解析第 0 日收盘与第 N 日收盘(N = 5 与 21 个**交易**日,非自然日)。
2. `forward_return_N = (close_N − close_d0) / close_d0`。
3. `alpha_5d = forward_return_5d − benchmark_return_5d`(默认基准 `000300.SH`,`MOSAIC_BENCHMARK_TICKER` 覆盖)。

`_fetch_close` 的价格路由:
- A 股**指数**(如 `000300.SH`)→ `pro.index_daily`。
- A 股 **ETF**(`5xxxxx.SH` / `1xxxxx.SZ`)→ `pro.fund_daily`。
- 否则**个股/港/美** → 经 `_fetch_price_data` 的 `pro.daily`。

这正是让 **ETF 推荐像个股一样被评分**(从而出现在胜率 / 技能里)的关键。

### 防前视

`score_pending` 把「今天」回退到最后一个已完成交易日,只给前向窗口已成熟的行评分;未成熟/缺失行被跳过(缺失行仍标记为已评分以离开待处理集)。

### 视图 / RPC

- `scorecard.append` —— 摄入一次 daily-cycle state。
- `scorecard.score_pending(cohort, today)` —— 回填已成熟收益(幂等;是 RPC,非 CLI 子命令)。
- `scorecard.list_skill` —— 逐 agent alpha / Sharpe / n。
- `scorecard.win_rate` —— 逐标的方向命中率:`sign(action) · 未来5日收益 > 0` 的占比,带样本数 `n`。
- `scorecard.latest_cio_actions` —— 最新 CIO 组合。

### 关于「胜率」的诚实说明

胜率是**本系统自身 CIO 历史**的方向命中率(在已评分行上)。需要积累若干天的 daily-cycle + 回填才有意义(`n` 太小不可信)。它**不是**对某只股票「会涨」的普适预测。

## Darwinian 权重

`darwinian.compute` / `darwinian.get_weights`(`mosaic/scorecard/weights.py`)把 agent 技能转成演化权重,供下游使用(如 `autonomous_execution`)。

## 纸上交易 (`mosaic/paper_trading/`)

自建纸上交易引擎(项目已弃 backtrader;这不是 backtrader 实现)。

- **认证** —— `register` / `login` / `logout` / `current_user`(bcrypt 哈希;`trading` extra)。会话在 `~/.mosaic/paper_session.json`,DB 在 `~/.mosaic/paper_trading.db`。
- **交易** —— `buy` / `sell`,**T+1** 结算(当日买入不可当日卖)、佣金、持仓跟踪(`get_positions`、`get_trades`、`get_account`)。
- **信号 → 下单** —— `suggest_order_from_signal` 把 agent 决策转成定量订单(`paper.suggest_order_from_signal`)。
- 读写路径均做**跨用户鉴权**。

CLI:`paper register|login|logout|account|buy|sell|positions|trades|suggest`。
