# MiroFish-Offline 可选旁路接入实施计划

日期：2026-06-01

## 结论

采用 `haphap/MiroFish-Offline` 作为 MOSAIC 的可选真实 MiroFish 旁路后端，但不替换默认 `montecarlo` 引擎。

原因：

- `MiroFish-Offline` 解决了原始 `666ghj/MiroFish` 的关键部署痛点：Zep Cloud 记忆和 DashScope/OpenAI 云 API 改为 Neo4j + Ollama + 本地 embedding。
- 它仍是独立 Flask 服务，不是可直接内嵌的 Python 库；MOSAIC 应保持 HTTP adapter 边界，而不是把源码搬进本仓库。
- 它输出的是社会模拟后的 markdown 预测报告，不是 MOSAIC 当前 `MirofishScenario.price_paths` 所需的价格路径；因此只能通过有损映射接入训练/评分链路。
- `MiroFish-Offline` 是 AGPL-3.0，MOSAIC 是 Apache-2.0；不能直接 vendor 代码，应该作为外部进程/服务调用。

目标状态：

- 默认：`config.mirofish.engine = "montecarlo"`，行为不变、成本最低、测试可复现。
- 可选旁路：显式 `engine = "offline"` 调用本地 `MiroFish-Offline` 服务；`engine = "oasis"` 继续保留给原真实服务适配器。
- Offline 生成的报告、解析信号、映射后的 scenario 进入 `mirofish_runs.detail_json` 和 `mirofish_context`，用于 dashboard、history、隔离训练账本和 CIO prompt context injection。
- 交易、paper trading、JANUS/Darwinian 权重不直接受 Offline 输出驱动，除非后续有真实 forward-return 验证和单独开关。

## 当前接入面

MOSAIC 已有以下能力：

- `mosaic/bridge/handlers/mirofish.py`
  - `mirofish.generate_scenarios`
  - `mirofish.score_recommendation`
  - `mirofish.record_run`
  - `mirofish.get_history`
  - `mirofish.save_context`
  - `mirofish.get_context`
- `mosaic/mirofish/oasis.py`
  - 已有外部 MiroFish HTTP adapter。
  - 当前流程：ontology generate -> graph build -> simulation create -> prepare -> report generate -> report get。
  - 当前缺口：没有显式调用 `/api/simulation/start` 跑完整模拟轮次。
- `mosaic-ts/src/mirofish/trainer.ts`
  - 仍要求 bridge 返回 `MirofishScenario[]`。
  - `MirofishScenario` 必须包含 `price_paths` 和 `final_state.csi300_return`。
- `mosaic-ts/src/agents/decision/_factory.ts`
  - 已支持 opt-in MiroFish context injection，仅注入 CIO prompt。

`MiroFish-Offline` 当前确认的服务形态：

- 后端：Flask，默认 `http://localhost:5001`
- 前端：Vue，默认 `http://localhost:3000`
- Graph：Neo4j CE，默认 `bolt://localhost:7687`
- LLM：OpenAI-compatible Ollama，默认 `http://localhost:11434/v1`
- Embedding：Ollama `nomic-embed-text`
- 关键 API：
  - `POST /api/graph/ontology/generate`
  - `POST /api/graph/build`
  - `GET /api/graph/task/<task_id>`
  - `POST /api/simulation/create`
  - `POST /api/simulation/prepare`
  - `POST /api/simulation/prepare/status`
  - `POST /api/simulation/start`
  - `GET /api/simulation/<simulation_id>/run-status`
  - `POST /api/report/generate`
  - `POST /api/report/generate/status`
  - `GET /api/report/<report_id>`

## 实施原则

