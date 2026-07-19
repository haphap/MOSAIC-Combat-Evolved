# 贡献指南

## 分支命名

- 人工:`phase-x-<feature>` / `fix-<scope>` / `chore-<scope>`。
- Autoresearch 自动分支:`cohort/{name}/auto/{agent}/{YYYY-MM-DD}`。

不要直接推 `main`;开 PR。

## 验证矩阵(提 PR 前全绿)

```bash
# TypeScript(在 mosaic-ts/ 下)
pnpm typecheck && pnpm lint && pnpm test
# Python(仓库根)
ruff check mosaic tests && python -m pytest -q
```

CI 在 `.github/workflows/ci.yml` 跑同样内容(一个 Python lane + 一个 TS lane)。TS lane 会建一个仓库根 `.venv` 装 bridge 依赖,使 live-sidecar 测试能 spawn 桥。

注意:
- `ruff` 排除 vendored 采集器(`mosaic/dataflows/collectors`)—— 第三方,逐字保留。
- 单体 `python -m pytest tests/ -q` 会串行执行 2,000 多个测试；请先用
  `--durations=80 --durations-min=0.1` profile，并对照 CI 的 RKE 单文件拆分。
  Registry fixture 会排除全部 private prefix，并在文件系统支持时使用
  copy-on-write clone；不得复制完整 operator registry，默认也不得触发 live FRED。
- 2026 年 7 月的一次本地 profile 显示,主要拖慢点是 `tests/test_rke_cli.py`:一个 CLI refresh contract 测试耗时 274s,多个 master-plan/promotion/review-progress CLI 用例耗时 22-89s。现在这些测试会 stub 掉本断言无关的深层 refresh/review-progress builder;本地跑该文件应约 10s 完成。accepted-import 测试也会 stub 掉无关的下游 report-bundle 重写;剩余已知本地热点是 `tests/test_rke_operator_handoff.py`,其中深层 handoff 用例仍会跑真实 manual review progress builder。
- `tests/test_rke_tushare_reports.py` 过去会复制包含 private ignored 文件的 166 MB registry 九次,并依赖 clean CI 中不存在的 review 文件。现在它只复制 public registry fixture 并使用 synthetic review rows;27 个测试应约 3 秒完成,且 clean checkout 与 operator checkout 结果一致。
- 部分测试由 `_HAS_QLIB` / 依赖存在性 guard,当某可选 extra(如 `pyqlib`、`bcrypt`、`numpy`)缺失时干净跳过,使套件可 hermetic 运行。
- CI 也会运行 prompt leak guard。它会阻止 autoresearch/private prompt 产物进入项目 repo,但它是 provenance-based 检查,不对普通 prompt 正文做内容分类。
- Domain control catalog 只属于 runtime contract。TypeScript、schema、calculator 和
  visibility filter 必须一致，但 catalog card、阈值和 mutation metadata 绝不能进入
  bundled/private 的模型可见 prompt。它们不是 KNOT mutation target；任何改动都要走
  显式 contract release，并创建新的 Darwinian/KNOT track identity。
- Decision 层 control 改动必须拥有独立合同、metric policy、PIT 测试和 release
  migration，不能混入私有 prompt behavior delta。
- Domain source binding 按 coverage 区分:`direct_tool` / `derived_proxy`
  card 需要匹配的 evidence dependency;`runtime_state` card 需要 runtime
  input source。
- Domain card metric 必须闭包到 evaluation metric registry:
  `evaluation_metric`、`rollback_condition.metric` 和 `secondary_metrics`
  都要已注册、horizon 兼容,且 rollback unit 要匹配 metric unit；
  `rollback_condition.worse_by` 必须非负。Registry entry
  还必须包含可用于 rollback 的 direction、value convention、baseline、PIT 和
  exclusion policy 字段，并覆盖 missing/stale input、source error、lookahead
  risk 和 incomplete fill。signed-return metric 必须是 higher-is-better，loss/cost
  convention 必须是 lower-is-better。
- KNOT mutation 只能改变私有 cohort-behavior 块内的推理顺序、反证检查或表达策略。
- CIO pre-decision card 不得消费 `candidate_target_state`;这个 source 只能由
  CRO/execution 或下游 validator 依赖 CIO 本轮 proposal 时使用。
- Layer 4 必须保持 proposal/freeze/CRO/execution/final 的 canonical 顺序,显式传递上一轮 final target,并让 CIO final 复用同一个 frozen prompt/source family。
- `conflicting_evidence` confidence cap 在 direction-adapter registry 可用前
  由 prompt check fail-closed。不要只靠 prose conflict rule 把这个 trigger 加进
  production knobs。
- Runtime confidence cap 会在 clamp 后对 structured 与 fallback output 都重新跑
  agent schema 校验。校验视图只移除 runtime-owned 顶层
  `verified_knob_audit`;返回 envelope 仍保留该 audit,用于样本排除和 UI 展示。
- Agent output 不得在 `declared_knob_influence_ids` 中列出已禁用的
  domain card id;runtime 会在 scoped source resolution 后拒绝这些 id。
- JSON tool output 中的 fallback metadata 必须写入 `toolStatuses.fallback`
  和 `toolStatuses.as_of`;重复调用命中 per-agent cache 时也必须保留这些字段。
- 完整 claim/evidence rollout 还必须提供 runtime-owned result fingerprint、evidence id、structured extractor 可见的 evidence catalog,并让每个 recommendation/action 带 claim refs。只有 graph schema 或 validator 不算完成。
- 当 PR 修改 `prompts/mosaic/**` 且你运行 private prompt repo 时,在 `mosaic-ts/` 下设置 `MOSAIC_PROMPTS_REPO` 后运行 `pnpm prompt:drift -- --base-ref origin/main`(`MOSAIC_PRIVATE_PROMPT_REPO` 仍作为兼容别名)。检查是 staleness-aware 的:只报告尚未与变更后 baseline **内容**对齐的 override(对齐状态按路径记录在 private repo 的 `prompts/mosaic/.baseline-sync.json`)。把 baseline 的工具/schema/contract 变更并入某个被标记的 override 后,用 `-- --mark-synced` 重新运行以记录其已对齐 —— 之后直到该 baseline 内容再次变化前都不再告警。
- scheduled operator check 先用已知安全的 `baseline_ref` 初始化 `data/prompt-drift-state.json`,再在 `mosaic-ts/` 下设置 `MOSAIC_PROMPTS_REPO` 并运行 `pnpm prompt:drift:scheduled`。检查通过时 state 会前进;优先用 `-- --mark-synced` 精确确认具体 override,或用 `-- --accept` 一次性把 state 推进到当前所有 findings 之后。

## 约定

- 每个 PR 聚焦单一关注点;描述含改了什么 / 怎么测的 / 已知限制。
- 新能力应**可选开关(opt-in,默认关)**且保持默认行为向后兼容 —— 参考 MiroFish 开关与 autoresearch git-push 标志的模式。
- 写最小化、直接满足需求的代码;匹配既有风格与已用库。
- 工具边界仅字符串/JSON(无跨语言 DataFrame 传输)。

## 各部分位置

仓库地图见[架构](Architecture.md)。权威设计 + 阶段日志是 `docs/plans/` 下的 [`mosaic-tsplan.md`](../../plans/mosaic-tsplan.md)。
