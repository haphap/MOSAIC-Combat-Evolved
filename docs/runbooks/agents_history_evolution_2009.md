# 2009 起 Agents 历史滚动进化 Runbook

本 runbook 用于在隔离历史沙箱内，从 2009 年开始顺序运行完整 25-Agent 图，使用
Qwen 3.6 35B NVFP4 生成月度 Prompt 候选，并通过未来验证和一次性锁箱决定是否在
后续历史日期启用候选。

该流程不会修改 RKE 的 shadow-only 边界，不注入 Fish 历史上下文，不会合并或推送
MOSAIC-Prompts 的默认分支，也不会触发 paper/live promotion。

## 固定范围与策略

- 本地 Qlib 完整范围：`2009-01-05` 至 `2026-06-09`。
- 初始资金：`1,000,000`；基准：`SH000300`。
- 前 504 个交易日使用冻结 Prompt。
- 每月首个交易日检查一次；每层最多一个未决候选。
- 504 日训练、5 日 purge、90 日验证、5 日 embargo、90 日锁箱。
- 候选采用 paired 5-day block bootstrap；同月候选执行 BH-FDR，并且每个 family 最多
  保留一个 winner，避免组合未经验证的 Prompt。
- Fish context 强制关闭；backtest memory 强制关闭。

## 1. 固定代码与 Prompt

工作树和私有 Prompt 仓库必须干净。不要使用浮动分支名作为恢复参数。

```bash
rtk git status --short
rtk git rev-parse HEAD
rtk git -C "$MOSAIC_PROMPTS_REPO" status --short
rtk git -C "$MOSAIC_PROMPTS_REPO" rev-parse HEAD
```

记录最后一条输出作为 `--prompt-baseline-commit`。整个 run 必须始终使用同一个代码
commit、Prompt baseline commit、sndr preset resolution 和 Qlib 日历；任一指纹变化时
恢复会 fail closed，应新建 run 目录。

## 2. 核对最新 sndr preset

35B preset 的可同步源是私有仓库
`git@github.com:haphap/sndr-local-qwen36-configs.git`。当前固定版本为 tag
`qwen35b-kde-128k-v2`、commit
`2e038f2d0ec31c8721762ed017a0262b1057684c`。新机器或 sndr checkout 重建后先执行：

```bash
rtk git clone git@github.com:haphap/sndr-local-qwen36-configs.git \
  /absolute/path/to/sndr-local-qwen36-configs
rtk git -C /absolute/path/to/sndr-local-qwen36-configs \
  checkout qwen35b-kde-128k-v2
rtk python /absolute/path/to/sndr-local-qwen36-configs/scripts/install.py \
  --sndr-root /absolute/path/to/sndr
rtk python /absolute/path/to/sndr-local-qwen36-configs/scripts/install.py \
  --sndr-root /absolute/path/to/sndr --check
```

安装器要求 sndr core 位于 bundle manifest 固定的 commit，只应用两处兼容补丁，并用
版本化副本原子同步四个明确列出的 hardware/model/preset/profile 文件；版本不符或补丁
冲突会 fail closed，随后执行的 `--check` 会拒绝任何安装结果漂移。仓库不包含模型权重、
缓存、密钥或私有运行证据。

不要从本文复制 vLLM 参数启动服务。每次以 sndr 当前解析结果为准：

```bash
rtk sndr --version
rtk sndr preset show nvidia-qwen3.6-35b-a3b-nvfp4-5090 --json
rtk sndr preflight nvidia-qwen3.6-35b-a3b-nvfp4-5090
rtk sndr launch nvidia-qwen3.6-35b-a3b-nvfp4-5090 --dry-run --skip-autodetect
```

当前注册表解析出的模型为 `qwen3.6-35b-a3b-nvfp4`，profile 为
`nvidia-qwen3.6-35b-a3b-nvfp4-tq-k8v4-5090`。命令会把实际 card/profile、上下文、
KV cache、并发、MTP、tool/reasoning parser 和渲染配置绑定进 manifest；服务配置与
card 不一致时会拒绝运行。

`backtest-evolve` 还会硬性拒绝任何不是 `max_model_len=128000` 且
`gpu_memory_utilization=0.85` 的 35B 渲染结果；因此旧机器即使仍残留 140K/0.90 preset，
也不能启动新的 Agents run。

当前 preset 的工作上下文固定为 `max_model_len=128000`，并使用
`gpu_memory_utilization=0.85`，保留 `turboquant_4bit_nc`、`max_num_seqs=1`、
`max_num_batched_tokens=2048` 和 MTP K=3。
此前的 140K 配置在 Agents 满载时曾把 RTX 5090 D 显存推到 KDE 无法分配 NVKMS
显示缓冲区的程度。不要通过手工 vLLM 参数恢复 140K；始终以 sndr 渲染结果为准。