1. 默认不变：不改变 `montecarlo`、`swarm`、`terminal` scorer 的默认行为。
2. 显式 opt-in：只有显式选择 `engine=offline` 且配置了 `MOSAIC_MIROFISH_URL` 时，才触发 `MiroFish-Offline` 外部服务。
3. 失败显式：Offline 服务不可用、模型未拉取、Neo4j 未连上、超时，都返回明确 RPC error，不静默 fallback 到 Monte Carlo。
4. 输出诚实：所有由报告映射出的价格路径标记为 synthetic / lossy，不把 narrative 预测伪装成市场路径预测。
5. 隔离账本：结果只进入 `mirofish_runs` / `mirofish_context`，不写真实 paper/portfolio 状态。
6. 许可证隔离：不复制 `MiroFish-Offline` 源码到本仓库；只保留 adapter、文档和 fake transport tests。
   注意 AGPL-3.0 §13（网络条款）：保持 arms-length 外部服务边界 —— 不 import 其模块、不把
   MiroFish-Offline 打进任何 MOSAIC 对外分发的 Docker 镜像。若 MOSAIC 日后以联网服务或商业发行
   形式提供，需要法律确认 AGPL 边界。

## Phase 0：本地服务验收

目标：证明 `haphap/MiroFish-Offline` 在本机能完整跑通，不先改 MOSAIC 业务逻辑。

任务：

1. 克隆/更新外部仓库。
   - 推荐路径：`~/Project/MiroFish-Offline`
   - 记录 commit SHA。
2. 准备 `.env`。
   - （以下 hostname / 服务名 / 密码 / 模型名为示例，须与 MiroFish-Offline 实际
     `docker-compose.yml` 对齐 —— P0 正是用来核对这些；不要照抄）
   - Docker 内部：
     - `LLM_API_KEY=ollama`
     - `LLM_BASE_URL=http://ollama:11434/v1`
     - `LLM_MODEL_NAME=qwen2.5:14b` 或 `qwen2.5:32b`
     - `EMBEDDING_MODEL=nomic-embed-text`
     - `EMBEDDING_BASE_URL=http://ollama:11434`
     - `NEO4J_URI=bolt://neo4j:7687`
     - `NEO4J_USER=neo4j`
     - `NEO4J_PASSWORD=mirofish`
     - `OPENAI_API_KEY=ollama`
     - `OPENAI_API_BASE_URL=http://ollama:11434/v1`
3. 启动服务。
   - `docker compose up -d`
   - 拉模型：
     - `docker exec mirofish-ollama ollama pull qwen2.5:14b`
     - `docker exec mirofish-ollama ollama pull nomic-embed-text`
4. 健康检查。
   - `curl http://localhost:5001/health`
   - Neo4j browser 可访问：`http://localhost:7474`
   - 前端可访问：`http://localhost:3000`
5. 手动跑一个小 seed。
   - 上传一份短金融/政策文本。
   - 构建图谱。
   - 创建 simulation。
   - prepare。
   - start，限制 `max_rounds=3` 到 `5`。
   - 生成 report。

验收：

- `/health` 返回 ok。
- `/api/report/<report_id>` 返回 `markdown_content`。
- 模拟可在 30 分钟内完成一个 `max_rounds <= 5` 的 smoke。
- 记录硬件、模型、耗时、失败点。

产出：

- `docs/mirofish-offline-live-smoke.md`，记录实测命令和结果。

## Phase 1：Adapter 命名与配置

目标：在 MOSAIC 中明确区分“原始 cloud MiroFish 风格 adapter”和“本地 Offline 服务”，并保持 Offline 为显式旁路。

任务：

1. 扩展 engine 枚举。
   - Python handler 支持：`montecarlo | swarm | oasis | offline`
   - TS CLI 类型支持同样枚举。
   - `offline` 用独立的 `OfflineMiroFishEngine`（继承 `OasisMiroFishEngine` 复用 HTTP 传输），
     **不**把它当 `oasis` 的裸别名 —— 因为 Phase 2 要给 pipeline 加 `simulation/start`，
     若共用同一 adapter 会改变既有 `oasis`（指向 666ghj/MiroFish 云服务）的默认行为。新增的
     start / run-status step 只在 `offline`（或显式开关）下默认启用；`oasis` 默认保持旧
     report-only 流程，除非已确认其后端同样支持 `/api/simulation/start`。
   - `default_config.py` 中保持 `engine = "montecarlo"`，Offline 只通过显式 `--engine offline` 或配置打开。
2. 扩展配置。
   - 增加可选说明字段，不要求默认值：
     - `MOSAIC_MIROFISH_URL`
     - `MOSAIC_MIROFISH_MAX_ROUNDS`
     - `MOSAIC_MIROFISH_POLL_TIMEOUT`
