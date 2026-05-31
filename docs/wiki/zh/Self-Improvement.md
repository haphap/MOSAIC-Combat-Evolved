# 自我改进

MOSAIC 的自我改进栈有四部分:**Autoresearch**(提示词进化)、**PRISM**(多周期训练)、**JANUS**(跨 cohort 元加权)、**MiroFish**(反身性模拟)。

## Autoresearch —— 提示词自进化

`mosaic/autoresearch/` —— 选一个 agent,让 LLM 改写其提示词,在 git feature 分支上提交该变更,跑两段式回测算 **ΔSharpe**,再按阈值 keep(合并到 main)或 revert(删分支)。

- **`git_ops.py`**(`GitOps`)—— `git` 的薄、fail-loud 封装。变更在一个一次性 `git worktree` 内提交,使操作者的工作树不被触碰。keep = `merge_to_main`,revert = `delete_branch`。
- **`constraints.py`** —— `check_cooldown`(每 agent 24h)、`check_monthly_cap`(≤100/cohort/月)、`check_keep_lockout`(keep 后 3 天)。
- **`evaluator.py`** —— 在评估窗口(默认 5 交易日)上算 ΔSharpe。
- **`decider.py`** —— `delta_sharpe ≥ keep_threshold_delta_sharpe`(默认 0.1)则 keep。

分支命名:`cohort/{name}/auto/{agent}/{YYYY-MM-DD}`。

### 可选:把 keep 的变更镜像到自托管 git 服务器

`autoresearch.git` 配置(默认**关闭**):当 `push: true`,keep 路径在成功合并后运行 `git push <remote> main`。push 失败只记录并吞掉(keep 决策本地仍成立);合并失败则跳过 push。凭证由操作者负责(SSH key / credential helper)。配置:`{ "push": false, "remote": "origin" }`。

默认值(`mosaic/default_config.py` → `autoresearch`):`agent_mutation_cooldown_hours: 24`、`keep_revert_lockout_days: 3`、`keep_threshold_delta_sharpe: 0.1`、`monthly_modification_cap_per_cohort: 100`、`evaluation_horizon_trading_days: 5`。

## PRISM —— 多周期训练

`mosaic/prism/` 跨 **7 个市场 regime cohort** 训练提示词进化,按 cohort 顺序进行、层内有界并发。Cohort(`prism/cohorts.py`):

| Cohort | 窗口 | Regime |
| --- | --- | --- |
| `bull_2007` | 2006-01-04 → 2007-10-16 | 牛市顶 6124 |
| `crisis_2008` | 2007-10-17 → 2008-10-28 | 暴跌 70%,1664 见底 |
| `bull_2016` | 2016-01-29 → 2017-12-29 | 慢牛 + 白酒 |
| `crisis_covid` | 2018-10-19 → 2020-03-23 | 贸易战 + 疫情合并 |
| `recovery_2020` | 2020-03-24 → 2020-12-31 | 疫后宽松反弹 |
| `euphoria_2021` | 2020-07-01 → 2021-02-18 | 茅指数高峰(启动 cohort) |
| `rate_tightening` | 2022-04-01 → 2023-12-31 | 中特估 + 量化退潮 + Fed 加息 |

CLI:`prism list|train|status|compare`。

## JANUS —— 跨 cohort 元加权

`mosaic/janus/` 跨 cohort 算 softmax 元权重(使在线系统按当前 regime 契合度融合各 regime 专精的提示词)。CLI:`janus run|weights|regime|history`;RPC `janus.run_daily|get_weights|regime|get_history`。

## MiroFish —— 反身性模拟

`mosaic/mirofish/` 从行为主体群合成前向情景,并据此给推荐打分。

- **engine**(`config.mirofish.engine`):`montecarlo`(默认 —— i.i.d. 相关路径 + 可选反身性核)或 `swarm`(主体间交互)。swarm 为 opt-in。
- **scorer**(`config.mirofish.scorer`):`terminal`(默认 —— 方向 × 累计收益)或 `path_aware`(回撤惩罚的权益曲线;`mirofish train` 上的 `--path-aware` 简写)。
- **inject_context**(`config.mirofish.inject_context`,默认关):把最新情景上下文追加到 CIO 提示词(见[智能体](Agents.md))。
- OASIS 适配器可经 HTTP 驱动真实外部 MiroFish 引擎(`MOSAIC_MIROFISH_URL`)。

CLI:`mirofish generate|train|history`;RPC 在 `mirofish.*`。

> 记忆/persona(7M.2/7M.3)经增益验证 deferred/NO-GO;记录于 `mosaic-tsplan.md` §11.8.1。