如服务未启动，由一个明确的 owner 启动并持续负责其生命周期：

```bash
rtk sndr launch nvidia-qwen3.6-35b-a3b-nvfp4-5090 --skip-autodetect
```

等待 `http://127.0.0.1:8000/health` 就绪，并确保 `MOSAIC_VLLM_API_KEY` 通过环境提供。
不要把 key 写入命令、runbook、manifest 或日志。

服务健康后先验证空闲桌面显存门槛：

```bash
rtk nvidia-smi \
  --query-gpu=memory.used,memory.free,utilization.gpu,temperature.gpu \
  --format=csv,noheader,nounits
rtk kscreen-doctor -o
rtk journalctl -k --since "10 minutes ago" \
  --grep "Failed to allocate NVKMS memory for GEM object" --no-pager
rtk journalctl --user --since "10 minutes ago" _COMM=kwin_wayland \
  --grep "Applying output configuration failed|Failed to find a working output layer configuration" \
  --no-pager
```

旧显示拓扑下的 128K/0.82 在 20 个交易日负载中最低留下 1979 MiB 可用显存。5090
当前不再承担显示输出，因此工作配置提升到 128K/0.85；每次真实 Agents smoke、扩展或
恢复仍必须通过
`scripts/run_with_kde_vram_guard.py` 启动。guard 每秒采样一次，要求全程至少保留
256 MiB；启动前或负载中低于门槛、`nvidia-smi` 采样失败或超时，都会终止整个 Agents
进程组。命令结束后，guard 从本次精确启动时间检查新增 KWin/NVKMS 错误；无法读取
journal 或发现新错误也会返回非零。CSV 及 `.summary.json` 写入 `.mosaic/` 私有证据，
其中 `minimum_free_mib_observed` 是本次负载最低值。桌面主机不得使用
`--skip-kde-log-check`。

128K/0.90 曾在长请求中降至约 226 MiB，不能作为桌面主机的运行参数。guard 返回非零
后，由服务 owner 执行
`rtk sndr down nvidia-qwen3.6-35b-a3b-nvfp4-5090`，不得在故障状态下继续运行。

2026-07-14 验证回执：128K/0.82 完成 20 个交易日负载，
累计 520 次模型调用、22,468,691 prompt tokens 和 1,326,271 completion tokens；
最低可用显存 1979 MiB、峰值温度 69°C。guard 退出码为 0，未发现显存门槛违规、
KDE/KWin/NVKMS 错误、CUDA OOM、NVIDIA Xid 或容器重启。该 `.mosaic/` 证据保持私有。

## 3. 静态验证

```bash
rtk uvx ruff@0.15.15 check mosaic tests
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp \
  rtk uv run python -m pytest tests/test_bridge_autoresearch.py -q \
  --basetemp .mosaic/tmp/pytest-agents-history
MOSAIC_RKE_TMPDIR=.mosaic/tmp TMPDIR=.mosaic/tmp \
  rtk uv run python -m pytest tests/test_kde_vram_guard.py -q \
  --basetemp .mosaic/tmp/pytest-kde-vram-guard
rtk pnpm --dir mosaic-ts typecheck
rtk pnpm --dir mosaic-ts lint
rtk pnpm --dir mosaic-ts test
rtk uv run python scripts/check_prompt_leaks.py
```

## 4. 无写入预检

以下示例中的 Prompt commit 必须替换成第 1 步记录的完整哈希：

```bash
rtk pnpm --dir mosaic-ts dev backtest-evolve \
  --start 2009-01-05 \
  --end 2026-06-09 \
  --run-dir .mosaic/backtests/history-2009-qwen35b \
  --prompt-baseline-commit <FULL_PROMPT_COMMIT> \
  --dry-run
```

预检会验证私有 Prompt 仓库、固定 commit、sndr preset/preflight、模型健康及 served
model。它不会创建 backtest run、候选分支或 checkpoint。

## 5. 分阶段启动

### 5.1 Fake LLM 恢复性冒烟

使用单独目录，避免与真实 run 混用：

```bash
rtk pnpm --dir mosaic-ts dev backtest-evolve \
  --start 2009-01-05 \
  --end 2026-06-09 \
  --run-dir .mosaic/backtests/history-2009-fake-smoke \
  --prompt-baseline-commit <FULL_PROMPT_COMMIT> \
  --fake-llm \
  --max-days 20
```