3. 更新 CLI help。
   - `pnpm dev mirofish generate --engine offline`
   - `pnpm dev mirofish train --engine offline --path-aware`

涉及文件：

- `mosaic/default_config.py`
- `mosaic/bridge/handlers/mirofish.py`
- `mosaic-ts/src/bridge/types.ts`
- `mosaic-ts/src/cli/commands/mirofish.ts`
- `mosaic-ts/test/mirofish_trainer.test.ts`
- `tests/test_bridge_mirofish.py`

验收：

- bad param tests 对未知 engine 仍报 `INVALID_PARAMS`。
- `engine=offline` 能走到外部 adapter。
- `engine=oasis` 兼容不破坏。
- 不设置 `MOSAIC_MIROFISH_URL` 时返回清晰错误。
- 不传 `engine` 时仍走默认 `montecarlo`，不触发外部服务。

## Phase 2：完整 Offline pipeline

目标：让 adapter 真正跑 MiroFish-Offline 的 simulation，而不只是 prepare 后直接生成 report。

任务：

1. 在 `mosaic/mirofish/oasis.py` 增加 start step（**默认仅对 `offline` 启用**，`oasis` 不变）。
   - 当前 `_run_pipeline()` 在 prepare 后直接 `report/generate`。
   - 新流程（`offline` 默认走完整版；`oasis` 默认仍是旧 report-only，除非确认后端支持 start）：
     - ontology generate
     - graph build + poll
     - simulation create
     - simulation prepare + poll
     - simulation start
     - run-status poll until `completed | stopped | failed`
     - report generate + poll
     - report get
2. 增加 max rounds。
   - 默认从 `MOSAIC_MIROFISH_MAX_ROUNDS` 读取。
   - 未设置时使用小安全默认值，例如 `5`，避免误跑长模拟。
   - 允许 bridge params 覆盖；CLI 暴露 `--max-rounds`。
3. 增加 run polling。
   - `GET /api/simulation/<simulation_id>/run-status`
   - 成功状态：`completed` 或测试环境允许 `stopped`
   - 失败状态：`failed`
   - 超时：`MiroFishUnavailable`
4. 保留兼容模式。
   - 默认行为按 engine 分流：`offline` 走完整 start/run-status 流程，`oasis` 保持旧 report-only。
   - `MOSAIC_MIROFISH_SKIP_START=1` 可在 `offline` 下强制走旧路径，方便排查 report-only 问题。
   - run-status step 复用同一段代码，由 `OfflineMiroFishEngine` 开启、`OasisMiroFishEngine` 默认关闭，
     避免改到既有 `oasis` 调用方。

涉及文件：

- `mosaic/mirofish/oasis.py`
- `mosaic/bridge/handlers/mirofish.py`
- `mosaic-ts/src/bridge/types.ts`
- `mosaic-ts/src/mirofish/trainer.ts`
- `mosaic-ts/src/cli/commands/mirofish.ts`
- `tests/test_mirofish_oasis.py`
- `tests/test_bridge_mirofish.py`
- `mosaic-ts/test/mirofish_trainer.test.ts`

验收：

- fake transport 单测覆盖完整调用顺序。
- CLI `--max-rounds` 能经 TS -> bridge -> adapter 传到 `/api/simulation/start`。
- run-status 超时、failed、非 JSON、`success:false` 都有明确异常。
- 旧测试不需要真实 Neo4j/Ollama。

## Phase 3：MOSAIC seed 输入增强

目标：让 Offline 模拟吃到足够的市场上下文，而不是只有一句泛泛的 A 股预测要求。

任务：

1. 定义 `MirofishSeed` 结构。
   - `as_of_date`
   - benchmark：CSI300 / 000300.SH 最近收益和波动
   - ETF basket：当前 watchlist / 默认 7 个 ETF
   - macro snapshot：央行、利率、中美利差、汇率、商品、政策摘要
   - flow snapshot：北向/行业资金/券商报告摘要
   - agent debate summary：L1-L4 关键分歧、CIO/CRO 结论
   - risk constraints：禁止使用未来数据、仅模拟用途
