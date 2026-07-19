# MOSAIC-Fish 真实服务与 Agents 反馈闭环

本流程把真实 MOSAIC-Fish/OASIS 输出自动写入 `mirofish_context`，随后由
Daily Cycle 的 CRO、autonomous execution 和 CIO 读取。情景只作为带有明确免责声明的
模拟证据，不能单独支持交易动作。

## 1. 启动真实服务

MOSAIC-Fish 默认位于 `/home/hap/Project/MOSAIC-Fish`。首次启动会构建较大的 OASIS
镜像；后续启动复用镜像和 Neo4j volume。

```bash
cd /home/hap/Project/MOSAIC-Fish
rtk docker compose up -d --build
rtk docker compose ps
rtk curl --fail http://127.0.0.1:5001/health
```

服务端 `.env` 必须配置有效的 `LLM_*`、`EMBEDDING_*`、`GRAPH_MEMORY_BACKEND=neo4j`
和 `NEO4J_*`。不要把 API key 复制到 MOSAIC-RKE、日志或提交中。

## 2. 配置 MOSAIC-RKE

在 MOSAIC-RKE 的本地 `.env` 中设置：

```env
MOSAIC_MIROFISH_URL=http://127.0.0.1:5001
```

`mirofish.engine=oasis` 与 `mirofish.inject_context=true` 均为默认值。因此普通
`mirofish generate` 会调用真实 Fish 并自动反馈；需要本地零服务运行时必须显式传入
`--engine montecarlo` 或 `--engine swarm`。需要紧急停用反馈时，可在 Dashboard 设置页
关闭 context 注入；停用不会删除历史 context。

## 3. 生成并自动保存 context

真实 smoke 先限制为一个场景和一轮，控制耗时及模型成本：

```bash
cd /home/hap/Project/MOSAIC-RKE
rtk pnpm --dir mosaic-ts dev mirofish generate \
  --engine oasis \
  --scenarios base \
  --days 5 \
  --max-rounds 1
```

`generate` 成功后会自动调用 `mirofish.save_context`，输出保存日期和 `context_hash`。
非 dry-run 的 `mirofish train` 也会在训练前自动保存同一组场景，并让训练账本与 context
使用同一个日期。`mirofish train --dry-run` 保持无写入语义，不保存 context 或训练记录。

## 4. 让 Agents 消费

下一次 Daily Cycle 会按 `as_of_date` 读取最近且不晚于运行日期的 context，并在同一轮
冻结给三个 L4 agent：

```bash
mkdir -p .mosaic/tmp
SMOKE_DATE="$(date +%F)"
SMOKE_ROOT="$(mktemp -d .mosaic/tmp/structured-smoke.XXXXXX)"
eval "$(uv run python scripts/build_structured_smoke_fixtures.py \
  --root "$SMOKE_ROOT" --date "$SMOKE_DATE" --shell-exports)"
rtk pnpm --dir mosaic-ts dev daily-cycle \
  --cohort cohort_default --date "$SMOKE_DATE" --fake-llm
```

运行日志/数据状态应显示 `mirofish_context` 为 `loaded`，而不是 `missing`；L4 runtime
快照应带非空 `mirofish_context_hash`。反前视校验会拒绝未来日期或缺少
`scenario_count`、`horizon_days`、`context_hash`、`generator_version` 的 context。

## 5. 运维

```bash
cd /home/hap/Project/MOSAIC-Fish
rtk docker compose logs --tail 200 mirofish
rtk docker compose restart
rtk docker compose down
```

排障顺序：`/health` → Neo4j health → MOSAIC-RKE 的 URL → Fish 后端日志 →
`mirofish generate --engine oasis --scenarios base --max-rounds 1`。只有完整 OASIS 报告生成
成功后才会覆盖现有 context，因此失败运行不会把半成品反馈给 Agents。