重复同一命令并加 `--resume`，验证 checkpoint 能从下一交易日继续。不要删除
`daily-journal.json`；若上次在写入阶段中断，恢复器会用它完成幂等提交。

### 5.2 Qwen 35B 三日冒烟

```bash
rtk uv run python scripts/run_with_kde_vram_guard.py \
  --output .mosaic/backtests/history-2009-qwen35b/vram-smoke-3d.csv \
  --minimum-free-mib 256 \
  -- \
  rtk pnpm --dir mosaic-ts dev backtest-evolve \
    --start 2009-01-05 \
    --end 2026-06-09 \
    --run-dir .mosaic/backtests/history-2009-qwen35b \
    --prompt-baseline-commit <FULL_PROMPT_COMMIT> \
    --max-days 3
```

要求：无未捕获异常、每日 checkpoint 完整、日期严格递增、manifest 中 Fish 为关闭、
模型/preset/config/data 指纹完整。

### 5.3 扩展至 20 日

前三日通过后再增加 17 个交易日：

```bash
rtk uv run python scripts/run_with_kde_vram_guard.py \
  --output .mosaic/backtests/history-2009-qwen35b/vram-resume-17d.csv \
  --minimum-free-mib 256 \
  -- \
  rtk pnpm --dir mosaic-ts dev backtest-evolve \
    --start 2009-01-05 \
    --end 2026-06-09 \
    --run-dir .mosaic/backtests/history-2009-qwen35b \
    --prompt-baseline-commit <FULL_PROMPT_COMMIT> \
    --resume \
    --max-days 17
```

根据这 20 日的实际耗时、tokens、错误率和 GPU 状态决定是否继续。`--max-days` 表示
本次进程新增完成的交易日数量，不是累计目标。

## 6. 继续运行与观察

通过资源门槛后去掉 `--max-days` 并恢复：

```bash
rtk uv run python scripts/run_with_kde_vram_guard.py \
  --output .mosaic/backtests/history-2009-qwen35b/vram-full-01.csv \
  --minimum-free-mib 256 \
  -- \
  rtk pnpm --dir mosaic-ts dev backtest-evolve \
    --start 2009-01-05 \
    --end 2026-06-09 \
    --run-dir .mosaic/backtests/history-2009-qwen35b \
    --prompt-baseline-commit <FULL_PROMPT_COMMIT> \
    --resume
```

每次重启必须换一个新的 guard `--output` 文件名（例如递增 `vram-full-02.csv`）；guard
拒绝覆盖既有证据。只有 `.summary.json` 中 `violation=null`、child return code 为 `0`、
最低显存不小于 256 MiB 且 KWin/NVKMS 匹配列表为空，才允许继续下一阶段。

所有日期严格顺序执行。主组合使用当前 active Prompt；每个候选拥有固定 base/candidate
双臂、独立持仓状态和独立 qlib run。验证失败立即在历史账本中 revert；锁箱通过且
同月 FDR 通过后，仅排名最高的通过候选会复制到 `history/.../active/...` 分支，并从
下一交易日生效；其余候选 revert。候选审计分支始终保留。

## 7. 产物与故障恢复

run 目录为私有、gitignored 数据，主要文件包括：

- `manifest.json`：代码、Prompt、Qlib、配置、模型和 sndr resolution 指纹。
- `checkpoint.json`：下一交易日、持仓、Prompt lineage、候选状态和未完成的月度演化意图。
- `daily-journal.json`：仅在日提交尚未完成时存在，用于 exactly-once 恢复。
- `data/scorecard.db`：隔离的回测、Autoresearch 和动作账本。
- `candidates/`：验证/锁箱双臂的 qlib summary 与 trajectory。
- `final/`：全历史 qlib 指标和 `evolution-summary.json`。

进程失败后使用完全相同的参数和 `--resume`。以下变化都会拒绝恢复：

- 代码 commit 改变；
- Prompt baseline commit 改变；
- sndr preset resolution 改变；
- 配置或 Qlib 交易日历改变；
- run 起止日期或 cohort 改变。
- 初始资金或 benchmark 改变。

不要手工编辑 checkpoint、journal、SQLite 或候选分支。若确需更换模型、参数、数据或
代码，保留旧目录作为审计证据并启动新的 run。

140K 与 128K 的 sndr resolution 不同。2026-07-13 之前按 140K 创建的 run（包括
`.mosaic/backtests/history-2009-qwen35b-main`）只能作为审计证据保留，不能用 128K
preset 执行 `--resume`；后续正式运行必须使用新的 run 目录。