2. Python 端生成 seed text。
   - 最小版本：adapter 内部根据 params 的 `seed_text` 使用，否则 fallback 到当前短文本。
   - 完整版本：新增 bridge method 或扩展 `mirofish.generate_scenarios` params。
3. TS 端接入 daily-cycle context。
   - 在 CLI `mirofish generate/train` 中先不自动拉全量 daily-cycle，避免过大改动。
   - 后续在 dashboard 或 daily-cycle post step 中调用 `mirofish.save_context`。

涉及文件：

- `mosaic/mirofish/oasis.py`
- `mosaic/bridge/handlers/mirofish.py`
- `mosaic-ts/src/bridge/types.ts`
- 可能新增：`mosaic/mirofish/seed.py`

验收：

- seed text 中包含 `as_of_date`。
- 单测确认 seed file 通过 multipart 上传。
- adapter 不在 seed 中包含未来日期或回测窗之后的数据。

## Phase 4：报告解析与价格路径映射

目标：减少当前“关键词计数 -> drift”的粗糙映射，把 Offline 报告转成更透明的 scenario context。

任务：

1. 新增 `ReportSignal`。
   - `direction`: `bullish | bearish | neutral`
   - `confidence`: `0..1`
   - `regime`: `RISK_ON | RISK_OFF | NEUTRAL`
   - `tail_risks`: list
   - `positive_catalysts`: list
   - `negative_catalysts`: list
   - `summary`
   - `raw_report_excerpt`
2. 新增 parser。
   - 第一版：规则解析 markdown heading、关键句和情绪词。
   - 第二版：可选 LLM structured extraction，但默认不用，避免额外成本。
3. 场景映射。
   - `base`：按 extracted direction/confidence 小幅倾斜。
   - `bull/bear/tail_*`：保留 MOSAIC scenario scaffold，但 narrative 和 tail risks 来自 report。
   - `final_state` 增加：
     - `report_direction`
     - `report_confidence`
     - `offline_report_id`
     - `mapping_lossy: true`
4. 原文落账。
   - `mirofish_runs.detail_json` 保存 report metadata 和截断后的 markdown。
   - `mirofish_context.narrative` 只保存摘要，不塞完整报告进 prompt。
5. lossy guard（机制级，不只靠约定）。
   - `mapping_lossy: true` 是硬开关：JANUS / Darwinian / paper-trading 权重写入入口对带此标记的
     scenario 做**显式拒绝或过滤**，使 Offline 派生的合成路径即便被误接线也无法回写真实交易权重。
   - `runMirofishTraining` 允许显式 `engine=offline` 的 scenario 进入隔离的 `mirofish_runs` 训练账本；
     这是可选旁路的主验证路径。
   - `score_recommendation` 仍可对这些路径算分，分数用于 `mirofish_runs`、dashboard 和 context；
     只有真实权重/交易路径禁止消费。
   - 加一条单测：把带 `mapping_lossy:true` 的 scenario 喂给 JANUS / Darwinian / paper 写入路径，
     断言被拒绝/跳过；同时确认 `runMirofishTraining` 可正常记录隔离账本。

涉及文件：

- `mosaic/mirofish/oasis.py`
- 可能新增：`mosaic/mirofish/report_parser.py`
- `mosaic/mirofish/context.py`
- `mosaic-ts/src/mirofish/trainer.ts`
- `mosaic-ts/test/mirofish_trainer.test.ts`
- `tests/test_mirofish_oasis.py`
- 可能新增：`tests/test_mirofish_report_parser.py`

验收：

- bullish / bearish / neutral fixture 能稳定解析。
- price path 仍兼容 `score_recommendation`，且 `runMirofishTraining` 可把结果写入隔离 `mirofish_runs`。
- 带 `mapping_lossy: true` 的 scenario 被 JANUS / Darwinian / paper 写入链路显式拒绝或排除（机制级 guard，有单测覆盖）。
- `derive_context()` 对新增字段兼容。
- prompt 注入文本明确带 “simulation only / not investment advice / no lookahead”。

## Phase 5：CLI 与操作手册

目标：让用户可以稳定运行、排错、复现。

任务：

1. CLI 增强。
   - `pnpm dev mirofish generate --engine offline --max-rounds 5 --print`
   - `pnpm dev mirofish train --engine offline --fake-llm --dry-run`
   - 默认基线：`pnpm dev mirofish generate --print` 仍走 `montecarlo`
   - `pnpm dev mirofish history`
2. 文档补充。
   - `docs/wiki/CLI-Reference.md`
   - `docs/wiki/Configuration.md`
   - `docs/wiki/Bridge-RPC.md`
   - 中文文档同步。
3. 运行手册。
   - 如何启动 MiroFish-Offline。
   - 如何设置 `MOSAIC_MIROFISH_URL`。
   - 常见错误：
     - Neo4j auth 失败
     - Ollama 模型未拉取
     - GPU 不可用
     - report timeout
     - AGPL 外部服务边界说明

验收：

- 新用户按文档能跑通旁路：`pnpm dev mirofish train --engine offline --fake-llm --dry-run`。
- 不传 `--engine offline` 时，CLI 仍按默认 `montecarlo` 跑通。
- CLI 错误信息能定位是 MOSAIC bridge、Offline backend、Neo4j 还是 Ollama。

## Phase 6：质量闸门与灰度

目标：确认 Offline 旁路带来可用信息增益，再决定是否扩大使用范围；默认引擎仍保持 `montecarlo`。

任务：

1. 结构质量对比。
   - 对比 `montecarlo`、`swarm`、`offline`：
     - 是否改变 regime 排序。
     - 是否产生更明确 tail risk。
     - 是否与 agent debate 的已知风险一致。
2. 回测/前向验证。
   - 使用历史 `as_of_date` seed。
   - 禁止未来数据。
   - 比较 5/10/20 trading days 后 CSI300/ETF basket 方向。
3. 灰度策略。
   - 默认仍关闭：`default_config.py` 保持 `mirofish.engine = "montecarlo"`。
   - CLI help 把 `offline` 描述为 opt-in real-engine旁路。
   - Dashboard 可读取 Offline context / runs，但不要求默认展示。
   - CIO context injection 仅 opt-in。
   - paper trading 不直接消费 Offline 分数，除非后续有真实 forward-return 验证和单独开关。
4. 回滚策略。
   - 因为 Offline 是旁路，回滚就是不传 `--engine offline` 或把配置恢复为 `montecarlo`。
   - 回滚不删除 Offline 历史账本；history 中保留 `engine` 字段区分来源。

验收：

- 至少 10 个历史日期 smoke。
- `offline` 相比 `montecarlo` 在 context quality 上有人工可解释增益。
- 真实方向验证未显著恶化。
- 成本和耗时可接受。
- 默认 engine 仍为 `montecarlo`，Offline 只在显式配置或 CLI 参数下运行。

## 任务清单

### P0 本地服务

- [ ] 克隆 `haphap/MiroFish-Offline` 并记录 SHA。
- [ ] 准备 `.env`。
- [ ] 启动 Docker Compose。
- [ ] 拉 Ollama LLM 和 embedding 模型。
- [ ] 跑 `/health`。
- [ ] 手工跑一次小 seed workflow。
- [ ] 写入 live smoke 记录。

### P1 配置与 engine

- [ ] Python bridge 支持 `offline` engine。
- [ ] TS bridge/CLI 支持 `offline` engine。
- [ ] 保持 `montecarlo` 默认不变。
- [ ] 补充 bad-param tests。
- [ ] 更新 CLI help。

### P2 完整 pipeline

- [ ] Adapter 增加 `/api/simulation/start`。
- [ ] Adapter 增加 run-status polling。
- [ ] Adapter 支持 max rounds。
- [ ] Bridge / TS types / trainer / CLI 透传 max rounds。
- [ ] Adapter 支持 skip-start 兼容模式。
- [ ] fake transport 覆盖成功、失败、超时。

### P3 seed 增强

- [ ] 定义 `MirofishSeed`。
- [ ] 生成 A 股市场 seed text。
- [ ] multipart 上传 seed file。
- [ ] 单测 anti-lookahead。
- [ ] 后续接 daily-cycle 摘要。

### P4 report parser

- [ ] 定义 `ReportSignal`。
- [ ] 实现 markdown parser。
- [ ] 场景映射增加 lossy metadata。
- [ ] `detail_json` 保存 report metadata。
- [ ] context 注入只使用摘要。
- [ ] 允许 `runMirofishTraining` 记录 Offline 隔离训练账本。
- [ ] 阻止 Offline lossy scenario 写入 JANUS / Darwinian / paper 权重路径。

### P5 文档与 CLI

- [ ] 增加 `--max-rounds`。
- [ ] 更新英文 CLI docs。
- [ ] 更新中文 CLI docs。
- [ ] 更新 Configuration docs。
- [ ] 更新 Bridge RPC docs。
- [ ] 编写故障排查说明。

### P6 验证与灰度

- [ ] 10 个历史日期 smoke。
- [ ] 对比 `montecarlo/swarm/offline` 输出差异。
- [ ] 记录耗时、成本、失败率。
- [ ] 决定是否允许 dashboard 展示 Offline context/runs。
- [ ] 保持默认 engine 为 `montecarlo`。
- [ ] CIO context injection 保持 opt-in。

## 测试计划

Python（仓库统一用 `pytest` —— 它同时收集 `unittest.TestCase` 和 pytest 风格用例；
注意 `test_mirofish.py` 是 pytest 风格的裸 `def test_*`，`python -m unittest` **不会**
收集到它，所以这里一律用 pytest，和 CI（`uv run python -m pytest tests/ -q`）保持一致）：

- `uv run python -m pytest tests/test_mirofish_oasis.py -q`
- `uv run python -m pytest tests/test_bridge_mirofish.py tests/test_mirofish_context.py -q`
- `uv run python -m pytest tests/test_mirofish.py tests/test_mirofish_path_aware.py -q`
- `git diff --check`

TypeScript：

- `pnpm typecheck`
- `pnpm lint`
- `pnpm test -- mirofish_trainer`
- `pnpm test -- mirofish_context_inject`

Live smoke：

```bash
export MOSAIC_MIROFISH_URL=http://localhost:5001
export MOSAIC_MIROFISH_MAX_ROUNDS=5
pnpm dev mirofish generate --engine offline --days 30 --max-rounds 5 --print
pnpm dev mirofish train --engine offline --fake-llm --dry-run
pnpm dev mirofish generate --days 30 --print  # default montecarlo baseline
```

## 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| Offline 服务慢 | CLI / bridge 超时 | 默认小 `max_rounds`，poll timeout 可配置 |
| 本地模型质量不足 | report 噪声大 | 推荐 `qwen2.5:14b/32b`，记录模型名到 detail |
| 报告不是价格预测 | scoring 语义偏移 | 标记 `mapping_lossy`，允许隔离训练账本，禁止真实权重/交易路径直接消费 |
| AGPL 许可证 | 不能内嵌源码 | 外部服务调用，不 vendor |
| Neo4j/Ollama 不稳定 | 用户难排错 | 明确错误分类和运行手册 |
| 历史回测偷看未来 | 结果失真 | seed 必须带 `as_of_date`，context query 使用 anti-lookahead |

## 不做事项

- 不把 `MiroFish-Offline` 源码复制进本仓库。
- 不让 Offline 输出直接改 JANUS/Darwinian/paper 权重，除非后续单独验证并加开关。
- 不默认开启 CIO prompt injection。
- 不把 report markdown 全量塞入 agent prompt。
- 不承诺 Offline price path 是真实市场路径预测。

## 建议执行顺序

第一轮只做 P1 + P2 的最小闭环：

1. `engine=offline` 旁路 adapter 接入，默认 `montecarlo` 保留。
2. Adapter 增加 `simulation/start` 和 run-status polling。
3. `--max-rounds` 从 CLI 透传到 adapter。
4. fake transport tests。
5. live smoke。

第二轮做 P3 + P4：

1. seed 增强。
2. report parser。
3. richer context。

第三轮做 P5 + P6：

1. 文档和 CLI polish。
2. 历史日期验证。
3. Offline 保持显式 opt-in。
4. Dashboard 展示和 CIO injection 均单独决策。
